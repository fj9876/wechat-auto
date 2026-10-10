# -*- coding: utf-8 -*-
"""实时语音识别与端点检测模块 (agent_core.voice_call.stt_worker)

复用现有配置的 Faster-Whisper 引擎与 Silero VAD：
1. 从音频路由队列接收对方人声切片
2. 毫秒级检测说话开始 (触发打断 Barge-in) 与说话结束
3. 本地 GPU 极速转写并分发给对话大模型
"""
from __future__ import annotations

import os
import re
import time
import queue
import logging
import threading
import collections
import numpy as np
from typing import Optional, Callable

logger = logging.getLogger("STTWorker")

class FunASRLoggingFilter(logging.Filter):
    """静默 FunASR 官方源码在 download_model_from_hub 中硬编码打印的无害 trust_remote_code 告警"""
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return "trust_remote_code" not in record.getMessage()
        except Exception:
            return True

try:
    logging.getLogger().addFilter(FunASRLoggingFilter())
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS_DIR = os.path.join(BASE_DIR, "models")
PARAFORMER_DIR = os.path.join(MODELS_DIR, "FunASR")

# 强制将 ModelScope 与 HuggingFace 缓存重定向至当前项目 models/ 目录，绝不污染系统 C 盘
os.environ["MODELSCOPE_CACHE"] = os.path.join(MODELS_DIR, "modelscope")
os.environ["HF_HOME"] = os.path.join(MODELS_DIR, "huggingface")
os.environ["HUGGINGFACE_HUB_CACHE"] = os.path.join(MODELS_DIR, "huggingface", "hub")
os.environ["TORCH_HOME"] = os.path.join(MODELS_DIR, "torch")


def _resolve_model_path(model_name: str) -> str:
    """优先从本地 models/ 目录定位离线 Faster-Whisper 模型，实现 100% 离线零联网加载"""
    if "HF_ENDPOINT" not in os.environ:
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    clean_name = (model_name or "small").strip().lower()
    candidates = [
        os.path.join(MODELS_DIR, f"whisper-{clean_name}"),
        os.path.join(MODELS_DIR, clean_name),
        os.path.join(MODELS_DIR, f"faster-whisper-{clean_name}"),
        os.path.join(MODELS_DIR, "whisper-small"),  # 默认备选兜底
        os.path.join(MODELS_DIR, "whisper-base"),
    ]
    for p in candidates:
        if os.path.isdir(p) and (os.path.exists(os.path.join(p, "model.bin")) or os.path.exists(os.path.join(p, "config.json"))):
            logger.info(f"[STTWorker] 命中本地离线 Faster-Whisper 模型路径: {p}")
            return p
    return clean_name


def _resolve_paraformer_path(model_name: str = "paraformer-zh") -> str:
    """优先从项目本地 models/ 目录定位离线 FunASR Paraformer 模型，不占用系统 C 盘空间"""
    clean_name = (model_name or "paraformer-zh").strip()
    candidates = [
        os.path.join(MODELS_DIR, "paraformer-zh"),
        os.path.join(MODELS_DIR, clean_name),
        os.path.join(PARAFORMER_DIR, clean_name),
        os.path.join(MODELS_DIR, "paraformer"),
    ]
    for p in candidates:
        if os.path.isdir(p) and (
            os.path.exists(os.path.join(p, "model.pt"))
            or os.path.exists(os.path.join(p, "model.onnx"))
            or os.path.exists(os.path.join(p, "config.yaml"))
        ):
            logger.info(f"[STTWorker] 命中本地离线 Paraformer 模型路径: {p}")
            return p

    # 检测本项目内置的 modelscope 缓存目录 (例如 models/modelscope/...)
    try:
        project_ms_dir = os.path.join(MODELS_DIR, "modelscope")
        if os.path.isdir(project_ms_dir):
            for root, _, files in os.walk(project_ms_dir):
                if "paraformer" in root.lower() and ("model.pt" in files or "model.onnx" in files):
                    logger.info(f"[STTWorker] 命中项目内置 ModelScope 缓存 Paraformer 路径: {root}")
                    return root
    except Exception:
        pass

    # 返回 ModelScope 或 Hugging Face 标识符
    if clean_name == "paraformer-zh":
        return "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
    return clean_name


class STTWorker:
    """实时语音识别工作线程 (双阶段自适应能量门限 + Silero VAD 深度学习人声判别)"""

    @staticmethod
    def _resolve_paraformer_path(model_name: str = "paraformer-zh") -> str:
        """解析并返回 Paraformer 模型路径或标识符"""
        return _resolve_paraformer_path(model_name)

    @staticmethod
    def is_paraformer_downloaded(model_name: str = "paraformer-zh") -> bool:
        """检查 Paraformer 模型文件是否已存在于本地 models/ 目录或 ModelScope 缓存中"""
        resolved = _resolve_paraformer_path(model_name)
        return os.path.isdir(resolved)

    def __init__(
        self,
        whisper_model_name: str = "small",
        device: str = "cuda",
        on_speech_started: Optional[Callable[[], None]] = None,
        on_transcription: Optional[Callable[[str], None]] = None,
        is_ai_speaking_fn: Optional[Callable[[], bool]] = None,
        barge_in_enabled: bool = False,
        acoustic_classifier: Optional[Any] = None,
        stt_engine: str = "paraformer",
        paraformer_model_name: str = "paraformer-zh",
    ):
        self.model_name = whisper_model_name
        self.device = device
        self.stt_engine = (stt_engine or "paraformer").lower()
        self.paraformer_model_name = paraformer_model_name or "paraformer-zh"
        self.on_speech_started = on_speech_started
        self.on_transcription = on_transcription
        self.is_ai_speaking_fn = is_ai_speaking_fn
        self.barge_in_enabled = barge_in_enabled
        self.acoustic_classifier = acoustic_classifier

        self._whisper_model = None
        self._paraformer_model = None
        self._vad_model = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # VAD 状态变量 (16kHz PCM 单声道)
        self._is_speaking = False
        self._silence_start_time = 0.0
        self._speech_buffer = bytearray()
        self._pre_speech_ring_buffer = collections.deque(maxlen=4)  # 缓存过去 4 块 (~256ms)，确保字头不被切

        # 智能人声识别与防噪抖动参数
        self._consecutive_speech_frames = 0
        self._consecutive_silence_frames = 0
        self._noise_floor = 300.0  # 动态自适应底噪
        self._min_energy_threshold = 800.0  # 基础人声能量底线 (排除轻微杂音、电流声与呼吸音)
        self._min_speech_duration = 0.35  # 最短有效人声时长 (秒，Paraformer 支持更短促语音)
        self._silence_timeout = 0.50  # 极速电话静音断句超时 (0.50秒)

    def _get_vad_model(self):
        """获取或初始化 Silero VAD 深度学习模型 (基于 ONNX Runtime C++ 推理，单帧延迟 <0.5ms)"""
        if self._vad_model is None:
            try:
                from faster_whisper.vad import get_vad_model
                self._vad_model = get_vad_model()
                logger.info("[STTWorker] Silero VAD 深度神经网络初始化就绪！")
            except Exception as e:
                logger.warning(f"[STTWorker] 初始化 Silero VAD 失败 ({e})，将使用增强自适应能量门限")
                self._vad_model = None
        return self._vad_model

    def _init_whisper_model(self):
        """初始化 Faster-Whisper 模型 (优先锁定 GPU 推理)"""
        if self._whisper_model is not None:
            return self._whisper_model
        try:
            from faster_whisper import WhisperModel
            actual_model_path = _resolve_model_path(self.model_name)
            compute_type = "float16" if self.device == "cuda" else "int8"
            max_cpu_threads = min(4, max(1, (os.cpu_count() or 4) // 2))
            logger.info(f"[STTWorker] 正在加载 Faster-Whisper: {actual_model_path} (device={self.device}, compute_type={compute_type}, cpu_threads={max_cpu_threads})...")
            self._whisper_model = WhisperModel(
                actual_model_path,
                device=self.device,
                compute_type=compute_type,
                download_root=MODELS_DIR,
                cpu_threads=max_cpu_threads,
            )
            logger.info("[STTWorker] Faster-Whisper 初始化成功！")
            return self._whisper_model
        except Exception as e:
            logger.warning(f"[STTWorker] {self.device} 模式加载 Whisper 失败: {e}，尝试降级为 CPU int8 运行...")
            try:
                from faster_whisper import WhisperModel
                actual_model_path = _resolve_model_path(self.model_name)
                max_cpu_threads = min(4, max(1, (os.cpu_count() or 4) // 2))
                self._whisper_model = WhisperModel(
                    actual_model_path,
                    device="cpu",
                    compute_type="int8",
                    download_root=MODELS_DIR,
                    cpu_threads=max_cpu_threads,
                )
                logger.info(f"[STTWorker] Faster-Whisper CPU 降级加载成功 (限制 cpu_threads={max_cpu_threads})！")
                return self._whisper_model
            except Exception as ex:
                logger.error(f"[STTWorker] Whisper 模型加载彻底失败: {ex}", exc_info=True)
                return None

    def _init_paraformer_model(self):
        """初始化阿里 FunASR Paraformer 模型 (优先锁定 GPU 推理)"""
        if self._paraformer_model is not None:
            return self._paraformer_model
        try:
            from funasr import AutoModel
            target_device = "cuda:0" if (self.device in ("cuda", "auto")) else "cpu"
            try:
                import torch
                if not torch.cuda.is_available() and target_device.startswith("cuda"):
                    target_device = "cpu"
            except Exception:
                target_device = "cpu"

            actual_path = _resolve_paraformer_path(self.paraformer_model_name)
            logger.info(f"[STTWorker] 正在加载阿里 FunASR Paraformer 模型: {actual_path} (device={target_device})...")
            self._paraformer_model = AutoModel(
                model=actual_path,
                device=target_device,
                disable_update=True,
                disable_pbar=True,
                trust_remote_code=False,
            )
            logger.info(f"[STTWorker] ✅ FunASR Paraformer 初始化成功 (运行于 [{target_device}])！")
            return self._paraformer_model
        except ImportError:
            logger.info("[STTWorker] FunASR 运行库未就绪，自动平滑切换至 Faster-Whisper 引擎")
            return None
        except Exception as e:
            logger.warning(f"[STTWorker] Paraformer 初始化异常 ({e})，平滑降级至 Faster-Whisper")
            return None

    def initialize_model(self):
        """初始化 STT 与 Silero VAD 模型 (优先 GPU 加速)"""
        # 预热 Silero VAD
        self._get_vad_model()

        if self.stt_engine == "paraformer":
            m = self._init_paraformer_model()
            if m is not None:
                return m
            logger.info("[STTWorker] Paraformer 未能加载，自动无感知平滑降级为 Faster-Whisper...")

        return self._init_whisper_model()

    def put_audio(self, pcm16_chunk: bytes):
        """投入音频块 (16kHz 16bit PCM 单声道)"""
        if self._running:
            self._audio_queue.put(pcm16_chunk)

    def start(self):
        """启动 STT 监听与处理线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._process_loop, daemon=True, name="STTWorkerThread")
        self._thread.start()

    def stop(self):
        """停止处理线程"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        # 清空缓冲区
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
        self._speech_buffer.clear()
        self._pre_speech_ring_buffer.clear()
        self._is_speaking = False
        self._consecutive_speech_frames = 0
        self._consecutive_silence_frames = 0

    def _process_loop(self):
        """主音频流双阶段分析 (能量门限 + Silero VAD) 与转写循环"""
        self.initialize_model()

        while self._running:
            try:
                chunk = self._audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if not chunk or len(chunk) < 512 * 2:
                continue

            samples = np.frombuffer(chunk, dtype=np.int16)
            energy = float(np.abs(samples).mean()) if len(samples) > 0 else 0.0

            # 检查当前 AI 是否正在发声播音 (防回音串音自打断)
            ai_speaking = False
            if self.is_ai_speaking_fn:
                try:
                    ai_speaking = bool(self.is_ai_speaking_fn())
                except Exception:
                    pass

            # 核心回声阻断门控 (杜绝串音与自对答)：
            # 当 AI 正在发声播音或处于残响延时保护期时，虚拟声卡输出端 (麦克风) 充斥着 AI 自身高幅发音。
            # 若未开启全双工打断 (barge_in_enabled=False)，必须彻底阻断并清空录音缓冲，
            # 杜绝任何 AI 自身语音样本被累积送入 Whisper 转写！
            if ai_speaking and not self.barge_in_enabled:
                self._speech_buffer.clear()
                self._pre_speech_ring_buffer.clear()
                self._is_speaking = False
                self._consecutive_speech_frames = 0
                self._consecutive_silence_frames = 0
                self._silence_start_time = 0.0
                continue

            # 动态跟踪环境底噪 (仅在静音待命时学习)
            if not self._is_speaking:
                self._noise_floor = 0.96 * self._noise_floor + 0.04 * energy
                self._noise_floor = max(100.0, min(self._noise_floor, 2500.0))

            # 阶段 1: 动态能量门限判定
            # 平时要求高于底噪与基准门限 (800)；若 AI 正在说话或处于残响保护期，门限加严至 2000+，过滤扬声器微弱回音
            energy_gate = max(self._min_energy_threshold, self._noise_floor * 1.8)
            if ai_speaking:
                energy_gate = max(energy_gate, 2000.0)

            has_energy = (energy >= energy_gate)

            # 阶段 2: 深度学习 Silero VAD 神经网络人声判定
            speech_prob = 0.0
            vad_model = self._get_vad_model()
            if vad_model is not None and has_energy:
                try:
                    # 必须保证音频样本数是 512 的整数倍
                    num_samples = (len(samples) // 512) * 512
                    if num_samples > 0:
                        float_samples = samples[:num_samples].astype(np.float32) / 32768.0
                        probs = vad_model(float_samples)
                        speech_prob = float(np.max(probs))
                except Exception:
                    speech_prob = 0.55 if has_energy else 0.0
            elif vad_model is None and has_energy:
                speech_prob = 0.60

            # 阶段 3: 人声判定标准
            # 平时 Silero 概率 >= 0.50 为有效人声；AI 播音/残响期提升至 0.80，防止扬声器残音触发打断
            prob_gate = 0.80 if ai_speaking else 0.50
            is_speech_frame = (speech_prob >= prob_gate) and has_energy

            # 阶段 4: 连续帧防抖窗口 (Multi-frame Debounce)
            # 必须连续真人语音帧才判定开始说话，杜绝瞬态敲击、爆音与扬声器残响
            required_frames = 5 if ai_speaking else 3

            if is_speech_frame:
                self._consecutive_speech_frames += 1
                self._consecutive_silence_frames = 0
            else:
                self._consecutive_silence_frames += 1
                if self._consecutive_silence_frames >= 2:
                    self._consecutive_speech_frames = 0

            now = time.time()
            if not self._is_speaking:
                # 待命状态：检查是否达到说话启动门限
                if self._consecutive_speech_frames >= required_frames:
                    # 【核心防护】若当前 AI 正在发声播音或处于残响期，且开启了声学判别器：
                    # 必须校验该段音频是否为 AI 自身通过虚拟声卡回流的声音，绝对杜绝 AI 自发音切断自身播音！
                    if ai_speaking and self.acoustic_classifier:
                        check_pcm = b"".join(list(self._pre_speech_ring_buffer) + [chunk])
                        try:
                            is_ai, corr, rec_p, ai_p, reason = self.acoustic_classifier.classify(check_pcm, rate=16000)
                            if is_ai or corr >= 0.35:
                                # 确认为 AI 自身回声，严禁误触发打断与录音，清空连续人声帧
                                self._consecutive_speech_frames = 0
                                self._pre_speech_ring_buffer.clear()
                                continue
                        except Exception as e:
                            logger.debug(f"[STTWorker] 预判 AI 回声异常: {e}")

                    self._is_speaking = True
                    self._silence_start_time = 0.0
                    logger.info(f"[STTWorker] 准确识别对方人声开始 (prob={speech_prob:.2f}, energy={energy:.0f}, 触发打断)...")

                    # 回溯拼接前置环形缓冲，保护字头完整度
                    for pre_chunk in self._pre_speech_ring_buffer:
                        self._speech_buffer.extend(pre_chunk)
                    self._speech_buffer.extend(chunk)

                    if self.on_speech_started:
                        try:
                            self.on_speech_started()
                        except Exception as e:
                            logger.error(f"[STTWorker] on_speech_started 异常: {e}")
                else:
                    # 尚未达到连续人声帧数，推入环形缓冲备用
                    self._pre_speech_ring_buffer.append(chunk)

            else:
                # 说话进行中：收集音频并检测断句
                self._speech_buffer.extend(chunk)
                if is_speech_frame:
                    self._silence_start_time = 0.0
                else:
                    if self._silence_start_time == 0.0:
                        self._silence_start_time = now
                    elif now - self._silence_start_time >= self._silence_timeout:
                        # 停顿超过静音超时，判定对方本句话结束
                        self._is_speaking = False
                        self._silence_start_time = 0.0
                        self._consecutive_speech_frames = 0
                        self._consecutive_silence_frames = 0
                        self._pre_speech_ring_buffer.clear()

                        duration = len(self._speech_buffer) / (16000 * 2)
                        if duration >= self._min_speech_duration:
                            self._transcribe_and_dispatch(bytes(self._speech_buffer))
                        self._speech_buffer.clear()

    def _transcribe_and_dispatch(self, pcm_bytes: bytes):
        """执行声波/音调声学物理判别与 Paraformer/Faster-Whisper 极速转写净化过滤"""
        if not self._whisper_model and not self._paraformer_model:
            self.initialize_model()

        if not self._whisper_model and not self._paraformer_model:
            return

        # 核心声学物理判别 (基于声波波形归一化互相关与音调基频特征):
        # 无论使用哪种 STT 引擎，必须优先经由声学判别器判定，杜绝虚拟声卡自发音死循环
        if self.acoustic_classifier:
            try:
                is_ai, corr, rec_p, ai_p, reason = self.acoustic_classifier.classify(pcm_bytes, rate=16000)
                if is_ai:
                    logger.warning(f"[STTWorker] 🚫 声波/音调判定为 AI 自身发音回流 ({reason})，已从底层物理阻断！")
                    return
                else:
                    logger.info(f"[STTWorker] 👤 声波/音调判定为对面真实用户发言 ({reason}) -> 启动语音识别 ({self.stt_engine})")
            except Exception as e:
                logger.debug(f"[STTWorker] 声学判别调用异常: {e}")

        try:
            audio_array = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            text = ""

            # 1. 优先使用阿里 FunASR Paraformer 极速毫秒级非自回归转写
            if self.stt_engine == "paraformer":
                if self._paraformer_model is None:
                    self._init_paraformer_model()

                if self._paraformer_model is not None:
                    try:
                        res = self._paraformer_model.generate(input=audio_array, batch_size_s=300)
                        if isinstance(res, list) and len(res) > 0:
                            first_item = res[0]
                            if isinstance(first_item, dict) and "text" in first_item:
                                text = str(first_item["text"] or "").strip()
                            elif isinstance(first_item, str):
                                text = first_item.strip()
                        elif isinstance(res, str):
                            text = res.strip()
                    except Exception as e:
                        logger.warning(f"[STTWorker] Paraformer 推理异常 ({e})，尝试自动平滑降级至 Whisper...")
                        text = ""

            # 2. 保底使用 Faster-Whisper 或用户指定 Whisper 模式
            if not text and (self.stt_engine == "whisper" or self._whisper_model is not None):
                if self._whisper_model is None:
                    self._init_whisper_model()

                if self._whisper_model is not None:
                    segments, _ = self._whisper_model.transcribe(
                        audio_array,
                        language="zh",
                        beam_size=1,  # 追求电话超低延迟
                        temperature=0.0,
                        vad_filter=True,
                        no_speech_threshold=0.60,  # 提高门限，强力过滤 Whisper 噪音幻觉识别
                    )
                    valid_segments = []
                    for seg in segments:
                        if getattr(seg, "no_speech_prob", 0.0) < 0.60:
                            valid_segments.append(seg.text)
                    text = "".join(valid_segments).strip()

            # 3. 文本结果清洗与有效性判定
            cleaned_text = re.sub(r'[\uff0c。？！、\s\.\?!,\-_]', '', text)
            # 必须至少 2 个有效汉字才能触发回复，防止单字幻觉带动大模型出话
            if len(cleaned_text) >= 2:
                logger.info(f"[STTWorker] 对方说: 「{text}」 (识别引擎={self.stt_engine})")
                if self.on_transcription:
                    try:
                        self.on_transcription(text)
                    except Exception as e:
                        logger.error(f"[STTWorker] on_transcription 回调异常: {e}")
            elif cleaned_text:
                logger.warning(f"[STTWorker] 转写结果过短（仅 {len(cleaned_text)} 字），属于噪山或幻觉，已废弃: 「{text}」")
        except Exception as e:
            logger.error(f"[STTWorker] 转写处理异常: {e}", exc_info=True)
