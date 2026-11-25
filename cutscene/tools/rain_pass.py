"""Rain layer for one shot: blender -b --factory-startup <project>/cutscene.blend --python-exit-code 1 -P rain_pass.py -- <project> <shot> [--drops 9000]
White streaks on black, seen from the shot's camera; the mannequin and the set are black so they hide rain behind them.
Writes <project>/h3/<shot>/rain/%04d.png (frame 1 = the shot's first frame). Composite with rain_comp.py."""
import bpy, json, os, random, sys
from mathutils import Vector

a = sys.argv[sys.argv.index("--") + 1:]
proj, shot = os.path.abspath(a[0]), a[1]
N = int(a[a.index("--drops") + 1]) if "--drops" in a else 9000
cfg = json.load(open(os.path.join(proj, "cutscene.json"), encoding="utf-8"))
f0, n = 1, 0
for s in cfg["shots"]:
    if s["id"] == shot:
        n = s["frames"]
        break
    f0 += s["frames"]
sc = bpy.context.scene
cam = bpy.data.objects["CAM_" + shot]
sc.camera = cam
sc.timeline_markers.clear()          # markers would switch the camera
for o in bpy.data.objects:            # water must not hide rain
    if o.name == "sea" or any(m.type == "OCEAN" for m in o.modifiers):
        o.hide_render = True


def flat(name, v):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    t = m.node_tree
    t.nodes.clear()
    e, o = t.nodes.new("ShaderNodeEmission"), t.nodes.new("ShaderNodeOutputMaterial")
    e.inputs[0].default_value = (v, v, v, 1)
    t.links.new(e.outputs[0], o.inputs[0])
    return m


black = flat("black", 0)
for o in bpy.data.objects:
    if o.type == "MESH":
        o.data.materials.clear()
        o.data.materials.append(black)
        for p in o.data.polygons:
            p.material_index = 0
bg = next(x for x in sc.world.node_tree.nodes if x.type == "BACKGROUND")
for lk in list(sc.world.node_tree.links):
    if lk.to_node == bg:
        sc.world.node_tree.links.remove(lk)
bg.inputs[0].default_value = (0, 0, 0, 1)
sc.view_settings.view_transform = "Raw"
sc.render.image_settings.file_format = "PNG"
sc.eevee.taa_render_samples = 32

# drops live in a world-space box around the camera path and wrap around in it
pts = []
for f in (f0, f0 + n - 1):
    sc.frame_set(f)
    pts.append(cam.matrix_world.translation.copy())
fwd = cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))
c = (pts[0] + pts[1]) / 2 + Vector((fwd.x, fwd.y, 0)).normalized() * 8
size = Vector((26, 26, 12))
lo = Vector((c.x - 13, c.y - 13, -1.6))
rnd = random.Random(7)
drops = [(Vector([rnd.random() * size[i] for i in range(3)]), rnd.uniform(.85, 1.15)) for _ in range(N)]
vel = Vector((-4.5, -1.0, -9.5))
# three brightness levels by distance
mats = [flat("near", .55), flat("mid", .42), flat("far", .30)]
me = bpy.data.meshes.new("rain")
ob = bpy.data.objects.new("rain", me)
sc.collection.objects.link(ob)
for m in mats:
    me.materials.append(m)
out = os.path.join(proj, "h3", shot, "rain")
os.makedirs(out, exist_ok=True)
for i in range(n):
    sc.frame_set(f0 + i)
    mw = cam.matrix_world.copy()
    eye, inv, t = mw.translation, mw.inverted(), i / cfg["fps"]
    px = 36 / cam.data.lens / cfg["size"][0]       # width of one pixel at distance 1
    V, F, M = [], [], []
    for p, k in drops:
        q = p + vel * (k * t)
        q = lo + Vector([q[j] % size[j] for j in range(3)])
        z = -(inv @ q).z
        if z < 1.2:
            continue
        tail = q - vel * (k / 55)
        side = (tail - q).cross(q - eye).normalized() * max(.0022, 1.1 * px * z) / 2
        b = len(V)
        V += [q - side, q + side, tail + side, tail - side]
        F.append((b, b + 1, b + 2, b + 3))
        M.append(0 if z < 4 else 1 if z < 9 else 2)
    me.clear_geometry()
    me.from_pydata(V, [], F)
    me.polygons.foreach_set("material_index", M)
    me.update()
    sc.render.filepath = os.path.join(out, "%04d.png" % (i + 1))
    bpy.ops.render.render(write_still=True)
