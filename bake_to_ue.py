# -*- coding: utf-8 -*-
"""把 Rigify 控制器的动作烘焙到 UE5 骨架（root）上，得到可以直接导出 UE 的干净文件。

用法
----
在 Blender 里：文本编辑器 → 打开本文件 → Run Script。
脚本会：
  1. 按场景帧范围，把 rig 的最终姿势“视觉烘焙”成 root 骨骼的关键帧；
  2. 删除 root 上所有 RTG-* 约束（动画已经写进关键帧，不再需要它们）；
  3. 把结果另存为  <原文件名>_baked.blend ，不覆盖当前文件。

命令行（无界面）也可以：
  blender -b rigue5_rigified.blend --python bake_to_ue.py
"""
import bpy
import os

ROOT_ARM = 'root'
RIG = 'rig'


def bake_pose_to_ue(root=None, rig=None, clear_helpers=True):
    scene = bpy.context.scene
    root = root or bpy.data.objects.get(ROOT_ARM)
    rig = rig or bpy.data.objects.get(RIG)
    if root is None:
        raise RuntimeError('找不到 UE 骨架对象 root')

    # 让烘焙后的动作是“干净”的：先把已有动画清掉，避免叠加
    if root.animation_data and root.animation_data.action:
        root.animation_data.action = None

    for o in bpy.data.objects:
        o.select_set(False)
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='SELECT')
    bpy.ops.pose.transforms_clear()

    bpy.ops.nla.bake(
        frame_start=scene.frame_start,
        frame_end=scene.frame_end,
        step=1,
        only_selected=True,
        visual_keying=True,
        clear_constraints=True,
        clear_parents=False,
        use_current_action=True,
        clean_curves=False,
        bake_types={'POSE'},
    )
    bpy.ops.object.mode_set(mode='OBJECT')

    # 约束已经烘进关键帧，删掉 RTG helper 物体让文件保持干净
    if clear_helpers:
        for o in list(bpy.data.objects):
            if o.name.startswith('RTG_') and o.type == 'EMPTY':
                bpy.data.objects.remove(o, do_unlink=True)
        coll = bpy.data.collections.get('RTG_CORRECTIVES')
        if coll:
            bpy.data.collections.remove(coll)

    return root


def main():
    path = bpy.data.filepath
    bake_pose_to_ue()
    out = os.path.splitext(path)[0] + '_baked.blend'
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print('[bake] 已烘焙并保存：', out)


if __name__ == '__main__':
    main()
