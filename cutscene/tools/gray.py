"""Untextured gray look for the H3 reference videos."""
import bpy, math


def to_gray(sc):
    for m in bpy.data.materials:  # keep light/dark separation, drop the colours
        b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        for lk in list(b.inputs["Base Color"].links):
            m.node_tree.links.remove(lk)
        c = b.inputs["Base Color"].default_value
        v = .12 + .5 * min(1, (.3*c[0] + .59*c[1] + .11*c[2]) ** .6)
        b.inputs["Base Color"].default_value = (v, v, v, 1)
        b.inputs["Emission Strength"].default_value = 0
    fill = bpy.data.lights.new("Fill", "SUN")  # from the opposite side, so faces are not flat
    fill.energy = 1.3
    fill.use_shadow = False
    o = bpy.data.objects.new("Fill", fill)
    sc.collection.objects.link(o)
    o.rotation_euler = (math.radians(50), 0, math.radians(150))
    wd = sc.world
    bg = next(n for n in wd.node_tree.nodes if n.type == "BACKGROUND")
    for lk in list(wd.node_tree.links):
        if lk.to_node == bg:
            wd.node_tree.links.remove(lk)
    bg.inputs[0].default_value = (.62, .64, .67, 1)
    bg.inputs[1].default_value = .4
    sun = bpy.data.objects["Sun"].data
    sun.color = (1, 1, 1)
    sun.energy = 2
