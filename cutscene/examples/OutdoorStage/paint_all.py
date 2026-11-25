"""python paint_all.py [--seed N] [S01 S03 ...]  -> h3/Sxx/painted.png (H3-Image repaint of the previs first frame; existing ones are skipped)
The wind is already in these start frames: hair, shirt and banners are blown before the video begins."""
import os, subprocess, sys
D = os.path.dirname(os.path.abspath(__file__))
PAINT = os.path.join(D, "..", "..", "tools", "paint_h3image.py")
WHO = ("the woman from <Picture 2> and <Picture 3>: short black bob with blunt bangs, small dark oval sunglasses, gold hoop earrings, thin necklaces, "
       "loose open shirt with orange, black and cream pattern over a black crop top, wide mustard-yellow cargo pants, cream platform sneakers")
WIDE = ("S01", "S07", "S09", "S10")     # full body visible
THIGH = ("S02", "S04", "S06", "S13", "S16", "S18")
SEED = "11"
if "--seed" in sys.argv:
    k = sys.argv.index("--seed")
    SEED = sys.argv[k + 1]
    del sys.argv[k:k + 2]
SET = ("The place is an outdoor music festival stage at golden sunset. Keep the background of <Picture 1> part by part, at the same places and from the same camera angle, "
       "and only make every surface real: weathered wooden stage deck, aluminium truss towers, stacked black loudspeakers, black guitar amplifiers, low black riser with small round warm light bulbs, "
       "green meadow, dark green trees, distant hills, wide golden orange sky with fast torn clouds. The stage is open to the sky and the back is open to the landscape. No audience, nobody else. ")
WIND = ("A very strong wind blows from the left of the picture to the right: her hair is swept far out to the right with loose strands flying, her open shirt is billowing and flapping far out to the right, "
        "the trousers flutter, the trees bend to the right. ")
VIEW = {
 "S01": "She is tiny and far away, full body, only one third of the picture height, with her feet in the middle of the deck and much empty deck in front of her, seen from the front, arms relaxed at her sides.",
 "S02": "Waist-up, seen from front left of the picture, her face turned slightly to the right.",
 "S03": "Chest-up close-up, seen from slightly right of the front, lips just parted.",
 "S04": "Low angle, thighs up, arms relaxed, seen from slightly right of the front.",
 "S05": "Waist-up, seen from the right of the front.",
 "S06": "Waist-up, seen straight from the front, arms relaxed.",
 "S07": "She is small and far away, full body, only two fifths of the picture height, at the lower left of the middle, seen from a slightly high camera at right, her arms held slightly open at her sides.",
 "S08": "Chest-up, seen from the left of the front, lips closed.",
 "S09": "Low wide shot, full body, seen from the left of the front, arms relaxed.",
 "S10": "Full body, seen from the right of the front, arms held slightly open at her sides, lips closed.",
 "S11": "Waist-up, seen from the right of the front.",
 "S12": "Chest-up close-up, seen from slightly left of the front, lips just parted.",
 "S13": "Low angle, thighs up, arms relaxed, seen from slightly left of the front.",
 "S14": "Waist-up, seen from the left of the front.",
 "S15": "Face and shoulders close-up, straight from the front, lips just parted.",
 "S16": "Thighs up, seen from the left of the front, arms held slightly open at her sides, lips closed.",
 "S17": "Waist-up, seen from the right of the front, lips closed.",
 "S18": "Thighs up, seen straight from the front, arms relaxed, lips closed.",
}
for s in sys.argv[1:] or VIEW:
    d = os.path.join(D, "h3", s)
    os.makedirs(d, exist_ok=True)
    if os.path.exists(os.path.join(d, "painted.png")):
        continue
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(D, "shots", s + ".mp4"), "-frames:v", "1", os.path.join(d, "previs_f001.png")], check=True)
    wide, thigh = s in WIDE, s in THIGH
    who = WHO if wide else WHO.split(", cream platform")[0] if thigh else WHO.split(", wide mustard")[0]
    size = ("Her head and feet are exactly where the mannequin's head and feet are, she is exactly as tall as the mannequin, no bigger. " if wide else
            "Her head is exactly as large in the picture as the mannequin's head and at the same place; the picture is cropped at the same point of her body. No zooming out. ")
    p = ("Edit <Picture 1>, a rough 3D blockout, into a photorealistic cinematic film still with exactly the same camera framing, pose, scale and layout. "
         "Replace the mannequin with %s. She is photorealistic, a real person. %s %s%s%sThere is no microphone. Warm low sunlight on her from the left. "
         "Keep every object where it is and at the same size, add nothing new. No 3D render look, no text, no numbers." % (who, VIEW[s], size, WIND, SET))
    i = lambda n: os.path.join(D, "input", n)
    subprocess.run([sys.executable, PAINT, os.path.join(d, "previs_f001.png"), os.path.join(d, "painted.png"), p,
                    i("face.png"), i("fullbody.png" if wide else "thigh.png" if thigh else "upper.png"), "--seed", SEED, "--mp", "3"], check=True)
    print(s, flush=True)
