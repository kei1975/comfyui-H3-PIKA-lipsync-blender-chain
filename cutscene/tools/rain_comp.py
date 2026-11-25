"""python rain_comp.py <project> <shot> <render folder in h3/<shot>> [--strength 0.8]  -> h3/<shot>/<folder>/video_rain.mp4"""
import os, subprocess, sys
proj, shot, d = sys.argv[1:4]
k = float(sys.argv[sys.argv.index("--strength") + 1]) if "--strength" in sys.argv else .8
b = os.path.join(proj, "h3", shot)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(b, d, "video.mp4"), "-framerate", "24", "-i", os.path.join(b, "rain", "%04d.png"),
                "-filter_complex", "[1:v]format=gbrp,gblur=sigma=0.6,split[r][r2];[r2]gblur=sigma=14,colorchannelmixer=rr=.5:gg=.5:bb=.5[mist];"
                "[r][mist]blend=all_mode=screen[rain];[0:v]format=gbrp[v];[v][rain]blend=all_mode=screen:all_opacity=%g,format=yuv420p[o]" % k,
                "-map", "[o]", "-map", "0:a", "-c:v", "libx264", "-crf", "14", "-c:a", "copy", "-movflags", "+faststart", os.path.join(b, d, "video_rain.mp4")], check=True)
