"""Writes cutscene.json (outdoor stage, whole song, 18 shots cut on the bar lines)."""
import json, math, os
FPS, BPM, BAR0 = 24, 96.6, 1.32
BEAT = 60 / BPM * FPS
RED, GOLD, BLUE, DARK, BULB = [.55, .06, .12], [.75, .5, .16], [.03, .05, .38], [.03, .03, .035], [1, .8, .45]
S = []


def box(n, loc, size, color, **k):
    S.append(dict(name=n, type="box", loc=loc, size=size, color=color, **k))


def disc(n, x, y, z, w, h, color, t=.15, **k):
    S.append(dict(name=n, type="cylinder", loc=[x, y, z], size=[w, h, t], rot=[90, 0, 0], color=color, **k))


def bulb(x, y, z, r=.09):
    S.append(dict(name="bulb", type="sphere", loc=[x, y, z], size=[r, r, r], color=BULB, emit=6))


# outdoor festival stage on a hill: deck, truss portal, speaker towers, banners, meadow, hills
box("meadow", [0, 60, -1.3], [400, 300, .2], [.10, .20, .05])
box("deck", [0, 0, -.6], [18, 17, 1.2], [.30, .19, .11], rough=.5)
for i in range(45):
    box("plank", [-8.8 + .4 * i, 0, .003], [.03, 17, .006], [.12, .07, .04])
TR = [.45, .46, .48]
for x in (-6.5, 6.5):                              # truss portal, open to the sky
    for dx in (-.2, .2):
        for dy in (-.2, .2):
            box("truss_leg", [x + dx, 6.5 + dy, 3.3], [.07, .07, 6.6], TR)
    for k in range(16):
        box("truss_rung", [x, 6.3, .3 + .4 * k], [.42, .04, .04], TR, rot=[0, 45 if k % 2 else -45, 0])
for dz in (6.4, 6.8):
    for dy in (-.2, .2):
        box("truss_top", [0, 6.5 + dy, dz], [13.4, .07, .07], TR)
for k in range(34):
    box("truss_rung", [-6.6 + .4 * k, 6.3, 6.6], [.04, .04, .55], TR, rot=[0, 45 if k % 2 else -45, 0])
for k in range(9):
    S.append(dict(name="spot", type="cone", loc=[-5.6 + 1.4 * k, 6.3, 6.1], size=[.42, .42, .45], top=.6, color=[.05, .05, .05]))
    bulb(-5.6 + 1.4 * k, 6.25, 5.83, .32)
for x in (-8.0, 8.0):                              # speaker towers
    for k in range(5):
        box("speaker", [x, 5.0, .6 + 1.1 * k], [1.5, .9, 1.04], DARK)
        disc("cone", x, 4.53, .6 + 1.1 * k, .8, .8, [.12, .12, .13], .04)
for x, y in ((-4.6, 5.6), (-3.3, 5.8), (3.3, 5.8), (4.6, 5.6)):   # amps
    box("amp", [x, y, .6], [1.1, .5, 1.2], DARK)
box("riser", [0, 5.6, .25], [4, 2.2, .5], DARK)
for j in range(19):                                # footlights on the back edge and the riser
    bulb(-8.1 + .9 * j, 7.6, .1, .16)
for j in range(12):
    bulb(-1.9 + 3.8 * j / 11, 4.48, .42, .1)
for k, x in enumerate((-12, -10, 10, 12)):         # banners on poles, blown to screen right
    y = 8 + (k % 2) * 3
    box("pole", [x, y, 2.6], [.1, .1, 8], [.7, .7, .7])
    box("banner", [x + .9, y, 4.6], [1.7, .06, 3.6], [.75, .12, .08] if k % 2 else [.85, .5, .08], rot=[0, -10, 14])
for x, y, w, z in ((-60, 110, 120, 13), (30, 130, 160, 17), (95, 105, 110, 11), (-20, 90, 90, 7)):   # hills
    S.append(dict(name="hill", type="sphere", loc=[x, y, -3], size=[w, 60, z * 2], color=[.07, .13, .06]))
for k in range(26):                                # tree line
    x = -62 + 5 * k
    S.append(dict(name="tree", type="sphere", loc=[x, 44 + (k * 7) % 9, .6 + (k * 5) % 3 * .5], size=[6, 5, 5 + (k * 3) % 4], color=[.04, .09, .03]))

cams = [  # id, frames used, desc, camera (t, pos, lens), look (t, pos)
 ("S01", 124, "Opening: wide set, pushes in to waist-up as she starts to sing",
  [(0, [0, -7.6, 2.2], 30), (.38, [0, -2.7, 1.5], 34), (1, [.1, -1.95, 1.44], 38)], [(0, [0, 1.2, 1.7]), (.38, [0, 0, 1.3]), (1, [0, 0, 1.33])]),
 ("S02", 119, "Waist-up, the camera arcs from her right to her left",
  [(0, [-1.15, -1.5, 1.42], 38), (.5, [-.2, -1.85, 1.42], 38), (1, [.75, -1.7, 1.42], 38)], [(0, [0, 0, 1.35]), (1, [0, 0, 1.35])]),
 ("S03", 119, "Face close-up, slow push in",
  [(0, [.55, -1.55, 1.5], 45), (1, [.42, -1.2, 1.5], 50)], [(0, [0, -.02, 1.46]), (1, [0, -.04, 1.5])]),
 ("S04", 119, "Low angle from screen right, rises; she lifts her arm on the long note",
  [(0, [.85, -2.15, .75], 34), (1, [.45, -1.9, 1.3], 36)], [(0, [-.15, 0, 1.38]), (1, [-.15, 0, 1.4])]),
 ("S05", 120, "Chest-up from screen right, drifts left",
  [(0, [1.25, -1.55, 1.46], 38), (1, [.65, -1.85, 1.46], 38)], [(0, [-.1, 0, 1.4]), (1, [-.05, 0, 1.4])]),
 ("S06", 124, "Finale: waist-up, pulls back and up to the whole set",
  [(0, [0, -1.8, 1.45], 38), (.55, [0, -2.3, 1.5], 36), (1, [0, -4.4, 1.9], 32)], [(0, [0, 0, 1.38]), (.55, [0, 0, 1.33]), (1, [0, .6, 1.5])]),
 ("S07", 0, "Interlude: high crane shot from the right, comes down",
  [(0, [2.2, -5.4, 3.0], 30), (1, [1.0, -3.0, 1.6], 32)], [(0, [-.2, 1.5, 1.5]), (1, [-.1, 0, 1.2])]),
 ("S08", 0, "Interlude: three-quarter close-up from the left, drifting",
  [(0, [-1.3, -1.3, 1.5], 42), (1, [-.85, -1.6, 1.5], 42)], [(0, [0, 0, 1.45]), (1, [0, 0, 1.45])]),
 ("S09", 0, "Interlude: low wide shot, slides sideways along the floor",
  [(0, [-2.6, -4.0, .5], 28), (1, [1.6, -4.0, .5], 28)], [(0, [0, 0, 1.2]), (1, [0, 0, 1.2])]),
 ("S10", 0, "Interlude end: long push in to chest-up, she starts the second verse",
  [(0, [1.6, -5.2, 1.9], 32), (1, [.1, -1.55, 1.46], 40)], [(0, [0, 0, 1.2]), (1, [0, 0, 1.43])]),
 ("S11", 0, "Waist-up, the camera arcs from her left to her right",
  [(0, [1.15, -1.5, 1.42], 38), (.5, [.2, -1.85, 1.42], 38), (1, [-.75, -1.7, 1.42], 38)], [(0, [0, 0, 1.35]), (1, [0, 0, 1.35])]),
 ("S12", 0, "Face close-up from screen left, slow push in",
  [(0, [-.55, -1.5, 1.48], 45), (1, [-.35, -1.2, 1.5], 50)], [(0, [0, -.02, 1.46]), (1, [0, -.04, 1.5])]),
 ("S13", 0, "Low angle from screen left, rises; left arm opens",
  [(0, [-.85, -2.15, .8], 34), (1, [-.4, -1.85, 1.3], 36)], [(0, [.1, 0, 1.38]), (1, [.05, 0, 1.4])]),
 ("S14", 0, "Chest-up from screen left, drifts right",
  [(0, [-1.2, -1.45, 1.46], 38), (1, [-.4, -1.75, 1.46], 38)], [(0, [.05, 0, 1.42]), (1, [0, 0, 1.42])]),
 ("S15", 0, "Front: the last line, close-up slowly pulling back",
  [(0, [.1, -1.3, 1.48], 45), (.25, [.1, -1.35, 1.48], 45), (1, [.4, -2.8, 1.55], 36)], [(0, [0, 0, 1.46]), (.25, [0, 0, 1.46]), (1, [0, 0, 1.25])]),
 ("S16", 0, "Outro: crane from the left, rising over the stage",
  [(0, [-1.0, -2.8, 1.4], 32), (1, [-2.2, -5.0, 2.9], 30)], [(0, [.1, 0, 1.25]), (1, [.3, 1.5, 1.5])]),
 ("S17", 0, "Outro: three-quarter close-up from the right, slow push in",
  [(0, [1.3, -1.5, 1.5], 40), (1, [.95, -1.2, 1.5], 45)], [(0, [0, 0, 1.43]), (1, [0, 0, 1.47])]),
 ("S18", 0, "Ending: pulls back to the whole set; final pose, then a bow",
  [(0, [0, -2.4, 1.5], 34), (1, [0, -5.4, 2.0], 30)], [(0, [0, 0, 1.3]), (1, [0, .8, 1.5])]),
]
# cut 0.12 s before every second bar line; the last shot ends with the song
CUT = [0] + [round((BAR0 - .12 + 8 * 60 / BPM * k - 1.0) * FPS) for k in range(1, 18)] + [round((90.76 - 1.0) * FPS)]
assert len(cams) == 18
cams = [(a, CUT[i + 1] - CUT[i], d, c_, l_) for i, (a, _, d, c_, l_) in enumerate(cams)]
assert all(c_[1] <= 124 for c_ in cams), [c_[1] for c_ in cams]
REST = {"upper_arm.L": [4, 0, 3], "forearm.L": [28, 0, 0], "upper_arm.R": [4, 0, -3], "forearm.R": [28, 0, 0]}
HOLD = {"upper_arm.R": [18, -45, -6], "forearm.R": [118, 0, 0]}   # right hand up toward the chest
UP = {"upper_arm.R": [20, 0, -125], "forearm.R": [20, 0, -10]}
OPEN = {"upper_arm.L": [30, 0, 42], "forearm.L": [30, 0, 0], "upper_arm.R": [30, 0, -42], "forearm.R": [30, 0, 0]}
UPL = {"upper_arm.L": [20, 0, 125], "forearm.L": [20, 0, 10]}
HOLDL = {"upper_arm.L": [18, 45, 6], "forearm.L": [118, 0, 0]}
script = {  # time 0..1 in the used part
 "S01": [(0, REST), (.55, REST), (.8, OPEN), (1, REST)],
 "S02": [(0, REST), (.35, REST), (.6, HOLD), (.85, HOLD), (1, REST)],
 "S03": [(0, REST), (1, REST)],
 "S04": [(0, REST), (.35, REST), (.6, UP), (.8, UP), (1, REST)],
 "S05": [(0, REST), (.4, REST), (.65, HOLD), (1, HOLD)],
 "S06": [(0, REST), (.45, REST), (.7, OPEN), (.85, {**OPEN, **UP}), (1, {**OPEN, **UP})],
 "S07": [(0, OPEN), (.25, REST), (.5, OPEN), (.75, REST), (1, OPEN)],
 "S08": [(0, REST), (.3, REST), (.55, HOLD), (.8, HOLD), (1, REST)],
 "S09": [(0, REST), (.25, UP), (.5, REST), (.75, UPL), (1, REST)],
 "S10": [(0, OPEN), (.4, REST), (1, REST)],
 "S11": [(0, REST), (.35, REST), (.6, HOLDL), (.85, HOLDL), (1, REST)],
 "S12": [(0, REST), (1, REST)],
 "S13": [(0, REST), (.35, REST), (.6, UPL), (.8, UPL), (1, REST)],
 "S14": [(0, REST), (.4, REST), (.65, HOLDL), (1, HOLDL)],
 "S15": [(0, REST), (.35, REST), (.65, OPEN), (1, OPEN)],
 "S16": [(0, OPEN), (.25, REST), (.5, OPEN), (.75, REST), (1, OPEN)],
 "S17": [(0, REST), (1, REST)],
 "S18": [(0, REST), (.2, UP), (.5, UP), (.7, REST), (1, REST)],
}
heads = {"S01": [(0, 0, 0), (.5, -3, 0), (1, 0, 0)], "S02": [(0, 0, -8), (.5, -4, 0), (1, 2, 8)],
         "S03": [(0, 0, 8), (.4, -5, 10), (.75, 3, 4), (1, 0, 8)], "S04": [(0, 2, 8), (.6, -10, 6), (.85, -8, 6), (1, 6, 2)],
         "S05": [(0, 0, 14), (.5, -4, 18), (1, 2, 10)], "S06": [(0, 0, 0), (.5, -6, 0), (1, -8, 0)],
         "S07": [(0, 0, 10), (.5, 0, -10), (1, 0, 10)], "S08": [(0, 0, -20), (.5, -6, -30), (1, 4, -14)], "S09": [(0, -4, 12), (.5, -4, -12), (1, -4, 8)],
         "S10": [(0, 8, 6), (.6, 6, 0), (.85, 0, 0), (1, -3, 0)], "S11": [(0, 0, 8), (.5, -4, 0), (1, 2, -8)], "S12": [(0, 0, -8), (.4, -5, -10), (.75, 3, -4), (1, 0, -6)],
         "S13": [(0, 2, -8), (.6, -10, -6), (.85, -8, -6), (1, 6, -2)], "S14": [(0, 0, -14), (.5, -4, -16), (1, 2, -8)], "S15": [(0, -3, 0), (.25, 0, 0), (1, 0, 4)],
         "S16": [(0, 0, -10), (.5, 0, 10), (1, 0, -10)], "S17": [(0, 2, 24), (.5, -3, 16), (1, 0, 28)], "S18": [(0, 0, 0), (.4, -8, 0), (.7, 10, 0), (.85, 24, 0), (1, 24, 0)]}
INST = {"S07": 1.5, "S08": 1.2, "S09": 1.6, "S16": 1.5}
poses, groove, shots, t, f = [], [], [], 1.0, 1
for sid, use, desc, cam, look in cams:
    shots.append(dict(id=sid, frames=124, use=use, start=round(t, 4), desc=desc,
                      camera=[dict(t=a, pos=p, lens=l) for a, p, l in cam], look=[dict(t=a, pos=p) for a, p in look]))
    at = lambda q: min(f + 123, round(f + q * use))
    for q, bones in script[sid]:
        poses.append(dict(f=at(q), bones=bones))
    for q, x, y in heads[sid]:
        poses.append(dict(f=at(q), bones={"head": [x, y, 0]}))
    b0 = (BAR0 - t) * FPS % (2 * BEAT)   # the same left/right phase through the song
    groove.append(dict(f0=f, f1=f + 123, beat0=f + b0, beat=BEAT, amount=.6 if sid in ("S03", "S12", "S17") else INST.get(sid, 1)))
    t += use / FPS
    f += 124
c = dict(title="OutdoorStage", fps=FPS, size=[1056, 576], song=dict(file="input/song.mp3"),
         world=dict(color=[.16, .30, .55], horizon=[.95, .55, .28], strength=.8, sun_dir=[58, 0, -40], sun_color=[1, .78, .52], sun_energy=3.2),
         set=S, shots=shots,
         characters=[dict(name="Hero", height=1.65, color=[.75, .27, .1], pants=[.8, .36, .03], shoes=[.8, .76, .66],
                          hair_color=[.015, .015, .02], hair="bob", glasses=True, start=[0, 0], heading=0, groove=groove, poses=poses)])
json.dump(c, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "cutscene.json"), "w", encoding="utf-8"), indent=1)
print("film %.2f s, song %.2f-%.2f" % (sum(s["use"] for s in shots) / FPS, shots[0]["start"], t))
