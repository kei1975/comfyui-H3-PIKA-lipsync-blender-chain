"""python join.py <project> S01=dir S02=dir ... [--no-rain] [--out FILE]
Uses video_rain.mp4 when the folder has one, else video.mp4. -> <project>/<project>_final.mp4 (hard cuts, levelled audio, 0.15 s audio crossfades)"""
import json, os, subprocess, sys
proj = os.path.abspath(sys.argv[1])
args = sys.argv[2:]
out = os.path.join(proj, os.path.basename(proj) + "_final.mp4")
if "--out" in args:
    i = args.index("--out")
    out = os.path.abspath(args[i + 1])
    del args[i:i + 2]
norain = "--no-rain" in args
args = [a for a in args if a != "--no-rain"]
cfg = json.load(open(os.path.join(proj, "cutscene.json"), encoding="utf-8"))
frames = {s["id"]: s["frames"] for s in cfg["shots"]}
dur = [frames[a.split("=")[0]] / cfg["fps"] for a in args]
v = []
for a in args:
    d = os.path.join(proj, "h3", *a.split("="))
    r = os.path.join(d, "video_rain.mp4")
    v.append(r if os.path.exists(r) and not norain else os.path.join(d, "video.mp4"))
if cfg.get("song"):                   # singing film: "use" frames of each shot, the original song under it
    S = {s["id"]: s for s in cfg["shots"]}
    a, fl, N = [], [], len(v)
    for i, (p, x) in enumerate(zip(v, args)):
        a += ["-i", p]
        fl.append("[%d:v]trim=end_frame=%d,setpts=PTS-STARTPTS,setsar=1[v%d]" % (i, S[x.split("=")[0]]["use"], i))
    fl.append("".join("[v%d]" % i for i in range(N)) + "concat=n=%d:v=1:a=0[v]" % N)
    t0 = S[args[0].split("=")[0]]["start"]
    T = sum(S[x.split("=")[0]]["use"] for x in args) / cfg["fps"]
    fl.append("[%d:a]atrim=%.5f:%.5f,asetpts=PTS-STARTPTS,aresample=48000,apad=whole_dur=%.5f[a]" % (N, t0, t0 + T, T))
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a, "-i", os.path.join(proj, cfg["song"]["file"]), "-filter_complex", ";".join(fl),
                    "-map", "[v]", "-map", "[a]", "-r", "24", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out], check=True)
    print(out)
    sys.exit()
a, fl, N, X = [], [], len(v), .15
for i, p in enumerate(v):
    a += ["-i", p]
    fl.append("[%d:v]setpts=PTS-STARTPTS,setsar=1[v%d]" % (i, i))
    # pad the tail so each crossfade does not shorten the sound against the picture
    fl.append("[%d:a]aresample=48000,loudnorm=I=-20:TP=-2:LRA=11,aresample=48000,atrim=0:%.5f,apad=pad_dur=%g[a%d]" % (i, dur[i], X if i < N-1 else 0, i))
fl.append("".join("[v%d]" % i for i in range(N)) + "concat=n=%d:v=1:a=0[v]" % N)
cur = "a0"
for i in range(1, N):
    fl.append("[%s][a%d]acrossfade=d=%g:c1=qsin:c2=qsin[x%d]" % (cur, i, X, i))
    cur = "x%d" % i
subprocess.run(["ffmpeg", "-v", "error", "-y", *a, "-filter_complex", ";".join(fl), "-map", "[v]", "-map", "[%s]" % cur, "-r", "24",
                "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out], check=True)
print(out)
