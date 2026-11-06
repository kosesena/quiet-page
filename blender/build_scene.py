"""The Quiet Page — book cafe diorama.

Re-run headless (does not touch any open Blender session):
  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
      --python build_scene.py -- [--no-render]

Outputs next to this file: quiet-page.blend, quiet-page.glb,
preview-overview.png, preview-ivy.png, preview-gate.png
"""
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

OUT = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
DO_RENDER = "--no-render" not in ARGS
random.seed(7)

# ---------------------------------------------------------------- reset
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "QuietPage"


# ---------------------------------------------------------------- materials
def srgb(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hexcol(h):
    h = h.lstrip("#")
    return tuple(srgb(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))


MATS = {}


def mat(name, hexc, rough=0.65, emit=None, emit_strength=0.0, alpha=1.0, metal=0.0):
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    col = hexcol(hexc)
    bsdf.inputs["Base Color"].default_value = (*col, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    m.diffuse_color = (*col, alpha)
    if emit:
        ec = hexcol(emit)
        for key in ("Emission Color", "Emission"):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = (*ec, 1.0)
                break
        bsdf.inputs["Emission Strength"].default_value = emit_strength
    if alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = alpha
        for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
            try:
                setattr(m, attr, val)
            except Exception:
                pass
        try:
            m.use_backface_culling = False
        except Exception:
            pass
    MATS[name] = m
    return m


M = {
    "white": mat("M_White", "#f4f3f0", 0.7),
    "platform": mat("M_Platform", "#fbfaf8", 0.75),
    "offwhite": mat("M_OffWhite", "#e8e5df", 0.7),
    "wood": mat("M_Wood", "#d9c7ad", 0.7),
    "wood_dark": mat("M_WoodDark", "#a88a6a", 0.7),
    "grey": mat("M_Grey", "#c9c9c7", 0.6),
    "graphite": mat("M_Graphite", "#3b3f45", 0.5),
    "steel": mat("M_Steel", "#b8bcc2", 0.35, metal=0.6),
    "green": mat("M_MutedGreen", "#6b8a74", 0.7),
    "green_dark": mat("M_MutedGreenDark", "#4f6a57", 0.7),
    "walnut": mat("M_Walnut", "#6e4b34", 0.55),
    "slate": mat("M_ChalkSlate", "#2f3534", 0.85),
    "chalk": mat("M_Chalk", "#e9e1cc", 0.9),
    "brass": mat("M_ShadeOchre", "#c99a5b", 0.45, metal=0.2),
    "bulb": mat("M_WarmBulb", "#ffe2b0", 0.3, emit="#ffc77a", emit_strength=8.0),
    "leaf": mat("M_Leaf", "#5e8560", 0.75),
    "leaf_light": mat("M_LeafLight", "#7b9d6f", 0.75),
    "soil": mat("M_Soil", "#4a3a2c", 0.95),
    "pastry": mat("M_Pastry", "#d9a15b", 0.6),
    "pastry_dark": mat("M_PastryDark", "#8a5a3c", 0.6),
    "glaze": mat("M_Glaze", "#eedcc0", 0.5),
    "rust": mat("M_Rust", "#b0644a", 0.7),
    "navy": mat("M_Navy", "#33415e", 0.65),
    "cream": mat("M_Cream", "#efe5cf", 0.7),
    "burgundy": mat("M_Burgundy", "#7a2e3b", 0.65),
    "apron": mat("M_ApronBrown", "#7a573f", 0.75),
    "skin": mat("M_Skin", "#efcfb6", 0.6),
    "hair_dark": mat("M_HairDark", "#4a3a2f", 0.7),
    "hair_grey": mat("M_HairGrey", "#bdbbb8", 0.7),
    "hair_auburn": mat("M_HairAuburn", "#8a5a3c", 0.7),
    "eye": mat("M_Eye", "#2a2a2e", 0.4),
    "pants": mat("M_PantsGrey", "#5d6168", 0.7),
    "pants_dark": mat("M_PantsDark", "#3c4049", 0.7),
    "hood": mat("M_HoodSlate", "#626873", 0.8),
    "hood_inside": mat("M_HoodShadow", "#16171a", 0.9),
    "ink": mat("M_Ink", "#1b1f3a", 0.3),
    "paper": mat("M_Paper", "#fbf8f1", 0.8),
    "glass": mat("M_Glass", "#dfeef5", 0.05, alpha=0.18),
    "alarm": mat("M_AlarmRed", "#e0322a", 0.4, emit="#ff2a1f", emit_strength=4.0, alpha=0.45),
    "blue_led": mat("M_StatusBlue", "#2f7bff", 0.3, emit="#2f7bff", emit_strength=6.0),
    "amber": mat("M_GateAmber", "#e07a1f", 0.3, emit="#ff7a0a", emit_strength=2.2),
    "screen": mat("M_Screen", "#26303d", 0.25, emit="#8fb4d9", emit_strength=0.6),
    "cup": mat("M_Cup", "#ffffff", 0.4),
    "coffee": mat("M_Coffee", "#5a3b28", 0.3),
}


# ---------------------------------------------------------------- collections & objects
def make_coll(name):
    c = bpy.data.collections.new(name)
    scene.collection.children.link(c)
    return c


def link(obj, coll):
    coll.objects.link(obj)
    return obj


def empty(name, coll, loc=(0, 0, 0), rot_z=0.0, parent=None):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "PLAIN_AXES"
    e.empty_display_size = 0.2
    e.location = loc
    e.rotation_euler = (0, 0, math.radians(rot_z))
    link(e, coll)
    if parent:
        e.parent = parent
    return e


def finish_mesh(bm, name, coll, material, loc, parent, smooth_angle=None, rot=None):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth_angle is not None:
        for p in me.polygons:
            p.use_smooth = True
        try:
            me.set_sharp_from_angle(angle=math.radians(smooth_angle))
        except Exception:
            pass
    me.materials.append(material)
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    if rot:
        ob.rotation_euler = [math.radians(a) for a in rot]
    link(ob, coll)
    if parent:
        ob.parent = parent
    return ob


def box(name, coll, size, loc, material, bevel=0.012, segs=2, parent=None, rot=None, smooth=30):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=list(bm.edges) + list(bm.verts), offset=bevel,
                        segments=segs, affect="EDGES", profile=0.5)
    return finish_mesh(bm, name, coll, material, loc, parent, smooth, rot)


def rounded_slab(name, coll, sx, sy, sz, radius, loc, material, parent=None, edge_bevel=0.05):
    """Box with rounded vertical corners + soft top/bottom edge."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector((sx, sy, sz)), verts=bm.verts)
    vert_edges = [e for e in bm.edges
                  if abs(e.verts[0].co.z - e.verts[1].co.z) > 1e-4]
    bmesh.ops.bevel(bm, geom=vert_edges, offset=radius, segments=10,
                    affect="EDGES", profile=0.5)
    horiz = [e for e in bm.edges
             if abs(e.verts[0].co.z - e.verts[1].co.z) < 1e-4
             and len(e.link_faces) == 2
             and any(abs(f.normal.z) > 0.9 for f in e.link_faces)]
    bmesh.ops.bevel(bm, geom=horiz, offset=edge_bevel, segments=4,
                    affect="EDGES", profile=0.5)
    return finish_mesh(bm, name, coll, material, loc, parent, 40)


def cyl(name, coll, r, depth, loc, material, segs=20, parent=None, rot=None, r2=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs,
                          radius1=r, radius2=r if r2 is None else r2, depth=depth)
    return finish_mesh(bm, name, coll, material, loc, parent, 40, rot)


def sphere(name, coll, r, loc, material, scale=(1, 1, 1), parent=None, segs=20, rings=12,
           cut_below=None):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=r)
    if cut_below is not None:
        doomed = [v for v in bm.verts if v.co.z < cut_below * r - 1e-5]
        bmesh.ops.delete(bm, geom=doomed, context="VERTS")
        edges = [e for e in bm.edges if e.is_boundary]
        if edges:
            bmesh.ops.holes_fill(bm, edges=edges, sides=0)
    bmesh.ops.scale(bm, vec=Vector(scale), verts=bm.verts)
    return finish_mesh(bm, name, coll, material, loc, parent, 60)


def capsule(name, coll, r, length, loc, material, parent=None, rot=None, sy=1.0, sx=1.0,
            segs=18, rings=12):
    """Capsule along local Z, total length = length (incl. caps), centred on loc."""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=r)
    half = max(0.0, length / 2 - r)
    for v in bm.verts:
        if v.co.z > 1e-6:
            v.co.z += half
        elif v.co.z < -1e-6:
            v.co.z -= half
    bmesh.ops.scale(bm, vec=Vector((sx, sy, 1.0)), verts=bm.verts)
    return finish_mesh(bm, name, coll, material, loc, parent, 60, rot)


def capsule_between(name, coll, r, a, b, material, parent=None):
    a, b = Vector(a), Vector(b)
    d = b - a
    ob = capsule(name, coll, r, d.length + 2 * r, (a + b) / 2, material, parent)
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d.normalized())
    return ob


def torus(name, coll, R, r, loc, material, parent=None, rot=(90, 0, 0)):
    bm = bmesh.new()
    seg_major, seg_minor = 20, 6
    verts = []
    for i in range(seg_major):
        u = 2 * math.pi * i / seg_major
        ring = []
        for j in range(seg_minor):
            v = 2 * math.pi * j / seg_minor
            x = (R + r * math.cos(v)) * math.cos(u)
            y = (R + r * math.cos(v)) * math.sin(u)
            z = r * math.sin(v)
            ring.append(bm.verts.new((x, y, z)))
        verts.append(ring)
    for i in range(seg_major):
        for j in range(seg_minor):
            a = verts[i][j]
            b = verts[(i + 1) % seg_major][j]
            c = verts[(i + 1) % seg_major][(j + 1) % seg_minor]
            d = verts[i][(j + 1) % seg_minor]
            bm.faces.new((a, b, c, d))
    return finish_mesh(bm, name, coll, material, loc, parent, 60, rot)


# ================================================================ 1. Platform
PLAT_T = 0.32
c_plat = make_coll("Platform")
platform = rounded_slab("Platform", c_plat, 6.0, 4.0, PLAT_T, 0.45, (0, 0, -PLAT_T / 2),
                        M["platform"], edge_bevel=0.06)

# ================================================================ 2. Shelves
c_sh = make_coll("Shelves")
shelves = empty("Shelves", c_sh)
BOOK_COLS = [M["green"], M["rust"], M["navy"], M["cream"]]


def bookshelf(tag, x, y):
    root = empty(f"Shelf_{tag}", c_sh, (x, y, 0), parent=shelves)
    W, D, H, T = 0.92, 0.34, 1.86, 0.035
    box(f"Shelf_{tag}_SideL", c_sh, (T, D, H), (-W / 2 + T / 2, 0, H / 2), M["white"], parent=root)
    box(f"Shelf_{tag}_SideR", c_sh, (T, D, H), (W / 2 - T / 2, 0, H / 2), M["white"], parent=root)
    box(f"Shelf_{tag}_Back", c_sh, (W - 2 * T, 0.02, H - 0.02), (0, D / 2 - 0.01, H / 2),
        M["offwhite"], bevel=0.004, parent=root)
    levels = [0.06, 0.50, 0.94, 1.38, H - T / 2]
    for i, z in enumerate(levels):
        box(f"Shelf_{tag}_Board{i}", c_sh, (W - 2 * T + 0.002, D, T), (0, 0, z), M["white"],
            parent=root)
    # books on the 4 lower compartments
    for li, z0 in enumerate(levels[:-1]):
        z_base = z0 + T / 2
        xcur = -W / 2 + T + 0.02
        xmax = W / 2 - T - 0.02
        n = 0
        while True:
            w = random.choice([0.035, 0.04, 0.045, 0.05, 0.06])
            if xcur + w > xmax - (0.12 if li % 2 == 0 else 0.0):
                break
            h = random.choice([0.26, 0.29, 0.31, 0.33, 0.35])
            d = random.choice([0.22, 0.24, 0.26])
            col = BOOK_COLS[(n + li * 2 + (1 if tag == "B" else 0)) % 4] \
                if random.random() > 0.25 else random.choice(BOOK_COLS)
            box(f"Book_{tag}{li}_{n}", c_sh, (w - 0.004, d, h),
                (xcur + w / 2, -0.02, z_base + h / 2), col, bevel=0.004, segs=1, parent=root)
            xcur += w
            n += 1
        if li % 2 == 0:  # a small horizontal stack fills the gap -> calm rhythm
            for k in range(3):
                box(f"Book_{tag}{li}_stack{k}", c_sh, (0.10, 0.2, 0.035),
                    (xmax - 0.055, -0.03, z_base + 0.0175 + k * 0.036),
                    BOOK_COLS[(k + li) % 4], bevel=0.004, segs=1, parent=root)
    return root


bookshelf("A", -2.35, 1.62)
bookshelf("B", -1.33, 1.62)

# ================================================================ 3. Counter
c_ct = make_coll("Counter")
counter = empty("Counter", c_ct, (1.1, 0.85, 0))
CT_W, CT_D, CT_H = 2.0, 0.62, 1.0
box("Counter_Body", c_ct, (CT_W, CT_D - 0.06, CT_H - 0.05), (0, 0.03, (CT_H - 0.05) / 2),
    M["white"], bevel=0.02, parent=counter)
box("Counter_Top", c_ct, (CT_W + 0.06, CT_D + 0.04, 0.05), (0, 0, CT_H - 0.025), M["wood"],
    bevel=0.012, parent=counter)
box("Counter_Kick", c_ct, (CT_W - 0.04, 0.02, 0.08), (0, -CT_D / 2 + 0.035, 0.04),
    M["grey"], bevel=0.004, parent=counter)
for i, xx in enumerate((-0.5, 0.0, 0.5)):  # three calm vertical panels
    box(f"Counter_Panel{i}", c_ct, (0.62, 0.014, 0.76), (xx * 1.3, -CT_D / 2 + 0.03, 0.5),
        M["walnut"], bevel=0.006, parent=counter)
# espresso machine (local to counter)
em = empty("Counter_Espresso", c_ct, (0.62, 0.08, CT_H), parent=counter)
box("Espresso_Body", c_ct, (0.42, 0.34, 0.36), (0, 0.02, 0.18), M["graphite"], bevel=0.03,
    parent=em)
box("Espresso_Top", c_ct, (0.44, 0.36, 0.03), (0, 0.02, 0.375), M["steel"], bevel=0.008,
    parent=em)
box("Espresso_Tray", c_ct, (0.3, 0.12, 0.02), (0, -0.2, 0.01), M["steel"], bevel=0.004,
    parent=em)
cyl("Espresso_Group", c_ct, 0.04, 0.05, (0, -0.17, 0.26), M["steel"], parent=em)
box("Espresso_Handle", c_ct, (0.03, 0.12, 0.02), (0, -0.25, 0.235), M["graphite"],
    bevel=0.008, parent=em)
cyl("Espresso_Gauge", c_ct, 0.03, 0.01, (0.13, -0.155, 0.3), M["cream"], parent=em,
    rot=(90, 0, 0))


def cup(name, loc, parent):
    root = empty(name, c_ct, loc, parent=parent)
    cyl(f"{name}_Saucer", c_ct, 0.06, 0.008, (0, 0, 0.004), M["cup"], parent=root)
    cyl(f"{name}_Body", c_ct, 0.04, 0.07, (0, 0, 0.043), M["cup"], parent=root, r2=0.045)
    cyl(f"{name}_Coffee", c_ct, 0.04, 0.004, (0, 0, 0.073), M["coffee"], parent=root)
    torus(f"{name}_Handle", c_ct, 0.018, 0.005, (0.05, 0, 0.045), M["cup"], parent=root,
          rot=(90, 0, 0))
    return root


cup("Cup_1", (0.12, -0.08, CT_H), counter)
cup("Cup_2", (0.28, -0.12, CT_H), counter)

# ================================================================ 8. PaymentTerminal
c_pt = make_coll("PaymentTerminal")
pt = empty("PaymentTerminal", c_pt, (0.42, 0.71, CT_H), rot_z=-12)
box("PaymentTerminal_Base", c_pt, (0.12, 0.16, 0.02), (0, 0, 0.01), M["graphite"], bevel=0.006,
    parent=pt)
box("PaymentTerminal_Body", c_pt, (0.1, 0.17, 0.035), (0, 0.0, 0.04), M["graphite"],
    bevel=0.01, parent=pt, rot=(14, 0, 0))
box("PaymentTerminal_Screen", c_pt, (0.075, 0.07, 0.004), (0, 0.03, 0.06), M["screen"],
    bevel=0.0, parent=pt, rot=(14, 0, 0))
box("PaymentTerminal_Keys", c_pt, (0.075, 0.06, 0.004), (0, -0.045, 0.042), M["grey"],
    bevel=0.0, parent=pt, rot=(14, 0, 0))

# ================================================================ 4. OrderDesk
c_od = make_coll("OrderDesk")
od = empty("OrderDesk", c_od, (-1.7, -0.6, 0))
DK_W, DK_D, DK_H = 1.2, 0.6, 0.76
box("OrderDesk_Top", c_od, (DK_W, DK_D, 0.045), (0, 0, DK_H - 0.0225), M["wood"], bevel=0.01,
    parent=od)
for sx in (-1, 1):
    box(f"OrderDesk_Leg{'L' if sx < 0 else 'R'}", c_od, (0.045, DK_D - 0.06, DK_H - 0.045),
        (sx * (DK_W / 2 - 0.06), 0, (DK_H - 0.045) / 2), M["white"], bevel=0.008, parent=od)
box("OrderDesk_Modesty", c_od, (DK_W - 0.16, 0.02, 0.34), (0, -DK_D / 2 + 0.06, DK_H - 0.22),
    M["white"], bevel=0.006, parent=od)
box("OrderDesk_InboxTray", c_od, (0.36, 0.28, 0.015), (-0.22, -0.02, DK_H + 0.0075),
    M["grey"], bevel=0.004, parent=od)
for i in range(5):  # stack of envelopes / papers
    m_ = M["paper"] if i % 2 == 0 else M["cream"]
    box(f"OrderDesk_Envelope{i}", c_od, (0.3, 0.21, 0.012),
        (-0.22 + random.uniform(-0.01, 0.01), -0.02 + random.uniform(-0.01, 0.01),
         DK_H + 0.021 + i * 0.013), m_, bevel=0.003, segs=1, parent=od,
        rot=(0, 0, random.uniform(-5, 5)))
box("OrderDesk_Letter", c_od, (0.21, 0.28, 0.003), (0.22, 0.0, DK_H + 0.0015), M["paper"],
    bevel=0.0, parent=od, rot=(0, 0, 8))
cyl("OrderDesk_Pen", c_od, 0.006, 0.14, (0.36, -0.06, DK_H + 0.006), M["navy"], segs=8,
    parent=od, rot=(0, 90, 25))

# ================================================================ 6. SandboxBox
c_sb = make_coll("SandboxBox")
sb = empty("SandboxBox", c_sb, (-0.62, -0.65, 0))
PL_H, G = 0.36, 0.6
box("SandboxBox_Plinth", c_sb, (0.72, 0.72, PL_H), (0, 0, PL_H / 2), M["white"], bevel=0.02,
    parent=sb)
box("SandboxBox_Glass", c_sb, (G - 0.01, G - 0.01, G - 0.01), (0, 0, PL_H + G / 2),
    M["glass"], bevel=0.0, parent=sb)
fr = 0.018
half = G / 2
k = 0
for ax in range(3):  # 12 frame edges
    for s1 in (-1, 1):
        for s2 in (-1, 1):
            size = [fr, fr, fr]
            size[ax] = G + fr
            p = [0.0, 0.0, 0.0]
            others = [a for a in range(3) if a != ax]
            p[others[0]] = s1 * half
            p[others[1]] = s2 * half
            p[2] += PL_H + half
            box(f"SandboxBox_Frame{k}", c_sb, size, p, M["graphite"], bevel=0.003, segs=1,
                parent=sb)
            k += 1
# small code "chip" inside the glass so the box reads as a runtime
box("SandboxBox_Core", c_sb, (0.16, 0.16, 0.04), (0, 0, PL_H + 0.02), M["graphite"],
    bevel=0.006, parent=sb)
box("SandboxBox_CoreLight", c_sb, (0.1, 0.1, 0.006), (0, 0, PL_H + 0.043), M["blue_led"],
    bevel=0.0, parent=sb)
alarm = box("SandboxBox_Alarm", c_sb, (G + 0.05, G + 0.05, G + 0.05), (0, 0, PL_H + G / 2),
            M["alarm"], bevel=0.01, parent=sb)
alarm["hidden_by_default"] = True
alarm.hide_render = True
alarm.hide_viewport = True

# ================================================================ 5. VultrVM
c_vm = make_coll("VultrVM")
vm = empty("VultrVM", c_vm, (2.58, 1.58, 0))
VW, VD, VH = 0.5, 0.56, 1.32
box("VultrVM_Cabinet", c_vm, (VW, VD, VH), (0, 0, VH / 2 + 0.04), M["graphite"], bevel=0.025,
    parent=vm)
for sx in (-1, 1):
    for sy in (-1, 1):
        cyl(f"VultrVM_Foot{sx}{sy}", c_vm, 0.03, 0.04,
            (sx * (VW / 2 - 0.06), sy * (VD / 2 - 0.06), 0.02), M["grey"], segs=12, parent=vm)
for i in range(6):  # rack units
    box(f"VultrVM_Unit{i}", c_vm, (VW - 0.08, 0.012, 0.15),
        (0, -VD / 2 - 0.002, 0.22 + i * 0.19), M["hood"], bevel=0.004, parent=vm)
    box(f"VultrVM_UnitLed{i}", c_vm, (0.035, 0.008, 0.02),
        (VW / 2 - 0.08, -VD / 2 - 0.01, 0.22 + i * 0.19), M["blue_led"], bevel=0.0, parent=vm)
status = box("VultrVM_Status", c_vm, (0.022, 0.012, VH - 0.18),
             (-VW / 2 + 0.035, -VD / 2 - 0.006, VH / 2 + 0.04), M["blue_led"], bevel=0.004,
             parent=vm)
box("VultrVM_StatusTop", c_vm, (VW - 0.1, VD - 0.1, 0.012), (0, 0, VH + 0.046), M["blue_led"],
    bevel=0.003, parent=vm)

# ================================================================ 7. Gate
c_gt = make_coll("Gate")
gate = empty("Gate", c_gt, (0.3, -0.05, 0))
POST_H = 1.02
box("Gate_Base", c_gt, (0.32, 0.32, 0.04), (0, 0, 0.02), M["grey"], bevel=0.012, parent=gate)
box("Gate_Post", c_gt, (0.2, 0.2, POST_H), (0, 0, POST_H / 2), M["white"], bevel=0.03,
    parent=gate)
box("Gate_Stripe", c_gt, (0.205, 0.205, 0.04), (0, 0, POST_H - 0.18), M["graphite"],
    bevel=0.006, parent=gate)
ARM_Z = POST_H - 0.12
arm = empty("Gate_Arm", c_gt, (0.1, 0, ARM_Z), parent=gate)  # pivot: rotate about local Y
cyl("Gate_Arm_Hub", c_gt, 0.06, 0.05, (0.0, 0, 0), M["graphite"], parent=arm, rot=(90, 0, 0))
ARM_L = 1.05
box("Gate_Arm_Bar", c_gt, (ARM_L, 0.045, 0.045), (ARM_L / 2, 0, 0), M["white"], bevel=0.015,
    parent=arm)
for i in range(3):
    box(f"Gate_Arm_Band{i}", c_gt, (0.08, 0.05, 0.05), (0.3 + i * 0.3, 0, 0), M["amber"],
        bevel=0.012, parent=arm)
arm["rotate_axis"] = "local Y (negative = arm down)"
gl = empty("Gate_Light", c_gt, (0, 0, POST_H), parent=gate)
cyl("Gate_Light_Base", c_gt, 0.07, 0.025, (0, 0, 0.0125), M["graphite"], parent=gl)
sphere("Gate_Light_Dome", c_gt, 0.06, (0, 0, 0.025), M["amber"], parent=gl, cut_below=0.0)



# ================================================================ 11. Logo + coffeehouse ambience
LOGO_PATH = os.path.join(os.path.dirname(OUT), "brand", "logo-1024.png")
logo_img = bpy.data.images.load(LOGO_PATH, check_existing=False)
logo_img.name = "QuietPage_Logo"
logo_img.pack()  # embedded in .blend; the glTF exporter embeds it in the .glb
LOGO_UV_R = 492 / 1024  # badge circle radius in UV units (alpha bbox 20..1004)

m_logo = bpy.data.materials.new("M_Logo")
m_logo.use_nodes = True
_nt = m_logo.node_tree
_bsdf = next(n for n in _nt.nodes if n.type == "BSDF_PRINCIPLED")
_tex = _nt.nodes.new("ShaderNodeTexImage")
_tex.image = logo_img
_nt.links.new(_tex.outputs["Color"], _bsdf.inputs["Base Color"])
_bsdf.inputs["Roughness"].default_value = 0.5
# Disc UVs stay inside the badge circle, so alpha is always 1 there -> opaque material
# (avoids transparency sorting on the web); the transparent PNG corners are never sampled.
m_logo_edge = mat("M_LogoEdge", "#2f5d50", 0.55)


def logo_disc(name, coll, r, depth, loc, parent=None, rot=(90, 0, 0)):
    """Cylinder disc; +Z cap carries the logo. rot (90,0,0) makes it face -Y (front)."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=48,
                          radius1=r, radius2=r, depth=depth)
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        top = f.normal.z > 0.9
        f.material_index = 0 if top else 1
        for lp in f.loops:
            co = lp.vert.co
            lp[uv].uv = (0.5 + co.x / r * LOGO_UV_R, 0.5 + co.y / r * LOGO_UV_R) if top \
                else (0.5, 0.97)
    ob = finish_mesh(bm, name, coll, m_logo, loc, parent, 40, rot)
    ob.data.materials.append(m_logo_edge)
    return ob


# --- back wall behind the counter (carries menu board + logo sign)
c_bw = make_coll("BackWall")
box("BackWall", c_bw, (2.3, 0.06, 2.7), (1.12, 1.95, 1.35), M["white"], bevel=0.015)
WALL_FRONT = 1.92

# --- Logo_Sign: ~45 cm disc on the counter's centre walnut panel (front, facing -Y)
c_ls = make_coll("Logo_Sign")
COUNTER_PANEL_FRONT = 0.85 - 0.31 + 0.03 - 0.007  # counter y + panel offset - half thickness
sign = logo_disc("Logo_Sign", c_ls, 0.225, 0.015, (1.1, COUNTER_PANEL_FRONT - 0.0075, 0.5))

# --- MenuBoard: readable drinks menu texture (frame + slate are in the image)
MENU_PATH = os.path.join(os.path.dirname(OUT), "brand", "menu-board.png")
menu_img = bpy.data.images.load(MENU_PATH, check_existing=False)
menu_img.name = "QuietPage_Menu"
menu_img.pack()
m_menu = bpy.data.materials.new("M_MenuBoard")
m_menu.use_nodes = True
_nt = m_menu.node_tree
_bsdf = next(n for n in _nt.nodes if n.type == "BSDF_PRINCIPLED")
_tex = _nt.nodes.new("ShaderNodeTexImage")
_tex.image = menu_img
_nt.links.new(_tex.outputs["Color"], _bsdf.inputs["Base Color"])
_bsdf.inputs["Roughness"].default_value = 0.8

MB_W, MB_H, MB_TOP = 1.2, 0.75, 2.1
c_mb = make_coll("MenuBoard")
mb = empty("MenuBoard", c_mb, (1.45, WALL_FRONT, MB_TOP - MB_H / 2))
box("MenuBoard_Backing", c_mb, (MB_W - 0.03, 0.02, MB_H - 0.03), (0, -0.01, 0), M["walnut"],
    bevel=0.01, parent=mb)
_bm = bmesh.new()
_v = [_bm.verts.new(c) for c in ((-MB_W / 2, 0, -MB_H / 2), (MB_W / 2, 0, -MB_H / 2),
                                 (MB_W / 2, 0, MB_H / 2), (-MB_W / 2, 0, MB_H / 2))]
_f = _bm.faces.new(_v)  # normal faces -Y (front)
_bm.normal_update()
if _f.normal.y > 0:
    _f.normal_flip()
# round the corners to match the image's rounded frame (~40 px of 1920)
bmesh.ops.bevel(_bm, geom=list(_bm.verts), offset=MB_W * 40 / 1920, segments=5,
                affect="VERTICES", profile=0.5)
_uv = _bm.loops.layers.uv.new("UVMap")
for f in _bm.faces:
    for lp in f.loops:
        co = lp.vert.co
        lp[_uv].uv = ((co.x + MB_W / 2) / MB_W, (co.z + MB_H / 2) / MB_H)
finish_mesh(_bm, "MenuBoard_Image", c_mb, m_menu, (0, -0.022, 0), mb)

# --- PendantLamps: thin ceiling rail from the wall top, 3 warm dome shades
c_pl = make_coll("PendantLamps")
pl = empty("PendantLamps", c_pl)
RAIL_Z, RAIL_Y = 2.66, 0.85  # high enough to project above the menu in Cam_Overview
for i, x in enumerate((0.2, 1.6)):
    box(f"PendantLamps_Arm{i}", c_pl, (0.03, WALL_FRONT - RAIL_Y + 0.03, 0.03),
        (x, (WALL_FRONT + RAIL_Y) / 2, RAIL_Z), M["white"], bevel=0.008, parent=pl)
box("PendantLamps_Rail", c_pl, (1.43, 0.03, 0.03), (0.9, RAIL_Y, RAIL_Z), M["white"],
    bevel=0.008, parent=pl)
BULBS = []
for i, x in enumerate((0.4, 0.9, 1.4)):
    cyl(f"PendantLamps_Cord{i}", c_pl, 0.004, RAIL_Z - 1.93, (x, RAIL_Y, (RAIL_Z + 1.93) / 2), M["graphite"],
        segs=6, parent=pl)
    sphere(f"PendantLamps_Shade{i}", c_pl, 0.12, (x, RAIL_Y, 1.86), M["brass"], parent=pl,
           scale=(1, 1, 0.8), cut_below=0.0)
    sphere(f"PendantLamps_Bulb{i}", c_pl, 0.04, (x, RAIL_Y, 1.855), M["bulb"], parent=pl,
           segs=12, rings=8)
    BULBS.append((x, RAIL_Y, 1.82))

# --- PastryCase on the counter
c_pc = make_coll("PastryCase")
pc = empty("PastryCase", c_pc, (0.86, 0.83, 1.0))
box("PastryCase_Base", c_pc, (0.42, 0.28, 0.03), (0, 0, 0.015), M["walnut"], bevel=0.006,
    parent=pc)
box("PastryCase_Glass", c_pc, (0.4, 0.26, 0.2), (0, 0, 0.13), M["glass"], bevel=0.0,
    parent=pc)
box("PastryCase_Lid", c_pc, (0.42, 0.28, 0.012), (0, 0, 0.236), M["walnut"], bevel=0.004,
    parent=pc)
cr = capsule("PastryCase_Croissant", c_pc, 0.026, 0.11, (-0.12, 0.04, 0.056), M["pastry"],
             parent=pc, rot=(0, 90, 20), sy=0.8)
cyl("PastryCase_MuffinCup", c_pc, 0.028, 0.035, (-0.03, -0.05, 0.048), M["glaze"], segs=14,
    parent=pc, r2=0.033)
sphere("PastryCase_MuffinTop", c_pc, 0.036, (-0.03, -0.05, 0.065), M["pastry_dark"],
       parent=pc, cut_below=0.0, segs=14, rings=8)
sphere("PastryCase_Bun", c_pc, 0.036, (0.065, 0.045, 0.052), M["pastry"], parent=pc,
       scale=(1, 1, 0.62), segs=14, rings=8)
torus("PastryCase_Donut", c_pc, 0.026, 0.013, (0.13, -0.045, 0.044), M["glaze"], parent=pc,
      rot=(0, 0, 0))

# --- Plants: one by the shelves, one by the VultrVM
c_pt2 = make_coll("Plants")
plants = empty("Plants", c_pt2)


def plant(tag, loc, h):
    root = empty(f"Plant_{tag}", c_pt2, loc, parent=plants)
    cyl(f"Plant_{tag}_Pot", c_pt2, 0.1, 0.28, (0, 0, 0.14), M["rust"], segs=18, parent=root,
        r2=0.135)
    cyl(f"Plant_{tag}_Soil", c_pt2, 0.125, 0.01, (0, 0, 0.27), M["soil"], segs=18,
        parent=root)
    leaves = [(0, 0, 0.42, 0.16), (0.08, 0.03, 0.62, 0.13), (-0.07, -0.04, 0.68, 0.12),
              (0.02, 0.05, 0.86, 0.11), (-0.03, -0.02, 0.98, 0.09)]
    for i, (x, y, z, r) in enumerate(leaves):
        z = 0.3 + (z - 0.3) * (h - 0.3) / 0.7
        sphere(f"Plant_{tag}_Leaf{i}", c_pt2, r, (x, y, z),
               M["leaf"] if i % 2 == 0 else M["leaf_light"], parent=root,
               scale=(1, 1, 1.15), segs=14, rings=8)


plant("Shelves", (-0.55, 1.68, 0), 1.05)
plant("VultrVM", (2.64, 0.78, 0), 0.8)

# --- Stools: in front of the counter, right of the gate arm's path
c_st = make_coll("Stools")
stools = empty("Stools", c_st)
for i, x in enumerate((1.7, 2.04)):
    root = empty(f"Stool_{i}", c_st, (x, 0.27, 0), parent=stools)
    cyl(f"Stool_{i}_Base", c_st, 0.16, 0.025, (0, 0, 0.0125), M["graphite"], segs=20,
        parent=root)
    cyl(f"Stool_{i}_Column", c_st, 0.022, 0.66, (0, 0, 0.355), M["steel"], segs=10,
        parent=root)
    torus(f"Stool_{i}_Footrest", c_st, 0.12, 0.009, (0, 0, 0.3), M["steel"], parent=root,
          rot=(0, 0, 0))
    cyl(f"Stool_{i}_Seat", c_st, 0.17, 0.06, (0, 0, 0.715), M["walnut"], segs=24,
        parent=root)

# ================================================================ 9. Characters
def figure(name, loc, rot_z, top, pants, hair_fn, arms=("down", "down"), eyes=True,
           extras=None, sleeve=None):
    """Stylized figure ~1.65 m. Local -Y is forward."""
    coll = make_coll(name)
    root = empty(name, coll, loc, rot_z=rot_z)
    sleeve = sleeve or top
    # legs
    for sx in (-1, 1):
        capsule(f"{name}_Leg{'L' if sx < 0 else 'R'}", coll, 0.075, 0.8,
                (sx * 0.085, 0, 0.4), pants, parent=root)
        box(f"{name}_Shoe{'L' if sx < 0 else 'R'}", coll, (0.11, 0.18, 0.06),
            (sx * 0.085, -0.03, 0.03), M["graphite"], bevel=0.025, parent=root)
    # torso
    capsule(f"{name}_Torso", coll, 0.19, 0.68, (0, 0, 1.06), top, parent=root, sy=0.72)
    # neck + head
    cyl(f"{name}_Neck", coll, 0.05, 0.08, (0, 0, 1.42), M["skin"], segs=12, parent=root)
    sphere(f"{name}_Head", coll, 0.135, (0, 0, 1.53), M["skin"], parent=root)
    if eyes:
        for sx in (-1, 1):
            sphere(f"{name}_Eye{'L' if sx < 0 else 'R'}", coll, 0.014,
                   (sx * 0.045, -0.125, 1.545), M["eye"], parent=root, segs=8, rings=6)
    hair_fn(name, coll, root)
    # arms
    sh_z, sh_x = 1.29, 0.215
    for side, pose in zip((-1, 1), arms):
        tag = "L" if side < 0 else "R"
        sh = Vector((side * sh_x, 0, sh_z))
        if pose == "down":
            elbow = Vector((side * (sh_x + 0.02), 0, 1.02))
            hand = Vector((side * (sh_x + 0.025), -0.02, 0.8))
        elif pose == "forward":
            elbow = Vector((side * (sh_x + 0.01), 0.0, 1.02))
            hand = Vector((side * (sh_x - 0.04), -0.26, 1.02))
        elif pose == "tuck":  # hugging something against the side
            elbow = Vector((side * (sh_x + 0.05), 0.02, 1.03))
            hand = Vector((side * (sh_x - 0.02), -0.16, 1.0))
        capsule_between(f"{name}_UpperArm{tag}", coll, 0.055, sh, elbow, sleeve, parent=root)
        fdir = (hand - elbow).normalized()
        capsule_between(f"{name}_Forearm{tag}", coll, 0.05, elbow, hand - fdir * 0.075,
                        sleeve, parent=root)
        sphere(f"{name}_Hand{tag}", coll, 0.047, tuple(hand), M["skin"], parent=root,
               segs=12, rings=8)
    if extras:
        extras(name, coll, root)
    return root


# --- hair styles
def hair_ivy(name, coll, root):
    sphere(f"{name}_Hair", coll, 0.148, (0, 0.012, 1.548), M["hair_auburn"], parent=root,
           scale=(1.0, 1.0, 0.95), cut_below=-0.05)
    sphere(f"{name}_HairBun", coll, 0.07, (0, 0.11, 1.64), M["hair_auburn"], parent=root,
           segs=14, rings=8)
    # glasses
    for sx in (-1, 1):
        torus(f"{name}_GlassesLens{'L' if sx < 0 else 'R'}", coll, 0.03, 0.0045,
              (sx * 0.047, -0.136, 1.545), M["graphite"], parent=root)
    box(f"{name}_GlassesBridge", coll, (0.03, 0.008, 0.008), (0, -0.138, 1.55), M["graphite"],
        bevel=0.0, parent=root)


def hair_milo(name, coll, root):
    sphere(f"{name}_Hair", coll, 0.145, (0, 0.015, 1.565), M["hair_dark"], parent=root,
           scale=(1.0, 1.0, 0.85), cut_below=0.05)
    box(f"{name}_HairFringe", coll, (0.22, 0.08, 0.05), (0, -0.07, 1.64), M["hair_dark"],
        bevel=0.02, parent=root)


def hair_hart(name, coll, root):
    """Short soft wavy hair: overlapping small blobs on top/sides/back, face left open."""
    hc = Vector((0, 0, 1.53))
    # small back-set base so gaps between curls never show scalp
    sphere(f"{name}_HairBase", coll, 0.138, (0, 0.03, 1.55), M["hair_grey"], parent=root,
           scale=(0.98, 0.95, 0.95), cut_below=0.15)
    blobs = [  # (azimuth from front deg, elevation deg, radius)
        (0, 68, 0.058), (35, 62, 0.055), (-35, 62, 0.055), (0, 88, 0.06),
        (70, 50, 0.056), (-70, 50, 0.056), (100, 22, 0.05), (-100, 22, 0.05),
        (125, 45, 0.058), (-125, 45, 0.058), (160, 25, 0.058), (-160, 25, 0.058),
        (180, 55, 0.06), (90, 72, 0.055), (-90, 72, 0.055), (150, 75, 0.055),
        (-150, 75, 0.055),
    ]
    for i, (az, el, rr) in enumerate(blobs):
        a, e = math.radians(az), math.radians(el)
        d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
        sphere(f"{name}_Curl{i}", coll, rr, tuple(hc + d * 0.118), M["hair_grey"],
               parent=root, segs=12, rings=8)


def hair_courier(name, coll, root):
    # hood hides the face completely
    sphere(f"{name}_Hood", coll, 0.175, (0, 0.015, 1.545), M["hood"], parent=root,
           scale=(1.0, 1.05, 1.08))
    sphere(f"{name}_HoodOpening", coll, 0.11, (0, -0.135, 1.52), M["hood_inside"],
           parent=root, scale=(0.95, 0.35, 1.1))
    capsule(f"{name}_HoodDrape", coll, 0.2, 0.3, (0, 0.03, 1.36), M["hood"], parent=root,
            sy=0.75)


# --- extras
def ivy_extras(name, coll, root):
    # closed cardigan: subtle darker V-neck collar + two small buttons
    for sx in (-1, 1):
        box(f"{name}_Collar{'L' if sx < 0 else 'R'}", coll, (0.02, 0.022, 0.15),
            (sx * 0.036, -0.118, 1.285), M["green_dark"], bevel=0.008, parent=root,
            rot=(-22, sx * 28, 0))
    for i, z in enumerate((1.14, 1.04)):
        sphere(f"{name}_Button{i}", coll, 0.014, (0, -0.135, z), M["green_dark"],
               parent=root, scale=(1, 0.5, 1), segs=10, rings=6)
    # three books held upright against the right hip, under the forearm
    for i, (c, w) in enumerate(((M["navy"], 0.24), (M["rust"], 0.22), (M["cream"], 0.25))):
        box(f"{name}_Book{i}", coll, (0.05, w, 0.18 - i * 0.01),
            (0.25 + i * 0.05, -0.06, 1.02), c, bevel=0.005, parent=root)


def milo_extras(name, coll, root):
    box(f"{name}_Apron", coll, (0.34, 0.03, 0.52), (0, -0.14, 0.98), M["apron"], bevel=0.02,
        parent=root)
    box(f"{name}_ApronBib", coll, (0.22, 0.03, 0.2), (0, -0.14, 1.27), M["apron"], bevel=0.015,
        parent=root)
    box(f"{name}_ApronPocket", coll, (0.16, 0.008, 0.07), (0, -0.157, 0.92), M["hair_dark"],
        bevel=0.004, parent=root)
    # tablet held in front with both hands
    box(f"{name}_Tablet", coll, (0.26, 0.18, 0.014), (0.0, -0.3, 1.04), M["graphite"],
        bevel=0.008, parent=root, rot=(30, 0, 0))
    box(f"{name}_TabletScreen", coll, (0.23, 0.15, 0.003), (0.0, -0.302, 1.049), M["screen"],
        bevel=0.0, parent=root, rot=(30, 0, 0))
    logo_disc("Logo_Badge", coll, 0.033, 0.006, (0.06, -0.158, 1.31), parent=root)


def hart_extras(name, coll, root):
    # burgundy vest over white shirt
    capsule(f"{name}_Vest", coll, 0.198, 0.62, (0, 0, 1.06), M["burgundy"], parent=root,
            sy=0.74)
    box(f"{name}_Collar", coll, (0.12, 0.02, 0.12), (0, -0.14, 1.3), M["white"], bevel=0.01,
        parent=root, rot=(-12, 0, 0))
    # stamp in right hand
    hx, hy, hz = 0.195, -0.26, 1.02
    cyl(f"{name}_StampHandle", coll, 0.02, 0.09, (hx, hy, hz + 0.06), M["wood_dark"], segs=12,
        parent=root)
    sphere(f"{name}_StampKnob", coll, 0.026, (hx, hy, hz + 0.115), M["wood_dark"], parent=root,
           segs=12, rings=8)
    box(f"{name}_StampBase", coll, (0.07, 0.05, 0.022), (hx, hy, hz - 0.04), M["burgundy"],
        bevel=0.005, parent=root)


def courier_extras(name, coll, root):
    box(f"{name}_BagStrap", coll, (0.05, 0.02, 0.6), (0.0, -0.14, 1.12), M["graphite"],
        bevel=0.006, parent=root, rot=(0, 38, 0))
    box(f"{name}_Bag", coll, (0.1, 0.26, 0.22), (-0.25, 0.02, 0.86), M["graphite"], bevel=0.02,
        parent=root)
    # ink-stained envelope held forward
    env = empty(f"{name}_Envelope", coll, (0.2, -0.29, 1.03), parent=root)
    env.rotation_euler = (math.radians(70), 0, 0)
    box(f"{name}_EnvelopePaper", coll, (0.22, 0.15, 0.008), (0, 0, 0), M["cream"], bevel=0.002,
        segs=1, parent=env)
    sphere(f"{name}_InkStain", coll, 0.04, (0.04, 0.01, -0.006), M["ink"], parent=env,
           scale=(1.0, 0.8, 0.12), segs=12, rings=6)
    sphere(f"{name}_InkDrop", coll, 0.015, (-0.03, -0.035, -0.006), M["ink"], parent=env,
           scale=(1.0, 1.0, 0.25), segs=10, rings=6)


figure("Ivy", (-1.7, -0.08, 0), 0, M["green"], M["pants"], hair_ivy,
       arms=("down", "tuck"), extras=ivy_extras)
figure("Milo", (1.3, 1.45, 0), 0, M["white"], M["pants_dark"], hair_milo,
       arms=("forward", "forward"), extras=milo_extras)
figure("MrsHart", (-0.14, 0.12, 0), -12, M["white"], M["pants_dark"], hair_hart,
       arms=("down", "forward"), extras=hart_extras)
figure("InkwellCourier", (1.35, -1.72, 0), -118, M["hood"], M["pants_dark"], hair_courier,
       arms=("down", "forward"), eyes=False, extras=courier_extras)


# ================================================================ 10. Lights / world / camera
c_env = make_coll("Environment")
world = bpy.data.worlds.new("QuietWorld")
scene.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs["Color"].default_value = (*hexcol("#e3e4e2"), 1)
bg.inputs["Strength"].default_value = 0.65

sun_d = bpy.data.lights.new("Sun_Key", "SUN")
sun_d.energy = 3.6
sun_d.angle = math.radians(12)
sun = bpy.data.objects.new("Sun_Key", sun_d)
sun.rotation_euler = (math.radians(42), math.radians(0), math.radians(-35))
link(sun, c_env)

for i, bpos in enumerate(BULBS):
    pd = bpy.data.lights.new(f"PendantLamp_Light{i}", "POINT")
    pd.energy = 25
    pd.color = (1.0, 0.78, 0.52)
    pd.shadow_soft_size = 0.05
    po = bpy.data.objects.new(f"PendantLamp_Light{i}", pd)
    po.location = bpos
    link(po, c_env)

area_d = bpy.data.lights.new("Area_Fill", "AREA")
area_d.energy = 400
area_d.size = 8
area = bpy.data.objects.new("Area_Fill", area_d)
area.location = (-4.5, -5.0, 6.5)
area.rotation_euler = (Vector((0, 0, 0.5)) - area.location).to_track_quat("-Z", "Y").to_euler()
link(area, c_env)

cam_d = bpy.data.cameras.new("Cam_Overview")
cam_d.lens = 50
cam_d.clip_end = 200
cam = bpy.data.objects.new("Cam_Overview", cam_d)
link(cam, c_env)
scene.camera = cam


def aim(cam_obj, loc, target, lens=50):
    cam_obj.location = loc
    cam_obj.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cam_obj.data.lens = lens


OVERVIEW = ((9.6, -11.2, 8.4), (0.0, -0.05, 0.3), 58)
aim(cam, *OVERVIEW)

# ---------------------------------------------------------------- render settings
r = scene.render
for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
    try:
        r.engine = eng
        break
    except TypeError:
        continue
r.resolution_x, r.resolution_y = 1600, 1000
r.resolution_percentage = 100
r.film_transparent = False
try:
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
except Exception:
    pass
scene.view_settings.exposure = 0.0
try:
    ee = scene.eevee
    ee.taa_render_samples = 64
    for attr, val in (("use_shadows", True), ("use_raytracing", False),
                      ("shadow_ray_count", 2), ("shadow_step_count", 8)):
        if hasattr(ee, attr):
            setattr(ee, attr, val)
except Exception as exc:
    print("eevee settings:", exc)

# ---------------------------------------------------------------- join meshes
# Fewer draw calls on the web: each named group becomes <Name>_Mesh under its root
# empty; parts the web page animates/toggles stay as their own objects.
def descendants(ob):
    out = []
    for ch in ob.children:
        out.append(ch)
        out.extend(descendants(ch))
    return out


def join_under(root, name, exclude_roots=()):
    excl = set()
    for e in exclude_roots:
        excl.add(e)
        excl.update(descendants(e))
    meshes = [o for o in descendants(root) if o.type == "MESH" and o not in excl]
    if not meshes:
        return None
    active = meshes[0]
    with bpy.context.temp_override(active_object=active, object=active,
                                   selected_objects=meshes,
                                   selected_editable_objects=meshes):
        bpy.ops.object.join()
    mw = active.matrix_world.copy()
    active.parent = root
    active.matrix_world = mw
    active.name = name
    active.data.name = name
    # drop now-empty helper empties (not root, not excluded)
    changed = True
    while changed:
        changed = False
        for o in descendants(root):
            if o.type == "EMPTY" and not o.children and o not in excl:
                bpy.data.objects.remove(o)
                changed = True
                break
    return active


O = bpy.data.objects
join_under(O["Shelves"], "Shelves_Mesh")
join_under(O["Counter"], "Counter_Mesh")
join_under(O["PaymentTerminal"], "PaymentTerminal_Mesh")
join_under(O["OrderDesk"], "OrderDesk_Mesh")
join_under(O["SandboxBox"], "SandboxBox_Frame",
           exclude_roots=(O["SandboxBox_Glass"], O["SandboxBox_Alarm"], O["SandboxBox_CoreLight"]))
join_under(O["VultrVM"], "VultrVM_Mesh", exclude_roots=(O["VultrVM_Status"],))
join_under(O["Gate_Arm"], "Gate_Arm_Mesh")
join_under(O["Gate_Light"], "Gate_Light_Mesh")
join_under(O["Gate"], "Gate_Mesh", exclude_roots=(O["Gate_Arm"], O["Gate_Light"]))
for who in ("Ivy", "Milo", "MrsHart", "InkwellCourier"):
    join_under(O[who], f"{who}_Mesh",
               exclude_roots=(O["Logo_Badge"],) if who == "Milo" else ())
join_under(O["MenuBoard"], "MenuBoard_Mesh")
join_under(O["PendantLamps"], "PendantLamps_Mesh")
join_under(O["PastryCase"], "PastryCase_Mesh", exclude_roots=(O["PastryCase_Glass"],))
join_under(O["Plants"], "Plants_Mesh")
join_under(O["Stools"], "Stools_Mesh")


# ---------------------------------------------------------------- stats
deps = bpy.context.evaluated_depsgraph_get()
tris = 0
for ob in scene.objects:
    if ob.type == "MESH":
        me = ob.evaluated_get(deps).to_mesh()
        me.calc_loop_triangles()
        tris += len(me.loop_triangles)
        ob.evaluated_get(deps).to_mesh_clear()
print(f"QP_STATS objects={len(scene.objects)} triangles={tris}")

# ---------------------------------------------------------------- save / export
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "quiet-page.blend"))

alarm.hide_viewport = False  # make sure the hidden alarm is exported
alarm.hide_render = False
alarm.hide_set(False)
gltf_kwargs = dict(filepath=os.path.join(OUT, "quiet-page.glb"), export_format="GLB",
                   use_selection=False, export_apply=True, export_extras=True,
                   export_cameras=True, export_lights=False, export_yup=True)
try:
    bpy.ops.export_scene.gltf(**gltf_kwargs)
except TypeError as exc:
    print("gltf kwargs issue:", exc)
    gltf_kwargs.pop("export_lights", None)
    bpy.ops.export_scene.gltf(**gltf_kwargs)
alarm.hide_viewport = True
alarm.hide_render = True


# ---------------------------------------------------------------- previews
def render_to(path, loc, target, lens):
    aim(cam, loc, target, lens)
    r.filepath = path
    bpy.ops.render.render(write_still=True)


if DO_RENDER:
    # preview-only ground far below so the floating slab casts a soft shadow
    # (added after the GLB export and removed before the final save)
    gm = mat("M_PreviewGround", "#bfc0be", 0.95)
    bmg = bmesh.new()
    bmesh.ops.create_grid(bmg, x_segments=1, y_segments=1, size=30)
    ground = finish_mesh(bmg, "Preview_Ground", c_env, gm, (0, 0, -1.1), None)
    render_to(os.path.join(OUT, "preview-overview.png"), *OVERVIEW)
    render_to(os.path.join(OUT, "preview-ivy.png"), (0.2, -2.7, 1.95), (-1.6, -0.25, 1.05), 42)
    render_to(os.path.join(OUT, "preview-counter.png"), (1.9, -1.1, 1.25), (1.4, 1.6, 1.6), 35)
    render_to(os.path.join(OUT, "preview-gate.png"), (2.6, -3.0, 2.1), (0.45, 0.3, 0.8), 45)
    aim(cam, *OVERVIEW)
    bpy.data.objects.remove(ground)
    bpy.data.materials.remove(gm)

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "quiet-page.blend"))
print("QP_DONE")
