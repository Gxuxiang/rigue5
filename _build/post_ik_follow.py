# -*- coding: utf-8 -*-
"""让手臂 IK 控制器跟着上身走。

Rigify 默认把手臂 IK 控制器挂在 root 上（世界空间），所以弯脊椎/躯干时手会留在
原地，控制器看起来"跑偏"。这里把手 IK 控制骨(h₁and_ik.L/R)的父级改成肩骨
(h₃shoulder.L/R)，保持位置不变 —— 于是手臂和控制器会跟着肩膀一起动，脚仍然踩在
root 上不动。
"""
import bpy

BLEND = r"D:\Projects\UE5Anim\rigue5_rigified.blend"


def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    rig = bpy.data.objects['rig']
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    ebs = rig.data.edit_bones
    for side in ('L', 'R'):
        eb = ebs['hand_ik.' + side]
        if eb.parent and eb.parent.name == 'shoulder.' + side:
            print("already parented:", eb.name)
            continue
        head, tail, roll = eb.head.copy(), eb.tail.copy(), eb.roll
        eb.parent = ebs['shoulder.' + side]
        eb.use_connect = False
        eb.head, eb.tail, eb.roll = head, tail, roll
        print("reparented %s -> %s" % (eb.name, eb.parent.name))
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.update()

    for side in ('L', 'R'):
        pb = rig.pose.bones['hand_ik.' + side]
        now = (rig.matrix_world @ pb.matrix).to_translation()
        rest = (rig.matrix_world @ pb.bone.matrix_local).to_translation()
        print("hand_ik.%s rest error %.6f" % (side, (now - rest).length))

    text = bpy.data.texts.get('README_rigify_UE5')
    if text and 'PATCH: IK-follow' not in text.as_string():
        text.write("\n[PATCH] 手臂 IK 控制器(hand_ik.L/R)已挂到肩骨下面：\n"
                   "        弯脊椎/弯腰时手臂和控制器跟着上身走，不再留在原地；\n"
                   "        脚仍然踩在 root 上不动。想回到原来的世界空间手，\n"
                   "        用 FK（IK_FK=1）或直接移动 hand_ik 控制器。\n")

    bpy.ops.wm.save_as_mainfile(filepath=BLEND)
    print("saved")


main()
