"""Face refine for finished H3 Chain scenes (distant faces): track + crop the face, re-render the crop with H3
(face card as reference, the scene's own audio locked so the lips follow it, denoise scaled by face size), paste it back.

usage: python face_refine.py <project_dir>/song.json <session> "<scenes>" [--canvas 448] [--denoise 0.3] [--submit]
  writes ComfyUI/output/H3Chains/<session>/facerefine/scene_XXX_*.mp4 (the refined scene, plus crops before/after)
  needs: ComfyUI-H3-FaceRefine (H3FaceTrackCrop / H3InjectVideoLatent / H3PerFrameDenoise / H3FaceStitch),
         VideoHelperSuite, face_yolov8n.pt in models/ultralytics/; env COMFYUI_DIR, COMFYUI_URL as for new_song.py

H3 Chain: Audio Lock (this pack) holds the scene's audio in the latent with the Director's lock_audio_latent.
"""
import json
import os
import random
import re
import shutil
import sys
import urllib.request


sys.stdout.reconfigure(encoding="utf-8")
COMFY = os.environ.get("COMFYUI_DIR", "")                # your ComfyUI folder (the one with models/, input/, output/)
SERVER = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
if not os.path.isdir(os.path.join(COMFY, "custom_nodes")):
    sys.exit("set COMFYUI_DIR to your ComfyUI folder (the one that has custom_nodes/), e.g. COMFYUI_DIR=D:\\ComfyUI")
cfg_path, session, scenes = os.path.abspath(sys.argv[1]), sys.argv[2], sys.argv[3]
args = sys.argv[4:]
opt = lambda k, d: type(d)(args[args.index(k) + 1]) if k in args else d
canvas = opt("--canvas", 448)
denoise = opt("--denoise", 0.3)
submit = "--submit" in args
cfg = json.load(open(cfg_path, encoding="utf-8"))
name = cfg["name"]
face = cfg.get("face")
if not face:
    sys.exit("song.json has no face card")
face_img = "%s_face%s" % (name.lower(), os.path.splitext(face["image"])[1].lower())
if not os.path.exists(os.path.join(COMFY, "input", face_img)):
    sys.exit("%s is not in ComfyUI/input (run new_song.py once)" % face_img)
sdir = os.path.join(COMFY, "output", "H3Chains", session)

who = cfg["character"]["name"]
prompt = ("subject_definitions:\n<Subject 1> is %s, whose face is shown in <Picture 1>.\n\n"
          "summary:\n[reference generation] A close-up of <Subject 1>'s face while she sings: the same face, hair, "
          "expression and head movement as the video, with sharp, natural, detailed features. %s Her lips follow the "
          "vocals and stay closed when there are no vocals. The light and colours stay exactly as in the video. "
          "No text, no logos." % (who, face["description"]))


def graph(src, tag, seed):
    out = "H3Chains/%s/facerefine/%s" % (session, tag)
    vc = lambda images, prefix, audio=None: {"class_type": "VHS_VideoCombine", "inputs": dict(
        images=images, frame_rate=24, loop_count=0, filename_prefix=prefix, format="video/h264-mp4",
        pix_fmt="yuv420p", crf=17, save_metadata=False, trim_to_audio=False, pingpong=False, save_output=True,
        **({"audio": audio} if audio else {}))}
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax\\Minimax-h3_Singularity_ref2va_v2_Pruned_int8.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": "minimax\\pika_h3_flex_ref2va_v1_bf16.safetensors", "strength_model": 1.0}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "10": {"class_type": "VHS_LoadVideo", "inputs": {"video": src, "force_rate": 0, "custom_width": 0, "custom_height": 0,
                                                       "frame_load_cap": 0, "skip_first_frames": 0, "select_every_nth": 1, "format": "None"}},
        "11": {"class_type": "LoadImage", "inputs": {"image": face_img}},
        "20": {"class_type": "H3FaceTrackCrop", "inputs": {
            "images": ["10", 0], "detector": "face_yolov8n.pt", "confidence": 0.35, "crop_factor": 2.5,
            "canvas_width": canvas, "canvas_height": canvas, "canvas_mode": "manual", "smooth_window": 21,
            "size_smooth_window": 51, "smooth_method": "gaussian", "size_mode": "per_frame", "identity_track": False,
            "select": "largest_face", "fallback_detector": "none", "cut_detection": "none", "absent_shots": "off"}},
        "21": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["3", 0], "prompt": prompt, "width": ["20", 4], "height": ["20", 5], "length": ["20", 6],
            "ref_image_size": "match", "vae": ["4", 0], "audio_vae": ["5", 0], "ref_images.ref_image_0": ["11", 0]}},
        "22": {"class_type": "H3InjectVideoLatent", "inputs": {"av_latent": ["21", 1], "images": ["20", 0], "vae": ["4", 0]}},
        "23": {"class_type": "H3ChainAudioLock", "inputs": {"av_latent": ["22", 0], "audio": ["10", 2], "audio_vae": ["5", 0]}},
        "24": {"class_type": "H3PerFrameDenoise", "inputs": {
            "model": ["2", 0], "av_latent": ["23", 0], "transform": ["20", 1], "denoise_multiplier_small_face": 1.0,
            "denoise_multiplier_large_face": 0.35, "scale_mode": "absolute_px", "face_px_small": 60.0,
            "face_px_large": 120.0, "gamma": 1.0, "smooth_frames": 9}},
        "30": {"class_type": "BasicScheduler", "inputs": {"model": ["2", 0], "scheduler": "beta", "steps": 8, "denoise": denoise}},
        "31": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "32": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "33": {"class_type": "BasicGuider", "inputs": {"model": ["24", 2], "conditioning": ["21", 0]}},
        "34": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["32", 0], "guider": ["33", 0], "sampler": ["31", 0],
                                                                "sigmas": ["30", 0], "latent_image": ["24", 0]}},
        "35": {"class_type": "VAEDecode", "inputs": {"samples": ["34", 0], "vae": ["4", 0]}},
        "40": {"class_type": "H3FaceStitch", "inputs": {
            "base_images": ["10", 0], "refined_crops": ["35", 0], "transform": ["20", 1], "paste_region": "face_only",
            "mask_dilation": 24, "feather": 24, "colour_match": 1.0, "blend": 1.0, "undetected_frames": "fade_out"}},
        "50": vc(["40", 0], out, ["10", 2]),
        "51": vc(["20", 0], out + "_crop_before"),
        "52": vc(["35", 0], out + "_crop_after"),
    }


for k in sorted({int(t) for t in re.split(r"[,\s]+", scenes) if t.strip()}):
    tag = "scene_%03d" % k
    src_path = os.path.join(sdir, tag + ".mp4")
    src = "%s_%s.mp4" % (session, tag)
    shutil.copyfile(src_path, os.path.join(COMFY, "input", src))
    g = graph(src, tag, random.randint(1, 2**48))
    if not submit:
        print(json.dumps(g, ensure_ascii=False)[:400]); continue
    req = urllib.request.Request(SERVER + "/prompt", data=json.dumps({"prompt": g}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        print(tag, urllib.request.urlopen(req).read().decode())
    except urllib.error.HTTPError as e:
        sys.exit("submit failed %s %s" % (e.code, e.read().decode()[:3000]))
