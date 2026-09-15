# -*- coding: utf-8 -*-
"""微信桥接服务模块 (agent_core.wechat_bridge)

对接 wechatauto 核心库：
1. 精准获取微信通讯录联系人（过滤公众号、订阅号与系统号）及微信群聊
2. 实时常驻增量监听微信消息 (基于 wechatauto.db.Listener)
3. 实时将所有到达消息推送到 Web UI 日志流中
4. 白名单过滤、群聊判定与 @自己 智能识别
5. 自动回复开关控制 (开启时生成回复并自动发送，关闭时纯监控记录)
"""
from __future__ import annotations

import collections
import os
import re
import threading
import time
from typing import Dict, Any, List, Optional, Tuple, Callable

from .config import AppConfig
from .media_engine import VoiceRecognizer
from .pipeline import AgentPipeline, PipelineResult

# 微信系统内置功能号与公众号过滤黑名单
SYSTEM_ACCOUNTS = {
    "brandsessionholder", "qqmail", "fmessage", "newsapp", "medianote",
    "floatbottle", "shakeapp", "qmessage", "lbsapp", "masssendapp",
    "feedsapp", "voip", "weixin", "weibo", "pc_share", "notifymessage",
    "topstoryapp", "appbrandcustomerservicemsg", "notification_messages",
    "opencustomerservicemsg", "tmessage", "helper_entry", "mphelper"
}


class WeChatBridge:
    """微信自动化与消息路由桥接器"""

    def __init__(self, config: AppConfig, pipeline: AgentPipeline):
        self.config = config
        self.pipeline = pipeline
        self.is_running = False          # 监听器是否运行中
        self.auto_reply_enabled = False  # 自动回复开关是否打开
        self._listener = None
        self._db = None
        self._gui = None
        self._self_info: Dict[str, Any] = {}
        self._event_listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._lock = threading.Lock()
        self._last_send_ts = 0.0
        self._recent_sent_replies: collections.deque = collections.deque(maxlen=200)
        self._recent_incoming_queries: collections.deque = collections.deque(maxlen=100)
        self._recent_group_at_records: Dict[str, float] = {}  # 记录群内提问者近期@机器人的时间戳 (key: username_sender)
        self.voice_recognizer = VoiceRecognizer(self.config.voice)

    def update_config(self, config: AppConfig) -> None:
        """更新微信桥接器配置"""
        self.config = config
        self.voice_recognizer.update_config(config.voice)

    def register_event_listener(self, listener: Callable[[Dict[str, Any]], None]) -> None:
        """注册前端 WebSocket 事件广播回调"""
        if listener not in self._event_listeners:
            self._event_listeners.append(listener)

    def unregister_event_listener(self, listener: Callable[[Dict[str, Any]], None]) -> None:
        if listener in self._event_listeners:
            self._event_listeners.remove(listener)

    def emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """向所有前端监听器广播事件"""
        payload = {
            "type": event_type,
            "timestamp": time.time(),
            "time_str": time.strftime("%H:%M:%S"),
            "data": data,
        }
        for listener in self._event_listeners:
            try:
                listener(payload)
            except Exception:
                pass

    def get_status(self) -> Dict[str, Any]:
        """获取微信与机器人运行状态"""
        wechat_detected = False
        self_name = "未登录/未检测到"
        self_wxid = ""

        try:
            from wechatauto.db import WeChatDB
            if self._db is None:
                self._db = WeChatDB()
            info = self._db.get_self_info()
            if info and info.get("username"):
                wechat_detected = True
                self_wxid = info.get("username", "")
                self_name = info.get("nick_name") or self_wxid
                self._self_info = info
        except Exception:
            pass

        return {
            "is_running": self.is_running,
            "auto_reply_enabled": self.auto_reply_enabled,
            "wechat_detected": wechat_detected,
            "self_name": self_name,
            "self_wxid": self_wxid,
        }

    def get_contacts_and_groups(self) -> Dict[str, List[Dict[str, Any]]]:
        """获取真实的微信通讯录好友与微信群列表 (排除公众号、订阅号与系统号)"""
        contacts = []
        groups = []

        try:
            from wechatauto.db import WeChatDB
            if self._db is None:
                self._db = WeChatDB()

            # 1. 获取近期会话字典映射 (用于显示未读数与最近一句话)
            session_map = {}
            try:
                raw_sessions = self._db.get_sessions(limit=500)
                for s in raw_sessions:
                    u = s.get("username", "")
                    if u:
                        session_map[u] = s
            except Exception:
                pass

            # 2. 默认添加文件传输助手 (置顶方便安全测试)
            contacts.append({
                "username": "filehelper",
                "name": "文件传输助手",
                "remark": "官方测试助手",
                "is_group": False,
                "summary": session_map.get("filehelper", {}).get("summary", "微信安全测试会话"),
                "unread": session_map.get("filehelper", {}).get("unread", 0),
                "is_recent": True,
            })

            # 3. 从 contact.db 精准查询通讯录联系人与群聊
            conn = self._db._contact_conn()
            if conn:
                try:
                    # 查询所有真实好友联系人：local_type = 1, verify_flag = 0, 排除 gh_ 开头的公众号与系统号
                    friends_sql = """
                        SELECT username, nick_name, remark, alias
                        FROM contact
                        WHERE delete_flag = 0
                          AND local_type = 1
                          AND verify_flag = 0
                          AND username NOT LIKE 'gh_%'
                          AND username NOT LIKE '%@chatroom'
                          AND username NOT LIKE '%@openim'
                          AND username != 'filehelper'
                    """
                    friend_rows = conn.execute(friends_sql).fetchall()
                    recent_contacts = []
                    other_contacts = []

                    for r in friend_rows:
                        u = r["username"]
                        if u in SYSTEM_ACCOUNTS or u.startswith("gh_"):
                            continue

                        disp_name = r["remark"] or r["nick_name"] or r["alias"] or u
                        s_info = session_map.get(u)

                        item = {
                            "username": u,
                            "name": disp_name,
                            "remark": r["remark"] or "",
                            "is_group": False,
                            "summary": s_info.get("summary", "") if s_info else "",
                            "unread": s_info.get("unread", 0) if s_info else 0,
                            "is_recent": bool(s_info),
                            "last_time": s_info.get("last_time", 0) if s_info else 0,
                        }

                        if s_info:
                            recent_contacts.append(item)
                        else:
                            other_contacts.append(item)

                    # 有最近聊天记录的联系人排在前面
                    recent_contacts.sort(key=lambda x: x["last_time"], reverse=True)
                    other_contacts.sort(key=lambda x: x["name"])
                    contacts.extend(recent_contacts)
                    contacts.extend(other_contacts)

                    # 查询所有微信群聊：local_type = 2 或 username 结尾为 @chatroom
                    groups_sql = """
                        SELECT username, nick_name, remark
                        FROM contact
                        WHERE delete_flag = 0
                          AND (local_type = 2 OR username LIKE '%@chatroom')
                    """
                    group_rows = conn.execute(groups_sql).fetchall()
                    seen_groups = set()

                    recent_groups = []
                    other_groups = []

                    for r in group_rows:
                        u = r["username"]
                        if not u.endswith("@chatroom") or u in seen_groups:
                            continue
                        seen_groups.add(u)

                        disp_name = r["remark"] or r["nick_name"] or u
                        s_info = session_map.get(u)

                        g_item = {
                            "username": u,
                            "name": disp_name,
                            "remark": "",
                            "is_group": True,
                            "summary": s_info.get("summary", "") if s_info else "",
                            "unread": s_info.get("unread", 0) if s_info else 0,
                            "is_recent": bool(s_info),
                            "last_time": s_info.get("last_time", 0) if s_info else 0,
                        }

                        if s_info:
                            recent_groups.append(g_item)
                        else:
                            other_groups.append(g_item)

                    recent_groups.sort(key=lambda x: x["last_time"], reverse=True)
                    other_groups.sort(key=lambda x: x["name"])
                    groups.extend(recent_groups)
                    groups.extend(other_groups)

                finally:
                    conn.close()

        except Exception as e:
            self.emit_event("log", {"level": "error", "message": f"获取通讯录与群列表失败: {e}"})

        return {"contacts": contacts, "groups": groups}

    def get_group_members(self, chatroom_wxid: str) -> List[Dict[str, Any]]:
        """获取指定群聊的全部成员列表"""
        if not self._db:
            return []
        try:
            return self._db.get_group_members(chatroom_wxid)
        except Exception as e:
            self.emit_event("log", {"level": "error", "message": f"获取群成员列表异常: {e}"})
            return []

    def is_self_group_owner(self, chatroom_wxid: str) -> bool:
        """检查当前登录微信账号是否为该群群主"""
        if not self._db:
            return False
        try:
            self_wxid = (self._self_info.get("username") or "").strip()
            if not self_wxid:
                info = self._db.get_self_info()
                self_wxid = info.get("username", "")
            if not self_wxid:
                return False
            conn = self._db._contact_conn()
            if not conn:
                return False
            try:
                row = conn.execute("SELECT owner FROM chat_room WHERE username=? LIMIT 1", (chatroom_wxid,)).fetchone()
                if row and row["owner"]:
                    return row["owner"] == self_wxid
            finally:
                conn.close()
        except Exception:
            pass
        return False

    def kick_group_member(self, chatroom_name_or_id: str, member_name_or_wxid: str) -> Tuple[bool, str]:
        """执行将群成员移出群聊 (踢人与黑名单落地)"""
        with self._lock:
            self._ensure_interactive_desktop()
            primary_name, candidates = self.resolve_chat_target(chatroom_name_or_id)
            group_target = primary_name or chatroom_name_or_id

            try:
                from wechatauto.guia import WeChatGUI
                if self._gui is None:
                    self._gui = WeChatGUI()

                if hasattr(self._gui, "kick_member"):
                    res = self._gui.kick_member(member_name_or_wxid, group_target)
                    if res is not None:
                        msg = res.message if hasattr(res, "message") else (res.get("message", "") if isinstance(res, dict) else str(res))
                        is_ok = getattr(res, "is_success", False) or (res.get("status") == "成功" if isinstance(res, dict) else False)
                        return is_ok, msg

                return False, f"未找到移出群成员执行方法（kick_member）"
            except Exception as e:
                return False, f"移出群成员执行异常: {e}"


    def _is_message_for_me_in_group(self, content: str, group_id: str = "") -> Tuple[bool, str]:
        """判定群消息是否 @ 了自己，并提取剥离@后的纯文本"""
        if not content:
            return False, ""

        # 确保 self_info 总是有效载入
        if not self._self_info or not self._self_info.get("username"):
            try:
                if self._db is not None:
                    info = self._db.get_self_info()
                    if info and info.get("username"):
                        self._self_info = info
            except Exception:
                pass

        self_nick = (self._self_info.get("nick_name") or "").strip()
        self_wxid = (self._self_info.get("username") or "").strip()

        # 候选触发词列表
        triggers = []
        if self_nick:
            triggers.append(self_nick)
        if self_wxid:
            triggers.append(self_wxid)
        if self.config.targets.custom_at_triggers:
            triggers.extend(self.config.targets.custom_at_triggers)

        # 若提供了群 ID，尝试获取机器人在该群内的群名片/群昵称
        if group_id and self._db:
            try:
                members = self.get_group_members(group_id)
                for m in members:
                    if m.get("username") == self_wxid:
                        gnick = (m.get("nick_name") or "").strip()
                        gremark = (m.get("remark") or "").strip()
                        if gnick and gnick not in triggers:
                            triggers.append(gnick)
                        if gremark and gremark not in triggers:
                            triggers.append(gremark)
            except Exception:
                pass

        # 宽松匹配: @昵称\u2005, @昵称 , @昵称:, @昵称：, @昵称\xa0, @昵称\u3000, 甚至紧挨着文本
        for tr in sorted(triggers, key=lambda x: -len(x)):
            if not tr:
                continue
            # 支持 @tr 后面紧跟空白符、标点或结尾
            pattern = re.compile(
                rf'@(?:{re.escape(tr)})(?:[\s\u2000-\u200f\u3000\xa0:：]+|$)',
                re.IGNORECASE
            )
            if pattern.search(content):
                clean_text = pattern.sub('', content).strip()
                return True, clean_text

            # 兼容极端情况：@tr 直接贴着中文字符输入，例如 @踮起脚看日出你好
            direct_prefix = f"@{tr}"
            if content.startswith(direct_prefix):
                clean_text = content[len(direct_prefix):].lstrip(" :\t\u2005\u3000\xa0")
                return True, clean_text

        return False, content

    def resolve_chat_target(self, username: str) -> Tuple[str, List[str]]:
        """将底层消息的 username/wxid 解析为微信客户端 UI 界面能识别匹配的会话名称

        Returns:
            (primary_target: str, all_candidates: List[str])
        """
        if not username:
            return "", []

        # 1. 文件传输助手
        if username in ("filehelper", "文件传输助手"):
            return "文件传输助手", ["文件传输助手", "filehelper"]

        # 2. 微信群聊
        if username.endswith("@chatroom"):
            grp_name = ""
            try:
                if self._db is not None:
                    grp_name = self._db.get_nickname(username) or ""
            except Exception:
                pass
            name = grp_name.strip() if grp_name else username
            return name, [name, username]

        # 3. 私聊好友
        candidates: List[str] = []
        try:
            if self._db is None:
                from wechatauto.db import WeChatDB
                self._db = WeChatDB()

            conn = self._db._contact_conn()
            if conn:
                try:
                    row = conn.execute(
                        "SELECT username, nick_name, remark, alias FROM contact WHERE username = ?",
                        (username,)
                    ).fetchone()
                    if row:
                        remark = (row["remark"] or "").strip()
                        if remark:
                            candidates.append(remark)

                        nick = (row["nick_name"] or "").strip()
                        # 过滤掉不可见空字符 (如 \u3164, \u200b 等)
                        clean_nick = re.sub(r'[\s\u2000-\u200f\u3164\ufeff]', '', nick)
                        if clean_nick and nick not in candidates:
                            candidates.append(nick)

                        alias = (row["alias"] or "").strip()
                        if alias and alias not in candidates:
                            candidates.append(alias)
                finally:
                    conn.close()
        except Exception:
            pass

        try:
            db_nick = self._db.get_nickname(username) if self._db else ""
            if db_nick and db_nick.strip() and db_nick.strip() not in candidates:
                candidates.append(db_nick.strip())
        except Exception:
            pass

        if username not in candidates:
            candidates.append(username)

        primary = candidates[0] if candidates else username
        return primary, candidates

    def _should_auto_reply(self, username: str, sender_name: str, content: str, has_image: bool = False) -> Tuple[bool, bool, bool, str]:
        """白名单与群聊@过滤策略判定

        Returns:
            (should_reply: bool, is_group: bool, is_at_me: bool, clean_text: str)
        """
        is_group = username.endswith("@chatroom")
        is_at_me = False
        clean_text = content.strip()

        if is_group:
            # 1. 检查群聊是否在白名单中
            allowed_group = False
            if self.config.targets.reply_all_groups:
                allowed_group = True
            else:
                primary_name, candidates = self.resolve_chat_target(username)
                all_grp_ids = set(candidates) | {username, sender_name}
                for target in self.config.targets.whitelist_groups:
                    if target in all_grp_ids:
                        allowed_group = True
                        break

            if not allowed_group:
                return False, True, False, clean_text

            # 2. 检查群聊是否设定「仅 @ 才回复」
            is_at, stripped = self._is_message_for_me_in_group(content, group_id=username)
            is_at_me = is_at
            clean_text = stripped

            at_key = f"{username}_{sender_name}"
            if is_at_me:
                self._recent_group_at_records[at_key] = time.time()
            elif has_image:
                # 若发送的是图片且未直接打出@，检测该用户近 60 秒内是否在群内 @ 过机器人
                if (time.time() - self._recent_group_at_records.get(at_key, 0)) < 60:
                    is_at_me = True

            if self.config.targets.group_at_only and not is_at_me:
                # 开启了仅@回复，但未被@ -> 忽略
                return False, True, False, clean_text

            return True, True, is_at_me, clean_text

        else:
            # 私聊过滤
            allowed_user = False
            if self.config.targets.reply_all_private:
                allowed_user = True
            else:
                primary_name, candidates = self.resolve_chat_target(username)
                all_ids = set(candidates) | {username, sender_name}
                if username in ("filehelper", "文件传输助手"):
                    all_ids.update({"filehelper", "文件传输助手"})

                for target in self.config.targets.whitelist_users:
                    if target in all_ids:
                        allowed_user = True
                        break

            if not allowed_user:
                return False, False, False, clean_text

            return True, False, True, clean_text

    def _is_self_message(self, msg_row: Dict[str, Any], raw_content: str, username: str) -> Tuple[bool, str]:
        """多重高精准识别是否为自己/本人发送的消息 (彻底杜绝死循环)
        
        Returns:
            (is_self: bool, reason: str)
        """
        # 确保 self_info 非空
        if not self._self_info or not self._self_info.get("username"):
            try:
                if self._db is not None:
                    info = self._db.get_self_info()
                    if info and info.get("username"):
                        self._self_info = info
            except Exception:
                pass

        self_wxid = (self._self_info.get("username") or "").strip()
        sender_username = (msg_row.get("sender_username") or "").strip()
        origin_source = msg_row.get("origin_source")
        status = msg_row.get("status")

        # 1. 检查防回环：与最近机器人发出的回复文本精确比对
        clean_text = (raw_content or "").strip()
        if username.endswith("@chatroom"):
            clean_text = re.sub(r'^(?:wxid_[0-9a-zA-Z_]+|.*?):\s*\n', '', clean_text).strip()

        if clean_text:
            now = time.time()
            with self._lock:
                for item in self._recent_sent_replies:
                    if now - item.get("ts", 0) > 180:
                        continue
                    sent_text = item.get("text", "")
                    if not sent_text:
                        continue
                    if clean_text == sent_text:
                        return True, "与近期发出回复完全一致 (死循环阻断)"
                    if len(sent_text) >= 6 and (sent_text in clean_text or clean_text in sent_text):
                        return True, "包含近期发出回复文本 (死循环阻断)"

        # 2. 文件传输助手 (filehelper) 自测支持：
        # 如果是发往文件传输助手的消息，且不是机器人自己刚刚发出的回复，允许作为测试消息放行
        if username in ("filehelper", "文件传输助手"):
            return False, ""

        # 3. 微信数据库底层 origin_source / status 识别本地发出的消息
        # origin_source == 1: 本地客户端发出；status in (1, 2): 发送中或已发送
        if origin_source == 1:
            return True, "origin_source==1 (本地客户端发出)"
        if status in (1, 2):
            return True, f"status=={status} (本地发出状态)"

        # 4. 手机端同步发出的消息识别 (手机微信在群聊发言，PC端同步接收):
        # 4.1 群聊消息中发言人 wxid 前缀匹配 (群消息格式: wxid_xxxx:\n...)
        if username.endswith("@chatroom") and raw_content:
            m = re.match(r'^(wxid_[0-9a-zA-Z_]+):\s*\n', raw_content)
            if m:
                extracted_wxid = m.group(1)
                if self_wxid and extracted_wxid == self_wxid:
                    return True, f"群消息前缀=={extracted_wxid} (手机端同步发送)"

        # 4.2 私聊会话中判定
        if not username.endswith("@chatroom"):
            # 对方发来的消息 (origin_source == 2 且 status in (3, 4))，明确放行
            if username != self_wxid and (origin_source == 2 or status in (3, 4)):
                return False, ""
            if self_wxid and sender_username and (sender_username == self_wxid) and username == self_wxid:
                return True, f"sender_username=={sender_username} (自己发给自己的会话)"

        return False, ""

    def _handle_incoming_message(self, msg_row: Dict[str, Any], listener) -> None:
        """处理增量到达的微信消息：第一时间广播到实时日志流中"""
        try:
            username = msg_row.get("username", "")
            raw_content = msg_row.get("content") or ""
            if isinstance(raw_content, bytes):
                raw_content = raw_content.decode("utf-8", errors="ignore")

            # -------------------------------------------------------------
            # 关键过滤：多重防线识别自己/机器人发送的消息，杜绝死循环
            # -------------------------------------------------------------
            is_self, self_reason = self._is_self_message(msg_row, raw_content, username)
            if is_self:
                # 属于本地自发消息，直接跳过，绝不触发自动回复
                return

            is_group = username.endswith("@chatroom")
            sender_name = "对方"
            group_name = ""
            group_sender_wxid = ""
            msg_body = raw_content

            if is_group:
                # 获取群名称
                try:
                    group_name = self._db.get_nickname(username) or username
                except Exception:
                    group_name = username

                # 提取群消息中的发送者 (群消息格式: wxid_xxxx:\n正文 或 25984984902854382@openim:\n正文)
                m = re.match(r'^([a-zA-Z0-9_@\.-]+):\s*\n(.*)$', raw_content, re.DOTALL)
                if m:
                    group_sender_wxid = m.group(1)
                    msg_body = m.group(2)
                    try:
                        sender_name = self._db.get_nickname(group_sender_wxid) or group_sender_wxid
                    except Exception:
                        sender_name = group_sender_wxid
                else:
                    sid = msg_row.get("real_sender_id") or msg_row.get("sender_id")
                    group_sender_wxid = str(sid or "")
                    sender_name = f"用户{sid}" if sid else "群成员"
            else:
                try:
                    sender_name = self._db.get_nickname(username) or username
                except Exception:
                    sender_name = username

            # -------------------------------------------------------------
            # 多模态媒体处理：语音提取转写 (ASR) 与 图片解密落地
            # -------------------------------------------------------------
            detected_voice_path = None
            detected_image_path = None
            raw_type = str(msg_row.get("type", "文本"))
            local_id = msg_row.get("local_id")

            # A. 语音消息自动下载与转文字
            if (raw_type == "语音" or msg_row.get("local_type") == 34) and local_id and self.config.voice.enabled:
                try:
                    from wechatauto.media import MediaDownloader
                    if self._db is not None:
                        md = MediaDownloader(self._db)
                        detected_voice_path = md.download_voice(username, int(local_id))
                except Exception as e:
                    self.emit_event("log", {"level": "warning", "message": f"⚠️ 提取语音媒体失败: {e}"})

                if detected_voice_path and os.path.exists(detected_voice_path):
                    ok_trans, text_trans, eng_name = self.voice_recognizer.transcribe(detected_voice_path)
                    if ok_trans and text_trans:
                        msg_body = text_trans
                        self.emit_event("log", {
                            "level": "info",
                            "message": f"🎤 [{eng_name} 语音识别成功] {display_title if 'display_title' in locals() else sender_name}: \"{text_trans}\""
                        })
                    else:
                        self.emit_event("log", {
                            "level": "warning",
                            "message": f"⚠️ [语音转写未检测到文字] {text_trans}"
                        })

            # B. 图片消息自动解密落地
            if (raw_type == "图片" or msg_row.get("local_type") == 3) and local_id and self.config.image.enabled:
                try:
                    from wechatauto.media import MediaDownloader
                    if self._db is not None:
                        md = MediaDownloader(self._db)
                        detected_image_path = md.download_image(username, int(local_id))
                except Exception as e:
                    self.emit_event("log", {"level": "warning", "message": f"⚠️ 解密图片媒体失败: {e}"})

                if detected_image_path and os.path.exists(detected_image_path):
                    self.emit_event("log", {
                        "level": "info",
                        "message": f"🖼️ [收到图片并解密落地] 文件: {os.path.basename(detected_image_path)}"
                    })

            # -------------------------------------------------------------
            # 1. 实时全透明广播收信日志 (关键需求4：不管是否回复，第一时间呈现)
            # -------------------------------------------------------------
            display_title = f"[群聊: {group_name} | 发送者: {sender_name}]" if is_group else f"[好友: {sender_name}]"
            self.emit_event("message_received", {
                "username": username,
                "sender_name": sender_name,
                "group_name": group_name,
                "is_group": is_group,
                "display_title": display_title,
                "content": msg_body,
                "raw_type": msg_row.get("type", "文本"),
            })

            # -------------------------------------------------------------
            # 群聊管理指令与黑名单风控拦截 (Master踢人 / 黑名单复入自动秒踢)
            # -------------------------------------------------------------
            if is_group:
                grp_cfg = self.config.get_group_config(username, group_name)
                is_admin = grp_cfg.is_admin_or_owner or self.is_self_group_owner(username)

                # 1. 检测黑名单成员在群内发言 -> 自动秒踢
                if grp_cfg.auto_kick_on_rejoin and self.config.is_group_blacklisted(username, user_id=str(group_sender_wxid), user_name=sender_name):
                    if is_admin:
                        self.emit_event("log", {
                            "level": "warning",
                            "message": f"🚨 检测到黑名单成员 @{sender_name} 在群【{group_name}】发言，正在自动执行移出群聊！"
                        })
                        self.kick_group_member(username, sender_name)
                        notice = grp_cfg.rejoin_kick_template.replace("{target}", sender_name)
                        self._send_reply(username, notice)
                        return

                # 2. 检测群系统入群消息：是否有黑名单成员再次加入 -> 自动秒踢
                m_join1 = re.search(r'["“](?P<name>[^"”]+)["”]通过扫描.+?加入群聊', raw_content)
                m_join2 = re.search(r'邀请["“](?P<name>[^"”]+)["”]加入了群聊', raw_content)
                m_join3 = re.search(r'["“](?P<name>[^"”]+)["”]加入了群聊', raw_content)
                m_join = m_join1 or m_join2 or m_join3
                if m_join and grp_cfg.auto_kick_on_rejoin:
                    joined_user = m_join.group("name").strip()
                    if self.config.is_group_blacklisted(username, user_name=joined_user):
                        if is_admin:
                            self.emit_event("log", {
                                "level": "warning",
                                "message": f"🚨 检测到黑名单成员【{joined_user}】再次潜入群聊【{group_name}】，正在自动秒踢！"
                            })
                            self.kick_group_member(username, joined_user)
                            notice = grp_cfg.rejoin_kick_template.replace("{target}", joined_user)
                            self._send_reply(username, notice)
                            return

                # 3. 检测群管理者 (Master) 发送的踢人/拉黑指令
                is_master = self.config.is_group_master(username, str(group_sender_wxid), sender_name)
                if is_master and grp_cfg.masters:
                    kick_kws = [k.strip() for k in grp_cfg.kick_keywords.replace("，", ",").split(",") if k.strip()]
                    kw_pattern = "|".join(sorted([re.escape(k) for k in kick_kws], key=lambda x: -len(x)))
                    m_k1 = re.search(rf'@(?P<target>[^\s\u2005@]+)[\s\u2005]*(?:{kw_pattern})(?:\s*|$|[!！。])', msg_body)
                    m_k2 = re.search(rf'(?:{kw_pattern})[\s\u2005]*@(?P<target>[^\s\u2005@]+)', msg_body)
                    target_match = m_k1 or m_k2

                    if target_match:
                        raw_target = target_match.group("target").strip()
                        if not is_admin:
                            err_msg = f"收到管理者 [{sender_name}] 踢人指令，但当前登录微信在【{group_name}】非群主或管理员，无法移出成员。"
                            self.emit_event("log", {"level": "warning", "message": f"⚠️ {err_msg}"})
                            self._send_reply(username, f"@{sender_name}\u2005当前微信账号在该群非群主或管理员，无踢人权限。")
                            return

                        # 查询被踢成员详情 (wxid 和真实昵称)
                        real_target_name = raw_target
                        target_wxid = ""
                        try:
                            members = self.get_group_members(username)
                            for m_item in members:
                                m_n = m_item.get("nick_name", "")
                                m_r = m_item.get("remark", "")
                                m_u = m_item.get("username", "")
                                if raw_target in (m_n, m_r, m_u) or (m_n and raw_target in m_n):
                                    target_wxid = m_u
                                    real_target_name = m_r or m_n or raw_target
                                    break
                        except Exception:
                            pass

                        self.emit_event("log", {
                            "level": "info",
                            "message": f"🚨 管理者 [{sender_name}] 触发踢人指令：正在将 @{real_target_name} 移出群聊【{group_name}】并加入黑名单..."
                        })

                        # 写入黑名单并持久化
                        self.config.add_to_group_blacklist(
                            chatroom_id=username,
                            username=target_wxid,
                            name=real_target_name,
                            kicked_by=f"{sender_name}({group_sender_wxid})"
                        )
                        self.config.save()

                        # 触发底层微信移出动作
                        ok, kick_res_msg = self.kick_group_member(username, real_target_name)

                        # 群内发送踢人通报（仅当微信真正完成移出时才发送）
                        if ok:
                            notice = grp_cfg.kick_notice_template.replace("{target}", real_target_name)
                            self._send_reply(username, notice)

                        self.emit_event("log", {
                            "level": "success" if ok else "warning",
                            "message": f"✅ 已成功将 @{real_target_name} 移出群聊并拉黑！结果: {kick_res_msg}" if ok else f"⚠️ 已拉黑 @{real_target_name}，但微信UI移出反馈: {kick_res_msg}"
                        })
                        return

            # -------------------------------------------------------------
            # 2. 检查自动回复开关
            # -------------------------------------------------------------
            if not self.auto_reply_enabled:
                # 自动回复未开启时，消息已通过 message_received 事件记录在 UI 实时流中，无需重复输出系统日志
                return

            # -------------------------------------------------------------
            # 3. 过滤规则判定 (白名单、群聊@)
            # -------------------------------------------------------------
            should_reply, is_group, is_at_me, clean_query = self._should_auto_reply(
                username, sender_name, msg_body, has_image=bool(detected_image_path)
            )
            if not should_reply:
                reason = "群聊消息未 @机器人" if (is_group and self.config.targets.group_at_only and not is_at_me) else "未在自动回复白名单中"
                self.emit_event("message_ignored", {
                    "username": username,
                    "sender_name": sender_name,
                    "reason": reason,
                    "content": msg_body,
                })
                self.emit_event("log", {
                    "level": "warning",
                    "message": f"⚠️ {display_title} 消息已忽略 [{reason}]: {msg_body}",
                })
                return

            self.emit_event("log", {
                "level": "info",
                "message": f"⚡ 触发自动回复匹配 -> {display_title} 准备处理: {clean_query}",
            })

            # 会话消息去重防抖 (3 秒内相同联系人相同内容直接忽略，防止重复冲击 LLM)
            with self._lock:
                for past_u, past_q, past_ts in self._recent_incoming_queries:
                    if username == past_u and past_q == clean_query and (time.time() - past_ts < 3.0):
                        self.emit_event("log", {
                            "level": "warning",
                            "message": f"⏳ 忽略 3 秒内重复到达的消息: [{display_title}] {clean_query[:40]}",
                        })
                        return
                self._recent_incoming_queries.append((username, clean_query, time.time()))

            # -------------------------------------------------------------
            # 4. 运行智能体全流程流水线 (LLM理解 -> RAG -> 工具调用 -> 回复生成)
            # -------------------------------------------------------------
            res: PipelineResult = self.pipeline.process(
                chat_id=username,
                sender_name=sender_name,
                content=clean_query,
                is_group=is_group,
                is_at_me=is_at_me,
                image_path=detected_image_path,
                raw_msg_type=raw_type,
            )

            # 广播完整流水线决策链路
            self.emit_event("pipeline_finished", {
                "chat_id": res.chat_id,
                "sender_name": res.sender_name,
                "display_title": display_title,
                "reply_text": res.reply_text,
                "should_send": res.should_send,
                "duration_ms": round(res.duration_ms, 1),
                "steps": [s.__dict__ for s in res.steps] if hasattr(res, "steps") else [],
                "rag_hits_count": len(res.rag_hits),
                "tools_count": len(res.tool_executions),
            })

            # -------------------------------------------------------------
            # 5. 执行微信发送
            # -------------------------------------------------------------
            if res.should_send and res.reply_text:
                self._send_reply(username, res.reply_text)

        except Exception as e:
            import traceback
            self.emit_event("log", {
                "level": "error",
                "message": f"处理接收消息发生异常: {e}\n{traceback.format_exc()}",
            })

    def _ensure_interactive_desktop(self) -> None:
        """激活当前线程到交互桌面，避免后台工作线程找不到可见窗口句柄"""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            h_desk = user32.OpenDesktopW("default", 0, False, 0x01FF)
            if h_desk:
                user32.SetThreadDesktop(h_desk)
        except Exception:
            pass

    def _send_reply(self, target_who: str, reply_text: str) -> None:
        """执行回复发送 (带防刷节流锁与智能名称多候选容错)"""
        with self._lock:
            cooldown = self.config.safety.cooldown_seconds or 1.0
            elapsed = time.time() - self._last_send_ts
            if elapsed < cooldown:
                time.sleep(cooldown - elapsed)

            self._ensure_interactive_desktop()
            primary_name, candidates = self.resolve_chat_target(target_who)

            try:
                from wechatauto.guia import WeChatGUI
                if self._gui is None:
                    self._gui = WeChatGUI()

                # 优先尝试最佳解析名 (如备注名、文件传输助手、群名)
                tried_targets = []
                send_success = False
                last_err = ""

                for candidate in candidates:
                    if not candidate or candidate in tried_targets:
                        continue
                    tried_targets.append(candidate)

                    self.emit_event("log", {
                        "level": "info",
                        "message": f"🚀 正在向 [{candidate}] 发送回复: {reply_text[:60]}...",
                    })

                    resp = self._gui.send_msg(reply_text, candidate)
                    self._last_send_ts = time.time()

                    # 记录本次发出的回复内容，以便拦截后续数据库落库回环
                    now = time.time()
                    clean_reply = reply_text.strip()
                    self._recent_sent_replies.append({
                        "target": target_who,
                        "text": clean_reply,
                        "ts": now,
                    })
                    self._recent_sent_replies.append({
                        "target": candidate,
                        "text": clean_reply,
                        "ts": now,
                    })

                    if resp.is_success:
                        send_success = True
                        self.emit_event("message_sent", {
                            "target": candidate,
                            "text": reply_text,
                            "success": True,
                        })
                        self.emit_event("log", {
                            "level": "success",
                            "message": f"✅ 成功回复 [{candidate}]！",
                        })
                        break
                    else:
                        last_err = resp.get("message", "未知响应")
                        self.emit_event("log", {
                            "level": "warning",
                            "message": f"⚠️ 向 [{candidate}] 发送未确认: {last_err}，尝试候选匹配...",
                        })

                if not send_success:
                    self.emit_event("log", {
                        "level": "error",
                        "message": f"❌ 向 [{target_who}]（尝试过: {tried_targets}）发送失败: {last_err}",
                    })

            except Exception as e:
                self.emit_event("log", {
                    "level": "error",
                    "message": f"调用微信发送异常: {e}",
                })

    def start_listening(self) -> Tuple[bool, str]:
        """启动微信底层监听服务（常驻消息采集）"""
        if self.is_running:
            return True, "消息监听已在运行中"

        try:
            from wechatauto.db import WeChatDB, Listener
            if self._db is None:
                self._db = WeChatDB()

            self._self_info = self._db.get_self_info()
            if not self._self_info or not self._self_info.get("username"):
                return False, "未能识别到已登录的微信客户端，请确认微信 4.x 已在电脑上运行并登录！"

            self._listener = Listener(self._db, interval=1.0)
            self._listener.add_all(self._handle_incoming_message, discover=True)
            self._listener.start()
            self.is_running = True

            self.emit_event("log", {
                "level": "success",
                "message": f"微信实时消息监听已启动！当前登录微信: {self._self_info.get('nick_name')} ({self._self_info.get('username')})",
            })
            return True, "微信监听已成功启动"

        except Exception as e:
            self.is_running = False
            self.emit_event("log", {
                "level": "error",
                "message": f"启动微信监听失败: {e}",
            })
            return False, f"启动失败: {e}"

    def stop_listening(self) -> Tuple[bool, str]:
        """停止微信监听服务"""
        if not self.is_running:
            return True, "监听未运行"

        try:
            if self._listener:
                self._listener.stop()
                self._listener = None
            self.is_running = False
            self.auto_reply_enabled = False
            self.emit_event("log", {
                "level": "info",
                "message": "微信消息监听与自动回复已完全停止",
            })
            return True, "已停止监听"
        except Exception as e:
            return False, f"停止异常: {e}"

    def set_auto_reply(self, enabled: bool) -> Tuple[bool, str]:
        """切换自动回复功能开关"""
        # 确保底层消息监听器已启动
        if not self.is_running:
            ok, msg = self.start_listening()
            if not ok:
                return False, msg

        self.auto_reply_enabled = enabled
        status_text = "开启" if enabled else "暂停"
        self.emit_event("log", {
            "level": "success" if enabled else "warning",
            "message": f"自动回复功能已【{status_text}】",
        })
        return True, f"自动回复已{status_text}"

    def get_latest_chat_stream(self, limit_sessions: int = 25) -> List[Dict[str, Any]]:
        """获取近期各会话的最新消息流（用于界面初始化或手动同步最近收信）"""
        messages = []
        try:
            if self._db is None:
                from wechatauto.db import WeChatDB
                self._db = WeChatDB()

            self._self_info = self._db.get_self_info()
            raw_sessions = self._db.get_sessions(limit=limit_sessions)

            for s in raw_sessions:
                u = s.get("username", "")
                if not u or u in SYSTEM_ACCOUNTS or u.startswith("gh_"):
                    continue

                try:
                    is_group = u.endswith("@chatroom")
                    grp_name = (self._db.get_nickname(u) or u) if is_group else ""

                    session_msgs = self._db.get_messages(u, limit=2)
                    for m in session_msgs:
                        raw_cnt = m.get("content") or ""
                        if isinstance(raw_cnt, bytes):
                            raw_cnt = raw_cnt.decode("utf-8", errors="ignore")

                        # 严格过滤自己发出的消息
                        is_self, _ = self._is_self_message(m, raw_cnt, u)
                        if is_self:
                            continue

                        # 净化展示文本
                        cnt_str = str(raw_cnt).strip()
                        if not cnt_str:
                            continue

                        sender_name = "对方"
                        if is_group:
                            match = re.match(r'^([a-zA-Z0-9_@\.-]+):\s*\n(.*)$', cnt_str, re.DOTALL)
                            if match:
                                gw = match.group(1)
                                cnt_str = match.group(2).strip()
                                sender_name = self._db.get_nickname(gw) or gw
                            else:
                                sender_name = "群成员"
                        else:
                            sender_name = self._db.get_nickname(u) or u

                        if cnt_str.startswith("<?xml") or cnt_str.startswith("<msg") or "<videomsg" in cnt_str or "<img" in cnt_str:
                            cnt_str = "[图片/视频/表情/卡片]"
                        elif "<sysmsg" in cnt_str or cnt_str.startswith("<sysmsg"):
                            cnt_str = "[系统通知]"

                        disp_title = f"[群聊: {grp_name} | 发送者: {sender_name}]" if is_group else f"[好友: {sender_name}]"
                        t_val = m.get("create_time", 0)
                        t_str = time.strftime("%H:%M:%S", time.localtime(t_val)) if t_val else "--:--"

                        messages.append({
                            "time_str": t_str,
                            "sort_seq": m.get("sort_seq", 0),
                            "display_title": disp_title,
                            "content": cnt_str,
                            "username": u,
                            "sender_name": sender_name,
                            "is_group": is_group,
                        })
                except Exception:
                    continue

            messages.sort(key=lambda x: x["sort_seq"])
        except Exception as e:
            self.emit_event("log", {"level": "error", "message": f"同步最新微信消息失败: {e}"})

        return messages
