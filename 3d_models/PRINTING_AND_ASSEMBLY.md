# SurfClock 3D Printable Hardware Guide

All 3D models are 100% watertight, 2-manifold solids engineered to print flat on any standard 200×200mm+ FDM print bed with **zero supports required**.

---

## 📦 Included Files

| File | Dimensions | Description |
| :--- | :--- | :--- |
| **`surfclock_face.stl`** | `190.0 × 190.0 × 2.6 mm` | Classic Sector Ring SurfClock Face (`0–1.6 mm` base disk + `1.6–2.6 mm` raised rings, 5 beaches, 6 o'clock `CONDITIONS` subdial `1–10` arc, center shaft hole at `(0,0)`, and conditions shaft hole at `(0,-54.0 mm)`). |
| **`surfclock_face_minimal.stl`** | `190.0 × 190.0 × 2.6 mm` | Optional Minimalist Open-Dial SurfClock Face (outer bezel ring + 5 beaches + 6 o'clock `CONDITIONS` subdial `1–10` arc + both shaft holes). |
| **`main_break_arm.stl`** | `16.0 × 78.7 × 7.5 mm` | Main Surf Break Indicator Hand. Press-fits **directly** onto the center `28BYJ-48` 5mm Double-D motor shaft. Includes stepped underside neodymium magnet pockets at `R = 22.0 mm` (primary datum) and `R = -10.8 mm` (tail). |
| **`conditions_arm.stl`** | `12.4 × 25.8 × 6.8 mm` | 6 O'Clock Conditions Subdial Needle. Press-fits **directly** onto the lower `28BYJ-48` 5mm Double-D motor shaft at `(0,-54.0 mm)`. Includes stepped underside neodymium magnet pocket at `R = 14.5 mm`. |
| **`back_compartment_chassis.stl`** | `174.0 × 174.0 × 12.0 mm` | Rear Motor & Electronics Carrier Chassis. Mounts behind the clock face and holds both `28BYJ-48` steppers, both `HW-477` / `A3144` Hall sensors, `2× ULN2003` driver boards, and the `Freenove ESP32-S3`. |
| **`back_compartment_cover.stl`** | `179.6 × 179.6 × 24.5 mm` | Large Clip-On Back Compartment Lid. Snaps over the chassis via 4 perimeter flex-clips to hide all cables & electronics. Features a recessed keyhole wall-hanger at 12 o'clock so the clock sits completely flat against the wall, plus a 6 o'clock USB cable exit. |
| **`desk_stand.stl`** | `124.0 × 106.0 × 46.7 mm` | Contoured 14° Desktop Cradle Stand. Holds both the 190mm clock face and clip-on back compartment with full visibility of the 6 o'clock Conditions gauge and a bottom USB cable routing tunnel. |
| **`surfclock_complete.blend`** | Blender 5.2 Scene | Complete Blender project containing all assembled parts and two-tone materials. |

---

## 🖨️ Slicing & Print Instructions

1. **Clock Face (`surfclock_face.stl` or `surfclock_face_minimal.stl`)**:
   - **Layer Height**: `0.20 mm`
   - **Color Change (`M600`)**: Add a filament swap at **`Z = 1.80 mm`** (Layer 9). Print layers `0.0–1.6 mm` in **Matte White** and layers `1.8–2.6 mm` in **Matte Black / Charcoal**.
2. **Arms (`main_break_arm.stl` & `conditions_arm.stl`)**:
   - Print flat with `Z = 0` on the build plate (`0.16 mm` or `0.20 mm` layer height, 3 perimeters). No supports required.
3. **Back Compartment (`back_compartment_chassis.stl` & `back_compartment_cover.stl`)**:
   - Print both flat on their large circular faces (`Z = 0` on bed, `0.20 mm` layer height, 15–20% gyroid/grid infill).
4. **Desk Stand (`desk_stand.stl`)**:
   - Print flat on its base (`Z = 0` on bed, `0.20 mm` layer height, 3 perimeters, 20% infill).

---

## 🔧 Hardware Assembly Summary

1. **Magnets**:
   - Press a `5×1.5 mm` / `4×2 mm` (outer step) or `3×1 mm` / `3×2 mm` (inner step) neodymium disc magnet into the underside pocket of **`main_break_arm.stl`** (`R = 22.0 mm`) and **`conditions_arm.stl`** (`R = 14.5 mm`).
2. **Motors & Hall Sensors**:
   - Fasten the two `28BYJ-48` stepper motors into the two cradles of **`back_compartment_chassis.stl`** using M3×8mm screws (`(0,0)` for Main Break and `(0,-54.0 mm)` for Conditions Gauge).
   - Slot the two `HW-477` / `A3144` Hall-effect sensors into their dedicated guide frames at `(0, +22.0 mm)` (12 o'clock datum) and `(-14.5, -54.0 mm)` (Rating 1 datum).
3. **Electronics & Cable Management**:
   - Mount the `2× ULN2003` boards on the left M3 standoffs and the `Freenove ESP32-S3` on the right M3 standoffs.
   - Route the USB-C power cable through the 6 o'clock bottom notch, tuck excess jumper wires behind the internal cable hooks, and snap **`back_compartment_cover.stl`** onto the chassis rim.
4. **Direct Arm Installation**:
   - Press **`main_break_arm.stl`** and **`conditions_arm.stl`** directly onto the 5mm Double-D flatted shafts protruding through the front of **`surfclock_face.stl`**.
