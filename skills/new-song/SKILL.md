---
name: new-song
description: Set up and render an H3 Chain music video for a new song and character from a materials folder (song, character sheet, face close-up, background image). Use when the user says "new song", gives such a folder, or asks for an MV with H3 Chain.
---

# New song -> H3 Chain MV

Reply in the user's language. The user starts and restarts ComfyUI; never restart it yourself and never download
models without asking.

## Setup this skill expects

- This node pack is installed in `ComfyUI/custom_nodes/` (any folder name). Its `tools/` folder holds:
  - `new_song.py`: song.json -> workflow, Director part-split check, `--submit`, `--redo`
  - `base_workflow.json`: the graph
  - `watch_chain.py`: waits until the chain has finished
  - `face_sizes.py`, `face_refine.py`, `apply_facerefine.py`: fix scenes where the face is small
  - `join_parts.py`, `join_intro.py`: join renders of song parts / put an intro in front
  - `example_song.json`: a full example
- Environment variables: `COMFYUI_DIR` (the ComfyUI folder) and, if not the default, `COMFYUI_URL`
  (http://127.0.0.1:8188).
- Python: one that has comfy-cli (`pip install comfy-cli`) for `new_song.py` / `face_refine.py`; ComfyUI's own Python
  for `face_sizes.py` / `apply_facerefine.py`. `ffmpeg` / `ffprobe` on PATH.
- If something is missing, tell the user what it is instead of working around it.

## Steps

1. **Look at the folder.** Read each image once, at most one per role: the character sheet, one face portrait and the
   background. If there is a memo / notes file, read it (title, character name, mood, orientation). Read the audio
   length with `ffprobe -show_entries format=duration`.

2. **Ask only what you cannot see** (one question round; skip what the memo answers):
   - the character's name
   - the song title, and the artist if it is a cover
   - the orientation: 9:16 is the default, 512x896; for 16:9 use 896x512
   - **when the first sung word starts**, as its own question ("At what second does the singing start? Not the
     length of the intro: the first moment a voice is heard.")
   - whether to have an intro scene, as a separate question

   Don't merge these two: asked together, an answer like "5 s" can mean either, and treating it as the vocal start
   when the singing really starts at 20 s gives a moving mouth over the instrumental intro. If an answer is ambiguous,
   ask again before writing song.json.
   Don't run stem separation or long audio analysis unless asked; ask where the vocals start instead.

3. **Write `<project>/song.json`.**
   - Start from `tools/example_song.json`. The field list is in the `new_song.py` docstring.
   - Paths are relative to song.json. The script copies the files into ComfyUI/input under ASCII names.
   - Match the song's mood in `look`, `common` and the shots: palette, light, camera speed, setting.
   - The default is 8 shots and 10 s scenes. Shots repeat in order; the intro scene is never reused.

4. **Build and submit the full song** with `python tools/new_song.py <project>/song.json --submit`.
   - Render the whole song, not a short test first; fix single scenes afterwards with `--redo <session> "3,7"`.
   - If the Director check fails, fix the text and run again.
   - Run `watch_chain.py` in the background. A full render takes very roughly 0.9 x the song length in minutes on a
     12 GB card at 512x896 (a 3-minute song takes about 2.5-3 h).

5. **When it finishes:**
   - Copy `output/H3Chains/<session>/{*.mp4,plan.json,scenes.txt}` into `<project>/output/<date>_<version>/`.
   - Make a frame strip and look at it once:
     `ffmpeg -i final.mp4 -vf "fps=1/2,scale=100:-1,tile=23x2" -frames:v 1 strip.jpg`.
   - Check for closed mouths while there are vocals, small faces, and the character walking in from far away.
   - Report. Each re-run gets a new `version`; never overwrite the user's workflows.

## Writing the scene text

**How the Director keeps text across render parts.** It splits each scene into render parts (5 s each).
- A sentence starting "The camera ..." is kept in every part. If it contains a move word (orbit, dolly, push, pan,
  track, circle, glide, rise, sweep, arc, move, tilt, ...), it is dropped from part 2 and replaced by "The camera holds a
  static shot".
- So write each shot as `[framing + move, beat 1, beat 2]`:
  - the framing sentence "The camera frames ...", with no move word;
  - the move sentence after it;
  - beat 1 (0-5 s) and beat 2 (5-10 s). Beat 2 never says "camera".

**Lip sync.**
- Every beat, beat 2 above all, must say she (he) sings. A beat that only describes a pose or an expression ("points at
  the lens with a smile", "a wink between lines") makes H3 close the mouth for that whole render part.
- Keep the face large: head to waist or closer for most shots. Faces in a puddle reflection, behind neon tubes, in a
  top-down full body or a crane shot can't follow the vocals.
- With a long street or a deep background, write "from the very first frame she is already standing close to the
  lens", or the character walks in from far away.
- Lips: "her lips follow the vocals and stay closed when there are no vocals".

**The camera.**
- Give every shot a different angle: close-ups, from the side, low angle, high angle, through glass, Dutch angle, and
  so on.
- Add "The camera never goes behind her; her face always stays in view." Without it, orbits end on the back.

**Movement.**
- Text moves hands far more than audio does. One short sentence about hands is enough; long hand sentences take motion
  away from the camera and lead to fidgeting (e.g. touching the hair all the time).
- For more energy, use "a light groove on the spot, small shoulder bounces, side steps". Spins, struts, "fast" and
  whip-pans are usually too much.

**Other conventions.**
- The background card is the location: describe it and say "the place is always the @Location".
- Intro scene (before the first word): put `intro_cut` 0.5 s before the vocals start.
- **Before the vocals start, nobody sings.** Every scene that ends before the first sung word says "she does not sing
  yet, her lips stay closed the whole time" and plays the instrument; never "begins to sing". "Lips follow the vocals"
  alone is not enough, the text moves the mouth more than the audio does. With a long instrumental intro, let `intro`
  run up to the vocal start instead of letting singing shots fall on it.
- Name each prop once and say "There is only one microphone in the room": a microphone in both the framing and the
  beats gave three or four microphones.
- Silence after the song: set `tail_seconds`, and optionally `tail_scene` (needs 5 s or more).
- A quiet song intro can be rendered on its own with `audio_start` / `length` and its own calm shot, then joined with
  `join_parts.py`.

## Dials (ComfyUI-Dials, optional)

`"dial": {"name": "h3_motion", "strength": 0.5}` puts Load Dial + Apply Dial between the Pika LoRA and the Director.
The file must be in `models/loras/dials/`.
- `h3_motion` makes the character walk or run around (locomotion), not dance on the spot. Leave it off for singing
  MVs where the singer stays in one place; use it for running or chase scenes, at +0.5 at most.
- The expression dials (`h3_evil_*`) change the face and the light at about +1.5; `unhinged` changes the face too much.

## Faces that are too small

1. `face_sizes.py <ComfyUI>/output/H3Chains/<session>` lists the face height per scene.
2. `face_refine.py <project>/song.json <session> "<scenes>" --denoise 0.3 --submit` for scenes whose smallest face is
   about 65 px or less (at 512x896). About 4-5 min per scene. 0.3 keeps the mouth and the expression; 0.45 changes them.
3. `apply_facerefine.py <session> "<scenes>"` puts them in (the originals go to `_pre_facerefine/`) and writes a new
   `final_N.mp4`.

## Don'ts

- Don't overwrite the user's workflows; each run gets a new version name.
- Don't restart ComfyUI and don't download models without asking.
- Don't upscale or run a high-resolution pass unless asked.
