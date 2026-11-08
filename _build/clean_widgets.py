# -*- coding: utf-8 -*-
"""Remove orphan widget objects left over from the old (face) rig."""
import bpy

BLEND = r"D:\Projects\UE5Anim\rigue5_rigified.blend"
bpy.ops.wm.open_mainfile(filepath=BLEND)

rig = bpy.data.objects['rig']
used = set()
for pb in rig.pose.bones:
    if pb.custom_shape:
        used.add(pb.custom_shape.name)
print("widgets in use:", len(used))

removed = 0
for o in list(bpy.data.objects):
    if o.name.startswith('WGT-') and o.name not in used:
        me = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if me and me.users == 0:
            bpy.data.meshes.remove(me)
        removed += 1
print("removed orphan widgets:", removed)
print("WGT objects left:", len([o for o in bpy.data.objects if o.name.startswith('WGT-')]))
print("meshes in file:", len(bpy.data.meshes))

bpy.ops.wm.save_as_mainfile(filepath=BLEND)
print("saved")
