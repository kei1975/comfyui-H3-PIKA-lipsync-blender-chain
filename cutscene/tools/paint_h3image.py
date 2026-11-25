"""Paint one source frame as the target with MiniMax-H3-Image edit (local).

<Picture 1> is the frame to edit; <Picture 2>, <Picture 3>... are photos of the person.
Usage: python paint_h3image.py <frame.png> <out.png> "<prompt>" <photo1> [photo2 ...] [--seed N] [--mp 4]
The frame is scaled to about <mp> megapixels for the model (it works poorly at low resolution);
the result is saved scaled back to the frame's size, plus <out>_full.png at model size.
"""
import json, os, shutil, subprocess, sys, time, urllib.error, urllib.request, uuid

SERVER = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
COMFY = os.environ.get("COMFYUI_DIR", "")
FFMPEG, FFPROBE = "ffmpeg", "ffprobe"
if not os.path.isdir(os.path.join(COMFY, "custom_nodes")):
    sys.exit("set COMFYUI_DIR to your ComfyUI folder (the one that has custom_nodes/)")


def post(path, data=None):
    req = urllib.request.Request(SERVER + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %d: %s" % (e.code, e.read().decode("utf-8", "replace")[:3000]))


args = sys.argv[1:]
seed, mp = 1, 4.0
if "--seed" in args:
    i = args.index("--seed"); seed = int(args[i + 1]); del args[i:i + 2]
if "--mp" in args:
    i = args.index("--mp"); mp = float(args[i + 1]); del args[i:i + 2]
frame, out, prompt, photos = args[0], args[1], args[2], args[3:]

tag = uuid.uuid4().hex[:8]
w, h = map(int, subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                "-of", "csv=p=0", frame], capture_output=True, text=True, check=True).stdout.strip().split(","))
k = (mp * 1e6 / (w * h)) ** 0.5
W, H = int(w * k) // 32 * 32, int(h * k) // 32 * 32
names = ["h3i_%s_0.png" % tag]
subprocess.run([FFMPEG, "-v", "error", "-y", "-i", frame, "-vf", "scale=%d:%d:flags=lanczos" % (W, H),
                os.path.join(COMFY, "input", names[0])], check=True)
for j, p in enumerate(photos, 1):
    n = "h3i_%s_%d.png" % (tag, j)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", p, os.path.join(COMFY, "input", n)], check=True)
    names.append(n)

g = {
    "29": {"class_type": "UNETLoader", "inputs": {"unet_name": os.path.join("h3", "minimax_h3_image_pruned_int8_convrot.safetensors"), "weight_dtype": "default"}},
    "30": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
    "31": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_image_vae_fp16.safetensors"}},
    "32": {"class_type": "MiniMaxH3ImageConditioning", "inputs": {"clip": ["30", 0], "vae": ["31", 0], "prompt": prompt, "width": W, "height": H}},
    "33": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["32", 0]}},
    "38": {"class_type": "KSampler", "inputs": {"model": ["29", 0], "positive": ["32", 0], "negative": ["33", 0], "latent_image": ["32", 1],
                                                "seed": seed, "steps": 6, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
    "42": {"class_type": "VAEDecode", "inputs": {"samples": ["38", 0], "vae": ["31", 0]}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["42", 0], "filename_prefix": "h3_cutscene_paint/" + tag}},
}
for j, n in enumerate(names, 1):
    g["5%d" % j] = {"class_type": "LoadImage", "inputs": {"image": n}}
    g["32"]["inputs"]["images.image_%d" % j] = ["5%d" % j, 0]

t0 = time.time()
pid = post("/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})["prompt_id"]
while True:
    hst = post("/history/" + pid)
    if pid in hst and (hst[pid]["status"].get("completed") or hst[pid]["status"].get("status_str") == "error"):
        break
    time.sleep(2)
if hst[pid]["status"].get("status_str") == "error":
    sys.exit(json.dumps(hst[pid]["status"]["messages"], ensure_ascii=False)[:3000])
img = next(i for o in hst[pid]["outputs"].values() for i in o.get("images", []) if i.get("type") == "output")
src = os.path.join(COMFY, "output", img["subfolder"], img["filename"])
subprocess.run([FFMPEG, "-v", "error", "-y", "-i", src, "-vf", "scale=%d:%d:flags=lanczos" % (w, h), out], check=True)
shutil.copy(src, out.replace(".png", "_full.png"))
print("painted: %s  (%dx%d, %.0fs)" % (out, W, H, time.time() - t0))
