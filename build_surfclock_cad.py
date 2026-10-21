#!/usr/bin/env python3
"""
SurfClock 3D Printable CAD Generator
Generates watertight 3D-printable STL models and assembly files for the SurfClock project,
based on the Weekday-Clock reference geometry (190mm diameter clock face) and adapted for:
  - 5 Northern Beaches (Long Reef 0°, Dee Why 60°, Curl Curl 120°, Freshie 240°, Queenscliff 300°)
  - 6 o'clock (180°) "CONDITIONS" subdial gauge (1-10 semicircle arc) + shaft through-hole
  - Direct-fit 28BYJ-48 stepper motor arms (Main Break Arm + Conditions Arm) with Double-D shaft sockets
  - Built-in neodymium magnet pockets on both arms aligned with HW-477 / A3144 Hall sensor mounts
  - Large clip-on back compartment (Chassis + Snap-Fit Flat Wall Cover) to hide all cables & electronics
  - Dedicated Desktop Stand for desk display
"""

import os
import math
from functools import reduce
import numpy as np
import shapely.geometry as sg
import shapely.affinity as sa
import shapely.ops as so
import trimesh
import manifold3d as m3d
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties

# Font setup for crisp 3D-printable bold lettering
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
if not os.path.exists(FONT_PATH):
    FONT_PATH = "/System/Library/Fonts/Helvetica.ttc"
FONT_PROP = FontProperties(fname=FONT_PATH)


def trimesh_to_manifold(mesh: trimesh.Trimesh) -> m3d.Manifold:
    """Convert a trimesh.Trimesh into a manifold3d.Manifold."""
    verts = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.uint32)
    return m3d.Manifold(m3d.Mesh(vert_properties=verts, tri_verts=faces))


def manifold_to_trimesh(manifold: m3d.Manifold) -> trimesh.Trimesh:
    """Convert a manifold3d.Manifold back into a clean trimesh.Trimesh."""
    m = manifold.to_mesh()
    verts = np.asarray(m.vert_properties)[:, :3]
    faces = np.asarray(m.tri_verts)
    tm = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    return tm


def extrude_shapely(geom, z_min: float, z_max: float) -> m3d.Manifold:
    """Extrude any Shapely Polygon or MultiPolygon from z_min to z_max as a Manifold."""
    if geom is None or geom.is_empty:
        return m3d.Manifold()
    height = z_max - z_min
    if height <= 0:
        return m3d.Manifold()

    polys = []
    if isinstance(geom, sg.Polygon):
        polys = [geom]
    elif isinstance(geom, (sg.MultiPolygon, sg.GeometryCollection)):
        polys = [g for g in geom.geoms if isinstance(g, sg.Polygon) and not g.is_empty and g.area > 1e-4]

    meshes = []
    for p in polys:
        p_clean = p.buffer(0)
        if p_clean.is_empty:
            continue
        sub_polys = [p_clean] if isinstance(p_clean, sg.Polygon) else list(p_clean.geoms)
        for sp in sub_polys:
            if sp.area < 1e-4:
                continue
            tm = trimesh.creation.extrude_polygon(sp, height=height)
            tm.apply_translation([0.0, 0.0, z_min])
            meshes.append(tm)

    if not meshes:
        return m3d.Manifold()
    combined = trimesh.util.concatenate(meshes)
    return trimesh_to_manifold(combined)


def circle_poly(cx: float, cy: float, r: float, resolution: int = 96) -> sg.Polygon:
    """Create a high-resolution circular Shapely polygon."""
    angles = np.linspace(0, 2 * np.pi, resolution, endpoint=False)
    pts = np.column_stack([cx + r * np.cos(angles), cy + r * np.sin(angles)])
    return sg.Polygon(pts)


def ring_poly(cx: float, cy: float, r_in: float, r_out: float, resolution: int = 128) -> sg.Polygon:
    """Create an annular ring Shapely polygon."""
    return circle_poly(cx, cy, r_out, resolution).difference(circle_poly(cx, cy, r_in, resolution))


def arc_band_poly(cx: float, cy: float, r_in: float, r_out: float,
                  deg_start_cw: float, deg_end_cw: float, steps: int = 96) -> sg.Polygon:
    """
    Create a circular arc band where angles are measured CLOCKWISE from +Y (12 o'clock).
    (0° = +Y, 90° = +X, -90° = -X, 180° = -Y)
    """
    thetas = np.radians(np.linspace(deg_start_cw, deg_end_cw, steps))
    outer = np.column_stack([cx + r_out * np.sin(thetas), cy + r_out * np.cos(thetas)])
    inner = np.column_stack([cx + r_in * np.sin(thetas[::-1]), cy + r_in * np.cos(thetas[::-1])])
    pts = np.vstack([outer, inner])
    return sg.Polygon(pts).buffer(0)


def text_to_shapely(text: str, size: float, tracking: float = 0.0) -> sg.base.BaseGeometry:
    """
    Render a text string to a centered 2D Shapely geometry using even-odd contour XOR
    so letter holes (O, R, D, Q, 0, etc.) are always preserved.
    """
    tp = TextPath((0, 0), text, size=size, prop=FONT_PROP)
    raw_loops = [sg.Polygon(p).buffer(0) for p in tp.to_polygons() if len(p) >= 3]
    if not raw_loops:
        return sg.Polygon()
    geom = reduce(lambda a, b: a.symmetric_difference(b), raw_loops)
    minx, miny, maxx, maxy = geom.bounds
    cx = 0.5 * (minx + maxx)
    cy = 0.5 * (miny + maxy)
    return sa.translate(geom, xoff=-cx, yoff=-cy)


def curved_text_shapely(text: str, radius: float, center_angle_cw_deg: float,
                        font_size: float, letter_spacing_deg: float,
                        bottom_half: bool = False) -> sg.base.BaseGeometry:
    """
    Place bold 3D-printable uppercase letters along a circular arc of given `radius`
    centered at `center_angle_cw_deg` (clockwise from 12 o'clock +Y).
    If `bottom_half=False`, letters run clockwise (readable at top/upper sides).
    If `bottom_half=True`, letters run counter-clockwise with tops inward (readable at bottom/lower sides).
    """
    chars = list(text)
    # Measure character widths for proportional angular spacing
    char_geoms = []
    char_widths = []
    space_width = font_size * 0.42
    extra_pad = font_size * 0.14

    for ch in chars:
        if ch == " ":
            char_geoms.append(None)
            char_widths.append(space_width)
        else:
            g = text_to_shapely(ch, size=font_size)
            minx, miny, maxx, maxy = g.bounds
            w = (maxx - minx) + extra_pad
            char_geoms.append(g)
            char_widths.append(w)

    total_arc_len = sum(char_widths)
    total_angle_deg = math.degrees(total_arc_len / radius)

    placed = []
    if not bottom_half:
        # Clockwise progression
        curr_deg = center_angle_cw_deg - 0.5 * total_angle_deg
        for g, w in zip(char_geoms, char_widths):
            d_deg = math.degrees(w / radius)
            char_deg = curr_deg + 0.5 * d_deg
            curr_deg += d_deg
            if g is not None:
                # At char_deg (CW from +Y), position is (R*sin(theta), R*cos(theta))
                # Rotation of letter is -char_deg (CCW degrees in standard XY)
                rad = math.radians(char_deg)
                x = radius * math.sin(rad)
                y = radius * math.cos(rad)
                g_rot = sa.rotate(g, -char_deg, origin=(0, 0))
                g_pos = sa.translate(g_rot, xoff=x, yoff=y)
                placed.append(g_pos)
    else:
        # Counter-clockwise progression so bottom labels read left-to-right right-side-up
        curr_deg = center_angle_cw_deg + 0.5 * total_angle_deg
        for g, w in zip(char_geoms, char_widths):
            d_deg = math.degrees(w / radius)
            char_deg = curr_deg - 0.5 * d_deg
            curr_deg -= d_deg
            if g is not None:
                rad = math.radians(char_deg)
                x = radius * math.sin(rad)
                y = radius * math.cos(rad)
                # Rotate by 180 - char_deg so top of letter points toward center
                g_rot = sa.rotate(g, 180.0 - char_deg, origin=(0, 0))
                g_pos = sa.translate(g_rot, xoff=x, yoff=y)
                placed.append(g_pos)

    return so.unary_union(placed)


def double_d_shaft_poly(cx: float = 0.0, cy: float = 0.0,
                        d_outer: float = 5.22, flat_width: float = 3.16,
                        rotation_deg: float = 0.0) -> sg.Polygon:
    """
    28BYJ-48 stepper motor Double-D output shaft socket cross-section.
    Standard shaft is 5.0mm OD with 3.0mm across flats.
    We use 5.22mm OD and 3.16mm across flats for a direct 3D-printed press-fit.
    """
    c = circle_poly(0, 0, d_outer / 2.0, resolution=72)
    box = sg.box(-d_outer, -flat_width / 2.0, d_outer, flat_width / 2.0)
    dd = c.intersection(box)
    if rotation_deg != 0.0:
        dd = sa.rotate(dd, rotation_deg, origin=(0, 0))
    return sa.translate(dd, xoff=cx, yoff=cy)


# ==============================================================================
# PART 1: SURFCLOCK FACE (Classic Sector Ring Edition + Minimalist Edition)
# ==============================================================================
def build_surfclock_face(classic_rings: bool = True) -> trimesh.Trimesh:
    """
    Build the 190mm SurfClock Face (`surfclock_face.stl` or `surfclock_face_minimal.stl`).
    - Base plate: Z = 0.0 to 1.6 mm (190.0mm diameter)
    - Raised relief: Z = 1.6 to 2.6 mm (1.0mm raised height for filament color change at 1.8mm)
    - Center hole at (0, 0): Ø 9.4mm for Main Break 28BYJ-48 shaft/boss
    - 6 o'clock hole at (0, -54.0): Ø 9.4mm for Conditions Gauge 28BYJ-48 shaft/boss
    - 5 Northern Beaches at 0° (Long Reef), 60° (Dee Why), 120° (Curl Curl), 240° (Freshie), 300° (Queenscliff)
    - 6 o'clock (180°) Conditions Subdial (1-10 semicircle gauge arc + ticks + CONDITIONS label)
    """
    R_OUTER = 95.0
    SUBDIAL_Y = -54.0
    HOLE_R = 4.7  # Ø 9.4mm clearance for 28BYJ-48 9mm boss + 5mm shaft

    # 1. Base disk (Z = 0.0 to 1.6 mm) with the two motor shaft holes
    base_2d = circle_poly(0, 0, R_OUTER, resolution=180)
    base_2d = base_2d.difference(circle_poly(0, 0, HOLE_R, resolution=64))
    base_2d = base_2d.difference(circle_poly(0, SUBDIAL_Y, HOLE_R, resolution=64))

    # Subtract 4 shallow registration sockets on the back (Z = 0.0 to 0.8 mm) at R = 85mm
    reg_holes_2d = so.unary_union([
        circle_poly(85.0 * math.cos(math.radians(a)), 85.0 * math.sin(math.radians(a)), 2.25, resolution=36)
        for a in [45, 135, 225, 315]
    ])
    base_bottom_2d = base_2d.difference(reg_holes_2d)

    m_base_bottom = extrude_shapely(base_bottom_2d, 0.0, 0.8)
    m_base_top = extrude_shapely(base_2d, 0.8, 1.6)
    m_base = m_base_bottom + m_base_top

    # 2. Raised relief geometry (Z = 1.6 to 2.6 mm)
    relief_parts = []

    if classic_rings:
        # Outer ring (R = 93..95mm)
        relief_parts.append(ring_poly(0, 0, 93.0, 95.0, resolution=180))

        # Inner ring (R = 68..70mm), gracefully arched around the 6 o'clock Conditions subdial
        inner_r = ring_poly(0, 0, 68.0, 70.0, resolution=180)
        subdial_clear = circle_poly(0, SUBDIAL_Y, 26.5, resolution=96)
        subdial_arch = ring_poly(0, SUBDIAL_Y, 26.5, 28.5, resolution=96).intersection(
            circle_poly(0, 0, 70.0, resolution=180)
        )
        inner_r = inner_r.difference(subdial_clear).union(subdial_arch)
        relief_parts.append(inner_r)

        # 6 sector divider lines at 30°, 90°, 150°, 210°, 270°, 330° (between the 6 60° zones)
        for div_deg in [30, 90, 150, 210, 270, 330]:
            bar = sg.box(-1.0, 68.5, 1.0, 94.0)
            bar_rot = sa.rotate(bar, -div_deg, origin=(0, 0))
            relief_parts.append(bar_rot)

        # 5 Beach target index ticks on outer & inner rings at 0°, 60°, 120°, 240°, 300°
        for tick_deg in [0, 60, 120, 240, 300]:
            outer_tick = sa.rotate(sg.box(-1.1, 90.0, 1.1, 93.5), -tick_deg, origin=(0, 0))
            inner_tick = sa.rotate(sg.box(-1.1, 65.5, 1.1, 69.0), -tick_deg, origin=(0, 0))
            relief_parts.append(outer_tick)
            relief_parts.append(inner_tick)
    else:
        # Minimalist outer bezel ring (R = 91.5..95.0mm) + subtle index ticks
        relief_parts.append(ring_poly(0, 0, 91.5, 95.0, resolution=180))
        for tick_deg in [0, 60, 120, 240, 300]:
            outer_tick = sa.rotate(sg.box(-1.0, 88.5, 1.0, 92.0), -tick_deg, origin=(0, 0))
            relief_parts.append(outer_tick)

    # 3. 5 Beaches + 6 o'clock CONDITIONS text labels
    # Angles from README.md & stepper_controller.cpp:
    #   Pos 1: LONG REEF   -> 0°   (12 o'clock)
    #   Pos 2: DEE WHY     -> 60°  (2 o'clock)
    #   Pos 3: CURL CURL   -> 120° (4 o'clock)
    #   Pos 4: FRESHIE     -> 240° (8 o'clock)
    #   Pos 5: QUEENSCLIFF -> 300° (10 o'clock)
    #   6 o'clock: CONDITIONS -> 180° (6 o'clock)
    beaches = [
        ("LONG REEF",   0.0,   False, 9.2),
        ("DEE WHY",     60.0,  False, 9.2),
        ("CURL CURL",   120.0, True,  9.2),
        ("FRESHIE",     240.0, True,  9.2),
        ("QUEENSCLIFF", 300.0, False, 8.3),
        ("CONDITIONS",  180.0, True,  7.6),
    ]
    for label, angle_cw, is_bottom, fsize in beaches:
        txt_geom = curved_text_shapely(
            label, radius=81.5, center_angle_cw_deg=angle_cw,
            font_size=fsize, letter_spacing_deg=0.0, bottom_half=is_bottom
        )
        # Bold buffer (+0.12mm) so thin strokes print rock-solid on 0.4mm nozzles
        relief_parts.append(txt_geom.buffer(0.12))

    # 4. 6 O'Clock Conditions Subdial Gauge (centered at (0, SUBDIAL_Y = -54.0))
    # Semicircle arc from -90° (left, Rating 1) through 0° (top, Rating 5.5) to +90° (right, Rating 10)
    R_ARC_IN = 18.0
    R_ARC_OUT = 19.8
    arc_band = arc_band_poly(0.0, SUBDIAL_Y, R_ARC_IN, R_ARC_OUT, -90.0, 90.0, steps=96)
    relief_parts.append(arc_band)

    # 10 Rating ticks along the 180° semicircle (Rating 1 at -90° to Rating 10 at +90°, every 20°)
    for i in range(10):
        deg_cw = -90.0 + i * 20.0
        is_major = (i == 0 or i == 9 or i == 4 or i == 5)
        t_in = 15.2 if (i == 0 or i == 9) else (16.0 if is_major else 16.6)
        t_w = 0.85 if (i == 0 or i == 9) else 0.65
        tick_box = sg.box(-t_w, t_in, t_w, R_ARC_OUT + 0.6)
        tick_rot = sa.rotate(tick_box, -deg_cw, origin=(0, 0))
        tick_pos = sa.translate(tick_rot, xoff=0.0, yoff=SUBDIAL_Y)
        relief_parts.append(tick_pos)

    # Subdial '1' and '10' markers at left (-90°) and right (+90°) of the arc
    lbl_1 = sa.translate(text_to_shapely("1", size=5.5).buffer(0.1), xoff=-23.2, yoff=SUBDIAL_Y + 0.5)
    lbl_10 = sa.translate(text_to_shapely("10", size=5.5).buffer(0.1), xoff=24.2, yoff=SUBDIAL_Y + 0.5)
    relief_parts.append(lbl_1)
    relief_parts.append(lbl_10)

    # Combine all raised relief elements and clip to base_2d
    relief_2d = so.unary_union(relief_parts).intersection(base_2d)
    m_relief = extrude_shapely(relief_2d, 1.6, 2.6)

    m_total = m_base + m_relief
    return manifold_to_trimesh(m_total)


# ==============================================================================
# ==============================================================================
# PART 2: MAIN BREAK ARM (Stepped Overpass Architecture + Magnet Pockets)
# ==============================================================================
def build_main_break_arm() -> trimesh.Trimesh:
    """
    Build the Main Break Pointer Arm (`main_break_arm.stl`).
    - Stepped Horological Overpass Design:
      - Hub base riser extends from Z = 0.0 to 4.85 mm.
      - Pointer blade takes off at Z = 4.80 mm (up to Z = 7.20 mm, 2.4mm thick).
      - This gives an unobstructed 1.4mm vertical clearance above the Conditions needle (max Z = 3.4mm),
        allowing full 360° unrestricted rotation across 6 o'clock during homing and travel without collision!
    - Direct press-fit 28BYJ-48 5mm Double-D shaft socket (6.5mm deep).
    - Stepped neodymium magnet pockets on underside of blade (R = 22.0mm) and tail (R = -10.8mm).
    """
    hub_outer = circle_poly(0, 0, 8.0, resolution=96)

    # Pointer blade + counterweight tail + magnet pads
    blade_pts = [
        (-3.6, -14.0),
        (3.6, -14.0),
        (4.2, 0.0),
        (2.8, 56.0),
        (0.0, 63.5),
        (-2.8, 56.0),
        (-4.2, 0.0),
    ]
    blade_poly = sg.Polygon(blade_pts).buffer(0.6, join_style=1)
    mag_pad_front = circle_poly(0, 22.0, 4.4, resolution=64)
    mag_pad_tail = circle_poly(0, -10.8, 3.8, resolution=64)
    arm_body_2d = so.unary_union([circle_poly(0, 0, 7.5, 64), blade_poly, mag_pad_front, mag_pad_tail])

    # Solid layers:
    # 1. Hub base riser collar (Z = 0.0 to 4.85 mm) elevating blade above Conditions arm
    m_hub_riser = extrude_shapely(hub_outer, 0.0, 4.85)
    # 2. Elevated pointer blade & tail (Z = 4.80 to 7.20 mm)
    m_blade = extrude_shapely(arm_body_2d, 4.80, 7.20)
    # 3. Center cap crown (Z = 7.15 to 7.80 mm, Ø 13.6mm)
    m_crown = extrude_shapely(circle_poly(0, 0, 6.8, 72), 7.15, 7.80)

    m_solid = m_hub_riser + m_blade + m_crown

    # Subtract Direct 28BYJ-48 Double-D Shaft Socket (Z = -0.1 to 6.5 mm deep)
    shaft_2d = double_d_shaft_poly(0, 0, d_outer=5.22, flat_width=3.16, rotation_deg=0.0)
    chamfer_2d = double_d_shaft_poly(0, 0, d_outer=5.60, flat_width=3.50, rotation_deg=0.0)
    m_shaft_cut = extrude_shapely(shaft_2d, -0.1, 6.5) + extrude_shapely(chamfer_2d, -0.1, 0.8)

    # Subtract Stepped Neodymium Magnet Pockets on underside of elevated blade:
    # Pocket 1 at (0, +22.0mm): outer Ø 5.2mm (Z = 4.7..6.1mm), inner Ø 3.2mm (Z = 6.0..6.9mm)
    m_mag1 = (
        extrude_shapely(circle_poly(0, 22.0, 2.62, 64), 4.7, 6.1) +
        extrude_shapely(circle_poly(0, 22.0, 1.62, 64), 6.0, 6.9)
    )
    # Pocket 2 at (0, -10.8mm): outer Ø 4.2mm (Z = 4.7..6.1mm), inner Ø 3.2mm (Z = 6.0..6.9mm)
    m_mag2 = (
        extrude_shapely(circle_poly(0, -10.8, 2.12, 64), 4.7, 6.1) +
        extrude_shapely(circle_poly(0, -10.8, 1.62, 64), 6.0, 6.9)
    )

    m_final = m_solid - m_shaft_cut - m_mag1 - m_mag2
    return manifold_to_trimesh(m_final)


# ==============================================================================
# PART 3: CONDITIONS SUBDIAL ARM (Low-Profile Sub-Dial Needle)
# ==============================================================================
def build_conditions_arm() -> trimesh.Trimesh:
    """
    Build the 6 o'clock Conditions Gauge Pointer Arm (`conditions_arm.stl`).
    - Low-Profile Subdial Design:
      - Max height is capped at Z = 3.4 mm above dial plate.
      - Sweeps below the elevated Main Break Arm (blade at Z = 4.80..7.20 mm).
    - Directly press-fits onto the second 28BYJ-48 5mm Double-D shaft at (0, -54.0mm).
    - Needle length: 19.2mm (sweeps along the R=18.0..19.8mm semicircle arc from 1 to 10).
    - Stepped underside neodymium magnet pocket at R = 14.5mm (Ø 4.2mm / Ø 3.2mm).
    """
    hub_outer = circle_poly(0, 0, 6.0, resolution=72)  # Ø 12.0mm hub covers Ø 9.4mm hole

    needle_pts = [
        (-2.0, -5.2),
        (2.0, -5.2),
        (2.4, 0.0),
        (1.5, 16.5),
        (0.0, 19.2),
        (-1.5, 16.5),
        (-2.4, 0.0),
    ]
    needle_poly = sg.Polygon(needle_pts).buffer(0.35, join_style=1)
    mag_pad = circle_poly(0, 14.5, 3.2, resolution=64)
    arm_body_2d = so.unary_union([circle_poly(0, 0, 5.5, 64), needle_poly, mag_pad])

    # Solid layers (Z = 0.0 to 3.40 mm)
    m_hub_col = extrude_shapely(hub_outer, 0.0, 3.10)
    m_needle = extrude_shapely(arm_body_2d, 1.0, 2.85)
    m_cap_top = extrude_shapely(circle_poly(0, 0, 4.4, 64), 3.05, 3.40)

    m_solid = m_hub_col + m_needle + m_cap_top

    # Subtract Direct 28BYJ-48 Double-D Shaft Socket (Z = -0.1 to 2.8 mm deep)
    shaft_2d = double_d_shaft_poly(0, 0, d_outer=5.22, flat_width=3.16, rotation_deg=0.0)
    chamfer_2d = double_d_shaft_poly(0, 0, d_outer=5.60, flat_width=3.50, rotation_deg=0.0)
    m_shaft_cut = extrude_shapely(shaft_2d, -0.1, 2.8) + extrude_shapely(chamfer_2d, -0.1, 0.5)

    # Subtract Stepped Magnet Pocket at (0, +14.5mm) on underside of needle (Z = 1.0 to 2.5 mm)
    m_mag = (
        extrude_shapely(circle_poly(0, 14.5, 2.12, 64), 1.0, 2.05) +
        extrude_shapely(circle_poly(0, 14.5, 1.62, 64), 2.00, 2.50)
    )

    m_final = m_solid - m_shaft_cut - m_mag
    return manifold_to_trimesh(m_final)


# ==============================================================================
# PART 4: BACK COMPARTMENT CHASSIS (Dual 28BYJ-48 Mounts + Hall Mounts + Clip Rim)
# ==============================================================================
def build_back_compartment_chassis() -> trimesh.Trimesh:
    """
    Build the Rear Motor & Electronics Carrier Chassis (`back_compartment_chassis.stl`).
    Mounts directly behind `surfclock_face.stl` (Z = 0 is the back of the clock face,
    printed flat on the bed with Z = 0 down).
    Features:
      - Motor 1 (28BYJ-48) cradle & M3 screw pillars for shaft at (0, 0) -> body at (0, -8.0mm), ears at (±17.5, -8.0mm)
        leaving the 12 o'clock datum at (0, +22.0mm) 100% clear of the motor can!
      - Motor 2 (28BYJ-48) cradle & M3 screw pillars for shaft at (0, -54.0mm) -> body at (0, -62.0mm), ears at (±17.5, -62.0mm)
      - Hall Sensor 1 (HW-477 / A3144) pocket at (0, +22.0mm) (12 o'clock datum)
      - Hall Sensor 2 (HW-477 / A3144) pocket at (-14.5, -54.0mm) (Rating 1 datum, completely clear of Motor 2 can)
      - Electronics mounting bosses for 2x ULN2003 boards & ESP32-S3 + cable tie loops
      - Outer snap-fit rim (Ø 174.0mm) that mates with `back_compartment_cover.stl`
    """
    R_CHASSIS = 87.0  # Ø 174.0mm
    SUBDIAL_Y = -54.0

    # 1. Base plate (Z = 0.0 to 3.0 mm)
    plate_2d = circle_poly(0, 0, R_CHASSIS, resolution=160)

    # Shaft + boss clearance holes for Motor 1 (0,0) and Motor 2 (0, -54.0)
    plate_2d = plate_2d.difference(circle_poly(0, 0, 5.2, resolution=64))
    plate_2d = plate_2d.difference(circle_poly(0, SUBDIAL_Y, 5.2, resolution=64))

    # Hall sensor windows right behind dial face so Hall sensor sits within 1.6mm of magnet:
    # Hall 1 at (0, +22.0mm), Hall 2 at (-14.5, -54.0mm)
    hall1_win = sg.box(-3.2, 19.0, 3.2, 25.0)
    hall2_win = sg.box(-17.8, SUBDIAL_Y - 3.2, -11.8, SUBDIAL_Y + 3.2)
    plate_2d = plate_2d.difference(hall1_win).difference(hall2_win)

    # M3 screw clearance holes through base plate at motor ear positions
    motor_ears = [
        (-17.5, -8.0), (17.5, -8.0),
        (-17.5, SUBDIAL_Y - 8.0), (17.5, SUBDIAL_Y - 8.0)
    ]
    for ex, ey in motor_ears:
        plate_2d = plate_2d.difference(circle_poly(ex, ey, 1.5, resolution=36))

    m_plate = extrude_shapely(plate_2d, 0.0, 3.05)

    # 2. Outer Snap-Fit Chassis Wall (R = 84.5 to 87.0 mm, Z = 3.0 to 12.0 mm)
    wall_2d = ring_poly(0, 0, 84.5, R_CHASSIS, resolution=160)
    usb_cut_2d = sg.box(-7.0, -90.0, 7.0, -80.0)
    wall_2d = wall_2d.difference(usb_cut_2d)
    m_wall = extrude_shapely(wall_2d, 2.95, 12.0)

    # Add 4 Exterior Snap-Fit Ridges on the outside of the chassis wall at Z = 8.0..10.5mm (angles 45°, 135°, 225°, 315°)
    snap_ears = []
    for ang in [45, 135, 225, 315]:
        arc = arc_band_poly(0, 0, R_CHASSIS - 0.5, R_CHASSIS + 0.9, ang - 12.0, ang + 12.0, steps=32)
        snap_ears.append(arc)
    m_snaps = extrude_shapely(so.unary_union(snap_ears), 8.0, 10.5)

    # 3. Dual 28BYJ-48 Motor Cradles & M3 Mounting Pillars (Z = 3.0 to 10.0 mm)
    # Motor 1 body center is (0, -8.0mm), radius = 14.2mm
    # Motor 2 body center is (0, -62.0mm), radius = 14.2mm
    cradle_parts = []
    for m_cy in [-8.0, SUBDIAL_Y - 8.0]:
        c_ring = ring_poly(0, m_cy, 14.2, 16.5, resolution=96)
        # Open slot at bottom of each motor ring for blue wire housing (-Y side)
        wire_slot = sg.box(-9.0, m_cy - 20.0, 9.0, m_cy - 10.0)
        # For Motor 2, also keep upper-left (-X, +Y) open for Hall Sensor 2 pocket at (-14.5, -54.0)
        if m_cy < -30.0:
            h2_clear = sg.box(-28.0, SUBDIAL_Y - 5.5, -10.5, SUBDIAL_Y + 8.0)
            c_ring = c_ring.difference(h2_clear)
        c_ring = c_ring.difference(wire_slot)
        cradle_parts.append(c_ring)

    # M3 Mounting Pillars at (±17.5, -8.0) and (±17.5, -62.0)
    for ex, ey in motor_ears:
        pillar = ring_poly(ex, ey, 1.45, 4.2, resolution=48)  # Ø 2.9mm M3 hole, Ø 8.4mm boss
        cradle_parts.append(pillar)

    # Hall Sensor Holder Walls (Z = 3.0 to 8.5 mm)
    # Hall 1 guide U-channel around (-6.8..+6.8, 17.5..33.0), open at +Y for sensor pins
    h1_frame = sg.box(-6.8, 17.5, 6.8, 33.0).difference(sg.box(-5.2, 18.8, 5.2, 34.0))
    # Hall 2 guide U-channel around (-28.0..-10.8, SUBDIAL_Y - 6.0..SUBDIAL_Y + 6.0), open at -X for sensor pins
    h2_frame = sg.box(-28.0, SUBDIAL_Y - 6.0, -10.8, SUBDIAL_Y + 6.0).difference(
        sg.box(-29.0, SUBDIAL_Y - 4.5, -11.8, SUBDIAL_Y + 4.5)
    )

    # Electronics Standoffs (Z = 3.0 to 8.5 mm) for 2x ULN2003 (left) & ESP32-S3 (right)
    standoffs = []
    for sx in [-62.0, -35.0]:
        for sy in [-28.0, -2.0, 24.0]:
            standoffs.append(ring_poly(sx, sy, 1.4, 3.5, resolution=36))
    for sx in [35.0, 63.0]:
        for sy in [-32.0, 22.0]:
            standoffs.append(ring_poly(sx, sy, 1.4, 3.5, resolution=36))

    m_cradles = extrude_shapely(so.unary_union(cradle_parts), 2.95, 10.0)
    m_hall_frames = extrude_shapely(so.unary_union([h1_frame, h2_frame]), 2.95, 8.5)
    m_standoffs = extrude_shapely(so.unary_union(standoffs), 2.95, 8.5)

    m_total = m_plate + m_wall + m_snaps + m_cradles + m_hall_frames + m_standoffs
    return manifold_to_trimesh(m_total)


# ==============================================================================
# PART 5: LARGE CLIP-ON BACK COMPARTMENT COVER (Hides Cables + Flat Wall Mount)
# ==============================================================================
def build_back_compartment_cover() -> trimesh.Trimesh:
    """
    Build the Large Clip-On Back Compartment Lid (`back_compartment_cover.stl`).
    - Prints flat on its exterior back face (Z = 0.0 is the flat wall-contact surface!).
    - Outer diameter: 179.6 mm (R = 89.8 mm), inner diameter: 174.6 mm (R = 87.3 mm).
      Clips directly over the Ø 174.0mm rim of `back_compartment_chassis.stl`!
    - Total height: 24.5 mm (provides 22.0 mm interior depth for 28BYJ-48 motors, ESP32, ULN2003, and all cables).
    - Includes a recessed Flush Keyhole Wall Hanger at 12 o'clock (0, +66.0mm) with an internal
      screw-head pocket so the clock hangs 100% flat against the wall!
    - Includes a bottom USB power cable slot at 6 o'clock (0, -89.8mm).
    """
    R_OUT = 89.8   # Ø 179.6mm
    R_IN = 87.3    # Ø 174.6mm (0.3mm radial clearance over R=87.0mm chassis wall)
    H_TOTAL = 24.5
    WALL_T = 2.4

    # 1. Flat back plate (Z = 0.0 to 2.4 mm)
    back_2d = circle_poly(0, 0, R_OUT, resolution=180)

    # Keyhole Wall-Mount Slot at 12 o'clock (0, +66.0 mm):
    # Entry circle at (0, +62.0mm) Ø 9.6mm, sliding slot up to (0, +70.0mm) width 4.6mm
    kh_entry = circle_poly(0, 62.0, 4.8, resolution=48)
    kh_slot = sg.box(-2.3, 62.0, 2.3, 70.0).union(circle_poly(0, 70.0, 2.3, resolution=36))
    keyhole_2d = kh_entry.union(kh_slot)
    back_2d = back_2d.difference(keyhole_2d)

    # Subtle ventilation slots in left/right lower quadrants for stepper heat dissipation
    vents = []
    for vy in [-25.0, -15.0, -5.0, 5.0, 15.0]:
        vents.append(sg.box(-64.0, vy - 1.2, -42.0, vy + 1.2))
        vents.append(sg.box(42.0, vy - 1.2, 64.0, vy + 1.2))
    back_2d = back_2d.difference(so.unary_union(vents))

    m_back = extrude_shapely(back_2d, 0.0, WALL_T)

    # 2. Internal Screw-Head Hood around Keyhole (Z = 2.4 to 8.0 mm)
    # Gives a recessed cavity inside the compartment for the wall screw head so it never touches electronics
    hood_outer = sg.box(-9.0, 54.0, 9.0, 75.0).buffer(2.0)
    hood_inner = sg.box(-6.5, 56.5, 6.5, 72.5).buffer(1.0)
    hood_walls_2d = hood_outer.difference(hood_inner)
    m_hood = extrude_shapely(hood_walls_2d, WALL_T - 0.1, 7.5)

    # 3. Cylindrical Enclosure Side Wall (Z = 2.3 to 24.5 mm)
    side_2d = ring_poly(0, 0, R_IN, R_OUT, resolution=180)
    # Cut USB cable exit portal at 6 o'clock (Y = -89.8mm, Z = 14.0 to 24.5 mm)
    usb_portal_2d = sg.box(-6.0, -92.0, 6.0, -84.0)
    # Also cut 4 flex-relief slots flanking the 4 snap clips at 45°, 135°, 225°, 315° (Z = 14.0 to 24.5 mm)
    flex_slots = []
    for ang in [45, 135, 225, 315]:
        for offset in [-13.5, 13.5]:
            s_arc = arc_band_poly(0, 0, R_IN - 1.0, R_OUT + 1.0, ang + offset - 1.2, ang + offset + 1.2, steps=8)
            flex_slots.append(s_arc)

    m_side_low = extrude_shapely(side_2d, WALL_T - 0.1, 14.05)
    side_high_2d = side_2d.difference(usb_portal_2d).difference(so.unary_union(flex_slots))
    m_side_high = extrude_shapely(side_high_2d, 13.95, H_TOTAL)

    # 4. 4 Internal Snap-Fit Detention Beads (Z = 20.5 to 22.8 mm) at 45°, 135°, 225°, 315°
    # Protrude inward by 0.85mm (from R_IN = 87.3mm to 86.45mm) to lock over the chassis snap ears!
    inward_snaps = []
    for ang in [45, 135, 225, 315]:
        s_in = arc_band_poly(0, 0, R_IN - 0.85, R_IN + 0.5, ang - 11.0, ang + 11.0, steps=32)
        inward_snaps.append(s_in)
    m_inward_snaps = extrude_shapely(so.unary_union(inward_snaps), 20.5, 22.8)

    # 5. Internal Cable Retainer Clips (3 inward posts connected to inner wall at 0°, 90°, 270° to tuck excess wire loops)
    cable_hooks_col = []
    cable_hooks_lip = []
    for ang in [0, 90, 270]:
        rad = math.radians(ang)
        hx = (R_IN - 1.5) * math.sin(rad)
        hy = (R_IN - 1.5) * math.cos(rad)
        cable_hooks_col.append(circle_poly(hx, hy, 2.6, resolution=32))
        hx_lip = (R_IN - 4.2) * math.sin(rad)
        hy_lip = (R_IN - 4.2) * math.cos(rad)
        cable_hooks_lip.append(circle_poly(hx_lip, hy_lip, 2.4, resolution=32).union(circle_poly(hx, hy, 2.6, 32)))

    m_hooks = (
        extrude_shapely(so.unary_union(cable_hooks_col), WALL_T - 0.1, 12.0) +
        extrude_shapely(so.unary_union(cable_hooks_lip), 9.9, 12.0)
    )

    m_total = m_back + m_hood + m_side_low + m_side_high + m_inward_snaps + m_hooks
    return manifold_to_trimesh(m_total)


# ==============================================================================
# PART 6: DESK STAND (`desk_stand.stl`)
# ==============================================================================
def build_desk_stand() -> trimesh.Trimesh:
    """
    Build the Desktop Cradle Stand (`desk_stand.stl`) for the SurfClock.
    - Designed to hold the assembled SurfClock (190mm Clock Face + 179.6mm Clip-On Back Compartment)
      at a stable 14° desktop tilt angle.
    - Prints flat on its base (Z = 0.0) with zero supports required!
    - Low-profile front lip (only 6.5mm overlap on outer rim) so the 6 o'clock CONDITIONS subdial
      and text are 100% visible and unobstructed!
    - Central bottom pass-through tunnel for the 5V USB power cable.
    """
    # Let's construct the Desk Stand from a sturdy base plate (Z = 0..4.0mm)
    # + Two sculpted side A-frame cradle ribs (at X = -52..-40mm and X = +40..+52mm)
    # + Front and rear crossbars with central USB cable opening!

    # Base footprint: X from -56 to +56mm (112mm wide), Y from -42 (front) to +52mm (back) (94mm deep)
    outer_base = sg.box(-56.0, -42.0, 56.0, 52.0).buffer(6.0)
    # Hollow center window + front/rear cable routing arch
    inner_cut = sg.box(-34.0, -30.0, 34.0, 38.0).buffer(4.0)
    cable_channel = sg.box(-12.0, -50.0, 12.0, 60.0)  # Leaves two connected side base pads joined by raised arches
    base_2d = outer_base.difference(inner_cut)

    m_base = extrude_shapely(base_2d, 0.0, 4.5)

    # Build the two side cradle walls in YZ profile, then extrude along X!
    # In YZ coordinates:
    #   Y = -36mm is front of stand, Y = +50mm is back of stand, Z = 0 is desk surface.
    #   Clock center when resting in stand at 14° tilt:
    #   Tilt angle alpha = 14° (clock face normal points forward (-Y) and slightly up (+Z)).
    #   Bottom edge of 190mm clock face sits at (Y_front = -28mm, Z_bottom = 12mm).
    #   Front lip wraps up to Z = 22mm in front of Y = -28mm.
    #    Clock face channel (3.2mm wide tilted at 14°) + Back compartment saddle (26.5mm wide tilted at 14°)
    #   Rear support backrest rises up to Z = 54mm at Y = +18mm and slopes down to (Y = +50mm, Z = 4.5mm).
    alpha = math.radians(14.0)
    sin_a, cos_a = math.sin(alpha), math.cos(alpha)

    # Origin of clock bottom rim in YZ:
    y0, z0 = -26.0, 11.0
    # Unit vectors along clock upward radial (+u) and rearward thickness (+v):
    uy, uz = sin_a, cos_a     # Up along clock dial (+14° tilted back)
    vy, vz = cos_a, -sin_a    # Rearward perpendicular to clock dial

    def pt_uv(u, v):
        return (y0 + u * uy + v * vy, z0 + u * uz + v * vz)

    # Side rib polygon in (Y, Z):
    p_front_bot = (-42.0, 0.0)
    p_front_top = pt_uv(11.0, -5.5)
    p_lip_tip   = pt_uv(11.0, -0.5)
    p_face_bot  = pt_uv(0.0, -0.5)
    p_face_rear = pt_uv(0.0, 3.2)
    # Step up slightly (6.4mm radial difference between R=95mm face and R=89.8mm cover = 5.2mm)
    p_cov_front = pt_uv(5.0, 3.2)
    p_cov_rear  = pt_uv(5.0, 29.0)
    p_back_top  = pt_uv(44.0, 29.0)
    p_back_peak = pt_uv(44.0, 39.0)
    p_rear_bot  = (52.0, 0.0)

    rib_yz_pts = [
        p_front_bot,
        (-42.0, 12.0),
        p_front_top,
        p_lip_tip,
        p_face_bot,
        p_face_rear,
        p_cov_front,
        p_cov_rear,
        p_back_top,
        p_back_peak,
        (52.0, 14.0),
        p_rear_bot,
    ]
    rib_yz = sg.Polygon(rib_yz_pts).buffer(0)

    # Extrude rib in local XY (which represents YZ), then swap axes to 3D (X, Y, Z)
    def extrude_yz_profile(poly_yz: sg.Polygon, x_min: float, x_max: float) -> m3d.Manifold:
        tm = trimesh.creation.extrude_polygon(poly_yz, height=(x_max - x_min))
        # Currently vertices are (Y, Z, X_local). Map to (X = X_local + x_min, Y = v[:,0], Z = v[:,1])
        v = np.asarray(tm.vertices, dtype=np.float32)
        new_v = np.column_stack([v[:, 2] + x_min, v[:, 0], v[:, 1]])
        tm.vertices = new_v
        tm.fix_normals()
        return trimesh_to_manifold(tm)

    m_rib_left = extrude_yz_profile(rib_yz, -56.0, -40.0)
    m_rib_right = extrude_yz_profile(rib_yz, 40.0, 56.0)

    # Add a sturdy rear cross-brace connecting left & right ribs from X = -40 to +40mm
    # with a 24mm wide × 12mm tall USB cable tunnel arch at the bottom center!
    brace_yz = sg.Polygon([
        pt_uv(5.0, 29.0),
        pt_uv(28.0, 29.0),
        pt_uv(28.0, 37.0),
        (38.0, 0.0),
        (12.0, 0.0),
    ]).buffer(0)
    m_brace = extrude_yz_profile(brace_yz, -40.0, 40.0)

    # Subtract central USB cable tunnel (X = -12..+12mm, Z = 0..11mm) through base & brace
    usb_tunnel_2d = sg.box(-12.0, -50.0, 12.0, 60.0)
    m_usb_cut = extrude_shapely(usb_tunnel_2d, -0.5, 10.5)

    m_stand = (m_base + m_rib_left + m_rib_right + m_brace) - m_usb_cut
    return manifold_to_trimesh(m_stand)


def main():
    out_dirs = [
        "/Users/raphaeldixon/surfclock/3d_models",
        "/Users/raphaeldixon/Downloads/weekday-clock-model_files",
    ]
    for d in out_dirs:
        os.makedirs(d, exist_ok=True)

    print("Building SurfClock 3D CAD models...")
    models = {
        "surfclock_face.stl": build_surfclock_face(classic_rings=True),
        "surfclock_face_minimal.stl": build_surfclock_face(classic_rings=False),
        "main_break_arm.stl": build_main_break_arm(),
        "conditions_arm.stl": build_conditions_arm(),
        "back_compartment_chassis.stl": build_back_compartment_chassis(),
        "back_compartment_cover.stl": build_back_compartment_cover(),
        "desk_stand.stl": build_desk_stand(),
    }

    for filename, mesh in models.items():
        print(f"  {filename:32s} | extents: {mesh.extents.round(2)} | watertight: {mesh.is_watertight} | faces: {len(mesh.faces)}")
        for d in out_dirs:
            mesh.export(os.path.join(d, filename))

    print("All STL models exported successfully!")


if __name__ == "__main__":
    main()
