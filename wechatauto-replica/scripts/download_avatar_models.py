# -*- coding: utf-8 -*-
"""数字人多引擎模型高速下载工具 (scripts/download_avatar_models.py)

专为 LivePortrait-Realtime (FasterLivePortrait ONNX) 与 MuseTalk 设计：
1. 采用国内高速镜像源 (hf-mirror.com)，支持断点续传
2. 严格保存在本项目 models/ 目录下，绝不占用系统 C 盘空间
3. 提供命令行参数与 Python 模块 API，支持实时进度回调
"""
from __future__ import annotations

import os
import sys
import time
import logging
from typing import Optional, Callable, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AvatarModelDownloader")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models")
LIVEPORTRAIT_DIR = os.path.join(MODELS_DIR, "liveportrait")
MUSETALK_DIR = os.path.join(MODELS_DIR, "musetalk")

WAV2LIP_DIR = os.path.join(MODELS_DIR, "wav2lip")

HF_MIRROR = "https://hf-mirror.com"

# 1. FasterLivePortrait ONNX 核心权重列表 (~642 MB)
LIVEPORTRAIT_REPO = "warmshao/FasterLivePortrait"
LIVEPORTRAIT_FILES = [
    ("liveportrait_onnx/appearance_feature_extractor.onnx", "appearance_feature_extractor.onnx"),
    ("liveportrait_onnx/motion_extractor.onnx", "motion_extractor.onnx"),
    ("liveportrait_onnx/warping_spade.onnx", "warping_spade.onnx"),
    ("liveportrait_onnx/landmark.onnx", "landmark.onnx"),
    ("liveportrait_onnx/face_2dpose_106_static.onnx", "face_2dpose_106_static.onnx"),
    ("liveportrait_onnx/retinaface_det_static.onnx", "retinaface_det_static.onnx"),
    ("liveportrait_onnx/stitching.onnx", "stitching.onnx"),
    ("liveportrait_onnx/stitching_lip.onnx", "stitching_lip.onnx"),
]

# 2. Wav2Lip 核心权重 (GAN 高清晰度唇形修复, ~415 MB)
WAV2LIP_REPO = "camenduru/Wav2Lip"
WAV2LIP_FILES = [
    ("checkpoints/wav2lip_gan.pth", "wav2lip_gan.pth"),
]

# 3. MuseTalk 核心权重列表 (~3.2 GB)
MUSETALK_REPO = "TMElyralab/MuseTalk"
MUSETALK_FILES = [
    ("musetalk/musetalk.json", "musetalk.json"),
    ("musetalk/pytorch_model.bin", "pytorch_model.bin"),
]


def check_liveportrait_status() -> Tuple[bool, int, int]:
    """检查 LivePortrait 权重就绪情况 (是否全部下载, 已有文件数, 总文件数)"""
    if not os.path.exists(LIVEPORTRAIT_DIR):
        return False, 0, len(LIVEPORTRAIT_FILES)
    found = 0
    for _, local_name in LIVEPORTRAIT_FILES:
        p1 = os.path.join(LIVEPORTRAIT_DIR, local_name)
        p2 = os.path.join(LIVEPORTRAIT_DIR, "liveportrait_onnx", local_name)
        if (os.path.exists(p1) and os.path.getsize(p1) > 1024) or (os.path.exists(p2) and os.path.getsize(p2) > 1024):
            found += 1
    return found == len(LIVEPORTRAIT_FILES), found, len(LIVEPORTRAIT_FILES)


def check_wav2lip_status() -> Tuple[bool, int, int]:
    """检查 Wav2Lip 权重就绪情况"""
    if not os.path.exists(WAV2LIP_DIR):
        return False, 0, 1
    p1 = os.path.join(WAV2LIP_DIR, "wav2lip_gan.pth")
    p2 = os.path.join(WAV2LIP_DIR, "wav2lip.pth")
    found = 1 if (os.path.exists(p1) and os.path.getsize(p1) > 1024 * 1024) or (os.path.exists(p2) and os.path.getsize(p2) > 1024 * 1024) else 0
    return found == 1, found, 1


def check_musetalk_status() -> Tuple[bool, int, int]:
    """检查 MuseTalk 权重就绪情况"""
    if not os.path.exists(MUSETALK_DIR):
        return False, 0, len(MUSETALK_FILES)
    found = 0
    for _, local_name in MUSETALK_FILES:
        p1 = os.path.join(MUSETALK_DIR, local_name)
        p2 = os.path.join(MUSETALK_DIR, "musetalk", local_name)
        if (os.path.exists(p1) and os.path.getsize(p1) > 50) or (os.path.exists(p2) and os.path.getsize(p2) > 50):
            found += 1
    return found == len(MUSETALK_FILES), found, len(MUSETALK_FILES)


def download_liveportrait(progress_cb: Optional[Callable[[str, float], None]] = None) -> bool:
    """高速下载 LivePortrait-Realtime ONNX 模型文件"""
    os.environ["HF_ENDPOINT"] = HF_MIRROR
    os.environ["HF_HOME"] = os.path.join(MODELS_DIR, "huggingface")
    os.makedirs(LIVEPORTRAIT_DIR, exist_ok=True)

    from huggingface_hub import hf_hub_download

    total = len(LIVEPORTRAIT_FILES)
    logger.info(f"[LivePortrait] 开始从高速镜像源下载 LivePortrait-Realtime ONNX 模型权重 (共 {total} 个文件)...")
    if progress_cb:
        progress_cb("正在连接镜像源...", 0.05)

    for idx, (remote_rel, local_name) in enumerate(LIVEPORTRAIT_FILES):
        p1 = os.path.join(LIVEPORTRAIT_DIR, local_name)
        p2 = os.path.join(LIVEPORTRAIT_DIR, "liveportrait_onnx", local_name)
        if (os.path.exists(p1) and os.path.getsize(p1) > 1024) or (os.path.exists(p2) and os.path.getsize(p2) > 1024):
            logger.info(f"[LivePortrait] 权重已就绪跳过: {local_name}")
            prog = (idx + 1) / total
            if progress_cb:
                progress_cb(f"已就绪: {local_name}", prog)
            continue

        prog = idx / total
        logger.info(f"[LivePortrait] 正在下载 ({idx+1}/{total}): {local_name}...")
        if progress_cb:
            progress_cb(f"正在下载: {local_name} ({idx+1}/{total})", prog)

        try:
            downloaded = hf_hub_download(
                repo_id=LIVEPORTRAIT_REPO,
                filename=remote_rel,
                local_dir=LIVEPORTRAIT_DIR,
                endpoint=HF_MIRROR,
            )
            # 若下载到了子目录，在根目录建立符号或直接复制/同名引用
            target_flat = os.path.join(LIVEPORTRAIT_DIR, local_name)
            if not os.path.exists(target_flat) and os.path.exists(downloaded):
                try:
                    import shutil
                    shutil.copy2(downloaded, target_flat)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[LivePortrait] 下载失败: {local_name} - {e}")
            if progress_cb:
                progress_cb(f"下载失败: {local_name}", prog)
            return False

    if progress_cb:
        progress_cb("LivePortrait-Realtime 全部权重下载就绪！", 1.0)
    logger.info("[LivePortrait] ✅ 全部 LivePortrait-Realtime ONNX 模型已成功就绪！")
    return True


def download_musetalk(progress_cb: Optional[Callable[[str, float], None]] = None) -> bool:
    """高速下载 MuseTalk UNet 模型文件 (~3.2 GB)"""
    os.environ["HF_ENDPOINT"] = HF_MIRROR
    os.environ["HF_HOME"] = os.path.join(MODELS_DIR, "huggingface")
    os.makedirs(MUSETALK_DIR, exist_ok=True)

    from huggingface_hub import hf_hub_download

    total = len(MUSETALK_FILES)
    logger.info(f"[MuseTalk] 开始从高速镜像源下载 MuseTalk 模型权重 (共 {total} 个文件)...")
    if progress_cb:
        progress_cb("正在连接镜像源...", 0.05)

    for idx, (remote_rel, local_name) in enumerate(MUSETALK_FILES):
        p1 = os.path.join(MUSETALK_DIR, local_name)
        p2 = os.path.join(MUSETALK_DIR, "musetalk", local_name)
        if (os.path.exists(p1) and os.path.getsize(p1) > 1024) or (os.path.exists(p2) and os.path.getsize(p2) > 1024):
            logger.info(f"[MuseTalk] 权重已就绪跳过: {local_name}")
            prog = (idx + 1) / total
            if progress_cb:
                progress_cb(f"已就绪: {local_name}", prog)
            continue

        prog = idx / total
        logger.info(f"[MuseTalk] 正在下载 ({idx+1}/{total}): {local_name} (~3.2GB)...")
        if progress_cb:
            progress_cb(f"正在下载: {local_name} (请耐心等待)", prog)

        try:
            downloaded = hf_hub_download(
                repo_id=MUSETALK_REPO,
                filename=remote_rel,
                local_dir=MUSETALK_DIR,
                endpoint=HF_MIRROR,
            )
            target_flat = os.path.join(MUSETALK_DIR, local_name)
            if not os.path.exists(target_flat) and os.path.exists(downloaded):
                try:
                    import shutil
                    shutil.copy2(downloaded, target_flat)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[MuseTalk] 下载失败: {local_name} - {e}")
            if progress_cb:
                progress_cb(f"下载失败: {local_name}", prog)
            return False

    if progress_cb:
        progress_cb("MuseTalk 全部权重下载就绪！", 1.0)
    logger.info("[MuseTalk] ✅ 全部 MuseTalk 模型已成功就绪！")
    return True


def download_wav2lip(progress_cb: Optional[Callable[[str, float], None]] = None) -> bool:
    """高速下载 Wav2Lip-GAN 权重 (~415 MB)"""
    os.environ["HF_ENDPOINT"] = HF_MIRROR
    os.environ["HF_HOME"] = os.path.join(MODELS_DIR, "huggingface")
    os.makedirs(WAV2LIP_DIR, exist_ok=True)

    from huggingface_hub import hf_hub_download

    total = len(WAV2LIP_FILES)
    logger.info(f"[Wav2Lip] 开始从高速镜像源下载 Wav2Lip-GAN 权重文件...")
    if progress_cb:
        progress_cb("正在连接镜像源...", 0.05)

    for idx, (remote_rel, local_name) in enumerate(WAV2LIP_FILES):
        p = os.path.join(WAV2LIP_DIR, local_name)
        if os.path.exists(p) and os.path.getsize(p) > 1024 * 1024:
            logger.info(f"[Wav2Lip] 权重已就绪跳过: {local_name}")
            if progress_cb:
                progress_cb(f"已就绪: {local_name}", 1.0)
            continue

        if progress_cb:
            progress_cb(f"正在下载: {local_name} (~415MB)", 0.2)

        try:
            downloaded = hf_hub_download(
                repo_id=WAV2LIP_REPO,
                filename=remote_rel,
                local_dir=WAV2LIP_DIR,
                endpoint=HF_MIRROR,
            )
            target_flat = os.path.join(WAV2LIP_DIR, local_name)
            if not os.path.exists(target_flat) and os.path.exists(downloaded):
                try:
                    import shutil
                    shutil.copy2(downloaded, target_flat)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[Wav2Lip] 下载失败: {local_name} - {e}")
            if progress_cb:
                progress_cb(f"下载失败: {local_name}", 0.0)
            return False

    if progress_cb:
        progress_cb("Wav2Lip 全部权重下载就绪！", 1.0)
    logger.info("[Wav2Lip] ✅ Wav2Lip-GAN 权重已成功就绪！")
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="下载虚拟数字人驱动模型")
    parser.add_argument("--engine", choices=["liveportrait", "wav2lip", "musetalk", "all"], default="all", help="要下载的引擎模型")
    args = parser.parse_args()

    if args.engine in ("liveportrait", "all"):
        download_liveportrait()
    if args.engine in ("wav2lip", "all"):
        download_wav2lip()
    if args.engine in ("musetalk", "all"):
        download_musetalk()
