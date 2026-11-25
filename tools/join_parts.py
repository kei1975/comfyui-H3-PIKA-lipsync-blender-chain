"""Join H3 Chain renders of consecutive parts of one song (song.json audio_start / length) into one video.

usage: python join_parts.py <song audio> <out.mp4> <part1 final.mp4> <start1> <part2 final.mp4> <start2> ...
  start = the part's audio_start in seconds. Each part but the last should run 0.5 s past the next start (length);
  the picture dissolves over those 0.5 s and the whole song is laid back on top, so the lip sync stays exact.
"""
import subprocess
import sys

XF = 0.5
song, out = sys.argv[1], sys.argv[2]
parts = [(sys.argv[i], float(sys.argv[i + 1])) for i in range(3, len(sys.argv), 2)]


def duration(f):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f],
                                capture_output=True, text=True, check=True).stdout)


args, fl, prev = ["ffmpeg", "-nostdin", "-v", "error", "-y"], [], None
for k, (f, start) in enumerate(parts):
    args += ["-i", f]
    fl.append("[%d:v]fps=24,format=yuv420p,setsar=1[p%d]" % (k, k))
for k in range(1, len(parts)):
    a = "p0" if k == 1 else "j%d" % (k - 1)
    fl.append("[%s][p%d]xfade=transition=fade:duration=%g:offset=%.3f[j%d]" % (a, k, XF, parts[k][1], k))
end = parts[-1][1] + duration(parts[-1][0])
vout = "p0" if len(parts) == 1 else "j%d" % (len(parts) - 1)
args += ["-i", song, "-filter_complex", ";".join(fl), "-map", "[%s]" % vout, "-map", "%d:a" % len(parts),
         "-t", "%.3f" % end, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "medium", "-c:a", "aac", "-b:a", "256k", out]
subprocess.run(args, check=True)
print("joined %s (%.2f s)" % (out, end))
