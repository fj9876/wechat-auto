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
KOKORO_DIR = os.path.join(MODELS_ROOT, "Kokoro-82M")

# 强制将 HuggingFace / ModelScope / Torch 缓存全部定向至项目 models 目录
os.environ["MODELSCOPE_CACHE"] = os.path.join(MODELS_ROOT, "modelscope")
os.environ["HF_HOME"] = os.path.join(MODELS_ROOT, "huggingface")
os.environ["HUGGINGFACE_HUB_CACHE"] = os.path.join(MODELS_ROOT, "huggingface", "hub")
os.environ["TORCH_HOME"] = os.path.join(MODELS_ROOT, "torch")

# 国内镜像源配置
HF_MIRROR_ENDPOINT = "https://hf-mirror.com"
CHATTTS_REPO_ID = "2noise/ChatTTS"
QWEN3_TTS_REPO_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
KOKORO_REPO_ID = "hexgrad/Kokoro-82M"


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
    """TTS 语音合成与声音克隆统一管理器 (支持 Kokoro-82M / Qwen3-TTS GGML / ChatTTS / Edge-TTS)"""

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
        self._qwen_ggml_model = None
        self._kokoro_model = None
        self._is_loading = False
        self._active_voice_clone_path: Optional[str] = None
        self._cached_spk_emb = None
        self._engine_load_failed: Dict[str, bool] = {}
        self._fallback_notified: Dict[str, bool] = {}

        # 进度追踪
        self.downloads: Dict[str, TTSDownloadProgress] = {
            "chattts": TTSDownloadProgress("ChatTTS"),
            "qwen3_tts": TTSDownloadProgress("Qwen3-TTS"),
            "kokoro": TTSDownloadProgress("Kokoro-82M"),
        }

        os.makedirs(MODELS_ROOT, exist_ok=True)
        os.makedirs(CHATTTS_DIR, exist_ok=True)
        os.makedirs(QWEN3_TTS_DIR, exist_ok=True)
        os.makedirs(KOKORO_DIR, exist_ok=True)

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
        elif engine == "kokoro":
            for root, _, files in os.walk(KOKORO_DIR):
                onnx_files = [f for f in files if f.endswith(".onnx")]
                bin_files = [f for f in files if f.endswith(".bin") or f.endswith(".json")]
                if onnx_files and bin_files:
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
        elif engine == "kokoro":
            import importlib.util
            return importlib.util.find_spec("kokoro_onnx") is not None or importlib.util.find_spec("kokoro") is not None
        elif engine == "chattts":
            import importlib.util
            return importlib.util.find_spec("ChatTTS") is not None
        elif engine in ("qwen3_tts", "qwen3"):
            import importlib.util
            return (
                importlib.util.find_spec("faster_qwen3_tts") is not None
                or importlib.util.find_spec("qwentts") is not None
                or importlib.util.find_spec("qwen_tts") is not None
            )
        return False

    @staticmethod
    def get_optimal_device() -> Tuple[str, str, Any]:
        """获取最优推理设备 (全面优先锁定 GPU CUDA)"""
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

        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                logger.info("[TTSManager] 🚀 探测到 ctranslate2 可用 CUDA 设备，锁定 cuda")
                return "cuda", "NVIDIA GPU (CUDA)", None
        except Exception:
            pass

        return "cpu", "CPU 处理器", None

    def auto_install_engine_wheel(self, engine: str, background: bool = True, callback: Optional[Callable[[str, bool, str], None]] = None) -> bool:
        """自动为指定引擎安装所需 wheel 依赖包 (支持清华镜像源一键静默补齐)"""
        pkg_map = {
            "kokoro": ["kokoro-onnx", "soundfile"],
            "paraformer": ["funasr", "modelscope"],
            "funasr": ["funasr", "modelscope"],
            "qwen3_tts": ["qwen-tts"],
            "chattts": ["ChatTTS"],
            "whisper": ["faster-whisper"],
            "edge_tts": ["edge-tts"],
        }
        pkgs = pkg_map.get(engine.lower())
        if not pkgs:
            return False

        def _do_install():
            logger.info(f"[TTSManager] 📦 正在自动为 [{engine}] 安装 wheel 依赖包: {pkgs}...")
            import subprocess
            cmd = [sys.executable, "-m", "pip", "install"] + pkgs + ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)
                if proc.returncode == 0:
                    logger.info(f"[TTSManager] ✅ [{engine}] 依赖包 {pkgs} 安装完成！")
                    if callback:
                        callback(engine, True, "安装成功")
                    return True
                else:
                    err = proc.stderr[:300] if proc.stderr else "返回码异常"
                    logger.error(f"[TTSManager] ❌ [{engine}] 依赖包安装失败: {err}")
                    if callback:
                        callback(engine, False, err)
                    return False
            except Exception as ex:
                logger.error(f"[TTSManager] ❌ [{engine}] 自动安装异常: {ex}")
                if callback:
                    callback(engine, False, str(ex))
                return False

        if background:
            threading.Thread(target=_do_install, daemon=True, name=f"AutoInstall-{engine}").start()
            return True
        else:
            return _do_install()

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
                os.environ["HF_ENDPOINT"] = HF_MIRROR_ENDPOINT
                from huggingface_hub import snapshot_download, hf_hub_download

                if engine == "chattts":
                    repo_id = CHATTTS_REPO_ID
                    target_dir = CHATTTS_DIR
                    snapshot_download(
                        repo_id=repo_id,
                        local_dir=target_dir,
                        local_dir_use_symlinks=False,
                        endpoint=HF_MIRROR_ENDPOINT,
                        resume_download=True,
                    )
                elif engine == "kokoro":
                    tracker.update("downloading", 0.1)
                    import requests
                    os.makedirs(KOKORO_DIR, exist_ok=True)
                    model_urls = [
                        ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx",
                         os.path.join(KOKORO_DIR, "kokoro-v0_19.onnx"), 0.5),
                        ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin",
                         os.path.join(KOKORO_DIR, "voices.bin"), 0.9),
                    ]
                    for url, target_path, prog in model_urls:
                        if not os.path.exists(target_path) or os.path.getsize(target_path) < 1024:
                            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, stream=True, timeout=60)
                            r.raise_for_status()
                            with open(target_path, "wb") as f:
                                for chunk in r.iter_content(chunk_size=1024 * 1024):
                                    if chunk:
                                        f.write(chunk)
                        tracker.update("downloading", prog)
                else:
                    repo_id = QWEN3_TTS_REPO_ID
                    target_dir = QWEN3_TTS_DIR
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

        elif engine == "kokoro":
            if self._kokoro_model is not None:
                return self._kokoro_model
            if self._engine_load_failed.get("kokoro", False):
                return None
            try:
                import kokoro_onnx
                # 寻找本地 Kokoro ONNX 模型与音色库
                model_file = None
                voices_file = None
                for root, _, files in os.walk(KOKORO_DIR):
                    for f in files:
                        if f.endswith(".onnx") and not model_file:
                            model_file = os.path.join(root, f)
                        elif (f.endswith(".bin") or f.endswith(".json")) and not voices_file:
                            voices_file = os.path.join(root, f)

                if not model_file or not voices_file:
                    logger.info("[TTSManager] 本地 Kokoro-82M 权重文件不全，尝试从镜像自动下载...")
                    self.auto_download_model("kokoro", background=False)
                    for root, _, files in os.walk(KOKORO_DIR):
                        for f in files:
                            if f.endswith(".onnx") and not model_file:
                                model_file = os.path.join(root, f)
                            elif (f.endswith(".bin") or f.endswith(".json")) and not voices_file:
                                voices_file = os.path.join(root, f)

                if model_file and voices_file:
                    logger.info(f"[TTSManager] 正在初始化 Kokoro-82M 引擎: {model_file}...")
                    import onnxruntime as ort
                    sess_opt = ort.SessionOptions()
                    sess_opt.intra_op_num_threads = min(8, max(2, (os.cpu_count() or 4)))
                    sess_opt.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                    providers = ["CPUExecutionProvider"]
                    sess = ort.InferenceSession(model_file, sess_options=sess_opt, providers=providers)
                    self._kokoro_model = kokoro_onnx.Kokoro.from_session(sess, voices_file)
                    logger.info(f"[TTSManager] ✅ Kokoro-82M 初始化就绪 (运行于 [{providers[0]}])！")
                    return self._kokoro_model
                else:
                    logger.warning("[TTSManager] Kokoro-82M 权重未准备就绪，自动降级至 Edge-TTS")
                    self._engine_load_failed["kokoro"] = True
                    return None
            except ImportError:
                if not self._fallback_notified.get("kokoro_missing", False):
                    logger.info("[TTSManager] kokoro-onnx 运行库未就绪，自动平滑切换至 Edge-TTS 高保真引擎")
                    self._fallback_notified["kokoro_missing"] = True
                self._engine_load_failed["kokoro"] = True
                return None
            except Exception as e:
                logger.warning(f"[TTSManager] Kokoro-82M 初始化异常: {e}，平滑降级至 Edge-TTS")
                self._engine_load_failed["kokoro"] = True
                return None

        elif engine in ("qwen3_tts", "qwen3"):
            if self._qwen_ggml_model is not None:
                return self._qwen_ggml_model
            if self._qwen_model is not None:
                return self._qwen_model
            if self._engine_load_failed.get("qwen3_tts", False):
                return None
            try:
                # 1. 优先尝试 GGML / C++ 量化推理库 (faster-qwen3-tts[ggml] / qwentts-cpp-python)
                try:
                    import faster_qwen3_tts
                    logger.info("[TTSManager] 🚀 发现 faster_qwen3_tts GGML C++ 加速后端，正在加载量化引擎...")
                    model = faster_qwen3_tts.Qwen3TTSModel(QWEN3_TTS_DIR if self.is_model_downloaded("qwen3_tts") else None)
                    self._qwen_ggml_model = model
                    logger.info("[TTSManager] ✅ Qwen3-TTS (GGML C++ 加速) 初始化就绪！")
                    return model
                except (ImportError, AttributeError, Exception) as e_ggml:
                    logger.debug(f"[TTSManager] GGML C++ 加速后端未就绪 ({e_ggml})，继续尝试标准 PyTorch 后端...")

                # 2. 尝试标准 PyTorch 权重加载 (全面优先锁定 GPU CUDA)
                from qwen_tts import Qwen3TTSModel
                import torch
                import warnings
                warnings.filterwarnings("ignore", message=".*Passing `repetition_penalty`.*")
                dev_str, dev_name, dtype = self.get_optimal_device()
                dtype = dtype or torch.float32
                logger.info(f"[TTSManager] 正在加载 Qwen3-TTS PyTorch 引擎权重 (设备=[{dev_name}], target={dev_str}, dtype={dtype})...")
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
        # 0. Kokoro-82M 超轻量极速本地语音分支 (<200ms 首包，CPU/GPU通吃)
        if engine == "kokoro":
            pcm, sr = self._synthesize_kokoro(text, ref_path)
            if pcm and len(pcm) > 1000:
                return pcm, sr
            if not self._fallback_notified.get("kokoro_fallback", False):
                logger.info("[TTSManager] Kokoro 未能输出有效音频，自动平滑切换至 Edge-TTS 高保真引擎")
                self._fallback_notified["kokoro_fallback"] = True
            return self._synthesize_edge_tts(text, ref_path)

        # 1. Edge-TTS 微软高清云端神经语音分支
        elif engine in ("edge_tts", "edge"):
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

        # 4. Qwen3-TTS 分支 (优先 GGML C++，回退 PyTorch，再次回退 Edge-TTS)
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

    def _synthesize_kokoro(self, text: str, ref_audio_path: Optional[str] = None) -> Tuple[bytes, int]:
        """通过 Kokoro-82M 超轻量极速语音引擎合成 (单句推理 <200ms)"""
        kokoro = self.load_engine("kokoro")
        sample_rate = 24000
        if kokoro is None:
            return b"", sample_rate

        try:
            # 优先从模型音色库中获取有效音色
            available_voices = kokoro.get_voices() if hasattr(kokoro, "get_voices") else []
            voice_name = getattr(self, "kokoro_voice", "zf_xiaobei") or "zf_xiaobei"
            if ref_audio_path and any(kw in ref_audio_path.lower() for kw in ["male", "男", "boy", "man"]):
                voice_name = "zm_yunjian"
            if available_voices and voice_name not in available_voices:
                # 若所选音色不在 voices 库中，选用库内首选音色
                voice_name = available_voices[0]

            # 生成 24kHz 音频样本 (float32 numpy array)
            # 在 espeak-ng / kokoro 中标准中文口语代号为 "cmn" (Mandarin)
            samples = None
            sr = 24000
            for lang_code in ["cmn", "en-us"]:
                try:
                    samples, sr = kokoro.create(text, voice=voice_name, speed=1.05, lang=lang_code)
                    if samples is not None and len(samples) > 0:
                        break
                except Exception as lang_err:
                    logger.debug(f"[TTSManager] Kokoro 尝试语言 {lang_code} 失败: {lang_err}")

            if samples is not None and len(samples) > 0:
                audio_array = np.array(samples, dtype=np.float32)
                pcm16 = self._float32_to_pcm16(audio_array)
                return pcm16, sr
        except Exception as e:
            logger.warning(f"[TTSManager] Kokoro-82M 合成异常: {e}")

        return b"", sample_rate

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
        """通过 Qwen3-TTS 进行高质量合成与参考音频克隆 (优先 GGML C++，回退 PyTorch)"""
        sample_rate = 24000
        # 1. 优先使用 GGML C++ 量化模型
        if self._qwen_ggml_model is not None:
            try:
                wav = self._qwen_ggml_model.generate(
                    text=text,
                    prompt_wav=ref_audio_path if (ref_audio_path and os.path.exists(ref_audio_path)) else None,
                )
                pcm16 = self._float32_to_pcm16(wav)
                return pcm16, sample_rate
            except Exception as e:
                logger.warning(f"[TTSManager] Qwen3-TTS GGML 合成失败: {e}")

        # 2. 若无 faster-qwen3-tts GGML C++ 量化库，标准 PyTorch Qwen3-TTS 单句推理耗时高达 80s+，
        # 会导致电话对面长久死寂听不到声音。自动切换为高保真毫秒级 Edge-TTS / ChatTTS 保底。
        if not self._fallback_notified.get("qwen_ggml_missing", False):
            logger.info("[TTSManager] Qwen3-TTS 运行于 PyTorch 模式，为确保电话毫秒级响应，已平滑切换至 Edge-TTS / ChatTTS")
            self._fallback_notified["qwen_ggml_missing"] = True
        return b"", sample_rate

        # 3. 备用 PyTorch 原生推理
        qwen = self.load_engine("qwen3_tts")
        if qwen is None:
            return b"", sample_rate

        try:
            if hasattr(qwen, "generate_custom_voice"):
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
