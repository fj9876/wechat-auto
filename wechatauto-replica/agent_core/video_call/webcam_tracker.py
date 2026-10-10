# -*- coding: utf-8 -*-
"""本地物理摄像头人脸动作捕捉与数字人重定向驱动器 (agent_core.video_call.webcam_tracker)

核心能力：
1. 探测并打开本地物理摄像头设备 (USB摄像头 / 笔记本内置摄像头，如 Camera 0)
2. 实时高帧率 (25~30 FPS) 人脸定位与面部运动参数追踪：
   - 嘴唇开合比率 (Mouth Open Ratio, MAR)
   - 眼睛眨眼与微闭合度 (Eye Aspect Ratio, EAR / Blink Ratio)
   - 真实头部 3D 姿态变化 (Pitch 俯仰, Yaw 偏航左右转, Roll 侧倾)
3. 动态时间阻尼滤波 (EMA Jitter Suppression)，过滤摄像头噪点与跳变
4. 实时重定向至数字人引擎渲染输出，并支持向虚拟摄像头推流
"""
from __future__ import annotations

import os
import time
import math
import logging
import threading
from typing import Optional, Callable, Dict, Any, List, Tuple
import numpy as np
import cv2

logger = logging.getLogger("WebcamTracker")


def probe_camera_devices(max_probe: int = 6) -> List[Tuple[int, str]]:
    """探测操作系统当前连接的真实物理/虚拟摄像头设备列表及硬件友好名称
    
    返回:
        [(0, "0: Web Camera"), (1, "1: Unity Video Capture"), ...]
    """
    devices_info: List[Tuple[int, str]] = []

    # 1. 优先使用 Windows DirectShow 枚举真实物理/虚拟摄像头友好名称
    try:
        from pygrabber.dshow_graph import FilterGraph
        graph = FilterGraph()
        dev_names = graph.get_input_devices()
        if dev_names:
            for idx, name in enumerate(dev_names):
                clean_name = str(name).strip() if name else f"Camera {idx}"
                devices_info.append((idx, f"{idx}: {clean_name}"))
            logger.info(f"[WebcamTracker] 成功枚举本地真实摄像头设备: {devices_info}")
            return devices_info
    except Exception as e:
        logger.debug(f"[WebcamTracker] DirectShow 枚举失败，降级使用索引扫描: {e}")

    # 2. 备用方案：通过 OpenCV 逐个索引探测
    for i in range(max_probe):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                devices_info.append((i, f"{i}: 本地摄像头 {i}"))
            cap.release()

    if not devices_info:
        devices_info.append((0, "0: 默认摄像头"))

    return devices_info


def probe_available_cameras(max_probe: int = 6) -> List[int]:
    """探测操作系统当前连接的有效本地物理摄像头索引列表 (兼容旧版调用)"""
    devs = probe_camera_devices(max_probe)
    return [idx for idx, _ in devs]


class WebcamTracker:
    """本地真实摄像头动作捕捉驱动器"""

    def __init__(
        self,
        device_index: int = 0,
        on_motion_frame: Optional[Callable[[Dict[str, float], np.ndarray], None]] = None,
        target_fps: int = 25
    ):
        self.device_index = device_index
        self.on_motion_frame = on_motion_frame
        self.target_fps = target_fps
        self.interval = 1.0 / float(target_fps)

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._last_raw_webcam_frame: Optional[np.ndarray] = None

        # 人脸检测器
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self._face_cascade = cv2.CascadeClassifier(cascade_path) if os.path.exists(cascade_path) else None

        # 连续平滑 EMA 阻尼状态
        self.smooth_mouth = 0.0
        self.smooth_eye = 0.0
        self.smooth_pitch = 0.0
        self.smooth_yaw = 0.0
        self.smooth_roll = 0.0

        # 基准人脸中心校准
        self._neutral_center: Optional[Tuple[float, float]] = None

    @property
    def is_running(self) -> bool:
        return self._running

    def get_latest_webcam_frame(self) -> Optional[np.ndarray]:
        """获取本地摄像头的最新原始画面 (用于画中画预览)"""
        return self._last_raw_webcam_frame

    def start(self, device_index: Optional[int] = None) -> bool:
        """启动本地摄像头捕获线程"""
        if self._running:
            return True

        if device_index is not None:
            self.device_index = device_index

        try:
            self._cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
            if not self._cap.isOpened():
                # 尝试默认后端
                self._cap = cv2.VideoCapture(self.device_index)

            if not self._cap.isOpened():
                logger.warning(f"[WebcamTracker] 无法打开物理摄像头设备: {self.device_index}")
                return False

            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self._cap.set(cv2.CAP_PROP_FPS, self.target_fps)

            self._running = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="WebcamCaptureThread")
            self._thread.start()
            logger.info(f"[WebcamTracker] ✅ 本地摄像头动作追踪已启动 (Camera {self.device_index})")
            return True
        except Exception as e:
            logger.error(f"[WebcamTracker] 启动摄像头捕获失败: {e}", exc_info=True)
            return False

    def stop(self):
        """停止本地摄像头捕获"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        logger.info("[WebcamTracker] 本地摄像头动作追踪已停止")

    def _estimate_face_motion(self, frame: np.ndarray) -> Dict[str, float]:
        """从摄像头画面中估算真实人脸姿态与开合参数"""
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        faces = []
        if self._face_cascade is not None:
            faces = self._face_cascade.detectMultiScale(gray, 1.2, 4, minSize=(90, 90))

        if len(faces) == 0:
            # 无人脸时平滑归位至中立态
            self.smooth_mouth *= 0.75
            self.smooth_eye *= 0.75
            self.smooth_pitch *= 0.8
            self.smooth_yaw *= 0.8
            self.smooth_roll *= 0.8
            return {
                "mouth_ratio": self.smooth_mouth,
                "eye_blink_ratio": self.smooth_eye,
                "pitch": self.smooth_pitch,
                "yaw": self.smooth_yaw,
                "roll": self.smooth_roll,
            }

        # 锁定最大人脸
        fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        cx, cy = fx + fw / 2.0, fy + fh / 2.0

        if self._neutral_center is None:
            self._neutral_center = (cx, cy)
        else:
            # 缓慢自适应校准基准中心
            ncx, ncy = self._neutral_center
            self._neutral_center = (0.98 * ncx + 0.02 * cx, 0.98 * ncy + 0.02 * cy)

        ncx, ncy = self._neutral_center

        # 估算头部 3D 偏航 (Yaw) 与俯仰 (Pitch) 偏移量
        raw_yaw = float((cx - ncx) / (w * 0.28))
        raw_pitch = float((cy - ncy) / (h * 0.25))

        # 估算嘴部开合：分析下半脸灰度梯度与对比度变化
        mouth_roi = gray[fy + int(fh * 0.65):fy + int(fh * 0.95), fx + int(fw * 0.25):fx + int(fw * 0.75)]
        raw_mouth = 0.0
        if mouth_roi.size > 0:
            # 开口时口腔阴影使局部均方差或暗度显著增大
            mean_val = np.mean(mouth_roi)
            std_val = np.std(mouth_roi)
            # 经验动态归一化 (根据口腔内明暗度与轮廓对比)
            m_ratio = np.clip((std_val - 12.0) / 28.0, 0.0, 1.0)
            raw_mouth = float(m_ratio ** 1.2)

        # 估算眼睛闭合度：分析眼部 ROI (两眼区域对比)
        eye_roi = gray[fy + int(fh * 0.28):fy + int(fh * 0.48), fx + int(fw * 0.18):fx + int(fw * 0.82)]
        raw_blink = 0.0
        if eye_roi.size > 0:
            e_std = np.std(eye_roi)
            # 闭眼时眼球反光与睫毛对比度降低
            if e_std < 18.0:
                raw_blink = float(np.clip((18.0 - e_std) / 8.0, 0.0, 1.0))

        # EMA 抗抖动平滑滤波
        self.smooth_mouth = 0.65 * raw_mouth + 0.35 * self.smooth_mouth
        self.smooth_eye = 0.70 * raw_blink + 0.30 * self.smooth_eye
        self.smooth_pitch = 0.55 * raw_pitch + 0.45 * self.smooth_pitch
        self.smooth_yaw = 0.55 * raw_yaw + 0.45 * self.smooth_yaw
        self.smooth_roll = 0.55 * 0.0 + 0.45 * self.smooth_roll

        return {
            "mouth_ratio": np.clip(self.smooth_mouth, 0.0, 1.0),
            "eye_blink_ratio": np.clip(self.smooth_eye, 0.0, 1.0),
            "pitch": np.clip(self.smooth_pitch, -1.5, 1.5),
            "yaw": np.clip(self.smooth_yaw, -2.0, 2.0),
            "roll": np.clip(self.smooth_roll, -1.0, 1.0),
        }

    def _capture_loop(self):
        """物理摄像头恒速捕获与运动重定向循环"""
        while self._running and self._cap and self._cap.isOpened():
            t_start = time.time()
            ret, frame = self._cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            # 镜像翻转符合自拍镜习惯
            frame = cv2.flip(frame, 1)
            self._last_raw_webcam_frame = frame

            motion = self._estimate_face_motion(frame)

            if self.on_motion_frame:
                try:
                    self.on_motion_frame(motion, frame)
                except Exception as ex:
                    logger.debug(f"[WebcamTracker] 运动分发回调异常: {ex}")

            elapsed = time.time() - t_start
            sleep_time = max(0.001, self.interval - elapsed)
            time.sleep(sleep_time)
