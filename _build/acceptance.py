# -*- coding: utf-8 -*-
"""Final acceptance check on the delivered blend."""
import bpy, math

BLEND = r"D:\Projects\UE5Anim\rigue5_rigified.blend"
bpy.ops.wm.open_mainfile(filepath=BLEND)

ue = bpy.data.objects['root']
rig = bpy.data.objects['rig']
mesh = bpy.data.objects['SKM_Manny']

print("objects:", [(o.name, o.type) for o in bpy.data.objects if o.type != 'EMPTY'])
print("collections:", [c.name for c in bpy.data.collections])
print("rig bones:", len(rig.data.bones), "| metarig bones:", len(bpy.data.objects['metarig'].data.bones))
print("UE bones:", len(ue.data.bones), "| vgroups:", len(mesh.vertex_groups))
print("armature modifier ->", [m.object.name for m in mesh.modifiers if m.type == 'ARMATURE'])
print("constraints on root:", sum(len(pb.constraints) for pb in ue.pose.bones))
print("helpers:", len([o for o in bpy.data.objects if o.name.startswith('RTG_')]))
print("actions:", [a.name for a in bpy.data.actions])
print("texts:", [t.name for t in bpy.data.texts])


def coords():
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    ob = mesh.evaluated_get(dg)
    me = ob.to_mesh()
    c = [ob.matrix_world @ v.co for v in me.vertices]
    ob.to_mesh_clear()
    return c


rest = coords()
static = [mesh.matrix_world @ v.co for v in mesh.data.vertices]
print("rest pose deviation from bind pose: %.7f m" % max((a - b).length for a, b in zip(rest, static)))

R = rig.pose.bones
R['hand_ik.L'].location = (0, 0.10, 0.30)
R['foot_ik.R'].location = (0, 0, 0.12)
R['torso'].rotation_mode = 'XYZ'
R['torso'].rotation_euler = (0, 0, math.radians(15))
bpy.context.view_layer.update()
posed = coords()
moved = [i for i, (a, b) in enumerate(zip(rest, posed)) if (a - b).length > 0.01]
print("posing the rig moves %d / %d vertices (max %.3f m)"
      % (len(moved), len(rest), max((a - b).length for a, b in zip(rest, posed))))

# back to rest
for pb in R:
    pb.location = (0, 0, 0)
    pb.rotation_euler = (0, 0, 0)
    pb.rotation_quaternion = (1, 0, 0, 0)
bpy.context.view_layer.update()
back = coords()
print("reset deviation: %.7f m" % max((a - b).length for a, b in zip(rest, back)))
print("OK")
