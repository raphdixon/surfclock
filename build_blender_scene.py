import bpy
import os
import math

bpy.ops.wm.read_factory_settings(use_empty=True)

models_dir = "/Users/raphaeldixon/surfclock/3d_models"
out_blend_1 = "/Users/raphaeldixon/surfclock/3d_models/surfclock_complete.blend"
out_blend_2 = "/Users/raphaeldixon/Downloads/weekday-clock-model_files/surfclock_complete.blend"
render_dir = "/Users/raphaeldixon/.gemini/jetski/brain/fb2a2352-c83d-4e41-bdc9-c00049ebbce1"

def import_stl(filepath, name):
    bpy.ops.wm.stl_import(filepath=filepath)
    obj = bpy.context.selected_objects[0]
    obj.name = name
    return obj

def make_material(name, rgba, roughness=0.35, metallic=0.0):
    mat = bpy.data.materials.new(name=name)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
    return mat

mat_white = make_material("Dial_White", (0.97, 0.97, 0.98, 1.0), roughness=0.25)
mat_charcoal = make_material("Charcoal_Black", (0.04, 0.05, 0.07, 1.0), roughness=0.25)
mat_blue = make_material("Surf_Blue", (0.01, 0.48, 0.78, 1.0), roughness=0.22)
mat_chassis = make_material("Chassis_TealGrey", (0.14, 0.22, 0.26, 1.0), roughness=0.35)
mat_cover = make_material("Cover_Slate", (0.10, 0.12, 0.15, 1.0), roughness=0.32)
mat_stand = make_material("Stand_WarmCharcoal", (0.18, 0.20, 0.24, 1.0), roughness=0.30)

def assign_two_tone_dial_materials(obj, z_threshold=1.61):
    obj.data.materials.clear()
    obj.data.materials.append(mat_white)     # Slot 0: Base White (0.0 - 1.6mm)
    obj.data.materials.append(mat_charcoal)  # Slot 1: Raised Relief Black (1.6 - 2.6mm)
    verts = obj.data.vertices
    for poly in obj.data.polygons:
        # Check max Z of vertices in this triangle
        max_z = max(verts[v_idx].co.z for v_idx in poly.vertices)
        min_z = min(verts[v_idx].co.z for v_idx in poly.vertices)
        if max_z > z_threshold and min_z >= 1.55:
            poly.material_index = 1
        else:
            poly.material_index = 0

# 1. Import Assembled SurfClock (Center)
face = import_stl(os.path.join(models_dir, "surfclock_face.stl"), "1_SurfClock_Face")
assign_two_tone_dial_materials(face)

main_arm = import_stl(os.path.join(models_dir, "main_break_arm.stl"), "2_Main_Break_Arm")
main_arm.data.materials.append(mat_charcoal)
main_arm.location = (0.0, 0.0, 2.6)
main_arm.rotation_euler = (0.0, 0.0, math.radians(-60.0))  # Pointing to Dee Why (60°)

cond_arm = import_stl(os.path.join(models_dir, "conditions_arm.stl"), "3_Conditions_Arm")
cond_arm.data.materials.append(mat_blue)
cond_arm.location = (0.0, -54.0, 2.6)
cond_arm.rotation_euler = (0.0, 0.0, math.radians(-35.0))  # Pointing to Rating ~7.5

chassis = import_stl(os.path.join(models_dir, "back_compartment_chassis.stl"), "4_Back_Compartment_Chassis")
chassis.data.materials.append(mat_chassis)
chassis.rotation_euler = (math.radians(180.0), 0.0, 0.0)
chassis.location = (0.0, 0.0, 0.0)

cover = import_stl(os.path.join(models_dir, "back_compartment_cover.stl"), "5_Back_Compartment_Cover")
cover.data.materials.append(mat_cover)
cover.location = (0.0, 0.0, -24.5)

# 2. Import Minimalist Dial Edition on Right (+210mm X)
face_min = import_stl(os.path.join(models_dir, "surfclock_face_minimal.stl"), "1b_SurfClock_Face_Minimal")
assign_two_tone_dial_materials(face_min)
face_min.location = (210.0, 0.0, 0.0)

# 3. Import Desk Stand on Left (-185mm X)
stand = import_stl(os.path.join(models_dir, "desk_stand.stl"), "6_Desk_Stand")
stand.data.materials.append(mat_stand)
stand.location = (-185.0, -20.0, 0.0)

# Setup Studio Lighting & World
world = bpy.data.worlds.new("StudioWorld")
bpy.context.scene.world = world
bg = world.node_tree.nodes.get("Background")
if bg:
    bg.inputs[0].default_value = (0.88, 0.90, 0.93, 1.0)
    bg.inputs[1].default_value = 0.9

def add_sun(name, energy, rot_deg):
    ldata = bpy.data.lights.new(name=name, type='SUN')
    ldata.energy = energy
    lobj = bpy.data.objects.new(name=name, object_data=ldata)
    bpy.context.collection.objects.link(lobj)
    lobj.rotation_euler = tuple(math.radians(a) for a in rot_deg)
    return lobj

add_sun("KeySun", 3.2, (35, 18, -25))
add_sun("FillSun", 1.4, (-30, -25, 45))

# Camera 1: Front/Angled Showcase
cam_data = bpy.data.cameras.new(name="StudioCam")
cam_data.lens = 45.0
cam_obj = bpy.data.objects.new(name="StudioCam", object_data=cam_data)
bpy.context.collection.objects.link(cam_obj)
bpy.context.scene.camera = cam_obj
cam_obj.location = (10.0, -230.0, 490.0)
cam_obj.rotation_euler = (math.radians(24.0), 0.0, 0.0)

scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = 1800
scene.render.resolution_y = 1050
scene.render.filepath = os.path.join(render_dir, "surfclock_3d_render.png")
bpy.ops.render.render(write_still=True)

# Save the organized .blend project before moving parts for the exploded back render
bpy.ops.wm.save_as_mainfile(filepath=out_blend_1)
bpy.ops.wm.save_as_mainfile(filepath=out_blend_2)

# Render 2: Rear Compartment, Chassis, and Arm Undersides Showcase
chassis.rotation_euler = (0.0, 0.0, 0.0)
chassis.location = (-105.0, 0.0, 0.0)

cover.rotation_euler = (0.0, 0.0, 0.0)
cover.location = (105.0, 0.0, 0.0)

# Flip arms upside down in center so their Double-D sockets and magnet pockets face the camera!
main_arm.rotation_euler = (math.radians(180.0), 0.0, 0.0)
main_arm.location = (-15.0, -110.0, 8.0)

cond_arm.rotation_euler = (math.radians(180.0), 0.0, 0.0)
cond_arm.location = (25.0, -110.0, 8.0)

face.hide_render = True
face_min.hide_render = True
stand.location = (0.0, 115.0, 0.0)

cam_obj.location = (0.0, -210.0, 440.0)
cam_obj.rotation_euler = (math.radians(24.0), 0.0, 0.0)
scene.render.filepath = os.path.join(render_dir, "surfclock_rear_and_internals_render.png")
bpy.ops.render.render(write_still=True)
print("Rendered both front and rear showcase views!")
