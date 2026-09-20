# -*- coding: utf-8 -*-
"""一键自动下载语音引擎与模型脚本 (scripts/download_tts_models.py)

自动从国内高速镜像 (https://hf-mirror.com / ModelScope) 下载：
1. Kokoro-82M (超轻量 82M ONNX 极速发音) 到 models/Kokoro-82M/
2. Alibaba FunASR Paraformer (毫秒级非自回归中文口语 ASR) 到 models/Paraformer/
3. 2noise/ChatTTS 模型到 models/ChatTTS/
4. Qwen/Qwen3-TTS 模型到 models/Qwen3-TTS/
"""
import os
import sys
import time

# 统一控制台输出 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 设置国内镜像与环境变量
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models")
KOKORO_DIR = os.path.join(MODELS_DIR, "Kokoro-82M")
PARAFORMER_DIR = os.path.join(MODELS_DIR, "Paraformer")
CHATTTS_DIR = os.path.join(MODELS_DIR, "ChatTTS")
QWEN3_TTS_DIR = os.path.join(MODELS_DIR, "Qwen3-TTS")

os.makedirs(KOKORO_DIR, exist_ok=True)
os.makedirs(PARAFORMER_DIR, exist_ok=True)
os.makedirs(CHATTTS_DIR, exist_ok=True)
os.makedirs(QWEN3_TTS_DIR, exist_ok=True)

print("=" * 65)
print("       WeChat-AIAgent Voice & TTS Model Downloader")
print("=" * 65)
print(f"[*] HuggingFace Mirror: https://hf-mirror.com")
print(f"[*] Kokoro-82M Target:  {KOKORO_DIR}")
print(f"[*] Paraformer Target:  {PARAFORMER_DIR}")
print(f"[*] ChatTTS Target:     {CHATTTS_DIR}")
print(f"[*] Qwen3-TTS Target:   {QWEN3_TTS_DIR}")
print("-" * 65)

# 1. 下载 Kokoro-82M (超轻量 82M，仅需两个文件)
print("\n[1/4] 正在下载 Kokoro-82M 轻量极速发音引擎 (约85MB)...")
try:
    import urllib.request
    onnx_file = os.path.join(KOKORO_DIR, "kokoro-v0_19.onnx")
    voices_file = os.path.join(KOKORO_DIR, "voices.bin")
    
    urls = [
        ("https://hf-mirror.com/hexgrad/Kokoro-82M/resolve/main/kokoro-v0_19.onnx", onnx_file),
        ("https://hf-mirror.com/hexgrad/Kokoro-82M/resolve/main/voices.bin", voices_file),
    ]
    for url, target in urls:
        if not os.path.exists(target) or os.path.getsize(target) < 1024:
            print(f"    -> 正在下载 {os.path.basename(target)}...")
            urllib.request.urlretrieve(url, target)
    print("✅ Kokoro-82M 核心模型与音色库已就绪！")
except Exception as e:
    print(f"⚠️ Kokoro-82M 下载异常: {e}")

# 2. 下载 / 缓存 FunASR Paraformer 中文口语流式 ASR 模型
print("\n[2/4] 正在缓存 FunASR Paraformer 中文流式语音识别模型...")
try:
    from funasr import AutoModel
    AutoModel(
        model="damo/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        disable_update=True,
        disable_pbar=True,
        trust_remote_code=False,
    )
    print("✅ FunASR Paraformer 语音识别模型已就绪！")
except Exception as e:
    print(f"⚠️ FunASR Paraformer 预下载异常 (通话时会自动通过 ModelScope 拉取): {e}")

# 3. 下载 ChatTTS
print("\n[3/4] 正在下载 ChatTTS 模型权重 (2noise/ChatTTS)...")
try:
    from huggingface_hub import snapshot_download
    start_t = time.time()
    snapshot_download(
        repo_id="2noise/ChatTTS",
        local_dir=CHATTTS_DIR,
        local_dir_use_symlinks=False,
        endpoint="https://hf-mirror.com",
        resume_download=True,
    )
    print(f"✅ ChatTTS 下载完成！耗时: {time.time() - start_t:.1f} 秒")
except Exception as e:
    print(f"❌ ChatTTS 下载失败: {e}")

# 4. 下载 Qwen3-TTS
print("\n[4/4] 正在下载 Qwen3-TTS 语音克隆模型权重...")
try:
    from huggingface_hub import snapshot_download
    start_t = time.time()
    snapshot_download(
        repo_id="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        local_dir=QWEN3_TTS_DIR,
        local_dir_use_symlinks=False,
        endpoint="https://hf-mirror.com",
        resume_download=True,
    )
    print(f"✅ Qwen3-TTS 下载完成！耗时: {time.time() - start_t:.1f} 秒")
except Exception as e:
    print(f"⚠️ Qwen3-TTS 0.6B 下载异常，尝试 1.7B: {e}")
    try:
        snapshot_download(
            repo_id="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            local_dir=QWEN3_TTS_DIR,
            local_dir_use_symlinks=False,
            endpoint="https://hf-mirror.com",
            resume_download=True,
        )
        print("✅ Qwen3-TTS 1.7B 下载完成！")
    except Exception as ex:
        print(f"❌ Qwen3-TTS 下载失败: {ex}")

print("\n" + "=" * 65)
print("所有语音与 TTS 模型下载检查完成！")
print("=" * 65)
