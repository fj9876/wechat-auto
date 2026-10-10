# -*- coding: utf-8 -*-
"""环形视频帧缓冲区与音视频时钟同步调度器 (agent_core.video_call.pipeline.ring_buffer)

参考 OpenTalking 流水线标准实现：
1. VideoRingBuffer: 线程安全、抗抖动环形帧缓冲队列，带语音结束平滑收口与淡出功能
2. AVSyncClock: 25 FPS 高精度单调时钟定时器，确保虚拟摄像头输出帧率丝滑均匀
"""
from __future__ import annotations

import time
import threading
import logging
from typing import Optional, List
import numpy as np
import cv2

logger = logging.getLogger("VideoRingBuffer")


class VideoRingBuffer:
    """抗抖动环形视频帧缓冲区"""

    def __init__(self, capacity: int = 300):
        self.capacity = capacity
        self._buffer: List[np.ndarray] = []
        self._lock = threading.Lock()
        self._last_popped_frame: Optional[np.ndarray] = None
        self._idle_frame: Optional[np.ndarray] = None
        self._closing_frames_remaining = 0  # 说话结束后平滑闭嘴过渡剩余帧数

    def set_idle_frame(self, frame: np.ndarray):
        """设置基准待命闭口帧"""
        if frame is not None:
            with self._lock:
                self._idle_frame = frame.copy()

    def push_frames(self, frames: List[np.ndarray]):
        """推入一批新的视频帧序列"""
        if not frames:
            return
        with self._lock:
            for f in frames:
                if len(self._buffer) >= self.capacity:
                    # 缓冲区超限时丢弃最老的一帧 (背压保护)
                    self._buffer.pop(0)
                self._buffer.append(f)
            # 有新说话帧推入，重置平滑闭嘴计数
            self._closing_frames_remaining = 5

    def push_frame(self, frame: np.ndarray):
        """推入单帧"""
        self.push_frames([frame])

    def pop_frame(self) -> Optional[np.ndarray]:
        """弹出下一帧供渲染或推流，若空则返回平滑过渡帧或 None"""
        with self._lock:
            if len(self._buffer) > 0:
                frame = self._buffer.pop(0)
                self._last_popped_frame = frame
                return frame

            # 队列已空 (说话结束阶段)，执行平滑闭嘴收口淡出
            if self._closing_frames_remaining > 0 and self._last_popped_frame is not None and self._idle_frame is not None:
                self._closing_frames_remaining -= 1
                alpha = float(self._closing_frames_remaining) / 5.0
                blended = cv2.addWeighted(self._last_popped_frame, alpha, self._idle_frame, 1.0 - alpha, 0.0)
                self._last_popped_frame = blended
                return blended

            return None

    def size(self) -> int:
        with self._lock:
            return len(self._buffer)

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._buffer) == 0

    def clear(self):
        with self._lock:
            self._buffer.clear()
            self._closing_frames_remaining = 0


class AVSyncClock:
    """25 FPS 精确音画同步时钟源"""

    def __init__(self, target_fps: int = 25):
        self.target_fps = target_fps
        self.frame_interval = 1.0 / float(target_fps)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._tick_callback = None

    def start(self, on_tick_callback):
        """启动同步时钟循环"""
        if self._running:
            return
        self._running = True
        self._tick_callback = on_tick_callback
        self._thread = threading.Thread(target=self._clock_loop, daemon=True, name="AVSyncClock")
        self._thread.start()
        logger.info(f"[AVSyncClock] 启动高精度同步时钟 ({self.target_fps} FPS, 间隔 {self.frame_interval*1000:.1f}ms)")

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        logger.info("[AVSyncClock] 同步时钟已停止")

    def _clock_loop(self):
        next_time = time.perf_counter()
        while self._running:
            now = time.perf_counter()
            if now >= next_time:
                try:
                    if self._tick_callback:
                        self._tick_callback()
                except Exception as e:
                    logger.debug(f"[AVSyncClock] 滴答回调异常: {e}")

                next_time += self.frame_interval
                # 防时钟漂移累积
                if now - next_time > 0.1:
                    next_time = now + self.frame_interval

            # 精密短休眠
            sleep_sec = next_time - time.perf_counter()
            if sleep_sec > 0.002:
                time.sleep(sleep_sec * 0.7)
