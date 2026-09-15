# -*- coding: utf-8 -*-
"""配置管理模块 (agent_core.config)

支持持久化保存与加载配置到 config.json：
- 大模型配置 (API URL, Key, 模型名称, 温度, MaxTokens)
- 系统提示词与预设模板
- 自动回复目标过滤配置 (联系人白名单、群聊白名单、群聊仅@回复)
- 本地 RAG 知识库配置 (是否启用、本地文件夹路径、Top-K、相似度阈值)
- 安全与风控配置 (转人工关键词、回复前缀/后缀、防刷冷却时间)
"""
from __future__ import annotations

import json
import os
import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

# 内置预设系统提示词
PROMPT_PRESETS: Dict[str, str] = {
    "通用全能助手": (
        "你是一个友好、专业、高效的微信智能助手。你的任务是清晰、礼貌地回答用户的问题。\n"
        "回答要条理清晰、通俗易懂，适合微信聊天阅读，避免过于冗长啰嗦。"
    ),
    "医学健康咨询专家": (
        "你是一名经验丰富的全科执业医师与健康咨询专家。你的职责是倾听患者的症状主诉，"
        "提供专业的健康宣教、科室分诊建议与就医指引。\n"
        "【重要安全准则】\n"
        "1. 若用户出现危急重症迹象（如急性剧烈胸痛、突发意识不清、呼吸极度困难、大出血等），"
        "必须第一时间发出红色预警并建议立即拨打120或前往急诊。\n"
        "2. 给出可能的健康指导与挂号科室建议，但必须说明你的回答仅供就医参考，不能替代线下面诊。\n"
        "3. 如参考了本地医疗知识库，请结合知识库内容给出专业解答。"
    ),
    "企业智能客服": (
        "你是一家企业的官方智能客服助手。你的职责是用热情、礼貌、专业的语气回答客户关于产品、"
        "服务、退换货及售前售后的各类咨询。\n"
        "若遇到无法解答的复杂投诉或专业订制问题，请提示客户回复'转人工'即可为您转接人工客服。"
    ),
    "编程与技术顾问": (
        "你是一位全栈软件开发与IT技术专家。能够快速解答各类编程语言（Python, JS, Go等）、"
        "架构设计、Bug排查、环境配置等技术问题。代码示例要简洁明了，并附带关键逻辑解释。"
    ),
    "生活情感与闲聊伙伴": (
        "你是一个幽默、善解人意、有同理心的生活好友。擅长倾听、开解情绪、分享生活小妙招和有趣故事，"
        "语气轻松自然，让微信聊天充满人情味。"
    )
}


class LLMConfig(BaseModel):
    """大模型接口配置"""
    api_url: str = Field(default="https://api.deepseek.com/v1", description="OpenAI兼容的API Base URL")
    api_key: str = Field(default="", description="API 密钥")
    model_name: str = Field(default="deepseek-chat", description="模型名称，如 deepseek-chat, gpt-4o, qwen-plus")
    temperature: float = Field(default=0.7, description="生成随机性 0.0 ~ 1.0")
    max_tokens: int = Field(default=1500, description="最大回复长度")
    embedding_api_url: str = Field(default="", description="可选: Embedding API 地址 (留空使用本地轻量BM25)")
    embedding_api_key: str = Field(default="", description="可选: Embedding API Key")
    embedding_model_name: str = Field(default="text-embedding-3-small", description="可选: Embedding 模型")


class TargetFilterConfig(BaseModel):
    """微信自动回复对象配置"""
    reply_all_private: bool = Field(default=False, description="是否自动回复所有私聊好友 (为False时仅回复白名单)")
    whitelist_users: List[str] = Field(default_factory=lambda: ["filehelper"], description="允许自动回复的私聊好友username/微信号/备注")
    reply_all_groups: bool = Field(default=False, description="是否自动回复所有群聊 (为False时仅回复白名单群)")
    whitelist_groups: List[str] = Field(default_factory=list, description="允许自动回复的群聊wxid/群名列表")
    group_at_only: bool = Field(default=True, description="群聊是否仅在被@时才回复 (强烈建议开启，避免刷屏)")
    group_auto_at_sender: bool = Field(default=True, description="群聊回复时是否自动@提问者")
    custom_at_triggers: List[str] = Field(default_factory=list, description="额外的自定义触发词或别名，如 ['小助手', '机器人']")


class RAGConfig(BaseModel):
    """本地 RAG 知识库配置 (可选)"""
    enabled: bool = Field(default=False, description="是否启用本地知识库 RAG")
    kb_folder_path: str = Field(default="", description="本地知识库文件夹绝对或相对路径")
    top_k: int = Field(default=3, description="检索召回切片数量")
    similarity_threshold: float = Field(default=0.25, description="相似度阈值")
    chunk_size: int = Field(default=500, description="切片大小字符数")
    chunk_overlap: int = Field(default=50, description="切片重叠字符数")


class SafetyConfig(BaseModel):
    """安全与提示词配置"""
    preset_name: str = Field(default="通用全能助手", description="选中的预设模板名称")
    presets: Dict[str, str] = Field(
        default_factory=lambda: dict(PROMPT_PRESETS),
        description="所有预设与自定义系统人设模板字典"
    )
    system_prompt: str = Field(
        default=PROMPT_PRESETS["通用全能助手"],
        description="当前生效的系统提示词"
    )
    # 回复修饰与品牌标识
    reply_prefix: str = Field(default="", description="回复内容前缀，例如 [AI回复] ")
    reply_suffix: str = Field(default="", description="回复内容后缀，例如 \\n(本回复由AI生成)")
    max_reply_length: int = Field(default=0, description="单条回复最大字数限制(0表示不限制，超出截断加省略号)")

    # 人工接管机制
    handover_keyword: str = Field(default="转人工,人工客服,找人工", description="触发转人工关键词(支持逗号分隔多个)")
    handover_reply: str = Field(
        default="已为您转接人工客服，机器人已暂停自动回复，稍后人工人员将为您服务。",
        description="触发转人工时的自动回复内容"
    )
    reset_handover_keyword: str = Field(default="恢复AI,退出人工,开启AI", description="解除人工接管模式的指令关键词(支持逗号分隔多个)")

    # 防刷与频率风控
    cooldown_seconds: float = Field(default=2.0, description="单会话回复防刷冷却时间(秒)，防并发冲击与微信风控")
    daily_chat_limit: int = Field(default=0, description="单个会话单日最大自动回复次数(0表示不限制)")

    # 敏感词合规过滤
    sensitive_words: str = Field(default="", description="敏感词/违禁词列表(逗号分隔)")
    sensitive_action: str = Field(default="refuse", description="敏感词处置策略: refuse(婉拒回复), handover(直接转人工), ignore(静默忽略)")
    sensitive_reply: str = Field(default="抱歉，该话题暂时无法通过AI助手解答，敬请谅解。", description="敏感词婉拒回复提示语")

    # 插件工具扩展
    enable_tools: bool = Field(default=True, description="是否启用工具调用功能 (如天气、计算器等外部插件)")

    def get_presets(self) -> Dict[str, str]:
        """获取全部人设字典映射，确保初始基础预设不丢失"""
        if not self.presets:
            self.presets = dict(PROMPT_PRESETS)
        return self.presets


class SingleGroupConfig(BaseModel):
    """单个群聊专属管理与黑名单配置"""
    chatroom_id: str = Field(default="", description="群聊 ID，如 xxx@chatroom")
    chatroom_name: str = Field(default="", description="群聊名称")
    is_admin_or_owner: bool = Field(default=False, description="当前登录微信账号是否为该群群主或管理员")
    masters: List[str] = Field(default_factory=list, description="本群管理者(master)成员列表(支持wxid、昵称或备注)")
    blacklist: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="本群黑名单列表，每项包含: username(wxid), name(昵称), kick_time(时间), kicked_by(操作者)"
    )
    kick_keywords: str = Field(default="踢,踢出,拉黑,移出,移出群聊", description="触发踢人拉黑关键词(逗号分隔)")
    kick_notice_template: str = Field(
        default="@{target} 已被群管理者移出本群并加入黑名单。",
        description="踢出群成员并拉黑后的群内通报模板"
    )
    rejoin_kick_template: str = Field(
        default="⚠️ 检测到黑名单成员 @{target} 再次进入群聊，已自动将其移出！",
        description="黑名单成员再次进群被自动踢出时的群内通报模板"
    )
    auto_kick_on_rejoin: bool = Field(default=True, description="是否开启黑名单复入自动秒踢")



class VoiceConfig(BaseModel):
    """语音识别 (ASR) 配置"""
    enabled: bool = Field(default=True, description="是否启用微信语音识别")
    engine: str = Field(default="local", description="语音识别引擎: local (本地 faster-whisper) 或 cloud (在线云端 ASR)")
    whisper_model: str = Field(default="base", description="本地 faster-whisper 模型规格: tiny, base, small, medium")
    whisper_device: str = Field(default="auto", description="本地推理设备: auto, cpu, cuda")
    cloud_api_url: str = Field(default="https://api.openai.com/v1", description="云端 Whisper API Base URL")
    cloud_api_key: str = Field(default="", description="云端 ASR API Key")
    cloud_model_name: str = Field(default="whisper-1", description="云端语音识别模型名称")


class ImageConfig(BaseModel):
    """图片多模态与 OCR 识别配置"""
    enabled: bool = Field(default=True, description="是否启用微信图片识别与分析")
    strategy: str = Field(default="auto", description="图片处理策略: auto (首选多模态视觉并自动降级OCR), vision_only (仅视觉模型), ocr_only (仅纯文字OCR)")
    vision_api_url: str = Field(default="", description="视觉大模型 API Base URL (留空继承全局大模型配置)")
    vision_api_key: str = Field(default="", description="视觉大模型 API Key (留空继承全局大模型配置)")
    vision_model_name: str = Field(default="", description="视觉大模型名称，如 qwen-vl-max, gpt-4o 等 (留空使用全局大模型)")
    fallback_to_ocr: bool = Field(default=True, description="当大模型不支持视觉或调用失败时，是否自动无缝降级为纯文字 OCR 提取")
    ocr_engine: str = Field(default="winrt", description="本地备用 OCR 引擎: winrt (Windows 原生硬件加速 OCR)")


class AppConfig(BaseModel):
    """系统全局配置"""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    targets: TargetFilterConfig = Field(default_factory=TargetFilterConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    image: ImageConfig = Field(default_factory=ImageConfig)
    groups_config: Dict[str, SingleGroupConfig] = Field(
        default_factory=dict,
        description="群聊专属个性化配置字典，key 为 chatroom_id"
    )
    auto_start_wechat: bool = Field(default=False, description="启动Web控制台时是否自动开启微信监听")

    def get_group_config(self, chatroom_id: str, chatroom_name: str = "") -> SingleGroupConfig:
        """获取指定群聊配置，若不存在则创建"""
        if chatroom_id not in self.groups_config:
            self.groups_config[chatroom_id] = SingleGroupConfig(
                chatroom_id=chatroom_id,
                chatroom_name=chatroom_name
            )
        elif chatroom_name and not self.groups_config[chatroom_id].chatroom_name:
            self.groups_config[chatroom_id].chatroom_name = chatroom_name
        return self.groups_config[chatroom_id]

    def is_group_master(self, chatroom_id: str, sender_id: str, sender_name: str = "") -> bool:
        """判断发送者是否为该群配置的管理者 (master)"""
        cfg = self.groups_config.get(chatroom_id)
        if not cfg or not cfg.masters:
            return False
        sender_id_clean = (sender_id or "").strip().lower()
        sender_name_clean = (sender_name or "").strip().lower()
        for m in cfg.masters:
            m_clean = m.strip().lower()
            if not m_clean:
                continue
            if sender_id_clean and (m_clean == sender_id_clean or sender_id_clean in m_clean):
                return True
            if sender_name_clean and (m_clean == sender_name_clean or sender_name_clean in m_clean or m_clean in sender_name_clean):
                return True
        return False

    def is_group_blacklisted(self, chatroom_id: str, user_id: str = "", user_name: str = "") -> bool:
        """判断成员是否处于该群黑名单中"""
        cfg = self.groups_config.get(chatroom_id)
        if not cfg or not cfg.blacklist:
            return False
        u_id = (user_id or "").strip().lower()
        u_name = (user_name or "").strip().lower()
        for b in cfg.blacklist:
            b_u = str(b.get("username", "")).strip().lower()
            b_n = str(b.get("name", "")).strip().lower()
            if u_id and b_u and (u_id == b_u or u_id in b_u):
                return True
            if u_name and b_n and (u_name == b_n or u_name in b_n or b_n in u_name):
                return True
        return False

    def add_to_group_blacklist(self, chatroom_id: str, username: str, name: str, kicked_by: str = "master") -> None:
        """将成员加入指定群黑名单并去重"""
        cfg = self.get_group_config(chatroom_id)
        for item in cfg.blacklist:
            if username and item.get("username") == username:
                item["name"] = name or item.get("name", "")
                item["kick_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                item["kicked_by"] = kicked_by
                return
            if name and item.get("name") == name:
                item["username"] = username or item.get("username", "")
                item["kick_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                item["kicked_by"] = kicked_by
                return
        cfg.blacklist.append({
            "username": username or "",
            "name": name or username,
            "kick_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "kicked_by": kicked_by or "master"
        })

    def remove_from_group_blacklist(self, chatroom_id: str, identifier: str) -> bool:
        """从指定群黑名单中移除某成员 (恢复进群与发言权限)"""
        cfg = self.groups_config.get(chatroom_id)
        if not cfg or not cfg.blacklist:
            return False
        clean_id = identifier.strip().lower()
        new_list = []
        removed = False
        for item in cfg.blacklist:
            b_u = str(item.get("username", "")).strip().lower()
            b_n = str(item.get("name", "")).strip().lower()
            if clean_id in (b_u, b_n):
                removed = True
            else:
                new_list.append(item)
        if removed:
            cfg.blacklist = new_list
        return removed

    @classmethod
    def load(cls, filepath: str = CONFIG_FILE_PATH) -> "AppConfig":
        """从 JSON 文件加载配置，不存在则使用默认配置并创建文件"""
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls(**data)
            except Exception as e:
                print(f"[Config] 加载配置文件失败，将使用默认配置: {e}")
        cfg = cls()
        cfg.save(filepath)
        return cfg

    def save(self, filepath: str = CONFIG_FILE_PATH) -> None:
        """保存配置到 JSON 文件"""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.model_dump(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Config] 保存配置文件失败: {e}")


# 全局单例
global_config = AppConfig.load()
