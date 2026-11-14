# -*- coding: utf-8 -*-
"""Dev test: exercise the Blender-side async pose job without the UI."""
import json
import os
import sys
import time

import bpy

mod = bpy.data.texts['character_tools.py'].as_module()
rig = bpy.data.objects.get('rig')
bpy.context.view_layer.objects.active = rig
rig.select_set(True)

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
if argv:
    bpy.context.scene.character_pose_backend = argv[0]
image = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'preview', '03_pose_three_quarter.png')
if len(argv) > 1:
    image = argv[1]
print('[flow] backend', mod._pose_choose_backend(bpy.context.scene))
print('[flow] status', mod._pose_env_status(bpy.context.scene)['label'])
mod._pose_start_job(bpy.context, 'image', image)
t0 = time.time()
last_stage = None
while mod._POSE_JOBS and time.time() - t0 < 300:
    mod._pose_poll_jobs()
    stage = bpy.context.scene.character_pose_stage
    if stage != last_stage:
        print('[flow] stage:', stage,
              'progress=%.2f' % bpy.context.scene.character_pose_progress)
        last_stage = stage
    time.sleep(0.3)
print('[flow] message:', bpy.context.scene.character_pose_message)
print('[flow] jobs left:', len(mod._POSE_JOBS))
print('[flow] hand_ik.L:', [round(v, 4) for v in
                            rig.pose.bones['hand_ik.L'].matrix.to_translation()])
print('[flow] foot_ik.L:', [round(v, 4) for v in
                            rig.pose.bones['foot_ik.L'].matrix.to_translation()])
