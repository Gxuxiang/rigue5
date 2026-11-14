#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rigify 姿态捕捉 helper。

由 Blender 端通过 subprocess 调用：
  stdin  : 一个 JSON 请求
  stdout : 一行 ``RIGUE5_POSE_RESULT {json}``
  stderr : 人类可读日志

后端：
  sam3d      ComfyUI 里的 SAM 3D Body 实现 + ComfyUI venv（torch/CUDA）
  instanthmr 公开 ONNX（onnxruntime），输出同样的 MHR70 70 个 3D 关键点
  mediapipe  MediaPipe Pose，作为 bbox / 最后兜底

所有后端统一输出 MHR70 的关键点（x 右、y 下、z 前，米制、身体中心），
Blender 端只认这一套索引。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

MARKER = "RIGUE5_POSE_RESULT "
PROGRESS_MARKER = "RIGUE5_POSE_PROGRESS "
PROTOCOL = 1
PROTOCOL_VERSION = 1

MHR70_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
    "left_big_toe_tip", "left_small_toe_tip", "left_heel",
    "right_big_toe_tip", "right_small_toe_tip", "right_heel",
    "right_thumb_tip", "right_thumb_first_joint", "right_thumb_second_joint", "right_thumb_third_joint",
    "right_index_tip", "right_index_first_joint", "right_index_second_joint", "right_index_third_joint",
    "right_middle_tip", "right_middle_first_joint", "right_middle_second_joint", "right_middle_third_joint",
    "right_ring_tip", "right_ring_first_joint", "right_ring_second_joint", "right_ring_third_joint",
    "right_pinky_tip", "right_pinky_first_joint", "right_pinky_second_joint", "right_pinky_third_joint",
    "right_wrist",
    "left_thumb_tip", "left_thumb_first_joint", "left_thumb_second_joint", "left_thumb_third_joint",
    "left_index_tip", "left_index_first_joint", "left_index_second_joint", "left_index_third_joint",
    "left_middle_tip", "left_middle_first_joint", "left_middle_second_joint", "left_middle_third_joint",
    "left_ring_tip", "left_ring_first_joint", "left_ring_second_joint", "left_ring_third_joint",
    "left_pinky_tip", "left_pinky_first_joint", "left_pinky_second_joint", "left_pinky_third_joint",
    "left_wrist",
    "left_olecranon", "right_olecranon",
    "left_cubital_fossa", "right_cubital_fossa",
    "left_acromion", "right_acromion",
    "neck",
]

# MediaPipe 33 -> MHR70 index
MP_TO_MHR70 = {
    0: 0,      # nose
    7: 3,      # left ear
    8: 4,      # right ear
    11: 5,     # left shoulder
    12: 6,     # right shoulder
    13: 7,     # left elbow
    14: 8,     # right elbow
    23: 9,     # left hip
    24: 10,    # right hip
    25: 11,    # left knee
    26: 12,    # right knee
    27: 13,    # left ankle
    28: 14,    # right ankle
    31: 15,    # left foot index
    32: 18,    # right foot index
    29: 17,    # left heel
    30: 20,    # right heel
    19: 46,    # left index
    20: 25,    # right index
    17: 58,    # left pinky
    18: 37,    # right pinky
    21: 42,    # left thumb
    22: 21,    # right thumb
    15: 62,    # left wrist
    16: 41,    # right wrist
}

DEFAULT_COMFY_ROOT = r"D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI"
DEFAULT_DETECTION_DIR = r"D:\Comfy-Desktop\ComfyUI-Shared\models\detection"
DEFAULT_LOCAL_MODELS = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "rigue5_pose", "models"
)


class HelperError(RuntimeError):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


# --------------------------------------------------------------------------- io

def emit(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, default=_json_default)
    sys.stdout.write(MARKER + text + "\n")
    sys.stdout.flush()
    sys.stderr.flush()


def emit_progress(fraction: float, stage: str) -> None:
    """进度写 stderr；Blender 端轮询日志更新面板进度条。"""
    fraction = max(0.0, min(1.0, float(fraction)))
    sys.stderr.write("%s%.3f %s\n" % (PROGRESS_MARKER, fraction, stage))
    sys.stderr.flush()


def _json_default(value):
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
    except Exception:
        pass
    return str(value)


def _ok(**kwargs) -> dict:
    out = {"protocol": PROTOCOL, "ok": True}
    out.update(kwargs)
    return out


def _err(exc: BaseException, mode: str = "") -> dict:
    if isinstance(exc, HelperError):
        return {
            "protocol": PROTOCOL,
            "ok": False,
            "mode": mode,
            "error": {"code": exc.code, "message": exc.message, "hint": exc.hint},
        }
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return {
        "protocol": PROTOCOL,
        "ok": False,
        "mode": mode,
        "error": {
            "code": "INTERNAL",
            "message": str(exc) or type(exc).__name__,
            "hint": tb[-3000:],
        },
    }


def _import_numpy():
    import numpy as np

    return np


def load_image(path: str):
    """PIL 读取，处理 EXIF，转 RGB numpy。"""
    np = _import_numpy()
    from PIL import Image, ImageOps

    if not path or not os.path.isfile(path):
        raise HelperError("NO_IMAGE", "找不到图片：%s" % path, "请重新选择图片或截图。")
    try:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:
        raise HelperError("BAD_IMAGE", "图片读取失败：%s" % exc, "换一张 PNG/JPG 试试。")
    # 限制长边，避免超大截图拖慢推理
    w, h = img.size
    long_edge = max(w, h)
    if long_edge > 2048:
        scale = 2048.0 / long_edge
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    return np.asarray(img, dtype=np.uint8)


def save_capture(image_rgb, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, time.strftime("screen_%Y%m%d_%H%M%S.png"))
    try:
        from PIL import Image

        Image.fromarray(image_rgb).save(path)
    except Exception:
        path = ""
    return path


# ---------------------------------------------------------------- screenshots

def _clipboard_sequence_number() -> int:
    try:
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:
        return 0


def _send_win_shift_s() -> None:
    """发送 Win+Shift+S 打开 Windows 截图选择框。"""
    user32 = ctypes.windll.user32
    VK_LWIN, VK_SHIFT, VK_S = 0x5B, 0x10, 0x53
    KEYUP = 0x0002

    def down(vk):
        user32.keybd_event(vk, 0, 0, 0)

    def up(vk):
        user32.keybd_event(vk, 0, KEYUP, 0)

    down(VK_LWIN)
    down(VK_SHIFT)
    down(VK_S)
    up(VK_S)
    up(VK_SHIFT)
    up(VK_LWIN)


def _open_snipping_overlay() -> None:
    # 直接发 Win+Shift+S 最稳；ms-screenclip: 在部分 Win11 上没注册。
    try:
        _send_win_shift_s()
        return
    except Exception:
        pass
    try:
        os.startfile("ms-screenclip:")
        return
    except Exception:
        pass
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "open", "ms-screenclip:", None, None, 0)
    except Exception:
        pass


def _grab_clipboard_image():
    from PIL import Image, ImageGrab

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    data = ImageGrab.grabclipboard()
    if isinstance(data, list):
        for item in data:
            try:
                img = Image.open(item)
                img.load()
                return img.convert("RGB")
            except Exception:
                continue
        return None
    if isinstance(data, Image.Image):
        return data.convert("RGB")
    return None


def capture_clipboard(timeout: float = 2.0):
    """读取当前剪贴板图片；没有就报错。"""
    np = _import_numpy()
    img = _grab_clipboard_image()
    if img is None:
        raise HelperError(
            "NO_IMAGE",
            "剪贴板里没有图片。",
            "先用 Win+Shift+S 截一张图，或点「截图 ➜ 姿态」。",
        )
    return np.asarray(img, dtype=np.uint8)


def capture_screen(timeout: float = 180.0):
    """调起 Windows 截图，轮询剪贴板，返回 RGB numpy。"""
    np = _import_numpy()
    from PIL import Image

    seq0 = _clipboard_sequence_number()
    _open_snipping_overlay()
    deadline = time.time() + max(5.0, float(timeout))
    last_seq = seq0
    while time.time() < deadline:
        time.sleep(0.35)
        seq = _clipboard_sequence_number()
        if seq == last_seq:
            continue
        last_seq = seq
        img = _grab_clipboard_image()
        if img is not None:
            return np.asarray(img, dtype=np.uint8)
    raise HelperError(
        "CAPTURE_CANCELLED",
        "没有等到截图（超时或已取消）。",
        "重新点「截图 ➜ 姿态」，或先用 Win+Shift+S 截图再点「剪贴板 ➜ 姿态」。",
    )


# ------------------------------------------------------------------- backend

def _comfy_root(req: dict) -> str:
    root = req.get("comfy_root") or os.environ.get("RIGUE5_COMFY_ROOT") or DEFAULT_COMFY_ROOT
    if not os.path.isdir(os.path.join(root, "comfy")):
        # 也认 ComfyUI Desktop 的 resources/ComfyUI
        alt = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Programs", "ComfyUI", "resources", "ComfyUI"
        )
        if os.path.isdir(os.path.join(alt, "comfy")):
            return alt
    return root


def _sam3d_candidates(req: dict):
    out = []
    if req.get("model_path"):
        out.append(req["model_path"])
    out += [
        # ComfyUI 官方转换过的 safetensors（推荐，键名与 comfy/ldm/sam3d_body 匹配）
        os.path.join(DEFAULT_DETECTION_DIR, "sam_3d_body_dinov3_bf16.safetensors"),
        os.path.join(DEFAULT_DETECTION_DIR, "sam_3d_body_dinov3_int8_convrot.safetensors"),
        os.path.join(DEFAULT_DETECTION_DIR, "sam-3d-body",
                     "sam_3d_body_dinov3_bf16.safetensors"),
        # 注意：原始 Meta model.ckpt 的键名和 ComfyUI 的 SAM3DBody 不兼容，
        # 不是这里的目标格式；需要的话用官方 facebookresearch/sam-3d-body repo。
    ]
    return out


def _find_sam3d_ckpt(req: dict) -> str | None:
    for path in _sam3d_candidates(req):
        if path and os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
            return path
    return None


def _instant_candidates(req: dict):
    model = req.get("model_path")
    body = req.get("body_path")
    base = req.get("model_dir") or DEFAULT_LOCAL_MODELS
    model = model or os.path.join(base, "instanthmr-medium-fit2.onnx")
    body = body or os.path.join(base, "mhr-body.onnx")
    return model, body


def _mediapipe_model(req: dict) -> str:
    return req.get("model_path") or os.path.join(DEFAULT_LOCAL_MODELS, "pose_landmarker_full.task")


def _yolo_path(req: dict) -> str:
    path = req.get("yolo_path") or os.path.join(DEFAULT_LOCAL_MODELS, "yolo11m-pose.pt")
    return path if os.path.isfile(path) else ""


def _expand_bbox(box, w: int, h: int, margin: float = 0.08):
    x1, y1, x2, y2 = [float(v) for v in box]
    bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
    mx, my = bw * margin, bh * margin
    return [max(0.0, x1 - mx), max(0.0, y1 - my),
            min(float(w), x2 + mx), min(float(h), y2 + my)]


def _bbox_from_mediapipe(image_rgb, req: dict):
    model_path = _mediapipe_model(req)
    if not os.path.isfile(model_path):
        return None
    try:
        np = _import_numpy()
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        options = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=model_path),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.3,
        )
        with vision.PoseLandmarker.create_from_options(options) as detector:
            result = detector.detect(mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(image_rgb)))
        if not result.pose_landmarks:
            return None
        H, W = image_rgb.shape[:2]
        pts = [(p.x, p.y) for p in result.pose_landmarks[0]]
        xs = [x for x, _ in pts]
        ys = [y for _, y in pts]
        box = [min(xs) * W, min(ys) * H, max(xs) * W, max(ys) * H]
        return _expand_bbox(box, W, H, margin=0.15)
    except Exception as exc:
        print("mediapipe bbox failed: %s" % exc, file=sys.stderr)
        return None


def detect_bbox(image_rgb, req: dict):
    """人物框：优先 YOLO，其次 MediaPipe，最后返回 None（整图）。"""
    given = req.get("bbox")
    if given and len(given) == 4:
        H, W = image_rgb.shape[:2]
        return _expand_bbox(given, W, H, margin=0.0)

    path = _yolo_path(req)
    if path:
        try:
            import torch
            from ultralytics import YOLO

            model = YOLO(path)
            device = 0 if torch.cuda.is_available() else "cpu"
            results = model.predict(image_rgb, verbose=False, conf=0.25,
                                    classes=[0], device=device)
            boxes = results[0].boxes.xyxy.cpu().numpy() if results else []
            if len(boxes):
                areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
                b = boxes[int(areas.argmax())]
                H, W = image_rgb.shape[:2]
                return _expand_bbox(b, W, H, margin=0.08)
            print("YOLO: no person box", file=sys.stderr)
        except Exception as exc:
            print("YOLO bbox failed: %s" % exc, file=sys.stderr)

    return _bbox_from_mediapipe(image_rgb, req)


def pick_backend(req: dict) -> str:
    backend = (req.get("backend") or "auto").lower()
    if backend in ("sam3d", "sam3d_body", "sam-3d-body"):
        return "sam3d"
    if backend in ("instanthmr", "instant"):
        return "instanthmr"
    if backend in ("mediapipe", "mp"):
        return "mediapipe"
    if backend != "auto":
        raise HelperError("UNSUPPORTED_MODE", "未知后端：%s" % backend)

    ckpt = _find_sam3d_ckpt(req)
    if ckpt:
        try:
            import torch  # noqa: F401

            return "sam3d"
        except Exception:
            pass
    model, body = _instant_candidates(req)
    if os.path.isfile(model) and os.path.isfile(body):
        try:
            import onnxruntime  # noqa: F401

            return "instanthmr"
        except Exception:
            pass
    if os.path.isfile(_mediapipe_model(req)):
        try:
            import mediapipe  # noqa: F401

            return "mediapipe"
        except Exception:
            pass
    raise HelperError(
        "NO_MODEL",
        "没有可用的姿态识别后端。",
        "下载 SAM 3D Body 的 model.ckpt（放到 %s），或下载 InstantHMR 的两个 onnx。"
        % DEFAULT_DETECTION_DIR,
    )


def estimate(req: dict, image_rgb, backend: str) -> dict:
    if backend == "sam3d":
        return estimate_sam3d(req, image_rgb)
    if backend == "instanthmr":
        return estimate_instanthmr(req, image_rgb)
    if backend == "mediapipe":
        return estimate_mediapipe(req, image_rgb)
    raise HelperError("UNSUPPORTED_MODE", "未知后端：%s" % backend)


# --------------------------------------------------------------- SAM 3D Body

def _torch_dtype_for(comfy_mm, comfy_utils, sd):
    import torch

    load_device = comfy_mm.get_torch_device()
    weight_dtype = comfy_utils.weight_dtype(sd)
    torch_dtype = comfy_mm.unet_dtype(
        device=load_device, model_params=-1, weight_dtype=weight_dtype
    )
    manual_cast_dtype = comfy_mm.unet_manual_cast(torch_dtype, load_device)
    return torch, load_device, torch_dtype, manual_cast_dtype


def _load_sam3d_model(ckpt_path: str, root: str | None = None, fp32: bool = False):
    import torch

    root = root or _comfy_root({})
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        os.chdir(root)
    except Exception:
        pass

    import comfy.model_management as comfy_mm
    import comfy.ops as comfy_ops
    import comfy.utils as comfy_utils
    from comfy.ldm.sam3d_body.model.model import SAM3DBody

    sd = comfy_utils.load_torch_file(ckpt_path, safe_load=True)
    if isinstance(sd, dict) and isinstance(sd.get("state_dict"), dict):
        sd = sd["state_dict"]
    sd = {k.replace(".layers.0.0.", ".layers.0."): v for k, v in sd.items()}
    if not isinstance(sd, dict):
        raise HelperError("NO_MODEL", "checkpoint 不是 state_dict：%s" % ckpt_path)

    torch_mod, load_device, torch_dtype, manual_cast = _torch_dtype_for(
        comfy_mm, comfy_utils, sd
    )
    if fp32:
        # ComfyUI 的 SAM 3D Body 手部精修（inference_type="full"）在
        # bf16/fp16 权重下会报 Float/Half 不匹配；手部精修时用 fp32 最稳。
        # 4070 Ti Super 16GB 跑 2.8GB 模型没问题。
        torch_dtype = torch.float32
        manual_cast = None
    ops = None
    try:
        quant_config = comfy_utils.detect_layer_quantization(sd, "")
    except Exception:
        quant_config = None
    if quant_config is not None:
        try:
            ops = comfy_ops.mixed_precision_ops(quant_config, torch_dtype)
        except Exception:
            ops = None
    if ops is None:
        try:
            ops = comfy_ops.pick_operations(
                torch_dtype, manual_cast, load_device=load_device,
                disable_fast_fp8=True
            )
        except Exception:
            ops = comfy_ops.disable_weight_init

    model = SAM3DBody(dtype=torch_dtype, operations=ops)
    sd.pop("hand_cls_embed.weight", None)
    sd.pop("hand_cls_embed.bias", None)
    missing, unexpected = model.load_state_dict(sd, strict=False)

    # 官方把 MHR rig 权重放在同目录的 assets/mhr_model.pt；ComfyUI 的 checkpoint
    # 通常已包含，但这里兼容两种布局。
    if missing:
        mhr_path = os.path.join(os.path.dirname(ckpt_path), "assets", "mhr_model.pt")
        if os.path.isfile(mhr_path):
            try:
                extra = torch.load(mhr_path, map_location="cpu", weights_only=True)
            except Exception:
                extra = torch.load(mhr_path, map_location="cpu", weights_only=False)
            if isinstance(extra, dict) and isinstance(extra.get("state_dict"), dict):
                extra = extra["state_dict"]
            # 补上缺失的键；兼容没有 mhr. 前缀的权重
            fixed = {}
            for key in list(missing):
                if key in extra:
                    fixed[key] = extra[key]
                elif ("mhr." + key) in extra:
                    fixed[key] = extra["mhr." + key]
                elif key.startswith("mhr.") and key[4:] in extra:
                    fixed[key] = extra[key[4:]]
            if fixed:
                missing, unexpected = model.load_state_dict(fixed, strict=False)

    if missing or unexpected:
        raise HelperError(
            "NO_MODEL",
            "SAM 3D Body 权重与代码不匹配（missing=%d, unexpected=%d）。"
            % (len(missing), len(unexpected)),
            "missing: %s; unexpected: %s"
            % (", ".join(list(missing)[:6]), ", ".join(list(unexpected)[:6])),
        )

    model.backbone_dtype = torch_dtype
    model.eval()
    try:
        model.to(load_device)
    except Exception:
        pass
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return model, load_device


def estimate_sam3d(req: dict, image_rgb) -> dict:
    np = _import_numpy()
    ckpt = _find_sam3d_ckpt(req)
    if not ckpt:
        raise HelperError(
            "NO_MODEL",
            "没有找到 SAM 3D Body 权重。",
            "把 sam_3d_body_dinov3_bf16.safetensors 放到 %s，或用 model_path 指定。"
            % DEFAULT_DETECTION_DIR,
        )
    import torch

    emit_progress(0.15, "检测人物框…")
    warnings = []
    bbox = detect_bbox(image_rgb, req)
    if bbox is None:
        warnings.append("没有检测到人物框，使用整图；建议把人物截得更大、更居中。")
    elif os.path.isfile(_yolo_path(req)):
        warnings.append("人物框：YOLO11m-pose")

    H, W = image_rgb.shape[:2]
    if bbox and len(bbox) == 4:
        x1, y1, x2, y2 = [float(v) for v in bbox]
    else:
        x1, y1, x2, y2 = 0.0, 0.0, float(W), float(H)
    # 裁剪到图像范围
    x1 = max(0.0, min(W - 1.0, x1))
    x2 = max(x1 + 2.0, min(float(W), x2))
    y1 = max(0.0, min(H - 1.0, y1))
    y2 = max(y1 + 2.0, min(float(H), y2))

    emit_progress(0.25, "加载 SAM 3D Body…")
    root = _comfy_root(req)
    model, device = _load_sam3d_model(
        ckpt, root, fp32=bool(req.get("refine_hands")))

    if root not in sys.path:
        sys.path.insert(0, root)
    from comfy_extras.sam3d_body.utils import run_batched_frames

    frame = torch.from_numpy(np.ascontiguousarray(image_rgb)).to(torch.uint8)
    boxes = [torch.tensor([[x1, y1, x2, y2]], dtype=torch.float32)]
    inference_type = "full" if req.get("refine_hands") else "body"

    emit_progress(0.65, "SAM 3D Body 推理…")
    t0 = time.time()

    def _run(kind):
        return run_batched_frames(
            model,
            [frame],
            boxes,
            None,
            model.image_size,
            kind,
            cam_int=None,
            pbar=None,
            crops_per_chunk=1,
        )

    with torch.inference_mode():
        try:
            out = _run(inference_type)
        except RuntimeError as exc:
            msg = str(exc).lower()
            # 手部精修是可选增强：显存不够或 ComfyUI 的 fp16/fp32 抖动时
            # 退回普通 body 推理，至少保证身体姿势能出来。
            if inference_type == "full" and (
                    "out of memory" in msg or "float and half" in msg):
                warnings.append("手部精修失败，已退回普通推理：%s" % str(exc)[:100])
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                out = _run("body")
            else:
                raise
    if not out or not out[0]:
        raise HelperError("NO_POSE", "SAM 3D Body 没有检测到人物。", "换一张清晰、全身、单人的图。")
    person = out[0][0]
    kp3 = np.asarray(person["pred_keypoints_3d"], dtype=np.float32)
    kp2 = np.asarray(person.get("pred_keypoints_2d"), dtype=np.float32)
    elapsed = int((time.time() - t0) * 1000)

    emit_progress(0.95, "整理关键点…")
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return _ok(
        backend="sam3d",
        space="mhr70_local",
        landmarks=_landmarks(kp3, np.ones(70, dtype=np.float32)),
        keypoints_2d=kp2.tolist() if kp2.size else None,
        model=os.path.basename(ckpt),
        device=str(device),
        elapsed_ms=elapsed,
        warnings=warnings,
    )


# ----------------------------------------------------------------- InstantHMR

def _instant_crop(image_rgb, bbox, scale, input_size, focal, cliff_focal):
    np = _import_numpy()
    import cv2

    h, w = image_rgb.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in bbox]
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    size = max(x2 - x1, y2 - y1) * scale
    if cliff_focal:
        cliff = [
            math.atan((cx - w / 2.0) / focal),
            math.atan((cy - h / 2.0) / focal),
            size / focal,
        ]
    else:
        cliff = [2.0 * cx / w - 1.0, 2.0 * cy / h - 1.0, size / max(w, h)]
    side = size * 1.2
    ix1 = math.floor(cx - side / 2.0)
    iy1 = math.floor(cy - side / 2.0)
    ix2 = math.ceil(cx - side / 2.0 + side)
    iy2 = math.ceil(cy - side / 2.0 + side)
    sx = (ix2 - ix1) / float(input_size)
    sy = (iy2 - iy1) / float(input_size)
    m = np.array(
        [[sx, 0.0, ix1 + 0.5 * sx - 0.5], [0.0, sy, iy1 + 0.5 * sy - 0.5]],
        dtype=np.float64,
    )
    crop = cv2.warpAffine(
        image_rgb,
        m,
        (input_size, input_size),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    return crop, np.asarray(cliff, np.float32), (ix1, iy1, ix2 - ix1, iy2 - iy1)


def estimate_instanthmr(req: dict, image_rgb) -> dict:
    np = _import_numpy()
    import onnxruntime as ort

    model_path, body_path = _instant_candidates(req)
    if not os.path.isfile(model_path) or not os.path.isfile(body_path):
        raise HelperError(
            "NO_MODEL",
            "没有找到 InstantHMR 模型。",
            "需要 instanthmr-medium-fit2.onnx 和 mhr-body.onnx，放到 %s。" % DEFAULT_LOCAL_MODELS,
        )

    emit_progress(0.2, "检测人物框…")
    warnings = []
    bbox = detect_bbox(image_rgb, req)
    if bbox is None:
        warnings.append("没有检测到人物框，使用整图；建议把人物截得更大、更居中。")

    emit_progress(0.35, "加载 InstantHMR…")
    providers = ["CPUExecutionProvider"]
    try:
        available = set(ort.get_available_providers())
        if "DmlExecutionProvider" in available:
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
    except Exception:
        pass

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(model_path, sess_options=so, providers=providers)
    meta = sess.get_modelmeta().custom_metadata_map
    input_size = int(meta.get("image_size", 288))
    n_crops = int(meta.get("crops", 2))
    scales = tuple(float(v) for v in meta.get("crop_scales", "0.9,0.7").split(","))[:n_crops]
    cliff_focal = meta.get("cliff_focal", "true") == "true"

    H, W = image_rgb.shape[:2]
    focal = 1.05 * math.hypot(H, W)
    box = bbox or [0.0, 0.0, float(W), float(H)]
    x1, y1, x2, y2 = [float(v) for v in box]
    # detector box -> GT box (InstantHMR 的约定)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    half_w = (x2 - x1) / 0.866 / 2.0
    half_h = (y2 - y1) / 0.866 / 2.0
    gt_box = [cx - half_w, cy - half_h, cx + half_w, cy + half_h]

    crops, cliffs, squares = [], [], []
    for scale in scales:
        c, cliff, sq = _instant_crop(
            image_rgb, gt_box, scale, input_size, focal, cliff_focal
        )
        crops.append(c)
        cliffs.append(cliff)
        squares.append(sq)

    feeds = {
        "image": np.stack(crops).astype(np.uint8),
        "cliff_cond": np.stack(cliffs).astype(np.float32),
        "crop_box": np.asarray(squares, np.float32),
        "cam": np.asarray([[focal, W / 2.0, H / 2.0]], np.float32),
    }
    emit_progress(0.55, "InstantHMR 推理…")
    t0 = time.time()
    outs = sess.run(
        ["mhr_params", "shape_params", "cam_trans", "joints_2d"], feeds
    )
    body = ort.InferenceSession(body_path, sess_options=so, providers=providers)
    joints = body.run(
        ["joints_3d"], {"mhr_params": outs[0], "shape_params": outs[1]}
    )[0]
    kp3 = np.asarray(joints[0], dtype=np.float32)
    elapsed = int((time.time() - t0) * 1000)
    emit_progress(0.95, "整理关键点…")
    return _ok(
        backend="instanthmr",
        space="mhr70_local",
        landmarks=_landmarks(kp3, np.ones(70, dtype=np.float32)),
        keypoints_2d=None,
        model=os.path.basename(model_path),
        device=providers[0],
        elapsed_ms=elapsed,
        warnings=warnings,
    )


# ------------------------------------------------------------------- MediaPipe

def estimate_mediapipe(req: dict, image_rgb) -> dict:
    np = _import_numpy()
    model_path = _mediapipe_model(req)
    if not os.path.isfile(model_path):
        raise HelperError(
            "NO_MODEL",
            "没有找到 MediaPipe Pose 模型。",
            "下载 pose_landmarker_full.task 放到 %s。" % DEFAULT_LOCAL_MODELS,
        )
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    base = mp_python.BaseOptions(model_asset_path=model_path)
    options = vision.PoseLandmarkerOptions(
        base_options=base,
        running_mode=vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.3,
        min_pose_presence_confidence=0.3,
    )
    emit_progress(0.35, "MediaPipe 推理…")
    t0 = time.time()
    with vision.PoseLandmarker.create_from_options(options) as detector:
        mp_img = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(image_rgb),
        )
        result = detector.detect(mp_img)
    if not result.pose_world_landmarks:
        raise HelperError("NO_POSE", "MediaPipe 没有检测到人物。", "换一张清晰的真人/写实图。")

    world = result.pose_world_landmarks[0]
    norm = result.pose_landmarks[0] if result.pose_landmarks else None
    kp = np.zeros((70, 3), dtype=np.float32)
    vis = np.zeros(70, dtype=np.float32)
    for mp_idx, mhr_idx in MP_TO_MHR70.items():
        if mp_idx >= len(world):
            continue
        lm = world[mp_idx]
        kp[mhr_idx] = (lm.x, lm.y, lm.z)
        if norm is not None and mp_idx < len(norm):
            v = getattr(norm[mp_idx], "visibility", None)
            p = getattr(world[mp_idx], "visibility", None)
            vis[mhr_idx] = float(min(v if v is not None else 1.0, p if p is not None else 1.0))
        else:
            vis[mhr_idx] = 1.0
    elapsed = int((time.time() - t0) * 1000)
    emit_progress(0.95, "整理关键点…")
    return _ok(
        backend="mediapipe",
        space="mhr70_world",
        landmarks=_landmarks(kp, vis),
        keypoints_2d=None,
        model=os.path.basename(model_path),
        device="cpu",
        elapsed_ms=elapsed,
        warnings=[],
    )


def _landmarks(kp, vis):
    out = []
    for i in range(70):
        x, y, z = [float(v) for v in kp[i]]
        out.append(
            {
                "i": i,
                "name": MHR70_NAMES[i],
                "x": x,
                "y": y,
                "z": z,
                "visibility": float(vis[i]),
            }
        )
    return out


# ----------------------------------------------------------------------- check

def check_backends(req: dict) -> dict:
    import importlib.util

    info = {"protocol": PROTOCOL, "ok": True, "python": sys.version.split()[0]}
    root = _comfy_root(req)
    ckpt = _find_sam3d_ckpt(req)
    sam3d = {
        "root": root,
        "root_exists": os.path.isdir(os.path.join(root, "comfy")),
        "model": ckpt,
        "model_exists": bool(ckpt),
        "torch": importlib.util.find_spec("torch") is not None,
        "cuda": False,
        "code": os.path.isfile(
            os.path.join(root, "comfy", "ldm", "sam3d_body", "model", "model.py")
        ),
    }
    try:
        import torch

        sam3d["cuda"] = bool(torch.cuda.is_available())
        sam3d["torch_version"] = torch.__version__
    except Exception:
        pass
    info["sam3d"] = sam3d

    model, body = _instant_candidates(req)
    info["instanthmr"] = {
        "model": model,
        "model_exists": os.path.isfile(model),
        "body": body,
        "body_exists": os.path.isfile(body),
        "onnxruntime": importlib.util.find_spec("onnxruntime") is not None,
    }
    mp_model = _mediapipe_model(req)
    info["mediapipe"] = {
        "model": mp_model,
        "model_exists": os.path.isfile(mp_model),
        "mediapipe": importlib.util.find_spec("mediapipe") is not None,
    }
    return info


# ----------------------------------------------------------------------- main

def _read_request() -> dict:
    text = sys.stdin.read()
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except Exception as exc:
        raise HelperError("BAD_REQUEST", "请求 JSON 解析失败：%s" % exc)


def main(argv=None) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--image")
    parser.add_argument("--clipboard", action="store_true")
    parser.add_argument("--backend", default="auto")
    parser.add_argument("--model_path")
    parser.add_argument("--body_path")
    parser.add_argument("--bbox", help="x1,y1,x2,y2")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    request = _read_request()
    if args.image:
        request.update({"mode": "image", "image_path": args.image})
    elif args.clipboard:
        request.setdefault("mode", "clipboard")
    if args.backend:
        request.setdefault("backend", args.backend)
    if args.model_path:
        request.setdefault("model_path", args.model_path)
    if args.body_path:
        request.setdefault("body_path", args.body_path)
    if args.bbox:
        request["bbox"] = [float(v) for v in args.bbox.split(",")]

    mode = (request.get("mode") or "image").lower()
    try:
        if mode == "check":
            emit(check_backends(request))
            return 0

        if mode == "image":
            emit_progress(0.05, "读取图片…")
            image = load_image(request.get("image_path", ""))
            emit_progress(0.1, "准备识别…")
        elif mode == "clipboard":
            emit_progress(0.05, "读取剪贴板…")
            image = capture_clipboard(float(request.get("screenshot_timeout", 5)))
            emit_progress(0.25, "已读取剪贴板，准备识别…")
        elif mode == "screenshot":
            emit_progress(0.02, "等待截图框选…")
            image = capture_screen(float(request.get("screenshot_timeout", 180)))
            emit_progress(0.25, "已截图，准备识别…")
        else:
            raise HelperError("UNSUPPORTED_MODE", "未知 mode：%s" % mode)

        backend = pick_backend(request)
        result = estimate(request, image, backend)

        capture_path = ""
        if request.get("save_capture") and mode in ("clipboard", "screenshot"):
            capture_path = save_capture(
                image,
                request.get("capture_dir")
                or os.path.join(os.path.dirname(DEFAULT_LOCAL_MODELS), "captures"),
            )
            result["capture"] = capture_path
        emit_progress(1.0, "完成")
        emit(result)
        return 0
    except SystemExit:
        raise
    except BaseException as exc:
        emit(_err(exc, mode))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
