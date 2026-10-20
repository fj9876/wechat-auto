# -*- coding: utf-8 -*-
"""云端全双工实时语音交互客户端 (agent_core.voice_call.cloud_realtime_client)

面向超低延迟全双工电话对话场景，支持接入主流云端实时多模态全双工 API：
1. 阿里百炼 DashScope 实时全双工语音 API (Qwen-Realtime / CosyVoice-Realtime)
2. OpenAI Realtime API (WebSocket /v1/realtime, gpt-4o-realtime-preview 等)

特性：
- 基于 WebSocket 的全双工双向音频流传输 (PCM16 16kHz 输入 / 24kHz 输出)
- 服务端原生 VAD 端点检测与超低延迟实时打断响应 (Barge-in)
- 线程安全异步事件循环封装，与本地 AudioRouter / VideoRouter 无缝接驳
- 具备网络抖动自愈与平滑降级机制 (连接失败时自动向上汇报并无缝切回本地级联架构)
"""
from __future__ import annotations

import os
import json
import time
import queue
import base64
import logging
import asyncio
import threading
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger("CloudRealtimeClient")


class CloudRealtimeClient:
    """云端全双工实时语音客户端"""

    def __init__(
        self,
        voip_config,
        on_audio_received: Optional[Callable[[bytes, int], None]] = None,
        on_interrupted: Optional[Callable[[], None]] = None,
        on_transcript: Optional[Callable[[str, str], None]] = None,  # (role, text)
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.config = voip_config
        self.on_audio_received = on_audio_received
        self.on_interrupted = on_interrupted
        self.on_transcript = on_transcript
        self.on_error = on_error

        self.provider = getattr(self.config, "cloud_realtime_provider", "dashscope").lower()
        self.model_name = getattr(self.config, "cloud_realtime_model", "qwen-realtime")
        self.api_url = getattr(self.config, "cloud_realtime_api_url", "")
        self.api_key = getattr(self.config, "cloud_realtime_api_key", "")

        self._running = False
        self._connected = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws = None
        self._audio_in_queue: asyncio.Queue = None
        self._sync_queue: queue.Queue = queue.Queue(maxsize=100)

    @property
    def is_connected(self) -> bool:
        return self._connected and self._running

    def _get_api_key(self) -> str:
        if self.api_key:
            return self.api_key.strip()
        if self.provider == "dashscope":
            return os.environ.get("DASHSCOPE_API_KEY", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
        return os.environ.get("OPENAI_API_KEY", "").strip()

    def _get_ws_url(self) -> str:
        if self.api_url:
            return self.api_url.strip()
        if self.provider == "dashscope":
            return "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
        return f"wss://api.openai.com/v1/realtime?model={self.model_name}"

    def start(self):
        """在后台线程中启动异步 WebSocket 连接循环"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True, name="CloudRealtimeLoop")
        self._thread.start()
        logger.info(f"[CloudRealtimeClient] 启动云端全双工实时客户端 (provider={self.provider}, model={self.model_name})...")

    def stop(self):
        """停止客户端并关闭连接"""
        self._running = False
        self._connected = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._cancel_all_tasks)
        self._thread = None
        logger.info("[CloudRealtimeClient] 云端全双工实时客户端已停止")

    def put_audio(self, pcm_bytes: bytes):
        """从 AudioRouter 接收本地捕获的 16kHz PCM16 音频切片，推入发送队列"""
        if not self._running or not self._connected:
            return
        try:
            self._sync_queue.put_nowait(pcm_bytes)
        except queue.Full:
            try:
                self._sync_queue.get_nowait()
                self._sync_queue.put_nowait(pcm_bytes)
            except Exception:
                pass

    def interrupt(self):
        """向服务端发送即时打断指令"""
        if not self._running or not self._connected:
            return
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._send_interrupt(), self._loop)

    async def _send_interrupt(self):
        try:
            if self._ws:
                if self.provider == "openai":
                    await self._ws.send(json.dumps({"type": "response.cancel"}))
                elif self.provider == "dashscope":
                    await self._ws.send(json.dumps({"header": {"action": "cancel-response"}}))
                logger.info("[CloudRealtimeClient] 已向云端发送打断取消指令 (response.cancel)")
        except Exception as e:
            logger.debug(f"[CloudRealtimeClient] 发送打断异常: {e}")

    def _cancel_all_tasks(self):
        for task in asyncio.all_tasks(self._loop):
            task.cancel()

    def _run_event_loop(self):
        """后台线程的 asyncio 事件循环"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main_ws_task())
        except Exception as e:
            logger.error(f"[CloudRealtimeClient] 事件循环异常退出: {e}")
        finally:
            self._loop.close()
            self._connected = False

    async def _main_ws_task(self):
        """主 WebSocket 生命周期管理与自动重连"""
        import websockets

        key = self._get_api_key()
        if not key:
            err = f"未配置 {self.provider} API Key，无法连接云端全双工实时 API"
            logger.warning(f"[CloudRealtimeClient] {err}")
            if self.on_error:
                self.on_error(err)
            return

        ws_url = self._get_ws_url()
        headers = {}
        if self.provider == "dashscope":
            headers["Authorization"] = f"Bearer {key}"
            headers["X-DashScope-DataInspection"] = "enable"
        else:
            headers["Authorization"] = f"Bearer {key}"
            headers["OpenAI-Beta"] = "realtime=v1"

        retry_count = 0
        max_retries = 3

        while self._running and retry_count < max_retries:
            try:
                logger.info(f"[CloudRealtimeClient] 正在连接云端全双工 WebSocket: {ws_url} (尝试 {retry_count + 1}/{max_retries})...")
                async with websockets.connect(
                    ws_url,
                    additional_headers=headers,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=10 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    retry_count = 0
                    logger.info("[CloudRealtimeClient] ✅ 成功建立云端全双工实时 WebSocket 会话！")

                    # 发送初始化会话配置
                    await self._send_session_init(ws)

                    # 并发执行发送与接收循环
                    sender_task = asyncio.create_task(self._audio_sender_loop(ws))
                    receiver_task = asyncio.create_task(self._message_receiver_loop(ws))

                    done, pending = await asyncio.wait(
                        [sender_task, receiver_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()

            except Exception as e:
                retry_count += 1
                self._connected = False
                logger.warning(f"[CloudRealtimeClient] WebSocket 连接中断或异常 ({retry_count}/{max_retries}): {e}")
                if self._running and retry_count < max_retries:
                    await asyncio.sleep(2.0 * retry_count)
                else:
                    if self.on_error:
                        self.on_error(f"云端实时服务连接失败: {e}")
                    break

    async def _send_session_init(self, ws):
        """配置实时会话参数 (VAD, 音色, 模式)"""
        try:
            if self.provider == "openai":
                session_update = {
                    "type": "session.update",
                    "session": {
                        "modalities": ["audio", "text"],
                        "instructions": (
                            "你正在接听微信用户的实时电话。请用亲切、简洁、地道口语回答，"
                            "每次回答控制在1到2句话以内，不要输出Markdown或特殊标记。"
                        ),
                        "voice": "alloy",
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 500,
                        },
                    },
                }
                await ws.send(json.dumps(session_update))
                logger.info("[CloudRealtimeClient] 已发送 OpenAI 实时会话初始化配置")
            elif self.provider == "dashscope":
                # DashScope 实时全双工协议支持
                init_msg = {
                    "header": {
                        "action": "run-task",
                        "task_id": f"task_{int(time.time() * 1000)}"
                    },
                    "payload": {
                        "task_group": "aigc",
                        "task": "voice-chat",
                        "function": "duplex",
                        "model": self.model_name or "qwen-realtime",
                        "parameters": {
                            "audio_format": "pcm",
                            "sample_rate": 16000,
                            "turn_detection": "server_vad"
                        }
                    }
                }
                await ws.send(json.dumps(init_msg))
                logger.info("[CloudRealtimeClient] 已发送 DashScope 实时会话初始化配置")
        except Exception as e:
            logger.error(f"[CloudRealtimeClient] 发送会话初始化配置失败: {e}")

    async def _audio_sender_loop(self, ws):
        """持续从同步队列拉取本地录音音频并推送到 WebSocket"""
        while self._running and self._connected:
            try:
                # 非阻塞获取同步队列里的 PCM 数据
                pcm_bytes = None
                try:
                    pcm_bytes = self._sync_queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.01)
                    continue

                if not pcm_bytes:
                    continue

                b64_audio = base64.b64encode(pcm_bytes).decode("utf-8")
                if self.provider == "openai":
                    msg = {
                        "type": "input_audio_buffer.append",
                        "audio": b64_audio,
                    }
                    await ws.send(json.dumps(msg))
                elif self.provider == "dashscope":
                    # DashScope 格式
                    msg = {
                        "header": {"action": "append-audio"},
                        "payload": {"audio": b64_audio}
                    }
                    await ws.send(json.dumps(msg))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[CloudRealtimeClient] 音频发送异常: {e}")
                break

    async def _message_receiver_loop(self, ws):
        """持续接收云端下发的音频流、字幕及打断事件"""
        while self._running and self._connected:
            try:
                raw_msg = await ws.recv()
                if not raw_msg:
                    continue

                msg = json.loads(raw_msg)
                msg_type = msg.get("type", "")

                # -------------------------------------------------------------
                # 1. OpenAI Realtime 协议事件处理
                # -------------------------------------------------------------
                if msg_type == "response.audio.delta":
                    delta_b64 = msg.get("delta", "")
                    if delta_b64 and self.on_audio_received:
                        pcm = base64.b64decode(delta_b64)
                        # OpenAI 默认输出 24kHz PCM16 单声道
                        self.on_audio_received(pcm, 24000)

                elif msg_type == "input_audio_buffer.speech_started":
                    # 服务端 VAD 检测到用户在说话 -> 触发打断！
                    logger.info("[CloudRealtimeClient] ⚡ 云端 VAD 探测到用户打断 (speech_started)")
                    if self.on_interrupted:
                        self.on_interrupted()

                elif msg_type == "response.audio_transcript.delta":
                    delta_text = msg.get("delta", "")
                    if delta_text and self.on_transcript:
                        self.on_transcript("assistant", delta_text)

                elif msg_type == "conversation.item.input_audio_transcription.completed":
                    transcript = msg.get("transcript", "")
                    if transcript and self.on_transcript:
                        self.on_transcript("user", transcript)

                elif msg_type == "error":
                    err_info = msg.get("error", {})
                    logger.error(f"[CloudRealtimeClient] 收到云端错误事件: {err_info}")
                    if self.on_error:
                        self.on_error(str(err_info.get("message", "未知云端错误")))

                # -------------------------------------------------------------
                # 2. DashScope Realtime 协议事件处理
                # -------------------------------------------------------------
                header = msg.get("header", {})
                event_name = header.get("event", "")
                payload = msg.get("payload", {})

                if event_name == "audio-packet":
                    audio_b64 = payload.get("audio", "")
                    if audio_b64 and self.on_audio_received:
                        pcm = base64.b64decode(audio_b64)
                        rate = payload.get("sample_rate", 16000)
                        self.on_audio_received(pcm, rate)

                elif event_name in ("user-speech-started", "barge-in"):
                    logger.info("[CloudRealtimeClient] ⚡ DashScope 云端探测到打断")
                    if self.on_interrupted:
                        self.on_interrupted()

                elif event_name == "text-packet":
                    text = payload.get("text", "")
                    if text and self.on_transcript:
                        self.on_transcript("assistant", text)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[CloudRealtimeClient] 消息接收异常: {e}")
                break
