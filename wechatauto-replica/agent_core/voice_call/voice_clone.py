# -*- coding: utf-8 -*-
"""声音克隆与多段音色档案管理模块 (agent_core.voice_call.voice_clone)

支持用户录制或上传 1~多段语音音频样本，智能合流与特征提取：
1. 多段音频自动重采样、转单声道并以 0.3s 平滑静音拼接
2. 用户自定义命名音色库 (新建、重命名、切换、删除、多段音频管理)
3. 专为 ChatTTS 与 Qwen3-TTS / Edge-TTS 提供个性化声音克隆支持
"""
from __future__ import annotations

import os
import json
import time
import shutil
import hashlib
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("VoiceClone")

VOICE_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "voices"
)


def merge_audio_files(input_paths: List[str], output_path: str, target_sr: int = 24000) -> str:
    """将多个不同格式的音频片段进行标准化合流并在片段间插入 0.3s 静音间隔生成合并声学样本"""
    import soundfile as sf
    import numpy as np

    valid_paths = [p for p in input_paths if p and os.path.exists(p)]
    if not valid_paths:
        raise FileNotFoundError("未提供有效的音频文件路径")

    merged_chunks = []
    silence = np.zeros(int(0.3 * target_sr), dtype=np.float32)

    for idx, p in enumerate(valid_paths):
        try:
            data, sr = sf.read(p, dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)  # 转为单声道
            if sr != target_sr and len(data) > 0:
                duration = len(data) / sr
                target_len = int(duration * target_sr)
                data = np.interp(
                    np.linspace(0, len(data), target_len, endpoint=False),
                    np.arange(len(data)),
                    data
                ).astype(np.float32)

            # 音量软归一化，避免爆音或音量断崖
            max_val = float(np.max(np.abs(data))) if len(data) > 0 else 0.0
            if max_val > 1e-4:
                data = data / max_val * 0.90

            if idx > 0 and len(merged_chunks) > 0:
                merged_chunks.append(silence)
            merged_chunks.append(data)
        except Exception as e:
            logger.warning(f"[VoiceClone] 读取或转换音频片段失败 ({p}): {e}")

    if not merged_chunks:
        raise ValueError("未能从提供的音频路径中解码出有效音频数据")

    combined = np.concatenate(merged_chunks)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    sf.write(output_path, combined, target_sr, subtype="PCM_16")
    logger.info(f"[VoiceClone] 多段音频已成功融合输出: {output_path} (采样率={target_sr}Hz, 总时长={len(combined)/target_sr:.1f}s)")
    return output_path


class VoiceProfile:
    """声音克隆音色档案"""

    def __init__(
        self,
        voice_id: str,
        name: str,
        audio_path: str,
        audio_paths: Optional[List[str]] = None,
        prompt_text: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.voice_id = voice_id
        self.name = name or "未命名音色"
        self.audio_path = audio_path  # 合并后的主参考音频路径
        self.audio_paths = audio_paths or ([audio_path] if audio_path else [])
        self.prompt_text = prompt_text
        self.metadata = metadata or {}
        self.embedding_path = os.path.join(VOICE_STORAGE_DIR, f"{voice_id}_spk.npy")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "voice_id": self.voice_id,
            "name": self.name,
            "audio_path": self.audio_path,
            "audio_paths": self.audio_paths,
            "clip_count": len(self.audio_paths),
            "prompt_text": self.prompt_text,
            "has_embedding": os.path.exists(self.embedding_path),
            "metadata": self.metadata,
        }


class VoiceCloneManager:
    """声音克隆与音色库总控管理器"""

    def __init__(self, storage_dir: str = VOICE_STORAGE_DIR):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.index_file = os.path.join(self.storage_dir, "voices_index.json")
        self._profiles: Dict[str, VoiceProfile] = {}
        self._load_index()

    def _load_index(self):
        """加载声音档案索引"""
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        p = VoiceProfile(
                            voice_id=item["voice_id"],
                            name=item.get("name", "未命名音色"),
                            audio_path=item.get("audio_path", ""),
                            audio_paths=item.get("audio_paths", []),
                            prompt_text=item.get("prompt_text", ""),
                            metadata=item.get("metadata", {})
                        )
                        self._profiles[p.voice_id] = p
            except Exception as e:
                logger.error(f"[VoiceClone] 加载音色索引失败: {e}")

    def _save_index(self):
        """持久化保存音色索引"""
        data = [p.to_dict() for p in self._profiles.values()]
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[VoiceClone] 保存音色索引失败: {e}")

    def list_voices(self) -> List[Dict[str, Any]]:
        """获取所有可用声音档案列表"""
        return [p.to_dict() for p in self._profiles.values()]

    def get_voice(self, voice_id: str) -> Optional[VoiceProfile]:
        """获取指定声音档案"""
        return self._profiles.get(voice_id)

    def create_voice(self, name: str, audio_paths: List[str], prompt_text: str = "") -> VoiceProfile:
        """根据 1 段或多段音频创建新命名克隆音色"""
        valid_paths = [p for p in audio_paths if p and os.path.exists(p)]
        if not valid_paths:
            raise FileNotFoundError("未选择有效的音频文件")

        # 生成唯一 ID
        hasher = hashlib.md5()
        hasher.update(f"{name}_{time.time()}".encode("utf-8"))
        voice_id = f"voice_{hasher.hexdigest()[:10]}"

        # 内部合并音频输出路径
        merged_filename = f"{voice_id}_merged.wav"
        dest_merged_path = os.path.join(self.storage_dir, merged_filename)

        # 永久归档所有原始片段
        saved_clip_paths = []
        for idx, src_p in enumerate(valid_paths):
            ext = os.path.splitext(src_p)[1].lower() or ".wav"
            clip_name = f"{voice_id}_clip_{idx+1}{ext}"
            clip_dest = os.path.join(self.storage_dir, clip_name)
            try:
                if os.path.abspath(src_p) != os.path.abspath(clip_dest):
                    shutil.copy2(src_p, clip_dest)
                saved_clip_paths.append(clip_dest)
            except Exception as e:
                logger.warning(f"[VoiceClone] 归档音频段失败 ({src_p}): {e}")
                saved_clip_paths.append(src_p)

        # 执行高质量音频融合
        merge_audio_files(saved_clip_paths, dest_merged_path)

        profile = VoiceProfile(
            voice_id=voice_id,
            name=name.strip() or "未命名音色",
            audio_path=dest_merged_path,
            audio_paths=saved_clip_paths,
            prompt_text=prompt_text,
            metadata={"created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "source": "multi_clip"}
        )
        self._profiles[voice_id] = profile
        self._save_index()
        logger.info(f"[VoiceClone] 成功创建克隆音色: [{profile.name}] (ID={voice_id}, 片段数={len(saved_clip_paths)})")
        return profile

    def update_voice(
        self,
        voice_id: str,
        name: Optional[str] = None,
        audio_paths: Optional[List[str]] = None,
        prompt_text: Optional[str] = None
    ) -> Optional[VoiceProfile]:
        """更新音色名称或重新合并音频片段"""
        profile = self._profiles.get(voice_id)
        if not profile:
            return None

        if name is not None and name.strip():
            profile.name = name.strip()

        if prompt_text is not None:
            profile.prompt_text = prompt_text

        if audio_paths is not None:
            valid_paths = [p for p in audio_paths if p and os.path.exists(p)]
            if valid_paths:
                profile.audio_paths = valid_paths
                merge_audio_files(valid_paths, profile.audio_path)

        self._save_index()
        return profile

    def import_voice_sample(self, src_audio_path: str, name: str, prompt_text: str = "") -> VoiceProfile:
        """单音频导入（向下兼容）"""
        return self.create_voice(name=name, audio_paths=[src_audio_path], prompt_text=prompt_text)

    def delete_voice(self, voice_id: str) -> bool:
        """删除指定声音档案及其磁盘文件"""
        if voice_id in self._profiles:
            profile = self._profiles.pop(voice_id)
            if profile.audio_path and os.path.exists(profile.audio_path):
                try:
                    os.remove(profile.audio_path)
                except Exception:
                    pass
            for clip_p in profile.audio_paths:
                if clip_p and os.path.exists(clip_p) and self.storage_dir in os.path.abspath(clip_p):
                    try:
                        os.remove(clip_p)
                    except Exception:
                        pass
            if os.path.exists(profile.embedding_path):
                try:
                    os.remove(profile.embedding_path)
                except Exception:
                    pass
            self._save_index()
            logger.info(f"[VoiceClone] 已删除音色档案: {profile.name} ({voice_id})")
            return True
        return False
