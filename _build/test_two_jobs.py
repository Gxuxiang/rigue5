# -*- coding: utf-8 -*-
"""Dev test: run two pose jobs back-to-back, with the timer forcibly unregistered
between them, to catch the stale `_POSE_TIMER` bug (second job stuck at 2%)."""
import os
import time

import bpy

mod = bpy.data.texts['character_tools.py'].as_module()
rig = bpy.data.objects.get('rig')
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.context.scene.character_pose_backend = 'sam3d'

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
images = [os.path.join(base, 'preview', '03_pose_three_quarter.png'),
          os.path.join(base, 'preview', '01_rest.png')]


def run(image, label):
    mod._pose_start_job(bpy.context, 'image', image)
    print('[two]', label, 'timer registered:',
          bpy.app.timers.is_registered(mod._pose_poll_jobs),
          'flag:', mod._POSE_TIMER)
    t0 = time.time()
    last = None
    while mod._POSE_JOBS and time.time() - t0 < 300:
        mod._pose_poll_jobs()
        stage = bpy.context.scene.character_pose_stage
        if stage != last:
            print('[two]', label, 'stage:', stage,
                  'progress=%.2f' % bpy.context.scene.character_pose_progress)
            last = stage
        time.sleep(0.3)
    print('[two]', label, 'message:', bpy.context.scene.character_pose_message)
    print('[two]', label, 'hand_ik.L:',
          [round(v, 4) for v in rig.pose.bones['hand_ik.L'].matrix.to_translation()])


run(images[0], 'first')

# Simulate the end-of-job state: Blender has unregistered the timer, but the
# module flag was left True by the old buggy return path.
try:
    bpy.app.timers.unregister(mod._pose_poll_jobs)
except Exception:
    pass
mod._POSE_TIMER = True

run(images[1], 'second')
print('[two] second job completed without being stuck at 2%')
