# -*- coding: utf-8 -*-
"""实时对话大模型流式引擎 (agent_core.voice_call.dialogue_engine)

严格使用当前大模型配置栏配置的供应商、API Key 与 Model：
1. 注入电话实时沟通人设与联系人专属记忆 (Memory Engine)
2. 流式获取大模型 Tokens，按标点断句流式推入 TTS 队列
3. 支持说话人插入打断 (Cancel)，实现秒级响应
"""
from __future__ import annotations

import os
import re
import time
import queue
import logging
import threading
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger("DialogueEngine")


class DialogueEngine:
    """电话智能体对话流式引擎"""

    def __init__(
        self,
        llm_config,
        profile_engine=None,
        on_sentence_ready: Optional[Callable[[str], None]] = None,
        on_reply_finished: Optional[Callable[[str], None]] = None,
    ):
        self.llm_config = llm_config
        self.profile_engine = profile_engine
        self.on_sentence_ready = on_sentence_ready
        self.on_reply_finished = on_reply_finished

        self._history: List[Dict[str, str]] = []
        self._current_caller_name: str = ""
        self._current_caller_id: str = ""
        self._is_generating = False
        self._cancel_flag = threading.Event()
        self._lock = threading.Lock()
        self._current_gen_token = 0
        self._client = None
        self._init_client()

    @property
    def is_generating(self) -> bool:
        """大模型是否正在流式思考与生成回答"""
        with self._lock:
            return self._is_generating

    def _init_client(self):
        """初始化 OpenAI 兼容客户端"""
        try:
            from openai import OpenAI
            api_key = (self.llm_config.api_key or "").strip()
            if not api_key:
                # 兼容本地开源模型或未填写 Key 的场景，防止 SDK 抛出 Missing credentials 导致启动报错
                api_key = "EMPTY"
            base_url = (self.llm_config.api_url or "").strip().rstrip("/")
            if not base_url:
                base_url = "https://api.deepseek.com/v1"
            self._client = OpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=30.0,
            )
        except Exception as e:
            logger.error(f"[DialogueEngine] 初始化 LLM 客户端失败: {e}")

    def update_config(self, llm_config):
        """动态同步大模型配置变更"""
        self.llm_config = llm_config
        self._init_client()

    def start_call_session(self, caller_name: str, caller_id: str = ""):
        """开启一次新的通话对话会话"""
        self._current_caller_name = caller_name
        self._current_caller_id = caller_id or caller_name
        self._history.clear()
        self._cancel_flag.clear()

        # 构建电话专属 System Prompt
        sys_prompt = self._build_system_prompt(caller_name, self._current_caller_id)
        self._history.append({"role": "system", "content": sys_prompt})
        logger.info(f"[DialogueEngine] 通话会话已建立: 对话人={caller_name}, 模型={self.llm_config.model_name}")

    def _build_system_prompt(self, caller_name: str, caller_id: str) -> str:
        """组装带记忆的电话交互人设 Prompt"""
        base = (
            f"你正在接听微信好友【{caller_name}】打来的实时语音电话。\n"
            "【电话交流特殊规则】\n"
            "1. 你正在通过电话与对方实时交谈，请用口语化、亲切、自然的人类真人语气说话。\n"
            "2. 每次回答必须控制在 1 到 2 句话以内（40字以内），严禁长篇大论，避免对方听着厌烦。\n"
            "3. 绝对不要使用 Markdown 语法、不要输出代码、不要使用括号补充心理活动，只输出你要说出的声音内容。\n"
            "4. 如果对方只是打招呼（如'喂'、'在吗'），你也自然礼貌回应即可（如'喂，在的，怎么啦？'）。"
        )

        # 尝试注入联系人记忆画像
        if self.profile_engine:
            try:
                prof = None
                if hasattr(self.profile_engine, "get_or_create_profile"):
                    prof = self.profile_engine.get_or_create_profile(caller_id, caller_name)
                elif hasattr(self.profile_engine, "load_profile"):
                    prof = self.profile_engine.load_profile(caller_id)
                if prof:
                    if hasattr(prof, "get_prompt_summary"):
                        base += "\n\n" + prof.get_prompt_summary()
                    else:
                        mem_parts = []
                        identity = getattr(prof, "identity", "") or getattr(prof, "role", "")
                        style = getattr(prof, "communication_style", "") or getattr(prof, "style", "")
                        facts = getattr(prof, "facts", [])
                        if identity:
                            mem_parts.append(f"对方角色: {identity}")
                        if style:
                            mem_parts.append(f"对方沟通偏好: {style}")
                        if facts:
                            mem_parts.append(f"已知事实: {'; '.join(facts[-3:])}")
                        if mem_parts:
                            base += "\n【对方背景与记忆】\n" + "\n".join(mem_parts)
            except Exception as e:
                logger.warning(f"[DialogueEngine] 提取联系人画像失败: {e}")

        return base

    def on_user_speech(self, text: str):
        """对方说完一句话，触发大模型流式思考与分句"""
        if not text.strip():
            return

        with self._lock:
            # 递增会话代号并触发前序中断
            self._current_gen_token += 1
            gen_token = self._current_gen_token
            self._cancel_flag.set()

        # 稍等片刻让旧流感知退出
        time.sleep(0.02)
        self._cancel_flag.clear()

        # 启动生成线程
        t = threading.Thread(target=self._generate_stream, args=(text, gen_token), daemon=True)
        t.start()

    def cancel(self):
        """打断当前大模型流式生成"""
        with self._lock:
            self._current_gen_token += 1
            self._cancel_flag.set()
        logger.info("[DialogueEngine] 触发生成中断 (Cancel)...")

    def _generate_stream(self, user_text: str, gen_token: int):
        """流式调用 LLM 并按标点分句输出"""
        if not self._client:
            self._init_client()
        if not self._client:
            logger.error("[DialogueEngine] LLM 客户端未初始化，无法生成回复")
            return

        with self._lock:
            if gen_token != self._current_gen_token:
                return
            self._is_generating = True
            self._history.append({"role": "user", "content": user_text})

            # 保留最近 10 轮历史
            if len(self._history) > 21:
                self._history = [self._history[0]] + self._history[-20:]

        full_reply = []
        clause_buffer = ""
        # 分句标点符号
        clause_delimiters = re.compile(r'([，,。!！?？\n；;]+)')

        try:
            logger.info(f"[DialogueEngine] 请求大模型: {self.llm_config.model_name}...")
            stream = self._client.chat.completions.create(
                model=self.llm_config.model_name,
                messages=self._history,
                temperature=self.llm_config.temperature,
                stream=True,
            )

            for chunk in stream:
                if self._cancel_flag.is_set() or gen_token != self._current_gen_token:
                    logger.info("[DialogueEngine] 流式已被打断或代号已过期，停止读取 Tokens")
                    break

                if not chunk.choices or len(chunk.choices) == 0:
                    continue
                delta = chunk.choices[0].delta
                token = getattr(delta, "content", None) or ""
                if not token:
                    continue

                full_reply.append(token)
                clause_buffer += token

                # 智能自然语流呼吸分句 (杜绝 2~3 个字的碎片短句被逗号强行切碎，引发声卡死寂卡顿)：
                # 1. 终结标点 (。！？!?\n；;) 只要字数 >= 3 即视为完整语义句；
                # 2. 呼吸逗号 (，,) 仅当当前累计字数 >= 10 字时才作为自然停顿切分，保证每句有足够播放时长支撑后台流水线
                for i, ch in enumerate(clause_buffer):
                    is_major = ch in "。!！?？\n；;"
                    is_minor = ch in "，," and len(clause_buffer[:i].strip()) >= 10
                    if is_major or is_minor:
                        ready_sentence = clause_buffer[:i + 1].strip()
                        clause_buffer = clause_buffer[i + 1:]
                        if ready_sentence and gen_token == self._current_gen_token and not self._cancel_flag.is_set() and self.on_sentence_ready:
                            try:
                                self.on_sentence_ready(ready_sentence)
                            except Exception as e:
                                logger.error(f"[DialogueEngine] 发音回调异常: {e}")
                        break

            # 处理结尾残余文本
            if clause_buffer.strip() and gen_token == self._current_gen_token and not self._cancel_flag.is_set():
                if self.on_sentence_ready:
                    try:
                        self.on_sentence_ready(clause_buffer.strip())
                    except Exception:
                        pass

            complete_text = "".join(full_reply).strip()
            if complete_text and gen_token == self._current_gen_token and not self._cancel_flag.is_set():
                with self._lock:
                    self._history.append({"role": "assistant", "content": complete_text})
                logger.info(f"[DialogueEngine] AI 完整回复: 「{complete_text}」")
                if self.on_reply_finished:
                    try:
                        self.on_reply_finished(complete_text)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"[DialogueEngine] 大模型生成异常: {e}", exc_info=True)
        finally:
            with self._lock:
                if gen_token == self._current_gen_token:
                    self._is_generating = False
