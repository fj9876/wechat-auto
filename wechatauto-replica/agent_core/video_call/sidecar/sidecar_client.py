# -*- coding: utf-8 -*-
"""Sidecar 客户端代理 (agent_core.video_call.sidecar.sidecar_client)

主进程通过该客户端调用独立进程中的数字人推理引擎：
1. 自动拉起与守护 Sidecar 独立子进程 (Process Watchdog)
2. 异常自动降级与静默重启 (High Availability)
3. 退出时清理子进程与显存 (Resource Cleanup)
"""
from __future__ import annotations

import os
import sys
import time
import atexit
import base64
import logging
import urllib.request
import urllib.error
import json
import subprocess
from typing import Optional, List
import numpy as np
import cv2

from agent_core.video_call.avatar_engine import BaseAvatarEngine, MockFallbackAvatarEngine

logger = logging.getLogger("SidecarClient")


class SidecarAvatarEngineClient(BaseAvatarEngine):
    """Sidecar 独立进程客户端代理"""

    def __init__(self, port: int = 18990, auto_spawn: bool = True):
        self.port = port
        self.auto_spawn = auto_spawn
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._process: Optional[subprocess.Popen] = None
        self.fallback = MockFallbackAvatarEngine()
        self.is_weights_loaded = False
        self.current_image_path = ""
        self.engine_name = "liveportrait"

        atexit.register(self.shutdown)

    def _ensure_sidecar_running(self) -> bool:
        """检查 Sidecar 是否就绪，若未运行则自动拉起"""
        if self._check_health():
            return True

        if not self.auto_spawn:
            return False

        logger.info("[SidecarClient] 正在拉起独立 Avatar Sidecar 守护进程...")
        server_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sidecar_server.py")
        cmd = [sys.executable, server_script, "--port", str(self.port)]

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            # 等待就绪 (最多等待 3 秒)
            for _ in range(30):
                time.sleep(0.1)
                if self._check_health():
                    logger.info(f"[SidecarClient] ✅ Sidecar 进程启动成功 (PID: {self._process.pid})")
                    return True

            logger.warning("[SidecarClient] Sidecar 启动超时，降级至主进程本地引擎")
            return False
        except Exception as e:
            logger.error(f"[SidecarClient] 拉起 Sidecar 子进程异常: {e}")
            return False

    def _check_health(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/health")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data.get("status") == "ok"
        except Exception:
            pass
        return False

    def _post(self, path: str, payload: dict, timeout: float = 2.0) -> Optional[dict]:
        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}{path}",
                data=body,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.debug(f"[SidecarClient] 请求 {path} 异常: {e}")
        return None

    def initialize(self, model_dir: str = "", device: str = "cuda") -> bool:
        self.fallback.initialize(model_dir, device)
        if not self._ensure_sidecar_running():
            self.is_weights_loaded = False
            return True

        res = self._post("/init", {"engine": self.engine_name, "model_dir": model_dir}, timeout=15.0)
        if res and res.get("status") == "ok":
            self.is_weights_loaded = True
            logger.info(f"[SidecarClient] ✅ Sidecar 引擎 [{self.engine_name}] 初始化完毕")
            return True

        self.is_weights_loaded = False
        return True

    def set_character_image(self, image_path: str) -> bool:
        self.current_image_path = image_path
        self.fallback.set_character_image(image_path)
        if not self._check_health():
            self._ensure_sidecar_running()

        res = self._post("/set_avatar", {"image_path": image_path}, timeout=45.0)
        if res and res.get("status") == "ok":
            return bool(res.get("loaded", True))
        return False

    def generate_idle_frame(self) -> np.ndarray:
        try:
            req = urllib.request.Request(f"{self.base_url}/idle_frame")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    b64 = data.get("frame", "")
                    if b64:
                        buf = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
                        bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        except Exception:
            pass
        return self.fallback.generate_idle_frame()

    def process_audio_chunk(self, pcm_chunk: bytes, sample_rate: int = 16000) -> List[np.ndarray]:
        if not pcm_chunk:
            return [self.generate_idle_frame()]

        try:
            b64 = base64.b64encode(pcm_chunk).decode("ascii")
            res = self._post("/process_chunk", {"pcm_base64": b64, "sample_rate": sample_rate}, timeout=2.0)
            if res and res.get("status") == "ok":
                frames_b64 = res.get("frames", [])
                frames = []
                for fb64 in frames_b64:
                    buf = np.frombuffer(base64.b64decode(fb64), dtype=np.uint8)
                    bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                    frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
                if frames:
                    return frames
        except Exception as e:
            logger.debug(f"[SidecarClient] 推理异常降级: {e}")

        return self.fallback.process_audio_chunk(pcm_chunk, sample_rate)

    def reset(self):
        self.fallback.reset()
        self._post("/reset", {}, timeout=0.5)

    def shutdown(self):
        if self._process and self._process.poll() is None:
            logger.info("[SidecarClient] 正在安全终止 Sidecar 守护进程并清空显存...")
            try:
                self._process.terminate()
                self._process.wait(timeout=1.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
