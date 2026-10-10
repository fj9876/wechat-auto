# -*- coding: utf-8 -*-
"""流式音频分块流水线 (agent_core.video_call.pipeline.chunk_pipeline)

参考 OpenTalking 流水线流水编排标准：
1. StreamChunkPipeline: 异步消费 PCM 音频切片，调用数字人引擎推理，并将生成的视频帧注入 RingBuffer
2. 零阻塞吞吐：TTS 生成与数字人视频帧生成并行解耦
3. 呼吸平滑过渡：说话结束时平滑过渡回待命微动帧，杜绝嘴部定格
"""
from __future__ import annotations

import time
import queue
import threading
import logging
from typing import Optional, List, Callable
import numpy as np

from agent_core.video_call.pipeline.ring_buffer import VideoRingBuffer, AVSyncClock

logger = logging.getLogger("ChunkPipeline")


class StreamChunkPipeline:
    """流式音频分块与帧编排流水线中枢"""

    def __init__(self, avatar_engine, chunk_duration_ms: int = 40, target_fps: int = 25):
        self.avatar_engine = avatar_engine
        self.chunk_duration_ms = chunk_duration_ms
        self.target_fps = target_fps

        self.ring_buffer = VideoRingBuffer(capacity=400)
        self.audio_chunk_queue: queue.Queue = queue.Queue(maxsize=1000)

        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._on_frame_ready_callbacks: List[Callable[[np.ndarray], None]] = []

    def start(self):
        """启动流水线异步消费线程"""
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(target=self._pipeline_worker, daemon=True, name="ChunkPipelineWorker")
        self._worker_thread.start()
        logger.info(f"[ChunkPipeline] 流水线工作线程已就绪 (粒度: {self.chunk_duration_ms}ms, 帧率: {self.target_fps} FPS)")

    def stop(self):
        """停止流水线"""
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=0.5)
        self.ring_buffer.clear()
        logger.info("[ChunkPipeline] 流水线已停止")

    def register_frame_listener(self, callback: Callable[[np.ndarray], None]):
        """注册帧生成回调监听器"""
        self._on_frame_ready_callbacks.append(callback)

    def push_audio(self, pcm_data: bytes, sample_rate: int = 16000):
        """向流水线灌入音频数据 (自动以 40ms/80ms 进行无缝分块切片)"""
        if not pcm_data or not self._running:
            return

        bytes_per_sample = 2  # 16-bit PCM
        samples_per_chunk = int(sample_rate * (self.chunk_duration_ms / 1000.0))
        chunk_bytes_len = samples_per_chunk * bytes_per_sample

        total_len = len(pcm_data)
        offset = 0
        while offset < total_len and self._running:
            end = min(total_len, offset + chunk_bytes_len)
            chunk = pcm_data[offset:end]
            offset = end

            try:
                self.audio_chunk_queue.put((chunk, sample_rate), timeout=0.1)
            except queue.Full:
                logger.warning("[ChunkPipeline] 音频块队列满，丢弃旧块")
                try:
                    self.audio_chunk_queue.get_nowait()
                    self.audio_chunk_queue.put((chunk, sample_rate), timeout=0.05)
                except Exception:
                    pass

    def get_next_frame(self) -> np.ndarray:
        """获取下一帧：说话时返回口型同步帧，静默时返回待命呼吸帧"""
        frame = self.ring_buffer.pop_frame()
        if frame is not None:
            return frame

        # 无语音帧时，生成自然的待命呼吸/眨眼帧
        if self.avatar_engine:
            idle = self.avatar_engine.generate_idle_frame()
            self.ring_buffer.set_idle_frame(idle)
            return idle

        # 默认黑屏
        return np.zeros((720, 720, 3), dtype=np.uint8)

    def reset(self):
        """打断通话时清空音频与视频缓冲"""
        while not self.audio_chunk_queue.empty():
            try:
                self.audio_chunk_queue.get_nowait()
            except Exception:
                break
        self.ring_buffer.clear()
        if self.avatar_engine:
            self.avatar_engine.reset()
        logger.info("[ChunkPipeline] 会话重置，缓冲队列已清空")

    def _pipeline_worker(self):
        """流水线核心工作循环：异步消费音频块并生成视频帧序列推入 RingBuffer"""
        while self._running:
            try:
                chunk, sr = self.audio_chunk_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                if self.avatar_engine:
                    frames = self.avatar_engine.process_audio_chunk(chunk, sample_rate=sr)
                    if frames:
                        self.ring_buffer.push_frames(frames)
                        for cb in self._on_frame_ready_callbacks:
                            for f in frames:
                                cb(f)
            except Exception as e:
                logger.error(f"[ChunkPipeline] 推理音频块异常: {e}", exc_info=True)
            finally:
                self.audio_chunk_queue.task_done()
