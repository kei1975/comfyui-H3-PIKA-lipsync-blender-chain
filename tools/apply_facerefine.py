"""Put face-refined scenes into an H3 Chain session and rebuild final.mp4 (no H3 run).

usage: <ComfyUI's python> apply_facerefine.py <session> "<scenes>"     (env COMFYUI_DIR)
  - the newest facerefine/scene_XXX_NNNNN.mp4 replaces scene_XXX.mp4; the original goes to _pre_facerefine/
  - then H3 Chain: Step's own final writer (crossfades, original song) writes final_N.mp4 next to the old finals
"""
import glob
import os
import re
import shutil
import sys
import types

COMFY = os.environ.get("COMFYUI_DIR", "")                # your ComfyUI folder (the one with models/, input/, output/)
if not os.path.isdir(os.path.join(COMFY, "custom_nodes")):
    sys.exit("set COMFYUI_DIR to your ComfyUI folder (the one that has custom_nodes/), e.g. COMFYUI_DIR=D:\\ComfyUI")
session, scenes = sys.argv[1], sys.argv[2]
sdir = os.path.join(COMFY, "output", "H3Chains", session)

import av  # noqa: E402

for k in sorted({int(t) for t in re.split(r"[,\s]+", scenes) if t.strip()}):
    tag = "scene_%03d" % k
    cands = sorted(p for p in glob.glob(os.path.join(sdir, "facerefine", tag + "_[0-9]*.mp4")) if "-audio" not in p)
    if not cands:
        sys.exit("no facerefine result for " + tag)
    new, cur = cands[-1], os.path.join(sdir, tag + ".mp4")
    count = lambda p: av.open(p).streams.video[0].frames
    if count(new) != count(cur):
        sys.exit("%s: frame count %d != %d" % (tag, count(new), count(cur)))
    keep = os.path.join(sdir, "_pre_facerefine", tag + ".mp4")
    os.makedirs(os.path.dirname(keep), exist_ok=True)
    if not os.path.exists(keep):
        shutil.copyfile(cur, keep)
    shutil.copyfile(new, cur)
    print("%s <- %s" % (tag, os.path.basename(new)))

# load the chain's nodes.py with stand-ins for ComfyUI's server modules (only _final is used)
sys.path.insert(0, COMFY)
fp = types.ModuleType("folder_paths"); fp.get_output_directory = lambda: os.path.join(COMFY, "output")
sv = types.ModuleType("server"); sv.PromptServer = type("PromptServer", (), {"instance": None})
sys.modules.setdefault("folder_paths", fp); sys.modules["server"] = sv
spec_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nodes.py")   # this pack
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("h3chain_nodes", spec_path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
out = mod.H3ChainStep()._final(sdir, "final", "original", 16)
print("final", out)
