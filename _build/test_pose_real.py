# -*- coding: utf-8 -*-
"""Dev test: apply a real pose payload and render a preview.

Not part of the deliverable. Run:
  blender -b --factory-startup --disable-autoexec rigue5_rigified.blend \
    --python _build/test_pose_real.py -- <payload.json> <out.png>
"""
import json
import math
import os
import runpy
import sys

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'character_tools.py')

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
payload_path = argv[0] if argv else ''
out_path = argv[1] if len(argv) > 1 else os.path.join(
    os.environ.get('TEMP', '.'), 'pose_capture_test.png')

mod = runpy.run_path(SRC, run_name='pose_real_test')
rig = bpy.data.objects['rig']
scene = bpy.context.scene
payload = json.load(open(payload_path, encoding='utf-8'))

for pb in rig.pose.bones:
    pb.matrix_basis = Matrix.Identity(4)
bpy.context.view_layer.update()

targets = mod['_pose_apply_payload'](rig, payload, scene)
print('[pose] backend', payload.get('backend'))
print('[pose] scale %.4f shift %s' % (targets['scale'], list(targets['shift'])))
print('[pose] warnings', targets.get('warnings'))
_rest = mod['_pose_rest_metrics'](rig)
_tq = targets['torso'].to_quaternion()
_rq = _rest['torso_rest'].to_quaternion()
print('[pose] torso delta %.2f deg'
      % math.degrees(_tq.rotation_difference(_rq).angle))
_hq = targets.get('head_rotation')
if _hq is not None:
    _hrq = rig.data.bones['head'].matrix_local.to_quaternion()
    print('[pose] head delta %.2f deg'
          % math.degrees(_hq.rotation_difference(_hrq).angle))
_nq = targets.get('neck_rotation')
if _nq is not None:
    _nrq = rig.data.bones['neck'].matrix_local.to_quaternion()
    print('[pose] neck delta %.2f deg'
          % math.degrees(_nq.rotation_difference(_nrq).angle))
for S in ('L', 'R'):
    if S in targets['hands']:
        print('[pose] hand_%s' % S, list(targets['hands'][S].to_translation()))
    if S in targets['feet']:
        print('[pose] foot_%s' % S, list(targets['feet'][S].to_translation()))
print('[pose] hand_ik.L actual',
      list(rig.pose.bones['hand_ik.L'].matrix.to_translation()))
print('[pose] hip center actual',
      list(((rig.pose.bones['DEF-thigh.L'].matrix.to_translation()
             + rig.pose.bones['DEF-thigh.R'].matrix.to_translation()) * 0.5)))

# camera + workbench preview
cam_data = bpy.data.cameras.new('PoseCam')
cam = bpy.data.objects.new('PoseCam', cam_data)
scene.collection.objects.link(cam)
cam.location = (0.0, -3.8, 1.5)
direction = Vector((0.0, 0.0, 0.95)) - cam.location
cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
cam_data.lens = 50
scene.camera = cam

for ob in bpy.data.objects:
    if ob.type == 'ARMATURE' or ob.name.startswith('WGT-'):
        ob.hide_render = True

scene.render.engine = 'BLENDER_WORKBENCH'
scene.display.shading.light = 'STUDIO'
scene.display.shading.color_type = 'MATERIAL'
scene.display.shading.show_shadows = True
scene.render.resolution_x = 640
scene.render.resolution_y = 800
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = out_path
scene.world.color = (0.08, 0.08, 0.08)
bpy.ops.render.render(write_still=True)
print('[pose] rendered', out_path)
