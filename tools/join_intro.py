"""Put an intro clip (e.g. one rendered with H3's own generated sound) in front of a final video, 0.5 s crossfade
(picture and sound).

usage: python join_intro.py <intro.mp4> <main.mp4> <out.mp4>
  For an H3 Chain intro session use its scene_001.mp4, not final.mp4: final.mp4 gets the input audio track,
  scene_001.mp4 keeps the sound H3 generated.
"""
import subprocess
import sys

intro, main, out = sys.argv[1:4]
XF = 0.5
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", intro],
                           capture_output=True, text=True, check=True).stdout)
fl = ("[0:v]fps=24,format=yuv420p,setsar=1[a];[1:v]fps=24,format=yuv420p,setsar=1[b];"
      "[a][b]xfade=transition=fade:duration=%g:offset=%.3f[v];"
      "[0:a]aresample=48000,aformat=channel_layouts=stereo[x];[1:a]aresample=48000,aformat=channel_layouts=stereo[y];"
      "[x][y]acrossfade=d=%g[au]" % (XF, dur - XF, XF))
subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", intro, "-i", main, "-filter_complex", fl,
                "-map", "[v]", "-map", "[au]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "medium",
                "-c:a", "aac", "-b:a", "256k", out], check=True)
print("joined", out)
