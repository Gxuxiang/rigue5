# -*- coding: utf-8 -*-
"""Dev test: measure IK elbow/knee deviation from captured joints."""
import json
import os
import runpy

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
char = runpy.run_path(os.path.join(HERE, 'character_tools.py'), run_name='limb_char')
rig = bpy.data.objects['rig']
bpy.context.scene.character_pose_ground = False   # 只比较相对肢体位置


def reset():
    for pb in rig.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()


for key in ('kick', 'stance', 'ballet'):
    path = os.path.join(os.environ['TEMP'], 'pose_%s.json' % key)
    payload = json.load(open(path, encoding='utf-8'))
    reset()
    targets = char['_pose_apply_payload'](rig, payload, bpy.context.scene)
    kp, vis = char['_pose_payload_arrays'](
        payload, mirror=False, use_depth=0.7)
    rest = char['_pose_rest_metrics'](rig)
    r_body, hip_cap, _ = char['_pose_body_frame'](kp, vis, rest)
    scale, shift = targets['scale'], targets['shift']

    def mapped(i):
        return rest['H0'] + shift + (r_body @ (Vector(kp[i]) - hip_cap)) * scale

    errs = {
        'L_elbow': (rig.pose.bones['DEF-forearm.L'].matrix.to_translation()
                    - mapped(7)).length,
        'R_elbow': (rig.pose.bones['DEF-forearm.R'].matrix.to_translation()
                    - mapped(8)).length,
        'L_knee': (rig.pose.bones['DEF-shin.L'].matrix.to_translation()
                   - mapped(11)).length,
        'R_knee': (rig.pose.bones['DEF-shin.R'].matrix.to_translation()
                   - mapped(12)).length,
    }
    print(key, {k: round(v, 3) for k, v in errs.items()})
reset()
