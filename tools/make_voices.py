"""Make every dialogue line of a story.json with OmniVoice (voice cloning from a short sample per character).

usage: <OmniVoice's python> make_voices.py <project_dir>/story.json [--force]
  env:  OMNIVOICE_MODEL = the OmniVoice model folder (from_pretrained), OMNIVOICE_ASR = a Whisper model folder or name
        (only needed when a voice sample has no transcript yet; default openai/whisper-large-v3-turbo)

Writes <project_dir>/voices/:
  <line id>_<who>_<hash>.wav    one file per line (24 kHz, 16-bit). The hash covers the text, voice sample, language,
                                speed, seed and steps, so a later run only makes the lines that changed (--force: all)
  manifest.json                 line id -> {file, seconds}; tools/new_story.py reads it
  ref_transcripts.json          the transcript of each voice sample (Whisper the first time). If it is wrong, correct it
                                here or give "ref_text" in the character's voice; it is used from then on
ComfyUI can stay open; this does not use it.

Tips (OmniVoice):
- Cut each voice sample at a pause (the end of a sentence), 3-10 s, in the language of the lines. A sample cut
  mid-phrase leaks its last words into every line.
- There is no emotion setting: the delivery follows the sample, so pick a lively sample for a lively line. "!" and the
  inline tags help: [laughter] [sigh] [surprise-oh] [surprise-wa] [question-en] [confirmation-en] [dissatisfaction-hnn].
"""
import hashlib
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
story_path = Path(sys.argv[1]).resolve()
force = "--force" in sys.argv[2:]
proj = story_path.parent
story = json.loads(story_path.read_text(encoding="utf-8"))
P = lambda p: Path(p) if os.path.isabs(p) else proj / p
out_dir = proj / "voices"
out_dir.mkdir(exist_ok=True)
vs = story.get("voice_settings", {})
SEED, STEPS = int(vs.get("seed", 42)), int(vs.get("steps", 32))

chars = {c["name"]: c for c in story["characters"]}
jobs = []                                                  # (line id, character, text, speed, file)
for si, scene in enumerate(story["scenes"]):
    for li, line in enumerate(scene.get("lines", [])):
        who = line["who"]
        if who not in chars or "voice" not in chars[who]:
            sys.exit("scene %d line %d: no character %r with a voice" % (si + 1, li + 1, who))
        voice = chars[who]["voice"]
        sample = P(voice["sample"])
        speed = float(line.get("speed", voice.get("speed", 1.0)))
        key = json.dumps([line["text"], sample.name, sample.stat().st_size, voice["language"], speed, SEED, STEPS],
                         ensure_ascii=False)
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
        lid = "s%02d_l%02d" % (si + 1, li + 1)
        jobs.append((lid, chars[who], line["text"], speed, out_dir / ("%s_%s_%s.wav" % (lid, who.lower(), h))))

todo = [j for j in jobs if force or not j[4].exists()]
manifest_path = out_dir / "manifest.json"
if todo:
    import torch
    import torchaudio
    from omnivoice import OmniVoice

    model_dir = os.environ.get("OMNIVOICE_MODEL")
    if not model_dir:
        sys.exit("set OMNIVOICE_MODEL to the OmniVoice model folder")
    tr_path = out_dir / "ref_transcripts.json"
    transcripts = json.loads(tr_path.read_text(encoding="utf-8")) if tr_path.exists() else {}
    used = {j[1]["name"]: j[1] for j in todo}
    model = OmniVoice.from_pretrained(model_dir, device_map="cuda:0", dtype=torch.float16)
    if any(not (c["voice"].get("ref_text") or transcripts.get(P(c["voice"]["sample"]).name)) for c in used.values()):
        model.load_asr_model(model_name=os.environ.get("OMNIVOICE_ASR", "openai/whisper-large-v3-turbo"))
    prompts = {}
    for name, c in used.items():
        sample = P(c["voice"]["sample"])
        ref = c["voice"].get("ref_text") or transcripts.get(sample.name) or None
        prompts[name] = model.create_voice_clone_prompt(str(sample), ref_text=ref)
        transcripts[sample.name] = prompts[name].ref_text
        print("[ref] %s (%s): %s" % (name, sample.name, transcripts[sample.name]))
    tr_path.write_text(json.dumps(transcripts, ensure_ascii=False, indent=2), encoding="utf-8")
    for lid, c, text, speed, path in todo:
        torch.manual_seed(SEED)
        audio = model.generate(text=text, language=c["voice"]["language"], voice_clone_prompt=prompts[c["name"]],
                               num_step=STEPS, speed=speed)[0]
        wav = audio.float().cpu()
        if wav.dim() == 1:
            wav = wav.unsqueeze(0)
        torchaudio.save(str(path), wav.clamp(-1, 1), model.sampling_rate, encoding="PCM_S", bits_per_sample=16)
        print("[ok] %s %s %.2fs  %s" % (lid, c["name"], wav.shape[-1] / model.sampling_rate, text))

import wave  # noqa: E402

manifest = {}
for lid, c, text, speed, path in jobs:
    with wave.open(str(path), "rb") as w:
        manifest[lid] = {"file": path.name, "seconds": round(w.getnframes() / float(w.getframerate()), 3),
                         "who": c["name"], "text": text}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
print("%d lines (%d made now) -> %s" % (len(jobs), len(todo), manifest_path))
