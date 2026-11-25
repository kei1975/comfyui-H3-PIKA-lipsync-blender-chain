"""python render_review.py <project dir> [--encode-only]
Builds cutscene.blend, renders it, and writes review.mp4 (labelled), shots/ and shots_gray/ Sxx.mp4 (clean, for H3) and review_sheet.jpg.
--encode-only: only re-encode what is in frames/."""
import json, os, shutil, subprocess, sys

BLENDER = os.environ.get("BLENDER", "blender")   # set BLENDER if blender is not on PATH
FONT = "fontfile='C\\:/Windows/Fonts/arial.ttf':" if os.name == "nt" else ""
here = os.path.dirname(os.path.abspath(__file__))
proj = os.path.abspath(sys.argv[1])
cfg = json.load(open(os.path.join(proj, "cutscene.json"), encoding="utf-8"))
frames = os.path.join(proj, "frames")
for d in ("shots", "shots_gray"):
    os.makedirs(os.path.join(proj, d), exist_ok=True)
if "--encode-only" not in sys.argv:
    for d in (frames, frames + "_gray"):  # generated files only
        shutil.rmtree(d, ignore_errors=True)
    subprocess.run([BLENDER, "-b", "--factory-startup", "--python-exit-code", "1", "-P",
                    os.path.join(here, "build_cutscene.py"), "--", proj, "--gray"], check=True, stdout=subprocess.DEVNULL)
total = sum(s["frames"] for s in cfg["shots"])
have = len([f for f in os.listdir(frames) if f.endswith(".jpg")])
assert have == total, f"{have} frames on disk, expected {total}"


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *map(str, a)], check=True, cwd=proj)


X264 = ["-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
draw, pick, f = [], [], 1
for s in cfg["shots"]:
    n = s["frames"]
    ff("-framerate", cfg["fps"], "-start_number", f, "-i", "frames/%04d.jpg", "-frames:v", n, *X264, f"shots/{s['id']}.mp4")
    ff("-framerate", cfg["fps"], "-start_number", f, "-i", "frames_gray/%04d.jpg", "-frames:v", n, *X264, f"shots_gray/{s['id']}.mp4")
    draw.append(f"drawtext={FONT}fontsize=26:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=6:"
                f"x=16:y=16:text='{s['id']}  f%{{eif\\:n+1-{f-1}\\:d}}':enable='between(n,{f-1},{f+n-2})'")
    pick += [f + 5, f + n//2, f + n - 6]
    f += n
song, aud, cut = cfg.get("song"), [], ""
if song:  # shots may render a few extra frames; the film uses "use" frames of each, and the song runs under it
    keep, f, t = [], 0, cfg["shots"][0]["start"]
    for s in cfg["shots"]:
        assert abs(s["start"] - t) < .5 / cfg["fps"], f"{s['id']}: start {s['start']} should be {t:.4f}"
        keep.append(f"between(n,{f},{f + s['use'] - 1})")
        f += s["frames"]
        t += s["use"] / cfg["fps"]
    cut = f",select='{'+'.join(keep)}',setpts=N/{cfg['fps']}/TB"
    t0 = cfg["shots"][0]["start"]
    aud = ["-ss", t0, "-t", t - t0, "-i", song["file"]]
ff("-framerate", cfg["fps"], "-i", "frames/%04d.jpg", *aud, "-vf", ",".join(draw) + cut,
   *X264, *(["-c:a", "aac", "-b:a", "192k"] if song else []), "review.mp4")
if song:  # the sheet below reads the trimmed review
    pick, f = [], 1
    for s in cfg["shots"]:
        pick += [f + 5, f + s["use"]//2, f + s["use"] - 6]
        f += s["use"]
sel = "+".join(f"eq(n,{p-1})" for p in pick)
ff("-i", "review.mp4", "-vf", f"select='{sel}',scale=640:-1,tile=3x{len(cfg['shots'])}", "-frames:v", 1, "-q:v", 3, "review_sheet.jpg")
print("ok", total, "frames")
