"""blender -b --factory-startup -P build_cutscene.py -- <project dir> [--still N,N] [--no-render]
cutscene.json -> cutscene.blend (one timeline, markers switch the cameras) + frames/."""
import bpy, bmesh, json, math, sys, os
from mathutils import Vector, Matrix

args = sys.argv[sys.argv.index("--") + 1:]
proj = os.path.abspath(args[0])
cfg = json.load(open(os.path.join(proj, "cutscene.json"), encoding="utf-8"))
for s in cfg["shots"]:
    if s["frames"] % 17 != 5:
        raise SystemExit(f"{s['id']}: frames must be 17n+5 (H3 grid)")
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.fps = cfg["fps"]
sc.render.resolution_x, sc.render.resolution_y = cfg["size"]
sc.frame_start = 1
sc.frame_end = sum(s["frames"] for s in cfg["shots"])


def mat(color, emit=0, rough=.7, cache={}):
    k = (tuple(color), emit, rough)
    if k not in cache:
        m = bpy.data.materials.new("mat")
        m.use_nodes = True
        m.diffuse_color = (*color, 1)
        b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        b.inputs["Base Color"].default_value = (*color, 1)
        b.inputs["Roughness"].default_value = rough
        if emit:
            b.inputs["Emission Color"].default_value = (*color, 1)
            b.inputs["Emission Strength"].default_value = emit
        cache[k] = m
    return cache[k]


def tex_mat(d):
    """color + an image crop on the front: "tex": [file, x, y, w, h] in pixels from the top left."""
    f, x, y, w_, h_ = d["tex"]
    img = bpy.data.images.load(os.path.join(proj, f), check_existing=True)
    W, H_ = img.size
    m = mat(d["color"], d.get("emit", 0), d.get("rough", .7)).copy()
    t = m.node_tree
    b = next(n for n in t.nodes if n.type == "BSDF_PRINCIPLED")
    co, sep, com, im = (t.nodes.new(k) for k in ("ShaderNodeTexCoord", "ShaderNodeSeparateXYZ", "ShaderNodeCombineXYZ", "ShaderNodeTexImage"))
    im.image = img
    t.links.new(co.outputs["Generated"], sep.inputs[0])
    for src, dst, off, k in (("X", "X", x / W, w_ / W), ("Y" if d["type"] == "cylinder" else "Z", "Y", 1 - (y + h_) / H_, h_ / H_)):
        q = t.nodes.new("ShaderNodeMath")
        q.operation = "MULTIPLY_ADD"
        q.inputs[1].default_value, q.inputs[2].default_value = k, off
        t.links.new(sep.outputs[src], q.inputs[0])
        t.links.new(q.outputs[0], com.inputs[dst])
    t.links.new(com.outputs[0], im.inputs[0])
    t.links.new(im.outputs[0], b.inputs["Base Color"])
    return m


def link(name, data):
    o = bpy.data.objects.new(name, data)
    sc.collection.objects.link(o)
    return o


def prim(d, name):
    bm = bmesh.new()
    t = d["type"]
    if t in ("box", "ocean"):
        bmesh.ops.create_cube(bm, size=1)
    elif t == "sphere":
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=.5)
    else:
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=.5, radius2=.5 * d.get("top", 1), depth=1)
    if t != "box":
        for f in bm.faces:
            f.smooth = len(f.verts) <= 4
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(tex_mat(d) if "tex" in d else mat(d["color"], d.get("emit", 0), d.get("rough", .7)))
    o = link(name, me)
    o.location = d["loc"]
    o.scale = d["size"]
    o.rotation_euler = [math.radians(v) for v in d.get("rot", (0, 0, 0))]
    return o


for d in cfg["set"]:
    if "parts" in d:
        root = link(d["name"], None)
        for i, p in enumerate(d["parts"]):
            prim(p, f"{d['name']}_{i}").parent = root
    else:
        rx, ry, rz, n = d.get("repeat", [0, 0, 0, 1])
        for i in range(n):
            root = prim(d, d["name"])
            root.location = Vector(d["loc"]) + Vector((rx, ry, rz)) * i
    if d.get("type") == "ocean":
        sea = root.modifiers.new("Ocean", "OCEAN")
        sea.geometry_mode = "GENERATE"
        sea.repeat_x = sea.repeat_y = d["repeat_tiles"]
        sea.spatial_size = d["tile"]
        sea.resolution = sea.viewport_resolution = 10
        sea.wave_scale, sea.choppiness, sea.wind_velocity = d["wave"], 1.0, 14
        for fr in (1, sc.frame_end):
            sea.time = fr / cfg["fps"] * d.get("rate", 1)
            sea.keyframe_insert("time", frame=fr)
    if "sway" in d:  # boat rocking; the travel keys stay as they are
        w_ = d["sway"]
        for fr in range(1, sc.frame_end + 1, 6):
            q = fr / cfg["fps"]
            root.rotation_euler = (math.radians(w_["pitch"]) * math.sin(q*1.7), math.radians(w_["roll"]) * math.sin(q*1.25 + 1), 0)
            root.keyframe_insert("rotation_euler", frame=fr)
            for o in root.children:
                o.delta_location = (0, 0, w_["heave"] * math.sin(q*1.5 + .6))
                o.keyframe_insert("delta_location", frame=fr)
    for k in d.get("keys", []):
        root.location = k["loc"]
        root.keyframe_insert("location", frame=k["f"])

# ---- mannequin: rest pose faces -Y, left is +X ----
H = 1.65


def build_char(c):
    S = c["height"] / H
    J = {"pelvis": ((0, 0, .92), (0, 0, 1.04), None), "chest": ((0, 0, 1.04), (0, 0, 1.36), "pelvis"),
         "neck": ((0, 0, 1.36), (0, 0, 1.43), "chest"), "head": ((0, 0, 1.43), (0, 0, 1.65), "neck")}
    for s, x in (("L", 1), ("R", -1)):
        J[f"upper_arm.{s}"] = ((x*.17, 0, 1.32), (x*.20, 0, 1.05), "chest")
        J[f"forearm.{s}"] = ((x*.20, 0, 1.05), (x*.21, -.01, .81), f"upper_arm.{s}")
        J[f"hand.{s}"] = ((x*.21, -.01, .81), (x*.21, -.02, .65), f"forearm.{s}")
        J[f"thigh.{s}"] = ((x*.09, 0, .92), (x*.09, -.02, .50), "pelvis")
        J[f"shin.{s}"] = ((x*.09, -.02, .50), (x*.09, 0, .08), f"thigh.{s}")
        J[f"foot.{s}"] = ((x*.09, 0, .08), (x*.09, -.15, .03), f"shin.{s}")
    ad = bpy.data.armatures.new(c["name"])
    arm = link(c["name"], ad)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for n, (a, b, p) in J.items():
        e = ad.edit_bones.new(n)
        e.head = Vector(a)*S
        e.tail = Vector(b)*S
        if p:
            e.parent = ad.edit_bones[p]
        e.align_roll((0, 0, 1) if n.startswith("foot") else (0, -1, 0))
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.show_in_front = True
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"

    bm = bmesh.new()
    dl = bm.verts.layers.deform.verify()
    names = list(J)

    def add(bone, m, kind="sphere", mi=0, r1=.5, r2=.5):
        if kind == "sphere":
            ret = bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=1, matrix=m)
        else:
            ret = bmesh.ops.create_cone(bm, cap_ends=True, segments=20, radius1=r1, radius2=r2, depth=1, matrix=m)
        for v in ret["verts"]:
            v[dl][names.index(bone)] = 1
        for f in {f for v in ret["verts"] for f in v.link_faces}:
            f.smooth = True
            f.material_index = mi

    def ball(bone, p, s, mi=0):
        s = (s,)*3 if isinstance(s, float) else s
        add(bone, Matrix.Translation(Vector(p)*S) @ Matrix.Diagonal((*[q*S for q in s], 1)), mi=mi)

    def limb(bone, r1, r2, mi=0):
        a, b = Vector(J[bone][0])*S, Vector(J[bone][1])*S
        d = b-a
        m = Matrix.Translation((a+b)/2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4() @ Matrix.Diagonal((1, 1, d.length, 1))
        add(bone, m, "cone", mi, r1*S, r2*S)
        ball(bone, J[bone][0], r1, mi)
        ball(bone, J[bone][1], r2, mi)

    SK, CO, DK = 0, 1, 2
    ball("pelvis", (0, 0, .95), (.155, .11, .13), DK)
    ball("chest", (0, 0, 1.22), (.17, .115, .19), CO)
    ball("chest", (0, 0, 1.07), (.135, .10, .12), CO)
    limb("neck", .05, .05, SK)
    ball("head", (0, -.01, 1.54), (.078, .098, .115), SK)
    HR, SH = 3, 4
    if c.get("hair") == "bob":
        ball("head", (0, .022, 1.565), (.098, .102, .108), HR)
        for x in (1, -1):
            ball("head", (x*.075, .01, 1.50), (.04, .075, .085), HR)
        ball("head", (0, .07, 1.50), (.085, .05, .085), HR)
        ball("head", (0, -.062, 1.612), (.07, .045, .035), HR)
    else:
        ball("head", (0, .018, 1.565), (.088, .095, .105), HR)
    ball("head", (0, -.11, 1.53), (.012, .016, .02), SK)    # nose
    for x in (1, -1):
        ball("head", (x*.034, -.098, 1.555), (.026, .012, .02) if c.get("glasses") else .012, HR)
    for s, x in (("L", 1), ("R", -1)):
        limb(f"upper_arm.{s}", .055, .043, CO)
        limb(f"forearm.{s}", .042, .03, CO)
        ball(f"hand.{s}", (x*.21, -.015, .74), (.02, .042, .085), SK)
        limb(f"thigh.{s}", .085, .055, DK)
        limb(f"shin.{s}", .055, .038, DK)
        ball(f"foot.{s}", (x*.09, -.07, .045), (.045, .13, .045), SH)
        ball(f"foot.{s}", (x*.09, .02, .05), (.04, .05, .05), SH)
    me = bpy.data.meshes.new(c["name"]+"_body")
    bm.to_mesh(me)
    bm.free()
    for m in (mat((.80, .58, .46)), mat(c["color"]), mat(c.get("pants", (.06, .055, .07))),
              mat(c.get("hair_color", (.06, .055, .07))), mat(c.get("shoes", (.06, .055, .07)))):
        me.materials.append(m)
    body = link(c["name"]+"_body", me)
    for n in names:
        body.vertex_groups.new(name=n)
    body.parent = arm
    body.modifiers.new("Armature", "ARMATURE").object = arm

    feet = {}
    for s in "LR":
        e = link(f"{c['name']}_foot_ctrl.{s}", None)
        e.empty_display_size = .15
        r = link(f"{c['name']}_foot_rot.{s}", None)
        r.parent = e
        r.empty_display_size = .02
        r.rotation_euler = ad.bones[f"foot.{s}"].matrix_local.to_euler()
        k = arm.pose.bones[f"shin.{s}"].constraints.new("IK")
        k.target = e
        k.chain_count = 2
        k = arm.pose.bones[f"foot.{s}"].constraints.new("COPY_ROTATION")
        k.target = r
        feet[s] = e

    # ---- animation ----
    def kb(n, f, rot):
        pb = arm.pose.bones[n]
        pb.rotation_euler = [math.radians(v) for v in rot]
        pb.keyframe_insert("rotation_euler", frame=f)

    def kbody(f, p, z, phi):
        arm.location = (p.x, p.y, z*S)
        arm.rotation_euler = (0, 0, phi)
        arm.keyframe_insert("location", frame=f)
        arm.keyframe_insert("rotation_euler", frame=f)

    def kfoot(s, f, p, lift, pitch, phi):
        x = (.09 if s == "L" else -.09)*S
        e = feet[s]
        e.location = (p.x + x*math.cos(phi), p.y + x*math.sin(phi), (.08+lift)*S)
        e.rotation_euler = (math.radians(pitch), 0, phi)
        e.keyframe_insert("location", frame=f)
        e.keyframe_insert("rotation_euler", frame=f)

    def rest_arms(f):
        for s, sg in (("L", 1), ("R", -1)):
            kb(f"upper_arm.{s}", f, (4, 0, sg*6))
            kb(f"forearm.{s}", f, (12, 0, 0))

    pos = Vector(c["start"]).to_3d()
    phi = math.radians(c.get("heading", 180))
    if not c.get("walks"):
        kbody(1, pos, -.005, phi)
        for s in "LR":
            kfoot(s, 1, pos, 0, 0, phi)
        rest_arms(1)
    for w in c.get("walks", []):
        to = Vector(w["to"]).to_3d()
        d = to-pos
        D = d.length
        u = d/D
        n = max(2, round(D/(.68*S)))
        L = D/n
        T = cfg["fps"]*L/w["speed"]
        f0 = w["f"]
        a = math.atan2(d.x, -d.y)
        phi = a + 2*math.pi*round((phi-a)/(2*math.pi))
        P = lambda q: pos+u*q
        kbody(f0, pos, -.005, phi)
        rest_arms(f0)
        at = {"L": 0.0, "R": 0.0}
        for s in "LR":
            kfoot(s, f0, pos, 0, 0, phi)
        for i in range(n+1):
            s = "LR"[i % 2]
            t0 = f0+i*T
            t1 = t0+T
            a0 = at[s]
            a1 = min(D, (i+1.5)*L)
            if i:
                kfoot(s, t0-.35*T, P(a0), 0, 0, phi)
                kfoot(s, t0, P(a0+.05*S), .07, 32, phi)
            kfoot(s, t0+.5*T, P((a0+a1)/2), .09, 18, phi)
            flat = a1 >= D
            kfoot(s, t1, P(a1), 0 if flat else .02, 0 if flat else -14, phi)
            kfoot(s, t1+.18*T, P(a1), 0, 0, phi)
            at[s] = a1
            if i < n:
                kbody(t0+.5*T, P((i+.5)*L), -.015, phi)
                kbody(t1, P((i+1)*L), -.05 if i < n-1 else -.03, phi)
                if i < n-1:
                    for q, sg in (("L", 1), ("R", -1)):
                        sw = -1 if q == s else 1
                        kb(f"upper_arm.{q}", t1, (sw*22+2, 0, sg*6))
                        kb(f"forearm.{q}", t1, (20+sw*8, 0, 0))
                    kb("chest", t1, (3, (-5 if s == "L" else 5), 0))
        e = f0+(n+1.4)*T
        kbody(e, to, -.005, phi)
        rest_arms(e)
        kb("chest", e, (0, 0, 0))
        pos = to
        print(f"{c['name']}: walk ends at frame {e:.0f}, {n} steps")
    # sway on the beat, per shot block: chest rolls and the hips shift left/right, with a dip on every beat
    for g in c.get("groove", []):
        k, side, f = g.get("amount", 1), 1, g["beat0"]
        while f > g["f0"]:
            f -= g["beat"]
            side = -side
        while f <= g["f1"] + g["beat"]:
            for q, z in ((0, -.028), (.5, -.004)):
                fr = f + q * g["beat"]
                if not g["f0"] <= fr <= g["f1"]:
                    continue
                x = side * (.03 if q == 0 else 0) * k
                kbody(fr, pos + Vector((x*math.cos(phi), x*math.sin(phi), 0)), z * k, phi)
                kb("chest", fr, (2, 0, side * (4 if q == 0 else 0) * k))
            f += g["beat"]
            side = -side
    for p in c.get("poses", []):
        for b, r in p["bones"].items():
            kb(b, p["f"], r)
    return arm


chars = {c["name"]: build_char(c) for c in cfg["characters"]}

# ---- light / cameras ----
w = cfg["world"]
wd = bpy.data.worlds.new("World")
sc.world = wd
wd.use_nodes = True
bg = next(n for n in wd.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs[0].default_value = (*w["color"], 1)
bg.inputs[1].default_value = w["strength"]
if "horizon" in w:  # sky gradient by view direction
    nt = wd.node_tree
    tc, sx, cr = (nt.nodes.new(x) for x in ("ShaderNodeTexCoord", "ShaderNodeSeparateXYZ", "ShaderNodeValToRGB"))
    cr.color_ramp.elements[0].color = (*w["horizon"], 1)
    cr.color_ramp.elements[1].color = (*w["color"], 1)
    cr.color_ramp.elements[1].position = .45
    nt.links.new(tc.outputs["Generated"], sx.inputs[0])
    nt.links.new(sx.outputs["Z"], cr.inputs[0])
    nt.links.new(cr.outputs[0], bg.inputs[0])
sun = bpy.data.lights.new("Sun", "SUN")
sun.energy = w["sun_energy"]
sun.color = w["sun_color"]
sun.angle = .05
link("Sun", sun).rotation_euler = [math.radians(a) for a in w["sun_dir"]]
f = 1
for s in cfg["shots"]:
    cd = bpy.data.cameras.new("CAM_"+s["id"])
    cam = link("CAM_"+s["id"], cd)
    cd.clip_end = 600
    at = lambda t: f + t*(s["frames"]-1)
    for k in s["camera"]:
        cam.location = k["pos"]
        cam.keyframe_insert("location", frame=at(k["t"]))
        cd.lens = k["lens"]
        cd.keyframe_insert("lens", frame=at(k["t"]))
    tr = cam.constraints.new("TRACK_TO")
    tr.track_axis = "TRACK_NEGATIVE_Z"
    tr.up_axis = "UP_Y"
    if isinstance(s["look"], str):
        n, b = s["look"].split(":")
        tr.target = chars[n]
        tr.subtarget = b
        tr.head_tail = .4
    else:
        e = link("LOOK_"+s["id"], None)
        tr.target = e
        for k in s["look"]:
            e.location = k["pos"]
            e.keyframe_insert("location", frame=at(k["t"]))
    m = sc.timeline_markers.new(s["id"], frame=f)
    m.camera = cam
    if f == 1:
        sc.camera = cam
    f += s["frames"]
sc.render.engine = "BLENDER_EEVEE"
sc.eevee.taa_render_samples = 16
sc.view_settings.view_transform = "Standard"
ims = sc.render.image_settings
ims.file_format = "JPEG"
ims.quality = 95
frames = os.path.join(proj, "frames", "")
os.makedirs(frames, exist_ok=True)
sc.render.filepath = "//frames/"
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(proj, "cutscene.blend"))
if "--still" in args:
    for x in args[args.index("--still")+1].split(","):
        sc.frame_set(int(x))
        sc.render.filepath = os.path.join(proj, "stills", f"{int(x):04d}.jpg")
        bpy.ops.render.render(write_still=True)
elif "--no-render" not in args:
    bpy.ops.render.render(animation=True)
if "--gray" in args:  # untextured version for H3
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from gray import to_gray
    to_gray(sc)
    sc.render.filepath = os.path.join(proj, "frames_gray", "")
    bpy.ops.render.render(animation=True)
