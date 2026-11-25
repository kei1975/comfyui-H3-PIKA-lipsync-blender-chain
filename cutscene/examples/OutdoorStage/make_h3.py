"""Writes h3.json: every shot in "position" mode (camera and place from Blender, free dancing, lip sync, strong wind).
Vocals: 1.75-20.25, 21.25-31.75, 50.0-71.75 s of the song."""
import json, os
D = os.path.dirname(os.path.abspath(__file__))
START = "The camera starts directly from the exact composition of the opening frame and "
SING = ("<Subject 1> sings the vocals of <Audio 1> from beginning to end: her lips, jaw and teeth move clearly on every syllable, open wide on long notes and close only at breaths. "
        "Her face stays toward the camera, and her hands and hair never cover her mouth. ")
SILENT = "There are no vocals: <Subject 1> does not sing, her lips stay closed the whole time. "
# face shots: upper body only, so that the mouth stays readable
SOFT = "While singing she moves freely and passionately: shoulders and head groove hard to the beat, she leans in, sways and gestures expressively with her hands below her chin. "
MID = "While singing she dances freely with her whole upper body: big expressive arm gestures out to the sides and up, shoulder accents, hips swaying to the beat, strong energy. "
BIG = ("She dances freely with full energy to the beat: wide arm swings, deep hip sways, bouncing knees, sharp poses on the accents, shoulders and head thrown into the rhythm. "
       "She stays around the same spot. ")
ARMS = "She has exactly two arms. "
WIND = ("A violent storm-force wind blows from the left of the picture to the right in every single frame, from the first to the last, and never weakens: "
        "her hair never hangs down at rest, it is lifted off her neck and ears and streams sideways to the right, with strands whipping across her forehead and cheek, "
        "and her bangs are blown up and apart; her open shirt is inflated like a sail and its fabric flaps fast to the right beside her; trees thrash and clouds race. ")
S = {  # summary, camera, mouth, dance
 "S01": ("Opening: from the whole stage the camera pushes in fast to a waist-up shot as Mimi starts to sing.", "pushes in smoothly toward her until she is seen waist-up,",
         "During the first second her lips are closed, then she starts to sing. " + SING, MID),
 "S02": ("Waist-up of Mimi singing and dancing while the camera arcs around her.", "arcs around her from left to right,", SING, MID),
 "S03": ("Close-up of Mimi singing, the camera pushes in slowly.", "pushes in slowly to her face,", SING, SOFT),
 "S04": ("Low angle: Mimi sings a long note and throws her arm up to the sky.", "rises slowly from a low angle,", SING + "In the last second the vocals stop and her lips close. ",
         MID + "In the middle she throws one arm up to the sky. "),
 "S05": ("Mimi sings and dances, seen from the right.", "drifts left around her,", SING, MID),
 "S06": ("Mimi sings the end of the first verse while the camera pulls back.", "holds close and then pulls back and up to a knee-up shot,", SING, MID + "Near the end she spreads both arms wide into the wind. "),
 "S07": ("Interlude: a crane shot comes down toward Mimi dancing on the stage.", "comes down and closer in one smooth crane move,",
         "During the first half second she finishes her last word, then her lips stay closed. She does not sing after that. ", BIG),
 "S08": ("Interlude: three-quarter close-up of Mimi grooving in the wind.", "drifts sideways around her,", SILENT, "She grooves freely with head and shoulders and sweeps the hair out of her face with one hand. "),
 "S09": ("Interlude: low wide shot of Mimi dancing with full energy as the camera slides sideways.", "slides sideways along the floor,", SILENT, BIG),
 "S10": ("The camera pushes in from full body to chest-up on dancing Mimi, who starts the second verse.", "pushes in smoothly to a chest-up shot,",
         "During the first four seconds there are no vocals and her lips stay closed. In the last second she opens her mouth and starts to sing. ", BIG),
 "S11": ("Waist-up of Mimi singing and dancing while the camera arcs around her.", "arcs around her from right to left,", SING, MID),
 "S12": ("Close-up of Mimi singing, the camera pushes in slowly.", "pushes in slowly to her face,", SING, SOFT),
 "S13": ("Low angle: Mimi sings and dances with big arms.", "rises slowly from a low angle,", SING, MID),
 "S14": ("Mimi sings and dances, seen from the left.", "drifts right around her,", SING, MID),
 "S15": ("Mimi sings the last word in close-up, then the camera pulls back.", "holds close for a moment and then pulls back to a thigh-up shot,",
         "During the first second she sings the last word of the song with a clearly moving mouth, then her lips close and stay closed. ", "Afterwards she spreads both arms wide and lets the wind hit her. "),
 "S16": ("Outro: the camera rises over the stage while Mimi dances.", "rises and pulls back in one smooth crane move,", SILENT, BIG),
 "S17": ("Outro: three-quarter close-up of Mimi, the camera pushes in slowly.", "pushes in slowly,", SILENT, "She grooves freely with head and shoulders, then looks proudly into the distance. "),
 "S18": ("Ending: the camera pulls back to the stage; Mimi raises her arm in a final pose.", "pulls back smoothly to the whole stage,", SILENT,
         "She dances with full energy for two seconds, then strikes a strong final pose with one arm raised to the sky and holds it. "),
}
# retakes w4: the wind died down in the first takes, and they shared the same arm poses
GUST = ("She sings into a roaring gale: at every moment, also while she moves and when she stands still, the gale pulls all of her hair straight out to the right side of her head, "
        "so that her left ear is bare, and the long tail of her open shirt stands out horizontally to the right like a flag, rippling fast. She leans against the gale. ")
OWN = {"S02": "She sweeps one arm slowly across in front of her and then points forward to the camera, hips swaying. ",
       "S04": "She rolls her shoulders, steps wide and punches one fist up to the sky on the long note. ",
       "S13": "She swings both arms in wide circles, bends her knees and throws her head back on the accents. ",
       "S14": "She twists her hips, reaches one hand out to the camera and pulls it back to her chest. "}
for k, own in OWN.items():
    a, cam, mouth, _ = S[k]
    S[k] = (a, cam, mouth, GUST + "While singing she dances freely with strong energy. " + own)

c = dict(
    sheet="input/char_sheet.png", seed=4201, size=[1056, 576], ref_size=[704, 384],
    song=dict(h3_audio="input/vocal_forward.wav", text="a section of a Japanese pop song with a female lead vocal, sung by <Subject 1>; the vocals are in front and the band is quiet behind"),
    subject="the woman in <Picture 1> (Mimi), a cool singer with a short black bob whipped sideways by storm wind, small dark oval sunglasses, gold hoop earrings, thin necklaces, a loose orange-black-cream patterned open shirt over a black crop top, wide mustard-yellow cargo pants and cream platform sneakers",
    retain="her face, black hair color and bob length, dark oval sunglasses, patterned shirt, black crop top and mustard cargo pants are retained; the hair is wildly windblown in every frame",
    look="Photorealistic cinematic live-action footage, one continuous uncut shot on an outdoor music festival stage at golden sunset: weathered wooden deck, aluminium truss, black loudspeaker stacks and amplifiers, meadow, trees and distant hills, golden orange sky with fast torn clouds. Warm low sunlight, rich colors, natural motion blur. " + WIND + "The set never changes, no other people. The sunglasses stay on. There is no microphone. There are no cuts, no subtitles and no on-screen text.",
    video_role="<Video 1> is a rough 3D blockout. Only its camera path, framing, timing and the place of the performer are followed.",
    sound="The song of <Audio 1> fills the air. No other voices, no applause.",
    shots={k: dict(ref="position", summary=a, detailed="", detailed_open=START + cam + " following <Video 1>. " + WIND + mouth + dance + ARMS + "Until the last frame the wind keeps her hair streaming sideways and her shirt flapping. ")
           for k, (a, cam, mouth, dance) in S.items()})
json.dump(c, open(os.path.join(D, "h3.json"), "w", encoding="utf-8"), indent=1)
