# -*- coding: utf-8 -*-
"""独立数字人推理守护进程 (agent_core.video_call.sidecar.sidecar_server)

参考 OpenTalking 独立 Sidecar 进程隔离架构：
1. 进程级隔离：深度学习模型（PyTorch/ONNX）与显存占用独立于微信电话主业务进程
2. 崩溃防护：模型推理异常或显存溢出绝不影响微信语音电话接听
3. RESTful / Binary IPC：高效本地通信，提供低时延音画推理服务
"""
from __future__ import annotations

import os
import sys
import json
import base64
import logging
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import numpy as np
import cv2

# 将项目根目录加入 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from agent_core.video_call.avatar_engine import MockFallbackAvatarEngine, BaseAvatarEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [AvatarSidecar] %(message)s")
logger = logging.getLogger("AvatarSidecar")


class AvatarSidecarState:
    """Sidecar 进程内全局状态"""
    engine_name: str = "liveportrait"
    engine: BaseAvatarEngine = MockFallbackAvatarEngine()
    current_image_path: str = ""
    is_ready: bool = False


state = AvatarSidecarState()


class SidecarHTTPHandler(BaseHTTPRequestHandler):
    """Sidecar 请求处理器"""

    def log_message(self, format, *args):
        # 静默常规日志，避免刷屏
        pass

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json({
                "status": "ok",
                "engine": state.engine_name,
                "is_ready": state.is_ready,
                "avatar": state.current_image_path,
                "pid": os.getpid()
            })
        elif self.path == "/idle_frame":
            try:
                frame = state.engine.generate_idle_frame()
                _, buf = cv2.imencode(".jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
                b64 = base64.b64encode(buf).decode("ascii")
                self._send_json({"status": "ok", "frame": b64})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, status=500)
        else:
            self._send_json({"status": "not_found"}, status=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""

        try:
            req = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            req = {}

        if self.path == "/init":
            engine_name = req.get("engine", "liveportrait").lower().strip()
            model_dir = req.get("model_dir", "")
            logger.info(f"收到引擎初始化请求: {engine_name}")

            target_engine = None
            if "wav2lip" in engine_name:
                try:
                    from agent_core.video_call.engines.wav2lip_engine import Wav2LipAvatarEngine
                    w_eng = Wav2LipAvatarEngine(model_dir=model_dir or "models/wav2lip")
                    w_eng.initialize()
                    target_engine = w_eng
                except Exception as e:
                    logger.warning(f"Wav2Lip 引擎装载异常: {e}")
            elif "liveportrait" in engine_name:
                try:
                    from agent_core.video_call.engines.liveportrait_engine import LivePortraitAvatarEngine
                    lp_eng = LivePortraitAvatarEngine(model_dir=model_dir or "models/liveportrait")
                    lp_eng.initialize()
                    target_engine = lp_eng
                except Exception as e:
                    logger.warning(f"LivePortrait 引擎装载异常: {e}")
            elif "musetalk" in engine_name:
                try:
                    from agent_core.video_call.engines.musetalk_engine import MuseTalkAvatarEngine
                    mt_eng = MuseTalkAvatarEngine(model_dir=model_dir or "models/musetalk")
                    mt_eng.initialize()
                    target_engine = mt_eng
                except Exception as e:
                    logger.warning(f"MuseTalk 引擎装载异常: {e}")

            if target_engine is None:
                target_engine = MockFallbackAvatarEngine()
                target_engine.initialize()

            state.engine = target_engine
            state.engine_name = engine_name
            state.is_ready = True

            if state.current_image_path and os.path.exists(state.current_image_path):
                state.engine.set_character_image(state.current_image_path)

            self._send_json({"status": "ok", "engine": state.engine_name, "is_ready": state.is_ready})

        elif self.path == "/set_avatar":
            img_path = req.get("image_path", "")
            if not os.path.exists(img_path):
                self._send_json({"status": "error", "message": "Image not found"}, status=400)
                return

            state.current_image_path = img_path
            ok = state.engine.set_character_image(img_path)
            self._send_json({"status": "ok", "loaded": ok, "path": img_path})

        elif self.path == "/process_chunk":
            pcm_b64 = req.get("pcm_base64", "")
            sample_rate = int(req.get("sample_rate", 16000))
            if not pcm_b64:
                self._send_json({"status": "ok", "frames": []})
                return

            pcm_bytes = base64.b64decode(pcm_b64)
            frames = state.engine.process_audio_chunk(pcm_bytes, sample_rate=sample_rate)

            # 将生成的帧序列转为轻量 JPEG 编码传输
            encoded_frames = []
            for f in frames:
                _, buf = cv2.imencode(".jpg", cv2.cvtColor(f, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
                encoded_frames.append(base64.b64encode(buf).decode("ascii"))

            self._send_json({"status": "ok", "frames": encoded_frames, "count": len(encoded_frames)})

        elif self.path == "/reset":
            state.engine.reset()
            self._send_json({"status": "ok"})
        else:
            self._send_json({"status": "not_found"}, status=404)


def run_server(port: int = 18990):
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, SidecarHTTPHandler)
    logger.info(f"✅ Avatar Sidecar 独立服务已启动，监听: http://127.0.0.1:{port} (PID: {os.getpid()})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        logger.info("Avatar Sidecar 独立服务已停止")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18990, help="Sidecar 监听端口")
    args = parser.parse_args()
    run_server(args.port)
