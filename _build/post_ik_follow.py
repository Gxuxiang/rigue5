# -*- coding: utf-8 -*-
"""让手臂 IK 控制器跟着上身走。

Rigify 默认把手臂 IK 控制器挂在 root 上（世界空间），所以弯脊椎/躯干时手会留在
原地，控制器看起来"跑偏"。这里把手 IK 控制骨(h₁and_ik.L/R)的父级改成肩骨
(h₃shoulder.L/R)，保持位置不变 —— 于是手臂和控制器会跟着肩膀一起动，脚仍然踩在
root 上不动。
"""
import bpy

BLEND = r"D:\Projects\UE5Anim\rigue5_rigified.blend"


def align_hand_controls(rig, ue):
    bones = rig.pose.bones
    for side in ('L', 'R'):
        suffix = '.' + side
        hand = bones['hand_ik' + suffix]
        forearm = bones['MCH-forearm_ik' + suffix]
        mechanism = bones['MCH-upper_arm_ik_target' + suffix]
        old_limit = mechanism.constraints.get('Limit Distance')
        if old_limit is not None:
            # Clamp the visible controller and the solver input together.
            limit = hand.constraints.new('LIMIT_DISTANCE')
            limit.name = 'Arm Reach'
            limit.target = rig
            limit.subtarget = old_limit.subtarget
            limit.space_object = rig
            limit.space_subtarget = old_limit.space_subtarget
            limit.owner_space = old_limit.owner_space
            limit.target_space = old_limit.target_space
            limit.limit_mode = old_limit.limit_mode
            limit.distance = bones['upper_arm_ik' + suffix].bone.length + forearm.bone.length
            limit.use_transform_limit = True
            old_limit.driver_remove('influence')
            mechanism.constraints.remove(old_limit)

            stretch_path = bones['upper_arm_parent' + suffix].path_from_id() + '["IK_Stretch"]'
            driven = [(limit, 'influence', '1 - stretch')]
            for constraint in forearm.constraints:
                if constraint.type == 'IK':
                    driven.append((constraint, 'use_stretch', 'stretch > 0'))
            for constraint, prop, expression in driven:
                driver = constraint.driver_add(prop).driver
                variable = driver.variables.new()
                variable.name = 'stretch'
                variable.targets[0].id = rig
                variable.targets[0].data_path = stretch_path
                driver.expression = expression

        # UE must also follow the solved elbow and wrist when stretch is enabled.
        for ue_name, rig_name in (('lowerarm', 'forearm'), ('hand', 'hand')):
            bone = ue.pose.bones[ue_name + '_' + side.lower()]
            target = 'DEF-' + rig_name + suffix
            name = 'RTG-loc:' + target
            location = bone.constraints.get(name)
            if location is None:
                location = bone.constraints.new('COPY_LOCATION')
                location.name = name
            location.target = rig
            location.subtarget = target

        # Draw each curl control along its proximal segment. Keep the original
        # master bone and its scale-driven curl behavior.
        for finger in ('f_index', 'f_middle', 'f_ring', 'f_pinky', 'thumb'):
            proximal = bones['ORG-' + finger + '.01' + suffix]
            master = bones[finger + '.01_master' + suffix]
            length = proximal.bone.length
            master.custom_shape_transform = proximal
            master.use_custom_shape_bone_size = False
            master.custom_shape_scale_xyz = (
                (-2 if side == 'R' else 2) * length, 0.8 * length, length
            )


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
    align_hand_controls(rig, bpy.data.objects['root'])
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


if __name__ == '__main__':
    main()
