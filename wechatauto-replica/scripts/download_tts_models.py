# -*- coding: utf-8 -*-
"""一键自动下载 TTS 模型脚本 (scripts/download_tts_models.py)

自动从国内高速镜像 (https://hf-mirror.com) 下载：
1. 2noise/ChatTTS 模型到 models/ChatTTS/
2. Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice 模型到 models/Qwen3-TTS/
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
CHATTTS_DIR = os.path.join(MODELS_DIR, "ChatTTS")
QWEN3_TTS_DIR = os.path.join(MODELS_DIR, "Qwen3-TTS")

os.makedirs(CHATTTS_DIR, exist_ok=True)
os.makedirs(QWEN3_TTS_DIR, exist_ok=True)

print("=" * 65)
print("       WeChat-AIAgent TTS Model Downloader")
print("=" * 65)
print(f"[*] Mirror: https://hf-mirror.com")
print(f"[*] ChatTTS Target: {CHATTTS_DIR}")
print(f"[*] Qwen3-TTS Target: {QWEN3_TTS_DIR}")
print("-" * 65)

from huggingface_hub import snapshot_download

# 1. 下载 ChatTTS
print("\n[1/2] 正在下载 ChatTTS 模型权重 (2noise/ChatTTS)...")
try:
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

# 2. 下载 Qwen3-TTS (0.6B CustomVoice 专为语音克隆设计，轻量低显存)
print("\n[2/2] 正在下载 Qwen3-TTS 语音克隆模型权重 (Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice)...")
try:
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
    print(f"⚠️ Qwen3-TTS 0.6B 下载异常，尝试 1.7B 或备用镜像: {e}")
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
print("所有模型下载检查完成！")
print("=" * 65)
