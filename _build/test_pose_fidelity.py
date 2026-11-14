# -*- coding: utf-8 -*-
"""姿态映射的“回环”测试：不用模型，直接验证捕获的姿势能不能被 1:1 还原。

blender -b --factory-startup --disable-autoexec rigue5_rigified.blend \
  --python _build/test_pose_fidelity.py -- [depth] [torso|notorso]

做法：把 rig 摆成一个已知姿势 -> 按 MHR70 的约定从网格上读出 70 个关键点
（相当于一个完美的人体识别）-> 跑姿态捕捉的映射 -> 和原姿势比关节位置。
理想情况下误差为 0，剩下的就是映射本身的误差（和识别模型无关）。

误差按“髋相对”的关节位置算：映射会把髋放在 rig 的髋位置，整体平移不算错。
`torso` 列是胸廓轴（肩中点 - 髋中点）的夹角，0° 表示躯干朝向完全一致。
测试同时检查 rig:root 在捕捉后必须保持静止（根运动不能被改）。
"""
import math
import os
import runpy
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'character_tools.py')
mod = runpy.run_path(SRC, run_name='pose_roundtrip')

# 判定阈值：关节误差 9 cm、躯干朝向 3°、root 必须一动没动、肩不能有位移。
# 9 cm 是留给“胯部铰链 vs 弯腰”这个二义性的：单张图只有肩/髋两组点，分不出
# 参考是胯在转还是腰在弯，映射按“弯腰优先”处理，肩/头/颈的位置会有几厘米差。
MAX_POS_ERR = 0.09
MAX_TORSO_ERR = 3.0
MAX_ROOT_ERR = 1e-9
MAX_SHOULDER_LOC = 1e-4

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
DEPTH = float(argv[0]) if argv else 1.0
TORSO = not (len(argv) > 1 and argv[1] == 'notorso')

rig = bpy.data.objects['rig']
bpy.context.view_layer.objects.active = rig

JOINTS = [
    ('L_sh', 'DEF-upper_arm.L'), ('R_sh', 'DEF-upper_arm.R'),
    ('L_el', 'DEF-forearm.L'), ('R_el', 'DEF-forearm.R'),
    ('L_wr', 'DEF-hand.L'), ('R_wr', 'DEF-hand.R'),
    ('L_hip', 'DEF-thigh.L'), ('R_hip', 'DEF-thigh.R'),
    ('L_kn', 'DEF-shin.L'), ('R_kn', 'DEF-shin.R'),
    ('L_ft', 'DEF-foot.L'), ('R_ft', 'DEF-foot.R'),
    ('L_toe', 'DEF-toe.L'), ('R_toe', 'DEF-toe.R'),
    ('head', 'DEF-spine.006'),
    ('neck', 'DEF-spine.005'),
]


def reset():
    for pb in rig.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()


def joint_positions():
    bpy.context.view_layer.update()
    out = {}
    for label, name in JOINTS:
        pb = rig.pose.bones.get(name)
        if pb is not None:
            out[label] = pb.head.copy()
    return out


def keypoints_from_rig():
    b = rig.pose.bones

    def head(name):
        return b[name].head.copy()

    def tail(name):
        return b[name].tail.copy()

    # 头部点按头骨的朝向生成（否则倒立/躺姿时“鼻子”方向会错）
    head_pb = b['DEF-spine.006']
    head_rest = rig.data.bones['DEF-spine.006'].matrix_local
    head_rest_inv = head_rest.inverted()

    def head_pt(offset):
        local = head_rest_inv @ (head_rest.to_translation() + Vector(offset))
        return head_pb.matrix @ local

    kp = [[0.0, 0.0, 0.0] for _ in range(70)]

    def put(i, v):
        kp[i] = [float(v.x), float(-v.z), float(v.y)]

    put(0, head_pt((0.0, -0.09, 0.0)))
    put(1, head_pt((0.03, -0.08, 0.0)))
    put(2, head_pt((-0.03, -0.08, 0.0)))
    put(3, head_pt((0.07, 0.0, 0.0)))
    put(4, head_pt((-0.07, 0.0, 0.0)))
    for S, base in (('L', 5), ('R', 6)):
        put(base, head('DEF-upper_arm.' + S))
        put(base + 2, head('DEF-forearm.' + S))
        put(62 if S == 'L' else 41, head('DEF-hand.' + S))
        if S == 'L':
            put(53, head('f_middle.01.L'))
            put(49, head('f_index.01.L'))
            put(61, head('f_pinky.01.L'))
            put(42, head('thumb.01.L.001'))
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
    put(69, head('DEF-spine.005'))
    return kp, [1.0] * 70


def rot(name, axis, deg):
    pb = rig.pose.bones.get(name)
    if pb is None:
        return
    q = Quaternion(Vector(axis).normalized(), math.radians(deg))
    pb.rotation_mode = 'QUATERNION'
    pb.rotation_quaternion = q


def translate(name, vec):
    pb = rig.pose.bones.get(name)
    if pb is not None:
        pb.location = Vector(vec)


POSES = {}


def pose(name, info=False):
    def deco(fn):
        POSES[name] = (fn, info)
        return fn
    return deco


def spine_bend(deg, axis=(1, 0, 0), bones=('spine_fk.001', 'spine_fk.002',
                                          'spine_fk.003')):
    """把 deg 均摊到几节脊椎上（和映射的做法一致，但不是同一个分段）。"""
    for name in bones:
        rot(name, axis, deg / len(bones))


@pose('spine_bow30')
def _p1():
    spine_bend(30)


@pose('spine_bow-25')
def _p1b():
    spine_bend(-25)


@pose('spine_side21')
def _p2():
    spine_bend(21, axis=(0, 1, 0))


@pose('torso_yaw35')
def _p3():
    rot('torso', (0, 0, 1), 35)


@pose('spine_bow20_arms')
def _p4():
    spine_bend(20)
    rot('upper_arm_fk.L', (0, 1, 0), -70)
    rot('upper_arm_fk.R', (0, 1, 0), 70)
    rot('forearm_fk.L', (1, 0, 0), -50)
    rot('forearm_fk.R', (1, 0, 0), -50)


@pose('crouch')
def _p5():
    translate('torso', (0.0, 0.05, -0.35))
    rot('thigh_fk.L', (1, 0, 0), -55)
    rot('thigh_fk.R', (1, 0, 0), -55)
    rot('shin_fk.L', (1, 0, 0), 70)
    rot('shin_fk.R', (1, 0, 0), 70)
    spine_bend(15)


@pose('kick')
def _p6():
    spine_bend(-12)
    rot('thigh_fk.L', (1, 0, 0), -95)
    rot('shin_fk.L', (1, 0, 0), 15)
    rot('thigh_fk.R', (1, 0, 0), 8)
    rot('upper_arm_fk.L', (0, 1, 0), -35)
    rot('upper_arm_fk.R', (0, 1, 0), 55)


@pose('lying')
def _p7():
    rot('torso', (1, 0, 0), 90)
    rot('upper_arm_fk.L', (0, 0, 1), -40)
    rot('upper_arm_fk.R', (0, 0, 1), 40)


@pose('headstand')
def _p8():
    rot('torso', (1, 0, 0), 170)
    rot('thigh_fk.L', (1, 0, 0), -25)
    rot('thigh_fk.R', (1, 0, 0), -25)
    rot('shin_fk.L', (1, 0, 0), 60)
    rot('shin_fk.R', (1, 0, 0), 60)


@pose('twist_bend')
def _p9():
    rot('torso', (0, 0, 1), 25)
    rot('spine_fk.003', (0, 1, 0), 12)
    rot('upper_arm_fk.L', (1, 0, 0), -60)


# 参考里“胯部铰链、背是直的”也能被识别成 30°（单图分不出是胯在转还是腰在弯）。
# 映射按“弯腰优先”处理，所以这一条只作为信息输出，不参与判定。
@pose('hip_hinge30', info=True)
def _p10():
    rot('torso', (1, 0, 0), 30)


def shape_errors(gt, got):
    gh = (gt['L_hip'] + gt['R_hip']) * 0.5
    ph = (got['L_hip'] + got['R_hip']) * 0.5
    return {k: ((got[k] - ph) - (gt[k] - gh)).length for k in gt if k in got}


def torso_angle(gt, got):
    def axis(d):
        sh = (d['L_sh'] + d['R_sh']) * 0.5
        hip = (d['L_hip'] + d['R_hip']) * 0.5
        return sh - hip
    g = axis(gt)
    p = axis(got)
    if g.length < 1e-6 or p.length < 1e-6:
        return 0.0
    return math.degrees(g.normalized().angle(p.normalized()))


print('depth=%.2f torso=%s' % (DEPTH, TORSO))
total_max = 0.0
worst_torso = 0.0
root_basis_max = 0.0
shoulder_move_max = 0.0
spine_used = 0
bow_spine_missing = []
fails = []
for name, (fn, info) in POSES.items():
    reset()
    fn()
    bpy.context.view_layer.update()
    gt = joint_positions()
    kp, vis = keypoints_from_rig()
    reset()
    targets = mod['_pose_build_targets'](
        rig, kp, vis, ground=False, torso_lean=TORSO, head_turn=True,
        face_reference=True)
    mod['_pose_apply_fk'](rig, targets, ground=False)
    got = joint_positions()
    errs = shape_errors(gt, got)
    tq = torso_angle(gt, got)
    root_basis = rig.pose.bones['root'].matrix_basis
    root_basis_max = max(root_basis_max,
                         max(abs(root_basis[i][j] - (1.0 if i == j else 0.0))
                             for i in range(4) for j in range(4)))
    # shoulder 只能转不能移：location 通道必须一直是 0
    for S in ('L', 'R'):
        pb = rig.pose.bones['shoulder.' + S]
        shoulder_move_max = max(shoulder_move_max, pb.location.length)
    spine_deg = math.degrees(targets['spine_delta'].to_quaternion().angle)
    if spine_deg > 5.0:
        spine_used += 1
    mx = max(errs.values())
    rms = math.sqrt(sum(e * e for e in errs.values()) / len(errs))
    worst = sorted(errs.items(), key=lambda kv: -kv[1])[:4]
    status = 'ok'
    if mx > MAX_POS_ERR or tq > MAX_TORSO_ERR:
        status = 'FAIL'
        if not info:
            fails.append(name)
    if info:
        status = 'info'
    if not info:
        total_max = max(total_max, mx)
        worst_torso = max(worst_torso, tq)
    print('%-18s max=%6.3f m  rms=%6.3f m  torso=%5.1f deg  pelvis=%5.1f '
          'spine=%5.1f  %-4s worst=%s' % (
              name, mx, rms, tq,
              math.degrees(targets['pelvis_delta'].to_quaternion().angle),
              spine_deg, status,
              ', '.join('%s=%.2f' % (k, v) for k, v in worst)))
    reset()

# 弯腰的姿势必须真的用上脊椎：spine_delta 不能是 0，而且不能全丢给骨盆
reset()
POSES['spine_bow30'][0]()
bpy.context.view_layer.update()
kp_bow, vis_bow = keypoints_from_rig()
reset()
t_bow = mod['_pose_build_targets'](rig, kp_bow, vis_bow, ground=False)
bow_spine = math.degrees(t_bow['spine_delta'].to_quaternion().angle)
bow_pelvis = math.degrees(t_bow['pelvis_delta'].to_quaternion().angle)
bow_chest = math.degrees(t_bow['chest_delta'].to_quaternion().angle)
if bow_spine < max(10.0, bow_chest * 0.8):
    fails.append('spine not used (%.1f of %.1f deg)' % (bow_spine, bow_chest))
if bow_pelvis > 5.0:
    fails.append('bow went to pelvis (%.1f deg)' % bow_pelvis)
reset()

print('\nWORST MAX %.3f m   WORST TORSO %.1f deg   ROOT BASIS MAX %.6f' % (
    total_max, worst_torso, root_basis_max))
print('SHOULDER LOCATION MAX %.9f m   bow: chest %.1f = pelvis %.1f + spine %.1f deg' % (
    shoulder_move_max, bow_chest, bow_pelvis, bow_spine))
if root_basis_max > MAX_ROOT_ERR:
    fails.append('root moved')
if shoulder_move_max > MAX_SHOULDER_LOC:
    fails.append('shoulder translated')
print('==== RESULT: %s ====' % ('FAIL: ' + ', '.join(fails) if fails else 'all poses ok'))
raise SystemExit(0 if not fails else 1)
