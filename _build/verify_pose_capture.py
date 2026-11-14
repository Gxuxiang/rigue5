# -*- coding: utf-8 -*-
r"""Headless verification for the pose-capture math.

Run:
  blender -b --factory-startup --disable-autoexec \
    D:\Projects\rigue5-main\rigue5_rigified.blend \
    --python D:\Projects\rigue5-main\_build\verify_pose_capture.py

It never saves the blend. Exercises the synthetic MHR70 -> Rigify mapping,
the apply path, mirror/missing/ground handling, and B_rig discovery.
"""

import math
import os
import runpy
import sys
import traceback

import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'character_tools.py')

FAILS = []
PASSES = []


def check(name, cond, detail=''):
    if cond:
        PASSES.append(name)
        print('[PASS] %s %s' % (name, detail))
    else:
        FAILS.append(name + (' ' + detail if detail else ''))
        print('[FAIL] %s %s' % (name, detail))


def close(a, b, eps=1e-4):
    return (Vector(a) - Vector(b)).length <= eps


def build_rest_keypoints(rig, posed=False):
    b = rig.data.bones
    pb = rig.pose.bones

    def head(name):
        if posed:
            return pb[name].head.copy()
        return b[name].head_local.copy()

    def tail(name):
        if posed:
            return pb[name].tail.copy()
        return b[name].tail_local.copy()

    kp = [[0.0, 0.0, 0.0] for _ in range(70)]

    def put(i, v):
        # Blender (X, Y, Z) -> 识别坐标 (x 右, y 下, z 前)
        kp[i] = [float(v.x), float(-v.z), float(v.y)]

    head_joint = head('DEF-spine.006')
    put(0, head_joint + Vector((0.0, -0.09, 0.0)))        # nose
    put(1, head_joint + Vector((0.03, -0.08, 0.0)))       # left eye
    put(2, head_joint + Vector((-0.03, -0.08, 0.0)))      # right eye
    put(3, head_joint + Vector((0.07, 0.0, 0.0)))         # left ear
    put(4, head_joint + Vector((-0.07, 0.0, 0.0)))        # right ear

    for S, base in (('L', 5), ('R', 6)):
        s = 'L' if S == 'L' else 'R'
        put(base, head('DEF-upper_arm.' + S))
        put(base + 2, head('DEF-forearm.' + S))
        put(62 if S == 'L' else 41, head('DEF-hand.' + S))
        # hand landmarks
        if S == 'L':
            put(53, head('f_middle.01.L'))                 # middle MCP
            put(49, head('f_index.01.L'))                  # index MCP
            put(61, head('f_pinky.01.L'))                  # pinky MCP
            put(42, head('thumb.01.L.001'))                # thumb tip
        else:
            put(32, head('f_middle.01.R'))
            put(28, head('f_index.01.R'))
            put(40, head('f_pinky.01.R'))
            put(21, head('thumb.01.R.001'))

        hip_i = 9 if S == 'L' else 10
        knee_i = 11 if S == 'L' else 12
        ankle_i = 13 if S == 'L' else 14
        toe_i = 15 if S == 'L' else 18
        small_i = 16 if S == 'L' else 19
        heel_i = 17 if S == 'L' else 20
        put(hip_i, head('DEF-thigh.' + S))
        put(knee_i, head('DEF-shin.' + S))
        ankle = head('DEF-foot.' + S)
        put(ankle_i, ankle)
        toe = tail('DEF-toe.' + S)
        put(toe_i, toe)
        side = 1.0 if S == 'L' else -1.0
        put(small_i, toe + Vector((-0.05 * side, 0.0, 0.0)))
        put(heel_i, ankle + Vector((0.0, 0.06, -0.075)))

    return kp, [1.0] * 70


def evaluate_verts(mesh):
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    ob = mesh.evaluated_get(dg)
    me = ob.to_mesh()
    co = [ob.matrix_world @ v.co for v in me.vertices]
    ob.to_mesh_clear()
    return co


def reset_rig(rig):
    for pb in rig.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()


def main():
    try:
        mod = runpy.run_path(SRC, run_name='pose_test')
    except Exception:
        traceback.print_exc()
        print('[FAIL] import character_tools.py')
        return 1

    rig = bpy.data.objects.get('rig')
    mesh = bpy.data.objects.get('SKM_Manny')
    if rig is None or mesh is None:
        print('[FAIL] missing rig/SKM_Manny')
        return 1

    reset_rig(rig)
    static = [mesh.matrix_world @ v.co for v in mesh.data.vertices]
    rest0 = evaluate_verts(mesh)
    baseline = max((a - b).length for a, b in zip(static, rest0))
    print('[info] rest baseline deviation: %.6f m' % baseline)
    kp, vis = build_rest_keypoints(rig)
    rest = mod['_pose_rest_metrics'](rig)

    def arm(i):
        x, y, z = kp[i]
        return Vector((x, z, -y))

    # ---------------------------------------------------------- rest mapping
    targets = mod['_pose_build_targets'](rig, kp, vis, ground=False)
    check('rest scale', abs(targets['scale'] - 1.0) < 1e-3,
          'scale=%.6f' % targets['scale'])
    check('rest shift zero', targets['shift'].length < 1e-6,
          'shift=%s' % list(targets['shift']))
    check('rest torso translation',
          close(targets['torso'].to_translation(),
                rest['torso_rest'].to_translation()),
          'err=%.6f' % (targets['torso'].to_translation()
                        - rest['torso_rest'].to_translation()).length)
    check('rest shoulder point',
          close(targets['shoulders_points']['L'], arm(5)),
          'err=%.6f' % (targets['shoulders_points']['L'] - arm(5)).length)

    if 'L' in targets['hands']:
        hpos = targets['hands']['L'].to_translation()
        check('rest hand position', close(hpos, arm(62), 5e-4),
              'err=%.6f' % (hpos - arm(62)).length)
        hand_rest_q = rig.data.bones['DEF-hand.L'].matrix_local.to_quaternion()
        hand_q = targets['hands']['L'].to_quaternion()
        ang = math.degrees(hand_q.rotation_difference(hand_rest_q).angle)
        check('rest hand rotation', ang < 1.0, 'err=%.4f deg' % ang)
    else:
        check('rest hand present', False, 'left hand missing')

    if 'L' in targets['feet']:
        fpos = targets['feet']['L'].to_translation()
        check('rest foot position', close(fpos, arm(13), 1e-4),
              'err=%.6f' % (fpos - arm(13)).length)
        q = targets['feet']['L'].to_quaternion()
        ang = math.degrees(q.angle)
        check('rest foot rotation', ang < 1.0, 'err=%.4f deg' % ang)
    else:
        check('rest foot present', False, 'left foot missing')

    # ---------------------------------------------------------- apply + mesh
    mod['_pose_apply'](rig, targets)
    bpy.context.view_layer.update()

    hand_pb = rig.pose.bones.get('hand_ik.L')
    check('hand_ik follows target',
          close(hand_pb.matrix.to_translation(), arm(62), 5e-4),
          'err=%.6f' % (hand_pb.matrix.to_translation()
                        - arm(62)).length)
    foot_pb = rig.pose.bones.get('foot_ik.L')
    check('foot_ik follows target',
          close(foot_pb.matrix.to_translation(), arm(13), 2e-4),
          'err=%.6f' % (foot_pb.matrix.to_translation()
                        - arm(13)).length)

    posed = evaluate_verts(mesh)
    dev = max((a - b).length for a, b in zip(static, posed))
    check('rest mesh deviation', dev <= baseline + 0.003,
          'max=%.6f m baseline=%.6f' % (dev, baseline))

    reset_rig(rig)
    back = evaluate_verts(mesh)
    dev_back = max((a - b).length for a, b in zip(rest0, back))
    check('reset mesh deviation', dev_back < 1e-5, 'max=%.7f m' % dev_back)

    # FK 四肢模式在静止姿势下也应复现绑定姿势
    reset_rig(rig)
    mod['_pose_apply_fk'](rig, targets, ground=False)
    bpy.context.view_layer.update()
    fk_rest = evaluate_verts(mesh)
    fk_dev = max((a - b).length for a, b in zip(static, fk_rest))
    check('FK rest mesh deviation', fk_dev < 0.02,
          'max=%.4f m' % fk_dev)
    reset_rig(rig)

    # ---------------------------------------------------------- mirror / missing
    payload = {'ok': True, 'landmarks': [
        {'i': i, 'x': kp[i][0], 'y': kp[i][1], 'z': kp[i][2], 'visibility': 1.0}
        for i in range(70)]}
    mkp, mvis = mod['_pose_payload_arrays'](payload, mirror=True, use_depth=True)
    check('mirror swaps shoulders', mkp[5] == kp[6] and mkp[6] == kp[5], '')
    check('mirror swaps wrists', mkp[62] == kp[41] and mkp[41] == kp[62], '')

    vis_missing = list(vis)
    vis_missing[62] = 0.0
    t_missing = mod['_pose_build_targets'](rig, kp, vis_missing, ground=False)
    check('missing left wrist skips hand', 'L' not in t_missing['hands'], '')
    check('missing left wrist keeps right', 'R' in t_missing['hands'], '')

    # ---------------------------------------------------------- ground contact
    # 贴地由 _pose_ground_targets 在摆完姿势后补偏移：整体平移姿势，
    # 不允许动 rig:root（根运动）。躺姿最能体现：不贴地时整个人是悬空的。
    kp_flat = [list(p) for p in kp]
    hip_mid = Vector(((kp[9][0] + kp[10][0]) / 2,
                      (kp[9][1] + kp[10][1]) / 2,
                      (kp[9][2] + kp[10][2]) / 2))
    lay = Matrix.Rotation(math.radians(80.0), 4, 'X')
    for i in list(range(0, 9)) + list(range(21, 70)):
        p = lay @ (Vector(kp_flat[i]) - hip_mid)
        kp_flat[i] = list(p + hip_mid)
    reset_rig(rig)
    t_ground = mod['_pose_build_targets'](rig, kp_flat, vis, ground=True)
    root_before = rig.pose.bones['root'].matrix_basis.copy()
    mod['_pose_apply_fk'](rig, t_ground)
    low0 = mod['_pose_mesh_lowest_z'](rig)
    mod['_pose_ground_targets'](rig, t_ground, mod['_pose_apply_fk'])
    bpy.context.view_layer.update()
    low = mod['_pose_mesh_lowest_z'](rig)
    check('ground: mesh on floor', low is not None and abs(low) < 0.002,
          'min_z=%.4f' % (low if low is not None else 1e9))
    check('ground: shift matches offset',
          low0 is not None and abs(t_ground['shift'].z + low0) < 1e-3,
          'before=%.4f shift_z=%.4f' % (low0 if low0 is not None else -1,
                                        t_ground['shift'].z))
    root_now = rig.pose.bones['root'].matrix_basis
    root_delta = max(abs(root_now[i][j] - root_before[i][j])
                     for i in range(4) for j in range(4))
    check('ground: root untouched', root_delta < 1e-9,
          'delta=%.10f' % root_delta)
    chest = (t_ground['joints']['shoulder_L'] + t_ground['joints']['shoulder_R']) * 0.5
    hip = (t_ground['joints']['hip_L'] + t_ground['joints']['hip_R']) * 0.5
    tilt = math.degrees((chest - hip).angle(Vector((0.0, 0.0, 1.0))))
    check('lying: body is horizontal', tilt > 60.0, 'chest tilt=%.1f deg' % tilt)
    reset_rig(rig)

    # ---------------------------------------------------------- root stays put
    # 姿态捕捉不允许碰 rig:root（位置和旋转都不动），否则会污染根运动。
    reset_rig(rig)
    t_plain = mod['_pose_build_targets'](rig, kp, vis, ground=True)
    mod['_pose_apply_fk'](rig, t_plain)
    mod['_pose_ground_targets'](rig, t_plain, mod['_pose_apply_fk'])
    m = rig.pose.bones['root'].matrix_basis
    delta = max(abs(m[i][j] - (1.0 if i == j else 0.0))
                for i in range(4) for j in range(4))
    check('root untouched by capture', delta < 1e-9, 'delta=%.10f' % delta)
    reset_rig(rig)

    # ---------------------------------------------------------- lean fidelity
    # 参考图弯腰就弯腰：躯干增量要和参考一致（不再有 8° 死区 + 0.9 缩放 + 35° 上限）
    def keypoints_for_pose(deg):
        reset_rig(rig)
        mod_rot = Quaternion(Vector((1.0, 0.0, 0.0)), math.radians(deg))
        for name in ('torso',):
            pb = rig.pose.bones[name]
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = mod_rot
        bpy.context.view_layer.update()
        kp2, vis2 = build_rest_keypoints(rig, posed=True)
        reset_rig(rig)
        return kp2, vis2

    kp_lean, vis_lean = keypoints_for_pose(40.0)
    t_lean = mod['_pose_build_targets'](rig, kp_lean, vis_lean, ground=False)
    lean_chest = math.degrees(
        t_lean['chest_delta'].to_quaternion().angle)
    lean_pelvis = math.degrees(
        t_lean['pelvis_delta'].to_quaternion().angle)
    lean_spine = math.degrees(
        t_lean['spine_delta'].to_quaternion().angle)
    check('lean fidelity 40deg', abs(lean_chest - 40.0) < 2.0,
          'chest=%.1f deg' % lean_chest)
    check('lean goes to spine', lean_pelvis < 3.0 and lean_spine > 30.0,
          'pelvis=%.1f spine=%.1f' % (lean_pelvis, lean_spine))

    # ---------------------------------------------------------- torso lean / head turn
    reset_rig(rig)
    kp_turn = [list(p) for p in kp]
    hip_mid_cap = Vector(((kp[9][0] + kp[10][0]) / 2,
                          (kp[9][1] + kp[10][1]) / 2,
                          (kp[9][2] + kp[10][2]) / 2))
    lean = Matrix.Rotation(math.radians(25.0), 4, 'X')
    upper = list(range(0, 9)) + list(range(21, 70))
    for i in upper:
        p = Vector(kp_turn[i]) - hip_mid_cap
        p = lean @ p
        kp_turn[i] = list(p + hip_mid_cap)
    head_center = Vector(kp_turn[69])
    yaw = Matrix.Rotation(math.radians(30.0), 4, 'Y')
    for i in range(0, 5):
        p = Vector(kp_turn[i]) - head_center
        p = yaw @ p
        kp_turn[i] = list(p + head_center)

    t_turn = mod['_pose_build_targets'](rig, kp_turn, vis, ground=False)
    torso_ang = math.degrees(t_turn['chest_delta'].to_quaternion().angle)
    spine_ang = math.degrees(t_turn['spine_delta'].to_quaternion().angle)
    head_rest_q = rig.data.bones['head'].matrix_local.to_quaternion()
    head_q = t_turn.get('head_rotation')
    head_ang = (math.degrees(head_q.rotation_difference(head_rest_q).angle)
                if head_q is not None else 0.0)
    check('torso lean applied', abs(torso_ang) > 5.0,
          'chest=%.2f spine=%.2f deg' % (torso_ang, spine_ang))
    check('head turn applied', head_q is not None and abs(head_ang) > 10.0,
          'angle=%.2f deg' % head_ang)

    # 应用一遍，确认 shoulder 只转不移、脊椎真的转了
    reset_rig(rig)
    mod['_pose_apply_fk'](rig, t_turn)
    bpy.context.view_layer.update()
    shoulder_loc = max(rig.pose.bones['shoulder.' + S].location.length
                       for S in ('L', 'R'))
    check('shoulder rotate only', shoulder_loc < 1e-4,
          'location=%.8f m' % shoulder_loc)
    spine_rot = 0.0
    for name in ('spine_fk.001', 'spine_fk.002', 'spine_fk.003'):
        pb = rig.pose.bones.get(name)
        if pb is not None:
            spine_rot += math.degrees(pb.matrix_basis.to_quaternion().angle)
    check('spine_fk actually bends', spine_rot > 10.0,
          'sum=%.1f deg' % spine_rot)
    reset_rig(rig)

    # ---------------------------------------------------------- FK -> IK 吸附
    # 按 FK 摆好之后要能切回 IK 控制器，而且姿势不能变。
    reset_rig(rig)
    t_snap = mod['_pose_build_targets'](rig, kp_turn, vis, ground=False)
    mod['_pose_apply_fk'](rig, t_snap)
    bpy.context.view_layer.update()
    watch = ('DEF-hand.L', 'DEF-hand.R', 'DEF-foot.L', 'DEF-foot.R',
             'DEF-forearm.L', 'DEF-shin.L')
    fk_pos = {n: rig.pose.bones[n].head.copy() for n in watch}
    drift = mod['_pose_snap_fk_to_ik'](rig, t_snap)
    bpy.context.view_layer.update()
    ik_now = {n: rig.pose.bones[n].head.copy() for n in watch}
    pose_delta = max((ik_now[n] - fk_pos[n]).length for n in watch)
    modes = [rig.pose.bones['%s.%s' % (p, S)]['IK_FK']
             for S in ('L', 'R')
             for p in ('upper_arm_parent', 'thigh_parent')]
    check('fk2ik switches to IK', all(abs(v) < 1e-6 for v in modes),
          'IK_FK=%s' % modes)
    check('fk2ik keeps the pose',
          pose_delta < 0.002 and drift < 0.002,
          'pose=%.5f m drift=%.5f m' % (pose_delta, drift))
    reset_rig(rig)

    # ---------------------------------------------------------- B_rig discovery
    try:
        reset_rig(rig)
        before = rig.pose.bones['hand_ik.L'].matrix_basis.copy()
        new_name, count = mod['duplicate_character'](rig, prefix='B_',
                                                     offset=(1.3, 0.0, 0.0))
        b_rig = bpy.data.objects.get(new_name)
        check('B_rig created', b_rig is not None and count > 0,
              'name=%s count=%d' % (new_name, count))
        if b_rig is not None:
            check('_find_rig(B_rig)', mod['_find_rig'](b_rig) is b_rig, '')
            t_b = mod['_pose_build_targets'](b_rig, kp, vis, ground=False)
            mod['_pose_apply'](b_rig, t_b)
            bpy.context.view_layer.update()
            after = rig.pose.bones['hand_ik.L'].matrix_basis.copy()
            delta = max(abs(after[i][j] - before[i][j])
                        for i in range(4) for j in range(4))
            check('B_rig leaves A untouched', delta < 1e-6,
                  'delta=%.8f' % delta)
    except Exception:
        traceback.print_exc()
        check('B_rig workflow', False, 'exception')

    reset_rig(rig)
    print('\n==== RESULT: %d passed, %d failed ====' % (len(PASSES), len(FAILS)))
    for f in FAILS:
        print('  FAIL:', f)
    return 0 if not FAILS else 1


if __name__ == '__main__':
    raise SystemExit(main())
