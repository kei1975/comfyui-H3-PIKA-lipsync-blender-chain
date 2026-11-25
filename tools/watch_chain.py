"""Wait until an H3 Chain run has finished (the ComfyUI queue stays empty), then print the newest session's videos.

usage: python watch_chain.py                         (env COMFYUI_DIR, COMFYUI_URL as for new_song.py)
The chain queues its next part itself about 0.5 s after each part, so the queue counts as finished only after it has
been empty on three checks in a row.
"""
import glob
import json
import os
import sys
import time
import urllib.request

COMFY = os.environ.get("COMFYUI_DIR", "")
SERVER = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
POLL, EMPTY_CHECKS, DEADLINE = 20, 3, 12 * 3600

start, empty = time.time(), 0
while time.time() - start < DEADLINE:
    try:
        q = json.load(urllib.request.urlopen(SERVER + "/queue", timeout=30))
        busy = bool(q.get("queue_running") or q.get("queue_pending"))
    except OSError as e:
        sys.exit("ComfyUI is not reachable at %s (%s)" % (SERVER, e))
    empty = 0 if busy else empty + 1
    if empty >= EMPTY_CHECKS:
        break
    time.sleep(POLL)
else:
    sys.exit("timeout")

print("queue empty after %.0f min" % ((time.time() - start) / 60))
sessions = sorted(glob.glob(os.path.join(COMFY, "output", "H3Chains", "*")), key=os.path.getmtime)
if COMFY and sessions:
    s = sessions[-1]
    print("session", s)
    for f in sorted(glob.glob(os.path.join(s, "final*.mp4"))):
        print("  ", os.path.basename(f))
