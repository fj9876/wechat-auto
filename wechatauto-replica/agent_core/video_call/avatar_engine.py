# -*- coding: utf-8 -*-
"""虚拟数字人多引擎基类与总控管理器 (agent_core.video_call.avatar_engine)

提供统一的数字人驱动标准接口：
1. BaseAvatarEngine: 抽象驱动基类
2. MockFallbackAvatarEngine: 轻量级自适应拟真兜底驱动器 (零权重依赖，保障立即可用)
3. AvatarEngineManager: 统一调度器，支持 LivePortrait-Realtime 与 MuseTalk 在运行时动态无缝切换
"""
from __future__ import annotations

import os
import math
import time
import random
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
import numpy as np
import cv2

logger = logging.getLogger("AvatarEngine")


class BaseAvatarEngine(ABC):
    """数字人驱动引擎抽象基类"""

    @abstractmethod
    def initialize(self, model_dir: str = "", device: str = "cuda") -> bool:
        """初始化加载模型权重 (若权重缺失应优雅返回 False 而非崩溃)"""
        pass

    @abstractmethod
    def set_character_image(self, image_path: str) -> bool:
        """加载用户自定义正面立绘人物图片并提取人脸特征"""
        pass

    @abstractmethod
    def generate_idle_frame(self) -> np.ndarray:
        """生成待命/思考/倾听时的自然微动作视频帧 (RGB 格式，720x720)"""
        pass

    @abstractmethod
    def process_audio_chunk(self, pcm_chunk: bytes, sample_rate: int = 16000) -> List[np.ndarray]:
        """将一段 PCM 语音块转化为音画同步的唇形动画视频帧序列"""
        pass

    @abstractmethod
    def reset(self):
        """通话打断或会话重置时的状态复位"""
        pass


class MockFallbackAvatarEngine(BaseAvatarEngine):
    """自适应视觉动画兜底引擎 (Pure OpenCV / CPU & GPU 极速)
    
    作用：
    当 LivePortrait 或 MuseTalk 庞大权重尚未下载或显存受限时，
    该引擎通过直接对用户自定义正面立绘图片实施微扰动：
    - 正弦波人体自然呼吸与头颈微动 (Breathing & Micro-movement)
    - 随机生理眨眼微闭合 (Blinking)
    - 紧密追踪 TTS 音频振幅 (RMS 能量包络) 的平滑下颌与嘴唇开合同步 (Volume-driven Lip Sync)
    保证用户能立刻预览到生动的虚拟数字人，绝不白屏、绝不卡死！
    """

    def __init__(self):
        self.raw_image: Optional[np.ndarray] = None
        self.canvas_size = (720, 720)
        self.face_center = (360, 360)
        self.mouth_rect = (320, 410, 400, 480)  # x1, y1, x2, y2
        self.eye_y = 350
        self.frame_idx = 0
        self.blink_countdown = 60
        self.is_blinking = 0

    def initialize(self, model_dir: str = "", device: str = "cuda") -> bool:
        logger.info("[MockFallbackEngine] 拟真视觉动画引擎就绪 (无需外部重型权重)")
        return True

    def set_character_image(self, image_path: str) -> bool:
        if not os.path.exists(image_path):
            logger.warning(f"[MockFallbackEngine] 图片文件不存在: {image_path}")
            return False

        try:
            # 读取图片并统一规整为 720x720 RGB
            bgr = cv2.imread(image_path)
            if bgr is None:
                return False

            h, w = bgr.shape[:2]
            # 等比例缩放裁剪到 720x720
            scale = max(720 / w, 720 / h)
            nw, nh = int(w * scale), int(h * scale)
            resized = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)

            cx, cy = nw // 2, nh // 2
            x1 = max(0, cx - 360)
            y1 = max(0, cy - 360)
            cropped = resized[y1:y1 + 720, x1:x1 + 720]
            if cropped.shape[0] != 720 or cropped.shape[1] != 720:
                cropped = cv2.resize(cropped, (720, 720))

            self.raw_image = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)

            # 使用 Haar Cascade 粗略检测人脸位置以获得嘴唇和眼睛准确区域
            try:
                gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
                cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                if os.path.exists(cascade_path):
                    face_cascade = cv2.CascadeClassifier(cascade_path)
                    faces = face_cascade.detectMultiScale(gray, 1.1, 4)
                    if len(faces) > 0:
                        fx, fy, fw, fh = int(faces[0][0]), int(faces[0][1]), int(faces[0][2]), int(faces[0][3])
                        self.face_center = (float(fx + fw // 2), float(fy + fh // 2))
                        self.eye_y = int(fy + int(fh * 0.38))
                        self.mouth_rect = (
                            int(fx + int(fw * 0.30)),
                            int(fy + int(fh * 0.68)),
                            int(fx + int(fw * 0.70)),
                            int(fy + int(fh * 0.88))
                        )
                        logger.info(f"[MockFallbackEngine] 自动定位人脸特征区域: 人脸中心={self.face_center}, 嘴部={self.mouth_rect}")
            except Exception as e:
                logger.debug(f"[MockFallbackEngine] 人脸特征定位跳过使用预设值: {e}")

            logger.info(f"[MockFallbackEngine] 成功装载正面立绘人物: {image_path}")
            return True
        except Exception as e:
            logger.error(f"[MockFallbackEngine] 加载立绘异常: {e}")
            return False

    def apply_head_motion(self, image: np.ndarray) -> np.ndarray:
        """对整幅人脸图像施加自然微晃律动 (确保口型与面部整体保持绝对刚体同步，杜绝局部撕裂与错位)"""
        if image is None:
            return image
        self.frame_idx += 1
        t = self.frame_idx * 0.08
        dy = int(1.5 * math.sin(t))
        dx = int(0.8 * math.cos(t * 0.6))
        rot = float(0.25 * math.sin(t * 0.4))
        cx, cy = float(self.face_center[0]), float(self.face_center[1])
        M = cv2.getRotationMatrix2D((cx, cy), rot, 1.0)
        M[0, 2] += dx
        M[1, 2] += dy
        return cv2.warpAffine(image, M, (720, 720), borderMode=cv2.BORDER_REFLECT)

    def generate_idle_frame(self) -> np.ndarray:
        if self.raw_image is None:
            canvas = np.zeros((720, 720, 3), dtype=np.uint8)
            cv2.putText(canvas, "No Character Image Loaded", (160, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
            return canvas
        return self.apply_head_motion(self.raw_image)

    def process_audio_chunk(self, pcm_chunk: bytes, sample_rate: int = 16000) -> List[np.ndarray]:
        """纯视觉保底兜底：伴随声音的自然微晃韵律，严禁做任何人工下巴矩形拉伸"""
        if not pcm_chunk or self.raw_image is None:
            return [self.generate_idle_frame()]

        try:
            samples = np.frombuffer(pcm_chunk, dtype=np.int16)
        except Exception:
            return [self.generate_idle_frame()]

        if len(samples) == 0:
            return [self.generate_idle_frame()]

        samples_per_frame = max(1, sample_rate // 25)
        num_frames = max(1, len(samples) // samples_per_frame)

        frames = []
        for _ in range(num_frames):
            frames.append(self.generate_idle_frame())
        return frames

    def drive_by_expression(
        self,
        mouth_ratio: float = 0.0,
        eye_blink_ratio: float = 0.0,
        pitch: float = 0.0,
        yaw: float = 0.0,
        roll: float = 0.0
    ) -> np.ndarray:
        """兜底模式下响应外部真实运动参数 (头姿平移与倾斜)"""
        if self.raw_image is None:
            return self.generate_idle_frame()

        cx, cy = float(self.face_center[0]), float(self.face_center[1])
        rot = float(np.clip(roll * 1.8, -15.0, 15.0))
        dx = float(np.clip(yaw * 14.0, -40.0, 40.0))
        dy = float(np.clip(pitch * 12.0, -35.0, 35.0))

        M = cv2.getRotationMatrix2D((cx, cy), rot, 1.0)
        M[0, 2] += dx
        M[1, 2] += dy
        frame = cv2.warpAffine(self.raw_image, M, (720, 720), borderMode=cv2.BORDER_REFLECT)
        return frame

    def reset(self):
        self.frame_idx = 0
        self.is_blinking = 0


class AvatarEngineManager:
    """数字人驱动引擎总控调度器"""

    def __init__(self, config=None):
        self.config = config
        self.engine_type = "liveportrait"  # 默认首选 liveportrait，可选 musetalk
        self.current_engine: BaseAvatarEngine = MockFallbackAvatarEngine()
        self.character_image_path = "data/avatars/default_avatar.png"
        self._available_engines: Dict[str, BaseAvatarEngine] = {}

        self._init_engines()

    def _init_engines(self):
        """登记可用引擎并预先就绪核心推理会话"""
        # 1. 注册兜底自适应物理形变引擎
        fallback = MockFallbackAvatarEngine()
        fallback.initialize()
        self._available_engines["mock"] = fallback

        # 2. 尝试导入并初始化 LivePortrait-Realtime 引擎
        try:
            from agent_core.video_call.engines.liveportrait_engine import LivePortraitAvatarEngine
            lp_eng = LivePortraitAvatarEngine()
            lp_eng.initialize()
            self._available_engines["liveportrait"] = lp_eng
            logger.info(f"[AvatarManager] LivePortrait 引擎已登记 (权重载入状态: {lp_eng.is_weights_loaded})")
        except Exception as e:
            logger.warning(f"[AvatarManager] LivePortrait 模块初始化跳过: {e}")

        # 3. 尝试导入并初始化 Wav2Lip 极速高保真引擎 (OpenTalking 推荐轻量级路线)
        try:
            from agent_core.video_call.engines.wav2lip_engine import Wav2LipAvatarEngine
            w_eng = Wav2LipAvatarEngine()
            w_eng.initialize()
            self._available_engines["wav2lip"] = w_eng
            logger.info(f"[AvatarManager] Wav2Lip 引擎已登记 (权重载入状态: {w_eng.is_weights_loaded})")
        except Exception as e:
            logger.warning(f"[AvatarManager] Wav2Lip 模块初始化跳过: {e}")

        # 4. 尝试导入并初始化 MuseTalk 引擎
        try:
            from agent_core.video_call.engines.musetalk_engine import MuseTalkAvatarEngine
            mt_eng = MuseTalkAvatarEngine()
            mt_eng.initialize()
            self._available_engines["musetalk"] = mt_eng
            logger.info(f"[AvatarManager] MuseTalk 引擎已登记 (权重载入状态: {mt_eng.is_weights_loaded})")
        except Exception as e:
            logger.warning(f"[AvatarManager] MuseTalk 模块初始化跳过: {e}")

        # 5. 检查是否开启 Sidecar 独立进程隔离模式
        use_sidecar = False
        if self.config and hasattr(self.config, "voip"):
            use_sidecar = getattr(self.config.voip, "use_sidecar", False)

        if use_sidecar:
            try:
                from agent_core.video_call.sidecar.sidecar_client import SidecarAvatarEngineClient
                sidecar_client = SidecarAvatarEngineClient(port=18990)
                self._available_engines["sidecar"] = sidecar_client
                logger.info("[AvatarManager] ✅ Sidecar 独立进程隔离客户端已装配")
            except Exception as e:
                logger.warning(f"[AvatarManager] Sidecar 客户端初始化跳过: {e}")

        # 默认生效配置的引擎
        cfg_eng = "liveportrait"
        if self.config and hasattr(self.config, "voip") and hasattr(self.config.voip, "avatar_engine"):
            cfg_eng = getattr(self.config.voip, "avatar_engine", "liveportrait").lower()
        self.set_engine_type(cfg_eng)

        # 6. 初始化流水线帧编排机制 (Chunk-Pipeline & Ring Buffer)
        try:
            from agent_core.video_call.pipeline.chunk_pipeline import StreamChunkPipeline
            self.pipeline = StreamChunkPipeline(avatar_engine=self.current_engine, chunk_duration_ms=40, target_fps=25)
            self.pipeline.start()
            logger.info("[AvatarManager] ✅ 40ms 流式分块流水线 (Chunk-Pipeline & RingBuffer) 已就绪")
        except Exception as e:
            logger.warning(f"[AvatarManager] 流水线启动异常: {e}")
            self.pipeline = None

    def set_engine_type(self, engine_name: str) -> bool:
        """在运行时由用户选择使用那一套引擎 (liveportrait / wav2lip / musetalk)"""
        engine_name = engine_name.lower().strip()
        logger.info(f"[AvatarManager] 切换数字人推理引擎至: [{engine_name}]")

        target_engine = None
        if engine_name in self._available_engines:
            target_engine = self._available_engines[engine_name]
        elif "wav2lip" in engine_name and "wav2lip" in self._available_engines:
            target_engine = self._available_engines["wav2lip"]
        elif "liveportrait" in engine_name and "liveportrait" in self._available_engines:
            target_engine = self._available_engines["liveportrait"]
        elif "musetalk" in engine_name and "musetalk" in self._available_engines:
            target_engine = self._available_engines["musetalk"]

        if target_engine is None:
            logger.warning(f"[AvatarManager] 指定引擎 [{engine_name}] 暂不可用，使用拟真视觉引擎兜底")
            target_engine = self._available_engines["mock"]

        if self.current_engine == target_engine and getattr(target_engine, "is_weights_loaded", True):
            logger.info(f"[AvatarManager] 目标引擎 [{engine_name}] 已经处于激活状态，无需重复初始化")
            return True

        self.engine_type = engine_name
        self.current_engine = target_engine

        # 更新流水线绑定的当前引擎
        if hasattr(self, "pipeline") and self.pipeline:
            self.pipeline.avatar_engine = self.current_engine

        # 确保目标引擎初始化
        try:
            if hasattr(self.current_engine, "is_weights_loaded") and not self.current_engine.is_weights_loaded:
                self.current_engine.initialize()
        except Exception as e:
            logger.debug(f"[AvatarManager] 引擎再次初始化尝试: {e}")

        # 重新应用人物立绘
        if self.character_image_path and os.path.exists(self.character_image_path):
            self.current_engine.set_character_image(self.character_image_path)
        return True

    def set_character_image(self, image_path: str) -> bool:
        """设置当前人物正面立绘"""
        if not os.path.exists(image_path):
            logger.warning(f"[AvatarManager] 立绘路径不存在: {image_path}")
            return False

        self.character_image_path = image_path
        # 通知当前激活引擎与兜底引擎
        ok = self.current_engine.set_character_image(image_path)
        if "mock" in self._available_engines and self.current_engine != self._available_engines["mock"]:
            self._available_engines["mock"].set_character_image(image_path)
        return ok

    def generate_idle_frame(self) -> np.ndarray:
        """生成待命/思考/倾听画面帧 (优先调用神经引擎)"""
        try:
            return self.current_engine.generate_idle_frame()
        except Exception as e:
            logger.debug(f"[AvatarManager] 待命帧生成降级尝试: {e}")

        # 优先平滑回退至已就绪的 FasterLivePortrait 神经引擎
        lp_eng = self._available_engines.get("liveportrait")
        if lp_eng and getattr(lp_eng, "is_weights_loaded", False) and self.current_engine != lp_eng:
            try:
                return lp_eng.generate_idle_frame()
            except Exception:
                pass

        return self._available_engines["mock"].generate_idle_frame()

    def process_audio_chunk(self, pcm_chunk: bytes, sample_rate: int = 16000) -> List[np.ndarray]:
        """将音频转换为唇形同步动画帧 (优先调用神经引擎)"""
        try:
            frames = self.current_engine.process_audio_chunk(pcm_chunk, sample_rate)
            if frames and len(frames) > 0:
                return frames
        except Exception as e:
            logger.warning(f"[AvatarManager] 主引擎唇形推理异常，尝试神经级联降级: {e}")

        # 优先平滑回退至已就绪的 FasterLivePortrait 神经引擎，杜绝假形变
        lp_eng = self._available_engines.get("liveportrait")
        if lp_eng and getattr(lp_eng, "is_weights_loaded", False) and self.current_engine != lp_eng:
            try:
                frames = lp_eng.process_audio_chunk(pcm_chunk, sample_rate)
                if frames and len(frames) > 0:
                    return frames
            except Exception as e_lp:
                logger.debug(f"[AvatarManager] 级联 LivePortrait 异常: {e_lp}")

        return self._available_engines["mock"].process_audio_chunk(pcm_chunk, sample_rate)

    def push_audio_stream(self, pcm_chunk: bytes, sample_rate: int = 16000):
        """流式分块输入：通过 Chunk-Pipeline 异步推流"""
        if hasattr(self, "pipeline") and self.pipeline:
            self.pipeline.push_audio(pcm_chunk, sample_rate=sample_rate)
        else:
            frames = self.process_audio_chunk(pcm_chunk, sample_rate)

    def drive_by_expression(
        self,
        mouth_ratio: float = 0.0,
        eye_blink_ratio: float = 0.0,
        pitch: float = 0.0,
        yaw: float = 0.0,
        roll: float = 0.0
    ) -> np.ndarray:
        """接收外部真实动作参数实时驱动数字人立绘 (本地摄像头动作驱动)"""
        # 1. 优先使用 LivePortrait 神经关键帧形变与 3D 头部旋转驱动
        lp = self._available_engines.get("liveportrait")
        if lp and getattr(lp, "is_weights_loaded", False) and hasattr(lp, "drive_by_expression"):
            return lp.drive_by_expression(mouth_ratio, eye_blink_ratio, pitch, yaw, roll)

        # 2. 回退至当前引擎或兜底引擎实现
        if hasattr(self.current_engine, "drive_by_expression"):
            return self.current_engine.drive_by_expression(mouth_ratio, eye_blink_ratio, pitch, yaw, roll)
        return self.generate_idle_frame()

    def start_webcam_driver(self, device_index: int = 0, on_rendered_frame: Optional[Callable[[np.ndarray], None]] = None) -> bool:
        """启动本地真实摄像头动作捕捉驱动数字人"""
        from agent_core.video_call.webcam_tracker import WebcamTracker
        if hasattr(self, "webcam_tracker") and self.webcam_tracker and self.webcam_tracker.is_running:
            self.webcam_tracker.stop()

        def _on_motion(motion, raw_cam):
            avatar_frame = self.drive_by_expression(
                mouth_ratio=motion.get("mouth_ratio", 0.0),
                eye_blink_ratio=motion.get("eye_blink_ratio", 0.0),
                pitch=motion.get("pitch", 0.0),
                yaw=motion.get("yaw", 0.0),
                roll=motion.get("roll", 0.0)
            )
            self._latest_webcam_driven_frame = avatar_frame
            if on_rendered_frame:
                try:
                    on_rendered_frame(avatar_frame)
                except Exception:
                    pass

        self._latest_webcam_driven_frame = None
        self.webcam_tracker = WebcamTracker(device_index=device_index, on_motion_frame=_on_motion)
        ok = self.webcam_tracker.start()
        logger.info(f"[AvatarManager] 本地摄像头数字人动作驱动器启动: {ok}")
        return ok

    def stop_webcam_driver(self):
        """停止本地物理摄像头驱动数字人"""
        if hasattr(self, "webcam_tracker") and self.webcam_tracker:
            self.webcam_tracker.stop()
            self.webcam_tracker = None
        self._latest_webcam_driven_frame = None
        logger.info("[AvatarManager] 本地摄像头数字人动作驱动器已关闭")

    def get_stream_frame(self) -> np.ndarray:
        """从推流管道获取下一帧 (支持真人本地摄像头实时驱动优先)"""
        if getattr(self, "_latest_webcam_driven_frame", None) is not None:
            return self._latest_webcam_driven_frame

        if hasattr(self, "pipeline") and self.pipeline:
            return self.pipeline.get_next_frame()
        return self.generate_idle_frame()

    def reset(self):
        """通话打断复位"""
        if hasattr(self, "pipeline") and self.pipeline:
            self.pipeline.reset()
        try:
            self.current_engine.reset()
        except Exception:
            pass
        if "mock" in self._available_engines:
            self._available_engines["mock"].reset()
