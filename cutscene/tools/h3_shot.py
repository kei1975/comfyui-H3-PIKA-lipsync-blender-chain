"""H3 pass for one shot: python h3_shot.py <project> <shot> <auto|gray|color|position|camera|free> [--seed N] [--tag NAME] [--build-only]
env: COMFYUI_DIR = your ComfyUI folder, COMFYUI_URL = http://127.0.0.1:8188 (default). ffmpeg on PATH.
<project>/h3/<shot>/painted.png is pinned as the first frame, the character sheet is <Picture 1>, the previs is <Video 1>.
What <Video 1> gives: gray/color = camera, place and body motion; position = camera and place (a pillar); camera = camera only
(position and camera come from ref_pass.py, the body is free); free = no reference video.
auto = the shot's "ref" in h3.json: motion (= gray, the default), position, camera or free.
position, camera and free take the shot text from "detailed_<mode>", else "detailed_open" ("summary_..." the same way, optional).
Graph: h3_base_api.json (Pika H3 Flex ref2va). Output: <project>/h3/<shot>/<mode>[_tag]/{video.mp4,prompt.txt,workflow_api.json}."""
import json, os, shutil, subprocess, sys, time, urllib.request
from urllib.error import HTTPError

COMFY = os.environ.get("COMFYUI_DIR", "")
SERVER = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
if not os.path.isdir(os.path.join(COMFY, "custom_nodes")):
    sys.exit("set COMFYUI_DIR to your ComfyUI folder (the one that has custom_nodes/)")
proj, shot, mode = os.path.abspath(sys.argv[1]), sys.argv[2], sys.argv[3]
opt = lambda k, d=None: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
cfg = json.load(open(os.path.join(proj, "h3.json"), encoding="utf-8"))
s = cfg["shots"][shot]
if mode == "auto":
    mode = {"motion": "gray"}.get(s.get("ref", "motion"), s.get("ref"))
if mode not in ("gray", "color", "position", "camera", "free"):
    sys.exit("unknown mode %s" % mode)
free, opened = mode == "free", mode in ("position", "camera", "free")
detailed, summary = s["detailed"], s["summary"]
if opened:
    summary = s.get("summary_" + mode) or s.get("summary_open") or summary
    detailed = s.get("detailed_" + mode) or s.get("detailed_open") or sys.exit("%s: h3.json needs detailed_%s or detailed_open" % (shot, mode))
if free and "<Video 1>" in summary + detailed + cfg["look"] + s.get("sound", cfg["sound"]):
    sys.exit("free has no reference video: %s needs a detailed_free without <Video 1>" % shot)
EMPTY = "Its flat gray materials and lighting are not copied. "
role = {"camera": "<Video 1> is a rough empty 3D blockout of the set. Only its camera path, framing and timing are followed. " + EMPTY +
                  "The performer is missing from <Video 1>; her body moves freely as described.",
        "position": "<Video 1> is a rough 3D blockout of the set. Only its camera path, framing, timing and the place of the performer are followed. " + EMPTY +
                    "The plain gray pillar marks only where <Subject 1> stands and which way she faces; the pillar itself never appears, and her body moves freely as described.",
        "free": ""}.get(mode, cfg["video_role"])
role = cfg.get("video_role_" + mode, role)
keep = {"camera": "camera movement, framing and timing only", "position": "camera movement, framing, timing and the place of the performer only"}.get(
    mode, "camera movement, framing, timing and body motion only")
keep = [] if free else ["<Video 1>: reference - %s." % keep]
seed = int(opt("--seed", cfg["seed"]))
tag = opt("--tag")
out = os.path.join(proj, "h3", shot, mode + ("_" + tag if tag else ""))
os.makedirs(out, exist_ok=True)
pre = "%s_%s_%s" % (os.path.basename(proj).lower(), shot, mode)
frames = next(x["frames"] for x in json.load(open(os.path.join(proj, "cutscene.json"), encoding="utf-8"))["shots"] if x["id"] == shot)
song = cfg.get("song")                 # singing: the shot's part of the song is <Audio 1>
cs = next(x for x in json.load(open(os.path.join(proj, "cutscene.json"), encoding="utf-8"))["shots"] if x["id"] == shot)
tags = "reference generation" + ("" if free else " + video reference") + (" + audio copy" if song else "")
audio_def = ["<Audio 1> is %s." % song["text"]] if song else []
audio_ret = ["<Audio 1>: fully_copy - <Audio 1> is reused as the target video's complete final audio track; "
             "the performer's lips follow its vocals exactly."] if song else []
prompt = "\n".join([
    "subject_definitions:", "<Subject 1> is %s." % cfg["subject"], *([role] if role else []), *audio_def, "",
    "summary:", "[%s] A %.1f-second continuous shot. %s" % (tags, frames / 24, summary), "",
    "retention_analysis:", "<Subject 1> (appears in [Shot 1]): fully_preserved - %s." % cfg["retain"],
    *keep, *audio_ret, "",
    "detailed_description:", cfg["look"], "[Shot 1] " + detailed, "",
    "overall_soundscape:", s.get("sound", cfg["sound"]), "",
    "non_diegetic_music:", "None. There is no background music." if not song else "None. The song of <Audio 1> is heard inside the scene; no other music is added."])
inp = os.path.join(COMFY, "input")
shutil.copy(os.path.join(proj, "h3", shot, "painted.png"), os.path.join(inp, pre + "_first.png"))
shutil.copy(os.path.join(proj, cfg["sheet"]), os.path.join(inp, pre + "_sheet.png"))
if not free:
    src = os.path.join(proj, "shots" if mode == "color" else "shots_" + mode, shot + ".mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", "scale=%d:%d:flags=lanczos" % tuple(cfg["ref_size"]),
                    "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", os.path.join(inp, pre + "_ref.mp4")], check=True)
g = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "h3_base_api.json")))
for n in g.values():                   # the json has Windows separators
    for k in ("unet_name", "lora_name"):
        if k in n["inputs"]:
            n["inputs"][k] = n["inputs"][k].replace("\\", os.sep)
c = g["182"]["inputs"]
if song:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(cs["start"]), "-t", "%.5f" % (frames / 24), "-i", os.path.join(proj, song["h3_audio"]),
                    "-af", "apad", "-t", "%.5f" % (frames / 24), os.path.join(inp, pre + "_song.wav")], check=True)
    g["402"] = {"class_type": "LoadAudio", "inputs": {"audio": pre + "_song.wav"}}
    c["ref_audios.ref_audio_1"] = ["402", 0]
c["width"], c["height"], c["length"] = cfg["size"][0], cfg["size"][1], frames
g["138"]["inputs"]["value"] = prompt
g["177"]["inputs"]["image"] = pre + "_sheet.png"
g["181"]["inputs"]["image"] = pre + "_first.png"
if not free:
    g["400"] = {"class_type": "LoadVideo", "inputs": {"file": pre + "_ref.mp4"}}
    g["401"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["400", 0]}}
    c["ref_videos.ref_video_1"] = ["401", 0]
g["129"]["inputs"]["noise_seed"] = seed
g["92"]["inputs"]["filename_prefix"] = "video/blender_cutscene/" + pre
open(os.path.join(out, "prompt.txt"), "w", encoding="utf-8").write(prompt)
json.dump(g, open(os.path.join(out, "workflow_api.json"), "w"), indent=1)
if "--build-only" in sys.argv:
    sys.exit()


def call(path, data=None):
    r = urllib.request.Request(SERVER + path, data=json.dumps(data).encode() if data else None, headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(r))
    except HTTPError as e:
        sys.exit("HTTP %d %s" % (e.code, e.read().decode("utf-8", "replace")[:3000]))


t0 = time.time()
pid = call("/prompt", {"prompt": g})["prompt_id"]
print("submitted", pid, flush=True)
while True:
    time.sleep(5)
    h = call("/history/" + pid).get(pid)
    if h and h["status"].get("status_str") == "error":
        sys.exit(json.dumps([m for m in h["status"]["messages"] if m[0] == "execution_error"])[:2500])
    if h and h["status"].get("completed"):
        break
f = next(x for o in h["outputs"].values() for k in o if k in ("images", "videos", "gifs") for x in o[k]
         if x.get("type") == "output" and x["filename"].endswith(".mp4"))
shutil.copy(os.path.join(COMFY, "output", f["subfolder"], f["filename"]), os.path.join(out, "video.mp4"))
print("%s %s seed %d: %.0f s" % (shot, mode, seed, time.time() - t0))
