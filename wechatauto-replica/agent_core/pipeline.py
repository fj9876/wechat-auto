# -*- coding: utf-8 -*-
"""智能体工作流流水线 (agent_core.pipeline)

串联整个智能决策过程：
1. 消息过滤与意图分析 (转人工状态、群聊@标记)
2. 本地 RAG 检索 (可选，若开启则动态注入参考知识)
3. 大模型对话与工具调用 (Function Calling 执行分诊、排班、计算等)
4. 综合回复生成与前缀/后缀质检
5. 记录完整执行链路，供 Web UI 实时追踪
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from .config import AppConfig
from .llm_client import LLMClient
from .media_engine import ImageEngine
from .rag_engine import RAGEngine
from .tools import TOOL_DEFINITIONS, ToolExecutor


@dataclass
class PipelineStep:
    """流水线单步追踪记录"""
    name: str
    status: str  # success / skipped / failed
    details: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class PipelineResult:
    """流水线最终执行结果"""
    chat_id: str
    sender_name: str
    original_content: str
    reply_text: str
    should_send: bool
    is_group: bool
    is_at_me: bool
    rag_hits: List[Dict[str, Any]] = field(default_factory=list)
    tool_executions: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[PipelineStep] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: float = 0.0


class AgentPipeline:
    """智能体全流程决策管道"""

    def __init__(
        self,
        config: AppConfig,
        llm_client: LLMClient,
        rag_engine: RAGEngine,
        profile_engine: Optional[ProfileEngine] = None,
    ):
        self.config = config
        self.llm_client = llm_client
        self.rag_engine = rag_engine
        self.profile_engine = profile_engine or ProfileEngine(config.profile, llm_client)
        self.image_engine = ImageEngine(config.image, config.llm)
        # 会话状态维护: chat_id -> {"history": list, "human_mode": bool, "last_reply_time": float}
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def update_config(self, config: AppConfig) -> None:
        self.config = config
        self.llm_client.update_config(config.llm)
        self.rag_engine.update_config(config.rag, config.llm)
        self.profile_engine.update_config(config.profile, config.llm)
        self.image_engine.update_config(config.image, config.llm)

    def _get_session(self, chat_id: str) -> Dict[str, Any]:
        if chat_id not in self.sessions:
            self.sessions[chat_id] = {
                "history": [],
                "human_mode": False,
                "last_reply_time": 0.0,
            }
        return self.sessions[chat_id]

    def reset_session(self, chat_id: str) -> None:
        if chat_id in self.sessions:
            self.sessions[chat_id] = {
                "history": [],
                "human_mode": False,
                "last_reply_time": 0.0,
            }

    @staticmethod
    def _truncate_cleanly(text: str, max_len: int) -> str:
        """智能优雅截断：优先在自然段落或完整句子标点处截断，保持逻辑连贯，绝不断词断句"""
        if max_len <= 0 or len(text) <= max_len:
            return text

        candidate = text[:max_len]
        # 搜索区间：从 max_len 倒退回约 70% 处，寻找最近的段落或句子结束标点
        min_cutoff = int(max_len * 0.7)

        # 优先在双换行段落或完整句子标点处截断
        for sep in ["\n\n", "。\n", "！\n", "？\n", "。", "！", "？", "；\n", "；", "\n", ". ", "! ", "? "]:
            pos = candidate.rfind(sep, min_cutoff)
            if pos != -1:
                return candidate[:pos + len(sep)].strip() + "\n\n(由于单条字数限制已截断，如需了解更多请回复'继续')..."

        # 若未找到标点，检查空格（避免在英文单词中间生硬截断）
        pos = candidate.rfind(" ", min_cutoff)
        if pos != -1:
            return candidate[:pos].strip() + "..."

        return candidate + "..."

    def _decorate_reply(self, reply_text: str, is_group: bool, sender_name: str) -> str:
        """统一对回复内容应用长度截断、前缀、后缀以及群聊@提问者"""
        reply = reply_text.strip()
        max_len = getattr(self.config.safety, "max_reply_length", 0) or 0
        if max_len > 0 and len(reply) > max_len:
            reply = self._truncate_cleanly(reply, max_len)

        if self.config.safety.reply_prefix:
            reply = f"{self.config.safety.reply_prefix}{reply}"
        if self.config.safety.reply_suffix:
            reply = f"{reply}\n{self.config.safety.reply_suffix}"

        if is_group and self.config.targets.group_auto_at_sender and sender_name:
            if not reply.startswith(f"@{sender_name}"):
                reply = f"@{sender_name}\u2005{reply}"
        return reply

    def process(
        self,
        chat_id: str,
        sender_name: str,
        content: str,
        is_group: bool = False,
        is_at_me: bool = False,
        image_path: Optional[str] = None,
        raw_msg_type: str = "文本",
        sender_wxid: str = "",
        enable_profile: bool = True,
    ) -> PipelineResult:
        """运行完整智能体流水线 (支持文本、语音转写、多模态图片、OCR、RAG与联系人专属画像记忆)"""
        start_ts = time.time()
        steps: List[PipelineStep] = []
        rag_hits: List[Dict[str, Any]] = []
        tool_executions: List[Dict[str, Any]] = []

        # 计算独立联系人实体 ID (群聊使用成员真实 wxid 强隔离，私聊使用 chat_id/wxid)
        if is_group:
            person_id = f"group_member:{sender_wxid}" if sender_wxid else f"group_member:{chat_id}:{sender_name}"
        else:
            person_id = sender_wxid or chat_id

        session = self._get_session(chat_id)
        clean_content = content.strip()

        # Step 1: 消息采集与接管判定
        msg_type_desc = f" [{raw_msg_type}]" if raw_msg_type != "文本" else ""
        steps.append(PipelineStep(
            name="1. 消息采集",
            status="success",
            details=f"收到来自 [{sender_name}] 的{msg_type_desc}消息: {clean_content} (群聊={is_group}, 被@={is_at_me})"
        ))

        # 语音消息记录
        if raw_msg_type == "语音":
            steps.append(PipelineStep(
                name="语音识别 (ASR)",
                status="success",
                details=f"微信语音已成功转写为文本: {clean_content}"
            ))

        # 图片消息处理 (主流 Vision LLM + 备用 WinRT OCR 自动降级)
        if image_path and os.path.exists(image_path):
            img_res = self.image_engine.process_image(image_path, user_prompt=clean_content)
            strat = img_res.get("strategy")
            if strat == "vision":
                v_reply = img_res.get("direct_reply", "")
                final_reply = self._decorate_reply(v_reply, is_group, sender_name)
                session["history"].append({"role": "user", "content": f"{sender_name}: [发送了一张图片] {clean_content}" if is_group else f"[发送了一张图片] {clean_content}"})
                session["history"].append({"role": "assistant", "content": v_reply})
                session["last_reply_time"] = time.time()
                steps.append(PipelineStep(
                    name="多模态视觉分析 (Vision LLM)",
                    status="success",
                    details=f"视觉大模型直接理解图片并生成回复: {v_reply[:60]}..."
                ))
                return PipelineResult(
                    chat_id=chat_id,
                    sender_name=sender_name,
                    original_content=f"[图片] {clean_content}".strip(),
                    reply_text=final_reply,
                    should_send=True,
                    is_group=is_group,
                    is_at_me=is_at_me,
                    steps=steps,
                    duration_ms=(time.time() - start_ts) * 1000,
                )
            elif strat in ("ocr_fallback", "ocr_only"):
                ocr_text = img_res.get("ocr_text", "")
                tag = "Windows 原生 WinRT OCR 提字" if strat == "ocr_only" else "自动降级 -> WinRT OCR 文字提取"
                steps.append(PipelineStep(
                    name=tag,
                    status="success",
                    details=f"已从图片提取到文字 (共 {len(ocr_text)} 字): {ocr_text[:60]}..."
                ))
                clean_content = img_res.get("prompt_for_llm", clean_content)
            else:
                fallback_msg = img_res.get("direct_reply") or "已收到您发送的图片，但当前大模型不支持视觉理解且未在图片中检测到文字。"
                steps.append(PipelineStep(
                    name="图片识别",
                    status="warning",
                    details=img_res.get("error") or "未从图片中提取到有效信息"
                ))
                final_reply = self._decorate_reply(fallback_msg, is_group, sender_name)
                return PipelineResult(
                    chat_id=chat_id,
                    sender_name=sender_name,
                    original_content=f"[图片] {clean_content}".strip(),
                    reply_text=final_reply,
                    should_send=True,
                    is_group=is_group,
                    is_at_me=is_at_me,
                    steps=steps,
                    duration_ms=(time.time() - start_ts) * 1000,
                )

        # 检查是否处于人工接管模式
        if session.get("human_mode", False):
            reset_kws = ["恢复AI", "恢复机器人", "开启AI", "结束人工", "开启机器人", "退出人工"]
            raw_reset = getattr(self.config.safety, "reset_handover_keyword", "") or ""
            if raw_reset:
                reset_kws.extend([k.strip() for k in raw_reset.replace("，", ",").split(",") if k.strip()])

            if any(k in clean_content for k in reset_kws if k):
                session["human_mode"] = False
                steps.append(PipelineStep(
                    name="人工接管状态",
                    status="success",
                    details="检测到解除人工指令，已退出人工接管模式，恢复AI自动回复"
                ))
            else:
                steps.append(PipelineStep(
                    name="人工接管状态",
                    status="skipped",
                    details="该会话正处于人工接管中，机器人已暂停回复"
                ))
                return PipelineResult(
                    chat_id=chat_id,
                    sender_name=sender_name,
                    original_content=content,
                    reply_text="",
                    should_send=False,
                    is_group=is_group,
                    is_at_me=is_at_me,
                    steps=steps,
                    duration_ms=(time.time() - start_ts) * 1000,
                )

        # 检查是否触发转人工关键词 (支持中英文逗号分隔多个词)
        raw_handover = getattr(self.config.safety, "handover_keyword", "") or ""
        handover_kws = [k.strip() for k in raw_handover.replace("，", ",").split(",") if k.strip()]
        if any(k in clean_content for k in handover_kws if k):
            session["human_mode"] = True
            handover_reply = getattr(self.config.safety, "handover_reply", "") or "已为您转接人工客服，机器人已暂停自动回复，稍后人工人员将为您服务。"
            steps.append(PipelineStep(
                name="转人工触发",
                status="success",
                details=f"命中转人工关键词，已进入人工接管模式"
            ))
            return PipelineResult(
                chat_id=chat_id,
                sender_name=sender_name,
                original_content=content,
                reply_text=handover_reply,
                should_send=bool(handover_reply.strip()),
                is_group=is_group,
                is_at_me=is_at_me,
                steps=steps,
                duration_ms=(time.time() - start_ts) * 1000,
            )

        # 检查单日回复频次上限 (防刷频保护)
        today_str = time.strftime("%Y-%m-%d")
        if session.get("daily_date") != today_str:
            session["daily_date"] = today_str
            session["daily_count"] = 0

        daily_limit = getattr(self.config.safety, "daily_chat_limit", 0) or 0
        if daily_limit > 0 and session.get("daily_count", 0) >= daily_limit:
            steps.append(PipelineStep(
                name="单日频控拦截",
                status="skipped",
                details=f"该会话今日已达到最大回复上限 ({daily_limit} 次)，触发防刷拦截"
            ))
            return PipelineResult(
                chat_id=chat_id,
                sender_name=sender_name,
                original_content=content,
                reply_text="",
                should_send=False,
                is_group=is_group,
                is_at_me=is_at_me,
                steps=steps,
                duration_ms=(time.time() - start_ts) * 1000,
            )

        # 检查敏感词/违禁词合规过滤
        sensitive_raw = getattr(self.config.safety, "sensitive_words", "") or ""
        if sensitive_raw:
            s_words = [w.strip() for w in sensitive_raw.replace("，", ",").split(",") if w.strip()]
            matched = [w for w in s_words if w in clean_content]
            if matched:
                action = getattr(self.config.safety, "sensitive_action", "refuse") or "refuse"
                steps.append(PipelineStep(
                    name="敏感词风控拦截",
                    status="warning",
                    details=f"命中敏感词: {matched}，处置策略: {action}"
                ))
                if action == "handover":
                    session["human_mode"] = True
                    h_reply = getattr(self.config.safety, "handover_reply", "") or "已为您转接人工客服，机器人已暂停自动回复，稍后人工人员将为您服务。"
                    return PipelineResult(
                        chat_id=chat_id,
                        sender_name=sender_name,
                        original_content=content,
                        reply_text=h_reply,
                        should_send=bool(h_reply.strip()),
                        is_group=is_group,
                        is_at_me=is_at_me,
                        steps=steps,
                        duration_ms=(time.time() - start_ts) * 1000,
                    )
                elif action == "ignore":
                    return PipelineResult(
                        chat_id=chat_id,
                        sender_name=sender_name,
                        original_content=content,
                        reply_text="",
                        should_send=False,
                        is_group=is_group,
                        is_at_me=is_at_me,
                        steps=steps,
                        duration_ms=(time.time() - start_ts) * 1000,
                    )
                else:  # refuse
                    refuse_msg = getattr(self.config.safety, "sensitive_reply", "") or "抱歉，该话题暂时无法通过AI助手解答，敬请谅解。"
                    return PipelineResult(
                        chat_id=chat_id,
                        sender_name=sender_name,
                        original_content=content,
                        reply_text=refuse_msg,
                        should_send=True,
                        is_group=is_group,
                        is_at_me=is_at_me,
                        steps=steps,
                        duration_ms=(time.time() - start_ts) * 1000,
                    )

        # Step 2: 本地知识库 RAG 检索 (可选)
        rag_context_text = ""
        if self.config.rag.enabled and self.rag_engine.is_indexed:
            try:
                rag_hits = self.rag_engine.search(
                    clean_content,
                    top_k=self.config.rag.top_k,
                    threshold=self.config.rag.similarity_threshold,
                )
                if rag_hits:
                    steps.append(PipelineStep(
                        name="2. RAG知识检索",
                        status="success",
                        details=f"命中 {len(rag_hits)} 个本地知识库切片: " + ", ".join([h["file_name"] for h in rag_hits])
                    ))
                    snippets = []
                    for i, hit in enumerate(rag_hits, 1):
                        snippets.append(f"【参考资料{i} - 来自《{hit['file_name']}》】\n{hit['content']}")
                    rag_context_text = "\n\n".join(snippets)
                else:
                    steps.append(PipelineStep(
                        name="2. RAG知识检索",
                        status="skipped",
                        details="未检索到高于阈值的相关知识切片"
                    ))
            except Exception as e:
                steps.append(PipelineStep(
                    name="2. RAG知识检索",
                    status="failed",
                    details=f"检索异常: {e}"
                ))
        else:
            steps.append(PipelineStep(
                name="2. RAG知识检索",
                status="skipped",
                details="RAG知识库未开启或未建立索引 (跳过检索，直接进入LLM理解)"
            ))

        # Step 2.5: 联系人专属画像与长期记忆注入 (聊天开始即生效，各成员独立隔离)
        profile_context_text = ""
        if enable_profile and self.config.profile.enabled:
            try:
                profile_context_text = self.profile_engine.get_prompt_context(person_id)
                if not profile_context_text:
                    # 首次交互自动初建画像 (基于已有聊天记录)
                    p = self.profile_engine.build_profile_from_history(
                        person_id=person_id,
                        name=sender_name,
                        chat_type="group" if is_group else "private",
                        last_chat_id=chat_id,
                    )
                    if p:
                        profile_context_text = p.get_prompt_summary()

                if profile_context_text:
                    steps.append(PipelineStep(
                        name="2.5 联系人专属画像",
                        status="success",
                        details=f"已加载 [{sender_name}] 的专属画像记忆并注入提示词"
                    ))
            except Exception as e:
                steps.append(PipelineStep(
                    name="2.5 联系人专属画像",
                    status="failed",
                    details=f"加载画像异常: {e}"
                ))
        else:
            if is_group and not enable_profile:
                steps.append(PipelineStep(
                    name="2.5 联系人专属画像",
                    status="skipped",
                    details="本群聊未开启群成员画像功能 (群设置默认关闭)"
                ))

        # Step 3: 构建大模型 Prompt 与上下文
        system_content = self.config.safety.system_prompt or "你是一个智能微信助手。"
        max_len = getattr(self.config.safety, "max_reply_length", 0) or 0
        if max_len > 0:
            system_content += f"\n\n【回答篇幅约束】请将回答精炼控制在 {max_len} 字以内，确保语言凝练、条理完整清晰，有始有终，避免未说完被截断。"
        if profile_context_text:
            system_content += f"\n\n{profile_context_text}"
        if rag_context_text:
            system_content += f"\n\n【本地知识库参考资料】\n请结合以下本地知识库内容优先准确回答用户问题：\n{rag_context_text}"

        messages: List[Dict[str, str]] = [{"role": "system", "content": system_content}]

        # 携带多轮历史 (最多保留最近 6 条)
        history = session.get("history", [])
        for h in history[-6:]:
            messages.append(h)

        user_input_with_sender = f"{sender_name}: {clean_content}" if is_group else clean_content
        messages.append({"role": "user", "content": user_input_with_sender})

        # Step 4: 大模型理解与工具调用决策
        tools = TOOL_DEFINITIONS if self.config.safety.enable_tools else None
        steps.append(PipelineStep(
            name="3. LLM意图推理",
            status="success",
            details=f"向模型 [{self.config.llm.model_name}] 发起请求..."
        ))

        llm_res = self.llm_client.chat_completion(
            messages=messages,
            tools=tools,
        )

        if not llm_res["success"]:
            err_msg = llm_res.get("error") or "大模型服务无响应"
            steps.append(PipelineStep(
                name="3. LLM意图推理",
                status="failed",
                details=err_msg
            ))
            return PipelineResult(
                chat_id=chat_id,
                sender_name=sender_name,
                original_content=content,
                reply_text=f"【系统提示】大模型调用失败: {err_msg}",
                should_send=False,
                is_group=is_group,
                is_at_me=is_at_me,
                steps=steps,
                error=err_msg,
                duration_ms=(time.time() - start_ts) * 1000,
            )

        final_content = llm_res["content"] or ""
        tool_calls = llm_res.get("tool_calls") or []

        # Step 5: 若触发工具调用，执行工具并二次综合回复
        if tool_calls:
            steps.append(PipelineStep(
                name="4. 工具调用",
                status="success",
                details=f"模型触发了 {len(tool_calls)} 个工具调用"
            ))

            # 把助手的带 tool_calls 的消息存入上下文
            messages.append({
                "role": "assistant",
                "content": final_content,
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                fn = tc.get("function", {})
                fn_name = fn.get("name", "")
                try:
                    fn_args = json.loads(fn.get("arguments", "{}"))
                except Exception:
                    fn_args = {}

                tool_output = ToolExecutor.execute(fn_name, fn_args)
                tool_executions.append({
                    "name": fn_name,
                    "arguments": fn_args,
                    "output": tool_output,
                })
                steps.append(PipelineStep(
                    name=f"工具执行: {fn_name}",
                    status="success",
                    details=f"入参: {fn_args} -> 结果: {tool_output[:120]}"
                ))

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", "call_default"),
                    "content": tool_output,
                })

            # 二次请求 LLM 综合工具输出生成人类友好的回复
            second_res = self.llm_client.chat_completion(messages=messages, tools=None)
            if second_res["success"] and second_res["content"]:
                final_content = second_res["content"]

        # Step 6: 组装最终回复与前缀后缀
        reply = self._decorate_reply(final_content, is_group, sender_name)

        # 记录会话历史 (只保留纯文本，方便多轮上下文)
        session["history"].append({"role": "user", "content": user_input_with_sender})
        session["history"].append({"role": "assistant", "content": final_content})
        session["last_reply_time"] = time.time()
        session["daily_count"] = session.get("daily_count", 0) + 1

        # 触发联系人画像持续自完善与自修复 (后台异步，不拖慢即时回复)
        if enable_profile and self.config.profile.enabled and self.config.profile.auto_refine:
            try:
                self.profile_engine.refine_profile_async(
                    person_id=person_id,
                    new_dialogue=[
                        {"role": "user", "content": clean_content},
                        {"role": "assistant", "content": final_content}
                    ],
                    name=sender_name,
                    chat_type="group" if is_group else "private",
                    last_chat_id=chat_id,
                )
            except Exception as e:
                print(f"[Pipeline] 触发联系人画像自完善异常: {e}")

        steps.append(PipelineStep(
            name="5. 自动回复生成",
            status="success",
            details=f"回复文本生成完成 (共 {len(reply)} 字符)"
        ))

        return PipelineResult(
            chat_id=chat_id,
            sender_name=sender_name,
            original_content=content,
            reply_text=reply,
            should_send=True,
            is_group=is_group,
            is_at_me=is_at_me,
            rag_hits=rag_hits,
            tool_executions=tool_executions,
            steps=steps,
            duration_ms=(time.time() - start_ts) * 1000,
        )
