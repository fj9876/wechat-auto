# -*- coding: utf-8 -*-
"""Web 控制台服务端入口 (web_app.py)

FastAPI 后端服务：
1. 提供 RESTful API 用于前端配置管理、大模型测试、RAG 文档扫描与检索、联系人与群选择
2. 提供 WebSocket 实时消息与流水线追踪事件推送
3. 提供在线沙盒直接测试智能体问答与工具链
4. 启动时自动调用本地默认浏览器打开控制台
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import webbrowser
from typing import Dict, Any, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 将当前目录加入模块搜索路径
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent_core.config import AppConfig, global_config, PROMPT_PRESETS
from agent_core.llm_client import LLMClient
from agent_core.rag_engine import RAGEngine
from agent_core.pipeline import AgentPipeline, PipelineResult
from agent_core.wechat_bridge import WeChatBridge

app = FastAPI(title="WeChat-AIAgent 控制台", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化组件
config: AppConfig = AppConfig.load()
llm_client = LLMClient(config.llm)
rag_engine = RAGEngine(config.rag, config.llm)
pipeline = AgentPipeline(config, llm_client, rag_engine)
wechat_bridge = WeChatBridge(config, pipeline)

# 若默认启用了 RAG 且配置了文件夹，启动时自动构建索引
if config.rag.enabled and config.rag.kb_folder_path:
    try:
        rag_engine.reindex(config.rag.kb_folder_path)
    except Exception as e:
        print(f"[Init] 自动索引知识库失败: {e}")

# 启动常驻后台微信消息监听（实时监控收信并推流至控制台日志）
def _start_wechat_monitor():
    time.sleep(1.2)
    try:
        ok, msg = wechat_bridge.start_listening()
        if ok:
            print("[Monitor] WeChat live message listener started successfully.")
        else:
            print(f"[Monitor] WeChat listener notice: {msg}")
    except Exception as e:
        print(f"[Monitor] WeChat listener error: {e}")

threading.Thread(target=_start_wechat_monitor, daemon=True).start()

# WebSocket 客户端连接池
active_websockets: List[WebSocket] = []
ws_lock = threading.Lock()


def broadcast_event_sync(payload: Dict[str, Any]) -> None:
    """从工作线程向所有活动 WebSocket 连接广播事件"""
    with ws_lock:
        clients = list(active_websockets)

    async def _send_all():
        for ws in clients:
            try:
                await ws.send_json(payload)
            except Exception:
                pass

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_send_all(), loop)
        else:
            loop.run_until_complete(_send_all())
    except RuntimeError:
        pass


wechat_bridge.register_event_listener(broadcast_event_sync)


# --------------------------------------------------------------------------
# 请求数据模型
# --------------------------------------------------------------------------

class TestLLMRequest(BaseModel):
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None


class SandboxChatRequest(BaseModel):
    message: str
    is_group: bool = False
    sender_name: str = "测试用户"


class ScanRAGRequest(BaseModel):
    folder_path: str


class SearchRAGRequest(BaseModel):
    query: str
    top_k: Optional[int] = 3


# --------------------------------------------------------------------------
# RESTful API 端点
# --------------------------------------------------------------------------

@app.get("/api/status")
def get_system_status():
    """获取整体系统状态"""
    wechat_stat = wechat_bridge.get_status()
    rag_stat = rag_engine.get_status()
    return {
        "status": "ok",
        "wechat": wechat_stat,
        "rag": rag_stat,
        "model_name": config.llm.model_name,
        "preset_name": config.safety.preset_name,
        "targets_count": {
            "users": len(config.targets.whitelist_users),
            "groups": len(config.targets.whitelist_groups),
            "reply_all_private": config.targets.reply_all_private,
            "reply_all_groups": config.targets.reply_all_groups,
            "group_at_only": config.targets.group_at_only,
        }
    }


@app.get("/api/config")
def get_config():
    """获取当前配置与提示词预设列表"""
    return {
        "config": config.model_dump(),
        "prompt_presets": PROMPT_PRESETS,
    }


@app.post("/api/config")
def update_config(new_config: Dict[str, Any]):
    """更新并保存系统配置"""
    global config
    try:
        updated = AppConfig(**new_config)
        updated.save()
        config = updated

        # 同步更新子模块
        llm_client.update_config(config.llm)
        rag_engine.update_config(config.rag, config.llm)
        pipeline.update_config(config)
        wechat_bridge.update_config(config)

        wechat_bridge.emit_event("log", {
            "level": "success",
            "message": "系统配置已更新并保存成功",
        })
        return {"success": True, "message": "配置保存成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"配置解析失败: {e}")


@app.post("/api/llm/test")
def test_llm_connection(req: TestLLMRequest):
    """测试大模型 API 连通性"""
    success, msg, latency = llm_client.test_connection(
        api_url=req.api_url,
        api_key=req.api_key,
        model_name=req.model_name,
    )
    return {
        "success": success,
        "message": msg,
        "latency_ms": latency,
    }


@app.post("/api/llm/models")
def get_upstream_models(req: TestLLMRequest):
    """一键获取上游大模型列表 (GET /models)"""
    success, models, msg = llm_client.get_models(req.api_url, req.api_key)
    return {
        "success": success,
        "models": models,
        "message": msg,
    }


class TestVoiceRequest(BaseModel):
    audio_path: Optional[str] = None
    engine: Optional[str] = None
    whisper_model: Optional[str] = None
    cloud_api_url: Optional[str] = None
    cloud_api_key: Optional[str] = None
    cloud_model_name: Optional[str] = None


class TestImageRequest(BaseModel):
    image_path: str
    prompt: Optional[str] = ""
    strategy: Optional[str] = None
    vision_model_name: Optional[str] = None


@app.post("/api/media/test_voice")
def test_voice_recognition(req: TestVoiceRequest):
    """测试语音识别转写"""
    try:
        from agent_core.media_engine import VoiceRecognizer
        from agent_core.config import VoiceConfig

        cfg = config.voice.model_copy()
        if req.engine:
            cfg.engine = req.engine
        if req.whisper_model:
            cfg.whisper_model = req.whisper_model
        if req.cloud_api_url is not None:
            cfg.cloud_api_url = req.cloud_api_url
        if req.cloud_api_key is not None:
            cfg.cloud_api_key = req.cloud_api_key
        if req.cloud_model_name:
            cfg.cloud_model_name = req.cloud_model_name

        recognizer = VoiceRecognizer(cfg)
        audio_path = req.audio_path
        if not audio_path or not os.path.exists(audio_path):
            return {"success": False, "message": f"音频文件不存在: {audio_path}"}

        ok, text, eng = recognizer.transcribe(audio_path)
        return {
            "success": ok,
            "text": text,
            "engine": eng,
            "message": "识别完成" if ok else text
        }
    except Exception as e:
        return {"success": False, "message": f"测试语音识别异常: {e}"}


@app.post("/api/media/test_image")
def test_image_recognition(req: TestImageRequest):
    """测试图片多模态视觉或 OCR 识别"""
    try:
        if not req.image_path or not os.path.exists(req.image_path):
            return {"success": False, "message": f"图片文件不存在: {req.image_path}"}

        img_cfg = config.image.model_copy()
        if req.strategy:
            img_cfg.strategy = req.strategy
        if req.vision_model_name:
            img_cfg.vision_model_name = req.vision_model_name

        from agent_core.media_engine import ImageEngine
        engine = ImageEngine(img_cfg, config.llm)
        res = engine.process_image(req.image_path, user_prompt=req.prompt or "")
        return {
            "success": res.get("success", False),
            "strategy": res.get("strategy", "unknown"),
            "direct_reply": res.get("direct_reply", ""),
            "ocr_text": res.get("ocr_text", ""),
            "error": res.get("error"),
        }
    except Exception as e:
        return {"success": False, "message": f"测试图片识别异常: {e}"}


@app.post("/api/utils/select_file")
def select_file_dialog(file_type: str = "all"):
    """打开系统原生弹窗选择本地测试文件"""
    import tkinter as tk
    from tkinter import filedialog

    selected_file = ""

    def _open_dialog():
        nonlocal selected_file
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            if file_type == "audio":
                types = [("Audio Files", "*.silk;*.wav;*.mp3;*.m4a;*.ogg;*.flac"), ("All Files", "*.*")]
            elif file_type == "image":
                types = [("Image Files", "*.jpg;*.jpeg;*.png;*.webp;*.bmp"), ("All Files", "*.*")]
            else:
                types = [("All Files", "*.*")]
            file_path = filedialog.askopenfilename(title="请选择文件", filetypes=types)
            root.destroy()
            selected_file = file_path
        except Exception as e:
            print(f"弹窗选择文件异常: {e}")

    t = threading.Thread(target=_open_dialog)
    t.start()
    t.join(timeout=60)

    if selected_file:
        norm_path = os.path.normpath(selected_file)
        return {"success": True, "file_path": norm_path}
    return {"success": False, "file_path": "", "message": "已取消选择"}


@app.post("/api/utils/select_folder")
def select_folder_dialog():
    """打开系统原生弹窗选择本地文件夹"""
    import tkinter as tk
    from tkinter import filedialog

    selected_folder = ""

    def _open_dialog():
        nonlocal selected_folder
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            folder = filedialog.askdirectory(title="请选择本地 RAG 知识库文件夹")
            root.destroy()
            selected_folder = folder
        except Exception as e:
            print(f"弹窗选择目录异常: {e}")

    t = threading.Thread(target=_open_dialog)
    t.start()
    t.join(timeout=60)

    if selected_folder:
        norm_path = os.path.normpath(selected_folder)
        return {"success": True, "folder_path": norm_path}
    return {"success": False, "folder_path": "", "message": "已取消选择文件夹"}


@app.get("/api/wechat/contacts")
def get_wechat_contacts():
    """获取微信联系人与微信群列表 (已过滤公众号与订阅号)"""
    return wechat_bridge.get_contacts_and_groups()


@app.post("/api/wechat/start")
def start_wechat():
    """开启自动回复"""
    ok, msg = wechat_bridge.set_auto_reply(True)
    return {"success": ok, "message": msg}


@app.post("/api/wechat/stop")
def stop_wechat():
    """暂停自动回复"""
    ok, msg = wechat_bridge.set_auto_reply(False)
    return {"success": ok, "message": msg}


@app.get("/api/rag/status")
def get_rag_status():
    """获取 RAG 状态"""
    return rag_engine.get_status()


@app.post("/api/rag/scan")
def scan_rag_folder(req: ScanRAGRequest):
    """扫描指定文件夹的文档"""
    path = req.folder_path.strip()
    if not path or not os.path.isdir(path):
        return {"success": False, "message": "目录不存在或路径无效", "files": []}
    files = rag_engine.scan_folder(path)
    return {
        "success": True,
        "message": f"成功扫描到 {len(files)} 个支持的文档",
        "files": files,
    }


@app.post("/api/rag/reindex")
def reindex_rag(req: ScanRAGRequest):
    """重建本地知识库索引"""
    res = rag_engine.reindex(req.folder_path)
    wechat_bridge.emit_event("log", {
        "level": "info" if res["success"] else "warning",
        "message": f"知识库索引构建: {res['message']}",
    })
    return res


@app.post("/api/rag/search")
def search_rag(req: SearchRAGRequest):
    """检索测试"""
    results = rag_engine.search(req.query, top_k=req.top_k)
    return {"query": req.query, "results": results}


@app.post("/api/chat/sandbox")
def chat_sandbox(req: SandboxChatRequest):
    """在线沙盒模拟测试（直接测试完整决策流水线，不向真实微信发消息）"""
    res: PipelineResult = pipeline.process(
        chat_id="sandbox_test",
        sender_name=req.sender_name,
        content=req.message,
        is_group=req.is_group,
        is_at_me=True,  # 沙盒中默认作为被@或直接对话
    )

    # 广播沙盒执行步骤
    wechat_bridge.emit_event("sandbox_result", {
        "sender_name": req.sender_name,
        "content": req.message,
        "reply_text": res.reply_text,
        "duration_ms": round(res.duration_ms, 1),
        "steps": [s.__dict__ for s in res.steps],
        "rag_hits": res.rag_hits,
        "tools": res.tool_executions,
    })

    return {
        "reply_text": res.reply_text,
        "duration_ms": round(res.duration_ms, 1),
        "steps": [s.__dict__ for s in res.steps],
        "rag_hits": res.rag_hits,
        "tool_executions": res.tool_executions,
        "error": res.error,
    }


# --------------------------------------------------------------------------
# WebSocket 实时日志流
# --------------------------------------------------------------------------

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    with ws_lock:
        active_websockets.append(websocket)

    # 发送欢迎状态包
    await websocket.send_json({
        "type": "log",
        "time_str": time.strftime("%H:%M:%S"),
        "data": {
            "level": "info",
            "message": "已成功连接至实时日志通道 (WebSocket)",
        }
    })

    try:
        while True:
            # 保持长连接并接收客户端心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except (WebSocketDisconnect, Exception):
        with ws_lock:
            if websocket in active_websockets:
                active_websockets.remove(websocket)


# --------------------------------------------------------------------------
# 静态资源与前端页面托管
# --------------------------------------------------------------------------

web_dir = os.path.join(CURRENT_DIR, "web")
if os.path.exists(web_dir):
    app.mount("/static", StaticFiles(directory=web_dir), name="static")


@app.get("/")
def serve_index():
    index_path = os.path.join(web_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"message": "Web 前端页面正在准备中..."})


def open_browser_later():
    time.sleep(1.2)
    try:
        webbrowser.open("http://127.0.0.1:8000")
    except Exception:
        pass


def main():
    import uvicorn
    # 自动在后台启动浏览器打开页面
    threading.Thread(target=open_browser_later, daemon=True).start()
    print("=" * 60)
    print("[START] WeChat-AIAgent Server starting...")
    print("[URL]   http://127.0.0.1:8000")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
