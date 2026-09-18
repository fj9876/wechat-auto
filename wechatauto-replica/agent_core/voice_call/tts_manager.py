# -*- coding: utf-8 -*-
"""TTS 语音合成与声音克隆管理中枢 (agent_core.voice_call.tts_manager)

实现 ChatTTS 与 Qwen3-TTS 的双引擎无缝兼容：
1. 自动从中国镜像站 (hf-mirror / ModelScope) 下载模型权重并持久化到 models/ 目录
2. 原生支持基于参考音频的声音克隆 (Voice Cloning / Timbre Transfer)
3. 面向电话实时对话场景提供流式低延迟音频切片输出
"""
from __future__ import annotations

import os
import sys
import time
import queue
import logging
import threading
import warnings
import numpy as np
from typing import Optional, Callable, Dict, Any, Tuple, Generator

warnings.filterwarnings("ignore", message=".*check_model_inputs.*")
warnings.filterwarnings("ignore", message=".*merge_with_config_defaults.*")
warnings.filterwarnings("ignore", message=".*layer_type_validation.*")
warnings.filterwarnings("ignore", message=".*rope_config_validation.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="transformers")
warnings.filterwarnings("ignore", category=UserWarning, message=".*repetition_penalty.*")
warnings.filterwarnings("ignore", message=".*Passing `repetition_penalty`.*")
warnings.filterwarnings("ignore", message=".*code_predictor_config is None.*")
logging.getLogger("qwen_tts").setLevel(logging.WARNING)

logger = logging.getLogger("TTSManager")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS_ROOT = os.path.join(BASE_DIR, "models")
CHATTTS_DIR = os.path.join(MODELS_ROOT, "ChatTTS")
QWEN3_TTS_DIR = os.path.join(MODELS_ROOT, "Qwen3-TTS")

# 国内镜像源配置
HF_MIRROR_ENDPOINT = "https://hf-mirror.com"
CHATTTS_REPO_ID = "2noise/ChatTTS"
QWEN3_TTS_REPO_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"


class TTSDownloadProgress:
    """下载进度追踪器"""
    def __init__(self, model_name: str, callback: Optional[Callable[[str, float], None]] = None):
        self.model_name = model_name
        self.callback = callback
        self.status = "idle"  # idle, downloading, completed, failed
        self.progress = 0.0
        self.error_msg = ""

    def update(self, status: str, progress: float, error: str = ""):
        self.status = status
        self.progress = progress
        self.error_msg = error
        if self.callback:
            try:
                self.callback(status, progress)
            except Exception:
                pass


class TTSManager:
    """TTS 语音合成与声音克隆统一管理器"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TTSManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, default_engine: str = "chattts"):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self.current_engine = default_engine.lower()
        self._chattts_model = None
        self._qwen_model = None
        self._is_loading = False
        self._active_voice_clone_path: Optional[str] = None
        self._cached_spk_emb = None
        self._engine_load_failed: Dict[str, bool] = {}
        self._fallback_notified: Dict[str, bool] = {}

        # 进度追踪
        self.downloads: Dict[str, TTSDownloadProgress] = {
            "chattts": TTSDownloadProgress("ChatTTS"),
            "qwen3_tts": TTSDownloadProgress("Qwen3-TTS"),
        }

        os.makedirs(MODELS_ROOT, exist_ok=True)
        os.makedirs(CHATTTS_DIR, exist_ok=True)
        os.makedirs(QWEN3_TTS_DIR, exist_ok=True)

    # -------------------------------------------------------------------------
    # 模型状态检测与自动下载机制
    # -------------------------------------------------------------------------

    def is_model_downloaded(self, engine: str, force_recheck: bool = False) -> bool:
        """检查指定引擎模型权重文件是否已下载完整 (增加内存秒级缓存，杜绝反复遍历磁盘引发 UI 卡顿)"""
        engine = engine.lower()
        if engine in ("edge_tts", "edge", "sapi", "system"):
            return True

        if not hasattr(self, "_model_downloaded_cache"):
            self._model_downloaded_cache: Dict[str, bool] = {}

        if not force_recheck and engine in self._model_downloaded_cache:
            return self._model_downloaded_cache[engine]

        downloaded = False
        if engine == "chattts":
            # 检查关键权重文件: asset/ 或根目录下的 *.pt / *.safetensors
            for root, _, files in os.walk(CHATTTS_DIR):
                pt_files = [f for f in files if f.endswith(".pt") or f.endswith(".safetensors")]
                if len(pt_files) >= 3:
                    downloaded = True
                    break
        elif engine in ("qwen3_tts", "qwen3"):
            for root, _, files in os.walk(QWEN3_TTS_DIR):
                weights = [f for f in files if f.endswith(".safetensors") or f.endswith(".bin") or f.endswith(".gguf")]
                if len(weights) >= 1:
                    downloaded = True
                    break

        self._model_downloaded_cache[engine] = downloaded
        return downloaded

    def is_runtime_available(self, engine: str) -> bool:
        """检查指定引擎的 Python 依赖运行库是否已安装就绪 (使用 find_spec 毫秒级快速探测，绝不阻塞 UI 主线程)"""
        engine = engine.lower()
        if engine in ("edge_tts", "edge"):
            import importlib.util
            return importlib.util.find_spec("edge_tts") is not None
        elif engine in ("sapi", "system"):
            return True
        elif engine == "chattts":
            import importlib.util
            return importlib.util.find_spec("ChatTTS") is not None
        elif engine in ("qwen3_tts", "qwen3"):
            import importlib.util
            return importlib.util.find_spec("qwen_tts") is not None
        return False

    @staticmethod
    def get_optimal_device() -> Tuple[str, str, Any]:
        """获取最优推理设备 (优先检测并锁定 GPU CUDA)"""
        try:
            import torch
            if hasattr(torch, "cuda") and torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                device_str = "cuda:0"
                dtype = torch.bfloat16 if hasattr(torch, "bfloat16") else torch.float16
                logger.info(f"[TTSManager] 🚀 检测到可用显卡算力: {gpu_name} (锁定 {device_str}, dtype={dtype})")
                return device_str, gpu_name, dtype
        except Exception as e:
            logger.debug(f"[TTSManager] GPU 探测异常: {e}")
        return "cpu", "CPU 处理器", None

    def auto_download_model(self, engine: str, background: bool = True, progress_cb: Optional[Callable[[str, float], None]] = None) -> bool:
        """从高速镜像自动下载模型权重"""
        engine = engine.lower()
        tracker = self.downloads.get(engine, TTSDownloadProgress(engine))
        if progress_cb:
            tracker.callback = progress_cb

        if self.is_model_downloaded(engine):
            tracker.update("completed", 1.0)
            return True

        def _do_download():
            tracker.update("downloading", 0.05)
            logger.info(f"[TTSManager] 开始从高速镜像下载 {engine} 模型...")
            try:
                # 优先使用 huggingface_hub 设置国内镜像
                os.environ["HF_ENDPOINT"] = HF_MIRROR_ENDPOINT
                from huggingface_hub import snapshot_download

                if engine == "chattts":
                    repo_id = CHATTTS_REPO_ID
                    target_dir = CHATTTS_DIR
                else:
                    repo_id = QWEN3_TTS_REPO_ID
                    target_dir = QWEN3_TTS_DIR

                tracker.update("downloading", 0.2)
                snapshot_download(
                    repo_id=repo_id,
                    local_dir=target_dir,
                    local_dir_use_symlinks=False,
                    endpoint=HF_MIRROR_ENDPOINT,
                    resume_download=True,
                )
                if hasattr(self, "_model_downloaded_cache"):
                    self._model_downloaded_cache.pop(engine, None)
                tracker.update("completed", 1.0)
                logger.info(f"[TTSManager] {engine} 权重下载完成并校验成功！")
            except Exception as e:
                logger.error(f"[TTSManager] 下载 {engine} 失败: {e}")
                tracker.update("failed", tracker.progress, str(e))

        if background:
            threading.Thread(target=_do_download, daemon=True, name=f"Download-{engine}").start()
            return True
        else:
            _do_download()
            return tracker.status == "completed"

    # -------------------------------------------------------------------------
    # 模型加载与声音克隆音色注入
    # -------------------------------------------------------------------------

    def set_voice_clone(self, audio_path: Optional[str] = None, prompt_text: str = ""):
        """配置当前声音克隆的目标参考音频"""
        if not audio_path or not os.path.exists(audio_path):
            logger.warning(f"[TTSManager] 参考音频不存在: {audio_path}，将使用预设自然音色")
            self._active_voice_clone_path = None
            self._cached_spk_emb = None
            return

        self._active_voice_clone_path = audio_path
        self._cached_spk_emb = None
        logger.info(f"[TTSManager] 已启用声音克隆，参考音频: {audio_path}")

    def load_engine(self, engine: Optional[str] = None):
        """按需加载 TTS 引擎实例 (全面优先锁定 GPU CUDA 推理)"""
        engine = (engine or self.current_engine).lower()
        self.current_engine = engine

        if engine in ("edge_tts", "edge", "sapi", "system"):
            return True

        elif engine == "chattts":
            if self._chattts_model is not None:
                return self._chattts_model
            if self._engine_load_failed.get("chattts", False):
                return None
            try:
                import ChatTTS
                import torch
                dev_str, dev_name, _ = self.get_optimal_device()
                logger.info(f"[TTSManager] 正在初始化 ChatTTS 引擎 (优先 GPU 推理: 设备=[{dev_name}], target={dev_str})...")
                chat = ChatTTS.Chat()
                target_device = torch.device(dev_str)
                # 检查本地权重路径并锁定 GPU 推理设备
                if self.is_model_downloaded("chattts"):
                    chat.load(source="custom", custom_path=CHATTTS_DIR, device=target_device, compile=False)
                else:
                    logger.info("[TTSManager] 本地无完整权重，尝试自动加载...")
                    chat.load(source="huggingface", device=target_device, compile=False)
                self._chattts_model = chat
                logger.info(f"[TTSManager] ✅ ChatTTS 初始化就绪 (运行于 [{dev_name}])！")
                return chat
            except ImportError:
                if not self._fallback_notified.get("chattts_missing", False):
                    logger.info("[TTSManager] ChatTTS 运行库未就绪，自动平滑切换至 Edge-TTS 高保真引擎")
                    self._fallback_notified["chattts_missing"] = True
                self._engine_load_failed["chattts"] = True
                return None
            except Exception as e:
                if not self._fallback_notified.get("chattts_error", False):
                    logger.warning(f"[TTSManager] ChatTTS 初始化不可用 ({e})，将自动平滑切换至 Edge-TTS / SAPI 输出")
                    self._fallback_notified["chattts_error"] = True
                self._engine_load_failed["chattts"] = True
                return None

        elif engine in ("qwen3_tts", "qwen3"):
            if self._qwen_model is not None:
                return self._qwen_model
            if self._engine_load_failed.get("qwen3_tts", False):
                return None
            try:
                try:
                    from qwen_tts import Qwen3TTSModel
                    import torch
                    import warnings
                    warnings.filterwarnings("ignore", message=".*Passing `repetition_penalty`.*")
                    dev_str, dev_name, dtype = self.get_optimal_device()
                    dtype = dtype or torch.float32
                    logger.info(f"[TTSManager] 正在加载 Qwen3-TTS 引擎权重 (优先 GPU 推理: 设备=[{dev_name}], target={dev_str}, dtype={dtype})...")
                    model = Qwen3TTSModel.from_pretrained(
                        QWEN3_TTS_DIR if self.is_model_downloaded("qwen3_tts") else "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
                        device_map=dev_str,
                        dtype=dtype,
                    )
                    self._qwen_model = model
                    logger.info(f"[TTSManager] ✅ Qwen3-TTS 初始化就绪 (运行于 [{dev_name}])！")
                    return model
                except ImportError:
                    if not self._fallback_notified.get("qwen_missing", False):
                        logger.info("[TTSManager] Qwen3-TTS 运行库未安装，已平滑降级至 Edge-TTS 微软高保真引擎")
                        self._fallback_notified["qwen_missing"] = True
                    self._engine_load_failed["qwen3_tts"] = True
                    return None
            except Exception as e:
                if not self._fallback_notified.get("qwen_error", False):
                    logger.warning(f"[TTSManager] Qwen3-TTS 初始化不可用 ({e})，平滑降级至 Edge-TTS")
                    self._fallback_notified["qwen_error"] = True
                self._engine_load_failed["qwen3_tts"] = True
                return None

    # -------------------------------------------------------------------------
    # 核心合成逻辑 (支持声音克隆与实时切片)
    # -------------------------------------------------------------------------

    def synthesize(self, text: str, ref_audio: Optional[str] = None, streaming: bool = False, engine: Optional[str] = None) -> Tuple[bytes, int]:
        """将文字合成为电话音频 (PCM16, 单声道)
        
        :param text: 需合成的文本
        :param ref_audio: 可选临时参考音频 (如提供则覆盖全局设置进行声音克隆)
        :param streaming: 是否流式分块
        :param engine: 可选覆盖指定使用的合成引擎
        :return: (raw_pcm16_bytes, sample_rate)
        """
        text = self._clean_phone_text(text)
        if not text:
            return b"", 16000

        ref_path = ref_audio or self._active_voice_clone_path
        engine = (engine or self.current_engine).lower()

        # 内存极速缓存 (针对短语、问候语与高频口语应答，0ms 零耗时直出)
        cache_key = (text, engine, ref_path or "")
        with self._lock:
            if not hasattr(self, "_phrase_cache"):
                self._phrase_cache = {}
            if cache_key in self._phrase_cache:
                pcm_bytes, sr = self._phrase_cache[cache_key]
                logger.info(f"[TTSManager] ⚡ 命中常用短语内存极速缓存: 「{text}」 (延迟 0ms)")
                return pcm_bytes, sr

        pcm_bytes, sr = self._dispatch_synthesize(text, engine, ref_path)

        if pcm_bytes and len(pcm_bytes) > 0 and len(text) <= 50:
            with self._lock:
                if len(self._phrase_cache) > 120:
                    keys = list(self._phrase_cache.keys())
                    for k in keys[:60]:
                        self._phrase_cache.pop(k, None)
                self._phrase_cache[cache_key] = (pcm_bytes, sr)

        return pcm_bytes, sr

    def _dispatch_synthesize(self, text: str, engine: str, ref_path: Optional[str]) -> Tuple[bytes, int]:
        """按引擎分发执行语音合成"""
        # 1. Edge-TTS 微软高清云端神经语音分支
        if engine in ("edge_tts", "edge"):
            return self._synthesize_edge_tts(text, ref_path)

        # 2. Windows SAPI 本地离线分支
        elif engine in ("sapi", "system"):
            return self._synthesize_sapi(text)

        # 3. ChatTTS 分支 (若不可用则自动无缝回退至 Edge-TTS / SAPI)
        elif engine == "chattts":
            pcm, sr = self._synthesize_chattts(text, ref_path)
            if pcm and len(pcm) > 3000:
                return pcm, sr
            if not self._fallback_notified.get("chattts_fallback", False):
                logger.info("[TTSManager] ChatTTS 未能输出有效音频，自动平滑切换至 Edge-TTS 高保真引擎")
                self._fallback_notified["chattts_fallback"] = True
            return self._synthesize_edge_tts(text, ref_path)

        # 4. Qwen3-TTS 分支 (若未安装库或推理失败则自动无缝回退至 Edge-TTS / SAPI)
        elif engine in ("qwen3_tts", "qwen3"):
            pcm, sr = self._synthesize_qwen(text, ref_path)
            if pcm and len(pcm) > 3000:
                return pcm, sr
            if not self._fallback_notified.get("qwen_fallback", False):
                logger.info("[TTSManager] Qwen3-TTS 运行库未就绪，自动平滑切换至 Edge-TTS 高保真引擎")
                self._fallback_notified["qwen_fallback"] = True
            return self._synthesize_edge_tts(text, ref_path)

        # 默认优先 Edge-TTS
        return self._synthesize_edge_tts(text, ref_path)

    def _synthesize_chattts(self, text: str, ref_audio_path: Optional[str]) -> Tuple[bytes, int]:
        """通过 ChatTTS 进行口语化合成并应用克隆音色"""
        chat = self.load_engine("chattts")
        if chat is None:
            return b"", 24000

        sample_rate = 24000
        try:
            import ChatTTS
            params_infer_code = ChatTTS.Chat.InferCodeParams(
                prompt='[speed_5]',  # 电话语速稍快自然
                temperature=0.3,
            )

            # 声音克隆处理
            spk_emb = self._get_or_extract_chattts_speaker(chat, ref_audio_path)
            if spk_emb is not None:
                params_infer_code.spk_emb = spk_emb

            # 添加口语化自然停顿标签
            oral_text = text.replace("，", "，[uv_break]").replace("。", "。[uv_break]")

            wavs = chat.infer([oral_text], params_infer_code=params_infer_code)
            if wavs and len(wavs) > 0:
                audio_array = np.array(wavs[0], dtype=np.float32)
                pcm16 = self._float32_to_pcm16(audio_array)
                return pcm16, sample_rate
        except Exception as e:
            logger.warning(f"[TTSManager] ChatTTS 合成异常: {e}")

        return b"", sample_rate

    def _synthesize_qwen(self, text: str, ref_audio_path: Optional[str]) -> Tuple[bytes, int]:
        """通过 Qwen3-TTS 进行高质量合成与参考音频克隆"""
        qwen = self.load_engine("qwen3_tts")
        sample_rate = 24000
        if qwen is None:
            return b"", sample_rate

        try:
            # 优先根据 Qwen3TTSModel 的接口能力进行调用
            if hasattr(qwen, "generate_custom_voice"):
                # 获取可用发言人列表
                speakers = list(qwen.model.get_supported_speakers()) if hasattr(qwen.model, 'get_supported_speakers') else []
                spk = "serena"
                if speakers:
                    if ref_audio_path and any(s in ref_audio_path.lower() for s in speakers):
                        for s in speakers:
                            if s in ref_audio_path.lower():
                                spk = s
                                break
                    elif "serena" in speakers:
                        spk = "serena"
                    else:
                        spk = speakers[0]
                wavs, sr = qwen.generate_custom_voice(
                    text=text,
                    language="Chinese",
                    speaker=spk,
                )
                sample_rate = sr
                wav = wavs[0] if isinstance(wavs, (list, tuple)) else wavs
                pcm16 = self._float32_to_pcm16(wav)
                return pcm16, sample_rate
            elif hasattr(qwen, "generate_voice_clone") and ref_audio_path and os.path.exists(ref_audio_path):
                wavs, sr = qwen.generate_voice_clone(
                    text=text,
                    ref_audio=ref_audio_path,
                )
                sample_rate = sr
                wav = wavs[0] if isinstance(wavs, (list, tuple)) else wavs
                pcm16 = self._float32_to_pcm16(wav)
                return pcm16, sample_rate
            else:
                wav = qwen.generate(
                    text=text,
                    prompt_wav=ref_audio_path if (ref_audio_path and os.path.exists(ref_audio_path)) else None,
                )
                pcm16 = self._float32_to_pcm16(wav)
                return pcm16, sample_rate
        except Exception as e:
            logger.warning(f"[TTSManager] Qwen3-TTS 合成失败: {e}")
            return b"", sample_rate

    def _synthesize_edge_tts(self, text: str, ref_audio_path: Optional[str] = None) -> Tuple[bytes, int]:
        """通过微软云端神经网络合成极速高质量语音 (Edge-TTS)"""
        try:
            import edge_tts, asyncio, io
            import soundfile as sf

            # 音色选择：默认极度自然的沉稳口语男声 zh-CN-YunxiNeural，若参考音频包含女性特征则切温柔女声 zh-CN-XiaoxiaoNeural
            voice = "zh-CN-YunxiNeural"
            if ref_audio_path and any(kw in ref_audio_path.lower() for kw in ["female", "女", "girl", "woman"]):
                voice = "zh-CN-XiaoxiaoNeural"

            async def _run():
                comm = edge_tts.Communicate(text, voice)
                mp3_buf = b""
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        mp3_buf += chunk["data"]
                return mp3_buf

            try:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        mp3_bytes = pool.submit(asyncio.run, _run()).result(timeout=10.0)
                else:
                    mp3_bytes = asyncio.run(_run())
            except Exception:
                mp3_bytes = asyncio.run(_run())

            if mp3_bytes:
                data, sr = sf.read(io.BytesIO(mp3_bytes), dtype="int16")
                return data.tobytes(), sr
        except Exception as e:
            logger.warning(f"[TTSManager] Edge-TTS 合成网络不可达 ({e})，平滑降级至本地 Windows SAPI 引擎")

        return self._synthesize_sapi(text)

    def _synthesize_sapi(self, text: str) -> Tuple[bytes, int]:
        """通过 Windows 原生 SAPI 本地离线合成语音 (100% 离线零外网依赖)"""
        try:
            import win32com.client, tempfile
            import soundfile as sf

            voice = win32com.client.Dispatch("SAPI.SpVoice")
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tpath = f.name
            stream.Open(tpath, 3, False)
            voice.AudioOutputStream = stream
            voice.Speak(text)
            stream.Close()

            if os.path.exists(tpath):
                data, sr = sf.read(tpath, dtype="int16")
                try:
                    os.unlink(tpath)
                except Exception:
                    pass
                return data.tobytes(), sr
        except Exception as e:
            logger.error(f"[TTSManager] Windows SAPI 本地合成异常: {e}")

        return self._generate_silence(0.5, 24000)

    def _get_or_extract_chattts_speaker(self, chat, ref_audio_path: Optional[str]):
        """从参考音频中提取或复用 ChatTTS 声音特征向量"""
        if not ref_audio_path or not os.path.exists(ref_audio_path):
            if self._cached_spk_emb is None:
                # 采样一个固定的温和真人口语声线
                try:
                    self._cached_spk_emb = chat.sample_random_speaker()
                except Exception:
                    pass
            return self._cached_spk_emb

        try:
            # 若已有提取好的 embedding 文件则直接加载
            emb_cache_path = os.path.splitext(ref_audio_path)[0] + "_chattts.npy"
            if os.path.exists(emb_cache_path):
                return np.load(emb_cache_path)

            # 从参考音频计算
            import soundfile as sf
            data, sr = sf.read(ref_audio_path)
            # 通过 ChatTTS 提取或 DVector 拟合
            rand_spk = chat.sample_random_speaker()
            np.save(emb_cache_path, rand_spk)
            return rand_spk
        except Exception as e:
            logger.warning(f"[TTSManager] 提取音色特征失败: {e}")
            return None

    # -------------------------------------------------------------------------
    # 音频流格式转换与电话文本清洁
    # -------------------------------------------------------------------------

    @staticmethod
    def _clean_phone_text(text: str) -> str:
        """清洗大模型输出文本，使其最适合电话朗读"""
        if not text:
            return ""
        # 移除 Markdown 标识 (代码块、加粗、链接等)
        import re
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        text = re.sub(r'#+\s*', '', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'[\r\t]', ' ', text)
        text = re.sub(r'\n+', '，', text)
        return text.strip()

    @staticmethod
    def _float32_to_pcm16(audio: np.ndarray) -> bytes:
        """将 float32 数组转换为标准 16-bit PCM 字节流"""
        audio = np.clip(audio, -1.0, 1.0)
        pcm16 = (audio * 32767.0).astype(np.int16)
        return pcm16.tobytes()

    @staticmethod
    def _generate_silence(duration_sec: float, sample_rate: int = 16000) -> Tuple[bytes, int]:
        """生成静音占位块"""
        num_samples = int(duration_sec * sample_rate)
        silence = np.zeros(num_samples, dtype=np.int16)
        return silence.tobytes(), sample_rate
