"""Dialogue story -> H3 Chain workflow, from one story.json (after tools/make_voices.py has made the lines).

What it does
  1. lays the lines out in time: each scene starts with `lead_in` s of silence, the lines follow each other with `gap` s
     between them (or the line's own "pause"), and the scene ends `tail` s after its last line (at least `min_scene` s,
     H3's shortest scene is ~4.46 s; a line-less scene lasts its "seconds")
  2. mixes the lines into one dialogue track (ffmpeg) and copies it, the character sheets and the location image into
     ComfyUI/input under ASCII names
  3. writes each scene's text: your text, then time beats made from the line times ("0–4.2s: @Ben talks to @Anna ...
     @Anna listens, lips closed. 4.2–9.4s: ..."), so every render part knows who talks; plus the spoken lines (who, what,
     language) for the Director
  4. writes the workflow (UI json) into the project folder and ComfyUI/user/default/workflows, checks the Director part
     split (part 2 must keep the scene's framing), and with --submit queues it; the chain runs on its own until final.mp4

usage: python new_story.py <project_dir>/story.json [--submit] [--redo <session> "<scenes>"]
  needs: ffmpeg / ffprobe on PATH; --submit also needs comfy-cli (pip install comfy-cli) and a running ComfyUI
  env:   COMFYUI_DIR = your ComfyUI folder, COMFYUI_URL = http://127.0.0.1:8188 (default)

story.json (paths relative to the json file):
  name, version              -> <project_dir>/H3_Story_<name>_<version>.json
  characters                 [{name, image, description, voice: {sample, language ("ja", "en", ...), ref_text (opt.),
                             speed (opt.)}, voice_description (opt.)}]; 1 or 2 characters (+ location), or 3 without one
  location (optional)        {name, image, description}: a background card
  look, idea                 State look (art style; say "no readable text" if signs show up) / Director idea
  common (optional)          text added after every scene's own text
  scenes                     [{text, lines: [{who, text, speed (opt.), action (opt.), pause (opt.)}], seconds (opt.)}]
                             text: "The camera frames ..." with no move word, then the move, the place and the action.
                             line text goes to OmniVoice as it is ([laughter] etc.); the Director gets it without tags.
                             action: what the speaker does while talking ("laughs and turns to @Anna"); default "talks"
  timing (optional)          {lead_in 0.6, gap 0.35, tail 0.9, min_scene 4.6}
  width (1056), height (576), crossfade (0.5), seed (optional), voice_settings {seed, steps} (make_voices.py)
"""
import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import types
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
COMFY = os.environ.get("COMFYUI_DIR", "")
SERVER = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
if not os.path.isdir(os.path.join(COMFY, "custom_nodes")):
    sys.exit("set COMFYUI_DIR to your ComfyUI folder (the one that has custom_nodes/), e.g. COMFYUI_DIR=D:\\ComfyUI")
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "base_workflow.json")
FPS = 24
LANGS = {"ja": "Japanese", "en": "English", "zh": "Chinese", "ko": "Korean", "fr": "French", "de": "German",
         "es": "Spanish", "it": "Italian", "pt": "Portuguese", "ru": "Russian"}

cfg_path = os.path.abspath(sys.argv[1])
submit = "--submit" in sys.argv[2:]
redo = None
if "--redo" in sys.argv:
    i = sys.argv.index("--redo")
    redo = (sys.argv[i + 1], sys.argv[i + 2])
proj = os.path.dirname(cfg_path)
cfg = json.load(open(cfg_path, encoding="utf-8"))
name, version = cfg["name"], cfg["version"]
P = lambda p: p if os.path.isabs(p) else os.path.join(proj, p)
slug = lambda s: re.sub(r"\W+", "_", s.lower()).strip("_")


def to_input(src, label):
    dst_name = "%s_%s%s" % (slug(name), label, os.path.splitext(src)[1].lower())
    dst = os.path.join(COMFY, "input", dst_name)
    if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
        shutil.copyfile(src, dst)
    return dst_name


# --- 1. timeline -----------------------------------------------------------------------------------------------------
manifest_path = os.path.join(proj, "voices", "manifest.json")
if not os.path.exists(manifest_path):
    sys.exit("no voices/manifest.json: run make_voices.py first")
manifest = json.load(open(manifest_path, encoding="utf-8"))
tm = dict(lead_in=0.6, gap=0.35, tail=0.9, min_scene=4.6)
tm.update(cfg.get("timing", {}))
chars = {c["name"]: c for c in cfg["characters"]}
ctx = {c["name"]: "ctx_" + slug(c["name"]) for c in cfg["characters"]}
scenes, t0, placed = [], 0.0, []                          # placed: (file, start in the track)
for si, sc in enumerate(cfg["scenes"]):
    t, lines = tm["lead_in"], []
    for li, line in enumerate(sc.get("lines", [])):
        lid = "s%02d_l%02d" % (si + 1, li + 1)
        m = manifest.get(lid)
        if not m or m["text"] != line["text"] or m["who"] != line["who"]:
            sys.exit("%s is not in voices/manifest.json as written: run make_voices.py again" % lid)
        if li:
            t += float(sc["lines"][li - 1].get("pause", tm["gap"]))
        lines.append(dict(line, id=lid, start=round(t, 3), end=round(t + m["seconds"], 3)))
        placed.append((os.path.join(proj, "voices", m["file"]), t0 + t))
        t += m["seconds"]
    length = max(t + tm["tail"], tm["min_scene"], float(sc.get("seconds", 0)))
    if not lines:
        length = max(float(sc.get("seconds", 5.0)), tm["min_scene"])
    scenes.append({"start": round(t0, 3), "seconds": round(length, 3), "lines": lines, "text": sc["text"]})
    t0 += length
total = t0

# --- 2. dialogue track and cards ------------------------------------------------------------------------------------
track = os.path.join(proj, "H3_Story_%s_%s_dialogue.wav" % (name, version))
args, fl = ["ffmpeg", "-nostdin", "-v", "error", "-y"], []
for k, (f, start) in enumerate(placed):
    args += ["-i", f]
    ms = int(round(start * 1000))
    fl.append("[%d:a]aresample=48000,aformat=channel_layouts=stereo,adelay=%d|%d[a%d]" % (k, ms, ms, k))
mix = "".join("[a%d]" % k for k in range(len(placed)))
fl.append("%samix=inputs=%d:normalize=0:duration=longest,apad,atrim=0:%.3f[out]" % (mix, len(placed), total))
subprocess.run(args + ["-filter_complex", ";".join(fl), "-map", "[out]", "-c:a", "pcm_s16le", track], check=True)
audio_name = to_input(track, "dialogue")

cards = [("character", c) for c in cfg["characters"]] + ([("location", cfg["location"])] if cfg.get("location") else [])
if len(cards) > 3:
    sys.exit("at most 3 image cards (characters + location); this story has %d" % len(cards))


# --- 3. scene texts -------------------------------------------------------------------------------------------------
def say(text):
    return " ".join(re.sub(r"\[[^\]]*\]", " ", text).split())


def beat_text(sc):
    names = [c["name"] for c in cfg["characters"]]
    in_scene = [n for n in names if "@" + n in sc["text"]] or names
    lines, beats = sc["lines"], []
    if not lines:
        return "0–%gs: Nobody talks; every mouth stays closed." % round(sc["seconds"], 1)
    for k, line in enumerate(lines):
        a = 0.0 if k == 0 else line["start"]
        b = lines[k + 1]["start"] if k + 1 < len(lines) else sc["seconds"]
        others = [n for n in in_scene if n != line["who"]]
        lang = LANGS.get(chars[line["who"]]["voice"]["language"], chars[line["who"]]["voice"]["language"])
        body = "@%s %s in %s." % (line["who"], line.get("action", "talks"), lang)
        if others:
            body += " " + " ".join("@%s listens, lips closed." % o for o in others)
        if k + 1 == len(lines) and b - line["end"] > 1.2:
            body += " Then nobody talks; every mouth stays closed."
        beats.append("%g–%gs: %s" % (round(a, 1), round(b, 1), body))
    return " ".join(beats)


common = cfg.get("common", "")
texts, spoken = [], []
for sc in scenes:
    texts.append(" ".join((sc["text"] + common + " " + beat_text(sc)).split()))
    spoken.append([{"text": say(l["text"]), "speaker_id": ctx[l["who"]],
                    "language": LANGS.get(chars[l["who"]]["voice"]["language"], "English"),
                    "voice": chars[l["who"]].get("voice_description", "a natural voice"), "start": l["start"]}
                   for l in sc["lines"]])
for sc_lines in spoken:
    for l in sc_lines:
        if any(c in l["voice"] for c in "\n\r[]():"):
            sys.exit("voice_description may not contain [ ] ( ) : or line breaks: %r" % l["voice"])

# --- 4. workflow ----------------------------------------------------------------------------------------------------
d = json.load(open(BASE, encoding="utf-8"))
n = {x["id"]: x for x in d["nodes"]}
slots = [31, 32, 45]
for (kind, c), nid in zip(cards, slots):
    w = n[nid]["widgets_values"]
    label = "location" if kind == "location" else slug(c["name"])
    w[0], w[1], w[2], w[3] = to_input(P(c["image"]), label), c["name"], c["description"], kind
    w[6] = ctx[c["name"]] if kind == "character" else "ctx_" + slug(c["name"]) + "_location"
    w[11] = ""
    n[nid]["title"] = "%s (%s)" % (c["name"], kind)
unused = slots[len(cards):]
for nid in unused:
    n[nid]["mode"] = 4                                     # bypassed (removed from the API graph on submit)
n[40]["widgets_values"][0] = audio_name
n[40]["title"] = "Dialogue (%s)" % cfg.get("title", name)
cuts = [sc["start"] for sc in scenes[1:]]
n[41]["widgets_values"][0] = ", ".join("%.2f" % x for x in cuts)
s = n[42]["widgets_values"]
s[0], s[1], s[3] = "\n\n".join(texts), cfg["look"], 10.0
s[5], s[6] = int(cfg.get("width", 1056)), int(cfg.get("height", 576))
s[7], s[8], s[9] = "all", 30.0, 0.0
s[10], s[11], s[12] = "dialogue", "lock", ""
if "seed" in cfg:
    s[13] = int(cfg["seed"])
s[14], s[15], s[16], s[17] = "", "", 0, ""
s[18] = float(cfg.get("crossfade", 0.5))
del s[19:]
s += [0.0, "", json.dumps(spoken, ensure_ascii=False)]
if redo:
    s[14], s[15] = redo
dw = n[7]["widgets_values"]
dw[0], dw[4], dw[5] = cfg.get("idea", ""), s[5], s[6]
dw[9], dw[10] = "N/A", "N/A"                               # no soundscape, no music: the track is only the dialogue
out = os.path.join(proj, "H3_Story_%s_%s.json" % (name, version))
for p in (out, os.path.join(COMFY, "user", "default", "workflows", os.path.basename(out))):
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open(os.path.join(proj, "H3_Story_%s_%s_timeline.txt" % (name, version)), "w", encoding="utf-8") as f:
    for k, sc in enumerate(scenes):
        f.write("scene %d  %.2f-%.2fs (%.2fs)\n" % (k + 1, sc["start"], sc["start"] + sc["seconds"], sc["seconds"]))
        for l in sc["lines"]:
            f.write("  %5.2f-%5.2fs  %s: %s\n" % (l["start"], l["end"], l["who"], l["text"]))
        f.write("  text: %s\n\n" % texts[k])
print("workflow  %s (%.2f s, %d scenes, %d lines)" % (out, total, len(scenes), len(placed)))
print("cuts      " + (n[41]["widgets_values"][0] or "(one scene)"))
for k, sc in enumerate(scenes):
    print("scene %d  %5.2fs  %s" % (k + 1, sc["seconds"], " / ".join("%s %.1f-%.1f" % (l["who"], l["start"], l["end"])
                                                                    for l in sc["lines"]) or "(no lines)"))

# --- 5. Director part-split check -----------------------------------------------------------------------------------
ss_hits = glob.glob(os.path.join(COMFY, "custom_nodes", "*", "ng", "core", "shot_share.py"))
if not ss_hits:
    sys.exit("MiniMax H3 Director not found in custom_nodes (needed for the part-split check)")
for mod, attrs in (("ng", {}), ("ng.core", {}), ("ng.core.limits", {"FPS": FPS})):
    m = types.ModuleType(mod); m.__path__ = []; m.__dict__.update(attrs); sys.modules.setdefault(mod, m)
spec = importlib.util.spec_from_file_location("ng.core.shot_share", ss_hits[0])
ss = importlib.util.module_from_spec(spec); spec.loader.exec_module(ss)
bad = []
for k, (t, sc) in enumerate(zip(texts, scenes)):
    frames = int(round(sc["seconds"] * FPS))
    if frames <= 124:
        continue                                           # one render part only
    p2 = ss.without_camera_moves(ss.share(t, 0, frames, 124, frames, frames - 124), re.compile(r"^$"))
    if "static shot" in p2 or not p2.startswith("The camera frames"):
        bad.append(k + 1)
print("director  part 2 keeps framing: %s" % ("OK" if not bad else "NO for scene %s" % bad))
if bad:
    sys.exit("fix those scene texts: start with 'The camera frames ...' with no move word, then the move")

# --- 6. submit ------------------------------------------------------------------------------------------------------
if submit:
    from comfy_cli.workflow_to_api import convert_ui_to_api
    oi = json.loads(subprocess.run(["curl", "-s", "-m", "120", SERVER + "/object_info"], capture_output=True,
                                   check=True).stdout.decode("utf-8"))
    if "spoken" not in json.dumps(oi.get("H3ChainState", {})):
        sys.exit("the installed H3 Chain has no `spoken` input: install this version and restart ComfyUI")
    api = convert_ui_to_api(d, oi)
    api["6"]["inputs"].pop("context_text.text_0", None)
    for nid in unused:
        api.pop(str(nid), None)
    api_path = os.path.join(proj, "H3_Story_%s_%s_api.json" % (name, version))
    json.dump(api, open(api_path, "w", encoding="utf-8"), ensure_ascii=False)
    req = urllib.request.Request(SERVER + "/prompt", data=json.dumps({"prompt": api}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        print("submitted", urllib.request.urlopen(req).read().decode())
    except urllib.error.HTTPError as e:
        sys.exit("submit failed %s %s" % (e.code, e.read().decode()[:2000]))
