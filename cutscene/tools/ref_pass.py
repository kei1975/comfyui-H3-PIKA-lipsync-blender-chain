"""Reference videos with less in them than the gray pass, for h3_shot.py:
blender -b --factory-startup <project>/cutscene.blend --python-exit-code 1 -P ref_pass.py -- <project> camera|position S09 [S13 ...]
camera: the set and the camera path, no mannequin. position: the same plus a plain pillar where each mannequin stands (its place, height and
facing over time, no pose). Writes <project>/shots_<kind>/Sxx.mp4 in the look of the gray pass. The blend is not saved."""
import bpy, json, math, os, subprocess, sys
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gray import to_gray

a = sys.argv[sys.argv.index("--") + 1:]
proj, kind, shots = os.path.abspath(a[0]), a[1], a[2:]
assert kind in ("camera", "position"), kind
cfg = json.load(open(os.path.join(proj, "cutscene.json"), encoding="utf-8"))
assert set(shots) <= {s["id"] for s in cfg["shots"]}, shots
sc = bpy.context.scene
rigs = [bpy.data.objects[c["name"]] for c in cfg["characters"]]
for o in bpy.data.objects:            # the mannequin: the rig, its children and everything skinned to it
    if o in rigs or o.parent in rigs or any(m.type == "ARMATURE" and m.object in rigs for m in o.modifiers):
        o.hide_render = True
to_gray(sc)
sc.timeline_markers.clear()           # markers would switch the camera


def pillar(height):
    m = bpy.data.materials.new("pillar")
    m.use_nodes = True
    next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Base Color"].default_value = (.75, .75, .75, 1)
    bpy.ops.mesh.primitive_cylinder_add(radius=.2, depth=height)
    p = bpy.context.object
    bpy.ops.mesh.primitive_cone_add(radius1=.07, depth=.2, location=(0, -.28, height * .4), rotation=(math.radians(90), 0, 0))
    nose = bpy.context.object         # shows the facing (the mannequin faces -Y at rest)
    nose.parent = p
    for o in (p, nose):
        o.data.materials.append(m)
    return p


marks = [(r, pillar(c["height"]), c["height"]) for r, c in zip(rigs, cfg["characters"])] if kind == "position" else []
dst = os.path.join(proj, "shots_" + kind)
os.makedirs(dst, exist_ok=True)
f = 1
for s in cfg["shots"]:
    if s["id"] in shots:
        sc.camera = bpy.data.objects["CAM_" + s["id"]]
        for x in range(f, f + s["frames"]):
            sc.frame_set(x)
            for r, p, h in marks:     # mean of the feet, so leaning and swaying of the body do not move it
                pb = r.pose.bones
                q = [r.matrix_world @ pb["foot." + k].head for k in "LR"]
                c = (q[0] + q[1]) / 2
                side = q[0] - q[1]    # right foot to left foot = +X of a figure that faces -Y
                p.location = (c.x, c.y, min(q[0].z, q[1].z) - .08 + h / 2)
                yaw = math.atan2(side.y, side.x)
                p.rotation_euler = (0, 0, yaw)
                p.keyframe_insert("location", frame=x)
                p.keyframe_insert("rotation_euler", frame=x)
        sc.frame_start, sc.frame_end = f, f + s["frames"] - 1
        fr = os.path.join(proj, "frames_" + kind, s["id"], "")
        sc.render.filepath = fr
        bpy.ops.render.render(animation=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(cfg["fps"]), "-start_number", str(f), "-i", fr + "%04d.jpg",
                        "-frames:v", str(s["frames"]), "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p",
                        os.path.join(dst, s["id"] + ".mp4")], check=True)
    f += s["frames"]
