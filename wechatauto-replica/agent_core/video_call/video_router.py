# -*- coding: utf-8 -*-
"""虚拟摄像头流控与帧调度路由器 (agent_core.video_call.video_router)

核心职责：
1. 管理 DirectShow / Media Foundation 虚拟摄像头驱动 (pyvirtualcam / OBS Virtual Camera / UnityCapture)
2. 恒定 25 FPS 高精多媒体时钟推流循环 (Strict 40ms Interval)
3. 状态自动流转：
   - 待机/倾听/思考期：生成微晃动与自然眨眼 Idle 视频流
   - AI 播音说话期：实时将 TTS 音频转化为唇形同步视频帧排队推流
4. 全双工打断支持 (Barge-in): 毫秒级清空帧缓冲，瞬时平滑淡化回待机状态
5. 容错保护：未安装驱动时自动降级静默模式，绝不影响语音通话与系统稳定性
"""
from __future__ import annotations

import time
import queue
import logging
import threading
from typing import Optional, Callable, Dict, Any, List, Tuple
import numpy as np

from agent_core.video_call.avatar_engine import AvatarEngineManager

logger = logging.getLogger("VideoRouter")


def check_virtual_camera_available() -> Tuple[bool, str]:
    """检测当前操作系统是否已安装可用的虚拟摄像头 DirectShow 滤镜驱动"""
    try:
        import pyvirtualcam
        # 尝试极速探测打开虚拟摄像头
        with pyvirtualcam.Camera(width=640, height=480, fps=25) as cam:
            return True, f"已就绪 ({cam.device})"
    except Exception as e:
        err_msg = str(e)
        if "device not found" in err_msg or "No camera registered" in err_msg:
            return False, "未检测到 OBS Virtual Camera 或 UnityCapture 驱动"
        return False, f"初始化异常: {err_msg}"


class VideoRouter:
    """虚拟视频摄像头流路由器"""

    def __init__(
        self,
        app_config=None,
        avatar_manager: Optional[AvatarEngineManager] = None,
        width: int = 640,
        height: int = 480,
        fps: int = 25,
        on_frame_rendered: Optional[Callable[[np.ndarray], None]] = None,
    ):
        self.config = app_config
        self.avatar_mgr = avatar_manager or AvatarEngineManager(app_config)
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_interval = 1.0 / float(fps)
        self.on_frame_rendered = on_frame_rendered

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frame_queue: queue.Queue = queue.Queue(maxsize=150)
        self._is_camera_driver_ready = False
        self._cam_instance = None
        self._last_rendered_frame: Optional[np.ndarray] = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self):
        """启动虚拟摄像头推流后台线程"""
        if self._running:
            return
        self._running = True

        # 清空残留帧队列
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except Exception:
                break

        self._thread = threading.Thread(target=self._stream_loop, daemon=True, name="VideoStreamThread")
        self._thread.start()
        logger.info(f"[VideoRouter] 虚拟摄像头推流中枢已启动 ({self.width}x{self.height} @ {self.fps}FPS)")

    def stop(self):
        """停止推流"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

        # 关闭物理虚拟摄像头句柄
        if self._cam_instance:
            try:
                self._cam_instance.close()
            except Exception:
                pass
            self._cam_instance = None

        logger.info("[VideoRouter] 虚拟摄像头推流中枢已停止")

    def interrupt(self):
        """全双工打断：立即丢弃所有尚未推流的嘴动帧，瞬时切回 Idle 状态"""
        logger.info("[VideoRouter] 收到打断信号: 立即清空视频帧缓冲并复位数字人状态")
        cleared_count = 0
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
                cleared_count += 1
            except Exception:
                break
        self.avatar_mgr.reset()
        if cleared_count > 0:
            logger.info(f"[VideoRouter] 已废弃未播唇动帧: {cleared_count} 帧")

    def put_audio(self, pcm_bytes: bytes, sample_rate: int = 16000):
        """接收来自 TTS 的实时音频数据流，交由数字人引擎生成音画同步帧并排入推流缓冲"""
        if not self._running or not pcm_bytes:
            return

        def _worker():
            try:
                frames = self.avatar_mgr.process_audio_chunk(pcm_bytes, sample_rate)
                for f in frames:
                    try:
                        self._frame_queue.put(f, timeout=0.1)
                    except queue.Full:
                        # 队列过满丢弃最旧帧以保时效性
                        try:
                            self._frame_queue.get_nowait()
                            self._frame_queue.put(f, timeout=0.05)
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"[VideoRouter] 音频转化为唇形帧异常: {e}", exc_info=True)

        # 异步驱动帧渲染，避免阻塞音频主播放队列
        t = threading.Thread(target=_worker, daemon=True, name="AvatarAudioToVideo")
        t.start()

    def _fit_frame_to_target(self, frame: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
        """智能按等比例居中适配目标分辨率，防止人脸畸变或拉伸变形，并增加边缘毛玻璃高级背景"""
        if frame is None:
            return np.zeros((target_h, target_w, 3), dtype=np.uint8)
        fh, fw = frame.shape[:2]
        if fh == target_h and fw == target_w:
            return frame

        import cv2
        scale = min(target_w / fw, target_h / fh)
        nw, nh = int(fw * scale), int(fh * scale)
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)

        # 创建目标尺寸画布
        canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        # 如果左右两侧有空余 (如 4:3 屏幕显示 1:1 图像)，用原图做暗色高斯虚化铺底
        if nw < target_w:
            try:
                bg_scale = max(target_w / fw, target_h / fh)
                bg_w, bg_h = int(fw * bg_scale), int(fh * bg_scale)
                bg = cv2.resize(frame, (bg_w, bg_h))
                # 居中裁切至画布尺寸
                bx = (bg_w - target_w) // 2
                by = (bg_h - target_h) // 2
                bg_crop = bg[by:by + target_h, bx:bx + target_w]
                if bg_crop.shape[:2] == (target_h, target_w):
                    canvas = (cv2.GaussianBlur(bg_crop, (25, 25), 12) * 0.45).astype(np.uint8)
            except Exception:
                pass

        x_off = (target_w - nw) // 2
        y_off = (target_h - nh) // 2
        canvas[y_off:y_off + nh, x_off:x_off + nw] = resized
        return canvas

    def _stream_loop(self):
        """严格按 1/fps 恒定节奏推流的主循环"""
        import pyvirtualcam

        cam = None
        try:
            cam = pyvirtualcam.Camera(
                width=self.width,
                height=self.height,
                fps=self.fps,
                fmt=pyvirtualcam.PixelFormat.RGB
            )
            self._cam_instance = cam
            self._is_camera_driver_ready = True
            logger.info(f"[VideoRouter] ✅ 成功绑定系统虚拟摄像头设备: [{cam.device}] ({self.width}x{self.height} @ {self.fps}FPS)")

            # 【关键防御】预热共享内存：立即向 DirectShow 驱动预充 5 帧初始待机帧，彻底杜绝微信连入瞬间显示绿幕
            try:
                init_frame = self.avatar_mgr.get_stream_frame()
                if init_frame is not None:
                    warm_frame = self._fit_frame_to_target(init_frame, self.width, self.height)
                    for _ in range(5):
                        cam.send(warm_frame)
            except Exception as e:
                logger.debug(f"[VideoRouter] 预充初始帧: {e}")
        except Exception as e:
            self._is_camera_driver_ready = False
            logger.warning(
                f"[VideoRouter] ⚠️ 无法打开物理虚拟摄像头 ({e})。\n"
                f"系统将以虚拟预览模式运行，请确保已安装 OBS Virtual Camera 或 UnityCapture 驱动并在微信中选中。"
            )

        next_tick = time.monotonic()

        while self._running:
            now = time.monotonic()
            if now < next_tick:
                sleep_time = next_tick - now
                time.sleep(max(0.001, sleep_time))
            next_tick += self.frame_interval

            # 1. 获取当前要推流的帧 (优先队列中的说话唇动帧，空闲时取待机帧)
            current_frame = None
            try:
                current_frame = self._frame_queue.get_nowait()
            except queue.Empty:
                current_frame = self.avatar_mgr.get_stream_frame()

            if current_frame is None:
                continue

            # 智能保持人物纵横比自适应到推流目标分辨率
            current_frame = self._fit_frame_to_target(current_frame, self.width, self.height)

            self._last_rendered_frame = current_frame

            # 2. 推送至系统虚拟摄像头 DirectShow 管道 (控频由外层 next_tick 保证，去除重复 sleep)
            if cam:
                try:
                    cam.send(current_frame)
                except Exception as e:
                    logger.debug(f"[VideoRouter] 推流帧异常: {e}")

            # 3. 触发 UI 实时监控回调
            if self.on_frame_rendered:
                try:
                    self.on_frame_rendered(current_frame)
                except Exception:
                    pass

        if cam:
            try:
                cam.close()
            except Exception:
                pass
            self._cam_instance = None
