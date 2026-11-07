"""The Quiet Page — book cafe diorama.

Re-run headless (does not touch any open Blender session):
  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
      --python build_scene.py -- [--no-render]

Outputs next to this file: quiet-page.blend, quiet-page.glb,
preview-overview.png, preview-ivy.png, preview-counter.png, preview-nook.png, preview-gate.png
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
    "white": mat("M_White", "#d8cfc2", 0.7),  # warm greige (no pure white)
    "platform": mat("M_Platform", "#8a7a6a", 0.8),  # warm taupe base
    "offwhite": mat("M_OffWhite", "#5a4030", 0.7),  # shelf backs (dark walnut)
    "wood": mat("M_Wood", "#d9c7ad", 0.7),
    "wood_dark": mat("M_WoodDark", "#a88a6a", 0.7),
    "grey": mat("M_Grey", "#c9c9c7", 0.6),
    "graphite": mat("M_Graphite", "#3b3f45", 0.5),
    "steel": mat("M_Steel", "#b8bcc2", 0.35, metal=0.6),
    "green": mat("M_MutedGreen", "#6b8a74", 0.7),
    "green_dark": mat("M_MutedGreenDark", "#4f6a57", 0.7),
    "walnut": mat("M_Walnut", "#6e4b34", 0.55),
    "dark_wood": mat("M_DarkWood", "#4a3426", 0.5),
    "slat_oak": mat("M_SlatOak", "#d9c7a8", 0.6),
    "slat_oak2": mat("M_SlatOakAccent", "#c4ab84", 0.6),
    "light_oak": mat("M_LightOak", "#d2b48c", 0.5),
    "cognac": mat("M_LeatherCognac", "#b9733a", 0.38),
    "ottoman": mat("M_LeatherGreyBrown", "#5b4a40", 0.45),
    "black_metal": mat("M_BlackMetal", "#262626", 0.35, metal=0.6),
    "rattan": mat("M_Rattan", "#c89b62", 0.8, emit="#ffc27a", emit_strength=0.35),
    "rattan_dark": mat("M_RattanWeave", "#9a7044", 0.85),
    "linen": mat("M_LinenShade", "#efe4cf", 0.8, emit="#ffd9a0", emit_strength=0.6),
    "led_2700": mat("M_LED2700K", "#ffd2a0", 0.3, emit="#ffb46b", emit_strength=4.0),
    "led_2700_soft": mat("M_LED2700KSoft", "#ffd2a0", 0.3, emit="#ffb46b", emit_strength=1.6),
    "brass_band": mat("M_BrushedBrass", "#c9a35f", 0.3, metal=0.85),
    "teal": mat("M_PosterTeal", "#2f7f7a", 0.8),
    "mustard": mat("M_PosterMustard", "#d6a630", 0.8),
    "screen_green": mat("M_ScreenGreen", "#1f3d33", 0.4, emit="#2c5a49", emit_strength=0.7),
    "screen_text": mat("M_ScreenText", "#f1e9d8", 0.4, emit="#f1e9d8", emit_strength=0.9),
    "daylight_glass": mat("M_DaylightGlass", "#d6ecf5", 0.05, emit="#e3f2fa", emit_strength=0.5, alpha=0.45),
    "wall_green": mat("M_WallSage", "#7e9478", 0.85),  # muted sage
    "wall_espresso": mat("M_WallCream", "#eadbc4", 0.9),  # warm cream plaster
    "dark_cabinet": mat("M_DarkCabinet", "#5a3e2b", 0.6),  # dark walnut
    "counter_top": mat("M_CounterTopWalnut", "#4a3426", 0.35),
    "dark_grey": mat("M_DarkGrey", "#5a4a3e", 0.6),
    "oak_edge_d": mat("M_DeskLeg", "#4f3828", 0.55),
    "holiday_red": mat("M_HolidayRed", "#a8322d", 0.45),
    "fir": mat("M_Fir", "#2d4f3c", 0.85),
    "fir_light": mat("M_FirLight", "#3b6249", 0.85),
    "gold": mat("M_Gold", "#d4a94f", 0.25, metal=0.8),
    "fairy": mat("M_FairyLight", "#ffd08a", 0.3, emit="#ffc766", emit_strength=3.5),  # daytime: subtler
    "pot_cream": mat("M_PotCream", "#e9e2d4", 0.6),
    "pot_char": mat("M_PotCharcoal", "#45484d", 0.6),
    "slate": mat("M_ChalkSlate", "#2f3534", 0.85),
    "chalk": mat("M_Chalk", "#e9e1cc", 0.9),
    "brass": mat("M_ShadeOchre", "#c99a5b", 0.45, metal=0.2),
    "bulb": mat("M_WarmBulb", "#ffe2b0", 0.3, emit="#ffb46b", emit_strength=6.0),  # ~2700K, daytime
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
    "cup": mat("M_Cup", "#ebe4d8", 0.4),
    "coffee": mat("M_Coffee", "#5a3b28", 0.3),
}


EXTRA_LIGHTS = []  # (name, location, power) recreated as warm point lights in the lighting section

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
platform = rounded_slab("Platform", c_plat, 16.0, 10.0, PLAT_T, 0.3, (0, 0, -PLAT_T / 2),
                        M["platform"], edge_bevel=0.06)

def text_mesh(name, coll, body, size, mat_, loc, rot=(90, 0, 0), parent=None, max_w=None,
              extrude=0.0):
    """Blender text converted to a flat mesh (centred), optionally scaled to max_w."""
    cu = bpy.data.curves.new(name + "_curve", "FONT")
    cu.resolution_u = 2  # light glyph tessellation for the web
    cu.body = body
    cu.size = size
    cu.extrude = extrude
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    tmp = bpy.data.objects.new(name + "_tmp", cu)
    scene.collection.objects.link(tmp)
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    me.name = name
    if max_w and len(me.vertices):
        w = max(v.co.x for v in me.vertices) - min(v.co.x for v in me.vertices)
        if w > max_w:
            for v in me.vertices:
                v.co *= max_w / w
    me.materials.append(mat_)
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.rotation_euler = [math.radians(a) for a in rot]
    link(ob, coll)
    if parent:
        ob.parent = parent
    return ob


def add_planar_uv(ob, scale_u, scale_v, axes=("x", "y")):
    me = ob.data
    uv = me.uv_layers.new(name="UVMap")
    for lp in me.loops:
        co = me.vertices[lp.vertex_index].co
        uv.data[lp.index].uv = (getattr(co, axes[0]) * scale_u, getattr(co, axes[1]) * scale_v)


def tex_material(name, img, rough=0.6, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = rough
    if emit:
        ekey = "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
        nt.links.new(tex.outputs["Color"], bsdf.inputs[ekey])
        bsdf.inputs["Emission Strength"].default_value = emit
    return m


def np_image(name, rgb):
    """rgb: HxWx3 float array in sRGB 0..1 -> packed Blender image."""
    import numpy as _np
    h, w = rgb.shape[:2]
    rgba = _np.ones((h, w, 4), dtype=_np.float32)
    rgba[..., :3] = _np.clip(rgb, 0, 1)
    im = bpy.data.images.new(name, w, h, alpha=False)
    im.pixels.foreach_set(rgba.ravel())
    im.pack()
    return im


def hex_srgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def groove_material(name, hexc, groove=0.62):
    """Vertical-groove panelling: one groove per texture tile (tile = 6 cm)."""
    import numpy as _np
    c = _np.array(hex_srgb(hexc))
    img = _np.tile(c, (8, 64, 1)).astype(_np.float32)
    img[:, :5] *= groove          # groove shadow
    img[:, 5:9] *= 1.06           # lit edge
    img[:, 56:] *= 0.93
    return tex_material(name, np_image(name + "_img", img), 0.7)


def grooved_panel(name, coll, w, h, loc, mat_, parent=None, rot_z=0.0, pitch=0.06):
    ob = face_plane(name, coll, w, h, loc, mat_, parent)
    for lp in ob.data.uv_layers[0].data:
        lp.uv = (lp.uv[0] * w / pitch, lp.uv[1])
    ob.rotation_euler = (0, 0, math.radians(rot_z))
    return ob


# --- oak plank floor (generated texture, planar UVs, 4 m tile)
import numpy as np


def plank_image(px=1024, tile=4.0):
    """Light warm-grey stone tile (#CFC9C0), long 1.0 x 0.5 m tiles, fine joints, slight mottling."""
    rng_ = np.random.default_rng(5)
    v = (np.arange(px) + 0.5) / px * tile
    u = (np.arange(px) + 0.5) / px * tile
    U, V = np.meshgrid(u, v)
    TW, TH = 1.0, 0.5
    row = np.floor(V / TH).astype(int)
    off = (row % 2) * 0.5
    col = np.floor((U + off) / TW).astype(int)
    tone = rng_.uniform(-0.025, 0.025, (16, 16))
    base = np.array(hex_srgb("#cfc9c0"))
    t = 1.0 + tone[row % 16, col % 16]
    mott = 1.0 + 0.015 * np.sin(U * 7.0 + np.sin(V * 5.0) * 2.0) * np.sin(V * 6.3)
    img = base[None, None, :] * (t * mott)[..., None]
    joint = ((V % TH) < 0.006) | (((U + off) % TW) < 0.006)
    img[joint] *= 0.82
    rgba = np.ones((px, px, 4), dtype=np.float32)
    rgba[..., :3] = np.clip(img, 0, 1)
    im = bpy.data.images.new("QuietPage_FloorTile", px, px, alpha=False)
    im.pixels.foreach_set(rgba.ravel())
    im.pack()
    return im

m_floor = bpy.data.materials.new("M_FloorTile")
m_floor.use_nodes = True
_nt = m_floor.node_tree
_bsdf = next(n for n in _nt.nodes if n.type == "BSDF_PRINCIPLED")
_tex = _nt.nodes.new("ShaderNodeTexImage")
_tex.image = plank_image()
_nt.links.new(_tex.outputs["Color"], _bsdf.inputs["Base Color"])
_bsdf.inputs["Roughness"].default_value = 0.32  # slight sheen
floor = rounded_slab("Floor", c_plat, 15.7, 9.7, 0.006, 0.18, (0, 0, -0.0025), m_floor,
                     edge_bevel=0.002)
floor.data.materials[0] = m_floor
_uv = floor.data.uv_layers.new(name="UVMap")
for lp in floor.data.loops:
    co = floor.data.vertices[lp.vertex_index].co
    _uv.data[lp.index].uv = (co.x / 4.0, co.y / 4.0)

# ================================================================ 2. Shelves
c_sh = make_coll("Shelves")
shelves = empty("Shelves", c_sh)
BOOK_COLS = [M["green"], M["rust"], M["navy"], M["cream"]]


def bookshelf(tag, x, y, rot=0.0):
    root = empty(f"Shelf_{tag}", c_sh, (x, y, 0), rot_z=rot, parent=shelves)
    W, D, H, T = 0.92, 0.34, 1.86, 0.035
    box(f"Shelf_{tag}_SideL", c_sh, (T, D, H), (-W / 2 + T / 2, 0, H / 2), M["walnut"], parent=root)
    box(f"Shelf_{tag}_SideR", c_sh, (T, D, H), (W / 2 - T / 2, 0, H / 2), M["walnut"], parent=root)
    box(f"Shelf_{tag}_Back", c_sh, (W - 2 * T, 0.02, H - 0.02), (0, D / 2 - 0.01, H / 2),
        M["offwhite"], bevel=0.004, parent=root)
    levels = [0.06, 0.50, 0.94, 1.38, H - T / 2]
    for i, z in enumerate(levels):
        box(f"Shelf_{tag}_Board{i}", c_sh, (W - 2 * T + 0.002, D, T), (0, 0, z), M["walnut"],
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


# tall shelves line the right edge beside the reading nook, books facing in (-X)
# RightWall: short wall on the right edge (front two-thirds), tall shelves flat against it
c_rw = make_coll("RightWall")
# Room shell: dollhouse with the front wall removed. Walls 12 cm thick, 2.7 m high.
ROOM_H, WALL_T = 2.7, 0.12
SIDE_IN = 7.8                     # inner face of the side walls (|x|)
SIDE_C = SIDE_IN + WALL_T / 2     # wall centre line
ROOM_Y0, ROOM_Y1 = -4.85, 4.82    # front edge .. back wall outer face
box("RightWall", c_rw, (WALL_T, ROOM_Y1 - ROOM_Y0, ROOM_H), (SIDE_C, (ROOM_Y0 + ROOM_Y1) / 2,
    ROOM_H / 2), M["wall_espresso"], bevel=0.006)
c_lw = make_coll("LeftWall")
SHOP_Y1 = ROOM_Y0 + 1.5  # front 1.5 m of the left wall is a glass shopfront
box("Banquette_SideWall", c_lw, (WALL_T, ROOM_Y1 - SHOP_Y1, ROOM_H), (-SIDE_C,
    (SHOP_Y1 + ROOM_Y1) / 2, ROOM_H / 2), M["wall_espresso"], bevel=0.006)  # left wall
bookshelf("A", SIDE_IN - 0.17, -3.4, -90)  # flat against the RightWall, books face in (-X)
bookshelf("B", SIDE_IN - 0.17, -2.48, -90)

# ================================================================ 3. Counter
c_ct = make_coll("Counter")
COUNTER_Y = 3.55
counter = empty("Counter", c_ct, (0.0, COUNTER_Y, 0))
CT_W, CT_D, CT_H = 6.0, 0.62, 1.0
box("Counter_Body", c_ct, (CT_W, CT_D - 0.06, CT_H - 0.07), (0, 0.03, (CT_H - 0.07) / 2),
    M["dark_wood"], bevel=0.07, segs=4, parent=counter)  # rounded outside corners
_mimg = None
try:
    import numpy as _np
    _rng = _np.random.default_rng(3)
    _W, _H = 1024, 256
    _u = _np.linspace(0, 6, _W)[None, :]
    _v = _np.linspace(0, 1.5, _H)[:, None]
    _vein = _np.abs(_np.sin(_u * 2.1 + _np.sin(_v * 5 + _u * 0.7) * 1.6 + _np.sin(_u * 9) * 0.15))
    _vein = _np.clip((0.06 - _vein) / 0.06, 0, 1) * 0.12
    _base = _np.array(hex_srgb("#e8dfd2"))
    _img = _base[None, None, :] * (1 - _vein[..., None])
    _mimg = np_image("QuietPage_Marble", _img.astype(_np.float32))
except Exception as exc:
    print("marble texture:", exc)
M["marble"] = tex_material("M_MarbleCream", _mimg, 0.28)
_top = box("Counter_Top", c_ct, (CT_W + 0.04, CT_D + 0.02, 0.045), (0, 0.01, CT_H - 0.0225),
           M["marble"], bevel=0.03, segs=3, parent=counter)
add_planar_uv(_top, 1 / 6.0, 1 / 1.5)
box("Counter_TopEdge", c_ct, (CT_W + 0.08, 0.06, 0.055), (0, -(CT_D + 0.02) / 2 - 0.0, CT_H - 0.0275),
    M["walnut"], bevel=0.026, segs=4, parent=counter)  # rounded walnut front edge
box("Counter_Kick", c_ct, (CT_W - 0.16, 0.02, 0.09), (0, -CT_D / 2 + 0.07, 0.045),
    M["dark_wood"], bevel=0.004, parent=counter)
# vertical fluted walnut front: close-spaced half-round ribs (one mesh)
_bm = bmesh.new()
_RIB_R, _RIB_P, _Z0, _Z1 = 0.017, 0.036, 0.1, 0.925
_YF = -(CT_D - 0.06) / 2 + 0.03  # body front face (local)
_n = int((CT_W - 0.16) / _RIB_P)
for k in range(_n):
    xc = -(_n - 1) * _RIB_P / 2 + k * _RIB_P
    ring_lo, ring_hi = [], []
    for j in range(8):
        a = math.pi * j / 7
        x = xc + _RIB_R * math.cos(a)
        y = _YF - _RIB_R * math.sin(a)
        ring_lo.append(_bm.verts.new((x, y, _Z0)))
        ring_hi.append(_bm.verts.new((x, y, _Z1)))
    for j in range(7):
        _bm.faces.new((ring_lo[j], ring_lo[j + 1], ring_hi[j + 1], ring_hi[j]))
bmesh.ops.recalc_face_normals(_bm, faces=_bm.faces)
for f in _bm.faces:  # make sure ribs face the customer (-Y)
    if f.normal.y > 0:
        f.normal_flip()
finish_mesh(_bm, "Counter_Fluting", c_ct, M["walnut"], (0, 0, 0), counter, 80)
# left end flutes (facing -X)
_bm = bmesh.new()
_n2 = int((CT_D - 0.2) / _RIB_P)
for k in range(_n2):
    yc = -(_n2 - 1) * _RIB_P / 2 + k * _RIB_P + 0.03
    lo, hi = [], []
    for j in range(8):
        a = math.pi * j / 7
        lo.append(_bm.verts.new((-CT_W / 2 - _RIB_R * math.sin(a), yc + _RIB_R * math.cos(a), _Z0)))
        hi.append(_bm.verts.new((-CT_W / 2 - _RIB_R * math.sin(a), yc + _RIB_R * math.cos(a), _Z1)))
    for j in range(7):
        _bm.faces.new((lo[j], lo[j + 1], hi[j + 1], hi[j]))
bmesh.ops.recalc_face_normals(_bm, faces=_bm.faces)
finish_mesh(_bm, "Counter_FlutingEnd", c_ct, M["walnut"], (0, 0, 0), counter, 80)
box("Counter_BrassBand", c_ct, (CT_W - 0.14, 0.008, 0.024), (0, _YF - _RIB_R - 0.006, 0.948),
    M["brass_band"], bevel=0.002, parent=counter)
box("Counter_CoveLED", c_ct, (CT_W - 0.1, 0.016, 0.008), (0, -(CT_D + 0.02) / 2 + 0.035, CT_H - 0.058),
    M["led_2700"], bevel=0.0, parent=counter)  # warm cove under the top's lip
box("Counter_ToeLED", c_ct, (CT_W - 0.18, 0.012, 0.008), (0, -CT_D / 2 + 0.055, 0.092),
    M["led_2700_soft"], bevel=0.0, parent=counter)
# espresso machine (local to counter)
em = empty("Counter_Espresso", c_ct, (2.0, 0.1, CT_H), parent=counter)
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


cup("Cup_1", (2.42, -0.05, CT_H), counter)
cup("Cup_2", (2.58, -0.1, CT_H), counter)
# grinder + cup stack: espresso section (right), against the back
gr = empty("Counter_Grinder", c_ct, (1.55, 0.12, CT_H), parent=counter)
box("Grinder_Body", c_ct, (0.16, 0.2, 0.28), (0, 0, 0.14), M["graphite"], bevel=0.02, parent=gr)
cyl("Grinder_Hopper", c_ct, 0.075, 0.16, (0, 0, 0.36), M["glass"], segs=16, parent=gr, r2=0.045)
cyl("Grinder_Beans", c_ct, 0.06, 0.07, (0, 0, 0.31), M["coffee"], segs=16, parent=gr)
for k in range(4):
    cyl(f"Counter_CupStack{k}", c_ct, 0.04, 0.05, (2.45, 0.18, CT_H + 0.025 + k * 0.045),
        M["cup"], segs=14, parent=counter, r2=0.045)
box("Counter_KnockBox", c_ct, (0.16, 0.16, 0.12), (1.3, 0.14, CT_H + 0.06), M["steel"],
    bevel=0.01, parent=counter)

# ================================================================ 8. PaymentTerminal
c_pt = make_coll("PaymentTerminal")
c_rg = make_coll("Register")
rg = empty("Register", c_rg, (0.0, COUNTER_Y + 0.05, CT_H))
box("Register_Drawer", c_rg, (0.42, 0.38, 0.1), (0, 0.02, 0.05), M["graphite"], bevel=0.012,
    parent=rg)
box("Register_DrawerFront", c_rg, (0.36, 0.01, 0.05), (0, -0.173, 0.05), M["hood"], bevel=0.004,
    parent=rg)
cyl("Register_Stand", c_rg, 0.022, 0.2, (0, 0.06, 0.2), M["steel"], segs=10, parent=rg)
box("Register_Screen", c_rg, (0.36, 0.025, 0.25), (0, 0.075, 0.36), M["graphite"], bevel=0.01,
    parent=rg, rot=(18, 0, 0))
box("Register_ScreenGlow", c_rg, (0.32, 0.004, 0.21), (0, 0.091, 0.365), M["screen"], bevel=0.0,
    parent=rg, rot=(18, 0, 0))  # faces Milo (+Y)
box("Register_CustomerDisplay", c_rg, (0.16, 0.015, 0.1), (0, -0.0, 0.53), M["graphite"],
    bevel=0.006, parent=rg, rot=(-15, 0, 0))
box("Register_CustomerGlow", c_rg, (0.14, 0.003, 0.08), (0, -0.009, 0.53), M["screen"],
    bevel=0.0, parent=rg, rot=(-15, 0, 0))
box("Register_CardReader", c_rg, (0.07, 0.1, 0.02), (-0.27, -0.05, 0.01), M["graphite"],
    bevel=0.006, parent=rg)
pt = empty("PaymentTerminal", c_pt, (0.6, COUNTER_Y - 0.17, CT_H), rot_z=-14)  # 'Braintree' card reader beside the Gate POS
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
od = empty("OrderDesk", c_od, (-4.6, -1.4, 0))
DK_W, DK_D, DK_H = 2.0, 0.65, 0.76
box("OrderDesk_Top", c_od, (DK_W, DK_D, 0.045), (0, 0, DK_H - 0.0225), M["walnut"], bevel=0.01,
    parent=od)
for sx in (-1, 1):
    box(f"OrderDesk_Leg{'L' if sx < 0 else 'R'}", c_od, (0.045, DK_D - 0.06, DK_H - 0.045),
        (sx * (DK_W / 2 - 0.06), 0, (DK_H - 0.045) / 2), M["oak_edge_d"], bevel=0.008, parent=od)
box("OrderDesk_Modesty", c_od, (DK_W - 0.16, 0.02, 0.34), (0, -DK_D / 2 + 0.06, DK_H - 0.22),
    M["walnut"], bevel=0.006, parent=od)
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
sb = empty("SandboxBox", c_sb, (-2.9, -1.45, 0))
PL_H, G = 0.36, 0.6
box("SandboxBox_Plinth", c_sb, (0.72, 0.72, PL_H), (0, 0, PL_H / 2), M["dark_grey"], bevel=0.02,
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
vm = empty("VultrVM", c_vm, (-7.2, 4.25, 0))
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

def face_plane(name, coll, w, h, loc, material, parent=None):
    """Plane in local XZ facing -Y with clean 0-1 UVs (u = left->right, v = bottom->top)."""
    bm = bmesh.new()
    vs = [bm.verts.new(c) for c in ((-w / 2, 0, -h / 2), (w / 2, 0, -h / 2),
                                    (w / 2, 0, h / 2), (-w / 2, 0, h / 2))]
    f = bm.faces.new(vs)
    bm.normal_update()
    if f.normal.y > 0:
        f.normal_flip()
    uv = bm.loops.layers.uv.new("UVMap")
    for lp in f.loops:
        co = lp.vert.co
        lp[uv].uv = ((co.x + w / 2) / w, (co.z + h / 2) / h)
    return finish_mesh(bm, name, coll, material, loc, parent)


# ================================================================ 7. Gate (countertop POS terminal)
# The Counterfoil gate *is* the POS card terminal: the web page draws the live result
# (green tick / amber hold / red block) on Gate_Screen.
c_gt = make_coll("Gate")
gate = empty("Gate", c_gt, (0.4, COUNTER_Y - 0.2, CT_H), rot_z=-14)  # customer side of the Register
cyl("Gate_Base", c_gt, 0.055, 0.014, (0, 0, 0.007), M["graphite"], segs=24, parent=gate)
cyl("Gate_Swivel", c_gt, 0.018, 0.06, (0, 0, 0.044), M["steel"], segs=12, parent=gate)
gbody = empty("Gate_Body", c_gt, (0, 0, 0.155), parent=gate)
gbody.rotation_euler = (math.radians(-14), 0, 0)  # leans back, screen faces the customer (-Y)
box("Gate_Shell", c_gt, (0.11, 0.026, 0.18), (0, 0, 0), M["graphite"], bevel=0.012, segs=3,
    parent=gbody)
box("Gate_Keypad", c_gt, (0.085, 0.004, 0.02), (0, -0.0135, -0.073), M["grey"], bevel=0.0,
    parent=gbody)
M["gate_screen"] = mat("M_GateScreen", "#151a20", 0.3, emit="#1f2a36", emit_strength=1.0)
face_plane("Gate_Screen", c_gt, 0.09, 0.14, (0, -0.0136, 0.012), M["gate_screen"], gbody)
gl = empty("Gate_Light", c_gt, (0.04, 0, 0.092), parent=gbody)
sphere("Gate_Light_LED", c_gt, 0.006, (0, 0, 0), M["amber"], parent=gl, segs=10, rings=6)

# --- Ledger: open accounting book on a small walnut stand next to the POS (decorative)
c_lg = make_coll("Ledger")
lg = empty("Ledger", c_lg, (0.98, COUNTER_Y - 0.12, CT_H), rot_z=-10)
box("Ledger_StandBase", c_lg, (0.3, 0.2, 0.02), (0, 0, 0.01), M["walnut"], bevel=0.005,
    parent=lg)
box("Ledger_StandRest", c_lg, (0.03, 0.12, 0.07), (0, 0.05, 0.045), M["walnut"], bevel=0.005,
    parent=lg)
bk = empty("Ledger_Book", c_lg, (0, 0.0, 0.075), parent=lg)
bk.rotation_euler = (math.radians(28), 0, 0)  # tilted toward the customer
box("Ledger_Cover", c_lg, (0.34, 0.23, 0.012), (0, 0, 0), M["green_dark"], bevel=0.004,
    parent=bk)
for sx in (-1, 1):
    pg = empty(f"Ledger_Page{sx}", c_lg, (sx * 0.083, 0, 0.012), parent=bk)
    pg.rotation_euler = (0, math.radians(-sx * 5), 0)
    box(f"Ledger_PageBlock{sx}", c_lg, (0.158, 0.215, 0.012), (0, 0, 0), M["paper"],
        bevel=0.002, segs=1, parent=pg)
    for k in range(9):
        box(f"Ledger_Rule{sx}_{k}", c_lg, (0.13, 0.0025, 0.0012),
            (0.0, -0.085 + k * 0.021, 0.0066), M["grey"], bevel=0.0, parent=pg)
    box(f"Ledger_Margin{sx}", c_lg, (0.0022, 0.19, 0.0012), (-sx * 0.045, 0, 0.0068),
        M["rust"], bevel=0.0, parent=pg)

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


def logo_disc(name, coll, r, depth, loc, parent=None, rot=(90, 0, 0), m_face=None):
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
    ob = finish_mesh(bm, name, coll, m_face or m_logo, loc, parent, 40, rot)
    ob.data.materials.append(m_logo_edge)
    return ob


# --- back wall behind the counter (carries menu board + logo sign)
c_bw = make_coll("BackWall")
WALL_FRONT = 4.7
box("BackWall", c_bw, (2 * (SIDE_IN + WALL_T), WALL_T, ROOM_H), (0.0, WALL_FRONT + WALL_T / 2,
    ROOM_H / 2), M["wall_espresso"], bevel=0.006)  # full width, cream plaster


# --- Logo_Sign: ~45 cm disc on the counter's centre walnut panel (front, facing -Y)
c_ls = make_coll("Logo_Sign")
COUNTER_PANEL_FRONT = COUNTER_Y - 0.31 + 0.03 - 0.007  # counter y + panel offset - half thickness
sign = logo_disc("Logo_Sign", c_ls, 0.225, 0.015, (0.0, COUNTER_PANEL_FRONT - 0.0075, 0.5))

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

MB_W, MB_H, MB_TOP = 1.2, 0.72, 2.66
c_mb = make_coll("MenuBoard")
mb = empty("MenuBoard", c_mb, (0.0, WALL_FRONT, MB_TOP - MB_H / 2))
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
RAIL_Z, RAIL_Y = 2.705, COUNTER_Y  # high enough to project above the menu in Cam_Overview
for i, x in enumerate((-2.9, 2.9)):
    box(f"PendantLamps_Arm{i}", c_pl, (0.03, WALL_FRONT - RAIL_Y + 0.03, 0.03),
        (x, (WALL_FRONT + RAIL_Y) / 2, RAIL_Z), M["graphite"], bevel=0.008, parent=pl)
box("PendantLamps_Rail", c_pl, (5.83, 0.03, 0.03), (0.0, RAIL_Y, RAIL_Z), M["graphite"],
    bevel=0.008, parent=pl)
BULBS = []
for i, x in enumerate((-2.3, -0.9, 0.9, 2.3)):
    cyl(f"PendantLamps_Cord{i}", c_pl, 0.004, RAIL_Z - 1.95, (x, RAIL_Y, (RAIL_Z + 1.95) / 2), M["graphite"],
        segs=6, parent=pl)
    sphere(f"PendantLamps_Shade{i}", c_pl, 0.13, (x, RAIL_Y, 1.78), M["rattan"], parent=pl,
           scale=(1, 1, 1.32), cut_below=-0.72, segs=18, rings=12)  # woven egg, open at the bottom
    for k, (zr, rr) in enumerate(((1.66, 0.112), (1.78, 0.131), (1.9, 0.112), (2.0, 0.07))):
        torus(f"PendantLamps_Weave{i}_{k}", c_pl, rr, 0.006, (x, RAIL_Y, zr), M["rattan_dark"],
              parent=pl, rot=(0, 0, 0))
    sphere(f"PendantLamps_Bulb{i}", c_pl, 0.04, (x, RAIL_Y, 1.74), M["bulb"], parent=pl,
           segs=12, rings=8)
    BULBS.append((x, RAIL_Y, 1.62))

# --- PastryCase: large 2-shelf display left of the register, filled with desserts
c_pc = make_coll("PastryCase")
PC_W, PC_D, PC_H = 1.3, 0.5, 0.52
pc = empty("PastryCase", c_pc, (-1.35, COUNTER_Y - 0.02, 1.0))
box("PastryCase_Base", c_pc, (PC_W, PC_D, 0.06), (0, 0, 0.03), M["walnut"], bevel=0.01,
    parent=pc)
box("PastryCase_Back", c_pc, (PC_W, 0.02, PC_H), (0, PC_D / 2 - 0.01, PC_H / 2 + 0.03),
    M["walnut"], bevel=0.006, parent=pc)
for sx in (-1, 1):
    box(f"PastryCase_Side{sx}", c_pc, (0.012, PC_D, PC_H), (sx * (PC_W / 2 - 0.006), 0,
        PC_H / 2 + 0.03), M["glass"], bevel=0.0, parent=pc)
box("PastryCase_Glass", c_pc, (PC_W - 0.02, PC_D - 0.04, 0.012), (0, 0.0, PC_H + 0.03),
    M["glass"], bevel=0.0, parent=pc)  # top glass
box("PastryCase_GlassFront", c_pc, (PC_W - 0.02, 0.012, PC_H + 0.05),
    (0, -PC_D / 2 + 0.1, PC_H / 2 + 0.03), M["glass"], bevel=0.0, parent=pc, rot=(-14, 0, 0))
box("PastryCase_Shelf", c_pc, (PC_W - 0.04, PC_D - 0.12, 0.012), (0, 0.04, 0.3), M["glass"],
    bevel=0.0, parent=pc)
box("PastryCase_InnerLED", c_pc, (PC_W - 0.08, 0.02, 0.008), (0, -0.06, PC_H + 0.028),
    M["led_2700"], bevel=0.0, parent=pc)
EXTRA_LIGHTS.append(("PastryCase_Light", (-1.35, COUNTER_Y - 0.08, 1.45), 6))
box("PastryCase_TopTrim", c_pc, (PC_W, PC_D, 0.02), (0, 0, PC_H + 0.045), M["walnut"],
    bevel=0.006, parent=pc)
M["cake"] = mat("M_CakeSponge", "#e8c898", 0.7)
M["cake_cream"] = mat("M_CakeCream", "#f6ecdc", 0.6)
M["choc"] = mat("M_Chocolate", "#5a3826", 0.45)
M["cookie"] = mat("M_Cookie", "#c98f55", 0.75)
L1, L2 = 0.06, 0.306  # shelf heights


def tray(name, x, z, w=0.26):
    box(name, c_pc, (w, 0.2, 0.008), (x, 0.03, z + 0.004), M["white"], bevel=0.002, segs=1,
        parent=pc)


def cake_slice(name, x, y, z, rot):
    bm = bmesh.new()
    pts = [(0, 0), (0.1, -0.035), (0.1, 0.035)]
    vb = [bm.verts.new((px, py, 0)) for px, py in pts]
    vt = [bm.verts.new((px, py, 0.07)) for px, py in pts]
    bm.faces.new(vb[::-1]); bm.faces.new(vt)
    for i in range(3):
        j = (i + 1) % 3
        bm.faces.new((vb[i], vb[j], vt[j], vt[i]))
    ob = finish_mesh(bm, name, c_pc, M["cake"], (x, y, z), pc, 30, (0, 0, rot))
    box(f"{name}_Frost", c_pc, (0.1, 0.07, 0.012), (x + 0.05 * math.cos(math.radians(rot)),
        y + 0.05 * math.sin(math.radians(rot)), z + 0.076), M["cake_cream"], bevel=0.004,
        parent=pc, rot=(0, 0, rot))
    box(f"{name}_Layer", c_pc, (0.098, 0.071, 0.01), (x + 0.05 * math.cos(math.radians(rot)),
        y + 0.05 * math.sin(math.radians(rot)), z + 0.035), M["choc"], bevel=0.0,
        parent=pc, rot=(0, 0, rot))


# lower shelf: croissants | muffins | cookies
tray("PastryCase_Tray0", -0.42, L1)
for k in range(3):
    capsule(f"PastryCase_Croissant{k}", c_pc, 0.028, 0.13, (-0.48 + k * 0.06, 0.03 + (k % 2) * 0.04,
            L1 + 0.035), M["pastry"], parent=pc, rot=(0, 90, 30 - k * 20), sy=0.8)
tray("PastryCase_Tray1", -0.05, L1)
for k in range(4):
    mx, my = -0.1 + (k % 2) * 0.1, -0.02 + (k // 2) * 0.1
    cyl(f"PastryCase_MuffinCup{k}", c_pc, 0.028, 0.04, (mx, my, L1 + 0.028), M["glaze"],
        segs=14, parent=pc, r2=0.034)
    sphere(f"PastryCase_MuffinTop{k}", c_pc, 0.038, (mx, my, L1 + 0.048),
           M["pastry_dark"] if k % 2 else M["choc"], parent=pc, cut_below=0.0, segs=14, rings=8)
tray("PastryCase_Tray2", 0.32, L1, 0.3)
for k in range(5):
    cyl(f"PastryCase_Cookie{k}", c_pc, 0.038, 0.012, (0.24 + (k % 3) * 0.08,
        -0.01 + (k // 3) * 0.09, L1 + 0.014 + (k // 3) * 0.0), M["cookie"], segs=16, parent=pc)
# upper shelf: cinnamon buns | cake slices | glazed donuts
tray("PastryCase_Tray3", -0.4, L2)
for k in range(3):
    bx = -0.48 + k * 0.08
    torus(f"PastryCase_CinnamonBun{k}", c_pc, 0.026, 0.016, (bx, 0.04, L2 + 0.024),
          M["pastry"], parent=pc, rot=(0, 0, 0))
    sphere(f"PastryCase_CinnamonTop{k}", c_pc, 0.025, (bx, 0.04, L2 + 0.03), M["glaze"],
           parent=pc, scale=(1, 1, 0.45), segs=12, rings=6)
tray("PastryCase_Tray4", 0.0, L2)
for k in range(3):
    cake_slice(f"PastryCase_Cake{k}", -0.09 + k * 0.08, 0.02, L2 + 0.008, 90 + (k - 1) * 12)
tray("PastryCase_Tray5", 0.38, L2)
for k in range(3):
    torus(f"PastryCase_Donut{k}", c_pc, 0.028, 0.014, (0.3 + k * 0.08, 0.03, L2 + 0.022),
          M["glaze"] if k != 1 else M["choc"], parent=pc, rot=(0, 0, 0))

# --- Plants: one by the shelves, one by the VultrVM
c_pt2 = make_coll("Plants")
plants = empty("Plants", c_pt2)


def plant(tag, loc, h, pot="rust", parent=None, coll=None, s=1.0):
    coll = coll or c_pt2
    root = empty(f"Plant_{tag}", coll, loc, parent=parent or plants)
    cyl(f"Plant_{tag}_Pot", coll, 0.1 * s, 0.28 * s, (0, 0, 0.14 * s), M[pot], segs=18,
        parent=root, r2=0.135 * s)
    cyl(f"Plant_{tag}_Soil", coll, 0.125 * s, 0.01, (0, 0, 0.27 * s), M["soil"], segs=18,
        parent=root)
    leaves = [(0, 0, 0.42, 0.16), (0.08, 0.03, 0.62, 0.13), (-0.07, -0.04, 0.68, 0.12),
              (0.02, 0.05, 0.86, 0.11), (-0.03, -0.02, 0.98, 0.09)]
    base = 0.3 * s
    for i, (x, y, z, r) in enumerate(leaves):
        z = base + (z - 0.3) * (h - base) / 0.7
        sphere(f"Plant_{tag}_Leaf{i}", coll, r * s, (x * s, y * s, z),
               M["leaf"] if i % 2 == 0 else M["leaf_light"], parent=root,
               scale=(1, 1, 1.15), segs=14, rings=8)
    return root


plant("Shelves", (4.8, 4.35, 0), 1.05)
plant("VultrVM", (-7.55, 3.78, 0), 0.8)
plant("Corner", (-7.5, -0.95, 0), 1.55, pot="pot_cream", s=1.3)
plant("BackRight", (7.3, 4.2, 0), 1.1, pot="pot_char", s=1.1)
plant("BackLeft", (-4.6, 4.3, 0), 0.65, pot="pot_cream", s=0.8)
plant("Divider", (5.0, -1.75, 0), 1.6, pot="pot_cream", s=1.3)  # tall plant at the divider end

# (no bar stools: normal cafe seating lives in CafeTables)


# ================================================================ 12. Screens, pickup, reading nook
WARM_2700K = (1.0, 0.63, 0.33)  # linear RGB approximation of a 2700K bulb


def image_mat(name, path, emissive=1.0, rough=0.4):
    img = bpy.data.images.load(path, check_existing=False)
    img.name = os.path.basename(path)
    img.pack()
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    ekey = "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
    nt.links.new(tex.outputs["Color"], bsdf.inputs[ekey])
    bsdf.inputs["Emission Strength"].default_value = emissive
    bsdf.inputs["Roughness"].default_value = rough
    return m


BRAND = os.path.join(os.path.dirname(OUT), "brand")

# --- AdScreen_L / AdScreen_R: portrait 9:16 screens flanking the menu board
for side, x, img in (("L", -4.0, "ad-1-latte.png"), ("R", 4.0, "ad-3-matcha.png")):
    c_ad = make_coll(f"AdScreen_{side}")
    bez = box(f"AdScreen_{side}", c_ad, (0.48, 0.03, 0.83), (x, WALL_FRONT - 0.015, 2.27),
              M["graphite"], bevel=0.008)
    face_plane(f"AdScreen_{side}_Face", c_ad, 0.45, 0.8, (0, -0.0155, 0),
               image_mat(f"M_AdScreen_{side}", os.path.join(BRAND, "ads", img), 1.0), bez)


# --- warm LED halos behind the ad screens (+ subtle one behind the menu board)
import numpy as np  # bundled with Blender

M["led_gold"] = mat("M_LEDGold", "#ffc766", 0.3, emit="#ffc766", emit_strength=1.5)


def rounded_rect_points(w, h, r, seg=6):
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90),
                       (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)):
        for k in range(seg + 1):
            a = math.radians(a0 + 90 * k / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def led_tube(name, coll, w, h, loc, parent=None, thick=0.01):
    """Rounded-rectangle rope light in local XZ (thin tube, ~1 cm)."""
    cu = bpy.data.curves.new(name + "_curve", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = thick / 2
    cu.bevel_resolution = 1
    sp = cu.splines.new("POLY")
    pts = rounded_rect_points(w, h, 0.03)
    sp.points.add(len(pts) - 1)
    for p_, (x, z) in zip(sp.points, pts):
        p_.co = (x, 0, z, 1)
    sp.use_cyclic_u = True
    tmp = bpy.data.objects.new(name + "_tmp", cu)
    scene.collection.objects.link(tmp)
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    me.name = name
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.clear()
    me.materials.append(M["led_gold"])
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    link(ob, coll)
    if parent:
        ob.parent = parent
    return ob


def glow_material(name, plane_w, plane_h, inner_w, inner_h, peak, px=256):
    """Generated soft-falloff gold glow (alpha) around an inner rounded rect."""
    W = px
    H = max(8, int(px * plane_h / plane_w))
    xs = (np.arange(W) + 0.5) / W * plane_w - plane_w / 2
    zs = (np.arange(H) + 0.5) / H * plane_h - plane_h / 2
    X, Z = np.meshgrid(xs, zs)
    r = 0.03
    qx = np.abs(X) - (inner_w / 2 - r)
    qz = np.abs(Z) - (inner_h / 2 - r)
    d = np.hypot(np.maximum(qx, 0), np.maximum(qz, 0)) - r
    d = np.maximum(d, 0)
    margin = min(plane_w - inner_w, plane_h - inner_h) / 2
    a = peak * np.exp(-(d / (margin * 0.38)) ** 1.4)
    a[d >= margin * 0.98] = 0
    img = bpy.data.images.new(name + "_img", W, H, alpha=True)
    rgba = np.zeros((H, W, 4), dtype=np.float32)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = 1.0, 0.80, 0.42
    rgba[..., 3] = a
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    ekey = "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
    nt.links.new(tex.outputs["Color"], bsdf.inputs[ekey])
    nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    bsdf.inputs["Emission Strength"].default_value = 0.6
    for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
        try:
            setattr(m, attr, val)
        except Exception:
            pass
    return m


for side, x in (("L", -4.0), ("R", 4.0)):
    scr = O_ = bpy.data.objects[f"AdScreen_{side}"]
    coll = bpy.data.collections[f"AdScreen_{side}"]
    # tube sits between screen and wall, ~2 cm outside the bezel
    led_tube(f"AdScreen_{side}_Halo", coll, 0.52, 0.87, (0, 0.009, 0), parent=scr)
    gw, gh = 0.48 + 0.22, 0.83 + 0.06
    face_plane(f"AdScreen_{side}_HaloGlow", coll, gw, gh, (0, 0.0135, 0),
               glow_material(f"M_AdScreen_{side}_Glow", gw, gh, 0.5, 0.85, 0.5), scr)
mbo = bpy.data.objects["MenuBoard"]
gw, gh = MB_W + 0.26, MB_H + 0.26
face_plane("MenuBoard_HaloGlow", bpy.data.collections["MenuBoard"], gw, gh, (0, -0.0015, 0),
           glow_material("M_MenuBoard_Glow", gw, gh, MB_W, MB_H, 0.32), mbo)

# --- PickupCorner: raised hand-off ledge at the counter end next to the Gate
c_pk = make_coll("PickupCorner")
pk = empty("PickupCorner", c_pk, (CT_W / 2 + 0.18, COUNTER_Y, 0))  # far end, after the espresso section
box("PickupCorner_Cabinet", c_pk, (0.3, 0.5, 1.06), (0, 0, 0.53), M["dark_cabinet"], bevel=0.015,
    parent=pk)
box("PickupCorner_Panel", c_pk, (0.012, 0.42, 0.76), (0.152, 0, 0.5), M["walnut"],
    bevel=0.004, parent=pk)
box("PickupCorner_Ledge", c_pk, (0.34, 0.54, 0.04), (0, 0, 1.08), M["walnut"], bevel=0.008,
    parent=pk)
LEDGE_Z = 1.10
# sign card + "PICK UP HERE" text converted to mesh
box("PickupCorner_SignStand", c_pk, (0.08, 0.04, 0.02), (0, 0.17, LEDGE_Z + 0.01),
    M["walnut"], bevel=0.005, parent=pk)
box("PickupCorner_SignCard", c_pk, (0.28, 0.008, 0.075), (0, 0.17, LEDGE_Z + 0.058),
    M["cream"], bevel=0.003, parent=pk)
_cu = bpy.data.curves.new("PickupText", "FONT")
_cu.body = "PICK UP HERE"
_cu.size = 0.032
_cu.extrude = 0.0006
_cu.align_x = "CENTER"
_cu.align_y = "CENTER"
_tob = bpy.data.objects.new("PickupText_tmp", _cu)
scene.collection.objects.link(_tob)
_me = bpy.data.meshes.new_from_object(_tob.evaluated_get(bpy.context.evaluated_depsgraph_get()))
bpy.data.objects.remove(_tob)
bpy.data.curves.remove(_cu)
_me.name = "PickupCorner_SignText"
_w = max(v.co.x for v in _me.vertices) - min(v.co.x for v in _me.vertices)
_sc = min(1.0, 0.24 / _w)
for v in _me.vertices:
    v.co *= _sc
_me.materials.append(M["graphite"])
_txt = bpy.data.objects.new("PickupCorner_SignText", _me)
_txt.location = (0, 0.17 - 0.0055, LEDGE_Z + 0.058)
_txt.rotation_euler = (math.radians(90), 0, 0)
link(_txt, c_pk)
_txt.parent = pk
M["kraft"] = mat("M_Kraft", "#b98a5e", 0.8)
for i, cx in enumerate((-0.085, 0.0, 0.085)):
    cup_root = empty(f"PickupCorner_Cup{i}", c_pk, (cx, -0.06 + (i % 2) * 0.03, LEDGE_Z),
                     parent=pk)
    cyl(f"PickupCorner_Cup{i}_Body", c_pk, 0.028, 0.12, (0, 0, 0.06), M["holiday_red"],
        segs=16, parent=cup_root, r2=0.036)  # winter cup
    cyl(f"PickupCorner_Cup{i}_Band", c_pk, 0.0349, 0.012, (0, 0, 0.104), M["cream"], segs=16,
        parent=cup_root, r2=0.0356)
    cyl(f"PickupCorner_Cup{i}_Sleeve", c_pk, 0.0335, 0.045, (0, 0, 0.065), M["kraft"],
        segs=16, parent=cup_root, r2=0.0355)
    cyl(f"PickupCorner_Cup{i}_Lid", c_pk, 0.038, 0.012, (0, 0, 0.126), M["cup"], segs=16,
        parent=cup_root, r2=0.034)
    cyl(f"PickupCorner_Cup{i}_LidTop", c_pk, 0.028, 0.008, (0, 0, 0.136), M["cup"], segs=16,
        parent=cup_root)
    box(f"PickupCorner_Cup{i}_Label", c_pk, (0.03, 0.004, 0.012), (0, -0.0345, 0.1),
        M["cream"], bevel=0.0, parent=cup_root, rot=(-4, 0, 0))

# --- ReadingNook: right side of the platform, clear of the courier/label space
c_rn = make_coll("ReadingNook")
M["velvet_green"] = mat("M_VelvetGreen", "#2f5a46", 0.85)
M["velvet_rust"] = mat("M_VelvetRust", "#a5573a", 0.85)
M["rug_in"] = mat("M_RugInner", "#e8ddcb", 0.95)
M["rug_out"] = mat("M_RugBorder", "#c4a789", 0.95)
M["brass_m"] = mat("M_Brass", "#c9a35f", 0.35, metal=0.7)
M["lampshade"] = mat("M_ReadingShade", "#f3e6cc", 0.6, emit="#ffbf80", emit_strength=0.6)
NOOK_X, NOOK_Y, NOOK_ROT = 6.05, -3.15, 40  # quiet front-right corner, chairs face the camera
nook = empty("ReadingNook", c_rn, (NOOK_X, NOOK_Y, 0), rot_z=NOOK_ROT)
cyl("ReadingNook_RugBorder", c_rn, 1.12, 0.008, (0, -0.1, 0.004), M["rug_out"], segs=48,
    parent=nook)
cyl("ReadingNook_Rug", c_rn, 1.02, 0.01, (0, -0.1, 0.005), M["rug_in"], segs=48,
    parent=nook)


def armchair(tag, loc, rot_z, fabric):
    root = empty(f"ReadingNook_Chair{tag}", c_rn, loc, rot_z=rot_z, parent=nook)
    box(f"Chair{tag}_Base", c_rn, (0.56, 0.52, 0.2), (0, 0, 0.19), fabric, bevel=0.05, segs=3,
        parent=root)
    box(f"Chair{tag}_Cushion", c_rn, (0.44, 0.42, 0.09), (0, -0.02, 0.33), fabric, bevel=0.035,
        segs=3, parent=root)
    box(f"Chair{tag}_Back", c_rn, (0.56, 0.13, 0.46), (0, 0.205, 0.52), fabric, bevel=0.05,
        segs=3, parent=root, rot=(-8, 0, 0))
    for sx in (-1, 1):
        box(f"Chair{tag}_Arm{sx}", c_rn, (0.085, 0.5, 0.2), (sx * 0.24, 0.0, 0.38), fabric,
            bevel=0.04, segs=3, parent=root)
        for sy in (-1, 1):
            cyl(f"Chair{tag}_Leg{sx}{sy}", c_rn, 0.016, 0.09,
                (sx * 0.22, sy * 0.2, 0.045), M["walnut"], segs=8, parent=root, r2=0.011)
    return root


armchair("Green", (-0.75, 0.12, 0), 24, M["velvet_green"])
armchair("Rust", (0.75, 0.12, 0), -24, M["velvet_rust"])
# round side table with a cup and an open book
tb = empty("ReadingNook_Table", c_rn, (0.0, -0.5, 0), parent=nook)
cyl("Table_Base", c_rn, 0.12, 0.015, (0, 0, 0.0075), M["brass_m"], segs=24, parent=tb)
cyl("Table_Stem", c_rn, 0.016, 0.47, (0, 0, 0.25), M["brass_m"], segs=10, parent=tb)
cyl("Table_Top", c_rn, 0.19, 0.025, (0, 0, 0.495), M["walnut"], segs=32, parent=tb)
TZ = 0.5075
cyl("Table_Saucer", c_rn, 0.05, 0.006, (0.08, 0.05, TZ + 0.003), M["cup"], parent=tb)
cyl("Table_Cup", c_rn, 0.033, 0.06, (0.08, 0.05, TZ + 0.036), M["cup"], parent=tb, r2=0.038)
cyl("Table_Coffee", c_rn, 0.034, 0.003, (0.08, 0.05, TZ + 0.064), M["coffee"], parent=tb)
for sx in (-1, 1):
    box(f"Table_BookPage{sx}", c_rn, (0.075, 0.11, 0.008),
        (-0.06 + sx * 0.037, -0.05, TZ + 0.012), M["paper"], bevel=0.002, segs=1, parent=tb,
        rot=(0, -sx * 8, 15))
box("Table_BookCover", c_rn, (0.16, 0.115, 0.006), (-0.06, -0.05, TZ + 0.004), M["rust"],
    bevel=0.002, segs=1, parent=tb, rot=(0, 0, 15))
# brass floor reading lamp between/behind the chairs
lp = empty("ReadingNook_Lamp", c_rn, (0.0, 0.32, 0), parent=nook)
cyl("Lamp_Base", c_rn, 0.12, 0.02, (0, 0, 0.01), M["brass_m"], segs=24, parent=lp)
cyl("Lamp_Pole", c_rn, 0.011, 1.3, (0, 0, 0.67), M["brass_m"], segs=10, parent=lp)
_bm = bmesh.new()
bmesh.ops.create_cone(_bm, cap_ends=False, segments=24, radius1=0.16, radius2=0.1, depth=0.2)
finish_mesh(_bm, "Lamp_Shade", c_rn, M["lampshade"], (0, 0, 1.36), lp, 60)
sphere("Lamp_Bulb", c_rn, 0.035, (0, 0, 1.31), M["bulb"], parent=lp, segs=12, rings=8)
_a = math.radians(NOOK_ROT)
NOOK_LAMP = (NOOK_X - 0.32 * math.sin(_a), NOOK_Y + 0.32 * math.cos(_a), 1.30)

# --- ReadingDivider: waist-high double-sided bookshelf + tall plant, closing the nook off
c_dv = make_coll("ReadingDivider")
dv = empty("ReadingDivider", c_dv, (6.1, -1.75, 0))  # low divider along the nook's north side
DW, DD, DH = 1.8, 0.34, 0.85
for sx in (-1, 1):
    box(f"Divider_End{sx}", c_dv, (0.03, DD, DH), (sx * (DW / 2 - 0.015), 0, DH / 2),
        M["walnut"], bevel=0.006, parent=dv)
for i, z in enumerate((0.03, 0.46, DH - 0.015)):
    box(f"Divider_Board{i}", c_dv, (DW, DD, 0.03), (0, 0, z), M["walnut"], bevel=0.006,
        parent=dv)
box("Divider_Spine", c_dv, (DW - 0.06, 0.015, DH - 0.06), (0, 0, DH / 2), M["walnut"],
    bevel=0.0, parent=dv)
for side in (-1, 1):  # books on both faces
    for row, z0 in enumerate((0.045, 0.475)):
        xcur, k = -DW / 2 + 0.05, 0
        while xcur < DW / 2 - 0.08:
            w = (0.035, 0.045, 0.04, 0.05, 0.03)[(k + row + side) % 5]
            h = (0.3, 0.27, 0.33, 0.29, 0.31)[(k * 3 + row) % 5]
            if (k + row) % 9 == 8:  # a little gap now and then
                xcur += 0.06
            box(f"Divider_Book{side}_{row}_{k}", c_dv, (w - 0.004, 0.14, h),
                (xcur + w / 2, side * 0.085, z0 + h / 2), BOOK_COLS[(k + row + (side > 0)) % 4],
                bevel=0.003, segs=1, parent=dv)
            xcur += w
            k += 1

# short low bookshelf behind the chairs
ls = empty("ReadingNook_LowShelf", c_rn, (0.0, 0.78, 0), parent=nook)
LW, LD, LH = 0.6, 0.26, 0.5
for sx in (-1, 1):
    box(f"LowShelf_Side{sx}", c_rn, (0.025, LD, LH), (sx * (LW / 2 - 0.0125), 0, LH / 2),
        M["walnut"], parent=ls)
for i, z in enumerate((0.03, 0.25, LH - 0.0125)):
    box(f"LowShelf_Board{i}", c_rn, (LW, LD, 0.025), (0, 0, z), M["walnut"], parent=ls)
for row, z0 in enumerate((0.0425, 0.2625)):
    xcur = -LW / 2 + 0.035
    k = 0
    while xcur < LW / 2 - 0.09:
        w = (0.035, 0.045, 0.04, 0.05)[k % 4]
        h = (0.17, 0.15, 0.18, 0.16)[(k + row) % 4]
        box(f"LowShelf_Book{row}_{k}", c_rn, (w - 0.004, 0.18, h), (xcur + w / 2, -0.01, z0 + h / 2),
            BOOK_COLS[(k + row) % 4], bevel=0.003, segs=1, parent=ls)
        xcur += w
        k += 1


# ================================================================ 13. Seating groups
M["oak"] = mat("M_Oak", "#b08660", 0.5)
M["oak_edge"] = mat("M_OakEdge", "#6f4d33", 0.55)
M["leather"] = mat("M_LeatherBrown", "#6b4128", 0.32)
M["leather_dark"] = mat("M_LeatherSeam", "#4a2c1b", 0.4)
M["fabric_green"] = mat("M_FabricGreen", "#2e4a3e", 0.97)
M["fabric_button"] = mat("M_FabricButton", "#22372e", 0.9)
M["ceramic"] = mat("M_CeramicSage", "#a9b8a0", 0.35)
M["laptop"] = mat("M_LaptopAlu", "#b9bcc1", 0.3, metal=0.6)
M["art_sage"] = mat("M_ArtSage", "#8fa58a", 0.9)
M["art_terra"] = mat("M_ArtTerracotta", "#c67a55", 0.9)
M["art_navy"] = mat("M_ArtNavy", "#3d4c6b", 0.9)


def wood_chair(name, coll, loc, rot_z, parent, m_a=None, m_b=None):
    root = empty(name, coll, loc, rot_z=rot_z, parent=parent)
    m_a = m_a or M["oak"]
    m_b = m_b or m_b
    box(f"{name}_Seat", coll, (0.42, 0.42, 0.045), (0, 0, 0.455), m_a, bevel=0.015,
        parent=root)
    for sx in (-1, 1):
        for sy in (-1, 1):
            cyl(f"{name}_Leg{sx}{sy}", coll, 0.017, 0.44, (sx * 0.175, sy * 0.175, 0.22),
                m_b, segs=8, parent=root, r2=0.014)
        cyl(f"{name}_Post{sx}", coll, 0.015, 0.4, (sx * 0.175, 0.185, 0.68), m_b,
            segs=8, parent=root)
    box(f"{name}_Rail", coll, (0.4, 0.03, 0.09), (0, 0.19, 0.82), m_a, bevel=0.012,
        parent=root)
    box(f"{name}_Rail2", coll, (0.36, 0.022, 0.04), (0, 0.19, 0.66), m_a, bevel=0.008,
        parent=root)
    return root


def hanging_lamp(prefix, coll, x, y, rail_z, shade_z, parent):
    cyl(f"{prefix}_Cord", coll, 0.004, rail_z - shade_z - 0.07, (x, y, (rail_z + shade_z + 0.07) / 2),
        M["graphite"], segs=6, parent=parent)
    sphere(f"{prefix}_Shade", coll, 0.1, (x, y, shade_z), M["brass"], parent=parent,
           scale=(1, 1, 0.85), cut_below=0.0)
    sphere(f"{prefix}_Bulb", coll, 0.034, (x, y, shade_z - 0.005), M["bulb"], parent=parent,
           segs=12, rings=8)


# --- 1. CommunalTable: long oak table, 6 chairs, 3 pendants on a ceiling rail
c_ct2 = make_coll("CommunalTable")
CT_X, CT_Yc = 2.1, -0.4
ctab = empty("CommunalTable", c_ct2, (CT_X, CT_Yc, 0))
box("CommunalTable_Edge", c_ct2, (2.6, 0.9, 0.05), (0, 0, 0.725), M["light_oak"], bevel=0.012,
    parent=ctab)
box("CommunalTable_Top", c_ct2, (2.56, 0.86, 0.012), (0, 0, 0.756), M["light_oak"], bevel=0.004,
    parent=ctab)
for sx in (-1, 1):  # two solid trestle legs + stretcher
    box(f"CommunalTable_Trestle{sx}", c_ct2, (0.08, 0.72, 0.68), (sx * 1.05, 0, 0.36),
        M["light_oak"], bevel=0.015, parent=ctab)
    box(f"CommunalTable_Foot{sx}", c_ct2, (0.12, 0.8, 0.05), (sx * 1.05, 0, 0.025),
        M["light_oak"], bevel=0.012, parent=ctab)
box("CommunalTable_Stretcher", c_ct2, (2.1, 0.06, 0.08), (0, 0, 0.3), M["light_oak"],
    bevel=0.012, parent=ctab)


def metal_chair(name, coll, loc, rot_z, parent):
    """Slim black metal cafe chair (local -Y is the front)."""
    root = empty(name, coll, loc, rot_z=rot_z, parent=parent)
    box(f"{name}_Seat", coll, (0.4, 0.4, 0.02), (0, 0, 0.46), M["black_metal"], bevel=0.006,
        parent=root)
    for sx in (-1, 1):
        for sy in (-1, 1):
            cyl(f"{name}_Leg{sx}{sy}", coll, 0.009, 0.46, (sx * 0.175, sy * 0.175, 0.23),
                M["black_metal"], segs=6, parent=root)
        cyl(f"{name}_Post{sx}", coll, 0.008, 0.36, (sx * 0.175, 0.19, 0.66), M["black_metal"],
            segs=6, parent=root)
    box(f"{name}_BackTop", coll, (0.37, 0.012, 0.05), (0, 0.19, 0.82), M["black_metal"],
        bevel=0.004, parent=root)
    box(f"{name}_BackMid", coll, (0.35, 0.01, 0.02), (0, 0.19, 0.64), M["black_metal"],
        bevel=0.003, parent=root)
    return root


for i, cx in enumerate((-0.95, 0.0, 0.95)):
    metal_chair(f"CommunalChair_N{i}", c_ct2, (cx, 0.7, 0), 0, ctab)  # faces table (-Y)
    metal_chair(f"CommunalChair_S{i}", c_ct2, (cx + 0.08, -0.7, 0), 180, ctab)  # faces table (+Y)
TT = 0.762
for i, (x, y) in enumerate(((-0.8, -0.18), (0.35, 0.2))):
    cyl(f"CommunalTable_Cup{i}", c_ct2, 0.035, 0.09, (x, y, TT + 0.045), M["cup"], segs=14,
        parent=ctab, r2=0.039)
    cyl(f"CommunalTable_Coffee{i}", c_ct2, 0.036, 0.003, (x, y, TT + 0.088), M["coffee"],
        segs=14, parent=ctab)
box("CommunalTable_LaptopBase", c_ct2, (0.32, 0.22, 0.014), (-0.2, -0.2, TT + 0.007),
    M["laptop"], bevel=0.005, parent=ctab, rot=(0, 0, 8))
box("CommunalTable_LaptopLid", c_ct2, (0.32, 0.012, 0.21), (-0.215, -0.09, TT + 0.1),
    M["laptop"], bevel=0.005, parent=ctab, rot=(-12, 0, 8))
cyl("CommunalTable_Vase", c_ct2, 0.045, 0.16, (0.75, 0.0, TT + 0.08), M["ceramic"], segs=16,
    parent=ctab, r2=0.03)
for k, (dx, dy, dz) in enumerate(((0, 0, 0.2), (0.03, 0.02, 0.24), (-0.025, -0.01, 0.23))):
    sphere(f"CommunalTable_Sprig{k}", c_ct2, 0.03, (0.75 + dx, dy, TT + dz), M["leaf_light"],
           parent=ctab, segs=10, rings=6)
# (the three small pendants were removed; lit by the room lights)

# --- 2. Banquette along a short left side wall, 2 walnut tables + chairs, WallArt above
c_bq = make_coll("Banquette")
BQ_X, BQ_Y = -SIDE_IN + 0.39, 1.8  # banquette back flat against the left wall
bq = empty("Banquette", c_bq, (BQ_X, BQ_Y, 0))
BQ_LEN, BQ_SEG = 3.6, 6
box("Banquette_Plinth", c_bq, (0.56, BQ_LEN, 0.08), (-0.12, 0, 0.04), M["dark_wood"], bevel=0.008,
    parent=bq)
box("Banquette_Base", c_bq, (0.52, BQ_LEN, 0.26), (-0.12, 0, 0.21), M["dark_wood"], bevel=0.012,
    parent=bq)
box("Banquette_BackPanel", c_bq, (0.06, BQ_LEN, 0.62), (-0.36, 0, 0.66), M["dark_wood"],
    bevel=0.01, parent=bq)
for k in range(BQ_SEG):
    yc = -BQ_LEN / 2 + (k + 0.5) * BQ_LEN / BQ_SEG
    box(f"Banquette_Seat{k}", c_bq, (0.5, BQ_LEN / BQ_SEG - 0.02, 0.1), (-0.12, yc, 0.39),
        M["cognac"], bevel=0.04, segs=3, parent=bq)
    box(f"Banquette_BackCushion{k}", c_bq, (0.12, BQ_LEN / BQ_SEG - 0.03, 0.44), (-0.27, yc, 0.7),
        M["cognac"], bevel=0.045, segs=3, parent=bq, rot=(0, -8, 0))
for ti in range(5):  # row of small round dark-wood bistro tables, one chair each
    ty = -1.5 + ti * 0.75
    t = empty(f"Banquette_Table{ti}", c_bq, (0.52, ty, 0), parent=bq)
    cyl(f"Banquette_Table{ti}_Top", c_bq, 0.3, 0.03, (0, 0, 0.735), M["dark_wood"], segs=28,
        parent=t)
    cyl(f"Banquette_Table{ti}_Stem", c_bq, 0.028, 0.7, (0, 0, 0.36), M["graphite"], segs=10,
        parent=t)
    cyl(f"Banquette_Table{ti}_Foot", c_bq, 0.2, 0.02, (0, 0, 0.01), M["graphite"], segs=20,
        parent=t)
    if ti % 2 == 0:
        cyl(f"Banquette_Table{ti}_Cup", c_bq, 0.034, 0.08, (0.05, 0.06, 0.79), M["cup"], segs=14,
            parent=t, r2=0.038)
    wood_chair(f"Banquette_Chair{ti}", c_bq, (1.12, ty, 0), -90, bq, M["dark_wood"], M["dark_wood"])
c_wa = make_coll("WallArt")
LW_S = -SIDE_IN + 0.03  # front of the left-wall slat cladding
wa = empty("WallArt", c_wa, (LW_S, BQ_Y, 0))
POSTERS = ((-0.85, M["teal"], "THE QUIET PAGE", "EST. 2026", "cup"),
           (0.0, M["mustard"], "COFFEE & BOOKS", "READ · SIP · STAY", "book"),
           (0.85, M["teal"], "SLOW MORNINGS", "THE QUIET PAGE", "beans"))
for i, (py, bg_m, line1, line2, motif) in enumerate(POSTERS):
    w, h, z = 0.55, 0.72, 1.6
    box(f"WallArt_Frame{i}", c_wa, (0.025, w, h), (0.0125, py, z), M["black_metal"], bevel=0.003,
        parent=wa)
    box(f"WallArt_Print{i}", c_wa, (0.004, w - 0.04, h - 0.04), (0.027, py, z), bg_m, bevel=0.0,
        parent=wa)
    if motif == "cup":
        box(f"WallArt_Cup{i}", c_wa, (0.004, 0.16, 0.15), (0.031, py, z + 0.08), M["cream"],
            bevel=0.0, parent=wa)
        torus(f"WallArt_CupHandle{i}", c_wa, 0.04, 0.012, (0.031, py - 0.1, z + 0.09), M["cream"],
              parent=wa, rot=(0, 90, 0))
        box(f"WallArt_Saucer{i}", c_wa, (0.004, 0.26, 0.02), (0.031, py, z - 0.005), M["cream"],
            bevel=0.0, parent=wa)
    elif motif == "book":
        for sx in (-1, 1):
            box(f"WallArt_Page{i}{sx}", c_wa, (0.004, 0.13, 0.17), (0.031, py + sx * 0.07, z + 0.07),
                M["cream"], bevel=0.0, parent=wa, rot=(sx * 8, 0, 0))
        box(f"WallArt_Steam{i}", c_wa, (0.004, 0.012, 0.09), (0.031, py, z + 0.22), M["rust"],
            bevel=0.0, parent=wa)
    else:
        for k, (dy, dz) in enumerate(((-0.06, 0.1), (0.04, 0.12), (0.0, 0.03), (0.08, 0.04), (-0.08, 0.0))):
            sphere(f"WallArt_Bean{i}_{k}", c_wa, 0.035, (0.031, py + dy, z + dz), M["coffee"],
                   parent=wa, scale=(0.15, 1.0, 0.7), segs=10, rings=6)
    text_mesh(f"WallArt_Text{i}a", c_wa, line1, 0.045, M["cream"], (0.031, py, z - 0.17),
              rot=(90, 0, 90), parent=wa, max_w=w - 0.1)
    text_mesh(f"WallArt_Text{i}b", c_wa, line2, 0.028, M["cream"], (0.031, py, z - 0.24),
              rot=(90, 0, 90), parent=wa, max_w=w - 0.14)

# --- 3. LoungeCluster: two leather club chairs facing each other, coffee table, lamp, plant
c_lc = make_coll("LoungeCluster")
LC_X, LC_Y = 6.0, 2.6
lc = empty("LoungeCluster", c_lc, (LC_X, LC_Y, 0))


def lounge_armchair(tag, loc, rot_z):
    """Cognac leather armchair with an exposed walnut frame and slim arms (front = local -Y)."""
    root = empty(f"LoungeCluster_Chair{tag}", c_lc, loc, rot_z=rot_z, parent=lc)
    for sx in (-1, 1):
        box(f"Lounge{tag}_ArmRail{sx}", c_lc, (0.05, 0.66, 0.035), (sx * 0.33, -0.02, 0.6),
            M["walnut"], bevel=0.012, parent=root)
        box(f"Lounge{tag}_SideRail{sx}", c_lc, (0.04, 0.62, 0.05), (sx * 0.33, 0.0, 0.17),
            M["walnut"], bevel=0.01, parent=root)
        for sy in (-1, 1):
            cyl(f"Lounge{tag}_Post{sx}{sy}", c_lc, 0.02, 0.6, (sx * 0.33, sy * 0.28, 0.3),
                M["walnut"], segs=10, parent=root, r2=0.016)
    box(f"Lounge{tag}_FrontRail", c_lc, (0.62, 0.04, 0.05), (0, -0.28, 0.2), M["walnut"],
        bevel=0.01, parent=root)
    box(f"Lounge{tag}_BackRail", c_lc, (0.62, 0.04, 0.05), (0, 0.3, 0.2), M["walnut"], bevel=0.01,
        parent=root)
    box(f"Lounge{tag}_Seat", c_lc, (0.6, 0.58, 0.14), (0, -0.02, 0.32), M["cognac"], bevel=0.05,
        segs=3, parent=root)
    box(f"Lounge{tag}_Back", c_lc, (0.6, 0.14, 0.48), (0, 0.27, 0.66), M["cognac"], bevel=0.05,
        segs=3, parent=root, rot=(-10, 0, 0))
    box(f"Lounge{tag}_BackFrame", c_lc, (0.62, 0.04, 0.05), (0, 0.33, 0.9), M["walnut"],
        bevel=0.012, parent=root)


lounge_armchair("A", (-0.95, 0.05, 0), 82)   # faces +X, angled slightly to the room
lounge_armchair("B", (0.95, 0.05, 0), -82)   # faces -X; ~1.2 m between chair fronts
cyl("LoungeCluster_Ottoman", c_lc, 0.32, 0.36, (0, 0.0, 0.18), M["ottoman"], segs=32, parent=lc)
cyl("LoungeCluster_OttomanTop", c_lc, 0.305, 0.04, (0, 0.0, 0.38), M["ottoman"], segs=32,
    parent=lc, r2=0.28)
for k, (dx, dy, r, h) in enumerate(((-0.95, 0.72, 0.2, 0.55), (0.95, -0.72, 0.16, 0.42))):
    cyl(f"LoungeCluster_Drum{k}", c_lc, r, h, (dx, dy, h / 2), M["black_metal"], segs=24,
        parent=lc)
box("LoungeCluster_Book", c_lc, (0.18, 0.13, 0.03), (0.92, -0.72, 0.435), M["navy"], bevel=0.004,
    parent=lc, rot=(0, 0, 20))
# slim black task lamp on the taller drum table
cyl("LoungeCluster_TaskBase", c_lc, 0.06, 0.015, (-0.95, 0.72, 0.5575), M["black_metal"], segs=16,
    parent=lc)
cyl("LoungeCluster_TaskStem", c_lc, 0.007, 0.36, (-0.95, 0.72, 0.745), M["black_metal"], segs=6,
    parent=lc)
_bm = bmesh.new()
bmesh.ops.create_cone(_bm, cap_ends=False, segments=16, radius1=0.06, radius2=0.025, depth=0.1)
finish_mesh(_bm, "LoungeCluster_TaskHead", c_lc, M["black_metal"], (-0.92, 0.72, 0.92), lc, 60,
            (0, 25, 0))
sphere("LoungeCluster_TaskBulb", c_lc, 0.018, (-0.9, 0.72, 0.89), M["bulb"], parent=lc, segs=8,
       rings=6)
# tall wooden tripod floor lamp with a linen drum shade
TRI = (0.0, 0.95)
for k in range(3):
    a = math.radians(90 + k * 120)
    fx, fy = TRI[0] + 0.32 * math.cos(a), TRI[1] + 0.32 * math.sin(a)
    capsule_between(f"LoungeCluster_TripodLeg{k}", c_lc, 0.014, (fx, fy, 0.02),
                    (TRI[0], TRI[1], 1.32), M["walnut"], parent=lc)
_bm = bmesh.new()
bmesh.ops.create_cone(_bm, cap_ends=False, segments=28, radius1=0.26, radius2=0.26, depth=0.3)
finish_mesh(_bm, "LoungeCluster_DrumShade", c_lc, M["linen"], (TRI[0], TRI[1], 1.45), lc, 60)
sphere("LoungeCluster_TripodBulb", c_lc, 0.04, (TRI[0], TRI[1], 1.4), M["bulb"], parent=lc,
       segs=10, rings=6)
# large warm rug under the lounge seating
cyl("LoungeCluster_Rug", c_lc, 1.4, 0.008, (0, 0.1, 0.004), M["rust"], segs=48, parent=lc)
cyl("LoungeCluster_RugInner", c_lc, 1.28, 0.009, (0, 0.1, 0.0045), M["rug_in"], segs=48, parent=lc)
plant("Lounge", (1.55, 0.95, 0), 0.9, pot="pot_char", parent=lc, coll=c_lc, s=0.9)
EXTRA_LIGHTS.append(("LoungeTask_Light", (LC_X - 0.9, LC_Y + 0.72, 0.85), 5))
EXTRA_LIGHTS.append(("LoungeLamp_Light", (LC_X + TRI[0], LC_Y + TRI[1], 1.38), 16))

# --- BookOfTheDay: free-standing digital totem at the nook's front-left edge, facing camera
c_bd = make_coll("BookOfTheDay")
bd = empty("BookOfTheDay", c_bd, (4.75, -2.95, 0), rot_z=40)  # at the nook opening  # outside the divider, at the nook edge, facing camera
box("BookOfTheDay_Base", c_bd, (0.36, 0.26, 0.045), (0, 0, 0.0225), M["walnut"], bevel=0.012,
    parent=bd)
cyl("BookOfTheDay_Pole", c_bd, 0.018, 0.52, (0, 0.02, 0.3), M["brass_m"], segs=10, parent=bd)
box("BookOfTheDay_Frame", c_bd, (0.46, 0.045, 0.76), (0, 0.02, 0.92), M["walnut"],
    bevel=0.012, parent=bd)
box("BookOfTheDay_Trim", c_bd, (0.47, 0.05, 0.014), (0, 0.02, 1.305), M["brass_m"],
    bevel=0.004, parent=bd)
M["botd"] = mat("M_BookOfTheDay", "#1d2127", 0.35, emit="#28313d", emit_strength=1.0)
face_plane("BookOfTheDay_Face", c_bd, 0.4, 0.7, (0, -0.0035, 0.92), M["botd"], bd)


# --- MerchShelf: built-in walnut wall unit set into the chevron section of the back wall's left end
c_ms = make_coll("MerchShelf")
MW, MD, MH = 1.8, 0.32, 2.1
ms = empty("MerchShelf", c_ms, (-5.75, WALL_FRONT - MD / 2 - 0.012, 0))  # front faces the room (-Y)
M["brand_green"] = mat("M_BrandGreen", "#2f5d50", 0.4)
M["tin_gold"] = mat("M_TinGold", "#c9a35f", 0.3, metal=0.6)
M["merch_back"] = mat("M_MerchBacklight", "#f1e2c8", 0.6, emit="#ffd9a8", emit_strength=0.45)
FR = 0.07  # walnut surround
for sx in (-1, 1):
    box(f"Merch_Side{sx}", c_ms, (FR, MD + 0.02, MH + FR), (sx * (MW / 2 + FR / 2), 0, (MH + FR) / 2),
        M["walnut"], bevel=0.008, parent=ms)
box("Merch_Top", c_ms, (MW + 2 * FR, MD + 0.02, FR), (0, 0, MH + FR / 2), M["walnut"], bevel=0.008, parent=ms)
box("Merch_Plinth", c_ms, (MW, MD, 0.1), (0, 0, 0.05), M["walnut"], bevel=0.006, parent=ms)
box("Merch_Back", c_ms, (MW, 0.015, MH - 0.1), (0, MD / 2 - 0.008, MH / 2 + 0.05), M["merch_back"],
    bevel=0.0, parent=ms)  # warm back-lit panel
SH = (0.1, 0.52, 0.94, 1.36, 1.74)
for i, z in enumerate(SH[1:]):
    box(f"Merch_Shelf{i}", c_ms, (MW, MD - 0.02, 0.03), (0, 0.01, z + 0.015), M["oak"], bevel=0.005, parent=ms)
for i, z in enumerate(SH[1:] + (MH,)):
    box(f"Merch_LED{i}", c_ms, (MW - 0.1, 0.012, 0.006), (0, -MD / 2 + 0.035, z - 0.004), M["led_2700_soft"],
        bevel=0.0, parent=ms)  # thin warm LED under each shelf
decals = empty("MerchShelf_Decals", c_ms, (0, 0, 0), parent=ms)
FRONT = -MD / 2 + 0.06


def tag(name, x, z):
    box(name, c_ms, (0.05, 0.004, 0.025), (x, -MD / 2 + 0.018, z + 0.012), M["cream"], bevel=0.0, parent=ms)


# level 3: branded tumblers (winter bands) with a small logo decal
z0 = SH[3] + 0.03
for k in range(8):
    col = ("brand_green", "cream", "rust")[k % 3]
    x = -0.77 + k * 0.22
    cyl(f"Merch_Tumbler{k}", c_ms, 0.036, 0.2, (x, FRONT + 0.03, z0 + 0.1), M[col], segs=18, parent=ms, r2=0.034)
    cyl(f"Merch_TumblerBand{k}", c_ms, 0.0355, 0.03, (x, FRONT + 0.03, z0 + 0.165),
        M["holiday_red"] if col == "cream" else M["cream"], segs=18, parent=ms, r2=0.0345)
    cyl(f"Merch_TumblerLid{k}", c_ms, 0.035, 0.025, (x, FRONT + 0.03, z0 + 0.212),
        M["graphite"] if col != "brand_green" else M["cream"], segs=18, parent=ms)
    logo_disc(f"Merch_TumblerLogo{k}", c_ms, 0.022, 0.002, (x, FRONT + 0.03 - 0.0365, z0 + 0.1), parent=decals)
tag("Merch_Price3", 0.0, z0)
# level 2: ceramic mugs + tea tins
z1 = SH[2] + 0.03
for k, col in enumerate(("cream", "brand_green", "cream", "rust", "brand_green")):
    x = -0.75 + k * 0.14
    cyl(f"Merch_Mug{k}", c_ms, 0.04, 0.09, (x, FRONT + 0.02, z1 + 0.045), M[col], segs=16, parent=ms)
    torus(f"Merch_MugHandle{k}", c_ms, 0.022, 0.006, (x + 0.048, FRONT + 0.02, z1 + 0.048), M[col], parent=ms,
          rot=(90, 0, 0))
for k, col in enumerate(("brand_green", "tin_gold", "rust", "navy")):
    x = 0.15 + k * 0.17
    cyl(f"Merch_Tin{k}", c_ms, 0.035, 0.11, (x, FRONT + 0.03, z1 + 0.055), M[col], segs=16, parent=ms)
    cyl(f"Merch_TinLid{k}", c_ms, 0.037, 0.015, (x, FRONT + 0.03, z1 + 0.115), M["tin_gold"], segs=16, parent=ms)
tag("Merch_Price2", -0.45, z1)
tag("Merch_Price2b", 0.4, z1)
# level 1: kraft coffee-bean pouches with labels
z2 = SH[1] + 0.03
for k in range(6):
    x = -0.72 + k * 0.288
    box(f"Merch_Pouch{k}", c_ms, (0.13, 0.065, 0.22), (x, FRONT + 0.04, z2 + 0.11), M["kraft"], bevel=0.015,
        segs=2, parent=ms)
    box(f"Merch_PouchFold{k}", c_ms, (0.13, 0.03, 0.025), (x, FRONT + 0.04, z2 + 0.232), M["kraft"], bevel=0.006,
        parent=ms)
    box(f"Merch_PouchLabel{k}", c_ms, (0.08, 0.004, 0.07), (x, FRONT + 0.0065, z2 + 0.12),
        M["cream"] if k % 2 == 0 else M["brand_green"], bevel=0.0, parent=ms)
tag("Merch_Price1", 0.0, z2)
# level 0 (on the plinth): folded tote stack, thermoses, wrapped gift stack
z3 = SH[0]
for k, col in enumerate(("cream", "brand_green", "cream", "rust")):
    box(f"Merch_Tote{k}", c_ms, (0.36, 0.24, 0.035), (-0.55, 0.0, z3 + 0.018 + k * 0.036), M[col], bevel=0.01,
        segs=2, parent=ms, rot=(0, 0, (k - 1.5) * 2.5))
for k, col in enumerate(("brand_green", "rust")):
    x = 0.02 + k * 0.17
    cyl(f"Merch_Thermos{k}", c_ms, 0.045, 0.26, (x, FRONT + 0.03, z3 + 0.13), M[col], segs=18, parent=ms)
    cyl(f"Merch_ThermosCap{k}", c_ms, 0.042, 0.045, (x, FRONT + 0.03, z3 + 0.282), M["steel"], segs=18, parent=ms)
    logo_disc(f"Merch_ThermosLogo{k}", c_ms, 0.026, 0.002, (x, FRONT + 0.03 - 0.0455, z3 + 0.15), parent=decals)
tag("Merch_Price0", 0.1, z3)
for k, (w, d, h, dx, rib) in enumerate(((0.26, 0.2, 0.14, 0.6, "brand_green"),
                                        (0.18, 0.15, 0.11, 0.62, "holiday_red"),
                                        (0.16, 0.14, 0.12, 0.38, "holiday_red"))):
    zb = z3 + (0.14 if k == 1 else 0.0)
    rz = (8, -12, 18)[k]
    box(f"Merch_Gift{k}", c_ms, (w, d, h), (dx, 0.0, zb + h / 2), M["kraft"], bevel=0.006, parent=ms,
        rot=(0, 0, rz))
    box(f"Merch_GiftRibbonA{k}", c_ms, (w + 0.004, 0.02, h + 0.004), (dx, 0.0, zb + h / 2), M[rib], bevel=0.0,
        parent=ms, rot=(0, 0, rz))
    box(f"Merch_GiftRibbonB{k}", c_ms, (0.02, d + 0.004, h + 0.004), (dx, 0.0, zb + h / 2), M[rib], bevel=0.0,
        parent=ms, rot=(0, 0, rz))
    for sx in (-1, 1):
        sphere(f"Merch_GiftBow{k}{sx}", c_ms, 0.022, (dx + sx * 0.018, 0.0, zb + h + 0.012), M[rib], parent=ms,
               scale=(1.2, 0.6, 0.7), segs=10, rings=6)
# level 4: coffee bags, glass jars, a small plant
z4 = SH[4] + 0.03
for k in range(3):
    x = -0.72 + k * 0.2
    box(f"Merch_Bag{k}", c_ms, (0.14, 0.08, 0.22), (x, FRONT + 0.04, z4 + 0.11), M["kraft"], bevel=0.014,
        parent=ms)
    box(f"Merch_BagLabel{k}", c_ms, (0.09, 0.004, 0.07), (x, FRONT - 0.0005, z4 + 0.12),
        M["brand_green"] if k != 1 else M["cream"], bevel=0.0, parent=ms)
for k in range(2):
    x = 0.05 + k * 0.16
    cyl(f"Merch_Jar{k}", c_ms, 0.055, 0.17, (x, FRONT + 0.03, z4 + 0.085), M["glass"], segs=16, parent=ms)
    cyl(f"Merch_JarBeans{k}", c_ms, 0.05, 0.11, (x, FRONT + 0.03, z4 + 0.06), M["coffee"], segs=16, parent=ms)
    cyl(f"Merch_JarLid{k}", c_ms, 0.057, 0.02, (x, FRONT + 0.03, z4 + 0.18), M["walnut"], segs=16, parent=ms)
cyl("Merch_PlantPot", c_ms, 0.06, 0.1, (0.62, 0.0, z4 + 0.05), M["pot_cream"], segs=16, parent=ms, r2=0.07)
for k, (dx, dz) in enumerate(((0.0, 0.17), (0.04, 0.2), (-0.035, 0.19))):
    sphere(f"Merch_PlantLeaf{k}", c_ms, 0.05, (0.62 + dx, 0.0, z4 + dz), M["leaf"] if k % 2 == 0 else M["leaf_light"],
           parent=ms, segs=10, rings=6)
EXTRA_LIGHTS.append(("MerchShelf_Light", (-5.75, WALL_FRONT - 0.45, 1.6), 8))

# ================================================================ 14. Holiday season
# --- HolidayTree: stylized layered fir, baubles, spiral fairy lights, star
c_ht = make_coll("HolidayTree")
TREE_X, TREE_Y = 7.38, -4.2  # inner corner by the RightWall
ht = empty("HolidayTree", c_ht, (TREE_X, TREE_Y, 0))
box("HolidayTree_Crate", c_ht, (0.36, 0.36, 0.26), (0, 0, 0.13), M["walnut"], bevel=0.012,
    parent=ht)
cyl("HolidayTree_Trunk", c_ht, 0.04, 0.12, (0, 0, 0.32), M["wood_dark"], segs=10, parent=ht)
LAYERS = ((0.38, 0.36, 0.36), (0.38, 0.62, 0.34), (0.3, 0.86, 0.32), (0.21, 1.08, 0.3),
          (0.13, 1.28, 0.26))  # (radius, base z, height)
for i, (r, zb, h) in enumerate(LAYERS):
    cyl(f"HolidayTree_Layer{i}", c_ht, r, h, (0, 0, zb + h / 2), M["fir"] if i % 2 == 0 else
        M["fir_light"], segs=20, parent=ht, r2=0.02)


def cone_point(t, ang, inset=0.0):
    """Point on the tree silhouette at height fraction t (0 bottom, 1 top)."""
    z = 0.4 + t * 1.08
    r = max(0.03, 0.44 * (1 - t) ** 0.95) - inset
    return (r * math.cos(ang), r * math.sin(ang), z)


rng = random.Random(11)
for k in range(16):
    t = 0.08 + 0.8 * (k / 16)
    ang = k * 2.4 + rng.uniform(-0.2, 0.2)
    x, y, z = cone_point(t, ang, 0.02)
    sphere(f"HolidayTree_Bauble{k}", c_ht, 0.03 if t < 0.6 else 0.024, (x, y, z - 0.03),
           (M["gold"], M["holiday_red"], M["cream"])[k % 3], parent=ht, segs=10, rings=6)
for k in range(46):  # spiral string of tiny warm bulbs
    t = 0.04 + 0.9 * k / 46
    x, y, z = cone_point(t, k * 0.62, -0.012)
    sphere(f"HolidayTree_Light{k}", c_ht, 0.011, (x, y, z), M["fairy"], parent=ht, segs=6,
           rings=4)
_bm = bmesh.new()  # 5-point star, extruded
pts = []
for k in range(10):
    a = math.pi / 2 + k * math.pi / 5
    rr = 0.085 if k % 2 == 0 else 0.036
    pts.append((rr * math.cos(a), 0, rr * math.sin(a)))
front = [_bm.verts.new((x, -0.012, z)) for x, _, z in pts]
back = [_bm.verts.new((x, 0.012, z)) for x, _, z in pts]
_bm.faces.new(front[::-1]); _bm.faces.new(back)
for k in range(10):
    j = (k + 1) % 10
    _bm.faces.new((front[k], front[j], back[j], back[k]))
star = finish_mesh(_bm, "HolidayTree_Star", c_ht, M["gold"], (0, 0, 1.6), ht, 20, (0, 0, 40))
EXTRA_LIGHTS.append(("HolidayTree_Light", (TREE_X - 0.25, TREE_Y - 0.25, 0.9), 8))


# --- StringLights: draped fairy lights (cord + tiny bulbs) on the back wall and shelf tops
c_sl = make_coll("StringLights")
sl = empty("StringLights", c_sl)


def drape(tag, a, b, sag, n_swags, spacing=0.12):
    a, b = Vector(a), Vector(b)
    total = (b - a).length
    n = max(2, int(total / spacing))
    pts = []
    for i in range(n + 1):
        u = i / n
        p_ = a.lerp(b, u)
        su = (u * n_swags) % 1.0
        p_.z -= sag * 4 * su * (1 - su)
        pts.append(p_)
    for i in range(n):
        p0, p1 = pts[i], pts[i + 1]
        d = p1 - p0
        cobj = cyl(f"StringLights_{tag}_Cord{i}", c_sl, 0.002, d.length, tuple((p0 + p1) / 2),
                   M["graphite"], segs=4, parent=sl)
        cobj.rotation_mode = "QUATERNION"
        cobj.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d.normalized())
        sphere(f"StringLights_{tag}_Bulb{i}", c_sl, 0.012, tuple(p0 - Vector((0, 0, 0.014))),
               M["fairy"], parent=sl, segs=6, rings=4)


drape("Wall", (-4.45, WALL_FRONT - 0.27, 2.69), (4.45, WALL_FRONT - 0.27, 2.69), 0.05, 10)
drape("Shelves", (SIDE_IN - 0.36, -3.85, 1.84), (SIDE_IN - 0.36, -2.03, 1.84), 0.08, 3, 0.1)

# --- Wreath on the back wall at the entrance end (left)
c_wr = make_coll("Wreath")
wr = empty("Wreath", c_wr, (-2.9, WALL_FRONT - 0.095, 1.5))
torus("Wreath_Ring", c_wr, 0.19, 0.055, (0, 0, 0), M["fir"], parent=wr, rot=(90, 0, 0))
for k in range(14):
    a = k * 2 * math.pi / 14
    sphere(f"Wreath_Tuft{k}", c_wr, 0.05, (0.19 * math.cos(a), -0.01, 0.19 * math.sin(a)),
           M["fir_light"] if k % 2 else M["fir"], parent=wr, scale=(1, 0.6, 1), segs=8, rings=6)
for k in range(7):
    a = 0.3 + k * 0.9
    sphere(f"Wreath_Berry{k}", c_wr, 0.016, (0.2 * math.cos(a), -0.05, 0.2 * math.sin(a)),
           M["holiday_red"], parent=wr, segs=8, rings=6)
for sx in (-1, 1):
    box(f"Wreath_BowLoop{sx}", c_wr, (0.09, 0.025, 0.06), (sx * 0.05, -0.06, -0.19),
        M["holiday_red"], bevel=0.012, parent=wr, rot=(0, sx * 18, 0))
    box(f"Wreath_BowTail{sx}", c_wr, (0.025, 0.012, 0.1), (sx * 0.025, -0.058, -0.26),
        M["holiday_red"], bevel=0.004, parent=wr, rot=(0, sx * 12, 0))
sphere("Wreath_BowKnot", c_wr, 0.022, (0, -0.065, -0.19), M["holiday_red"], parent=wr, segs=8,
       rings=6)


# ================================================================ 15. Wall details (oak / walnut / brass)
c_wd = make_coll("WallDetails")
wd = empty("WallDetails", c_wd)
M["led_warm"] = mat("M_LEDWarm", "#ffd9a0", 0.3, emit="#ffc27a", emit_strength=1.75)
BW_X0, BW_X1, BW_H = -4.5, 4.5, 2.7
SL_W, SL_D, SL_P = 0.04, 0.025, 0.075
SL_Y = WALL_FRONT - SL_D / 2


def slat_run(tag, x0, x1, z0, z1, mat_a, mat_b):
    n = int((x1 - x0) / SL_P)
    for k in range(n):
        x = x0 + SL_P / 2 + k * SL_P
        box(f"Slat_{tag}{k}", c_wd, (SL_W, SL_D, z1 - z0), (x, SL_Y, (z0 + z1) / 2),
            mat_a if k % 5 else mat_b, bevel=0.0, parent=wd)


# crown trims
# walnut caps on the cut top edge of all three walls (read cleanly from above)
CAP_W, CAP_H = WALL_T + 0.04, 0.04
box("Crown_Back", c_wd, (2 * (SIDE_IN + WALL_T) + 0.04, CAP_W, CAP_H),
    (0, WALL_FRONT + WALL_T / 2, ROOM_H + CAP_H / 2), M["walnut"], bevel=0.008, parent=wd)
for tag, sx in (("Left", -1), ("Right", 1)):
    box(f"Crown_{tag}", c_wd, (CAP_W, ROOM_Y1 - ROOM_Y0 + 0.02, CAP_H),
        (sx * SIDE_C, (ROOM_Y0 + ROOM_Y1) / 2, ROOM_H + CAP_H / 2), M["walnut"], bevel=0.008,
        parent=wd)
    box(f"WallEnd_{tag}", c_wd, (CAP_W, 0.02, ROOM_H), (sx * SIDE_C, ROOM_Y0 - 0.01, ROOM_H / 2),
        M["walnut"], bevel=0.004, parent=wd)  # walnut edge on the open front cut
LW_X = -SIDE_IN            # left wall inner face
LW_Y0, LW_Y1 = ROOM_Y0, WALL_FRONT
RW_X = SIDE_IN             # right wall inner face
RW_Y0, RW_Y1 = ROOM_Y0, WALL_FRONT
# walnut wainscot (~1.1 m) with a thin oak top rail and vertical stiles, both side walls
for tag, xf, y0, y1, sgn in (("Left", LW_X, -3.35, -0.2, 1), ("LeftB", LW_X, 3.8, LW_Y1, 1),
                             ("Right", RW_X, RW_Y0, 1.2, -1)):
    L = y1 - y0
    yc = (y0 + y1) / 2
    box(f"Wainscot_{tag}", c_wd, (0.02, L, 1.1), (xf + sgn * 0.01, yc, 0.55), M["oak"],
        bevel=0.0, parent=wd)
    box(f"Wainscot_{tag}Rail", c_wd, (0.045, L + 0.02, 0.04), (xf + sgn * 0.022, yc, 1.12),
        M["oak"], bevel=0.008, parent=wd)
    box(f"Wainscot_{tag}Skirt", c_wd, (0.035, L, 0.1), (xf + sgn * 0.017, yc, 0.05), M["oak_edge"],
        bevel=0.004, parent=wd)
    n = int(L / 0.6)
    for k in range(n + 1):
        box(f"Wainscot_{tag}Stile{k}", c_wd, (0.03, 0.035, 0.95), (xf + sgn * 0.033,
            y0 + k * (L / n), 0.6), M["oak_edge"], bevel=0.004, parent=wd)

# brass picture lights over the two prints + the map
for k, py in enumerate((BQ_Y - 0.85, BQ_Y, BQ_Y + 0.85)):
    w = 0.42
    box(f"PictureLight_Mount{k}", c_wd, (0.03, 0.05, 0.05), (LW_S + 0.015, py, 2.08), M["brass_m"],
        bevel=0.006, parent=wd)
    cyl(f"PictureLight_Arm{k}", c_wd, 0.007, 0.12, (LW_S + 0.07, py, 2.08), M["brass_m"], segs=8,
        parent=wd, rot=(0, 90, 0))
    cyl(f"PictureLight_Bar{k}", c_wd, 0.022, w, (LW_S + 0.13, py, 2.07), M["brass_m"], segs=12,
        parent=wd, rot=(90, 0, 0))
    box(f"PictureLight_Glow{k}", c_wd, (0.012, w - 0.03, 0.006), (LW_S + 0.13, py, 2.047),
        M["led_warm"], bevel=0.0, parent=wd)
# brass wall sconces flanking the banquette
for k, py in enumerate((BQ_Y - 1.65, BQ_Y + 1.65)):
    cyl(f"Sconce_Plate{k}", c_wd, 0.05, 0.015, (LW_S + 0.008, py, 1.7), M["brass_m"], segs=16,
        parent=wd, rot=(0, 90, 0))
    cyl(f"Sconce_Arm{k}", c_wd, 0.008, 0.14, (LW_S + 0.08, py, 1.7), M["brass_m"], segs=8,
        parent=wd, rot=(0, 90, 0))
    _bm = bmesh.new()
    bmesh.ops.create_cone(_bm, cap_ends=False, segments=18, radius1=0.07, radius2=0.045, depth=0.12)
    finish_mesh(_bm, f"Sconce_Shade{k}", c_wd, M["lampshade"], (LW_S + 0.15, py, 1.78), wd, 60)
    sphere(f"Sconce_Bulb{k}", c_wd, 0.022, (LW_S + 0.15, py, 1.76), M["bulb"], parent=wd, segs=10,
           rings=6)
    EXTRA_LIGHTS.append((f"Sconce_Light{k}", (LW_S + 0.2, py, 1.72), 6))
# floating walnut shelves on the RightWall by the reading corner (books + small plants)
for k, (sy, sz) in enumerate(((-1.1, 1.45), (-0.55, 1.85), (0.05, 1.45))):
    box(f"FloatShelf_{k}", c_wd, (0.22, 0.8, 0.035), (RW_X - 0.11, sy, sz), M["walnut"],
        bevel=0.006, parent=wd)
    for b in range(5):
        h = (0.2, 0.17, 0.22, 0.18, 0.19)[(b + k) % 5]
        box(f"FloatShelf_{k}_Book{b}", c_wd, (0.16, 0.035, h), (RW_X - 0.1, sy - 0.32 + b * 0.04,
            sz + 0.0175 + h / 2), BOOK_COLS[(b + k) % 4], bevel=0.003, segs=1, parent=wd)
    cyl(f"FloatShelf_{k}_Pot", c_wd, 0.045, 0.08, (RW_X - 0.11, sy + 0.22, sz + 0.0575),
        M["pot_cream"], segs=14, parent=wd, r2=0.055)
    for j, (dx, dy, dz) in enumerate(((0, 0, 0.13), (0.02, 0.03, 0.17), (-0.02, -0.025, 0.16))):
        sphere(f"FloatShelf_{k}_Leaf{j}", c_wd, 0.04, (RW_X - 0.11 + dx, sy + 0.22 + dy, sz + dz),
               M["leaf"] if j % 2 == 0 else M["leaf_light"], parent=wd, segs=10, rings=6)
    box(f"FloatShelf_{k}_Bookend", c_wd, (0.12, 0.015, 0.12), (RW_X - 0.11, sy - 0.12, sz + 0.0775),
        M["brass_m"], bevel=0.003, parent=wd)


# ================================================================ 16. Flagship restyle (materials + light language)
import numpy as _np
c_rs = make_coll("RestyleLights")

# --- back wall, counter zone: terracotta stack-bond tiles up to 1.9 m, warm LED along the top
_TW, _TH = 0.075, 0.25          # tile size (m)
_px_w, _px_h = 480, 400         # texture covers 8 x 2 tiles = 0.6 x 0.5 m
_img = _np.zeros((_px_h, _px_w, 3), dtype=_np.float32)
_rng = _np.random.default_rng(9)
_base = _np.array(hex_srgb("#c98a64"))
for ty in range(2):
    for tx in range(8):
        tone = 1.0 + _rng.uniform(-0.07, 0.07)
        _img[ty * 200:(ty + 1) * 200, tx * 60:(tx + 1) * 60] = _base * tone
_img[::200, :] = _np.array(hex_srgb("#e6dccd"))
_img[1::200, :] = _np.array(hex_srgb("#e6dccd"))
_img[:, ::60] = _np.array(hex_srgb("#e6dccd"))
_img[:, 1::60] = _np.array(hex_srgb("#e6dccd"))
M["terracotta"] = tex_material("M_TerracottaTile", np_image("QuietPage_TerracottaTile", _img), 0.55)
TILE_X, TILE_H = 4.5, 1.9
_tp = face_plane("BackWall_Tiles", c_bw, 2 * TILE_X, TILE_H, (0, WALL_FRONT - 0.003, TILE_H / 2),
                 M["terracotta"])
for lp in _tp.data.uv_layers[0].data:
    lp.uv = (lp.uv[0] * 2 * TILE_X / 0.6, lp.uv[1] * TILE_H / 0.5)
box("BackWall_TileLED", c_bw, (2 * TILE_X - 0.1, 0.02, 0.012), (0, WALL_FRONT - 0.03, TILE_H - 0.01),
    M["led_2700"], bevel=0.0)

# --- above the tiles: sage vertical-groove panelling (cubby backs) across the counter zone
grooved_panel("BackWall_SageGroove", c_bw, 2 * TILE_X, ROOM_H - TILE_H,
              (0, WALL_FRONT - 0.004, (TILE_H + ROOM_H) / 2), groove_material("M_SageGroove", "#7e9c86"))

# --- open walnut cubby shelves with menu screens set into the middle of the walnut frame
c_bb = make_coll("BackBar")
bb = empty("BackBar", c_bb)
CB_D, CB_T = 0.26, 0.025
CB_Y = WALL_FRONT - CB_D / 2
CB_Z = (TILE_H + 0.0125, 2.29, 2.67)
for side, x0, x1 in (("L", -3.72, -1.62), ("R", 1.62, 3.72)):
    for i, z in enumerate(CB_Z):
        box(f"Cubby{side}_Board{i}", c_bb, (x1 - x0, CB_D, CB_T), ((x0 + x1) / 2, CB_Y, z),
            M["walnut"], bevel=0.004, parent=bb)
    n = 5
    for k in range(n + 1):
        x = x0 + k * (x1 - x0) / n
        box(f"Cubby{side}_Div{k}", c_bb, (CB_T, CB_D, CB_Z[2] - CB_Z[0]), (x, CB_Y, (CB_Z[0] + CB_Z[2]) / 2),
            M["walnut"], bevel=0.004, parent=bb)
    for row in range(2):
        zb = CB_Z[row] + CB_T / 2
        for k in range(n):
            cx = x0 + (k + 0.5) * (x1 - x0) / n
            kind = (k + row * 2 + (side == "R")) % 4
            nm = f"Cubby{side}_{row}{k}"
            if kind == 0:   # kraft coffee bags
                for j in (-1, 1):
                    box(f"{nm}_Bag{j}", c_bb, (0.11, 0.07, 0.2), (cx + j * 0.065, CB_Y, zb + 0.1), M["kraft"],
                        bevel=0.012, parent=bb)
                    box(f"{nm}_Label{j}", c_bb, (0.07, 0.004, 0.06), (cx + j * 0.065, CB_Y - 0.037, zb + 0.11),
                        M["brand_green"] if j < 0 else M["cream"], bevel=0.0, parent=bb)
            elif kind == 1:  # glass jars with beans
                for j in (-1, 1):
                    cyl(f"{nm}_Jar{j}", c_bb, 0.055, 0.17, (cx + j * 0.07, CB_Y, zb + 0.085), M["glass"],
                        segs=16, parent=bb)
                    cyl(f"{nm}_Beans{j}", c_bb, 0.05, 0.11, (cx + j * 0.07, CB_Y, zb + 0.06), M["coffee"],
                        segs=16, parent=bb)
                    cyl(f"{nm}_Lid{j}", c_bb, 0.057, 0.02, (cx + j * 0.07, CB_Y, zb + 0.18), M["walnut"],
                        segs=16, parent=bb)
            elif kind == 2:  # dried-grass vase
                cyl(f"{nm}_Vase", c_bb, 0.05, 0.16, (cx, CB_Y, zb + 0.08), M["pot_cream"], segs=16,
                    parent=bb, r2=0.035)
                for j in range(5):
                    a = -30 + j * 15
                    box(f"{nm}_Grass{j}", c_bb, (0.008, 0.008, 0.2),
                        (cx + 0.1 * math.sin(math.radians(a)), CB_Y, zb + 0.24), M["kraft"], bevel=0.0,
                        parent=bb, rot=(0, a, 0))
            else:            # mugs
                for j in (-1, 1):
                    cyl(f"{nm}_Mug{j}", c_bb, 0.04, 0.09, (cx + j * 0.07, CB_Y, zb + 0.045),
                        M["cream"] if j < 0 else M["brand_green"], segs=14, parent=bb)
                    torus(f"{nm}_MugHandle{j}", c_bb, 0.022, 0.006, (cx + j * 0.07 + 0.048, CB_Y, zb + 0.05),
                          M["cream"] if j < 0 else M["brand_green"], parent=bb, rot=(90, 0, 0))
# walnut frame around the screen group (MenuScreen_L | MenuBoard | MenuScreen_R)
SF_X = 1.58
for i, z in enumerate((TILE_H + 0.0125, 2.69)):
    box(f"ScreenFrame_H{i}", c_bb, (2 * SF_X, 0.06, 0.03), (0, WALL_FRONT - 0.03, z), M["walnut"],
        bevel=0.004, parent=bb)
for i, x in enumerate((-SF_X, SF_X)):
    box(f"ScreenFrame_V{i}", c_bb, (0.04, 0.06, 2.69 - TILE_H), (x, WALL_FRONT - 0.03, (2.69 + TILE_H) / 2),
        M["walnut"], bevel=0.004, parent=bb)
c_mr = make_coll("MenuRow")
MENU_LINES = (("MenuScreen_L", -1.18, ("HOT DRINKS", "ESPRESSO  3.00", "FLAT WHITE  4.50", "CAFFE LATTE  4.50")),
              ("MenuScreen_R", 1.18, ("COLD & TEA", "COLD BREW  4.00", "CHAI LATTE  4.25", "MATCHA  4.75")))
for nm, x, lines in MENU_LINES:
    scr = box(nm, c_mr, (0.66, 0.03, 0.7), (x, WALL_FRONT - 0.03, 2.3), M["black_metal"], bevel=0.006)
    face_plane(f"{nm}_Face", c_mr, 0.62, 0.66, (0, -0.0155, 0), M["screen_green"], scr)
    for k, ln in enumerate(lines):
        text_mesh(f"{nm}_Line{k}", c_mr, ln, 0.05 if k == 0 else 0.038, M["screen_text"],
                  (0, -0.018, 0.2 - k * 0.11 - (0.03 if k else 0)), rot=(90, 0, 0), parent=scr, max_w=0.54)
    cyl(f"{nm}_Cup", c_mr, 0.05, 0.004, (0.0, -0.018, -0.25), M["screen_text"], segs=20, parent=scr,
        rot=(90, 0, 0))

# --- back wall left end (x -7.8 .. -4.5): diagonal slats in one big inverted-V (chevron)
def _clip(poly, x0, x1, z0, z1):
    def clip_edge(pts, inside, inter):
        out = []
        for i in range(len(pts)):
            a, b = pts[i - 1], pts[i]
            ia, ib = inside(a), inside(b)
            if ib:
                if not ia:
                    out.append(inter(a, b))
                out.append(b)
            elif ia:
                out.append(inter(a, b))
        return out

    def ix(a, b, xv):
        t = (xv - a[0]) / (b[0] - a[0])
        return (xv, a[1] + t * (b[1] - a[1]))

    def iz(a, b, zv):
        t = (zv - a[1]) / (b[1] - a[1])
        return (a[0] + t * (b[0] - a[0]), zv)
    pts = poly
    for inside, inter in ((lambda p: p[0] >= x0, lambda a, b: ix(a, b, x0)),
                          (lambda p: p[0] <= x1, lambda a, b: ix(a, b, x1)),
                          (lambda p: p[1] >= z0, lambda a, b: iz(a, b, z0)),
                          (lambda p: p[1] <= z1, lambda a, b: iz(a, b, z1))):
        if not pts:
            break
        pts = clip_edge(pts, inside, inter)
    return pts


c_cl = make_coll("WallCladding")
cl = empty("WallCladding", c_cl)
_bm = bmesh.new()
CV_X0, CV_X1, CV_H = -SIDE_IN, -4.5, ROOM_H
CV_XM = (CV_X0 + CV_X1) / 2
_slope = math.tan(math.radians(32))
_pitch = 0.11 / math.cos(math.radians(32))
_gap = 0.012 / math.cos(math.radians(32))
_yv = WALL_FRONT - 0.012
for half, (hx0, hx1, sgn) in enumerate(((CV_X0, CV_XM, 1), (CV_XM, CV_X1, -1))):
    xa = CV_X0 if sgn > 0 else CV_X1   # lines rise toward the centre: z = c + slope*|x - xa|
    k = 0
    c = -_slope * (CV_XM - CV_X0) - _pitch
    while c < CV_H:
        def zl(x, cc):
            return cc + _slope * abs(x - xa)
        quad = [(hx0, zl(hx0, c)), (hx1, zl(hx1, c)), (hx1, zl(hx1, c + _pitch - _gap)),
                (hx0, zl(hx0, c + _pitch - _gap))]
        pts = _clip(quad, hx0, hx1, 0.0, CV_H)
        if len(pts) >= 3:
            vs = [_bm.verts.new((x, _yv, z)) for x, z in pts]
            f = _bm.faces.new(vs)
            f.material_index = k % 2
        c += _pitch
        k += 1
bmesh.ops.recalc_face_normals(_bm, faces=_bm.faces)
for f in _bm.faces:
    if f.normal.y > 0:
        f.normal_flip()
_chev = finish_mesh(_bm, "WallCladding_Chevron", c_cl, M["oak"], (0, 0, 0), cl)
_chev.data.materials.append(M["walnut"])
box("WallCladding_ChevronBack", c_cl, (CV_X1 - CV_X0, 0.006, CV_H), (CV_XM, WALL_FRONT - 0.006, CV_H / 2),
    M["dark_wood"], bevel=0.0, parent=cl)   # shadow gaps read dark
# left wall behind the banquette: thick horizontal slats, light oak / dark walnut alternating
SL_Y0, SL_Y1 = -0.2, 3.8
box("WallCladding_SlatBack", c_cl, (0.006, SL_Y1 - SL_Y0, ROOM_H), (-SIDE_IN + 0.003, (SL_Y0 + SL_Y1) / 2, ROOM_H / 2),
    M["dark_wood"], bevel=0.0, parent=cl)
_z, _k = 0.0, 0
while _z < ROOM_H - 0.02:
    h = min(0.1, ROOM_H - _z - 0.012)
    box(f"WallCladding_Slat{_k}", c_cl, (0.03, SL_Y1 - SL_Y0, h), (-SIDE_IN + 0.015, (SL_Y0 + SL_Y1) / 2, _z + h / 2),
        M["light_oak"] if _k % 2 == 0 else M["walnut"], bevel=0.004, parent=cl)
    _z += h + 0.012
    _k += 1

# --- lounge corner walls: dark walnut vertical-groove panelling (back wall right end + right wall)
M["walnut_groove"] = groove_material("M_WalnutGroove", "#5a3d2a", 0.55)
grooved_panel("LoungeWall_Back", c_cl, SIDE_IN - TILE_X, ROOM_H,
              ((SIDE_IN + TILE_X) / 2, WALL_FRONT - 0.004, ROOM_H / 2), M["walnut_groove"])
grooved_panel("LoungeWall_Right", c_cl, WALL_FRONT - 1.2, ROOM_H,
              (SIDE_IN - 0.004, (WALL_FRONT + 1.2) / 2, ROOM_H / 2), M["walnut_groove"], rot_z=-90)

# --- lounge art: coffee-branch print, burlap-sack print, walnut floating shelf with trailing pothos
c_la = make_coll("LoungeArt")
la = empty("LoungeArt", c_la)
AX = SIDE_IN - 0.006
box("LoungeArt_BranchFrame", c_la, (0.025, 1.0, 0.72), (AX - 0.0125, LC_Y, 1.62), M["black_metal"],
    bevel=0.003, parent=la)
box("LoungeArt_BranchPrint", c_la, (0.004, 0.94, 0.66), (AX - 0.027, LC_Y, 1.62), mat("M_PrintOlive", "#3e4a36", 0.8),
    bevel=0.0, parent=la)
M["cherry_red"] = mat("M_CherryRed", "#b8322a", 0.5)
M["cherry_green"] = mat("M_CherryGreen", "#7fa04a", 0.5)
capsule_between("LoungeArt_Branch", c_la, 0.012, (AX - 0.03, LC_Y - 0.4, 1.4), (AX - 0.03, LC_Y + 0.42, 1.86),
                M["wood_dark"], parent=la)
for k in range(7):
    t = (k + 0.5) / 7
    by, bz = LC_Y - 0.4 + 0.82 * t, 1.4 + 0.46 * t
    for sgn in (-1, 1):
        sphere(f"LoungeArt_Leaf{k}{sgn}", c_la, 1.0, (AX - 0.032, by + 0.02 * sgn, bz + sgn * 0.08), M["leaf"],
               parent=la, scale=(0.004, 0.06, 0.025), segs=10, rings=6)
    for j in range(3):
        sphere(f"LoungeArt_Cherry{k}_{j}", c_la, 0.02, (AX - 0.034, by + (j - 1) * 0.025, bz - 0.035),
               M["cherry_red"] if (k + j) % 3 else M["cherry_green"], parent=la, scale=(0.4, 1, 1),
               segs=8, rings=6)
BX = 6.6
box("LoungeArt_SackFrame", c_la, (0.5, 0.025, 0.62), (BX, WALL_FRONT - 0.0125, 1.7), M["black_metal"],
    bevel=0.003, parent=la)
box("LoungeArt_SackPrint", c_la, (0.46, 0.004, 0.58), (BX, WALL_FRONT - 0.027, 1.7), M["cream"], bevel=0.0,
    parent=la)
M["burlap"] = mat("M_Burlap", "#b99a6b", 0.9)
for k, (dx, dz, w, h) in enumerate(((-0.11, 1.6, 0.18, 0.28), (0.1, 1.62, 0.17, 0.3), (0.0, 1.8, 0.16, 0.22))):
    box(f"LoungeArt_Sack{k}", c_la, (w, 0.006, h), (BX + dx, WALL_FRONT - 0.032, dz), M["burlap"], bevel=0.0,
        parent=la)
    box(f"LoungeArt_SackStencil{k}", c_la, (w * 0.6, 0.003, 0.02), (BX + dx, WALL_FRONT - 0.036, dz + 0.02),
        M["wood_dark"], bevel=0.0, parent=la)
FSX = 5.3
box("LoungeArt_FloatShelf", c_la, (0.72, 0.22, 0.04), (FSX, WALL_FRONT - 0.11, 1.45), M["walnut"], bevel=0.006,
    parent=la)
cyl("LoungeArt_PothosPot", c_la, 0.07, 0.12, (FSX - 0.18, WALL_FRONT - 0.11, 1.53), M["pot_cream"], segs=16,
    parent=la, r2=0.085)
for k in range(10):
    t = k / 9
    sphere(f"LoungeArt_Pothos{k}", c_la, 0.035, (FSX - 0.18 - 0.05 * math.sin(t * 3), WALL_FRONT - 0.2 - 0.02 * t,
           1.6 - 0.65 * t ** 1.3), M["leaf"] if k % 2 else M["leaf_light"], parent=la, scale=(1, 0.6, 1),
           segs=8, rings=6)
sphere("LoungeArt_Ornament", c_la, 0.05, (FSX + 0.2, WALL_FRONT - 0.11, 1.52), M["brass_m"], parent=la,
       segs=14, rings=8)

# --- shopfront: black-framed glass door + sidelight on the front 1.5 m of the left wall
c_sf = make_coll("Shopfront")
sf = empty("Shopfront", c_sf, (-SIDE_C, (ROOM_Y0 + SHOP_Y1) / 2, 0))
SF_L = SHOP_Y1 - ROOM_Y0
for i, (dy, w) in enumerate(((-SF_L / 2 + 0.03, 0.06), (SF_L / 2 - 0.03, 0.06), (-SF_L / 2 + 0.95, 0.05))):
    box(f"Shopfront_Post{i}", c_sf, (WALL_T, w, ROOM_H), (0, dy, ROOM_H / 2), M["black_metal"], bevel=0.004,
        parent=sf)
for i, (z, h) in enumerate(((0.05, 0.1), (2.2, 0.05), (ROOM_H - 0.03, 0.06))):
    box(f"Shopfront_Rail{i}", c_sf, (WALL_T, SF_L, h), (0, 0, z), M["black_metal"], bevel=0.004, parent=sf)
for i, (y0, y1, z0, z1) in enumerate(((-SF_L / 2 + 0.06, -SF_L / 2 + 0.925, 0.1, 2.175),
                                      (-SF_L / 2 + 0.975, SF_L / 2 - 0.06, 0.1, 2.175),
                                      (-SF_L / 2 + 0.06, SF_L / 2 - 0.06, 2.225, ROOM_H - 0.06))):
    box(f"Shopfront_Glass{i}", c_sf, (0.012, y1 - y0, z1 - z0), (0, (y0 + y1) / 2, (z0 + z1) / 2),
        M["daylight_glass"], bevel=0.0, parent=sf)
box("Shopfront_Handle", c_sf, (0.03, 0.025, 0.6), (WALL_T / 2 + 0.03, -SF_L / 2 + 0.85, 1.05), M["brass_band"],
    bevel=0.008, parent=sf)

# --- blade sign: double-sided round logo sign on a black bracket at the entrance, softly lit
c_bs = make_coll("BladeSign")
bs = empty("BladeSign", c_bs, (-SIDE_C, ROOM_Y0 + 0.2, 0))
M["logo_lit"] = tex_material("M_LogoLit", logo_img, 0.5, emit=0.55)
box("BladeSign_Arm", c_bs, (0.66, 0.03, 0.03), (-0.39, 0, 2.68), M["black_metal"], bevel=0.004, parent=bs)
box("BladeSign_Plate", c_bs, (0.04, 0.12, 0.16), (-0.07, 0, 2.62), M["black_metal"], bevel=0.004, parent=bs)
for i, dx in enumerate((-0.25, -0.53)):
    cyl(f"BladeSign_Drop{i}", c_bs, 0.006, 0.05, (dx, 0, 2.645), M["black_metal"], segs=6, parent=bs)
cyl("BladeSign_Rim", c_bs, 0.355, 0.05, (-0.39, 0, 2.27), M["black_metal"], segs=48, parent=bs, rot=(90, 0, 0))
logo_disc("BladeSign_Front", c_bs, 0.34, 0.006, (-0.39, -0.028, 2.27), parent=bs, rot=(90, 0, 0),
          m_face=M["logo_lit"])
logo_disc("BladeSign_Back", c_bs, 0.34, 0.006, (-0.39, 0.028, 2.27), parent=bs, rot=(-90, 0, 180),
          m_face=M["logo_lit"])

# --- canopy: slim floating light-oak soffit frame over the counter, recessed downlights underneath.
# Sits high and set back (front beam at y 3.0, underside 2.5 m) so from Cam_Overview it projects above the
# lower edge of the cubby row and never covers the baristas or the POS.
c_cn = make_coll("Canopy")
cn = empty("Canopy", c_cn)
M["downlight"] = mat("M_Downlight", "#fff1dd", 0.3, emit="#ffe2bd", emit_strength=3.0)
CN_X, CN_Y0, CN_Y1 = 3.4, 3.0, 4.38
CN_ZB = 2.5                       # underside
box("Canopy_Front", c_cn, (2 * CN_X + 0.3, 0.26, 0.08), (0, CN_Y0, CN_ZB + 0.04), M["light_oak"], bevel=0.008,
    parent=cn)
for sx in (-1, 1):
    box(f"Canopy_Side{sx}", c_cn, (0.26, CN_Y1 - CN_Y0, 0.18), (sx * CN_X, (CN_Y0 + CN_Y1) / 2, CN_ZB + 0.09),
        M["light_oak"], bevel=0.008, parent=cn)
    box(f"Canopy_Seam{sx}", c_cn, (0.004, CN_Y1 - CN_Y0, 0.006), (sx * CN_X - sx * 0.131,
        (CN_Y0 + CN_Y1) / 2, CN_ZB + 0.09), M["oak_edge"], bevel=0.0, parent=cn)
    for k in range(4):
        cyl(f"Canopy_DownlightS{sx}{k}", c_cn, 0.04, 0.006, (sx * CN_X, CN_Y0 + 0.2 + k * 0.32, CN_ZB - 0.003),
            M["downlight"], segs=14, parent=cn)
    EXTRA_LIGHTS.append((f"Canopy_Light{sx}", (sx * CN_X, 3.7, 2.38), 22))
for k in range(11):
    cyl(f"Canopy_DownlightF{k}", c_cn, 0.04, 0.006, (-3.0 + k * 0.6, CN_Y0, CN_ZB - 0.003), M["downlight"],
        segs=14, parent=cn)
EXTRA_LIGHTS.append(("Canopy_LightFront", (0.0, CN_Y0, 2.4), 22))

# --- warm cove light under the counter lip (area strip, pointing down the fluted front)
_cd = bpy.data.lights.new("Counter_CoveLight", "AREA")
_cd.shape = "RECTANGLE"
_cd.size, _cd.size_y = CT_W - 0.2, 0.05
_cd.energy = 45
_cd.color = WARM_2700K
_co = bpy.data.objects.new("Counter_CoveLight", _cd)
_co.location = (0, COUNTER_Y - 0.31, CT_H - 0.07)
_co.rotation_euler = (math.radians(-12), 0, 0)
link(_co, c_rs)
_co["light_type"] = "AREA"
_co["light_color"] = list(WARM_2700K)
_co["light_power_w"] = 45
_co["light_size_m"] = [CT_W - 0.2, 0.05]


# ================================================================ 17. Front floor + upper side-wall detail
# --- large low-pile rug in the front-middle (courier's spot ~1.5 m clear)
c_fr = make_coll("FrontRug")
fr = empty("FrontRug", c_fr, (2.2, -2.4, 0))
box("FrontRug_Border", c_fr, (3.6, 1.6, 0.006), (0, 0, 0.003), mat("M_RugTerracotta", "#c27a55", 0.95),
    bevel=0.0, parent=fr)
box("FrontRug_Field", c_fr, (3.44, 1.44, 0.008), (0, 0, 0.004), mat("M_RugNeutral", "#e2d6c3", 0.95),
    bevel=0.0, parent=fr)

# --- tall potted plants spaced along the open front edge (fiddle-leaf / olive)
c_fp = make_coll("FrontPlants")
fpl = empty("FrontPlants", c_fp)
M["fiddle"] = mat("M_FiddleLeaf", "#3f6b3c", 0.6)
M["olive"] = mat("M_OliveLeaf", "#8a9a6e", 0.8)
for i, (px, kind, pot) in enumerate(((-6.3, "fiddle", "rust"), (-2.8, "olive", "black_metal"),
                                    (2.6, "fiddle", "black_metal"), (4.0, "olive", "rust"))):
    root = empty(f"FrontPlant_{i}", c_fp, (px, -4.5, 0), parent=fpl)
    cyl(f"FrontPlant_{i}_Pot", c_fp, 0.16, 0.42, (0, 0, 0.21), M[pot], segs=20, parent=root, r2=0.2)
    cyl(f"FrontPlant_{i}_Soil", c_fp, 0.185, 0.01, (0, 0, 0.415), M["soil"], segs=20, parent=root)
    cyl(f"FrontPlant_{i}_Trunk", c_fp, 0.018, 0.75, (0, 0, 0.78), M["wood_dark"], segs=8, parent=root)
    rng_p = random.Random(20 + i)
    if kind == "fiddle":
        for k in range(10):
            a = k * 2.4
            z = 0.95 + (k % 5) * 0.08
            sphere(f"FrontPlant_{i}_Leaf{k}", c_fp, 1.0, (0.13 * math.cos(a), 0.13 * math.sin(a), z), M["fiddle"],
                   parent=root, scale=(0.11, 0.03, 0.15), segs=10, rings=6).rotation_euler = (
                math.radians(rng_p.uniform(-25, 25)), 0, a)
    else:
        for k, (dx, dy, dz, r) in enumerate(((0, 0, 1.18, 0.2), (0.14, 0.05, 1.05, 0.15), (-0.13, -0.06, 1.08, 0.16),
                                             (0.03, -0.1, 1.28, 0.13))):
            sphere(f"FrontPlant_{i}_Crown{k}", c_fp, r, (dx, dy, dz), M["olive"], parent=root,
                   scale=(1, 1, 0.8), segs=12, rings=8)

# --- upper side walls: walnut picture rail at 2.1 m + light-oak battens above the wainscot
c_uw = make_coll("UpperWallDetail")
uw = empty("UpperWallDetail", c_uw)
for tag, xf, sgn, y0, y1, batten_spans in (
        ("Left", -SIDE_IN, 1, SHOP_Y1, SL_Y0, ((SHOP_Y1, SL_Y0),)),
        ("Right", SIDE_IN, -1, ROOM_Y0, 1.2, ((ROOM_Y0 + 0.05, -1.6), (0.5, 1.15)))):
    box(f"PictureRail_{tag}", c_uw, (0.04, y1 - y0, 0.035), (xf + sgn * 0.02, (y0 + y1) / 2, 2.1), M["walnut"],
        bevel=0.006, parent=uw)
    k = 0
    for b0, b1 in batten_spans:
        y = b0 + 0.12
        while y < b1 - 0.05:
            box(f"Batten_{tag}{k}", c_uw, (0.02, 0.035, 0.94), (xf + sgn * 0.01, y, 1.61), M["light_oak"],
                bevel=0.004, parent=uw)
            y += 0.25
            k += 1

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
    # small tablet for approving holds, held in front with both hands
    box(f"{name}_Tablet", coll, (0.22, 0.16, 0.012), (0.0, -0.3, 1.04), M["graphite"],
        bevel=0.007, parent=root, rot=(30, 0, 0))
    box(f"{name}_TabletScreen", coll, (0.195, 0.135, 0.003), (0.0, -0.302, 1.048), M["screen"],
        bevel=0.0, parent=root, rot=(30, 0, 0))


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


figure("Ivy", (-4.6, -0.85, 0), 0, M["green"], M["pants"], hair_ivy,
       arms=("down", "tuck"), extras=ivy_extras)
figure("Milo", (0.0, COUNTER_Y + 0.62, 0), 0, M["white"], M["pants_dark"], hair_milo,
       arms=("forward", "forward"), extras=milo_extras)
figure("MrsHart", (0.85, COUNTER_Y + 0.66, 0), -8, M["white"], M["pants_dark"], hair_hart,
       arms=("forward", "forward"), extras=hart_extras)
figure("InkwellCourier", (-0.3, -4.2, 0), -128, M["hood"], M["pants_dark"], hair_courier,
       arms=("down", "forward"), eyes=False, extras=courier_extras)


# ================================================================ 10. Lights / world / camera
c_env = make_coll("Environment")
world = bpy.data.worlds.new("QuietWorld")
scene.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs["Color"].default_value = (*hexcol("#cfc6b8"), 1)
bg.inputs["Strength"].default_value = 0.85  # soft warm-grey daylight ambient

sun_d = bpy.data.lights.new("Sun_Key", "SUN")
sun_d.energy = 2.5
sun_d.color = (1.0, 0.96, 0.9)  # warm white, from front-left
sun_d.angle = math.radians(12)
sun = bpy.data.objects.new("Sun_Key", sun_d)
sun.rotation_euler = (math.radians(42), math.radians(0), math.radians(-35))
link(sun, c_env)

def tag_light(ob):
    """Extras so the web page can recreate the light (color linear RGB, power in W)."""
    d = ob.data
    ob["light_type"] = d.type
    ob["light_color"] = [round(c, 4) for c in d.color]
    ob["light_power_w" if d.type != "SUN" else "light_strength"] = d.energy
    if d.type == "AREA":
        ob["light_size_m"] = d.size


tag_light(sun)
for i, bpos in enumerate(BULBS):
    pd = bpy.data.lights.new(f"PendantLamp_Light{i}", "POINT")
    pd.energy = 28
    pd.color = WARM_2700K
    pd.shadow_soft_size = 0.06
    po = bpy.data.objects.new(f"PendantLamp_Light{i}", pd)
    po.location = bpos
    link(po, c_env)
    tag_light(po)
nd = bpy.data.lights.new("ReadingLamp_Light", "POINT")
nd.energy = 22
nd.color = WARM_2700K
nd.shadow_soft_size = 0.08
no = bpy.data.objects.new("ReadingLamp_Light", nd)
no.location = NOOK_LAMP
link(no, c_env)
tag_light(no)
for lname, lpos, lpow in EXTRA_LIGHTS:
    ld = bpy.data.lights.new(lname, "POINT")
    ld.energy = lpow * 0.9
    ld.color = WARM_2700K
    ld.shadow_soft_size = 0.06
    lo = bpy.data.objects.new(lname, ld)
    lo.location = lpos
    link(lo, c_env)
    tag_light(lo)

area_d = bpy.data.lights.new("Area_Fill", "AREA")
area_d.energy = 450
area_d.size = 12
area = bpy.data.objects.new("Area_Fill", area_d)
area.location = (-7.5, -8.0, 9.0)
area.rotation_euler = (Vector((0, 0, 0.5)) - area.location).to_track_quat("-Z", "Y").to_euler()
link(area, c_env)
tag_light(area)

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


OVERVIEW = ((1.2, -16.5, 8.6), (0.3, 0.2, 0.3), 29.5)  # looks in through the open front
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
    if hasattr(ee, "shadow_pool_size"):
        try:
            ee.shadow_pool_size = "1024"
        except Exception:
            pass
    for attr, val in (("use_shadows", True), ("use_raytracing", False),
                      ("shadow_ray_count", 2), ("shadow_step_count", 8)):
        if hasattr(ee, attr):
            setattr(ee, attr, val)
except Exception as exc:
    print("eevee settings:", exc)

# soft bloom on emissive bulbs/screens via compositor Glare (Blender 5.x node-group API)
try:
    ng = bpy.data.node_groups.new("QP_Compositor", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = ng.nodes.new("CompositorNodeRLayers")
    gl = ng.nodes.new("CompositorNodeGlare")
    out = ng.nodes.new("NodeGroupOutput")
    if hasattr(gl, "glare_type"):
        gl.glare_type = "BLOOM"
    elif "Type" in gl.inputs:
        gl.inputs["Type"].default_value = "Bloom"
    for key, val in (("Threshold", 1.4), ("Strength", 0.2), ("Size", 0.5)):
        if key in gl.inputs:
            gl.inputs[key].default_value = val
    ng.links.new(rl.outputs["Image"], gl.inputs["Image"])
    ng.links.new(gl.outputs["Image"], out.inputs[0])
    scene.compositing_node_group = ng
    print("QP_BLOOM ok", [(i.name, getattr(i, "default_value", None)) for i in gl.inputs if i.name in ("Type", "Threshold", "Strength", "Size")])
except Exception as exc:
    print("QP_BLOOM skipped:", exc)

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
join_under(O["Gate_Light"], "Gate_Light_Mesh")
join_under(O["Gate"], "Gate_Mesh", exclude_roots=(O["Gate_Light"], O["Gate_Screen"]))
join_under(O["Ledger"], "Ledger_Mesh")
for who in ("Ivy", "Milo", "MrsHart", "InkwellCourier"):
    join_under(O[who], f"{who}_Mesh",
               exclude_roots=(O["Logo_Badge"],) if who == "Milo" else ())
join_under(O["MenuBoard"], "MenuBoard_Mesh", exclude_roots=(O["MenuBoard_Image"], O["MenuBoard_HaloGlow"]))
join_under(O["PendantLamps"], "PendantLamps_Mesh")
join_under(O["PastryCase"], "PastryCase_Mesh", exclude_roots=(O["PastryCase_Glass"], O["PastryCase_GlassFront"]))
join_under(O["Register"], "Register_Mesh")
join_under(O["Plants"], "Plants_Mesh")
join_under(O["PickupCorner"], "PickupCorner_Mesh", exclude_roots=(O["PickupCorner_SignText"],))
join_under(O["ReadingNook"], "ReadingNook_Mesh")
join_under(O["ReadingDivider"], "ReadingDivider_Mesh")
join_under(O["MerchShelf"], "MerchShelf_Mesh", exclude_roots=(O["MerchShelf_Decals"],))
join_under(O["HolidayTree"], "HolidayTree_Mesh")
join_under(O["StringLights"], "StringLights_Mesh")
join_under(O["Wreath"], "Wreath_Mesh")
join_under(O["WallDetails"], "WallDetails_Mesh")
join_under(O["FrontRug"], "FrontRug_Mesh")
join_under(O["FrontPlants"], "FrontPlants_Mesh")
join_under(O["UpperWallDetail"], "UpperWallDetail_Mesh")
join_under(O["BackBar"], "BackBar_Mesh")
join_under(O["WallCladding"], "WallCladding_Mesh", exclude_roots=(O["WallCladding_Chevron"], O["LoungeWall_Back"], O["LoungeWall_Right"]))
join_under(O["LoungeArt"], "LoungeArt_Mesh")
join_under(O["Shopfront"], "Shopfront_Mesh")
join_under(O["Canopy"], "Canopy_Mesh")
join_under(O["CommunalTable"], "CommunalTable_Mesh")
join_under(O["Banquette"], "Banquette_Mesh")
join_under(O["WallArt"], "WallArt_Mesh")
join_under(O["LoungeCluster"], "LoungeCluster_Mesh")
join_under(O["BookOfTheDay"], "BookOfTheDay_Mesh", exclude_roots=(O["BookOfTheDay_Face"],))


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
                   export_cameras=True, export_lights=True, export_yup=True)
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
    gm = mat("M_PreviewGround", "#b9b0a3", 0.95)
    bmg = bmesh.new()
    bmesh.ops.create_grid(bmg, x_segments=1, y_segments=1, size=400)
    ground = finish_mesh(bmg, "Preview_Ground", c_env, gm, (0, 0, -1.1), None)
    render_to(os.path.join(OUT, "preview-overview.png"), *OVERVIEW)
    render_to(os.path.join(OUT, "preview-ivy.png"), (-2.9, -3.7, 1.95), (-4.5, -1.2, 1.05), 42)
    render_to(os.path.join(OUT, "preview-counter.png"), (0.55, 0.9, 2.45), (0.25, 3.85, 1.15), 16)
    render_to(os.path.join(OUT, "preview-seating.png"), (0.5, -8.6, 6.2), (0.0, 1.4, 0.6), 19)
    render_to(os.path.join(OUT, "preview-merch.png"), (-4.4, 1.2, 1.7), (-5.75, 4.4, 1.05), 30)
    render_to(os.path.join(OUT, "preview-holiday.png"), (4.2, -8.2, 2.8), (6.6, -3.2, 1.1), 26)
    render_to(os.path.join(OUT, "preview-walls.png"), (1.2, -1.8, 2.1), (-5.2, 3.0, 1.45), 22)
    render_to(os.path.join(OUT, "preview-nook.png"), (3.9, -8.0, 2.7), (6.3, -2.9, 0.8), 30)
    render_to(os.path.join(OUT, "preview-gate.png"), (0.75, 2.3, 1.5), (0.5, 3.4, 1.12), 40)
    aim(cam, *OVERVIEW)
    bpy.data.objects.remove(ground)
    bpy.data.materials.remove(gm)

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "quiet-page.blend"))
print("QP_DONE")
