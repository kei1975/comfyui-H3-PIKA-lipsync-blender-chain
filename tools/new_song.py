"""New song -> H3 Chain workflow, from one small song.json.

What it does
  1. copies the song's files (audio, character sheet, face, location) into ComfyUI/input under ASCII names
  2. reads the song length (ffprobe) and plans the cuts: an optional intro scene (0 .. intro_cut, e.g. until the first
     word) and then scene_seconds-long scenes; every scene gets its own text (shots repeat in order, never the intro)
  3. writes the workflow (UI json) into the project folder and into ComfyUI/user/default/workflows
  4. checks the Director part split: part 2 of each scene must keep the framing and the beat-2 motion (no "static")
  5. --submit: converts to API json (live object_info) and queues it; the chain then runs on its own until final.mp4

usage: python new_song.py <project_dir>/song.json [--submit] [--redo <session> "<scenes>"]
  needs: ffprobe on PATH; --submit also needs comfy-cli (pip install comfy-cli) and a running ComfyUI
  env:   COMFYUI_DIR = your ComfyUI folder, COMFYUI_URL = http://127.0.0.1:8188 (default)

song.json (paths relative to the json file; see example_song.json next to this script):
  name, version              "singer", "v1" -> <project_dir>/H3_Chain_<name>_<version>.json
  audio                      source audio file
  character {name, image, description}, face {image, description} (optional), location {name, image, description}
  look, idea, common         look = State look; idea = Director idea; common = text added after every shot's framing
  intro (optional)           text of scene 1 (until intro_cut s); write its camera sentence without move words
  intro_cut                  seconds; scene 1 ends here (0.5 s before the first word works well with crossfade 0.5)
  shots                      [[framing + move, beat 1, beat 2], ...]; framing starts with "The camera frames";
                             beat 2 never says "camera" (the Director keeps it in the second render part)
  scene_seconds (10), width (512), height (896), crossfade (0.5), seed (optional), tail_seconds (0), tail_scene ("")
  turbo ("")                 "lite4" = Pika Flex Turbo lite r32 LoRA + 4 steps; "" = old Pika v1 LoRA + LCM 6 steps
  audio_start (0), length (0) render only audio_start .. audio_start+length s of the song (0 = to the end); join the
                             parts with join_parts.py
  dial (optional)            {"name": "h3_motion", "strength": 0.5}: ComfyUI-Dials Load Dial + Apply Dial between the
                             Pika LoRA (30) and the connector (6); the file goes in models/loras/dials/
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import types
import importlib.util
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "base_workflow.json")          # the H3 Chain song graph (cards 31/32/45, audio 40, State 42)
MIN_SCENE = 4.5

sys.stdout.reconfigure(encoding="utf-8")
COMFY = os.environ.get("COMFYUI_DIR", "")                # your ComfyUI folder (the one with models/, input/, output/)
SERVER = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
if not os.path.isdir(os.path.join(COMFY, "custom_nodes")):
    sys.exit("set COMFYUI_DIR to your ComfyUI folder (the one that has custom_nodes/), e.g. COMFYUI_DIR=D:\\ComfyUI")
cfg_path = os.path.abspath(sys.argv[1])
submit = "--submit" in sys.argv[2:]
redo = None                                              # --redo <session> <scenes>: remake those scenes, rebuild final
if "--redo" in sys.argv:
    i = sys.argv.index("--redo")
    redo = (sys.argv[i + 1], sys.argv[i + 2])
proj = os.path.dirname(cfg_path)
cfg = json.load(open(cfg_path, encoding="utf-8"))
name, version = cfg["name"], cfg["version"]
P = lambda p: p if os.path.isabs(p) else os.path.join(proj, p)


def ascii_name(src, label):
    ext = os.path.splitext(src)[1].lower()
    return "%s_%s%s" % (name.lower(), label, ext)


def to_input(src, label):
    dst_name = ascii_name(src, label)
    dst = os.path.join(COMFY, "input", dst_name)
    if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(P(src)):
        shutil.copyfile(P(src), dst)
    return dst_name


# --- 1. files ------------------------------------------------------------------------------------------------------
audio_name = to_input(cfg["audio"], "song")
song_s = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                               P(cfg["audio"])], capture_output=True, text=True, check=True).stdout.strip())
audio_start = float(cfg.get("audio_start", 0) or 0)     # render only a part of the song: audio_start .. +length
length = float(cfg.get("length", 0) or 0)
song_s -= audio_start
if length:
    song_s = min(song_s, length)
ch, face, loc = cfg["character"], cfg.get("face"), cfg["location"]
ch_img = to_input(ch["image"], "charsheet")
face_img = to_input(face["image"], "face") if face else None
loc_img = to_input(loc["image"], "location")

# --- 2. cuts and texts ---------------------------------------------------------------------------------------------
step = float(cfg.get("scene_seconds", 10.0))
intro = cfg.get("intro")
first = float(cfg["intro_cut"]) if intro else 0.0
cuts = ([first] if intro else []) + [round(first + step * k, 2) for k in range(1, 1000) if first + step * k < song_s]
total = song_s + float(cfg.get("tail_seconds", 0) or 0)
while cuts and song_s - cuts[-1] < MIN_SCENE:          # a short end joins the scene before it (H3 Chain does the same)
    cuts.pop()
n_scenes = len(cuts) + 1
common = cfg.get("common", "")
shot_texts = ["%s%s 0–5s: %s 5–10s: %s" % (f, common, a, b) for f, a, b in cfg["shots"]]
texts = ([intro] if intro else []) + [shot_texts[k % len(shot_texts)] for k in range(n_scenes - (1 if intro else 0))]

# --- 3. workflow ---------------------------------------------------------------------------------------------------
d = json.load(open(BASE, encoding="utf-8"))
n = {x["id"]: x for x in d["nodes"]}
ctx = "ctx_" + re.sub(r"\W+", "_", name.lower())
c = n[31]["widgets_values"]
c[0], c[1], c[2], c[6] = ch_img, ch["name"], ch["description"], ctx
n[31]["title"] = "%s (character sheet)" % ch["name"]
if face:
    f = n[32]["widgets_values"]
    f[0], f[1], f[2], f[6], f[11] = face_img, ch["name"] + " face", face["description"], ctx + "_face", json.dumps([ctx])
    n[32]["title"] = ch["name"] + " face"
else:
    n[32]["mode"] = 4                                      # bypass the face card
r = n[45]["widgets_values"]
r[0], r[1], r[2], r[6] = loc_img, loc["name"], loc["description"], ctx + "_location"
n[45]["title"] = loc["name"]
n[40]["widgets_values"][0] = audio_name
n[40]["title"] = "Song (%s)" % cfg.get("title", name)
s = n[42]["widgets_values"]
# scenes, look, scene_cuts, scene_seconds, chunk_seconds, width, height, length_mode, length_seconds, audio_start_sec,
# audio_content, lane_mode, speaker, base_seed, redo_session, redo_scenes, chain_iter, chain_state, scene_crossfade,
# [tail_seconds, tail_scene]
s[0], s[1], s[3] = "\n\n".join(texts), cfg["look"], step
s[5], s[6] = int(cfg.get("width", 512)), int(cfg.get("height", 896))
s[7], s[8], s[9] = ("seconds", length, audio_start) if length else ("all", 30.0, audio_start)
s[12] = ctx
if "seed" in cfg:
    s[13] = int(cfg["seed"])
s[14], s[15], s[16], s[17] = "", "", 0, ""
s[18] = float(cfg.get("crossfade", 0.5))
tail = float(cfg.get("tail_seconds", 0) or 0)
del s[19:]
if tail > 0:
    s += [tail, cfg.get("tail_scene", "")]
if redo:
    s[14], s[15] = redo
turbo = cfg.get("turbo", "")
if turbo == "lite4":                                   # Pika Flex Turbo lite r32 (ref2va), 4 steps, simple @ shift 12
    n[30]["widgets_values"][0] = "h3\\pika_h3_flex_turbo_4step_ref2va_lite_r32.safetensors"
    n[30]["title"] = "Pika Flex Turbo lite (4-step)"
    n[37]["widgets_values"][0] = "1.0, 0.972973, 0.923077, 0.8, 0.0"
    n[37]["title"] = "4-step sigmas (simple, shift 12)"
elif turbo:
    sys.exit("unknown turbo %r (only 'lite4')" % turbo)
dial = cfg.get("dial")
if dial:                                               # Pika LoRA 30 -> Load Dial 50 + Apply Dial 51 -> connector 6
    old = next(l for l in d["links"] if l[1] == 30 and l[3] == 6 and l[5] == "MODEL")
    l_dial, l_out = max(l[0] for l in d["links"]) + 1, max(l[0] for l in d["links"]) + 2
    x, y = n[30]["pos"][0], n[30]["pos"][1] + 140
    d["nodes"].append({"id": 50, "type": "DialsLoadDial", "title": "Dial: " + dial["name"], "pos": [x, y],
                       "size": [320, 80], "flags": {}, "order": 0, "mode": 0, "inputs": [],
                       "outputs": [{"name": "dial", "type": "DIAL", "links": [l_dial]},
                                   {"name": "report", "type": "STRING", "links": []}],
                       "properties": {"Node name for S&R": "DialsLoadDial"},
                       "widgets_values": ["dials\\%s.safetensors" % dial["name"]]})
    d["nodes"].append({"id": 51, "type": "DialsApplyDial", "title": "Apply Dial %+g" % dial["strength"],
                       "pos": [x, y + 120], "size": [320, 80], "flags": {}, "order": 0, "mode": 0,
                       "inputs": [{"name": "model", "type": "MODEL", "link": old[0]},
                                  {"name": "dial", "type": "DIAL", "link": l_dial}],
                       "outputs": [{"name": "MODEL", "type": "MODEL", "links": [l_out]}],
                       "properties": {"Node name for S&R": "DialsApplyDial"},
                       "widgets_values": [float(dial["strength"])]})
    d["links"] += [[l_dial, 50, 0, 51, 1, "DIAL"], [l_out, 51, 0, 6, old[4], "MODEL"]]
    for inp in n[6]["inputs"]:
        if inp.get("link") == old[0]:
            inp["link"] = l_out
    old[3], old[4] = 51, 0
    d["last_node_id"], d["last_link_id"] = max(d.get("last_node_id", 0), 51), l_out
n[41]["widgets_values"][0] = ", ".join("%.2f" % x for x in cuts)
dw = n[7]["widgets_values"]
dw[0], dw[4], dw[5] = cfg["idea"], s[5], s[6]          # idea, ..., chunk_seconds [3], width [4], height [5]
out = os.path.join(proj, "H3_Chain_%s_%s.json" % (name, version))
for p in (out, os.path.join(COMFY, "user", "default", "workflows", os.path.basename(out))):
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("workflow  %s (%.2f s song%s, %d scenes)" % (out, song_s, ", +%.1f s silence" % tail if tail else "", n_scenes))
print("cuts      " + n[41]["widgets_values"][0])

# --- 4. Director part-split check ----------------------------------------------------------------------------------
ss_hits = glob.glob(os.path.join(COMFY, "custom_nodes", "*", "ng", "core", "shot_share.py"))
if not ss_hits:
    sys.exit("MiniMax H3 Director not found in custom_nodes (needed for the part-split check)")
ss_path = ss_hits[0]
for mod, attrs in (("ng", {}), ("ng.core", {}), ("ng.core.limits", {"FPS": 24})):
    m = types.ModuleType(mod); m.__path__ = []; m.__dict__.update(attrs); sys.modules.setdefault(mod, m)
spec = importlib.util.spec_from_file_location("ng.core.shot_share", ss_path)
ss = importlib.util.module_from_spec(spec); spec.loader.exec_module(ss)
bad = []
for k, t in enumerate(texts[:len(shot_texts) + (1 if intro else 0)]):
    frames = 216 if (intro and k == 0) else 252
    p2 = ss.without_camera_moves(ss.share(t, 0, frames, 124, frames, frames - 124), re.compile(r"^$"))
    if "static shot" in p2 or not p2.startswith("The camera frames"):
        bad.append(k + 1)
print("director  part 2 keeps framing + motion: %s" % ("OK" if not bad else "NO for scene text %s" % bad))
if bad:
    sys.exit("fix those texts: framing sentence must start 'The camera frames' and contain no move word; "
             "beat 2 must not say 'camera'")

# --- 5. submit -----------------------------------------------------------------------------------------------------
if submit:
    from comfy_cli.workflow_to_api import convert_ui_to_api
    # curl: some antivirus tools reset Python's urllib on the big object_info response
    oi = json.loads(subprocess.run(["curl", "-s", "-m", "120", SERVER + "/object_info"], capture_output=True,
                                   check=True).stdout.decode("utf-8"))
    if tail > 0 and "tail_seconds" not in json.dumps(oi.get("H3ChainState", {})):
        sys.exit("tail_seconds needs a ComfyUI restart (H3 Chain node not reloaded yet)")
    api = convert_ui_to_api(d, oi)
    api["6"]["inputs"].pop("context_text.text_0", None)
    if dial and api["6"]["inputs"].get("model_ref2va") != ["51", 0]:
        sys.exit("dial not wired into the ref2va model input")
    if not face:
        api.pop("32", None)
    api_path = os.path.join(proj, "H3_Chain_%s_%s_api.json" % (name, version))
    json.dump(api, open(api_path, "w", encoding="utf-8"), ensure_ascii=False)
    req = urllib.request.Request(SERVER + "/prompt", data=json.dumps({"prompt": api}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        print("submitted", urllib.request.urlopen(req).read().decode())
    except urllib.error.HTTPError as e:
        sys.exit("submit failed %s %s" % (e.code, e.read().decode()[:2000]))
