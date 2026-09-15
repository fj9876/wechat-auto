# -*- coding: utf-8 -*-
"""联系人专属用户画像与永久记忆引擎 (agent_core.profile_engine)

核心能力：
1. 实体强隔离：私聊以好友 wxid/username 唯一建档，群聊以成员真实 sender_wxid 独立建档，绝不混淆。
2. 永久磁盘记忆：一人一文件独立持久化（data/profiles/{safe_id}.json）。
3. 基于已有聊天记录深度全量初建画像：利用微信本地历史记录与大模型构建立体基线。
4. 聊天开始即生效：实时提取记忆摘要注入大模型 System Prompt，实现知己知彼的个性化回复。
5. 异步增量自完善与自修复：每次对话后对比新信息，提取新事实、更正旧误解，持续演进。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple

from .config import ProfileConfig
from .llm_client import LLMClient


@dataclass
class ContactProfile:
    """联系人用户画像与永久记忆数据模型"""
    person_id: str                                  # 实体唯一ID (私聊为好友wxid，群聊为 group_member:{sender_wxid})
    name: str = ""                                  # 昵称或显示名
    remark: str = ""                                # 好友微信备注名
    chat_type: str = "private"                      # "private" (私聊) 或 "group" (群聊)
    last_chat_id: str = ""                          # 最近交互的会话ID (wxid或群ID)

    # 维度1: 身份定位与属性标签
    identity: str = "普通联系人"                     # 身份角色，如：潜在客户、技术同事、老同学、VIP采购商
    tags: List[str] = field(default_factory=list)   # 标签列表，如：["关注自动化", "价格敏感", "高净值", "夜间活跃"]

    # 维度2: 性格特质与沟通偏好
    personality: str = "礼貌友好"                   # 性格特质，如：严谨细致、风趣幽默、干脆利落、谨慎
    communication_style: str = "偏好直接简明回答"   # 沟通偏好，如：喜欢步骤清晰的执行方案、反感客套套话

    # 维度3: 业务关注点与兴趣偏好
    interests: List[str] = field(default_factory=list) # 兴趣/业务方向，如：["微信自动化", "群管理", "数据库"]
    current_focus: str = ""                         # 当前正在跟进的核心事项或痛点

    # 维度4: 关键事实永久记忆列表 (Fact Memories)
    facts: List[str] = field(default_factory=list)  # 具体事实碎片，如：["使用Win11系统", "拥有3个500人群", "周三下午常开会"]

    # 维度5: 自完善与纠偏历史 (Refinement History)
    refinements: List[Dict[str, Any]] = field(default_factory=list) # 历史纠偏记录，如：[{"time": "...", "note": "更正了之前职业身份为技术经理"}]

    # 统计元数据
    interaction_count: int = 0                      # 累计互动对话轮数
    created_at: str = ""                            # 画像初建时间
    updated_at: str = ""                            # 最近一次自完善更新时间

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ContactProfile:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    def get_prompt_summary(self) -> str:
        """生成注入到大模型系统提示词的高浓度记忆摘要"""
        facts_str = "；".join(self.facts[-6:]) if self.facts else "暂无特殊事实记录"
        tags_str = ", ".join(self.tags) if self.tags else "待标记"
        interests_str = ", ".join(self.interests) if self.interests else "待发掘"

        lines = [
            f"【聊天对象专属画像与长期记忆 - {self.name or self.person_id}】",
            f"- 身份属性: {self.identity} (标签: {tags_str})",
            f"- 性格与沟通习惯: {self.personality} | {self.communication_style}",
            f"- 业务与兴趣关注: {interests_str}" + (f" (当前重点: {self.current_focus})" if self.current_focus else ""),
            f"- 关键事实永久记忆: {facts_str}",
            "- 个性化策略指导: 回复时请自然体现对其背景与历史习惯的连贯认知，遵循其沟通风格偏好，知己知彼但切勿机械生硬背诵记忆。"
        ]
        return "\n".join(lines)


class ProfileEngine:
    """联系人专属画像与永久记忆引擎"""

    def __init__(self, config: Optional[ProfileConfig] = None, llm_client: Optional[LLMClient] = None, db_instance=None):
        self.config = config or ProfileConfig()
        self.llm_client = llm_client or LLMClient()
        self.db = db_instance
        self._lock = threading.Lock()
        self._cache: Dict[str, ContactProfile] = {}

        # 确保存储目录存在
        self.storage_dir = self._resolve_storage_dir()
        os.makedirs(self.storage_dir, exist_ok=True)

    def _resolve_storage_dir(self) -> str:
        """解析存储绝对路径"""
        p = self.config.storage_dir or "data/profiles"
        if not os.path.isabs(p):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            p = os.path.join(base_dir, p)
        return p

    def update_config(self, config: ProfileConfig, llm_client: Optional[LLMClient] = None) -> None:
        self.config = config
        if llm_client:
            self.llm_client = llm_client
        self.storage_dir = self._resolve_storage_dir()
        os.makedirs(self.storage_dir, exist_ok=True)

    def set_db(self, db_instance) -> None:
        self.db = db_instance

    def safe_person_id(self, person_id: str) -> str:
        """将 person_id 转为安全的文件名字符"""
        return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', person_id)

    def _get_file_path(self, person_id: str) -> str:
        safe_id = self.safe_person_id(person_id)
        return os.path.join(self.storage_dir, f"{safe_id}.json")

    def load_profile(self, person_id: str) -> Optional[ContactProfile]:
        """读取指定联系人的永久记忆画像"""
        if not person_id:
            return None

        with self._lock:
            if person_id in self._cache:
                return self._cache[person_id]

        file_path = self._get_file_path(person_id)
        if not os.path.isfile(file_path):
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            profile = ContactProfile.from_dict(data)
            with self._lock:
                self._cache[person_id] = profile
            return profile
        except Exception as e:
            print(f"[Profile] 读取画像文件失败 ({file_path}): {e}")
            return None

    def save_profile(self, profile: ContactProfile) -> None:
        """持久化保存画像到独立文件"""
        if not profile or not profile.person_id:
            return

        profile.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        if not profile.created_at:
            profile.created_at = profile.updated_at

        file_path = self._get_file_path(profile.person_id)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)
            with self._lock:
                self._cache[profile.person_id] = profile
        except Exception as e:
            print(f"[Profile] 保存画像文件失败 ({file_path}): {e}")

    def list_profiles(self) -> List[Dict[str, Any]]:
        """获取所有已持久化的联系人画像列表概要"""
        results = []
        if not os.path.isdir(self.storage_dir):
            return results

        for fname in os.listdir(self.storage_dir):
            if fname.endswith(".json") and not fname.startswith("."):
                fpath = os.path.join(self.storage_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    results.append({
                        "person_id": data.get("person_id", ""),
                        "name": data.get("name", ""),
                        "remark": data.get("remark", ""),
                        "identity": data.get("identity", "普通联系人"),
                        "tags": data.get("tags", []),
                        "personality": data.get("personality", ""),
                        "current_focus": data.get("current_focus", ""),
                        "facts_count": len(data.get("facts", [])),
                        "interaction_count": data.get("interaction_count", 0),
                        "chat_type": data.get("chat_type", "private"),
                        "updated_at": data.get("updated_at", ""),
                    })
                except Exception:
                    continue

        results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return results

    def delete_profile(self, person_id: str) -> bool:
        """清除指定联系人的画像与永久记忆"""
        file_path = self._get_file_path(person_id)
        with self._lock:
            self._cache.pop(person_id, None)

        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
                return True
            except Exception as e:
                print(f"[Profile] 删除画像文件失败: {e}")
                return False
        return False

    def build_profile_from_history(
        self,
        person_id: str,
        name: str = "",
        remark: str = "",
        chat_type: str = "private",
        last_chat_id: str = "",
        history_messages: Optional[List[Dict[str, Any]]] = None
    ) -> ContactProfile:
        """基于已有历史聊天记录调用大模型全量初始化构建画像"""
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")

        target_user = last_chat_id or (person_id.replace("group_member:", "") if ":" in person_id else person_id)
        if self.db is not None:
            try:
                conn = self.db._contact_conn()
                if conn:
                    row = conn.execute(
                        "SELECT nick_name, remark FROM contact WHERE username=? LIMIT 1",
                        (target_user,),
                    ).fetchone()
                    if row:
                        db_remark = (row["remark"] or "").strip()
                        db_nick = (row["nick_name"] or "").strip()
                        if db_remark:
                            remark = db_remark
                        if not name or name == person_id or name.startswith("wxid_"):
                            name = db_remark or db_nick or name
            except Exception as e:
                pass

        # 1. 尝试从本地微信数据库读取聊天记录
        msgs = history_messages or []
        if not msgs and self.db is not None:
            try:
                db_msgs = self.db.get_messages(target_user, limit=self.config.max_history_scan or 50)
                if db_msgs:
                    msgs = db_msgs
            except Exception as e:
                print(f"[Profile] 从微信数据库拉取历史消息失败: {e}")

        # 格式化历史对话文本
        dialogue_snippets = []
        if msgs:
            # 按时间正序排列
            sorted_msgs = list(reversed(msgs)) if msgs and msgs[0].get("time", 0) > msgs[-1].get("time", 0) else msgs
            for m in sorted_msgs[-40:]:
                sender = "我方" if m.get("is_self") or m.get("sender_id") == 1 else (name or "对方")
                content = str(m.get("content") or "").strip()
                if content and not content.startswith("<msg") and not content.startswith("<?xml"):
                    dialogue_snippets.append(f"{sender}: {content}")

        dialogue_text = "\n".join(dialogue_snippets)

        # 2. 调用大模型提取结构化画像
        extracted = {}
        if dialogue_text.strip():
            sys_prompt = (
                "你是一个专业的人类性格分析与用户画像专家。\n"
                "请仔细分析以下我与该联系人的历史微信聊天记录，为TA建立立体的用户画像。\n"
                "必须严格按照以下 JSON 格式输出，不得包含任何 Markdown 格式或额外说明文本：\n"
                "{\n"
                '  "identity": "身份属性简述(如: 潜在客户、企业HR、技术专家、老同学等)",\n'
                '  "tags": ["标签1", "标签2", "标签3"],\n'
                '  "personality": "性格特点(如: 严谨务实、热情活泼、谨慎慢热等)",\n'
                '  "communication_style": "沟通习惯与偏好(如: 喜欢分点解答、偏好语音、厌恶推销等)",\n'
                '  "interests": ["关注领域1", "关注领域2"],\n'
                '  "current_focus": "近期正在探讨或关心的核心问题",\n'
                '  "facts": ["已明确的关键事实1", "已明确的关键事实2"]\n'
                "}"
            )

            res = self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"【联系人昵称/备注】: {name} (备注: {remark})\n\n【历史聊天记录】:\n{dialogue_text}"}
                ],
                temperature=0.3
            )

            if res.get("success") and res.get("content"):
                try:
                    raw_out = res["content"].strip()
                    # 剥离 markdown ```json ```
                    if "```" in raw_out:
                        raw_out = re.sub(r'^```[a-zA-Z]*\n', '', raw_out)
                        raw_out = re.sub(r'\n```$', '', raw_out)
                    extracted = json.loads(raw_out.strip())
                except Exception as ex:
                    print(f"[Profile] 解析大模型画像 JSON 失败: {ex}")

        # 3. 构造并持久化画像对象
        profile = ContactProfile(
            person_id=person_id,
            name=name or (remark or person_id),
            remark=remark,
            chat_type=chat_type,
            last_chat_id=last_chat_id,
            identity=extracted.get("identity") or (remark or "微信联系人"),
            tags=extracted.get("tags") or (["已建档"] if dialogue_text else ["新联系人"]),
            personality=extracted.get("personality") or "礼貌友好",
            communication_style=extracted.get("communication_style") or "偏好直接简明回答",
            interests=extracted.get("interests") or [],
            current_focus=extracted.get("current_focus") or "",
            facts=extracted.get("facts") or [],
            refinements=[{
                "time": now_str,
                "note": f"基于 {len(dialogue_snippets)} 条历史聊天记录完成初次全面画像分析" if dialogue_snippets else "初次建立基础画像卡片"
            }],
            interaction_count=len(dialogue_snippets) // 2,
            created_at=now_str,
            updated_at=now_str,
        )

        self.save_profile(profile)
        return profile

    def refine_profile(
        self,
        person_id: str,
        new_dialogue: List[Dict[str, str]],
        name: str = "",
        remark: str = "",
        chat_type: str = "private",
        last_chat_id: str = ""
    ) -> Optional[ContactProfile]:
        """随新对话内容持续增量自完善与自修复画像"""
        if not self.config.auto_refine or not person_id or not new_dialogue:
            return None

        profile = self.load_profile(person_id)
        if not profile:
            # 尚未建档，直接初始化全量构建
            return self.build_profile_from_history(
                person_id=person_id,
                name=name,
                remark=remark,
                chat_type=chat_type,
                last_chat_id=last_chat_id,
            )

        # 若已有 profile 没有规范的显示名称，尝试补全为备注或昵称
        if not profile.name or profile.name == person_id or profile.name.startswith("wxid_"):
            if name and not name.startswith("wxid_"):
                profile.name = name
            elif self.db is not None:
                try:
                    target_u = last_chat_id or (person_id.replace("group_member:", "") if ":" in person_id else person_id)
                    db_nick = self.db.get_nickname(target_u)
                    if db_nick and not db_nick.startswith("wxid_"):
                        profile.name = db_nick
                except Exception:
                    pass

        # 拼装新对话文本
        new_lines = []
        for d in new_dialogue[-4:]:
            role = "对方" if d.get("role") == "user" else "我方"
            content = d.get("content", "").strip()
            if content:
                new_lines.append(f"{role}: {content}")

        if not new_lines:
            return profile

        new_text = "\n".join(new_lines)
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")

        sys_prompt = (
            "你是一个专业的联系人画像记忆更新器。\n"
            "你的任务是根据本次最新的增量对话内容，对该联系人已有的画像和长期记忆进行【自完善与自修复】。\n"
            "判断准则：\n"
            "1. 纠偏自修复：若新对话纠正了之前的误解或旧信息（例如之前认为用Mac，本次明确换成了Win11），必须更新并记录修正。\n"
            "2. 增量事实：若发现了新的明确个人信息、业务需求或习惯，追加到 new_facts 中。\n"
            "3. 若新对话仅为无信息量的简短问答（如‘好的’、‘谢谢’），则 has_update 填 false。\n"
            "必须输出纯 JSON 格式：\n"
            "{\n"
            '  "has_update": true或false,\n'
            '  "identity": "更新后的身份属性(若未改变保持原样)",\n'
            '  "tags_to_add": ["新发现的标签"],\n'
            '  "personality": "更精准的性格描述",\n'
            '  "current_focus": "最新的关注点",\n'
            '  "new_facts": ["本次新确认的具体事实"],\n'
            '  "correction_note": "纠偏自修复说明，无纠偏留空"\n'
            "}"
        )

        user_content = (
            f"【已有联系人画像】:\n"
            f"- 身份: {profile.identity}\n"
            f"- 性格与风格: {profile.personality} | {profile.communication_style}\n"
            f"- 当前关注: {profile.current_focus}\n"
            f"- 已有事实记忆: {profile.facts}\n\n"
            f"【本次最新对话增量】:\n{new_text}"
        )

        res = self.llm_client.chat_completion(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.3
        )

        if not res.get("success") or not res.get("content"):
            return profile

        try:
            raw_out = res["content"].strip()
            if "```" in raw_out:
                raw_out = re.sub(r'^```[a-zA-Z]*\n', '', raw_out)
                raw_out = re.sub(r'\n```$', '', raw_out)
            result_json = json.loads(raw_out.strip())

            if not result_json.get("has_update", False):
                profile.interaction_count += 1
                self.save_profile(profile)
                return profile

            # 应用自完善
            changed = False
            if result_json.get("identity") and result_json["identity"] != profile.identity:
                profile.identity = result_json["identity"]
                changed = True

            if result_json.get("personality") and result_json["personality"] != profile.personality:
                profile.personality = result_json["personality"]
                changed = True

            if result_json.get("current_focus"):
                profile.current_focus = result_json["current_focus"]
                changed = True

            # 增量添加标签
            for tag in result_json.get("tags_to_add", []):
                t = str(tag).strip()
                if t and t not in profile.tags:
                    profile.tags.append(t)
                    changed = True

            # 增量添加事实
            for fact in result_json.get("new_facts", []):
                f_str = str(fact).strip()
                if f_str and f_str not in profile.facts:
                    profile.facts.append(f_str)
                    changed = True

            # 记录纠偏与自完善日志
            corr_note = result_json.get("correction_note", "").strip()
            refine_note = corr_note or f"增量对话自完善 (更新了关注点或新增了事实记忆)"
            profile.refinements.append({
                "time": now_str,
                "note": refine_note
            })

            profile.interaction_count += 1
            profile.updated_at = now_str
            self.save_profile(profile)
            return profile

        except Exception as e:
            print(f"[Profile] 自完善画像解析更新失败: {e}")
            return profile

    def refine_profile_async(
        self,
        person_id: str,
        new_dialogue: List[Dict[str, str]],
        name: str = "",
        remark: str = "",
        chat_type: str = "private",
        last_chat_id: str = ""
    ) -> None:
        """后台异步执行画像增量自完善，不阻塞消息正常发送"""
        def worker():
            try:
                self.refine_profile(
                    person_id=person_id,
                    new_dialogue=new_dialogue,
                    name=name,
                    remark=remark,
                    chat_type=chat_type,
                    last_chat_id=last_chat_id,
                )
            except Exception as e:
                print(f"[Profile] 异步自完善任务异常: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def get_prompt_context(self, person_id: str) -> str:
        """获取用于注入系统 Prompt 的画像摘要"""
        if not self.config.enabled or not self.config.inject_prompt or not person_id:
            return ""

        profile = self.load_profile(person_id)
        if not profile:
            return ""

        return profile.get_prompt_summary()
