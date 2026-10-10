# -*- coding: utf-8 -*-
"""agent_core 微信通用智能体核心包"""
import os

# 锁定所有 AI 运行库的全局模型与缓存路径至当前项目 models/ 目录，杜绝污染或占用系统 C 盘空间
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODELS_DIR = os.path.join(_BASE_DIR, "models")
os.makedirs(_MODELS_DIR, exist_ok=True)
os.environ["MODELSCOPE_CACHE"] = os.path.join(_MODELS_DIR, "modelscope")
os.environ["HF_HOME"] = os.path.join(_MODELS_DIR, "huggingface")
os.environ["HUGGINGFACE_HUB_CACHE"] = os.path.join(_MODELS_DIR, "huggingface", "hub")
os.environ["TORCH_HOME"] = os.path.join(_MODELS_DIR, "torch")

from .config import AppConfig, global_config
from .llm_client import LLMClient
from .rag_engine import RAGEngine
from .profile_engine import ProfileEngine, ContactProfile
from .tools import TOOL_DEFINITIONS, ToolExecutor
from .pipeline import AgentPipeline, PipelineResult
from .wechat_bridge import WeChatBridge

__all__ = [
    "AppConfig",
    "global_config",
    "LLMClient",
    "RAGEngine",
    "ProfileEngine",
    "ContactProfile",
    "TOOL_DEFINITIONS",
    "ToolExecutor",
    "AgentPipeline",
    "PipelineResult",
    "WeChatBridge",
]
