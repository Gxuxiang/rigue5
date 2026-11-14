# -*- coding: utf-8 -*-
"""角色工具：在 3D 视图 N 面板「Rigify」标签里加一个「复制角色」按钮。

这段代码会被写进 .blend 的文本块 character_tools.py（use_module=True），
打开文件时自动运行；按钮会把当前角色整套（rig + UE 骨架 + 网格 + 重定向空物体）
复制一份，并重新指向副本自己的对象。
"""
import bpy
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from mathutils import Matrix, Quaternion, Vector


def _find_rig(ob):
    """当前选中的可能是 rig，也可能是 UE 骨架，都换算回 rig。"""
    if ob is None or ob.type != 'ARMATURE':
        return None
    if any('RTG_' in o.name and o.parent is ob for o in bpy.data.objects):
        return ob
    helpers = set()
    for pb in ob.pose.bones:
        for c in pb.constraints:
            tgt = getattr(c, 'target', None)
            if tgt is not None and 'RTG_' in tgt.name and tgt.parent is not None:
                helpers.add(tgt.parent)
    if len(helpers) == 1:
        return next(iter(helpers))
    return None


def _character_parts(rig):
    """找出和这个 rig 配套的：重定向空物体、UE 骨架、网格。"""
    helpers = [o for o in bpy.data.objects
               if 'RTG_' in o.name and o.parent is rig]
    root = None
    for ob in bpy.data.objects:
        if ob.type != 'ARMATURE' or ob is rig:
            continue
        for pb in ob.pose.bones:
            for c in pb.constraints:
                tgt = getattr(c, 'target', None)
                if tgt is not None and tgt in helpers:
                    root = ob
                    break
            if root is not None:
                break
        if root is not None:
            break
    mesh = None
    if root is not None:
        for ob in bpy.data.objects:
            if ob.type == 'MESH' and any(m.type == 'ARMATURE' and m.object is root
                                         for m in ob.modifiers):
                mesh = ob
                break
    return helpers, root, mesh


def _strip_suffix(name):
    return re.sub(r'\.\d{3}$', '', name)


# =========================================================================
# 姿态捕捉（截图/图片 -> Rigify 姿态）
# =========================================================================

POSE_MHR70_NAMES = [
    'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder',
    'left_elbow', 'right_elbow',
    'left_hip', 'right_hip',
    'left_knee', 'right_knee',
    'left_ankle', 'right_ankle',
    'left_big_toe_tip', 'left_small_toe_tip', 'left_heel',
    'right_big_toe_tip', 'right_small_toe_tip', 'right_heel',
    'right_thumb_tip', 'right_thumb_first_joint', 'right_thumb_second_joint',
    'right_thumb_third_joint',
    'right_index_tip', 'right_index_first_joint', 'right_index_second_joint',
    'right_index_third_joint',
    'right_middle_tip', 'right_middle_first_joint', 'right_middle_second_joint',
    'right_middle_third_joint',
    'right_ring_tip', 'right_ring_first_joint', 'right_ring_second_joint',
    'right_ring_third_joint',
    'right_pinky_tip', 'right_pinky_first_joint', 'right_pinky_second_joint',
    'right_pinky_third_joint',
    'right_wrist',
    'left_thumb_tip', 'left_thumb_first_joint', 'left_thumb_second_joint',
    'left_thumb_third_joint',
    'left_index_tip', 'left_index_first_joint', 'left_index_second_joint',
    'left_index_third_joint',
    'left_middle_tip', 'left_middle_first_joint', 'left_middle_second_joint',
    'left_middle_third_joint',
    'left_ring_tip', 'left_ring_first_joint', 'left_ring_second_joint',
    'left_ring_third_joint',
    'left_pinky_tip', 'left_pinky_first_joint', 'left_pinky_second_joint',
    'left_pinky_third_joint',
    'left_wrist',
    'left_olecranon', 'right_olecranon',
    'left_cubital_fossa', 'right_cubital_fossa',
    'left_acromion', 'right_acromion',
    'neck',
]

POSE_MIRROR_PAIRS = [
    (1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12), (13, 14),
    (15, 18), (16, 19), (17, 20),
] + [(i, i + 21) for i in range(21, 42)] + [(63, 64), (65, 66), (67, 68)]

# MHR70 的手指顺序是「尖 → 关节1 → 关节2 → 关节3(MCP)」，拇指是
# 「尖 → IP → MCP → CMC」。这里按 Rigify 的骨骼顺序（近端→远端）排成
# 4 个点：p0 是第一节的起点，p1/p2/p3 是后续关节，所以：
#   .01 方向 = p1 - p0，.02 = p2 - p1，.03 = p3 - p2。
POSE_FINGER_CHAINS = {
    'L': {
        'thumb': (45, 44, 43, 42),      # CMC, MCP, IP, tip
        'f_index': (49, 48, 47, 46),    # MCP, PIP, DIP, tip
        'f_middle': (53, 52, 51, 50),
        'f_ring': (57, 56, 55, 54),
        'f_pinky': (61, 60, 59, 58),
    },
    'R': {
        'thumb': (24, 23, 22, 21),
        'f_index': (28, 27, 26, 25),
        'f_middle': (32, 31, 30, 29),
        'f_ring': (36, 35, 34, 33),
        'f_pinky': (40, 39, 38, 37),
    },
}

# 捕捉坐标（x 右、y 下、z 朝后）-> 角色世界坐标（x 右、y 后、z 上）。
# 直立、正面朝镜头的人对应恒等旋转。倒立/躺姿时用它把整个角色转到参考朝向。
POSE_CAP_TO_WORLD = Matrix(((1.0, 0.0, 0.0),
                            (0.0, 0.0, 1.0),
                            (0.0, -1.0, 0.0)))

POSE_MARKER = 'RIGUE5_POSE_RESULT '
POSE_COMFY_ROOT = r'D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI'
POSE_DETECTION_DIR = r'D:\Comfy-Desktop\ComfyUI-Shared\models\detection'
POSE_LOCAL_ROOT = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'rigue5_pose')
POSE_LOCAL_MODELS = os.path.join(POSE_LOCAL_ROOT, 'models')
POSE_HELPER_PATH = os.path.join(POSE_LOCAL_ROOT, 'pose_helper.py')
POSE_DOWNLOAD_URL = 'https://huggingface.co/Comfy-Org/sam-3d-body'

_POSE_JOBS = {}
_POSE_JOB_SEQ = 0
_POSE_TIMER = False
_POSE_PROGRESS_ACTIVE = False


# ---------------------------------------------------------------- 环境 / 路径

def _pose_comfy_python(scene=None):
    custom = getattr(scene, 'character_pose_comfy_python', '') if scene else ''
    if custom and os.path.isfile(custom):
        return custom
    candidates = [
        os.path.join(POSE_COMFY_ROOT, '.venv', 'Scripts', 'python.exe'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''),
                     'Programs', 'ComfyUI', 'resources', 'ComfyUI', '.venv',
                     'Scripts', 'python.exe'),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ''


def _pose_system_python(scene=None):
    custom = getattr(scene, 'character_pose_sys_python', '') if scene else ''
    if custom and os.path.isfile(custom):
        return custom
    candidates = [
        os.path.join(os.environ.get('LOCALAPPDATA', ''),
                     'Programs', 'Python', 'Python312', 'python.exe'),
        shutil.which('python.exe') or '',
        shutil.which('python') or '',
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ''


def _pose_comfy_root(scene=None):
    custom = getattr(scene, 'character_pose_comfy_root', '') if scene else ''
    if custom and os.path.isdir(os.path.join(custom, 'comfy')):
        return custom
    return POSE_COMFY_ROOT


def _pose_sam3d_ckpt(scene=None):
    custom = getattr(scene, 'character_pose_model_path', '') if scene else ''
    candidates = []
    if custom:
        candidates.append(custom)
    candidates += [
        # ComfyUI 官方转换过的 safetensors（推荐）
        os.path.join(POSE_DETECTION_DIR, 'sam_3d_body_dinov3_bf16.safetensors'),
        os.path.join(POSE_DETECTION_DIR, 'sam_3d_body_dinov3_int8_convrot.safetensors'),
        os.path.join(POSE_DETECTION_DIR, 'sam-3d-body',
                     'sam_3d_body_dinov3_bf16.safetensors'),
        # 原始 Meta model.ckpt 的键名和 ComfyUI 的 SAM3DBody 不兼容，不在这里自动识别。
    ]
    for path in candidates:
        try:
            if path and os.path.isfile(path) and os.path.getsize(path) > 1000000:
                return path
        except OSError:
            pass
    return ''


def _pose_instant_paths(scene=None):
    base = POSE_LOCAL_MODELS
    return (os.path.join(base, 'instanthmr-medium-fit2.onnx'),
            os.path.join(base, 'mhr-body.onnx'))


def _pose_mediapipe_path(scene=None):
    return os.path.join(POSE_LOCAL_MODELS, 'pose_landmarker_full.task')


def _pose_env_status(scene=None):
    comfy_python = _pose_comfy_python(scene)
    comfy_root = _pose_comfy_root(scene)
    ckpt = _pose_sam3d_ckpt(scene)
    code = os.path.isfile(os.path.join(
        comfy_root, 'comfy', 'ldm', 'sam3d_body', 'model', 'model.py'))
    sam3d_ready = bool(comfy_python and ckpt and code)
    model, body = _pose_instant_paths(scene)
    instant_ready = os.path.isfile(model) and os.path.isfile(body)
    mp_model = _pose_mediapipe_path(scene)
    mediapipe_ready = os.path.isfile(mp_model)
    if sam3d_ready:
        label, icon = 'SAM 3D Body 就绪', 'CHECKMARK'
    elif instant_ready:
        label, icon = 'InstantHMR 就绪（SAM 3D Body 未就绪）', 'CHECKMARK'
    elif mediapipe_ready:
        label, icon = 'MediaPipe 就绪（兜底）', 'INFO'
    else:
        label, icon = '未找到模型', 'ERROR'
    return {
        'sam3d_ready': sam3d_ready, 'sam3d_ckpt': ckpt,
        'sam3d_python': comfy_python, 'sam3d_root': comfy_root,
        'sam3d_code': code,
        'instant_ready': instant_ready, 'instant_model': model,
        'instant_body': body, 'mediapipe_ready': mediapipe_ready,
        'mediapipe_model': mp_model,
        'any': sam3d_ready or instant_ready or mediapipe_ready,
        'label': label, 'icon': icon,
    }


def _pose_choose_backend(scene):
    selected = getattr(scene, 'character_pose_backend', 'auto')
    if selected == 'sam3d':
        return 'sam3d'
    if selected == 'instanthmr':
        return 'instanthmr'
    if selected == 'mediapipe':
        return 'mediapipe'
    status = _pose_env_status(scene)
    if status['sam3d_ready']:
        return 'sam3d'
    if status['instant_ready']:
        return 'instanthmr'
    if status['mediapipe_ready']:
        return 'mediapipe'
    raise RuntimeError(
        '没有可用的姿态识别模型。请先下载 SAM 3D Body 的\n'
        'sam_3d_body_dinov3_bf16.safetensors 放到\n'
        + POSE_DETECTION_DIR)


def _pose_python_for(backend, scene):
    python = _pose_comfy_python(scene) if backend == 'sam3d' else _pose_system_python(scene)
    if not python:
        raise RuntimeError(
            '找不到 %s 的 Python 解释器。可以在面板里设置路径。' % backend)
    return python


def _pose_helper_source():
    text = bpy.data.texts.get('pose_helper.py')
    if text is None:
        raise RuntimeError(
            'blend 里缺少 pose_helper.py 文本块；请运行 _build/add_character_ui.py 同步。')
    return text.as_string()


def _ensure_pose_helper():
    os.makedirs(POSE_LOCAL_ROOT, exist_ok=True)
    src = _pose_helper_source()
    path = POSE_HELPER_PATH
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            old = fh.read()
    except OSError:
        old = None
    if old != src:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(src)
        os.replace(tmp, path)
    return path


# ---------------------------------------------------------------- 关键点 -> 姿态

def _pose_payload_arrays(payload, mirror=False, use_depth=True):
    """helper 的 landmarks -> (70 个 xyz, 70 个 visibility)。"""
    kp = [[0.0, 0.0, 0.0] for _ in range(70)]
    vis = [0.0] * 70
    for item in payload.get('landmarks') or []:
        try:
            i = int(item.get('i', -1))
        except (TypeError, ValueError):
            continue
        if not (0 <= i < 70):
            continue
        try:
            kp[i] = [float(item.get('x', 0.0)),
                     float(item.get('y', 0.0)),
                     float(item.get('z', 0.0))]
            vis[i] = float(item.get('visibility', 1.0))
        except (TypeError, ValueError):
            continue
    if mirror:
        for a, b in POSE_MIRROR_PAIRS:
            kp[a], kp[b] = kp[b], kp[a]
            vis[a], vis[b] = vis[b], vis[a]
    depth_scale = max(0.0, min(1.0, float(use_depth)))
    if depth_scale != 1.0:
        for p in kp:
            p[2] *= depth_scale
    return kp, vis


def _v3(seq):
    return Vector((float(seq[0]), float(seq[1]), float(seq[2])))


def _pose_frame(f, l, u):
    """列向量为 f / l / u 的 3x3 矩阵。"""
    return Matrix(((f.x, l.x, u.x),
                   (f.y, l.y, u.y),
                   (f.z, l.z, u.z)))


def _pose_hand_frame(wrist, middle, index, pinky):
    """手掌坐标系：X=拇指侧(食指->小指叉乘), Y=腕->中指, Z=食指->小指。"""
    f = Vector(middle) - Vector(wrist)
    if f.length < 1e-6:
        raise ValueError('hand forward degenerate')
    f.normalize()
    l = Vector(index) - Vector(pinky)
    l = l - f * l.dot(f)
    if l.length < 1e-6:
        raise ValueError('hand side degenerate')
    l.normalize()
    n = f.cross(l)
    n.normalize()
    return _pose_frame(n, f, l)


def _pose_rest_metrics(rig):
    bones = rig.data.bones

    def head(name):
        return bones[name].head_local.copy()

    def tail(name):
        return bones[name].tail_local.copy()

    hip_l, hip_r = head('DEF-thigh.L'), head('DEF-thigh.R')
    sh_l, sh_r = head('DEF-upper_arm.L'), head('DEF-upper_arm.R')
    rest = {
        'H0': (hip_l + hip_r) * 0.5,
        'S0': (sh_l + sh_r) * 0.5,
        'rest_upper': (sh_l - head('DEF-forearm.L')).length,
        'rest_fore': (head('DEF-forearm.L') - head('DEF-hand.L')).length,
        'rest_thigh': (hip_l - head('DEF-shin.L')).length,
        'rest_shin': (head('DEF-shin.L') - head('DEF-foot.L')).length,
        'rest_torso': ((sh_l + sh_r) * 0.5 - (hip_l + hip_r) * 0.5).length,
        'rest_ankle_z': head('DEF-foot.L').z,
        'torso_rest': rig.pose.bones['torso'].bone.matrix_local.copy(),
        'hand_rest': {},
        'hand_frame': {},
        'finger_roll': {},
        'forearm_roll': {},
        'foot_rest': {},
    }
    # 静止身体坐标系（A-pose 本身有轻微前倾，不能强行对齐到世界 Z）
    u0 = ((sh_l + sh_r) * 0.5 - (hip_l + hip_r) * 0.5)
    u0.normalize()
    l0 = sh_l - sh_r
    l0 = l0 - u0 * l0.dot(u0)
    l0.normalize()
    f0 = l0.cross(u0)
    f0.normalize()
    l0 = u0.cross(f0)
    l0.normalize()
    rest['body_frame'] = _pose_frame(f0, l0, u0)
    # 髋部参考坐标系（髋线 + 世界 Z）。只用髋线判断左右，不把腿的弯曲
    # 带进躯干倾斜的计算。
    u_h = Vector((0.0, 0.0, 1.0))
    l_h = hip_l - hip_r
    l_h = l_h - u_h * l_h.dot(u_h)
    if l_h.length < 1e-6:
        l_h = Vector((1.0, 0.0, 0.0))
    l_h.normalize()
    f_h = l_h.cross(u_h)
    f_h.normalize()
    l_h = u_h.cross(f_h)
    l_h.normalize()
    rest['hip_frame'] = _pose_frame(f_h, l_h, u_h)

    for S in ('L', 'R'):
        wrist = head('DEF-hand.' + S)
        try:
            middle = head('f_middle.01.' + S)
        except KeyError:
            middle = wrist + Vector((0.0, -0.025, 0.0))
        try:
            index = head('f_index.01.' + S)
        except KeyError:
            index = wrist + Vector((0.0, -0.02, 0.0))
        try:
            pinky = head('f_pinky.01.' + S)
        except KeyError:
            pinky = wrist + Vector((0.01, 0.0, 0.0))
        try:
            thumb = head('thumb.01.' + S)
        except KeyError:
            thumb = wrist
        rest['hand_rest'][S] = (wrist, middle, index, pinky, thumb)
        try:
            rest['hand_frame'][S] = _pose_hand_frame(wrist, middle, index, pinky)
        except ValueError:
            rest['hand_frame'][S] = _pose_frame(
                Vector((0.0, -1.0, 0.0)),
                Vector((1.0, 0.0, 0.0)),
                Vector((0.0, 0.0, 1.0)))

        # 手指/前臂的 roll：记下它们静止时 local X 在“手掌坐标系”里的分量。
        # 摆姿势时用同一个分量重建 local X，手指就不会绕自身轴乱滚。
        F = rest['hand_frame'][S]

        def roll_coef(bone_name):
            b = bones.get(bone_name)
            if b is None:
                return None
            x = b.matrix_local.to_3x3().col[0]
            return Vector((x.dot(F.col[0]), x.dot(F.col[1]), x.dot(F.col[2])))

        rolls = {}
        for finger in ('thumb', 'f_index', 'f_middle', 'f_ring', 'f_pinky'):
            for i in (1, 2, 3):
                name = '%s.0%d.%s' % (finger, i, S)
                coef = roll_coef(name)
                if coef is not None:
                    rolls[name] = coef
        rest['finger_roll'][S] = rolls
        rest['forearm_roll'][S] = roll_coef('DEF-forearm.' + S) or roll_coef('forearm_fk.' + S)

        ankle = head('DEF-foot.' + S)
        toe = tail('DEF-toe.' + S)
        heel = ankle + Vector((0.0, 0.06, -0.075))
        rest['foot_rest'][S] = (ankle, toe, heel)

    arm_max = 0.5502
    pb = rig.pose.bones.get('hand_ik.L')
    if pb:
        for c in pb.constraints:
            if c.type == 'LIMIT_DISTANCE' and c.name == 'Arm Reach':
                arm_max = float(c.distance)
    rest['arm_max'] = arm_max
    return rest


def _pose_body_frame(kp, vis, rest):
    def ok(i):
        return 0 <= i < len(vis) and vis[i] >= 0.5

    for i in (5, 6, 9, 10):
        if not ok(i):
            raise RuntimeError('需要同时看到左右肩和左右髋（全身或大半身图）。')
    P = _v3
    hip_mid = (P(kp[9]) + P(kp[10])) * 0.5
    sh_mid = (P(kp[5]) + P(kp[6])) * 0.5
    u = sh_mid - hip_mid
    if u.length < 1e-6:
        raise RuntimeError('肩和髋几乎重合，无法识别人体朝向。')
    u.normalize()
    l = P(kp[5]) - P(kp[6])
    l = l - u * l.dot(u)
    if l.length < 1e-6:
        raise RuntimeError('左右肩重合，无法确定身体左右方向。')
    l.normalize()
    f = l.cross(u)
    if f.length < 1e-6:
        raise RuntimeError('身体坐标系退化。')
    f.normalize()
    l = u.cross(f)
    l.normalize()
    f_cap = _pose_frame(f, l, u)
    # 相对“静止身体坐标系”求旋转；静止时 R_body == I。
    r_body = rest['body_frame'] @ f_cap.transposed()
    if r_body.determinant() < 0.0:
        raise RuntimeError('姿态坐标系是左手系，无法转换。')
    return r_body, hip_mid, u


def _pose_auto_scale(kp, vis, rest):
    ratios = []

    def add(a, b, rest_len):
        if vis[a] >= 0.5 and vis[b] >= 0.5:
            d = (_v3(kp[a]) - _v3(kp[b])).length
            if d > 1e-4:
                ratios.append(rest_len / d)

    add(9, 11, rest['rest_thigh'])
    add(11, 13, rest['rest_shin'])
    add(10, 12, rest['rest_thigh'])
    add(12, 14, rest['rest_shin'])
    add(5, 7, rest['rest_upper'])
    add(7, 62, rest['rest_fore'])
    add(6, 8, rest['rest_upper'])
    add(8, 41, rest['rest_fore'])
    if vis[5] >= 0.5 and vis[6] >= 0.5 and vis[9] >= 0.5 and vis[10] >= 0.5:
        sh_mid = (_v3(kp[5]) + _v3(kp[6])) * 0.5
        hip_mid = (_v3(kp[9]) + _v3(kp[10])) * 0.5
        d = (sh_mid - hip_mid).length
        if d > 1e-4:
            ratios.append(rest['rest_torso'] / d)
            ratios.append(rest['rest_torso'] / d)
    if not ratios:
        return 1.0
    ratios.sort()
    scale = ratios[len(ratios) // 2]
    return max(0.4, min(3.0, scale))


def _pose_clamp_reach(pivot, target, max_len):
    delta = target - pivot
    if delta.length > max_len:
        return pivot + delta.normalized() * max_len
    return target


def _pose_build_targets(rig, kp, vis, ground=True, torso_lean=True,
                        head_turn=True, face_reference=True):
    rest = _pose_rest_metrics(rig)
    r_body, hip_cap, up_cap = _pose_body_frame(kp, vis, rest)
    scale = _pose_auto_scale(kp, vis, rest)
    H0 = rest['H0']
    warnings = []
    # 身体 up 与图像 up 的夹角。直立时约 0°，躺姿约 90°，倒立约 180°。
    # 夹角大时不再假设“脚踩地 + 脊柱竖直”，而是把整个角色按参考朝向
    # 全局旋转（root），再按网格最低点贴地。
    tilt = math.degrees(up_cap.angle(Vector((0.0, -1.0, 0.0))))
    global_root = False
    root_rotation = None
    if tilt > 60.0:
        rg = POSE_CAP_TO_WORLD @ r_body.transposed()
        if rg.determinant() > 0.0:
            global_root = True
            root_rotation = rg
        else:
            warnings.append('检测到倒立/躺姿，但身体坐标系是左手系，已按脚踩地处理。')

    # 参考图里的人可能侧身/背身；把整个角色绕 Z 转到相同的相对朝向。
    root_yaw = 0.0
    if face_reference:
        u_face = ((_v3(kp[5]) + _v3(kp[6])) * 0.5
                  - (_v3(kp[9]) + _v3(kp[10])) * 0.5)
        if u_face.length > 1e-6:
            u_face.normalize()
            l_face = _v3(kp[5]) - _v3(kp[6])
            l_face = l_face - u_face * l_face.dot(u_face)
            if l_face.length > 1e-6:
                l_face.normalize()
                f_face = l_face.cross(u_face)
                if f_face.length > 1e-6:
                    f_face.normalize()
                    root_yaw = math.atan2(f_face.x, -f_face.z)

    # 头/颈朝向：鼻子 + 左右耳构造头部坐标系，映射到 armature 后套到控制骨。
    head_rotation = None
    neck_rotation = None
    if head_turn and vis[0] >= 0.5 and vis[3] >= 0.5 and vis[4] >= 0.5:
        nose = _v3(kp[0])
        ear_l = _v3(kp[3])
        ear_r = _v3(kp[4])
        l_head = ear_l - ear_r
        if l_head.length > 1e-6:
            l_head.normalize()
            mid_ears = (ear_l + ear_r) * 0.5
            f_head = nose - mid_ears
            f_head = f_head - l_head * f_head.dot(l_head)
            if f_head.length > 1e-6:
                f_head.normalize()
                u_head = f_head.cross(l_head)
                if u_head.length > 1e-6:
                    u_head.normalize()
                    f_arm = r_body @ f_head
                    if f_arm.length > 1e-6:
                        f_arm.normalize()
                        # 只取“转头(yaw)”和少量“抬头/低头(pitch)”，不做 roll；
                        # 避免鼻子/耳朵的 3D 噪声把整个头拧歪。
                        yaw = math.atan2(f_arm.x, -f_arm.y)
                        pitch = math.asin(max(-1.0, min(1.0, f_arm.z)))
                        yaw = max(-math.radians(60.0),
                                  min(math.radians(60.0), yaw))
                        pitch = max(-math.radians(25.0),
                                    min(math.radians(25.0), pitch))
                        q_head_rest = rig.data.bones['head'].matrix_local.to_quaternion()
                        q_neck_rest = rig.data.bones['neck'].matrix_local.to_quaternion()
                        q_yaw = Quaternion((0.0, 0.0, 1.0), yaw)
                        q_pitch = Quaternion((1.0, 0.0, 0.0), -pitch * 0.5)
                        q_target = q_yaw @ q_pitch @ q_head_rest
                        head_rotation = q_target
                        neck_rotation = q_neck_rest.slerp(q_target, 0.35)

    def to_rig(p, shift):
        return H0 + shift + (r_body @ (p - hip_cap)) * scale

    def build(shift):
        # 躯干倾斜：在 capture 空间用“髋线 + 图像垂直方向”做全局参考，
        # 再把肩部姿态映射到 armature。位置映射仍用 R_body，所以四肢
        # 位置不受躯干旋转影响；腿弯也不会被误当成躯干前倾。
        u_cap = Vector((0.0, -1.0, 0.0))
        l_cap = _v3(kp[9]) - _v3(kp[10])
        l_cap = l_cap - u_cap * l_cap.dot(u_cap)
        if l_cap.length < 1e-6:
            l_cap = _v3(kp[5]) - _v3(kp[6])
            l_cap = l_cap - u_cap * l_cap.dot(u_cap)
        if l_cap.length < 1e-6:
            l_cap = Vector((1.0, 0.0, 0.0))
        l_cap.normalize()
        f_cap = l_cap.cross(u_cap)
        f_cap.normalize()
        l_cap = u_cap.cross(f_cap)
        l_cap.normalize()
        f_hip_cap = _pose_frame(f_cap, l_cap, u_cap)
        r_global = rest['hip_frame'] @ f_hip_cap.transposed()

        sh_mid_cap = (_v3(kp[5]) + _v3(kp[6])) * 0.5
        hip_mid_cap = (_v3(kp[9]) + _v3(kp[10])) * 0.5
        u_s = sh_mid_cap - hip_mid_cap
        if u_s.length < 1e-6:
            u_s = u_cap
        u_s.normalize()
        l_s = _v3(kp[5]) - _v3(kp[6])
        l_s = l_s - u_s * l_s.dot(u_s)
        if l_s.length < 1e-6:
            l_s = l_cap
        l_s.normalize()
        f_s = l_s.cross(u_s)
        f_s.normalize()
        l_s = u_s.cross(f_s)
        l_s.normalize()
        f_sh_cap = _pose_frame(f_s, l_s, u_s)

        if torso_lean and not global_root:
            f_sh_arm = r_global @ f_sh_cap
            r_delta = f_sh_arm @ rest['body_frame'].transposed()
            if r_delta.determinant() < 0.0:
                r_delta = Matrix.Identity(3)
            # 死区 + 缩放：单图 3D 深度噪声会让躯干“总是前倾”，12° 以内忽略；
            # 真弯腰时再按比例应用，最多 35°。
            q_delta = r_delta.to_quaternion()
            ang = abs(q_delta.angle)
            if ang < math.radians(8.0):
                r_delta = Matrix.Identity(3)
            else:
                applied = min(math.radians(35.0),
                              (ang - math.radians(8.0)) * 0.9)
                r_delta = Quaternion(q_delta.axis, applied).to_matrix()
        else:
            r_delta = Matrix.Identity(3)
        torso = (Matrix.Translation(H0 + shift)
                 @ r_delta.to_4x4()
                 @ Matrix.Translation(-H0)
                 @ rest['torso_rest'])

        shoulder_points = {}
        for S, idx in (('L', 5), ('R', 6)):
            shoulder_points[S] = to_rig(_v3(kp[idx]), shift)

        hands = {}
        hand_frames = {}
        for S, wrist_i, middle_i, index_i, pinky_i, thumb_i in (
                ('L', 62, 53, 49, 61, 42), ('R', 41, 32, 28, 40, 21)):
            if vis[wrist_i] < 0.5:
                warnings.append('手部关键点缺失：%s' % S)
                continue
            wrist = _v3(kp[wrist_i])
            middle = _v3(kp[middle_i]) if vis[middle_i] >= 0.5 else wrist
            index = _v3(kp[index_i]) if vis[index_i] >= 0.5 else wrist
            pinky = _v3(kp[pinky_i]) if vis[pinky_i] >= 0.5 else wrist
            thumb = _v3(kp[thumb_i]) if vis[thumb_i] >= 0.5 else wrist

            f = middle - wrist
            if f.length < 1e-4:
                f = index - wrist
            if f.length < 1e-4:
                f = thumb - wrist
            if f.length < 1e-4:
                f = r_body.transposed() @ Vector((0.0, -1.0, 0.0))
            if f.length < 1e-6:
                warnings.append('手部方向无法确定：%s' % S)
                continue
            f.normalize()

            l = index - pinky
            l = l - f * l.dot(f)
            if l.length < 1e-4:
                l = thumb - wrist
                l = l - f * l.dot(f)
            if l.length < 1e-4:
                l = f.cross(r_body.transposed() @ Vector((0.0, 0.0, 1.0)))
                l = l - f * l.dot(f)
            if l.length < 1e-6:
                warnings.append('手掌朝向无法确定：%s' % S)
                continue
            l.normalize()
            n = f.cross(l)
            n.normalize()
            # 手骨的 Y 是腕->中指根，Z 是食指->小指方向；所以列为 [X=n, Y=f, Z=l]
            f_cap = _pose_frame(n, f, l)
            hand_frames[S] = r_body @ f_cap

            target = to_rig(wrist, shift)
            target = _pose_clamp_reach(shoulder_points[S], target,
                                       rest['arm_max'] * 0.995)
            if (target - to_rig(wrist, shift)).length > 1e-5:
                warnings.append('手臂超出可达范围，已收缩：%s' % S)
            # 相对静止手掌坐标系求 delta，再套到控制骨静止朝向上
            f_rest = rest['hand_frame'][S]
            r_delta = (r_body @ f_cap) @ f_rest.transposed()
            q_rest = rig.data.bones['DEF-hand.' + S].matrix_local.to_quaternion()
            target_m = (Matrix.Translation(target)
                        @ (r_delta @ q_rest.to_matrix()).to_4x4())
            hands[S] = target_m

        # 手指：只取方向（r_body 旋转到 armature 静止坐标系），不取位置。
        # 这样即使手掌被手臂可达范围夹住，手指也不会被拉长/扭到图像里的位置。
        fingers = {}
        for S, wrist_i in (('L', 62), ('R', 41)):
            if vis[wrist_i] < 0.5:
                continue
            chains = []
            for fname, ids in POSE_FINGER_CHAINS.get(S, {}).items():
                if any(vis[i] < 0.5 for i in ids):
                    continue
                pts = [_v3(kp[i]) for i in ids]
                segs = [(b - a).length for a, b in zip(pts, pts[1:])]
                # 单图 3D 的手部点有时会塌陷/乱飘；明显不合理的整根手指跳过，
                # 不要让手指控制骨被拉成“触手”。
                if any(s < 0.003 or s > 0.12 for s in segs):
                    continue
                if (pts[3] - _v3(kp[wrist_i])).length > 0.40:
                    continue
                F_t = hand_frames.get(S)
                if F_t is None:
                    continue
                frames = []
                for i, (a, b) in enumerate(zip(pts, pts[1:]), 1):
                    d = b - a
                    if d.length < 1e-4:
                        break
                    y = r_body @ d
                    if y.length < 1e-6:
                        break
                    y.normalize()
                    bone_name = '%s.0%d.%s' % (fname, i, S)
                    coef = rest['finger_roll'].get(S, {}).get(bone_name)
                    if coef is None:
                        break
                    # 参考手掌坐标系里的 roll：x = F_t @ coef，再投影到指节方向。
                    # 只设 Y 方向（rotation_difference）会让手指绕自身轴乱滚。
                    x = F_t @ coef
                    x = x - y * x.dot(y)
                    if x.length < 0.05:
                        alt = F_t.col[0]
                        x = alt - y * alt.dot(y)
                    if x.length < 1e-4:
                        break
                    x.normalize()
                    z = x.cross(y)
                    R = Matrix(((x.x, y.x, z.x),
                                (x.y, y.y, z.y),
                                (x.z, y.z, z.z)))
                    frames.append((bone_name, R))
                if len(frames) == 3:
                    chains.append((fname, frames))
            if chains:
                fingers[S] = chains

        feet = {}
        for S, ankle_i, toe_i, heel_i in (
                ('L', 13, 15, 17), ('R', 14, 18, 20)):
            if vis[ankle_i] < 0.5:
                warnings.append('脚踝关键点缺失：%s' % S)
                continue
            ankle = _v3(kp[ankle_i])
            toe = _v3(kp[toe_i]) if vis[toe_i] >= 0.5 else ankle
            heel = _v3(kp[heel_i]) if vis[heel_i] >= 0.5 else ankle

            f_c = toe - ankle
            if f_c.length < 1e-4:
                f_c = r_body.transposed() @ Vector((0.0, -1.0, 0.0))
            if f_c.length < 1e-6:
                warnings.append('脚方向无法确定：%s' % S)
                continue
            f_c.normalize()
            u_raw = ankle - heel
            if u_raw.length < 1e-4:
                u_raw = r_body.transposed() @ Vector((0.0, 0.0, 1.0))
            u_c = u_raw - f_c * u_raw.dot(f_c)
            if u_c.length < 1e-6:
                u_c = r_body.transposed() @ Vector((0.0, 0.0, 1.0))
                u_c = u_c - f_c * u_c.dot(f_c)
            u_c.normalize()
            l_c = u_c.cross(f_c)
            l_c.normalize()
            u_c = f_c.cross(l_c)
            u_c.normalize()
            f_cap = _pose_frame(f_c, l_c, u_c)

            r_ankle, r_toe, r_heel = rest['foot_rest'][S]
            r_f = r_toe - r_ankle
            if r_f.length < 1e-6:
                continue
            r_f.normalize()
            r_u = (r_ankle - r_heel)
            r_u = r_u - r_f * r_u.dot(r_f)
            if r_u.length < 1e-6:
                continue
            r_u.normalize()
            r_l = r_u.cross(r_f)
            r_l.normalize()
            r_u = r_f.cross(r_l)
            r_u.normalize()
            f_rest = _pose_frame(r_f, r_l, r_u)

            target = to_rig(ankle, shift)
            if (target - r_ankle).length > 1.2 or target.z < -0.2:
                warnings.append('脚部目标异常，已跳过：%s' % S)
                continue
            r_delta = (r_body @ f_cap) @ f_rest.transposed()
            feet[S] = Matrix.Translation(target) @ r_delta.to_4x4()

        joints = {
            'shoulder_L': shoulder_points.get('L'),
            'shoulder_R': shoulder_points.get('R'),
            'elbow_L': to_rig(_v3(kp[7]), shift),
            'elbow_R': to_rig(_v3(kp[8]), shift),
            'wrist_L': to_rig(_v3(kp[62]), shift),
            'wrist_R': to_rig(_v3(kp[41]), shift),
            'hip_L': to_rig(_v3(kp[9]), shift),
            'hip_R': to_rig(_v3(kp[10]), shift),
            'knee_L': to_rig(_v3(kp[11]), shift),
            'knee_R': to_rig(_v3(kp[12]), shift),
            'ankle_L': to_rig(_v3(kp[13]), shift),
            'ankle_R': to_rig(_v3(kp[14]), shift),
        }

        return {
            'torso': torso,
            'shoulders_points': shoulder_points,
            'hands': hands,
            'hand_frames': hand_frames,
            'fingers': fingers,
            'forearm_refs': {
                S: hand_frames[S] @ rest['forearm_roll'][S]
                for S in hand_frames
                if rest['forearm_roll'].get(S) is not None},
            'feet': feet,
            'joints': joints,
            'head_rotation': head_rotation,
            'neck_rotation': neck_rotation,
            'warnings': warnings,
        }

    base = build(Vector((0.0, 0.0, 0.0)))
    shift = Vector((0.0, 0.0, 0.0))
    if ground and not global_root:
        zs = []
        for idx in (13, 14):
            if vis[idx] >= 0.5:
                zs.append(to_rig(_v3(kp[idx]), shift).z)
        if zs:
            dz = rest['rest_ankle_z'] - min(zs)
            up_arm = r_body @ up_cap
            if abs(dz) <= 0.6 and up_arm.z > 0.5:
                shift = Vector((0.0, 0.0, dz))
    targets = build(shift) if shift.length > 1e-9 else base
    targets['scale'] = scale
    targets['shift'] = shift
    targets['root_yaw'] = root_yaw
    targets['apply_root_yaw'] = bool(face_reference and not global_root)
    targets['root_rotation'] = root_rotation
    targets['global_root'] = global_root
    # 不只倒立：坐/躺/跪姿的最低点也不一定是脚。统一按整个网格的最低点贴地。
    targets['ground_via_mesh'] = bool(ground)
    targets['warnings'] = targets.get('warnings', [])
    return targets


def _pose_set_bone_matrix(rig, name, matrix_pose):
    pb = rig.pose.bones.get(name)
    if pb is None:
        return
    local = rig.convert_space(pose_bone=pb, matrix=matrix_pose,
                              from_space='POSE', to_space='LOCAL')
    pb.matrix_basis = local


def _pose_prepare_ik(rig):
    for side in ('L', 'R'):
        for name in ('upper_arm_parent.' + side, 'thigh_parent.' + side):
            pb = rig.pose.bones.get(name)
            if pb is None:
                continue
            if 'IK_FK' in pb:
                pb['IK_FK'] = 0.0
            if 'IK_Stretch' in pb:
                pb['IK_Stretch'] = 0.0


def _pose_reset_bones(rig):
    names = ['torso', 'shoulder.L', 'shoulder.R',
             'spine_fk', 'spine_fk.001', 'spine_fk.002', 'spine_fk.003',
             'neck', 'head',
             'hand_ik.L', 'hand_ik.R', 'foot_ik.L', 'foot_ik.R',
             'upper_arm_fk.L', 'upper_arm_fk.R',
             'forearm_fk.L', 'forearm_fk.R',
             'hand_fk.L', 'hand_fk.R',
             'thigh_fk.L', 'thigh_fk.R',
             'shin_fk.L', 'shin_fk.R',
             'foot_fk.L', 'foot_fk.R']
    for S in ('L', 'R'):
        for finger in ('thumb', 'f_index', 'f_middle', 'f_ring', 'f_pinky'):
            names.append('%s.01_master.%s' % (finger, S))
            for i in (1, 2, 3):
                names.append('%s.0%d.%s' % (finger, i, S))
    for name in names:
        pb = rig.pose.bones.get(name)
        if pb is not None:
            pb.matrix_basis = Matrix.Identity(4)


def _pose_prepare_fk(rig):
    for side in ('L', 'R'):
        for name in ('upper_arm_parent.' + side, 'thigh_parent.' + side):
            pb = rig.pose.bones.get(name)
            if pb is None:
                continue
            if 'IK_FK' in pb:
                pb['IK_FK'] = 1.0
            if 'IK_Stretch' in pb:
                pb['IK_Stretch'] = 0.0


def _pose_set_bone_direction(rig, name, direction):
    """把一根 FK 骨的 Y 轴转到给定方向（armature 空间）。"""
    pb = rig.pose.bones.get(name)
    if pb is None or direction is None:
        return
    direction = Vector(direction)
    if direction.length < 1e-6:
        return
    direction.normalize()
    root = pb.matrix.to_translation()
    rest_q = pb.bone.matrix_local.to_quaternion()
    rest_y = rest_q @ Vector((0.0, 1.0, 0.0))
    rest_y.normalize()
    q = rest_y.rotation_difference(direction)
    _pose_set_bone_matrix(
        rig, name,
        Matrix.Translation(root) @ (q @ rest_q).to_matrix().to_4x4())


def _pose_set_bone_frame(rig, name, rot):
    """把一根 FK 骨设成给定的 3x3 世界朝向（保留当前位置）。"""
    pb = rig.pose.bones.get(name)
    if pb is None or rot is None:
        return
    pos = pb.matrix.to_translation()
    _pose_set_bone_matrix(
        rig, name, Matrix.Translation(pos) @ rot.to_4x4())


def _pose_set_chain_bone(rig, name, target):
    """把一根 FK 骨的 Y 轴转向 root->target 方向。"""
    pb = rig.pose.bones.get(name)
    if pb is None or target is None:
        return
    _pose_set_bone_direction(rig, name, target - pb.matrix.to_translation())


def _pose_set_chain_bone_roll(rig, name, target, roll_ref):
    """Y 轴指向 target，同时用 roll_ref 决定绕 Y 的滚转。"""
    pb = rig.pose.bones.get(name)
    if pb is None:
        return
    if target is None or roll_ref is None:
        _pose_set_chain_bone(rig, name, target)
        return
    y = target - pb.matrix.to_translation()
    if y.length < 1e-6:
        return
    y.normalize()
    x = roll_ref - y * roll_ref.dot(y)
    if x.length < 1e-4:
        _pose_set_chain_bone(rig, name, target)
        return
    x.normalize()
    z = x.cross(y)
    R = Matrix(((x.x, y.x, z.x),
                (x.y, y.y, z.y),
                (x.z, y.z, z.z)))
    _pose_set_bone_frame(rig, name, R)


def _pose_apply_fingers(rig, targets, side=None):
    """手指控制是 FK 链：按近端→远端逐节套完整朝向（含 roll）。"""
    fingers = targets.get('fingers') or {}
    for S in ((side,) if side else ('L', 'R')):
        for _fname, frames in fingers.get(S, []):
            for bone_name, rot in frames:
                _pose_set_bone_frame(rig, bone_name, rot)
                bpy.context.view_layer.update()


def _pose_apply_torso_head(rig, targets):
    _pose_set_bone_matrix(rig, 'torso', targets['torso'])
    bpy.context.view_layer.update()

    # torso 是刚性主控，而参考图只有肩/髋两组点。先把“肩中心 -> 目标肩中心”
    # 的偏差分摊到脊椎 FK 上，让胸腔先弯过去；剩下的再由 shoulder 控制小范围
    # 平移修正。否则大侧弯时肩膀要硬拉十几厘米，网格会拉出尖角。
    pivots = {}
    for S in ('L', 'R'):
        pb = (rig.pose.bones.get('MCH-upper_arm_parent.' + S)
              or rig.pose.bones.get('upper_arm_ik.' + S))
        if pb is not None:
            pivots[S] = pb.matrix.to_translation()
    sp = targets.get('shoulders_points') or {}
    if len(pivots) == 2 and sp.get('L') is not None and sp.get('R') is not None:
        base_pb = rig.pose.bones.get('spine_fk.001')
        if base_pb is not None:
            cur = (pivots['L'] + pivots['R']) * 0.5
            tgt = (sp['L'] + sp['R']) * 0.5
            base = base_pb.matrix.to_translation()
            vc = cur - base
            vt = tgt - base
            if vc.length > 1e-4 and vt.length > 1e-4:
                q = vc.normalized().rotation_difference(vt.normalized())
                ang = min(abs(q.angle), math.radians(50.0))
                if ang > math.radians(3.0):
                    for name in ('spine_fk.001', 'spine_fk.002',
                                 'spine_fk.003'):
                        pb = rig.pose.bones.get(name)
                        if pb is None:
                            continue
                        inc = Quaternion(q.axis, ang / 3.0).to_matrix()
                        rot = inc @ pb.matrix.to_quaternion().to_matrix()
                        _pose_set_bone_matrix(
                            rig, name,
                            Matrix.Translation(pb.matrix.to_translation())
                            @ rot.to_4x4())
                        bpy.context.view_layer.update()

    for S in ('L', 'R'):
        pb = rig.pose.bones.get('shoulder.' + S)
        target = targets['shoulders_points'].get(S)
        if pb is None or target is None:
            continue
        # 目标点是肱骨头（手臂枢轴），不是锁骨根；用 MCH-upper_arm_parent 的
        # pose 位置算当前枢轴，避免把手/手臂整体平移 8 cm。
        pivot_pb = rig.pose.bones.get('MCH-upper_arm_parent.' + S)
        if pivot_pb is None:
            pivot_pb = rig.pose.bones.get('upper_arm_ik.' + S)
        if pivot_pb is None:
            continue
        current = pb.matrix.copy()
        delta = target - pivot_pb.matrix.to_translation()
        if delta.length > 0.10:
            targets.setdefault('warnings', []).append(
                '肩部位置修正超过 10 cm，已截断：%s（%.2f m）' % (S, delta.length))
            delta = delta.normalized() * 0.10
        _pose_set_bone_matrix(rig, 'shoulder.' + S,
                              Matrix.Translation(delta) @ current)
    bpy.context.view_layer.update()

    neck_q = targets.get('neck_rotation')
    if neck_q is not None:
        pb = rig.pose.bones.get('neck')
        if pb is not None:
            pos = pb.matrix.to_translation()
            _pose_set_bone_matrix(
                rig, 'neck',
                Matrix.Translation(pos) @ neck_q.to_matrix().to_4x4())
            bpy.context.view_layer.update()
    head_q = targets.get('head_rotation')
    if head_q is not None:
        pb = rig.pose.bones.get('head')
        if pb is not None:
            pos = pb.matrix.to_translation()
            _pose_set_bone_matrix(
                rig, 'head',
                Matrix.Translation(pos) @ head_q.to_matrix().to_4x4())
            bpy.context.view_layer.update()


def _pose_apply(rig, targets):
    _pose_prepare_ik(rig)
    _pose_reset_bones(rig)
    bpy.context.view_layer.update()
    _pose_apply_torso_head(rig, targets)

    for S in ('L', 'R'):
        if S in targets['hands']:
            _pose_set_bone_matrix(rig, 'hand_ik.' + S, targets['hands'][S])
    for S in ('L', 'R'):
        if S in targets['feet']:
            _pose_set_bone_matrix(rig, 'foot_ik.' + S, targets['feet'][S])
    bpy.context.view_layer.update()
    _pose_apply_fingers(rig, targets)
    _pose_apply_root_yaw(rig, targets)
    _pose_ground_mesh(rig, targets)
    return targets


def _pose_apply_root_yaw(rig, targets):
    pb = rig.pose.bones.get('root')
    if pb is None:
        return
    rot = targets.get('root_rotation')
    if rot is None and not targets.get('apply_root_yaw', True):
        return
    # 保留 root 当前的位移（根运动），旋转统一回到静止朝向 + 参考朝向，
    # 这样连续识别两张图不会把 yaw 累加。非直立时 rot 是完整的全局朝向。
    loc = pb.matrix.to_translation()
    rest_q = pb.bone.matrix_local.to_quaternion()
    if rot is not None:
        q_global = rot.to_quaternion()
    else:
        q_global = Quaternion((0.0, 0.0, 1.0),
                              float(targets.get('root_yaw') or 0.0))
    target_q = q_global @ rest_q
    _pose_set_bone_matrix(
        rig, 'root',
        Matrix.Translation(loc) @ target_q.to_matrix().to_4x4())
    bpy.context.view_layer.update()


def _pose_ground_mesh(rig, targets):
    """非直立姿势：按整个网格的最低点贴地（倒立时最低点是手/头）。"""
    if not targets.get('ground_via_mesh'):
        return
    pb = rig.pose.bones.get('root')
    mesh = _character_parts(rig)[2] if pb is not None else None
    if pb is None or mesh is None:
        return
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = mesh.evaluated_get(dg)
    me = ev.to_mesh()
    zs = [(ev.matrix_world @ v.co).z for v in me.vertices]
    ev.to_mesh_clear()
    if not zs:
        return
    m = pb.matrix.copy()
    m.translation.z -= min(zs)
    _pose_set_bone_matrix(rig, 'root', m)
    bpy.context.view_layer.update()


def _pose_apply_fk(rig, targets, ground=True):
    _pose_prepare_fk(rig)
    _pose_reset_bones(rig)
    bpy.context.view_layer.update()
    _pose_apply_torso_head(rig, targets)

    joints = targets.get('joints') or {}
    for S in ('L', 'R'):
        _pose_set_chain_bone(rig, 'upper_arm_fk.' + S,
                             joints.get('elbow_' + S))
        bpy.context.view_layer.update()
        # 前臂的滚转跟随手掌坐标系的“手背方向”，否则手腕/前臂网格会拧。
        _pose_set_chain_bone_roll(
            rig, 'forearm_fk.' + S, joints.get('wrist_' + S),
            (targets.get('forearm_refs') or {}).get(S))
        bpy.context.view_layer.update()
        hand = targets['hands'].get(S)
        pbh = rig.pose.bones.get('hand_fk.' + S)
        if hand is not None and pbh is not None:
            pos = pbh.matrix.to_translation()
            _pose_set_bone_matrix(
                rig, 'hand_fk.' + S,
                Matrix.Translation(pos) @ hand.to_quaternion().to_matrix().to_4x4())
            bpy.context.view_layer.update()
            _pose_apply_fingers(rig, targets, side=S)

        _pose_set_chain_bone(rig, 'thigh_fk.' + S,
                             joints.get('knee_' + S))
        bpy.context.view_layer.update()
        _pose_set_chain_bone(rig, 'shin_fk.' + S,
                             joints.get('ankle_' + S))
        bpy.context.view_layer.update()
        foot = targets['feet'].get(S)
        pbf = rig.pose.bones.get('foot_fk.' + S)
        if foot is not None and pbf is not None:
            pos = pbf.matrix.to_translation()
            rest_q = pbf.bone.matrix_local.to_quaternion()
            r_delta = foot.to_quaternion()
            _pose_set_bone_matrix(
                rig, 'foot_fk.' + S,
                Matrix.Translation(pos) @ (r_delta @ rest_q).to_matrix().to_4x4())
            bpy.context.view_layer.update()

    if ground and not targets.get('global_root'):
        rest_z = rig.data.bones['DEF-foot.L'].head_local.z
        zs = []
        for S in ('L', 'R'):
            pb = rig.pose.bones.get('DEF-foot.' + S)
            if pb is not None:
                zs.append(pb.matrix.to_translation().z)
        if zs:
            dz = rest_z - min(zs)
            if abs(dz) <= 0.6:
                ptorso = rig.pose.bones.get('torso')
                if ptorso is not None:
                    _pose_set_bone_matrix(
                        rig, 'torso',
                        Matrix.Translation(Vector((0.0, 0.0, dz)))
                        @ ptorso.matrix)
                    bpy.context.view_layer.update()
    _pose_apply_root_yaw(rig, targets)
    _pose_ground_mesh(rig, targets)
    return targets


def _pose_apply_payload(rig, payload, scene):
    if not payload.get('ok'):
        err = payload.get('error') or {}
        raise RuntimeError(err.get('message') or '姿态识别失败')
    kp, vis = _pose_payload_arrays(
        payload,
        mirror=bool(scene.character_pose_mirror),
        use_depth=float(scene.character_pose_depth))
    targets = _pose_build_targets(
        rig, kp, vis, ground=bool(scene.character_pose_ground),
        torso_lean=bool(getattr(scene, 'character_pose_torso', True)),
        head_turn=bool(getattr(scene, 'character_pose_head', True)),
        face_reference=bool(getattr(scene, 'character_pose_facing', True)))
    if not getattr(scene, 'character_pose_fingers', True):
        targets['fingers'] = {}
    if getattr(scene, 'character_pose_limbs', 'fk') == 'ik':
        _pose_apply(rig, targets)
    else:
        _pose_apply_fk(rig, targets,
                       ground=bool(scene.character_pose_ground))
    return targets


def _pose_summary(payload, targets):
    backend = payload.get('backend', '?')
    scale = targets.get('scale', 1.0)
    shift = targets.get('shift', Vector((0, 0, 0)))
    warnings = targets.get('warnings') or []
    text = '已应用 %s：缩放 %.2f，贴地偏移 %.3f m' % (backend, scale, shift.z)
    if warnings:
        text += '（%d 条提示）' % len(warnings)
    return text


# ---------------------------------------------------------------- 截图/图片任务

def _pose_parse_output(text):
    for line in reversed((text or '').splitlines()):
        if line.startswith(POSE_MARKER):
            try:
                return json.loads(line[len(POSE_MARKER):])
            except Exception:
                return None
    return None


def _pose_tag_redraw():
    try:
        wm = bpy.context.window_manager
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass


def _pose_log_tail(path, n=8192):
    try:
        with open(path, 'rb') as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - n))
            data = fh.read()
        return data.decode('utf-8', errors='replace')
    except OSError:
        return ''


def _pose_parse_progress(text):
    marker = 'RIGUE5_POSE_PROGRESS '
    for line in reversed((text or '').splitlines()):
        if not line.startswith(marker):
            continue
        rest = line[len(marker):].strip()
        parts = rest.split(' ', 1)
        try:
            frac = float(parts[0])
        except (TypeError, ValueError):
            continue
        stage = parts[1] if len(parts) > 1 else ''
        return max(0.0, min(1.0, frac)), stage
    return None


def _pose_progress_begin():
    global _POSE_PROGRESS_ACTIVE
    if _POSE_PROGRESS_ACTIVE:
        return
    try:
        bpy.ops.wm.progress_begin(min=0, max=100)
        _POSE_PROGRESS_ACTIVE = True
    except Exception:
        _POSE_PROGRESS_ACTIVE = False


def _pose_progress_end():
    global _POSE_PROGRESS_ACTIVE
    if not _POSE_PROGRESS_ACTIVE:
        return
    try:
        bpy.ops.wm.progress_end()
    except Exception:
        pass
    _POSE_PROGRESS_ACTIVE = False


def _pose_set_progress(scene, frac, stage):
    scene.character_pose_progress = float(frac)
    scene.character_pose_stage = stage or ''
    if _POSE_PROGRESS_ACTIVE:
        try:
            bpy.ops.wm.progress_update(int(max(0.0, min(1.0, frac)) * 100))
        except Exception:
            pass
    _pose_tag_redraw()


def _pose_kill_job(job):
    proc = job.get('proc')
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass


def _pose_finish_job(job_id):
    job = _POSE_JOBS.pop(job_id, None)
    if job is None:
        return
    if job.get('proc') is not None and job['proc'].poll() is None:
        _pose_kill_job(job)
    scene = bpy.data.scenes.get(job.get('scene')) or bpy.context.scene
    _pose_progress_end()
    scene.character_pose_progress = 0.0
    scene.character_pose_stage = ''
    _pose_tag_redraw()
    try:
        with open(job['out'], 'r', encoding='utf-8', errors='replace') as fh:
            stdout = fh.read()
    except OSError:
        stdout = ''
    try:
        with open(job['err'], 'r', encoding='utf-8', errors='replace') as fh:
            stderr = fh.read()
    except OSError:
        stderr = ''
    for path in (job['out'], job['err']):
        try:
            os.remove(path)
        except OSError:
            pass

    payload = _pose_parse_output(stdout)
    scene = bpy.data.scenes.get(job.get('scene')) or bpy.context.scene
    log_path = ''
    if payload is None or not payload.get('ok'):
        try:
            os.makedirs(POSE_LOCAL_ROOT, exist_ok=True)
            log_path = os.path.join(POSE_LOCAL_ROOT, 'last_error.log')
            with open(log_path, 'w', encoding='utf-8') as fh:
                fh.write('stdout:\n' + stdout + '\n\nstderr:\n' + stderr)
        except OSError:
            log_path = ''
    if payload is None:
        msg = '识别进程没有返回结果。'
        if stderr.strip():
            msg += ' 最后日志：' + stderr.strip().splitlines()[-1][:160]
        if log_path:
            msg += ' / 完整日志：' + log_path
        scene.character_pose_message = msg
        print('[pose]', msg)
        return
    if not payload.get('ok'):
        err = payload.get('error') or {}
        msg = err.get('message') or '姿态识别失败'
        hint = err.get('hint') or ''
        if hint:
            msg += ' / ' + hint.splitlines()[0][:120]
        if log_path:
            msg += ' / 日志：' + log_path
        scene.character_pose_message = msg
        print('[pose]', msg)
        return

    rig = bpy.data.objects.get(job.get('rig'))
    if rig is None:
        scene.character_pose_message = '识别完成，但找不到原来的 rig。'
        return
    try:
        targets = _pose_apply_payload(rig, payload, scene)
        scene.character_pose_message = _pose_summary(payload, targets)
        try:
            os.remove(os.path.join(POSE_LOCAL_ROOT, 'last_error.log'))
        except OSError:
            pass
        try:
            bpy.ops.ed.undo_push(message='姿态捕捉')
        except Exception:
            pass
    except Exception as exc:
        scene.character_pose_message = '应用姿态失败：%s' % exc
        print('[pose]', scene.character_pose_message)


def _pose_poll_jobs():
    global _POSE_TIMER
    if not _POSE_JOBS:
        _POSE_TIMER = False
        return None
    now = time.time()
    for job_id, job in list(_POSE_JOBS.items()):
        proc = job.get('proc')
        if proc is None:
            _pose_finish_job(job_id)
            continue
        if proc.poll() is None:
            elapsed = now - job['start']
            if elapsed > job['timeout']:
                _pose_kill_job(job)
                job['timeout'] = True
                _pose_finish_job(job_id)
                continue
            scene = bpy.data.scenes.get(job.get('scene'))
            if scene is not None:
                prog = _pose_parse_progress(_pose_log_tail(job['err']))
                if prog is None:
                    expected = job.get('expected', 30.0)
                    frac = min(0.9, 0.03 + (elapsed / expected) * 0.85)
                    stage = job.get('pending_stage') or '正在识别…'
                else:
                    frac, stage = prog
                stage = '%s（%ds）' % (stage, int(elapsed))
                _pose_set_progress(scene, frac, stage)
            continue
        _pose_finish_job(job_id)
    if _POSE_JOBS:
        return 0.3
    # 最后一个任务在本 tick 内完成：返回 None 会让 Blender 注销定时器，
    # 必须同时把标志复位，否则下一个任务不会再注册定时器（卡在 2%）。
    _POSE_TIMER = False
    return None


def _pose_ensure_timer():
    global _POSE_TIMER
    try:
        if bpy.app.timers.is_registered(_pose_poll_jobs):
            _POSE_TIMER = True
            return
    except Exception:
        pass
    try:
        bpy.app.timers.register(_pose_poll_jobs, first_interval=0.3)
        _POSE_TIMER = True
    except Exception:
        _POSE_TIMER = False


def _pose_start_job(context, mode, image_path=''):
    global _POSE_JOB_SEQ
    scene = context.scene
    rig = _find_rig(context.active_object)
    if rig is None:
        raise RuntimeError('请先选中角色的 rig。')
    backend = _pose_choose_backend(scene)
    if backend == 'sam3d' and not _pose_sam3d_ckpt(scene):
        raise RuntimeError(
            '没有找到 SAM 3D Body 权重。\n'
            '下载：%s\n放到：%s' % (POSE_DOWNLOAD_URL, POSE_DETECTION_DIR))
    python = _pose_python_for(backend, scene)
    helper = _ensure_pose_helper()

    request = {
        'protocol': 1,
        'mode': mode,
        'backend': backend,
        'image_path': image_path,
        'model_dir': POSE_LOCAL_MODELS,
        'comfy_root': _pose_comfy_root(scene),
        'refine_hands': bool(getattr(scene, 'character_pose_fingers', True)),
        'save_capture': mode in ('clipboard', 'screenshot'),
        'capture_dir': os.path.join(POSE_LOCAL_ROOT, 'captures'),
    }
    if backend == 'sam3d':
        request['model_path'] = _pose_sam3d_ckpt(scene)
    elif backend == 'mediapipe':
        request['model_path'] = _pose_mediapipe_path(scene)

    os.makedirs(POSE_LOCAL_ROOT, exist_ok=True)
    out_fh = tempfile.NamedTemporaryFile(
        prefix='rigue5_pose_', suffix='.out', delete=False,
        mode='w', encoding='utf-8')
    err_fh = tempfile.NamedTemporaryFile(
        prefix='rigue5_pose_', suffix='.err', delete=False,
        mode='w', encoding='utf-8')
    out_path, err_path = out_fh.name, err_fh.name
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    env['RIGUE5_COMFY_ROOT'] = _pose_comfy_root(scene)
    env['RIGUE5_POSE_PYTHON'] = python
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    cwd = _pose_comfy_root(scene) if backend == 'sam3d' else None
    try:
        proc = subprocess.Popen(
            [python, helper], stdin=subprocess.PIPE,
            stdout=out_fh, stderr=err_fh, text=True, encoding='utf-8',
            errors='replace', cwd=cwd, env=env, creationflags=creationflags)
        out_fh.close()
        err_fh.close()
        try:
            proc.stdin.write(json.dumps(request, ensure_ascii=False))
            proc.stdin.close()
        except Exception:
            pass
    except Exception:
        out_fh.close()
        err_fh.close()
        try:
            os.remove(out_path)
            os.remove(err_path)
        except OSError:
            pass
        raise

    _POSE_JOB_SEQ += 1
    job_id = _POSE_JOB_SEQ
    timeout = 600 if backend == 'sam3d' else 240
    if mode == 'screenshot':
        pending_stage = '等待截图框选…'
        expected = 30.0
    elif mode == 'clipboard':
        pending_stage = '读取剪贴板…'
        expected = 8.0
    else:
        pending_stage = '读取图片…'
        expected = 8.0
    if backend == 'sam3d':
        expected = 40.0
    _POSE_JOBS[job_id] = {
        'proc': proc,
        'out': out_path,
        'err': err_path,
        'start': time.time(),
        'timeout': timeout,
        'rig': rig.name,
        'scene': scene.name,
        'backend': backend,
        'mode': mode,
        'expected': expected,
        'pending_stage': pending_stage,
    }
    scene.character_pose_message = ''
    _pose_progress_begin()
    _pose_set_progress(scene, 0.02, pending_stage)
    _pose_ensure_timer()


def _pose_cancel_all(scene=None):
    for job_id in list(_POSE_JOBS.keys()):
        job = _POSE_JOBS.pop(job_id, None)
        if job is None:
            continue
        _pose_kill_job(job)
        for path in (job.get('out'), job.get('err')):
            try:
                if path:
                    os.remove(path)
            except OSError:
                pass
    _pose_progress_end()
    if scene is not None:
        scene.character_pose_progress = 0.0
        scene.character_pose_stage = ''
        scene.character_pose_message = '已取消姿态识别。'
        _pose_tag_redraw()


# ---------------------------------------------------------------- 姿态捕捉 operator

class CHARACTER_OT_pose_from_image(bpy.types.Operator):
    """选择一张图片，自动识别姿态并套到当前 rig"""
    bl_idname = 'character.pose_from_image'
    bl_label = '图片 ➜ 姿态'
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')

    def invoke(self, context, event):
        if _find_rig(context.active_object) is None:
            self.report({'ERROR'}, '请先选中角色的 rig')
            return {'CANCELLED'}
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = self.filepath
        if not path or not os.path.isfile(path):
            self.report({'ERROR'}, '图片不存在：%s' % path)
            return {'CANCELLED'}
        ext = os.path.splitext(path)[1].lower()
        if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'):
            self.report({'ERROR'}, '不支持的图片格式：%s' % ext)
            return {'CANCELLED'}
        try:
            _pose_start_job(context, 'image', path)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            context.scene.character_pose_message = str(exc)
            return {'CANCELLED'}
        return {'FINISHED'}


class CHARACTER_OT_pose_from_clipboard(bpy.types.Operator):
    """读取剪贴板里的图片并摆姿势"""
    bl_idname = 'character.pose_from_clipboard'
    bl_label = '剪贴板 ➜ 姿态'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            _pose_start_job(context, 'clipboard')
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            context.scene.character_pose_message = str(exc)
            return {'CANCELLED'}
        return {'FINISHED'}


class CHARACTER_OT_pose_from_screen(bpy.types.Operator):
    """调起 Windows 截图，框选后自动摆姿势"""
    bl_idname = 'character.pose_from_screen'
    bl_label = '截图 ➜ 姿态'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            _pose_start_job(context, 'screenshot')
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            context.scene.character_pose_message = str(exc)
            return {'CANCELLED'}
        return {'FINISHED'}


class CHARACTER_OT_pose_cancel(bpy.types.Operator):
    """取消正在等待的截图/识别任务"""
    bl_idname = 'character.pose_cancel'
    bl_label = '取消姿态识别'
    bl_options = {'REGISTER'}

    def execute(self, context):
        _pose_cancel_all(context.scene)
        return {'FINISHED'}


class CHARACTER_OT_pose_env_check(bpy.types.Operator):
    """检查 ComfyUI / SAM 3D Body / InstantHMR / MediaPipe 环境"""
    bl_idname = 'character.pose_env_check'
    bl_label = '检查姿态识别环境'
    bl_options = {'REGISTER'}

    def execute(self, context):
        status = _pose_env_status(context.scene)
        context.scene.character_pose_env_report = json.dumps(
            status, ensure_ascii=False)
        context.scene.character_pose_message = status['label']
        return {'FINISHED'}


class CHARACTER_OT_pose_open_log(bpy.types.Operator):
    """打开上一次姿态识别的错误日志"""
    bl_idname = 'character.pose_open_log'
    bl_label = '打开姿态识别日志'
    bl_options = {'REGISTER'}

    def execute(self, context):
        path = os.path.join(POSE_LOCAL_ROOT, 'last_error.log')
        if not os.path.isfile(path):
            self.report({'INFO'}, '还没有错误日志。')
            return {'CANCELLED'}
        try:
            os.startfile(path)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class CHARACTER_OT_pose_open_downloads(bpy.types.Operator):
    """在浏览器里打开 SAM 3D Body 权重下载页"""
    bl_idname = 'character.pose_open_downloads'
    bl_label = '打开模型下载页'
    bl_options = {'REGISTER'}

    def execute(self, context):
        import webbrowser
        webbrowser.open(POSE_DOWNLOAD_URL)
        return {'FINISHED'}


# ---------------------------------------------------------------- 动作选择
# Blender 4.4+ 的 Action 分「槽位」（slot），每个槽位绑定一个物体。
# 动作列表只显示能驱动这个 rig 的，避免双角色时选到 B_rig 的动作。

def _action_slots(action):
    return list(getattr(action, 'slots', []) or [])


def _slot_matches_rig(slot, rig):
    if getattr(slot, 'target_id_type', 'OBJECT') != 'OBJECT':
        return False
    return (slot.name_display == rig.name
            or getattr(slot, 'identifier', '') == 'OB' + rig.name)


def _action_fits_rig(action, rig):
    slots = _action_slots(action)
    if not slots:          # 4.4 以前的旧动作，没有槽位概念
        return True
    return any(_slot_matches_rig(s, rig) for s in slots)


def _any_object_slot(action):
    slots = _action_slots(action)
    if not slots:
        return True
    return any(getattr(s, 'target_id_type', 'OBJECT') == 'OBJECT' for s in slots)


def actions_for_rig(rig):
    """当前 rig 能用的动作：优先按槽位名过滤；都被过滤掉时退回所有物体动作。"""
    acts = [a for a in bpy.data.actions if _action_fits_rig(a, rig)]
    if not acts:
        acts = [a for a in bpy.data.actions if _any_object_slot(a)]
    return sorted(acts, key=lambda a: a.name.lower())


def action_frame_range(action):
    start, end = action.frame_range
    start = int(math.floor(start + 0.5))
    end = int(math.ceil(end - 0.5))
    return start, max(start, end)


def _pick_action_slot(action, obj):
    """在动作的槽位里挑一个给 obj 用的（Blender 4.4+）。"""
    slots = _action_slots(action)
    if not slots:
        return None
    obj_slots = [s for s in slots
                 if getattr(s, 'target_id_type', 'OBJECT') == 'OBJECT']
    for s in obj_slots:
        if _slot_matches_rig(s, obj):
            return s
    return obj_slots[0] if obj_slots else slots[0]


def _assign_action(obj, action):
    """切到指定动作；切完如果槽位没自动对上，就手动补一个。"""
    ad = obj.animation_data or obj.animation_data_create()
    ad.action = action
    if hasattr(ad, 'action_slot') and getattr(ad, 'action_slot', None) is None:
        slot = _pick_action_slot(action, obj)
        if slot is not None:
            try:
                ad.action_slot = slot
            except (TypeError, AttributeError):
                pass
    return ad


def _capture_pose(obj):
    """记下物体和所有骨骼当前的变换，导出完用于还原。"""
    return {
        'object': (tuple(obj.location), tuple(obj.rotation_euler),
                   tuple(obj.rotation_quaternion), tuple(obj.rotation_axis_angle),
                   tuple(obj.scale)),
        'bones': {pb.name: (tuple(pb.location), tuple(pb.rotation_euler),
                            tuple(pb.rotation_quaternion),
                            tuple(pb.rotation_axis_angle), tuple(pb.scale))
                  for pb in obj.pose.bones},
    }


def _restore_pose(obj, state):
    obj.location = state['object'][0]
    obj.rotation_euler = state['object'][1]
    obj.rotation_quaternion = state['object'][2]
    obj.rotation_axis_angle = state['object'][3]
    obj.scale = state['object'][4]
    for name, vals in state['bones'].items():
        pb = obj.pose.bones.get(name)
        if pb is not None:
            (pb.location, pb.rotation_euler, pb.rotation_quaternion,
             pb.rotation_axis_angle, pb.scale) = vals


def _reset_pose(obj):
    """清到静止姿势。

    切动作时 Blender 不会重置动作里没有 K 帧的通道，会把上一段动作最后一帧的
    姿势/位移留在身上（根运动尤其明显：原地动作会带上前一段的位移）。
    导出前清一次，保证每个动作都是独立的。
    """
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    obj.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)
    for pb in obj.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)


def _menu_actions(context):
    """当前 rig 可选的动作；选中的不是 rig 时退回全部物体动作。"""
    rig = _find_rig(getattr(context, 'active_object', None))
    if rig is not None:
        return actions_for_rig(rig)
    return sorted((a for a in bpy.data.actions if _any_object_slot(a)),
                  key=lambda a: a.name.lower())


def duplicate_character(rig, prefix='B_', offset=(1.3, 0.0, 0.0)):
    helpers, root, mesh = _character_parts(rig)
    if root is None or mesh is None:
        raise RuntimeError('找不到这个角色的 UE 骨架或网格（RTG_ 空物体是否还在？）')

    group = [rig, root, mesh] + helpers
    hidden = {o: o.hide_get() for o in group}
    for o in group:
        o.hide_set(False)

    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in bpy.data.objects:
        o.select_set(False)
    for o in group:
        o.select_set(True)
    bpy.context.view_layer.objects.active = rig

    before = set(bpy.data.objects)
    bpy.ops.object.duplicate(linked=False)
    copies = [o for o in bpy.data.objects if o not in before]

    for o, h in hidden.items():
        o.hide_set(h)

    for o in copies:
        o.name = prefix + _strip_suffix(o.name)
        if o.data is not None:
            o.data.name = o.name

    new_rig = next((o for o in copies if o.type == 'ARMATURE'
                    and o.data.bones.get('DEF-spine')), None)
    new_root = next((o for o in copies if o.type == 'ARMATURE' and o is not new_rig), None)
    new_mesh = next((o for o in copies if o.type == 'MESH'
                     and len(o.data.vertices) > 10000), None)

    off = Vector(offset)
    for o in (new_rig, new_root):
        if o is not None:
            o.location = o.location + off

    coll = bpy.data.collections.get(prefix.rstrip('_') + ' character')
    if coll is None:
        coll = bpy.data.collections.new(prefix.rstrip('_') + ' character')
        bpy.context.scene.collection.children.link(coll)
    for o in copies:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
        o.hide_set(True)

    return new_rig.name if new_rig else '?', len(copies)


class CHARACTER_OT_duplicate(bpy.types.Operator):
    """把当前角色整套复制一份（骨架+网格+重定向空物体），互不影响"""
    bl_idname = 'character.duplicate_character'
    bl_label = '复制当前角色'
    bl_options = {'REGISTER', 'UNDO'}

    prefix: bpy.props.StringProperty(name='名称前缀', default='B_')
    offset: bpy.props.FloatVectorProperty(name='位置偏移', default=(1.3, 0.0, 0.0),
                                          subtype='TRANSLATION', unit='LENGTH')

    def execute(self, context):
        rig = _find_rig(context.active_object)
        if rig is None:
            self.report({'ERROR'}, '请先选中角色的 rig')
            return {'CANCELLED'}
        try:
            name, count = duplicate_character(rig, self.prefix, self.offset)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, '已复制 %d 个对象，新骨架：%s' % (count, name))
        return {'FINISHED'}


def export_character(rig, filepath, action=None):
    """导出这个角色的 root + 网格，动画（含根运动）一起烘焙进 FBX。

    action 为动作名（或 Action 对象）时，临时切到该动作、按它自己的帧范围导出，
    导出完再把当前动作和场景帧范围还原；为 None 时按场景时间轴导出（旧行为）。
    """
    helpers, root, mesh = _character_parts(rig)
    if root is None or mesh is None:
        raise RuntimeError('找不到 UE 骨架或网格')

    scene = bpy.context.scene
    ad = rig.animation_data
    saved_action = ad.action if ad else None
    saved_slot = getattr(ad, 'action_slot', None) if ad else None
    saved_range = (scene.frame_start, scene.frame_end)
    saved_frame = scene.frame_current
    saved_pose = None

    act = None
    if action:
        act = action if isinstance(action, bpy.types.Action) else bpy.data.actions.get(action)
        if act is None:
            raise RuntimeError('找不到动作：%s' % action)
        start, end = action_frame_range(act)

    hidden = root.hide_get()
    try:
        if act is not None:
            saved_pose = _capture_pose(rig)
            _reset_pose(rig)
            ad = _assign_action(rig, act)
            scene.frame_start, scene.frame_end = start, end
        root.hide_set(False)
        for o in bpy.data.objects:
            o.select_set(False)
        root.select_set(True)
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = root
        bpy.ops.export_scene.fbx(
            filepath=filepath,
            use_selection=True,
            object_types={'ARMATURE', 'MESH'},
            bake_anim=True,
            bake_anim_use_all_bones=True,
            bake_anim_use_nla_strips=False,
            bake_anim_use_all_actions=False,
            bake_anim_force_startend_keying=True,
            bake_anim_step=1,
            bake_anim_simplify_factor=0.0,
            add_leaf_bones=False,
            primary_bone_axis='Y',
            secondary_bone_axis='X',
        )
    finally:
        root.hide_set(hidden)
        if act is not None:
            scene.frame_start, scene.frame_end = saved_range
            if ad is not None:
                ad.action = saved_action
                if saved_action is not None and saved_slot is not None \
                        and hasattr(ad, 'action_slot'):
                    try:
                        ad.action_slot = saved_slot
                    except (TypeError, AttributeError):
                        pass
            scene.frame_set(saved_frame)
            if saved_pose is not None:
                _restore_pose(rig, saved_pose)
    return root.name


class CHARACTER_OT_toggle_ue(bpy.types.Operator):
    """在视口里显示/隐藏 UE 骨架，导出 FBX 前需要它可见可选"""
    bl_idname = 'character.toggle_ue_skeleton'
    bl_label = '显示 UE 骨架（导出用）'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = _find_rig(context.active_object)
        if rig is None:
            self.report({'ERROR'}, '请先选中角色的 rig')
            return {'CANCELLED'}
        parts = _character_parts(rig)
        root = parts[1]
        mesh = parts[2]
        if root is None:
            self.report({'ERROR'}, '找不到 UE 骨架')
            return {'CANCELLED'}
        show = root.hide_get()
        root.hide_set(not show)
        if show:
            for o in bpy.data.objects:
                o.select_set(False)
            root.select_set(True)
            if mesh:
                mesh.select_set(True)
            self.report({'INFO'}, '已显示并选中 %s + 网格，可以导出 FBX 了' % root.name)
        else:
            self.report({'INFO'}, '已隐藏 UE 骨架')
        return {'FINISHED'}


class CHARACTER_OT_export_fbx(bpy.types.Operator):
    """把当前角色导出成 FBX（动画 + 根运动一起烘焙）"""
    bl_idname = 'character.export_fbx'
    bl_label = '导出 FBX（含根运动）'
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    action: bpy.props.StringProperty(
        name='动作', default='', options={'HIDDEN'},
        description='要导出的动作名；留空则用面板「动作」菜单的选择')

    def invoke(self, context, event):
        rig = _find_rig(context.active_object)
        if rig is None:
            self.report({'ERROR'}, '请先选中角色的 rig')
            return {'CANCELLED'}
        if not self.filepath:
            base = bpy.path.basename(bpy.data.filepath)
            base = base.rsplit('.', 1)[0] if base else 'character'
            self.filepath = bpy.path.abspath('//%s_export.fbx' % base)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        rig = _find_rig(context.active_object)
        if rig is None:
            self.report({'ERROR'}, '请先选中角色的 rig')
            return {'CANCELLED'}
        action = self.action.strip()
        if not action:
            action = getattr(context.scene, 'character_export_action', '').strip()
        path = bpy.path.ensure_ext(self.filepath, '.fbx')
        try:
            root_name = export_character(rig, path, action or None)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if action:
            self.report({'INFO'}, '已导出 %s（动作 %s）到 %s' % (root_name, action, path))
        else:
            self.report({'INFO'}, '已导出 %s 到 %s' % (root_name, path))
        return {'FINISHED'}


class CHARACTER_OT_set_export_action(bpy.types.Operator):
    """记录「要导出的动作」；空字符串表示按场景时间轴导出"""
    bl_idname = 'character.set_export_action'
    bl_label = '选择导出动作'
    bl_options = {'INTERNAL'}

    action: bpy.props.StringProperty(default='')

    def execute(self, context):
        context.scene.character_export_action = self.action
        return {'FINISHED'}


class CHARACTER_MT_export_actions(bpy.types.Menu):
    bl_idname = 'CHARACTER_MT_export_actions'
    bl_label = '导出动作'

    def draw(self, context):
        layout = self.layout
        selected = getattr(context.scene, 'character_export_action', '')
        op = layout.operator('character.set_export_action',
                             text='当前时间轴（不切换动作）',
                             icon='CHECKMARK' if not selected else 'TIME')
        op.action = ''
        acts = _menu_actions(context)
        if acts:
            layout.separator()
        for act in acts:
            start, end = action_frame_range(act)
            op = layout.operator(
                'character.set_export_action',
                text='%s   （帧 %d - %d）' % (act.name, start, end),
                icon='CHECKMARK' if act.name == selected else 'ACTION')
            op.action = act.name


class VIEW3D_PT_character_tools(bpy.types.Panel):
    bl_label = '角色工具'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Rigify'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        ob = context.active_object
        is_rig = _find_rig(ob) is not None
        col = layout.column(align=True)
        col.enabled = is_rig
        col.operator('character.duplicate_character', icon='DUPLICATE', text='复制当前角色')
        col.operator('character.toggle_ue_skeleton', icon='HIDE_OFF', text='显示/隐藏 UE 骨架')
        col.separator()
        selected = getattr(scene, 'character_export_action', '')
        act = bpy.data.actions.get(selected) if selected else None
        col.menu('CHARACTER_MT_export_actions', icon='ACTION',
                 text='动作：' + (act.name if act else '当前时间轴'))
        if selected and act is None:
            col.label(text='动作已不存在：%s' % selected, icon='ERROR')
        elif act is not None:
            start, end = action_frame_range(act)
            col.label(text='按动作帧范围：%d - %d' % (start, end), icon='ACTION')
        else:
            col.label(text='按时间轴导出：帧 %d - %d' % (
                scene.frame_start, scene.frame_end), icon='TIME')
        col.operator('character.export_fbx', icon='EXPORT', text='导出 FBX（含根运动）')
        if not is_rig:
            layout.label(text='先选中角色的 rig', icon='INFO')
        layout.label(text='根运动：移动 rig 或 Pose 的 root（含旋转）', icon='BLANK1')

        # ---- 姿态捕捉 -------------------------------------------------
        box = layout.box()
        box.label(text='姿态捕捉（截图/图片）', icon='TRACKER')
        pcol = box.column(align=True)
        pcol.enabled = is_rig
        pcol.prop(scene, 'character_pose_backend', text='后端')
        pcol.prop(scene, 'character_pose_model_path', text='SAM3D 权重')
        pcol.operator('character.pose_from_image', text='图片 ➜ 姿态',
                      icon='IMAGE_DATA')
        pcol.operator('character.pose_from_screen', text='截图 ➜ 姿态',
                      icon='FULLSCREEN_ENTER')
        pcol.operator('character.pose_from_clipboard', text='剪贴板 ➜ 姿态',
                      icon='PASTEDOWN')
        row = pcol.row(align=True)
        row.prop(scene, 'character_pose_ground', text='贴地')
        row.prop(scene, 'character_pose_depth', text='深度')
        row.prop(scene, 'character_pose_mirror', text='镜像')
        row2 = pcol.row(align=True)
        row2.prop(scene, 'character_pose_torso', text='躯干倾斜')
        row2.prop(scene, 'character_pose_head', text='头/颈转向')
        row3 = pcol.row(align=True)
        row3.prop(scene, 'character_pose_facing', text='匹配朝向')
        row3.prop(scene, 'character_pose_limbs', text='四肢')
        row4 = pcol.row(align=True)
        row4.prop(scene, 'character_pose_fingers', text='手指')
        if scene.character_pose_message:
            box.label(text=scene.character_pose_message, icon='INFO')
        if scene.character_pose_stage:
            box.label(text=scene.character_pose_stage, icon='TIME')
        progress = float(scene.character_pose_progress)
        if 0.0 < progress < 1.0:
            pct = int(round(progress * 100))
            filled = max(0, min(20, pct // 5))
            bar = '#' * filled + '.' * (20 - filled)
            box.label(text='%s %3d%%' % (bar, pct), icon='BLANK1')
        status = _pose_env_status(scene)
        srow = box.row(align=True)
        srow.label(text='环境：' + status['label'], icon=status['icon'])
        srow.operator('character.pose_env_check', text='', icon='FILE_REFRESH')
        lrow = box.row(align=True)
        lrow.operator('character.pose_cancel', text='取消识别', icon='CANCEL')
        lrow.operator('character.pose_open_log', text='打开日志', icon='TEXT')
        if not status['any']:
            box.label(text='SAM 3D Body：把 sam_3d_body_dinov3_bf16.safetensors 放到 detection',
                      icon='ERROR')
            box.operator('character.pose_open_downloads',
                         text='打开模型下载页', icon='URL')


def register():
    for cls in (CHARACTER_OT_duplicate, CHARACTER_OT_export_fbx,
                CHARACTER_OT_toggle_ue, CHARACTER_OT_set_export_action,
                CHARACTER_MT_export_actions,
                CHARACTER_OT_pose_from_image, CHARACTER_OT_pose_from_clipboard,
                CHARACTER_OT_pose_from_screen, CHARACTER_OT_pose_cancel,
                CHARACTER_OT_pose_env_check, CHARACTER_OT_pose_open_log,
                CHARACTER_OT_pose_open_downloads,
                VIEW3D_PT_character_tools):
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            bpy.utils.unregister_class(cls)
            bpy.utils.register_class(cls)
    bpy.types.Scene.character_export_action = bpy.props.StringProperty(
        name='动作',
        description='要导出的动作名（按动作自己的帧范围烘焙）；留空表示按场景时间轴',
        default='')
    bpy.types.Scene.character_pose_backend = bpy.props.EnumProperty(
        name='姿态识别后端',
        description='自动：优先 SAM 3D Body，其次 InstantHMR，最后 MediaPipe',
        items=[
            ('auto', '自动', '优先 SAM 3D Body，其次 InstantHMR，最后 MediaPipe'),
            ('sam3d', 'SAM 3D Body', '使用 ComfyUI 里的 SAM 3D Body'),
            ('instanthmr', 'InstantHMR', '公开 ONNX 兜底'),
            ('mediapipe', 'MediaPipe', '轻量兜底 / bbox'),
        ],
        default='auto')
    bpy.types.Scene.character_pose_ground = bpy.props.BoolProperty(
        name='贴地',
        description='按整个网格的最低点贴地（直立是脚、坐/躺是背/臀、倒立是手/头）',
        default=True)
    bpy.types.Scene.character_pose_depth = bpy.props.FloatProperty(
        name='深度', min=0.0, max=1.0, default=0.7)
    bpy.types.Scene.character_pose_mirror = bpy.props.BoolProperty(
        name='镜像', default=False)
    bpy.types.Scene.character_pose_torso = bpy.props.BoolProperty(
        name='躯干倾斜', default=True)
    bpy.types.Scene.character_pose_head = bpy.props.BoolProperty(
        name='头/颈转向', default=True)
    bpy.types.Scene.character_pose_facing = bpy.props.BoolProperty(
        name='匹配朝向', default=True)
    bpy.types.Scene.character_pose_fingers = bpy.props.BoolProperty(
        name='手指',
        description='用 MHR70 的手部关键点摆手指（SAM 3D Body 会顺手部精修）',
        default=True)
    bpy.types.Scene.character_pose_limbs = bpy.props.EnumProperty(
        name='四肢',
        description='FK：肘/膝更贴近参考；IK：手/脚落点更精确',
        items=[('fk', 'FK', '按参考的肩-肘-腕/髋-膝-踝方向摆 FK 骨'),
               ('ik', 'IK', '用 IK 把手/脚放到参考位置，肘/膝由 IK 平面决定')],
        default='fk')
    bpy.types.Scene.character_pose_message = bpy.props.StringProperty(
        name='姿态捕捉状态', default='')
    bpy.types.Scene.character_pose_stage = bpy.props.StringProperty(
        name='姿态识别阶段', default='')
    bpy.types.Scene.character_pose_progress = bpy.props.FloatProperty(
        name='姿态识别进度', min=0.0, max=1.0, default=0.0)
    bpy.types.Scene.character_pose_env_report = bpy.props.StringProperty(
        name='姿态识别环境', default='')
    bpy.types.Scene.character_pose_comfy_python = bpy.props.StringProperty(
        name='ComfyUI Python', subtype='FILE_PATH', default='')
    bpy.types.Scene.character_pose_sys_python = bpy.props.StringProperty(
        name='系统 Python', subtype='FILE_PATH', default='')
    bpy.types.Scene.character_pose_comfy_root = bpy.props.StringProperty(
        name='ComfyUI 根目录', subtype='DIR_PATH', default='')
    bpy.types.Scene.character_pose_model_path = bpy.props.StringProperty(
        name='SAM 3D Body 权重', subtype='FILE_PATH', default='')


def unregister():
    if hasattr(bpy.types.Scene, 'character_export_action'):
        del bpy.types.Scene.character_export_action
    for name in ('character_pose_backend', 'character_pose_ground',
                 'character_pose_depth', 'character_pose_mirror',
                 'character_pose_torso', 'character_pose_head',
                 'character_pose_facing', 'character_pose_limbs',
                 'character_pose_fingers',
                 'character_pose_message', 'character_pose_stage',
                 'character_pose_progress', 'character_pose_env_report',
                 'character_pose_comfy_python', 'character_pose_sys_python',
                 'character_pose_comfy_root', 'character_pose_model_path'):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    _pose_cancel_all(None)
    for cls in (VIEW3D_PT_character_tools,
                CHARACTER_OT_pose_open_downloads, CHARACTER_OT_pose_open_log,
                CHARACTER_OT_pose_env_check, CHARACTER_OT_pose_cancel,
                CHARACTER_OT_pose_from_screen,
                CHARACTER_OT_pose_from_clipboard, CHARACTER_OT_pose_from_image,
                CHARACTER_MT_export_actions, CHARACTER_OT_set_export_action,
                CHARACTER_OT_toggle_ue, CHARACTER_OT_export_fbx,
                CHARACTER_OT_duplicate):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


register()
