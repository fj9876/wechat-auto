# -*- coding: utf-8 -*-
"""大模型客户端模块 (agent_core.llm_client)

基于 OpenAI 兼容规范封装 HTTP 客户端：
- 支持各类云端大模型：DeepSeek、通义千问 (Qwen)、Moonshot (Kimi)、智谱 GLM、OpenAI GPT-4o 等
- 支持本地开源大模型：Ollama、vLLM、LM Studio、Xinference 等
- 提供 API 连通性测试、单轮与多轮对话生成
"""
from __future__ import annotations

import json
import time
from typing import List, Dict, Any, Optional, Tuple
import urllib.request
import urllib.error

from .config import LLMConfig


class LLMClient:
    """OpenAI 兼容的大模型客户端"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()

    def update_config(self, config: LLMConfig) -> None:
        """更新客户端配置"""
        self.config = config

    def reload_config(self, config: LLMConfig) -> None:
        """重新加载客户端配置 (update_config 别名)"""
        self.update_config(config)

    def _get_base_url(self) -> str:
        """规范化 API URL"""
        url = (self.config.api_url or "").strip().rstrip("/")
        if not url:
            url = "https://api.deepseek.com/v1"
        return url

    def test_connection(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> Tuple[bool, str, float]:
        """测试大模型 API 连通性

        Returns:
            (success: bool, message: str, latency_ms: float)
        """
        url = (api_url or self.config.api_url).strip().rstrip("/")
        key = (api_key if api_key is not None else self.config.api_key).strip()
        model = (model_name or self.config.model_name).strip() or "deepseek-chat"

        endpoint = f"{url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}" if key else "",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "你好，请用一句话证明你正常运行"}],
            "max_tokens": 30,
            "temperature": 0.5,
        }

        start_time = time.time()
        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                elapsed = (time.time() - start_time) * 1000
                res_body = json.loads(resp.read().decode("utf-8"))
                reply = res_body.get("choices", [{}])[0].get("message", {}).get("content", "")
                return True, f"连通成功！模型响应: {reply.strip()}", round(elapsed, 1)
        except urllib.error.HTTPError as e:
            elapsed = (time.time() - start_time) * 1000
            err_msg = e.read().decode("utf-8", errors="ignore")
            return False, f"HTTP错误 [{e.code}]: {err_msg[:300]}", round(elapsed, 1)
        except urllib.error.URLError as e:
            elapsed = (time.time() - start_time) * 1000
            return False, f"网络连接失败: {e.reason}", round(elapsed, 1)
        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            return False, f"测试异常: {str(e)}", round(elapsed, 1)

    def get_models(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> Tuple[bool, List[str], str]:
        """获取上游大模型列表 (GET /models)

        Returns:
            (success: bool, models: List[str], message: str)
        """
        url = (api_url or self.config.api_url).strip().rstrip("/")
        key = (api_key if api_key is not None else self.config.api_key).strip()
        endpoint = f"{url}/models"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}" if key else "",
        }
        try:
            req = urllib.request.Request(endpoint, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=12) as resp:
                res_body = json.loads(resp.read().decode("utf-8"))
                models = []
                # OpenAI format: {"data": [{"id": "model_id"}, ...]}
                if isinstance(res_body.get("data"), list):
                    for item in res_body["data"]:
                        if isinstance(item, dict) and item.get("id"):
                            models.append(item["id"])
                # Ollama format: {"models": [{"name": "model_name"}, ...]}
                elif isinstance(res_body.get("models"), list):
                    for item in res_body["models"]:
                        if isinstance(item, dict):
                            m_id = item.get("name") or item.get("id") or item.get("model")
                            if m_id:
                                models.append(m_id)
                elif isinstance(res_body, list):
                    for item in res_body:
                        if isinstance(item, str):
                            models.append(item)
                        elif isinstance(item, dict) and item.get("id"):
                            models.append(item["id"])

                if models:
                    models = sorted(list(set(models)))
                    return True, models, f"成功获取到 {len(models)} 个可用上游模型"
                return False, [], "上游接口响应正常，但未解析出模型列表"
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            return False, [], f"获取模型失败 HTTP [{e.code}]: {err_msg[:200]}"
        except Exception as e:
            return False, [], f"获取模型请求失败: {str(e)}"

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """请求大模型生成回复 (支持多模态内容与可选的 Function Call / Tools)

        Returns:
            {
                "success": bool,
                "content": str,
                "tool_calls": List[dict],
                "error": Optional[str],
                "usage": dict
            }
        """
        endpoint = f"{self._get_base_url()}/chat/completions"
        key = (self.config.api_key or "").strip()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}" if key else "",
        }

        payload: Dict[str, Any] = {
            "model": (model_name or self.config.model_name or "deepseek-chat").strip(),
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=35) as resp:
                res_body = json.loads(resp.read().decode("utf-8"))
                choice = res_body.get("choices", [{}])[0]
                message = choice.get("message", {})
                content = message.get("content") or ""
                tool_calls = message.get("tool_calls") or []
                usage = res_body.get("usage", {})

                return {
                    "success": True,
                    "content": content,
                    "tool_calls": tool_calls,
                    "error": None,
                    "usage": usage,
                }
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            return {
                "success": False,
                "content": "",
                "tool_calls": [],
                "error": f"API HTTP [{e.code}]: {err_msg[:300]}",
                "usage": {},
            }
        except Exception as e:
            return {
                "success": False,
                "content": "",
                "tool_calls": [],
                "error": f"请求失败: {str(e)}",
                "usage": {},
            }
