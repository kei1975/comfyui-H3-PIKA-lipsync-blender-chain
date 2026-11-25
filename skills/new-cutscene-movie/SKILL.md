---
name: new-cutscene-movie
description: Make a cutscene movie by blocking it out in Blender first (set, mannequin, camera), letting the user review it, then replacing each shot with MiniMax H3 video that follows the Blender camera and motion. Use when the user says new-cutscene-movie, カットシーン, Blender で作って H3 に置き換え, previs, プリビズ, or wants a multi-shot scene with planned camera work.
---

# New cutscene movie: Blender previs -> H3

Reply in the user's language. ComfyUI runs at 127.0.0.1:8188 (or `COMFYUI_URL`); the user starts and restarts it.
The tools are in `cutscene/` of the comfyui-H3-PIKA-lipsync-blender-chain repository. Run the commands below from there. Make each project in its own folder next to `examples/`; use `examples/Harbor/` as the template for every file.

- `PY`: any Python 3.10+. `BLENDER`: the Blender executable (5.3 was used), also as the environment variable `BLENDER` for `render_review.py`. `PAINT`: `tools/paint_h3image.py`.
- Environment: `COMFYUI_DIR` (the ComfyUI folder), `COMFYUI_URL` if it is not http://127.0.0.1:8188. `ffmpeg` / `ffprobe` on PATH.
- The numbers below come from a 12 GB RTX 4070 Ti. If something is missing, tell the user instead of working around it.
- Write JSON and prompts with the Write tool or Python. PowerShell `Set-Content -Encoding utf8` adds a BOM, which breaks `json.load`.

| Script in `tools/` | What it does |
|---|---|
| `render_review.py <project>` | `cutscene.json` -> `cutscene.blend`, `review.mp4` (shot names and frame numbers), `review_sheet.jpg`, clean `shots/` and `shots_gray/`. |
| `build_cutscene.py` | Called by `render_review.py`. Alone, with `--still N,N`, it renders single frames to `stills/`: `BLENDER -b --factory-startup --python-exit-code 1 -P tools/build_cutscene.py -- <project> --still 10,130`. |
| `h3_shot.py <project> <shot> <mode>` | Renders one shot in H3 (about 8 to 11 min at 124 frames). Modes: `gray`, `position`, `camera`, `free`, `auto`; see "What H3 takes from Blender". Options: `--seed N`, `--tag NAME` (keeps another take in its own folder), `--build-only`. |
| `ref_pass.py` | Reference videos for `position` and `camera`: `BLENDER -b --factory-startup <project>/cutscene.blend --python-exit-code 1 -P tools/ref_pass.py -- <project> position S01 S02` -> `shots_position/`. |
| `rain_pass.py`, `rain_comp.py` | Rain drawn in Blender, blended over the H3 video. |
| `join.py <project> S01=gray S02=gray ...` | Hard cuts and levelled audio -> `<project>_final.mp4`. Uses `video_rain.mp4` when the folder has one. Options: `--no-rain`, `--out FILE`. |
| `paint_h3image.py` | Repaints one previs frame with MiniMax H3 Image: the start frame of a shot. |

**There are two gates where you stop and wait for the user: after the Blender previs (step 4) and after the first H3 shot (step 6). Don't pass a gate without an OK, unless the user has said to run straight through.**

## Steps

1. **Ask once, only what is missing.** Scene and story, the character (an image), the mood or weather, and what H3 takes from Blender (motion, position, camera or free; see below). Defaults: 4 shots of 124 frames (about 20 s), 1056x576, no dialogue, no BGM. Look at each image once. Don't use ControlNet or download models; the previs is already the control.

2. **Make the project** `<Scene>_v1/` with `input/`.
   - Copy the character sheet to `input/char_sheet.png`. Crop `input/face.png` and `input/fullbody.png` from it with ffmpeg, then view the crops: the crop numbers differ for every sheet.
   - A new version of a scene is a new folder (`_v2`). Never overwrite an older one.

3. **Write `cutscene.json`.**
   - `world`: sky colours, sun. `set`: `box`, `sphere`, `cylinder`, `cone` (`top` = top radius ratio), `ocean`, or `parts` for a compound object. `repeat` is [dx, dy, dz, count]; `keys` moves an object; `sway` rocks a boat; `emit` makes it glow.
   - `ocean`: `loc` is the corner, not the centre, so shift it by about half of `tile` x `repeat_tiles`, or the sea is cut off.
   - `characters`: `start`, `walks` (`f`, `to`, `speed`; 1.3 m/s is a normal walk), `poses` (bone rotations in degrees at a frame). Match the mannequin to the character: `color`, `pants`, `shoes`, `hair_color`, `hair: "bob"`, `glasses`. Frame numbers run over the whole film, not per shot.
   - Bones: `pelvis chest neck head`, `upper_arm forearm hand thigh shin foot` with `.L`/`.R`. The character's left is `.L`.
   - `shots`: `frames` must be 17n+5 (124 = 5.2 s). Camera keys `t` 0..1 with `pos` and `lens`; `look` is `"Hero:chest"`, `"Hero:head"` or position keys.
   - Plan each shot around one clear action. Vary size and angle: wide, side tracking, front push-in, from behind. Give a face shot a long enough close-up.
   - Keep lamp posts and other set objects out of the foreground unless you want them big.

4. **Build the previs, check it, then stop.** `PY tools/render_review.py <project>`.
   - View `review_sheet.jpg` and a few gray frames. Check: the character is in frame, feet on the ground, no camera inside an object, the action reads, the gray version still separates figure, ground and sky.
   - Fix problems yourself, then send `review.mp4` and the sheet. Tell the user they can open `cutscene.blend` (Numpad 0, then Space).
   - Warn them that a rebuild overwrites `cutscene.blend`; hand edits go in `cutscene_edit.blend`. If they did edit it, use their file: render from it, don't rebuild.
   - **Gate 1: wait for the OK. Do not start H3 before it.**

5. **Paint the start frame of each shot** (after the OK).
   - `ffmpeg -i shots/S01.mp4 -frames:v 1 h3/S01/previs_f001.png`
   - `PY PAINT h3/S01/previs_f001.png h3/S01/painted.png "<prompt>" input/fullbody.png input/face.png --seed 11 --mp 3`
   - Prompt: "Edit <Picture 1>, a rough 3D blockout, into a photorealistic cinematic film still with exactly the same camera framing, pose, scale and layout. Replace the mannequin with the woman from <Picture 2> and <Picture 3>: (concrete features and clothes). (pose and view direction). (place and weather). Keep every object where it is and at the same size, add nothing new. No 3D render look, no text."
   - Photos: `face` + `fullbody` for a front view, `fullbody` + `face` for wide or from behind, `char_sheet` + `fullbody` for a side view.
   - Compare each one with its previs frame: size and place of objects, pose, number of limbs. The framing must match, since this frame is pinned.
   - Make all shots agree (lamps, boats, clothes). To fix a detail, repaint from `painted_full.png` with a crop of the right design as <Picture 2> and "Keep everything else in <Picture 1> exactly the same". Save the old one as `painted_v1*.png` first. H3-Image tends to enlarge small objects; if it does, paste the good small object back with ffmpeg and view the crop.
   - A repaint from the `_full` image comes out at model size. Scale it to the cutscene `size` before H3.

6. **Write `h3.json`, then render one shot as a test.** Start from the Harbor file.
   - `subject`, `retain`, `look`, `video_role`, `sound` are shared; each shot needs `summary` and `detailed`. Rewrite all of them for the new scene; Harbor's `video_role` and `look` mention rain and wind.
   - `ref_size` stays [704, 384]. 1056x576 ran out of memory.
   - Keep `video_role` saying the previs gives only camera, framing, timing and body motion.
   - In `detailed`: start with "The camera starts directly from the exact composition of the opening frame and ..., following <Video 1>". State what the body does in order, the mouth state and the limb count. No dial or motion LoRA.
   - Use `gray`, not `color`, when the body must follow Blender; otherwise the mode the user chose.
   - Test the shot with the largest face: `PY tools/h3_shot.py <project> S03 gray` in the background. Compare it with the previs side by side, send both. **Gate 2: wait for the OK.**

7. **Render the other shots**, one at a time, in the background. Check each with a strip of frames: camera path, identity, limbs, objects jumping or changing. On OOM: free ComfyUI's memory through its API (never restart it) and retry once; then report the result instead of looping. Redo a bad shot with another `--seed` and a `--tag`, and keep the old take.

8. **Rain (only if the scene needs it).** Stronger prompts did not add rain or wind in H3.
   - `BLENDER -b --factory-startup <project>/cutscene.blend --python-exit-code 1 -P tools/rain_pass.py -- <project> S01 --drops 20000` (about 40 s per shot)
   - `PY tools/rain_comp.py <project> S01 gray --strength 0.55` (0.8 was too strong)
   - Run `rain_pass.py` before any edit to `cutscene.json` or the blend; it uses that blend's camera. Don't delete `h3/*/rain/` until the user is happy with the strength: without it every strength change needs the 40 s pass again.
   - Say honestly that wind comes out uneven between shots. See "Strong wind" above.

9. **Join, check, report.** `PY tools/join.py <project> S01=gray S02=gray ...`
   - Confirm the frame count (sum of `frames`), the length and one loudness value per cut.
   - Make `final_compare.mp4` (Blender | H3) and `final_sheet.jpg`; view the sheet.
   - Write the recipe (folders, seeds, rain strength, problems) to the project's `README.md`.
   - Report with file links, what you checked, what is weak, and what you could not check from stills: motion smoothness and how the sound actually is.

## What H3 takes from Blender

The previs limits the body: with `gray` the figure moves as stiffly as the mannequin. Let the user choose, per film or per shot (`"ref"` in `h3.json`, rendered with `auto`):

| Mode | Follows Blender | Free | Use for |
|---|---|---|---|
| `gray` (`"ref": "motion"`, default) | camera, place, body motion | - | walking, acting, planned actions |
| `position` | camera, place, facing (a pillar) | body | dance and singing; recommended |
| `camera` | camera, set | body, place | one figure where the place does not matter |
| `free` | nothing (no reference video) | all | a wild shot; the camera comes from the text |

- Run `ref_pass.py` first for `position` and `camera`.
- These modes read `detailed_<mode>` or `detailed_open` (`summary_...` the same way). Describe the dance in the text, different for every shot: the same sentence gives the same pose at the same second. `free` must not mention `<Video 1>`.
- Check that the pillar never shows and the feet stay near the place.
- Start frames of wide shots: the painter makes the person too large. Try other seeds, "tiny and far away, one third of the picture height", and a crop of a small full-body figure as a reference.

**Strong wind.** Prompt text alone fades out during the shot. In this order: paint the start frames windblown, replace the character sheet (`"sheet"`) by one built from painted windblown faces and bodies, put the wind first in `detailed` and in `look`, and remove anything that says calm hair. Waist-up singing shots still calm down; another seed with the wind repeated next to the action did not bring it back, so say so instead of looping.

## Singing (lip sync)

Template: `examples/OutdoorStage/` (free dancing, `position`): `make_json.py`, `paint_all.py`, `make_h3.py`. Its times and lyrics cues belong to its own song; rewrite them.

- `cutscene.json`: `song.file`; every shot has `start` (seconds in the song) and `use` (frames kept in the film, at most the rendered 124). Cut 0.12 s before a bar line. Character `groove` sways to the beat. Set prims take `rot`, `rough` and `tex: [file, x, y, w, h]` (crop of a set photo on the front).
- `h3.json`: `song.h3_audio` (song with the vocals forward) and `song.text`. `h3_shot.py` cuts the shot's part and passes it as `<Audio 1>`; `join.py` trims to `use` and lays the original song underneath.
- Find the vocal times first. Singing shots: the mouth moves on every syllable, face toward the camera, the microphone never covers the mouth. Others: no vocals, lips closed. Mixed shots: say which seconds.
- Put the set photo into Blender as textures. Giving the whole set image to the painter overrides the composition; give it person photos only, cropped to the shot (`upper`, `thigh`, `fullbody`), or it zooms out.
- Words become objects: "globe lamps" drew an Earth globe, "number tiles" drew stray boards. Say "plain round white glass lamps".
- Test lip sync on a close-up, then check face strips every 10 frames for all shots.

## Don'ts

- Don't run H3 before the user has approved the previs.
- Don't monitor the GPU temperature, restart ComfyUI or download models without asking.
- Don't delete the user's files or older takes without asking. `frames/` and `frames_gray/` are generated and may be removed.
- Don't commit unless asked.
