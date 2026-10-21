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
    obj.data.materials.append(mat_white)
    obj.data.materials.append(mat_charcoal)
    verts = obj.data.vertices
    for poly in obj.data.polygons:
        max_z = max(verts[v_idx].co.z for v_idx in poly.vertices)
        min_z = min(verts[v_idx].co.z for v_idx in poly.vertices)
        if max_z > z_threshold and min_z >= 1.55:
            poly.material_index = 1
        else:
            poly.material_index = 0

face = import_stl(os.path.join(models_dir, "surfclock_face.stl"), "surfclock_face")
assign_two_tone_dial_materials(face)

# Center Main Break Arm: Rotated to 180° (pointing straight DOWN past 6 o'clock!)
main_arm = import_stl(os.path.join(models_dir, "main_break_arm.stl"), "main_break_arm")
main_arm.data.materials.append(mat_charcoal)
main_arm.location = (0.0, 0.0, 2.6)
main_arm.rotation_euler = (0.0, 0.0, math.radians(180.0))

# Conditions Arm at (0, -54.0): Rotated to 0° (pointing straight UP toward the center!)
cond_arm = import_stl(os.path.join(models_dir, "conditions_arm.stl"), "conditions_arm")
cond_arm.data.materials.append(mat_blue)
cond_arm.location = (0.0, -54.0, 2.6)
cond_arm.rotation_euler = (0.0, 0.0, 0.0)

chassis = import_stl(os.path.join(models_dir, "back_compartment_chassis.stl"), "back_compartment_chassis")
chassis.data.materials.append(mat_chassis)
chassis.rotation_euler = (math.radians(180.0), 0.0, 0.0)
chassis.location = (0.0, 0.0, 0.0)

cover = import_stl(os.path.join(models_dir, "back_compartment_cover.stl"), "back_compartment_cover")
cover.data.materials.append(mat_cover)
cover.location = (0.0, 0.0, -24.5)

face_min = import_stl(os.path.join(models_dir, "surfclock_face_minimal.stl"), "surfclock_face_minimal")
assign_two_tone_dial_materials(face_min)
face_min.location = (210.0, 0.0, 0.0)

stand = import_stl(os.path.join(models_dir, "desk_stand.stl"), "desk_stand")
stand.data.materials.append(mat_stand)
stand.location = (-185.0, -20.0, 0.0)

world = bpy.data.worlds.new("StudioWorld")
bpy.context.scene.world = world
bg = world.node_tree.nodes.get("Background")
if bg:
    bg.inputs[0].default_value = (0.88, 0.90, 0.93, 1.0)
    bg.inputs[1].default_value = 0.95

def add_sun(name, energy, rot_deg):
    ldata = bpy.data.lights.new(name=name, type='SUN')
    ldata.energy = energy
    lobj = bpy.data.objects.new(name=name, object_data=ldata)
    bpy.context.collection.objects.link(lobj)
    lobj.rotation_euler = tuple(math.radians(a) for a in rot_deg)
    return lobj

add_sun("KeySun", 3.4, (38, 15, -30))
add_sun("FillSun", 1.5, (-25, -20, 50))

# Camera: Close-up angled view specifically showing the big hand passing OVER the conditions hand at 6 o'clock!
cam_data = bpy.data.cameras.new(name="ClearanceCam")
cam_data.lens = 75.0
cam_obj = bpy.data.objects.new(name="ClearanceCam", object_data=cam_data)
bpy.context.collection.objects.link(cam_obj)
bpy.context.scene.camera = cam_obj

# Aim camera right at the overlap region (0, -45, 5) from an oblique side angle
cam_obj.location = (65.0, -115.0, 52.0)
cam_obj.rotation_euler = (math.radians(58.0), 0.0, math.radians(45.0))

scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = 1600
scene.render.resolution_y = 1050
scene.render.filepath = os.path.join(render_dir, "surfclock_arm_overpass_clearance_render.png")
bpy.ops.render.render(write_still=True)

# Save .blend
bpy.ops.wm.save_as_mainfile(filepath=out_blend_1)
bpy.ops.wm.save_as_mainfile(filepath=out_blend_2)

# Export GLB and USDZ
bpy.ops.export_scene.gltf(filepath="/Users/raphaeldixon/surfclock/3d_models/surfclock_complete.glb", export_format='GLB')
bpy.ops.export_scene.gltf(filepath="/Users/raphaeldixon/Downloads/weekday-clock-model_files/surfclock_complete.glb", export_format='GLB')
bpy.ops.wm.usd_export(filepath="/Users/raphaeldixon/surfclock/3d_models/surfclock_complete.usdz")
bpy.ops.wm.usd_export(filepath="/Users/raphaeldixon/Downloads/weekday-clock-model_files/surfclock_complete.usdz")

print("Rendered arm overpass clearance demonstration and updated 3D exports!")
