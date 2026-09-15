# -*- coding: utf-8 -*-
"""微信多模态媒体处理引擎 (agent_core.media_engine)

负责微信语音消息与图片消息的解码、分析与智能理解：
1. 音频解码与转码 (AudioConverter)：
   - 支持将微信 SILK V3 原始音频解码并转码为标准 24kHz 单声道 16-bit WAV 格式 (基于 pilk)
2. 语音识别 (VoiceRecognizer)：
   - 本地模式：接入 faster-whisper 引擎，支持 GPU/CPU 自适应推理与模型按需懒加载
   - 云端模式：兼容标准 OpenAI Whisper API (/v1/audio/transcriptions)，支持硅基流动、DashScope、Groq 等
3. 图片识别 (ImageEngine)：
   - 方案 A (主流)：OpenAI 兼容的多模态视觉大模型 (Vision LLM, 如 Qwen-VL, GPT-4o 等)，直接理解图片内容
   - 方案 B (备用)：Windows 原生 WinRT OCR 硬件加速引擎 (0 额外庞大依赖)，当大模型不支持视觉或调用报错时自动无缝降级提取文字
"""
from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import re
import tempfile
import time
import urllib.request
import urllib.error
import wave
from typing import Dict, Any, List, Optional, Tuple

from PIL import Image

from .config import VoiceConfig, ImageConfig, LLMConfig


class AudioConverter:
    """音频转码工具类：处理微信 SILK 格式转标准 WAV"""

    @staticmethod
    def silk_to_wav(silk_path: str, wav_path: Optional[str] = None, sample_rate: int = 24000) -> str:
        """将微信 SILK V3 音频解码并保存为标准 WAV 文件
        
        Args:
            silk_path: 输入 .silk 文件路径
            wav_path: 输出 .wav 文件路径 (为 None 则在临时文件夹生成)
            sample_rate: 采样率 (微信语音通常为 24000Hz)
            
        Returns:
            生成的 wav 文件绝对路径
        """
        if not os.path.exists(silk_path):
            raise FileNotFoundError(f"SILK 文件不存在: {silk_path}")

        if wav_path is None:
            fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="wx_voice_")
            os.close(fd)

        # 检查微信 SILK 头部格式：部分微信版本头部有 \x02 字节或缺失 #!SILK_V3 标记
        with open(silk_path, "rb") as sf:
            raw_data = sf.read()

        if not raw_data:
            raise ValueError(f"SILK 文件为空: {silk_path}")

        # 规范化 SILK 数据头
        clean_silk_path = silk_path
        tmp_silk_file = None
        if raw_data.startswith(b"\x02#!SILK_V3"):
            tmp_silk_file = silk_path + ".fixed.silk"
            with open(tmp_silk_file, "wb") as f_fix:
                f_fix.write(raw_data[1:])
            clean_silk_path = tmp_silk_file
        elif not raw_data.startswith(b"#!SILK_V3"):
            # 添加标准 SILK_V3 头
            tmp_silk_file = silk_path + ".fixed.silk"
            with open(tmp_silk_file, "wb") as f_fix:
                f_fix.write(b"#!SILK_V3" + raw_data)
            clean_silk_path = tmp_silk_file

        # 生成中间 PCM 文件
        fd_pcm, pcm_path = tempfile.mkstemp(suffix=".pcm", prefix="wx_pcm_")
        os.close(fd_pcm)

        try:
            import pilk
            pilk.decode(clean_silk_path, pcm_path)

            # 将 PCM 原始字节封装为标准 WAV
            with open(pcm_path, "rb") as pf:
                pcm_data = pf.read()

            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)       # 单声道
                wf.setsampwidth(2)       # 16-bit
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_data)

            return wav_path
        except Exception as e:
            raise RuntimeError(f"SILK 转 WAV 失败: {e}")
        finally:
            if os.path.exists(pcm_path):
                try:
                    os.remove(pcm_path)
                except OSError:
                    pass
            if tmp_silk_file and os.path.exists(tmp_silk_file):
                try:
                    os.remove(tmp_silk_file)
                except OSError:
                    pass


class VoiceRecognizer:
    """语音识别器：支持本地 faster-whisper 与在线云端 Whisper 接口"""

    def __init__(self, config: VoiceConfig):
        self.config = config
        self._local_model = None
        self._loaded_model_spec: Optional[str] = None

    def update_config(self, config: VoiceConfig) -> None:
        """更新语音识别配置"""
        if (self.config.whisper_model != config.whisper_model or
            self.config.whisper_device != config.whisper_device):
            # 模型规格或硬件发生变化时重置本地模型缓存
            self._local_model = None
            self._loaded_model_spec = None
        self.config = config

    def _get_local_model(self):
        """懒加载本地 faster-whisper 模型 (支持优先从项目 models/ 目录秒速离线加载)"""
        if "HF_ENDPOINT" not in os.environ:
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

        model_name = (self.config.whisper_model or "base").strip()
        device_req = (self.config.whisper_device or "auto").strip().lower()

        spec_key = f"{model_name}_{device_req}"
        if self._local_model is not None and self._loaded_model_spec == spec_key:
            return self._local_model

        # 检查项目内的 models/ 目录
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        models_dir = os.path.join(project_root, "models")
        os.makedirs(models_dir, exist_ok=True)

        # 优先检索本地项目已经下载的模型文件夹
        candidate_paths = [
            os.path.join(models_dir, f"whisper-{model_name}"),
            os.path.join(models_dir, model_name),
            os.path.join(models_dir, f"faster-whisper-{model_name}"),
        ]
        
        actual_model_path_or_name = model_name
        for p in candidate_paths:
            if os.path.isdir(p) and (os.path.exists(os.path.join(p, "model.bin")) or os.path.exists(os.path.join(p, "config.json"))):
                actual_model_path_or_name = p
                break

        from faster_whisper import WhisperModel

        device = "cpu"
        compute_type = "int8"
        if device_req in ("cuda", "gpu"):
            device = "cuda"
            compute_type = "float16"
        elif device_req == "auto":
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                    compute_type = "float16"
            except Exception:
                device = "cpu"
                compute_type = "int8"

        try:
            model = WhisperModel(
                actual_model_path_or_name,
                device=device,
                compute_type=compute_type,
                download_root=models_dir
            )
        except Exception as e:
            # 如果 CUDA 初始化失败 (如显存不足或未装 cuDNN)，自动回退到 CPU
            if device == "cuda":
                model = WhisperModel(
                    actual_model_path_or_name,
                    device="cpu",
                    compute_type="int8",
                    download_root=models_dir
                )
            else:
                raise e

        self._local_model = model
        self._loaded_model_spec = spec_key
        return self._local_model

    def transcribe_local(self, wav_path: str, language: str = "zh") -> Tuple[bool, str]:
        """使用本地 faster-whisper 模型执行识别"""
        try:
            model = self._get_local_model()
            segments, info = model.transcribe(wav_path, language=language, beam_size=5)
            text = "".join([segment.text for segment in segments]).strip()
            return True, text
        except Exception as e:
            return False, f"本地语音识别异常: {e}"

    def transcribe_cloud(self, wav_path: str, language: str = "zh") -> Tuple[bool, str]:
        """使用在线云端 Whisper 接口执行识别 (POST /v1/audio/transcriptions)"""
        url = (self.config.cloud_api_url or "").strip().rstrip("/")
        if not url:
            url = "https://api.openai.com/v1"
        endpoint = f"{url}/audio/transcriptions"
        api_key = (self.config.cloud_api_key or "").strip()
        model_name = (self.config.cloud_model_name or "whisper-1").strip()

        with open(wav_path, "rb") as f:
            wav_bytes = f.read()

        filename = os.path.basename(wav_path)
        boundary = f"----WebKitFormBoundary{int(time.time() * 1000)}"

        # 构造 multipart/form-data
        body = bytearray()
        
        # model 参数
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="model"\r\n\r\n{model_name}\r\n'.encode("utf-8"))

        # language 参数
        if language:
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="language"\r\n\r\n{language}\r\n'.encode("utf-8"))

        # file 数据
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"))
        body.extend(b"Content-Type: audio/wav\r\n\r\n")
        body.extend(wav_bytes)
        body.extend(b"\r\n")

        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {api_key}" if api_key else "",
        }

        try:
            req = urllib.request.Request(endpoint, data=bytes(body), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data.get("text", "").strip()
                return True, text
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            return False, f"云端 ASR HTTP 错误 [{e.code}]: {err_msg[:200]}"
        except Exception as e:
            return False, f"云端 ASR 请求失败: {e}"

    def transcribe(self, audio_path: str, language: str = "zh") -> Tuple[bool, str, str]:
        """统一音频转写入口 (支持 .silk, .wav, .mp3 等)
        
        Returns:
            (success: bool, text_or_error: str, engine_used: str)
        """
        if not self.config.enabled:
            return False, "语音识别功能已在配置中关闭", "disabled"

        wav_to_clean = None
        wav_path = audio_path

        try:
            if audio_path.lower().endswith(".silk"):
                wav_path = AudioConverter.silk_to_wav(audio_path)
                wav_to_clean = wav_path

            engine = (self.config.engine or "local").strip().lower()
            if engine == "cloud":
                ok, text = self.transcribe_cloud(wav_path, language=language)
                return ok, text, "cloud"
            else:
                ok, text = self.transcribe_local(wav_path, language=language)
                return ok, text, "faster-whisper"
        finally:
            if wav_to_clean and os.path.exists(wav_to_clean):
                try:
                    os.remove(wav_to_clean)
                except OSError:
                    pass


class ImageEngine:
    """图片智能处理引擎：主流 Vision 大模型 + 备用 WinRT OCR 降级体系"""

    def __init__(self, image_config: ImageConfig, llm_config: LLMConfig):
        self.image_config = image_config
        self.llm_config = llm_config

    def update_config(self, image_config: ImageConfig, llm_config: LLMConfig) -> None:
        self.image_config = image_config
        self.llm_config = llm_config

    def recognize_with_ocr(self, image_path: str) -> Tuple[bool, str, str]:
        """使用 Windows 原生 WinRT OCR 引擎提取图片内的全部文字 (纯离线、硬件加速)
        
        Returns:
            (success: bool, text_content: str, method: str)
        """
        if not os.path.exists(image_path):
            return False, f"图片文件不存在: {image_path}", "winrt_ocr"

        try:
            img = Image.open(image_path)
        except Exception as e:
            return False, f"读取图片文件失败: {e}", "winrt_ocr"

        # 尝试使用 winocr 库或系统 WinRT 原生 API
        try:
            import winocr
            res = winocr.recognize_pil_sync(img, lang="zh-Hans-CN")
            if res and isinstance(res, dict) and "text" in res:
                return True, res["text"].strip(), "winrt_ocr"
            elif res and hasattr(res, "text"):
                return True, str(res.text).strip(), "winrt_ocr"
        except Exception:
            pass

        # 回退使用 Windows SDK 原生 WinRT
        try:
            from winsdk.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
            from winsdk.windows.media.ocr import OcrEngine
            from winsdk.windows.storage.streams import DataWriter

            img_rgba = img.convert("RGBA")
            w, h = img_rgba.size
            raw_bytes = img_rgba.tobytes()

            writer = DataWriter()
            writer.write_bytes(raw_bytes)
            buf = writer.detach_buffer()

            bmp = SoftwareBitmap.create_copy_from_buffer(
                buf, BitmapPixelFormat.RGBA8, w, h, BitmapAlphaMode.PREMULTIPLIED
            )

            eng = OcrEngine.try_create_from_user_profile_languages()
            if eng is None:
                return False, "未能初始化系统 WinRT OCR 引擎 (语言包未就绪)", "winrt_ocr"

            async def _run():
                result = await eng.recognize_async(bmp)
                lines = [line.text.strip() for line in result.lines if line.text.strip()]
                return "\n".join(lines)

            ocr_text = asyncio.run(asyncio.wait_for(_run(), timeout=8))
            return True, ocr_text.strip(), "winrt_ocr"
        except Exception as e:
            return False, f"WinRT OCR 提取异常: {e}", "winrt_ocr"

    def recognize_with_vision(
        self,
        image_path: str,
        user_prompt: str = "",
        max_tokens: int = 1500
    ) -> Tuple[bool, str, str]:
        """使用主流多模态视觉大模型 (Vision LLM) 理解图片 (方案 A)
        
        Returns:
            (success: bool, answer_or_error: str, method: str)
        """
        if not os.path.exists(image_path):
            return False, f"图片文件不存在: {image_path}", "vision"

        # 确定调用的视觉模型、URL与 Key
        api_url = (self.image_config.vision_api_url or self.llm_config.api_url or "").strip().rstrip("/")
        if not api_url:
            api_url = "https://api.deepseek.com/v1"
        endpoint = f"{api_url}/chat/completions"

        api_key = (self.image_config.vision_api_key or self.llm_config.api_key or "").strip()
        model_name = (self.image_config.vision_model_name or self.llm_config.model_name or "").strip()

        # 读取图片转为 Base64 Data URI
        try:
            mime, _ = mimetypes.guess_type(image_path)
            if not mime or not mime.startswith("image/"):
                mime = "image/jpeg"

            with open(image_path, "rb") as img_f:
                b64_str = base64.b64encode(img_f.read()).decode("utf-8")
            image_data_uri = f"data:{mime};base64,{b64_str}"
        except Exception as e:
            return False, f"图片编码 Base64 失败: {e}", "vision"

        # 构造 OpenAI 标准多模态 Message
        text_content = user_prompt.strip() if user_prompt.strip() else "请仔细分析这张图片的内容。若包含文字或信息，请予以总结并解答用户的疑问："
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_content},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_data_uri,
                            "detail": "auto"
                        }
                    }
                ]
            }
        ]

        payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": self.llm_config.temperature,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}" if api_key else "",
        }

        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=40) as resp:
                res_body = json.loads(resp.read().decode("utf-8"))
                choice = res_body.get("choices", [{}])[0]
                reply = choice.get("message", {}).get("content", "").strip()
                return True, reply, "vision"
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            return False, f"Vision API HTTP [{e.code}]: {err_msg[:250]}", "vision"
        except Exception as e:
            return False, f"Vision API 请求失败: {e}", "vision"

    def process_image(
        self,
        image_path: str,
        user_prompt: str = ""
    ) -> Dict[str, Any]:
        """全流程图片处理调度器：主流 Vision + 备用 OCR 降级体系
        
        Returns:
            {
                "success": bool,
                "strategy": str,         # "vision" / "ocr_fallback" / "ocr_only"
                "direct_reply": str,     # 若 Vision 成功则直接有回复
                "ocr_text": str,         # 若走 OCR 则存放提取出的文字
                "prompt_for_llm": str,   # 备用 OCR 时整理给纯文本 LLM 的提示词
                "error": Optional[str]
            }
        """
        if not self.image_config.enabled:
            return {
                "success": False,
                "strategy": "disabled",
                "direct_reply": "",
                "ocr_text": "",
                "prompt_for_llm": "",
                "error": "图片识别功能已在配置中关闭"
            }

        strategy = (self.image_config.strategy or "auto").strip().lower()

        # 1. 显式指定仅使用 OCR
        if strategy == "ocr_only":
            ok, ocr_text, _ = self.recognize_with_ocr(image_path)
            if ok and ocr_text:
                combined_prompt = f"【用户发送了图片，OCR文字提取如下】：\n{ocr_text}"
                if user_prompt.strip():
                    combined_prompt += f"\n\n【用户问题】：{user_prompt.strip()}"
                return {
                    "success": True,
                    "strategy": "ocr_only",
                    "direct_reply": "",
                    "ocr_text": ocr_text,
                    "prompt_for_llm": combined_prompt,
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "strategy": "ocr_only",
                    "direct_reply": "已收到您发送的图片，但未在图片中检测到可识别的文字。",
                    "ocr_text": "",
                    "prompt_for_llm": "",
                    "error": ocr_text if not ok else "未识别到文字"
                }

        # 2. 尝试主流多模态大模型 (Vision LLM)
        if strategy in ("auto", "vision_only"):
            v_ok, v_reply, v_info = self.recognize_with_vision(image_path, user_prompt=user_prompt)
            if v_ok:
                return {
                    "success": True,
                    "strategy": "vision",
                    "direct_reply": v_reply,
                    "ocr_text": "",
                    "prompt_for_llm": "",
                    "error": None
                }

            # Vision 失败：检查是否允许降级到 OCR
            if strategy == "auto" and self.image_config.fallback_to_ocr:
                # 自动降级为方案 B (WinRT OCR)
                ocr_ok, ocr_text, _ = self.recognize_with_ocr(image_path)
                if ocr_ok and ocr_text:
                    combined_prompt = f"【用户发送了图片，由于当前大模型不支持多模态视觉，系统已自动通过 OCR 提取图片内文字】：\n{ocr_text}"
                    if user_prompt.strip():
                        combined_prompt += f"\n\n【用户问题】：{user_prompt.strip()}"
                    return {
                        "success": True,
                        "strategy": "ocr_fallback",
                        "direct_reply": "",
                        "ocr_text": ocr_text,
                        "prompt_for_llm": combined_prompt,
                        "error": None
                    }
                else:
                    return {
                        "success": False,
                        "strategy": "ocr_fallback_failed",
                        "direct_reply": "已收到您发送的图片。当前接入的大模型不支持直接查看图片，且图片中未提取到有效文字。",
                        "ocr_text": "",
                        "prompt_for_llm": "",
                        "error": f"Vision失败 ({v_reply}); OCR无文字"
                    }

            # vision_only 且失败
            return {
                "success": False,
                "strategy": "vision_only_failed",
                "direct_reply": f"图片视觉识别失败: {v_reply}",
                "ocr_text": "",
                "prompt_for_llm": "",
                "error": v_reply
            }

        return {
            "success": False,
            "strategy": "unknown",
            "direct_reply": "",
            "ocr_text": "",
            "prompt_for_llm": "",
            "error": f"未知的图片识别策略: {strategy}"
        }
