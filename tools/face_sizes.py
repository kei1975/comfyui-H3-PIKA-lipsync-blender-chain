"""Face height per scene of an H3 Chain session (YOLO face detector, every 12th frame).
usage: <ComfyUI's python (has ultralytics + av)> face_sizes.py <ComfyUI>/output/H3Chains/<session>
Scenes whose min face height is small (about 65 px or less at 512x896) are worth a face_refine.py pass."""
import glob, os, sys
import av
from ultralytics import YOLO
model = YOLO(os.path.join(os.path.dirname(sys.argv[1]), "..", "..", "models", "ultralytics", "face_yolov8n.pt"))
for path in sorted(glob.glob(os.path.join(sys.argv[1], "scene_*.mp4"))):
    hs, miss, n = [], 0, 0
    with av.open(path) as c:
        for i, f in enumerate(c.decode(video=0)):
            if i % 12:
                continue
            n += 1
            r = model(f.to_ndarray(format="rgb24"), conf=0.35, verbose=False)[0]
            if len(r.boxes) == 0:
                miss += 1; continue
            b = r.boxes.xyxy.cpu().numpy()
            hs.append(max(y2 - y1 for x1, y1, x2, y2 in b))
    hs.sort()
    med = hs[len(hs) // 2] if hs else 0
    print("%s  median %4.0fpx  min %4.0f  max %4.0f  no-face %d/%d" % (os.path.basename(path), med, hs[0] if hs else 0, hs[-1] if hs else 0, miss, n))
