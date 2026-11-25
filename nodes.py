"""H3 Chain: one-click, any-length MiniMax H3 videos on a 12 GB card.

Same idea as the LTX-2.5 Lip-Sync Chain: every render part is its own ComfyUI job. A Step node saves the
part, then re-queues the workflow for the next part, so memory is freed between parts and the length of the
song does not matter. Unlike the H3 Director's own loop:

- every scene is its own Director plan, so a scene change is a clean cut at the start of a part
  (no "late_change": the pinned frames of the previous part never hold a new scene back);
- inside a scene the parts continue exactly like the Director (22 pinned frames + the last second of sound),
  because the Director's own nodes do the conditioning and the joining;
- the song (or dialogue track) is locked: every scene gets its slice of it, and the final video carries the
  original track, so the lip sync stays on time over the whole song.

Nodes: H3 Chain: State (plan, session, re-queue state), H3 Chain: Step (save, build scene videos, re-queue,
final video). Scene changes come from H3 Chain: Scene Cuts (waveform) or from scene_seconds.
"""
import copy
import json
import logging
import math
import os
import re
import sys
import threading
import time
import urllib.request
import wave
from datetime import datetime
from fractions import Fraction

import av
import numpy as np
import torch

import folder_paths
from server import PromptServer

CHAIN_TYPE = "H3_CHAIN"
STATE_NODE_CLASS = "H3ChainState"
CHAINS_SUBDIR = "H3Chains"           # output/H3Chains/<session>/
INPUT_SUBDIR = "h3chain"             # input/h3chain/<session>/scene_XX.wav (the Director reads cards from input/)
AUDIO_CTX = "ctx_h3chain_audio"
FPS = 24
LOG = logging.getLogger("H3Chain")

AUDIO_CONTENT = ["singing", "music", "dialogue", "voice"]
LANE_MODES = ["lock", "copy", "ref"]


# --------------------------------------------------------------------------------------------- helpers

def _director_module(suffix):
    """A module of the already-loaded MiniMax H3 Director pack (never import a second copy: its classes
    must be the same objects the Director checks against)."""
    for module in list(sys.modules.values()):
        path = (getattr(module, "__file__", None) or "").replace("\\", "/")
        if path.endswith(suffix) and "minimaxh3-director" in path.lower():
            return module
    raise RuntimeError("H3 Chain needs the MiniMax H3 Director node pack (minimaxh3-director); module %s not found" % suffix)


def _first(value):
    return value[0] if isinstance(value, list) else value


def _session_dir(session):
    path = os.path.join(folder_paths.get_output_directory(), CHAINS_SUBDIR, session)
    os.makedirs(path, exist_ok=True)
    return path


def _new_session():
    root = os.path.join(folder_paths.get_output_directory(), CHAINS_SUBDIR)
    os.makedirs(root, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    taken = {name for name in os.listdir(root)}
    k = 1
    while f"{day}_v{k:02d}" in taken:
        k += 1
    return f"{day}_v{k:02d}"


def _write_wav(path, waveform, rate):
    """waveform: [channels, samples] float tensor/array in -1..1."""
    data = np.asarray(waveform.detach().cpu().float() if torch.is_tensor(waveform) else waveform, dtype=np.float32)
    data = np.clip(data, -1.0, 1.0)
    pcm = (data.T * 32767.0).astype("<i2")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as out:
        out.setnchannels(data.shape[0])
        out.setsampwidth(2)
        out.setframerate(int(rate))
        out.writeframes(pcm.tobytes())


def _read_wav(path):
    with wave.open(path, "rb") as src:
        channels, rate, frames = src.getnchannels(), src.getframerate(), src.getnframes()
        pcm = np.frombuffer(src.readframes(frames), dtype="<i2").astype(np.float32) / 32767.0
    return pcm.reshape(-1, channels).T, rate


def parse_cuts(text):
    cuts = []
    for token in re.split(r"[,\s]+", text or ""):
        if not token:
            continue
        try:
            cuts.append(float(token))
        except ValueError:
            LOG.warning("[H3 Chain] ignoring scene cut %r", token)
    return sorted(set(cuts))


def parse_scene_texts(text):
    """Scene descriptions: blocks separated by a blank line or a line '---'. Used in order, then cycled."""
    blocks, current = [], []
    for line in (text or "").splitlines():
        if not line.strip() or line.strip() == "---":
            if current:
                blocks.append(" ".join(current).strip())
                current = []
            continue
        current.append(line.strip())
    if current:
        blocks.append(" ".join(current).strip())
    return blocks or ["@Singer performs to the song. Medium shot, the camera moves slowly."]


def split_scenes(total_s, cuts, scene_seconds, min_scene_s=4.5):
    """Rough scene spans (seconds) before snapping to H3's frame grid."""
    edges = [c for c in cuts if 0.0 < c < total_s]
    if not edges and scene_seconds > 0:
        edges = [scene_seconds * k for k in range(1, int(math.ceil(total_s / scene_seconds))) if scene_seconds * k < total_s]
    bounds = [0.0] + edges + [total_s]
    spans = [[bounds[i], bounds[i + 1]] for i in range(len(bounds) - 1)]
    merged = []
    for span in spans:  # a scene shorter than min_scene_s (H3 renders at least ~4.46 s) joins the one before it
        if merged and span[1] - span[0] < min_scene_s:
            merged[-1][1] = span[1]
        else:
            merged.append(span)
    if len(merged) > 1 and merged[0][1] - merged[0][0] < min_scene_s:
        merged[1][0] = 0.0
        merged.pop(0)
    return merged


def plan_spans(song_s, total_s, cuts, scene_seconds, tail_scene=False, min_scene_s=4.5):
    """Scene spans for a song of song_s seconds followed by (total_s - song_s) s of added silence.
    tail_scene=True gives the silence its own scene, cut exactly where the song ends (only if it is long enough for
    H3; otherwise the silence just extends the last scene). Returns (spans, tail_scene_used)."""
    tail = total_s - song_s
    if tail_scene and tail >= min_scene_s and song_s >= 1.0:
        return split_scenes(song_s, cuts, scene_seconds, min_scene_s) + [[song_s, total_s]], True
    return split_scenes(total_s, cuts, scene_seconds, min_scene_s), False


def shots_document(length_s, text, look, lane_mode, spoken=()):
    return json.dumps({
        "format": "h3-director-shots", "schema_version": 1,
        "shots": [{"id": "s1", "start": 0, "end": round(length_s, 4), "text": text, "media": [], "spoken": list(spoken),
                   "locked_fields": [], "draft": None}],
        "audio": [{"schema_version": 1, "id": "song", "context_id": AUDIO_CTX, "start": 0, "end": round(length_s, 4),
                   "offset": 0.0, "mode": lane_mode, "lane": "l1"}],
        "audio_lanes": ["l1"], "look": look,
    }, ensure_ascii=False)


def parse_spoken(text):
    """The `spoken` input: JSON, one list of lines per scene (or empty)."""
    if not (text or "").strip():
        return []
    data = json.loads(text)
    if not isinstance(data, list) or not all(isinstance(x, list) for x in data):
        raise ValueError("spoken: expected a JSON list with one list of lines per scene")
    return data


def first_part_lines(lines_per_scene, k, parts):
    """Spoken lines of scene k for the Director. It gives a shot's lines only to the part the shot starts in, so only the
    lines that start inside the first part (0.5 s before its end at the latest) are sent; the scene text's time beats say
    who talks in the later parts."""
    if k >= len(lines_per_scene):
        return []
    limit = (parts[0] / FPS - 0.5) if len(parts) > 1 else float("inf")
    keep = ("text", "speaker_id", "voice", "language", "delivery")
    out = []
    for line in lines_per_scene[k]:
        if float(line.get("start", 0.0)) < limit and str(line.get("text", "")).strip():
            entry = {"schema_version": 1, "delivery": "says"}
            entry.update({key: str(line[key]) for key in keep if key in line})
            out.append(entry)
    return out


def snap_length(length_s, chunk_seconds, width, height):
    """The length the Director really renders for a scene of length_s (H3's frame grid), in frames."""
    preview = _director_module("ng/core/preview.py")
    director = {"idea": "scene", "shots": shots_document(length_s, "A scene.", "", "lock"), "project_seconds": float(length_s),
                "chunk_seconds": float(chunk_seconds), "width": int(width), "height": int(height), "mode": "ref2va",
                "continuity": "video_audio", "pin_frames": "22", "soundscape": "N/A", "music": "N/A", "prepend_text": "",
                "style": "None", "prompt_override": "", "output": "video"}
    result = preview.plan_preview({"director": director, "contexts": []})
    if not result.get("ok"):
        director["mode"] = "auto"
        result = preview.plan_preview({"director": director, "contexts": []})
    if not result.get("ok"):
        raise RuntimeError("H3 Chain could not plan a %.2fs scene: %s" % (length_s, result.get("error")))
    return int(result["total_frames"]), [c["sampled_frames"] for c in result["chunks"]]


def _save_latent(path, latent):
    samples = latent["samples"]
    payload = {"nested": hasattr(samples, "tensors")}
    payload["tensors"] = [t.detach().cpu() for t in samples.tensors] if payload["nested"] else [samples.detach().cpu()]
    payload["extra"] = {k: v.detach().cpu() for k, v in latent.items() if k != "samples" and torch.is_tensor(v)}
    torch.save(payload, path)


def _load_latent(path):
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if payload["nested"]:
        from comfy.nested_tensor import NestedTensor
        samples = NestedTensor(payload["tensors"])
    else:
        samples = payload["tensors"][0]
    return {"samples": samples, **payload.get("extra", {})}


# --------------------------------------------------------------------------------------------- State

class H3ChainState:
    """Plans the session (scenes on H3's frame grid, one audio slice per scene) and tells this job which
    scene and render part to make. The Step node re-queues the workflow with chain_state filled in."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {"tooltip": "The whole song (or dialogue track). Each scene gets its slice, locked into the Director's audio lane"}),
                "scenes": ("STRING", {"multiline": True, "default":
                    "@Singer sings on a small stage, warm spotlight. Medium shot, the camera slowly pushes in.\n\n"
                    "@Singer sings close to the camera, soft backlight. Close-up, slow orbit.",
                    "tooltip": "Scene texts, one block per scene (separate with a blank line or ---). Repeats from the top if there are more scenes. Call a character with @Name (the image card's name)"}),
                "look": ("STRING", {"multiline": True, "default": "",
                                    "tooltip": "Look shared by all scenes (the Director's look)"}),
                "scene_cuts": ("STRING", {"default": "", "tooltip": "Scene cut times in seconds, comma separated. Connect H3 Chain: Scene Cuts to place them on the waveform. Empty = every scene_seconds"}),
                "scene_seconds": ("FLOAT", {"default": 10.0, "min": 0.0, "max": 600.0, "step": 0.5,
                                            "tooltip": "Scene length in seconds when scene_cuts is empty"}),
                "chunk_seconds": ("FLOAT", {"default": 5.0, "min": 3.0, "max": 10.0, "step": 0.5,
                                            "tooltip": "Length of one job (render part). 5 s works on 12 GB up to 1056x576"}),
                "width": ("INT", {"default": 1056, "min": 256, "max": 2048, "step": 32,
                                  "tooltip": "Same as the Director's width (used to plan the scene lengths)"}),
                "height": ("INT", {"default": 576, "min": 256, "max": 2048, "step": 32}),
                "length_mode": (["all", "seconds"], {"default": "all", "tooltip": "all = to the end of the audio / seconds = only length_seconds from audio_start_sec"}),
                "length_seconds": ("FLOAT", {"default": 15.0, "min": 1.0, "max": 3600.0, "step": 0.5}),
                "audio_start_sec": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 3600.0, "step": 0.1}),
                "audio_content": (AUDIO_CONTENT, {"default": "singing", "tooltip": "singing for songs, dialogue for speech"}),
                "lane_mode": (LANE_MODES, {"default": "lock", "tooltip": "lock = use the audio as it is and sync the lips to it (recommended)"}),
                "speaker": ("STRING", {"default": "", "tooltip": "context_id of the singing / speaking character's image card (e.g. ctx_singer). Empty = none"}),
                "base_seed": ("INT", {"default": 767425881343200, "min": 0, "max": 0xffffffffffffffff,
                                 "tooltip": "Scene k uses seed + 1000*k (the Director adds 1 per part)"}),
                "redo_session": ("STRING", {"default": "", "tooltip": "Session to redo (e.g. 20261115_v01)"}),
                "redo_scenes": ("STRING", {"default": "", "tooltip": "Scene numbers to redo (e.g. 2,5). Empty = a new session"}),
                "chain_iter": ("INT", {"default": 0, "min": 0, "max": 100000, "tooltip": "Set by the chain (leave it alone)"}),
                "chain_state": ("STRING", {"default": "", "tooltip": "Set by the chain (leave it alone). Empty = start a new session"}),
            },
            "optional": {
                "scene_crossfade": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 2.0, "step": 0.25,
                                              "tooltip": "Dissolve between scenes in seconds (0 = hard cut). Each scene is rendered this much longer and overlapped, so the length and the lip sync do not change"}),
                "final_track": ("AUDIO", {"tooltip": "Audio for final.mp4 (final_audio = original). If connected, H3 hears `audio` (e.g. a bass-boosted mix) "
                                                     "and final.mp4 gets this track (the original song). Same length and start as `audio`"}),
                "tail_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 30.0, "step": 0.5,
                                           "tooltip": "Seconds of silence added after the audio; the video goes on that long (an ending). 0 = none"}),
                "tail_scene": ("STRING", {"default": "", "multiline": True,
                                          "tooltip": "Text of an ending scene for the silence only (e.g. the song ends, the lights dim, the camera slowly pulls back). "
                                                     "Cuts exactly at the end of the audio and makes one scene from this text (tail_seconds 5 s or more). "
                                                     "Empty = the last scene just runs longer"}),
                "spoken": ("STRING", {"default": "", "multiline": True,
                                      "tooltip": "Dialogue lines per scene as JSON (written by tools/new_story.py): a list with one list per scene of "
                                                 "{text, speaker_id, language, voice, start}. start = seconds from the scene start. The lines that "
                                                 "start in a scene's first render part go to the Director as spoken lines (it gives the later "
                                                 "parts of a shot none). Empty = no spoken lines (songs)"}),
            },
        }

    RETURN_TYPES = ("STRING", "FLOAT", "INT", "INT", "LATENT", "NG_CONTEXT", CHAIN_TYPE, "STRING")
    RETURN_NAMES = ("shots", "project_seconds", "chunk_index", "seed", "previous", "audio_context", "chain", "info")
    FUNCTION = "run"
    CATEGORY = "H3 Chain"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")  # every Run starts or continues a chain; never reuse a cached plan

    def run(self, audio, scenes, look, scene_cuts, scene_seconds, chunk_seconds, width, height, length_mode, length_seconds,
            audio_start_sec, audio_content, lane_mode, speaker, base_seed, redo_session, redo_scenes, chain_iter, chain_state,
            scene_crossfade=0.5, final_track=None, tail_seconds=0.0, tail_scene="", spoken=""):
        state = json.loads(chain_state) if chain_state.strip() else {}
        if state:
            session = state["session"]
            plan = json.load(open(os.path.join(_session_dir(session), "plan.json"), encoding="utf-8"))
        elif redo_scenes.strip():
            session = redo_session.strip()
            if not session:
                raise ValueError("redo_scenes needs redo_session (the output/H3Chains folder name)")
            plan = json.load(open(os.path.join(_session_dir(session), "plan.json"), encoding="utf-8"))
            order = sorted({int(t) - 1 for t in re.split(r"[,\s]+", redo_scenes) if t.strip()})
            bad = [k + 1 for k in order if not 0 <= k < len(plan["scenes"])]
            if bad:
                raise ValueError("redo_scenes %s: the session has %d scenes" % (bad, len(plan["scenes"])))
            state = {"session": session, "order": order, "pos": 0, "chunk": 0, "redo": True}
            self._archive(session, order)
        else:
            session = _new_session()
            plan = self._plan(session, audio, scenes, look, scene_cuts, scene_seconds, chunk_seconds, width, height,
                              length_mode, length_seconds, audio_start_sec, audio_content, lane_mode, speaker, base_seed,
                              scene_crossfade, final_track, tail_seconds, tail_scene, spoken)
            state = {"session": session, "order": list(range(len(plan["scenes"]))), "pos": 0, "chunk": 0, "redo": False}

        scene_index = state["order"][state["pos"]]
        scene = plan["scenes"][scene_index]
        chunk = int(state["chunk"])
        sdir = _session_dir(session)
        previous = None
        if chunk > 0:
            previous = _load_latent(os.path.join(sdir, "scene_%03d" % (scene_index + 1), "part_%03d.pt" % chunk))

        context_build = _director_module("ng/core/context_build.py")
        widgets = dict(audio=scene["audio_file"], name="Song" if plan["audio_content"] != "dialogue" else "Dialogue",
                       description="The track of this scene, kept exactly; the lips follow it.",
                       content=plan["audio_content"], usage="lock" if plan["lane_mode"] == "lock" else (
                           "copy" if plan["lane_mode"] == "copy" else "sound_reference"),
                       preserve="high", speaker=plan["speaker"], context_id=AUDIO_CTX, color="#d095ce")
        audio_context = context_build.item_from_widgets("audio", widgets, scene["seconds"])

        chain = {"session": session, "scene_index": scene_index, "chunk": chunk, "order": state["order"], "pos": state["pos"],
                 "redo": state["redo"], "scene_count": len(plan["scenes"]), "parts": scene["parts"]}
        info = "session %s | scene %d/%d (%.2f-%.2fs) | part %d/%d%s" % (
            session, scene_index + 1, len(plan["scenes"]), scene["start"], scene["end"], chunk + 1, len(scene["parts"]),
            " | REDO" if state["redo"] else "")
        LOG.info("[H3 Chain] %s", info)
        scene_seed = (int(plan["seed"]) + 1000 * scene_index) % (2 ** 64)
        return (scene["shots"], float(scene["seconds"]), chunk, scene_seed, previous, audio_context, chain, info)

    # -- planning ------------------------------------------------------------------------------------

    def _plan(self, session, audio, scenes, look, scene_cuts, scene_seconds, chunk_seconds, width, height, length_mode,
              length_seconds, audio_start_sec, audio_content, lane_mode, speaker, seed, scene_crossfade=0.0, final_track=None, tail_seconds=0.0, tail_scene="",
              spoken=""):
        rate = int(audio["sample_rate"])
        wave_all = audio["waveform"][0].float()  # [channels, samples]
        s0 = int(round(audio_start_sec * rate))
        song = wave_all[:, s0:]
        song_s = song.shape[-1] / rate
        tail_s = max(0.0, float(tail_seconds or 0.0))
        if tail_s > 0:   # silence after the song: H3 hears it (lips close), final.mp4 keeps it
            song = torch.nn.functional.pad(song, (0, int(round(tail_s * rate))))
        total = song.shape[-1] / rate
        if length_mode == "seconds":
            total = min(total, float(length_seconds))
        if total < 1.0:
            raise ValueError("H3 Chain: less than 1 s of audio after audio_start_sec")
        texts = parse_scene_texts(scenes)
        lines_per_scene = parse_spoken(spoken)
        tail_text = " ".join((tail_scene or "").split())
        spans, tail_used = plan_spans(min(song_s, total), total, parse_cuts(scene_cuts), float(scene_seconds),
                                      bool(tail_text))
        if tail_text and total > song_s and not tail_used:
            LOG.warning("[H3 Chain] tail_scene ignored: the silence (%.2fs) is shorter than one H3 scene (4.5s)",
                        total - song_s)
        if tail_s > 0:
            LOG.info("[H3 Chain] %.2fs of silence after the song (%.2fs)%s", tail_s, song_s,
                     " -> its own ending scene" if tail_used else "")

        sdir = _session_dir(session)
        in_dir = os.path.join(folder_paths.get_input_directory(), INPUT_SUBDIR, session)
        overlap = int(round(max(0.0, float(scene_crossfade or 0.0)) * FPS))
        planned, t = [], 0.0
        for k, (a, b) in enumerate(spans):
            last = k == len(spans) - 1
            tail = 0 if last else overlap   # rendered past the scene's end; the next scene dissolves over it
            want = (total - t) if last else (b - t) + tail / FPS
            frames, parts = snap_length(max(want, 0.5), chunk_seconds, width, height)
            # plan again at the snapped length: that is the value the Director gets, and its part split can differ
            frames_again, parts = snap_length(frames / FPS, chunk_seconds, width, height)
            if frames_again != frames:
                LOG.warning("[H3 Chain] scene %d: %d frames re-planned as %d", k + 1, frames, frames_again)
                frames = frames_again
            seconds = frames / FPS
            text = tail_text if (tail_used and last) else texts[k % len(texts)]
            i0, i1 = int(round(t * rate)), int(round((t + seconds) * rate))
            piece = song[:, i0:i1]
            if piece.shape[-1] < i1 - i0:  # the last scene may run past the song: pad with silence
                piece = torch.nn.functional.pad(piece, (0, i1 - i0 - piece.shape[-1]))
            name = "scene_%03d.wav" % (k + 1)
            _write_wav(os.path.join(in_dir, name), piece, rate)
            planned.append({"index": k, "start": round(t, 4), "end": round(t + seconds, 4), "seconds": seconds,
                            "frames": frames, "overlap_frames": tail, "parts": parts, "text": text,
                            "audio_file": "%s/%s/%s" % (INPUT_SUBDIR, session, name),
                            "shots": shots_document(seconds, text, look, lane_mode,
                                                    first_part_lines(lines_per_scene, k, parts))})
            t += (frames - tail) / FPS   # the next scene starts where this one's overlap tail starts
        song_len = int(round(t * rate))
        song_out = song[:, :song_len]
        if final_track is not None:   # H3 heard `audio`; the finished video gets this track
            f_rate = int(final_track["sample_rate"])
            track = final_track["waveform"][0].float()[:, int(round(audio_start_sec * f_rate)):]
            if f_rate != rate:
                import torchaudio
                track = torchaudio.functional.resample(track, f_rate, rate)
            if track.shape[0] != song.shape[0]:
                track = track.mean(0, keepdim=True).expand(song.shape[0], -1)
            song_out = track[:, :song_len]
            LOG.info("[H3 Chain] final.mp4 gets final_track (%.2fs), H3 hears audio", track.shape[-1] / rate)
        if song_out.shape[-1] < song_len:
            song_out = torch.nn.functional.pad(song_out, (0, song_len - song_out.shape[-1]))
        _write_wav(os.path.join(sdir, "song.wav"), song_out, rate)
        plan = {"session": session, "created": datetime.now().isoformat(timespec="seconds"), "fps": FPS,
                "total_seconds": t, "audio_start_sec": audio_start_sec, "audio_content": audio_content, "lane_mode": lane_mode,
                "speaker": speaker, "seed": int(seed), "chunk_seconds": chunk_seconds, "width": width, "height": height,
                "look": look, "scene_crossfade_frames": overlap, "song_seconds": round(song_s, 4),
                "tail_seconds": tail_s, "tail_scene": tail_used, "scenes": planned}
        with open(os.path.join(sdir, "plan.json"), "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=1)
        with open(os.path.join(sdir, "scenes.txt"), "w", encoding="utf-8") as f:
            for s in planned:
                f.write("scene %d  %.2f-%.2fs  (%d parts: %s frames)\n%s\n\n" % (
                    s["index"] + 1, s["start"], s["end"], len(s["parts"]), s["parts"], s["text"]))
        LOG.info("[H3 Chain] new session %s: %.2fs, %d scenes, %d parts", session, t, len(planned),
                 sum(len(s["parts"]) for s in planned))
        return plan

    def _archive(self, session, order):
        sdir = _session_dir(session)
        stamp = datetime.now().strftime("%H%M%S")
        bdir = os.path.join(sdir, "_old", stamp)
        for k in order:
            for name in ("scene_%03d.mp4" % (k + 1), "scene_%03d" % (k + 1)):
                src = os.path.join(sdir, name)
                if os.path.exists(src):
                    os.makedirs(bdir, exist_ok=True)
                    os.replace(src, os.path.join(bdir, name))


# --------------------------------------------------------------------------------------------- Step

class H3ChainStep:
    """Saves the part's latent. After a scene's last part it writes the scene video with the Director's own
    join (pinned frames removed, locked sound restored). Then it re-queues the workflow for the next part or
    scene; after the last scene it writes final.mp4 with the original track."""

    INPUT_IS_LIST = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "latent": ("LATENT", {"tooltip": "SamplerCustomAdvanced output (the AV latent of the whole part)"}),
                "chunks": ("NG_CHUNK", {"tooltip": "chunks from the H3 Director"}),
                "chain": (CHAIN_TYPE,),
                "vae": ("VAE",),
                "audio_vae": ("VAE",),
                "final_name": ("STRING", {"default": "final"}),
                "final_audio": (["original", "generated"], {"default": "original",
                                "tooltip": "original = put the input audio back on as it is (recommended for lip sync)"}),
                "final_crf": ("INT", {"default": 16, "min": 0, "max": 51}),
                "auto_continue": ("BOOLEAN", {"default": True, "tooltip": "Off = do not queue the next part (for testing)"}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("info",)
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = "H3 Chain"

    def run(self, latent, chunks, chain, vae, audio_vae, final_name, final_audio, final_crf, auto_continue,
            prompt=None, extra_pnginfo=None, unique_id=None):
        chain, latent, vae, audio_vae = _first(chain), _first(latent), _first(vae), _first(audio_vae)
        final_name, final_audio, final_crf, auto_continue = (_first(final_name), _first(final_audio), _first(final_crf),
                                                             _first(auto_continue))
        prompt, extra_pnginfo = _first(prompt), _first(extra_pnginfo)
        chunks = list(chunks)
        session, k, c = chain["session"], chain["scene_index"], chain["chunk"]
        sdir = _session_dir(session)
        scene_dir = os.path.join(sdir, "scene_%03d" % (k + 1))
        os.makedirs(scene_dir, exist_ok=True)
        _save_latent(os.path.join(scene_dir, "part_%03d.pt" % (c + 1)), latent)
        subfolder = "%s/%s" % (CHAINS_SUBDIR, session)

        if c + 1 < len(chunks):
            nxt = {"session": session, "order": chain["order"], "pos": chain["pos"], "chunk": c + 1, "redo": chain["redo"]}
            info = "scene %d part %d/%d done -> next part" % (k + 1, c + 1, len(chunks))
            return self._continue(prompt, extra_pnginfo, nxt, auto_continue, info, None, subfolder)

        scene_path = self._scene_video(chunks, scene_dir, vae, audio_vae, os.path.join(sdir, "scene_%03d.mp4" % (k + 1)))
        files = [{"filename": os.path.basename(scene_path), "subfolder": subfolder, "type": "output"}]
        if chain["pos"] + 1 < len(chain["order"]):
            nxt = {"session": session, "order": chain["order"], "pos": chain["pos"] + 1, "chunk": 0, "redo": chain["redo"]}
            info = "scene %d done (%d parts) -> scene %d" % (k + 1, len(chunks), chain["order"][chain["pos"] + 1] + 1)
            return self._continue(prompt, extra_pnginfo, nxt, auto_continue, info, files, subfolder)

        final_path = self._final(sdir, final_name, final_audio, final_crf)
        info = "all scenes done -> %s/%s" % (subfolder, os.path.basename(final_path))
        if chain["redo"]:
            info += "  (clear redo_scenes on the State node again)"
        LOG.info("[H3 Chain] %s", info)
        files = [{"filename": os.path.basename(final_path), "subfolder": subfolder, "type": "output"}]
        return {"ui": {"images": files, "animated": (True,), "text": [info]}, "result": (info,)}

    # -- helpers -------------------------------------------------------------------------------------

    def _continue(self, prompt, extra_pnginfo, state, auto_continue, info, files, subfolder):
        if auto_continue:
            self._requeue(prompt, extra_pnginfo, state)
        else:
            info += " (auto_continue off)"
        LOG.info("[H3 Chain] %s", info)
        ui = {"text": [info]}
        if files:
            ui.update({"images": files, "animated": (True,)})
        return {"ui": ui, "result": (info,)}

    def _scene_video(self, chunks, scene_dir, vae, audio_vae, out_path):
        latents = []
        for i in range(len(chunks)):
            path = os.path.join(scene_dir, "part_%03d.pt" % (i + 1))
            if not os.path.isfile(path):
                raise FileNotFoundError("H3 Chain: missing %s" % path)
            latents.append(_load_latent(path))
        chunk_node = _director_module("ng/nodes/chunk_node.py")
        out = chunk_node.NGCollectVideo.execute(latents=latents, chunks=chunks, vae=[vae], audio_vae=[audio_vae],
                                                smooth_source_join=[True])
        args = getattr(out, "args", None) or getattr(out, "result", None) or out
        video = args[0]
        warnings = args[1] if len(args) > 1 else ""
        if warnings:
            LOG.warning("[H3 Chain] %s", warnings)
        if os.path.exists(out_path):
            os.remove(out_path)
        src = getattr(video, "_VideoFromFile__file", None)
        if isinstance(src, str) and os.path.isfile(src):
            os.replace(src, out_path) if os.path.splitdrive(src)[0] == os.path.splitdrive(out_path)[0] else self._copy(src, out_path)
        else:
            video.save_to(out_path)
        LOG.info("[H3 Chain] scene video %s", out_path)
        return out_path

    @staticmethod
    def _copy(src, dst):
        import shutil
        shutil.copyfile(src, dst)

    def _final(self, sdir, final_name, final_audio, crf):
        plan = json.load(open(os.path.join(sdir, "plan.json"), encoding="utf-8"))
        paths = [os.path.join(sdir, "scene_%03d.mp4" % (s["index"] + 1)) for s in plan["scenes"]]
        missing = [os.path.basename(p) for p in paths if not os.path.isfile(p)]
        if missing:
            raise FileNotFoundError("H3 Chain: missing scene videos %s" % missing)
        safe = re.sub(r'[\\/:*?"<>|]+', "_", (final_name or "").strip()) or "final"
        final_path = os.path.join(sdir, safe + ".mp4")
        k = 2
        while os.path.exists(final_path):
            final_path = os.path.join(sdir, "%s_%d.mp4" % (safe, k))
            k += 1

        # each scene but the last was rendered `overlap_frames` past its end; the next scene dissolves over that tail
        overlaps = [int(sc.get("overlap_frames", 0) or 0) for sc in plan["scenes"]]

        # 1) size and length of the scene videos (minus the overlap tails)
        n_frames, size = 0, None
        for p, ov in zip(paths, overlaps):
            with av.open(p) as src:
                vstream = src.streams.video[0]
                size = size or (vstream.codec_context.width, vstream.codec_context.height)
                n_frames += (vstream.frames or sum(1 for _ in src.decode(video=0))) - ov
        video_len = n_frames / FPS

        # 2) the sound: the original track (lip sync stays exact) or the scenes' own sound
        wav, rate = None, None
        if final_audio == "generated":
            pieces = []
            for p, ov in zip(paths, overlaps):
                with av.open(p) as src:
                    if src.streams.audio:
                        rate = src.streams.audio[0].rate
                        blocks = [fr.to_ndarray() for fr in src.decode(audio=0)]
                        if blocks:
                            piece = np.concatenate([b if b.ndim == 2 else b[None] for b in blocks], axis=-1)
                            cut = int(round(ov * rate / FPS))
                            pieces.append(piece[:, :piece.shape[-1] - cut] if cut else piece)
            if pieces:
                wav = np.concatenate(pieces, axis=-1)
        if wav is None:
            wav, rate = _read_wav(os.path.join(sdir, "song.wav"))
        rate = int(rate)
        wav = wav[:, :int(math.ceil(video_len * rate))].astype(np.float32)
        layout = "stereo" if wav.shape[0] >= 2 else "mono"
        wav = np.ascontiguousarray(wav[:2] if layout == "stereo" else wav[:1])

        # 3) both streams are added before anything is written (the MP4 header is written on the first packet)
        with av.open(final_path, mode="w") as out:
            vs = out.add_stream("libx264", rate=Fraction(FPS))
            vs.width, vs.height, vs.pix_fmt = size[0], size[1], "yuv420p"
            vs.options = {"crf": str(crf), "preset": "medium"}
            astream = out.add_stream("aac", rate=rate, layout=layout)
            idx = 0

            def write(rgb):
                nonlocal idx
                f = av.VideoFrame.from_ndarray(rgb, format="rgb24").reformat(format="yuv420p")
                f.pts, f.time_base = idx, Fraction(1, FPS)
                idx += 1
                for packet in vs.encode(f):
                    out.mux(packet)

            tail = []  # the previous scene's overlap frames, waiting for the dissolve
            for p, ov in zip(paths, overlaps):
                with av.open(p) as src:
                    frames = [fr.to_ndarray(format="rgb24") for fr in src.decode(video=0)]
                start = 0
                if tail:
                    n = min(len(tail), len(frames))
                    for i in range(n):  # cross-dissolve: the old scene fades out while the new one fades in
                        a = (i + 1) / (n + 1)
                        write(np.clip(tail[i].astype(np.float32) * (1 - a) + frames[i].astype(np.float32) * a + 0.5, 0, 255).astype(np.uint8))
                    start = n
                end = len(frames) - ov if ov else len(frames)
                for i in range(start, max(start, end)):
                    write(frames[i])
                tail = frames[end:] if ov else []
            for rgb in tail:  # only if the last scene still had a tail (never in a normal plan)
                write(rgb)
            for packet in vs.encode(None):
                out.mux(packet)
            step = 1024 * 32
            for i0 in range(0, wav.shape[-1], step):
                af = av.AudioFrame.from_ndarray(np.ascontiguousarray(wav[:, i0:i0 + step]), format="fltp", layout=layout)
                af.sample_rate, af.pts, af.time_base = rate, i0, Fraction(1, rate)
                for packet in astream.encode(af):
                    out.mux(packet)
            for packet in astream.encode(None):
                out.mux(packet)
        LOG.info("[H3 Chain] final video %s (%d frames, %.2fs)", final_path, idx, idx / FPS)
        return final_path

    def _requeue(self, prompt, extra_pnginfo, state):
        if prompt is None:
            raise RuntimeError("H3 Chain: hidden PROMPT missing; cannot re-queue")
        new_prompt = copy.deepcopy(prompt)
        ids = [k for k, v in new_prompt.items() if v.get("class_type") == STATE_NODE_CLASS]
        if not ids:
            raise RuntimeError("H3 Chain: H3ChainState node not found in the prompt")
        for sid in ids:
            inputs = new_prompt[sid]["inputs"]
            inputs["chain_iter"] = int(inputs.get("chain_iter", 0) or 0) + 1
            inputs["chain_state"] = json.dumps(state)
        server = PromptServer.instance
        body = {"prompt": new_prompt, "extra_data": {}}
        if extra_pnginfo is not None:
            body["extra_data"]["extra_pnginfo"] = extra_pnginfo
        if server.client_id:
            body["client_id"] = server.client_id
        host = server.address if server.address not in (None, "", "0.0.0.0", "::") else "127.0.0.1"
        if ":" in host and not host.startswith("["):
            host = "[%s]" % host
        url = "http://%s:%s/prompt" % (host, server.port)
        data = json.dumps(body).encode("utf-8")

        def post():
            try:
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    resp = json.loads(r.read().decode("utf-8"))
                LOG.info("[H3 Chain] queued next job %s", resp.get("prompt_id"))
            except Exception as e:  # noqa: BLE001
                LOG.error("[H3 Chain] failed to queue the next job: %s", e)

        threading.Timer(0.5, post).start()  # after this prompt has finished


class H3ChainAudioLock:
    """Hold a whole audio track in the audio stream of an H3 AV latent (for the face-refine pass).

    The audio is encoded with the H3 audio VAE and written into the audio stream with a zero noise mask, the same way
    the Director locks a song (`lock_audio_latent`), so the model hears it and the lips follow it. The video half of the
    mask is all ones. Put H3 Per-Frame Denoise after this node; it keeps the audio-side zeros."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"av_latent": ("LATENT",), "audio": ("AUDIO",), "audio_vae": ("VAE",)}}

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("av_latent",)
    FUNCTION = "run"
    CATEGORY = "H3 Chain"

    def run(self, av_latent, audio, audio_vae):
        from comfy_extras import nodes_minimax_h3 as mm
        lock_audio_latent = _director_module("minimax_director.py").lock_audio_latent
        steps = av_latent["samples"].unbind()[1].shape[-1]
        fps = mm.AUDIO_LATENT_FPS
        sr = int(audio["sample_rate"])
        wave_ = audio["waveform"][:1].float()
        if wave_.shape[1] == 1:
            wave_ = wave_.expand(-1, 2, -1)
        wave_ = wave_[:, :2]
        need = int(math.ceil(steps / float(fps) * sr))
        if wave_.shape[-1] < need:
            wave_ = torch.nn.functional.pad(wave_, (0, need - wave_.shape[-1]))
        wave_ = wave_[..., :need].clamp(-1, 1)
        encoded, _ = mm._encode_ref_audio(audio_vae, {"waveform": wave_, "sample_rate": sr})
        LOG.info("[H3 Chain] audio lock: %d audio steps (%.2f s)", steps, steps / float(fps))
        return (lock_audio_latent(av_latent, encoded, [(0.0, steps / float(fps))], fps),)


class H3ChainSceneCuts:
    """Cut-line editor. The waveform UI (web/scene_cuts.js) writes the times into `cuts`; this node normalises the
    text and passes it on to H3 Chain: State's scene_cuts."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "cuts": ("STRING", {"default": "", "multiline": False,
                                    "tooltip": "Scene cut times (seconds, comma separated). Click the waveform above to add them, or type"}),
            },
            "optional": {
                "audio": ("AUDIO", {"tooltip": "Connect the LoadAudio node to see its waveform (the audio itself is not used)"}),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("scene_cuts", "scene_count")
    FUNCTION = "run"
    CATEGORY = "H3 Chain"

    def run(self, cuts, audio=None):
        vals = parse_cuts(cuts)
        return (", ".join("%g" % v for v in vals), len(vals) + 1)


NODE_CLASS_MAPPINGS = {"H3ChainState": H3ChainState, "H3ChainStep": H3ChainStep, "H3ChainAudioLock": H3ChainAudioLock,
                       "H3ChainSceneCuts": H3ChainSceneCuts}
NODE_DISPLAY_NAME_MAPPINGS = {"H3ChainState": "H3 Chain: State", "H3ChainStep": "H3 Chain: Step",
                              "H3ChainSceneCuts": "H3 Chain: Scene Cuts",
                              "H3ChainAudioLock": "H3 Chain: Audio Lock (face refine)"}
