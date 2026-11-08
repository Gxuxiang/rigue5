# -*- coding: utf-8 -*-
"""Rebuild rigue5_rigified.blend from rigue5.blend, in one go.

blender -b --factory-startup --python _build/build_all.py
"""
import bpy
import os
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))

STEPS = ['build_rig.py',      # fit metarig to the Manny, generate rig, retarget
         'finalize.py',       # collections, readme, viewport defaults, cleanup
         'clean_widgets.py',  # drop orphan face widgets from the old rig
         'post_ik_follow.py',  # arm IK controls ride on the shoulders
         'add_character_ui.py']  # 「复制角色」按钮写进 N 面板

for step in STEPS:
    print("=== %s ===" % step)
    runpy.run_path(os.path.join(HERE, step), run_name='__main__')
