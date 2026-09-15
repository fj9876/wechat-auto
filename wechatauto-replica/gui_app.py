# -*- coding: utf-8 -*-
"""WeChat-AIAgent 微信智能自动回复桌面客户端 (基于 Python Tkinter)

提供完整的原生桌面 GUI 界面：
1. 运行状态看板与实时彩色消息流 (透明显示所有收信与回复)
2. 纯净通讯录与群聊选择 (无公众号/订阅号，支持搜索与全选)
3. 大模型配置 (支持一键获取上游可用模型与连通性测试)
4. 本地 RAG 知识库管理 (支持原生文件夹选择弹窗与即时测试)
5. 智能体调试沙盒 (无干扰调试全链路决策)
"""
from __future__ import annotations

import os
import sys
import time
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext, simpledialog
from typing import Dict, Any, List, Optional

# 启用 Windows 高 DPI 感知，确保在高分辨率屏幕上字体与控件清晰细腻
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# 项目路径定位
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from agent_core.config import AppConfig, PROMPT_PRESETS
from agent_core.llm_client import LLMClient
from agent_core.rag_engine import RAGEngine
from agent_core.tools import ToolExecutor
from agent_core.pipeline import AgentPipeline, PipelineResult
from agent_core.wechat_bridge import WeChatBridge


class WeChatAIAgentApp:
    """WeChat-AIAgent 原生桌面应用主窗口"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("WeChat-AIAgent 微信智能自动回复助手 v2.0")
        self.root.geometry("1140x820")
        self.root.minsize(980, 680)

        # 核心引擎组件初始化
        self.config = AppConfig.load()
        self.llm_client = LLMClient(self.config.llm)
        self.rag_engine = RAGEngine(self.config.rag)
        self.tools = ToolExecutor
        self.pipeline = AgentPipeline(self.config, self.llm_client, self.rag_engine)
        self.bridge = WeChatBridge(self.config, self.pipeline)
        self.presets: Dict[str, str] = self.config.safety.get_presets()

        # 线程安全事件队列
        self.event_queue: queue.Queue = queue.Queue()
        self.bridge.register_event_listener(self._on_bridge_event)

        # 统计计数器
        self.stat_received = 0
        self.stat_replied = 0
        self.stat_ignored = 0
        self.start_time = time.time()

        # 联系人与群缓存
        self.all_contacts: List[Dict[str, Any]] = []
        self.all_groups: List[Dict[str, Any]] = []
        self.selected_users: set[str] = set(self.config.targets.whitelist_users)
        self.selected_groups: set[str] = set(self.config.targets.whitelist_groups)

        # 样式与主题设置
        self._setup_styles()

        # 构建 UI 界面
        self._create_header_bar()
        self._create_notebook()
        self._create_status_bar()

        # 启动后台事件轮询与心跳
        self.root.after(50, self._process_events)
        self.root.after(1000, self._periodic_heartbeat)

        # 异步加载初始数据 (联系人与微信状态)
        threading.Thread(target=self._async_initial_load, daemon=True).start()

    # -------------------------------------------------------------------------
    # 样式配置
    # -------------------------------------------------------------------------
    def _setup_styles(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # 基础色彩调色板
        self.COLOR_BG = "#f8fafc"
        self.COLOR_CARD = "#ffffff"
        self.COLOR_HEADER = "#0f172a"
        self.COLOR_PRIMARY = "#2563eb"
        self.COLOR_SUCCESS = "#10b981"
        self.COLOR_WARNING = "#f59e0b"
        self.COLOR_DANGER = "#ef4444"
        self.COLOR_TEXT = "#1e293b"
        self.COLOR_MUTED = "#64748b"
        self.COLOR_BORDER = "#cbd5e1"

        self.root.configure(bg=self.COLOR_BG)

        # ttk 控件样式
        self.style.configure("TFrame", background=self.COLOR_BG)
        self.style.configure("Card.TFrame", background=self.COLOR_CARD, relief="flat")
        self.style.configure("TLabel", background=self.COLOR_BG, foreground=self.COLOR_TEXT, font=("Segoe UI", 9))
        self.style.configure("Card.TLabel", background=self.COLOR_CARD, foreground=self.COLOR_TEXT, font=("Segoe UI", 9))
        self.style.configure("Header.TLabel", background=self.COLOR_HEADER, foreground="#ffffff", font=("Segoe UI", 12, "bold"))
        self.style.configure("Muted.TLabel", background=self.COLOR_CARD, foreground=self.COLOR_MUTED, font=("Segoe UI", 8))

        self.style.configure("TNotebook", background=self.COLOR_BG, borderwidth=0)
        self.style.configure("TNotebook.Tab", padding=[16, 8], font=("Segoe UI", 10, "bold"), background="#e2e8f0")
        self.style.map("TNotebook.Tab", background=[("selected", self.COLOR_CARD)], foreground=[("selected", self.COLOR_PRIMARY)])

        self.style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"), padding=[10, 5])
        self.style.configure("Success.TButton", font=("Segoe UI", 9, "bold"), padding=[12, 6])
        self.style.configure("Danger.TButton", font=("Segoe UI", 9, "bold"), padding=[12, 6])

        # Treeview 表格行高与现代样式配置
        self.style.configure(
            "Treeview",
            background="#ffffff",
            foreground=self.COLOR_TEXT,
            fieldbackground="#ffffff",
            font=("Microsoft YaHei UI", 9),
            rowheight=28
        )
        self.style.configure(
            "Treeview.Heading",
            background="#f1f5f9",
            foreground="#334155",
            font=("Microsoft YaHei UI", 9, "bold")
        )
        self.style.map(
            "Treeview",
            background=[("selected", "#bfdbfe")],
            foreground=[("selected", "#1e3a8a")]
        )

    # -------------------------------------------------------------------------
    # 顶部状态与控制栏
    # -------------------------------------------------------------------------
    def _create_header_bar(self):
        header_frame = tk.Frame(self.root, bg=self.COLOR_HEADER, height=64)
        header_frame.pack(fill="x", side="top")

        # 左侧 LOGO 与主标题
        left_box = tk.Frame(header_frame, bg=self.COLOR_HEADER)
        left_box.pack(side="left", padx=16, pady=10)

        lbl_title = tk.Label(
            left_box,
            text="🤖 WeChat-AIAgent 微信智能自动回复助手",
            font=("Microsoft YaHei UI", 13, "bold"),
            bg=self.COLOR_HEADER,
            fg="#ffffff"
        )
        lbl_title.pack(anchor="w")

        self.lbl_wechat_status = tk.Label(
            left_box,
            text="● 正在检测微信状态...",
            font=("Microsoft YaHei UI", 9),
            bg=self.COLOR_HEADER,
            fg="#94a3b8"
        )
        self.lbl_wechat_status.pack(anchor="w")

        # 右侧操作区 (主控制开关与刷新)
        right_box = tk.Frame(header_frame, bg=self.COLOR_HEADER)
        right_box.pack(side="right", padx=16, pady=10)

        self.btn_refresh = tk.Button(
            right_box,
            text="🔄 刷新状态",
            command=self._on_refresh_status_click,
            font=("Microsoft YaHei UI", 9),
            bg="#334155",
            fg="#ffffff",
            activebackground="#475569",
            activeforeground="#ffffff",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2"
        )
        self.btn_refresh.pack(side="left", padx=6)

        self.btn_toggle_autoreply = tk.Button(
            right_box,
            text="▶ 开启自动回复",
            command=self._on_toggle_autoreply_click,
            font=("Microsoft YaHei UI", 10, "bold"),
            bg=self.COLOR_SUCCESS,
            fg="#ffffff",
            activebackground="#059669",
            activeforeground="#ffffff",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2"
        )
        self.btn_toggle_autoreply.pack(side="left", padx=6)

    # -------------------------------------------------------------------------
    # 主体多标签页 Notebook
    # -------------------------------------------------------------------------
    def _create_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=8)

        # Tab 1: 实时运行看板与消息日志
        self.tab_dashboard = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_dashboard, text=" 📊 运行看板与实时日志 ")
        self._build_dashboard_tab()

        # Tab 2: 回复对象配置
        self.tab_targets = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_targets, text=" 👥 回复对象配置 ")
        self._build_targets_tab()

        # Tab 3: 大模型配置
        self.tab_llm = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_llm, text=" 🧠 大模型配置 ")
        self._build_llm_tab()

        # Tab 4: 本地知识库 (RAG)
        self.tab_rag = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_rag, text=" 📚 本地知识库 (RAG) ")
        self._build_rag_tab()

        # Tab 5: 多模态与媒体设置
        self.tab_media = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_media, text=" 🎙️ 多模态与媒体设置 ")
        self._build_media_tab()

        # Tab 6: 在线测试沙盒
        self.tab_sandbox = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_sandbox, text=" 🧪 交互测试沙盒 ")
        self._build_sandbox_tab()

    # -------------------------------------------------------------------------
    # 底部状态栏
    # -------------------------------------------------------------------------
    def _create_status_bar(self):
        status_bar = tk.Frame(self.root, bg="#e2e8f0", height=24)
        status_bar.pack(fill="x", side="bottom")

        self.lbl_status_left = tk.Label(
            status_bar,
            text="就绪 · 本地原生桌面 GUI",
            font=("Segoe UI", 8),
            bg="#e2e8f0",
            fg="#475569"
        )
        self.lbl_status_left.pack(side="left", padx=10)

        self.lbl_status_right = tk.Label(
            status_bar,
            text="微信 4.x 自动化 | LLM: " + (self.config.llm.model_name or "未配置"),
            font=("Segoe UI", 8),
            bg="#e2e8f0",
            fg="#475569"
        )
        self.lbl_status_right.pack(side="right", padx=10)

    # -------------------------------------------------------------------------
    # Tab 1: 实时监控与日志看板
    # -------------------------------------------------------------------------
    def _build_dashboard_tab(self):
        parent = self.tab_dashboard

        # 顶部指标卡片
        metrics_frame = tk.Frame(parent, bg=self.COLOR_BG)
        metrics_frame.pack(fill="x", pady=6)

        def make_card(p, title, value, color):
            card = tk.Frame(p, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
            card.pack(side="left", fill="both", expand=True, padx=4, pady=2)
            tk.Label(card, text=title, font=("Microsoft YaHei UI", 8), bg=self.COLOR_CARD, fg=self.COLOR_MUTED).pack(anchor="w", padx=10, pady=(6, 0))
            lbl_val = tk.Label(card, text=value, font=("Segoe UI", 16, "bold"), bg=self.COLOR_CARD, fg=color)
            lbl_val.pack(anchor="w", padx=10, pady=(0, 6))
            return lbl_val

        self.card_val_received = make_card(metrics_frame, "今日接收消息", "0", self.COLOR_PRIMARY)
        self.card_val_replied = make_card(metrics_frame, "自动成功回复", "0", self.COLOR_SUCCESS)
        self.card_val_ignored = make_card(metrics_frame, "规则过滤/忽略", "0", self.COLOR_WARNING)
        self.card_val_status = make_card(metrics_frame, "自动回复开关", "已暂停", self.COLOR_MUTED)

        # 日志流主区域
        log_container = tk.Frame(parent, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        log_container.pack(fill="both", expand=True, padx=4, pady=4)

        # 日志工具栏
        tool_bar = tk.Frame(log_container, bg="#f1f5f9", height=32)
        tool_bar.pack(fill="x", side="top", padx=1, pady=1)

        tk.Label(tool_bar, text="⚡ 实时微信消息流与智能体决策链路", font=("Microsoft YaHei UI", 9, "bold"), bg="#f1f5f9", fg=self.COLOR_TEXT).pack(side="left", padx=8, pady=4)

        self.var_autoscroll = tk.BooleanVar(value=True)
        chk_scroll = tk.Checkbutton(tool_bar, text="自动滚屏", variable=self.var_autoscroll, bg="#f1f5f9", font=("Microsoft YaHei UI", 8))
        chk_scroll.pack(side="right", padx=6)

        btn_copy = tk.Button(tool_bar, text="📋 复制日志", command=self._on_copy_logs, bg="#e2e8f0", relief="flat", font=("Microsoft YaHei UI", 8), cursor="hand2")
        btn_copy.pack(side="right", padx=4)

        btn_clear = tk.Button(tool_bar, text="🧹 清空日志", command=self._on_clear_logs, bg="#e2e8f0", relief="flat", font=("Microsoft YaHei UI", 8), cursor="hand2")
        btn_clear.pack(side="right", padx=4)

        btn_sync = tk.Button(
            tool_bar,
            text="🔄 同步微信最新消息",
            command=self._on_sync_recent_messages_click,
            bg="#e0e7ff",
            fg="#3730a3",
            activebackground="#c7d2fe",
            relief="flat",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2"
        )
        btn_sync.pack(side="right", padx=6)

        # 彩色日志输出框
        self.txt_logs = scrolledtext.ScrolledText(
            log_container,
            wrap="word",
            bg="#0f172a",
            fg="#f8fafc",
            font=("Consolas", 9),
            insertbackground="#ffffff",
            bd=0
        )
        self.txt_logs.pack(fill="both", expand=True, padx=1, pady=1)

        # 配置日志色彩标签
        self.txt_logs.tag_config("time", foreground="#94a3b8")
        self.txt_logs.tag_config("info", foreground="#38bdf8")
        self.txt_logs.tag_config("received", foreground="#60a5fa", font=("Consolas", 9, "bold"))
        self.txt_logs.tag_config("pipeline", foreground="#c084fc")
        self.txt_logs.tag_config("ai", foreground="#34d399", font=("Consolas", 9, "bold"))
        self.txt_logs.tag_config("sent", foreground="#4ade80", font=("Consolas", 9, "bold"))
        self.txt_logs.tag_config("warning", foreground="#fbbf24")
        self.txt_logs.tag_config("error", foreground="#f87171", font=("Consolas", 9, "bold"))

        # 输出欢迎启动信息
        self._append_log("info", "系统", "WeChat-AIAgent 原生桌面客户端已启动，正在就绪...")

    def _append_log(self, tag: str, prefix: str, message: str):
        now_str = time.strftime("%H:%M:%S")
        self.txt_logs.insert("end", f"[{now_str}] ", "time")
        self.txt_logs.insert("end", f"{prefix} ", tag)
        self.txt_logs.insert("end", f"{message}\n", tag)
        if self.var_autoscroll.get():
            self.txt_logs.see("end")

    def _on_clear_logs(self):
        self.txt_logs.delete("1.0", "end")

    def _on_copy_logs(self):
        text = self.txt_logs.get("1.0", "end")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        messagebox.showinfo("提示", "日志已复制到剪贴板！")

    def _on_sync_recent_messages_click(self):
        """用户手动点击同步微信最新消息"""
        threading.Thread(target=lambda: self._sync_recent_messages_internal(notify=True), daemon=True).start()

    def _sync_recent_messages_internal(self, notify: bool = False):
        """从微信数据库拉取近期活跃会话最新消息并呈现于控制台实时流中"""
        try:
            recent_msgs = self.bridge.get_latest_chat_stream(limit_sessions=30)
            def on_done():
                if recent_msgs:
                    self._append_log("info", "系统", f"已从微信客户端同步近期 {len(recent_msgs)} 条最新往来消息流：")
                    for m in recent_msgs:
                        t_str = m.get("time_str", "--:--")
                        disp = m.get("display_title", "")
                        cnt = m.get("content", "")
                        self.txt_logs.insert("end", f"[{t_str}] ", "time")
                        self.txt_logs.insert("end", f"📨 {disp}: ", "received")
                        self.txt_logs.insert("end", f"{cnt}\n", "received")
                    if self.var_autoscroll.get():
                        self.txt_logs.see("end")
                    self._append_log("info", "系统", "微信实时消息监听服务已就绪，后台正在持续捕获最新消息...")
                else:
                    self._append_log("info", "系统", "已连接微信客户端，未检测到近期新消息。实时监听服务已就绪。")
                if notify:
                    messagebox.showinfo("同步完成", f"已成功从微信客户端同步近期 {len(recent_msgs)} 条最新往来消息！")
            self.dispatch_ui(on_done)
        except Exception as e:
            self.dispatch_ui(self._append_log, "error", "异常", f"同步微信消息流失败: {e}")

    # -------------------------------------------------------------------------
    # Tab 2: 回复对象配置 (好友与群聊)
    # -------------------------------------------------------------------------
    def _build_targets_tab(self):
        parent = self.tab_targets

        paned = tk.PanedWindow(parent, orient="horizontal", bg=self.COLOR_BG, sashwidth=4)
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        # ----------------- 左侧：好友列表 (已排除公众号) -----------------
        left_frame = tk.Frame(paned, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        paned.add(left_frame, minsize=420)

        # 标题栏
        f_header = tk.Frame(left_frame, bg="#f8fafc")
        f_header.pack(fill="x", padx=8, pady=6)
        self.lbl_contacts_header = tk.Label(
            f_header,
            text="👤 通讯录真实好友 (已勾选: 0 / 共 0 人)",
            font=("Microsoft YaHei UI", 10, "bold"),
            bg="#f8fafc",
            fg=self.COLOR_TEXT
        )
        self.lbl_contacts_header.pack(anchor="w")

        # 搜索与快捷操作
        f_actions = tk.Frame(left_frame, bg=self.COLOR_CARD)
        f_actions.pack(fill="x", padx=8, pady=4)

        self.var_search_contact = tk.StringVar()
        self.var_search_contact.trace_add("write", self._on_contact_search_changed)
        ent_search_c = ttk.Entry(f_actions, textvariable=self.var_search_contact, font=("Microsoft YaHei UI", 9))
        ent_search_c.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_select_all_c = ttk.Button(f_actions, text="全选", width=6, command=lambda: self._select_all_contacts(True))
        btn_select_all_c.pack(side="left", padx=2)

        btn_clear_c = ttk.Button(f_actions, text="清空", width=6, command=lambda: self._select_all_contacts(False))
        btn_clear_c.pack(side="left", padx=2)

        btn_filehelper_c = ttk.Button(f_actions, text="仅文件助手", width=11, command=self._select_only_filehelper)
        btn_filehelper_c.pack(side="left", padx=2)

        # 全局私聊开关
        self.var_reply_all_private = tk.BooleanVar(value=self.config.targets.reply_all_private)
        chk_all_private = tk.Checkbutton(
            left_frame,
            text="允许自动回复所有好友私聊 (不限白名单)",
            variable=self.var_reply_all_private,
            bg=self.COLOR_CARD,
            font=("Microsoft YaHei UI", 9)
        )
        chk_all_private.pack(anchor="w", padx=8, pady=2)

        # 好友 Treeview
        c_tree_frame = tk.Frame(left_frame, bg=self.COLOR_CARD)
        c_tree_frame.pack(fill="both", expand=True, padx=8, pady=4)

        columns_c = ("selected", "name", "wxid", "summary")
        self.tree_contacts = ttk.Treeview(c_tree_frame, columns=columns_c, show="headings", selectmode="extended")
        self.tree_contacts.heading("selected", text="勾选状态")
        self.tree_contacts.heading("name", text="姓名 / 备注")
        self.tree_contacts.heading("wxid", text="微信号 / 标识")
        self.tree_contacts.heading("summary", text="最近消息摘要")

        self.tree_contacts.column("selected", width=85, anchor="center")
        self.tree_contacts.column("name", width=135, anchor="w")
        self.tree_contacts.column("wxid", width=125, anchor="w")
        self.tree_contacts.column("summary", width=160, anchor="w")

        # 配置选中行与未选中行的高对比色彩 Tag
        self.tree_contacts.tag_configure("checked", background="#dbeafe", foreground="#1e40af")
        self.tree_contacts.tag_configure("unchecked", background="#ffffff", foreground="#1e293b")

        c_scroll = ttk.Scrollbar(c_tree_frame, orient="vertical", command=self.tree_contacts.yview)
        self.tree_contacts.configure(yscrollcommand=c_scroll.set)
        self.tree_contacts.pack(side="left", fill="both", expand=True)
        c_scroll.pack(side="right", fill="y")

        self.tree_contacts.bind("<ButtonRelease-1>", self._on_contact_tree_click)

        # ----------------- 右侧：微信群聊列表 -----------------
        right_frame = tk.Frame(paned, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        paned.add(right_frame, minsize=420)

        g_header = tk.Frame(right_frame, bg="#f8fafc")
        g_header.pack(fill="x", padx=8, pady=6)
        self.lbl_groups_header = tk.Label(
            g_header,
            text="👥 微信群聊会话 (已勾选: 0 / 共 0 个)",
            font=("Microsoft YaHei UI", 10, "bold"),
            bg="#f8fafc",
            fg=self.COLOR_TEXT
        )
        self.lbl_groups_header.pack(anchor="w")

        g_actions = tk.Frame(right_frame, bg=self.COLOR_CARD)
        g_actions.pack(fill="x", padx=8, pady=4)

        self.var_search_group = tk.StringVar()
        self.var_search_group.trace_add("write", self._on_group_search_changed)
        ent_search_g = ttk.Entry(g_actions, textvariable=self.var_search_group, font=("Microsoft YaHei UI", 9))
        ent_search_g.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_select_all_g = ttk.Button(g_actions, text="全选", width=6, command=lambda: self._select_all_groups(True))
        btn_select_all_g.pack(side="left", padx=2)

        btn_clear_g = ttk.Button(g_actions, text="清空", width=6, command=lambda: self._select_all_groups(False))
        btn_clear_g.pack(side="left", padx=2)

        btn_setting_g = ttk.Button(g_actions, text="⚙️ 群设置", width=9, command=self._on_group_setting_btn_click)
        btn_setting_g.pack(side="left", padx=2)

        # 群聊配置选项
        g_options = tk.Frame(right_frame, bg=self.COLOR_CARD)
        g_options.pack(fill="x", padx=8, pady=2)

        self.var_reply_all_groups = tk.BooleanVar(value=self.config.targets.reply_all_groups)
        chk_all_groups = tk.Checkbutton(g_options, text="允许回复所有群聊", variable=self.var_reply_all_groups, bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 8))
        chk_all_groups.pack(side="left", padx=2)

        self.var_group_at_only = tk.BooleanVar(value=self.config.targets.group_at_only)
        chk_at_only = tk.Checkbutton(g_options, text="仅在被 @ 时才回复 (推荐)", variable=self.var_group_at_only, bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 8, "bold"), fg=self.COLOR_PRIMARY)
        chk_at_only.pack(side="left", padx=8)

        self.var_group_auto_at = tk.BooleanVar(value=self.config.targets.group_auto_at_sender)
        chk_auto_at = tk.Checkbutton(g_options, text="回复时自动 @ 提问者", variable=self.var_group_auto_at, bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 8))
        chk_auto_at.pack(side="left", padx=2)

        # 鼠标右键设置快捷提示
        g_hint_bar = tk.Frame(right_frame, bg=self.COLOR_CARD)
        g_hint_bar.pack(fill="x", padx=8, pady=(0, 2))
        lbl_hint_g = tk.Label(
            g_hint_bar,
            text="💡 提示：在任意群聊名称上【鼠标右键】可弹出【单独设置此群聊】(管理者Master与黑名单)",
            bg=self.COLOR_CARD,
            fg=self.COLOR_PRIMARY,
            font=("Microsoft YaHei UI", 8)
        )
        lbl_hint_g.pack(side="left")

        # 群聊 Treeview
        g_tree_frame = tk.Frame(right_frame, bg=self.COLOR_CARD)
        g_tree_frame.pack(fill="both", expand=True, padx=8, pady=4)

        columns_g = ("selected", "name", "wxid", "summary")
        self.tree_groups = ttk.Treeview(g_tree_frame, columns=columns_g, show="headings", selectmode="extended")
        self.tree_groups.heading("selected", text="勾选状态")
        self.tree_groups.heading("name", text="群名称")
        self.tree_groups.heading("wxid", text="群 ID")
        self.tree_groups.heading("summary", text="最近消息摘要")

        self.tree_groups.column("selected", width=85, anchor="center")
        self.tree_groups.column("name", width=135, anchor="w")
        self.tree_groups.column("wxid", width=125, anchor="w")
        self.tree_groups.column("summary", width=160, anchor="w")

        # 配置群聊选中行与未选中行的高对比色彩 Tag
        self.tree_groups.tag_configure("checked", background="#dbeafe", foreground="#1e40af")
        self.tree_groups.tag_configure("unchecked", background="#ffffff", foreground="#1e293b")

        g_scroll = ttk.Scrollbar(g_tree_frame, orient="vertical", command=self.tree_groups.yview)
        self.tree_groups.configure(yscrollcommand=g_scroll.set)
        self.tree_groups.pack(side="left", fill="both", expand=True)
        g_scroll.pack(side="right", fill="y")

        self.tree_groups.bind("<ButtonRelease-1>", self._on_group_tree_click)
        self.tree_groups.bind("<Button-3>", self._on_group_right_click)
        self.tree_groups.bind("<Double-Button-1>", self._on_group_double_click)

        # 底部保存栏
        btn_save_targets = tk.Button(
            parent,
            text="💾 保存回复对象配置",
            command=self._on_save_targets_click,
            font=("Microsoft YaHei UI", 10, "bold"),
            bg=self.COLOR_PRIMARY,
            fg="#ffffff",
            relief="flat",
            padx=20,
            pady=8,
            cursor="hand2"
        )
        btn_save_targets.pack(side="bottom", pady=6)

    def _render_contacts_tree(self):
        self.tree_contacts.delete(*self.tree_contacts.get_children())
        query = self.var_search_contact.get().strip().lower()

        for c in self.all_contacts:
            u = c["username"]
            n = c["name"]
            r = c.get("remark", "")
            s = c.get("summary", "")

            if query:
                if query not in u.lower() and query not in n.lower() and query not in r.lower():
                    continue

            is_sel = u in self.selected_users or n in self.selected_users
            mark = "✔ [已勾选]" if is_sel else "○ [未选]"
            tag = "checked" if is_sel else "unchecked"
            disp_title = f"{n} ({r})" if r and r != n else n
            self.tree_contacts.insert("", "end", iid=f"c_{u}", values=(mark, disp_title, u, s), tags=(tag,))
        self._update_target_badges()

    def _render_groups_tree(self):
        self.tree_groups.delete(*self.tree_groups.get_children())
        query = self.var_search_group.get().strip().lower()

        for g in self.all_groups:
            u = g["username"]
            n = g["name"]
            s = g.get("summary", "")

            if query:
                if query not in u.lower() and query not in n.lower():
                    continue

            is_sel = u in self.selected_groups or n in self.selected_groups
            mark = "✔ [已勾选]" if is_sel else "○ [未选]"
            tag = "checked" if is_sel else "unchecked"

            # 标识已配置管理者或黑名单的群聊
            disp_name = n
            g_cfg = self.config.groups_config.get(u)
            if g_cfg:
                badges = []
                if g_cfg.masters:
                    badges.append(f"👑{len(g_cfg.masters)}管")
                if g_cfg.blacklist:
                    badges.append(f"⛔{len(g_cfg.blacklist)}黑")
                if badges:
                    disp_name = f"{n} ({' / '.join(badges)})"

            self.tree_groups.insert("", "end", iid=f"g_{u}", values=(mark, disp_name, u, s), tags=(tag,))
        self._update_target_badges()

    def _update_target_badges(self):
        """动态刷新联系人与群聊已勾选数量徽标"""
        c_count = len(self.all_contacts)
        c_sel = len(self.selected_users)
        g_count = len(self.all_groups)
        g_sel = len(self.selected_groups)
        if hasattr(self, "lbl_contacts_header"):
            self.lbl_contacts_header.configure(text=f"👤 通讯录真实好友 (已勾选: {c_sel} / 共 {c_count} 人)")
        if hasattr(self, "lbl_groups_header"):
            self.lbl_groups_header.configure(text=f"👥 微信群聊会话 (已勾选: {g_sel} / 共 {g_count} 个)")

    def _on_contact_search_changed(self, *args):
        self._render_contacts_tree()

    def _on_group_search_changed(self, *args):
        self._render_groups_tree()

    def _on_contact_tree_click(self, event):
        item_id = self.tree_contacts.identify_row(event.y)
        if not item_id or not item_id.startswith("c_"):
            return
        u = item_id[2:]
        if u in self.selected_users:
            self.selected_users.discard(u)
            is_sel = False
        else:
            self.selected_users.add(u)
            is_sel = True

        # 就地更新该行数值与色彩Tag，滚动条位置不发生重置跳动
        item_data = self.tree_contacts.item(item_id)
        vals = list(item_data.get("values", []))
        if vals:
            vals[0] = "✔ [已勾选]" if is_sel else "○ [未选]"
            tag = "checked" if is_sel else "unchecked"
            self.tree_contacts.item(item_id, values=vals, tags=(tag,))
        self._update_target_badges()

    def _on_group_tree_click(self, event):
        item_id = self.tree_groups.identify_row(event.y)
        if not item_id or not item_id.startswith("g_"):
            return
        u = item_id[2:]
        if u in self.selected_groups:
            self.selected_groups.discard(u)
            is_sel = False
        else:
            self.selected_groups.add(u)
            is_sel = True

        # 就地更新该行数值与色彩Tag
        item_data = self.tree_groups.item(item_id)
        vals = list(item_data.get("values", []))
        if vals:
            vals[0] = "✔ [已勾选]" if is_sel else "○ [未选]"
            tag = "checked" if is_sel else "unchecked"
            self.tree_groups.item(item_id, values=vals, tags=(tag,))
        self._update_target_badges()

    def _on_group_right_click(self, event):
        """鼠标右键单击群聊，弹出快捷设置菜单"""
        item_id = self.tree_groups.identify_row(event.y)
        if not item_id or not item_id.startswith("g_"):
            return
        self.tree_groups.selection_set(item_id)
        u = item_id[2:]
        group_name = next((g["name"] for g in self.all_groups if g["username"] == u), u)

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(
            label=f"⚙️ 单独设置此群聊: {group_name[:12]}...",
            command=lambda: self._open_group_settings_dialog(u, group_name),
            font=("Microsoft YaHei UI", 9, "bold")
        )
        menu.add_separator()
        is_sel = u in self.selected_groups
        menu.add_command(
            label="❌ 取消勾选此群自动回复" if is_sel else "✔ 勾选此群开启自动回复",
            command=lambda: self._toggle_group_selection(item_id, u)
        )
        menu.tk_popup(event.x_root, event.y_root)

    def _on_group_double_click(self, event):
        """双击群聊快速打开独立设置"""
        item_id = self.tree_groups.identify_row(event.y)
        if not item_id or not item_id.startswith("g_"):
            return
        u = item_id[2:]
        group_name = next((g["name"] for g in self.all_groups if g["username"] == u), u)
        self._open_group_settings_dialog(u, group_name)

    def _on_group_setting_btn_click(self):
        """点击上方'⚙️ 群设置'按钮打开当前选中群聊的设置"""
        sel = self.tree_groups.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在群聊列表中单击选中一个群聊，或直接在群聊名称上点击鼠标右键！")
            return
        item_id = sel[0]
        if not item_id.startswith("g_"):
            return
        u = item_id[2:]
        group_name = next((g["name"] for g in self.all_groups if g["username"] == u), u)
        self._open_group_settings_dialog(u, group_name)

    def _toggle_group_selection(self, item_id: str, u: str):
        """切换群聊勾选状态并就地刷新颜色"""
        if u in self.selected_groups:
            self.selected_groups.discard(u)
            is_sel = False
        else:
            self.selected_groups.add(u)
            is_sel = True

        item_data = self.tree_groups.item(item_id)
        vals = list(item_data.get("values", []))
        if vals:
            vals[0] = "✔ [已勾选]" if is_sel else "○ [未选]"
            tag = "checked" if is_sel else "unchecked"
            self.tree_groups.item(item_id, values=vals, tags=(tag,))
        self._update_target_badges()

    def _open_group_settings_dialog(self, chatroom_id: str, group_name: str):
        """弹出指定群聊的专属管理配置对话框 (管理者Master、黑名单移出与拉黑、踢人规则)"""
        g_cfg = self.config.get_group_config(chatroom_id, group_name)

        # 检查微信数据库中当前账号是否为群主
        is_detected_owner = self.bridge.is_self_group_owner(chatroom_id)
        if is_detected_owner and not g_cfg.is_admin_or_owner:
            g_cfg.is_admin_or_owner = True

        dlg = tk.Toplevel(self.root)
        dlg.title(f"群聊专属设置 - {group_name}")
        dlg.geometry("820x760")
        dlg.minsize(740, 640)
        dlg.configure(bg=self.COLOR_BG)
        dlg.transient(self.root)
        dlg.grab_set()

        # 本地可编辑副本 (点击保存时持久化)
        working_masters: List[str] = list(g_cfg.masters)
        working_blacklist: List[Dict[str, Any]] = [dict(b) for b in g_cfg.blacklist]

        # 异步/同步获取群成员列表
        member_list = []
        try:
            member_list = self.bridge.get_group_members(chatroom_id)
        except Exception:
            pass

        # 底部保存与取消按钮栏
        bottom_bar = tk.Frame(dlg, bg=self.COLOR_BG, padx=16, pady=12)
        bottom_bar.pack(side="bottom", fill="x")

        # 主滚动区域
        canvas = tk.Canvas(dlg, bg=self.COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(dlg, orient="vertical", command=canvas.yview)
        content_frame = tk.Frame(canvas, bg=self.COLOR_BG)

        content_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas_win = canvas.create_window((0, 0), window=content_frame, anchor="nw", width=785)
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_win, width=event.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_dlg_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        dlg.bind("<MouseWheel>", _on_dlg_mousewheel)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # ---------------------------------------------------------------------
        # 卡片 1: 群聊基本信息与微信管理员权限声明
        # ---------------------------------------------------------------------
        card1 = tk.Frame(content_frame, bg=self.COLOR_CARD, padx=16, pady=12, relief="solid", bd=1)
        card1.pack(fill="x", padx=16, pady=(12, 8))

        lbl_c1_title = tk.Label(
            card1,
            text=f"👥 群聊：{group_name}",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg=self.COLOR_CARD,
            fg=self.COLOR_HEADER
        )
        lbl_c1_title.pack(anchor="w")

        lbl_c1_id = tk.Label(
            card1,
            text=f"群聊微信 ID: {chatroom_id}",
            font=("Consolas", 9),
            bg=self.COLOR_CARD,
            fg=self.COLOR_MUTED
        )
        lbl_c1_id.pack(anchor="w", pady=(2, 6))

        # 微信原生权限检测显示
        if is_detected_owner:
            owner_text = "👑 微信系统检测：当前已登录微信账号【是本群群主】，具备微信官方移出成员权限！"
            owner_fg = "#16a34a"
        else:
            owner_text = "ℹ️ 微信系统检测：当前登录微信在数据库中为普通成员。若您已被设为管理员，请确保有移出群成员权限。"
            owner_fg = "#d97706"

        lbl_owner_status = tk.Label(
            card1,
            text=owner_text,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg=self.COLOR_CARD,
            fg=owner_fg
        )
        lbl_owner_status.pack(anchor="w", pady=3)

        var_is_admin_or_owner = tk.BooleanVar(value=g_cfg.is_admin_or_owner)
        chk_admin = tk.Checkbutton(
            card1,
            text="当前登录微信是本群群主或管理员 (勾选后允许管理者触发踢人/拉黑指令)",
            variable=var_is_admin_or_owner,
            bg=self.COLOR_CARD,
            font=("Microsoft YaHei UI", 9, "bold"),
            fg=self.COLOR_PRIMARY
        )
        chk_admin.pack(anchor="w", pady=(4, 2))

        # ---------------------------------------------------------------------
        # 卡片 2: 群管理者 (Master) 设置
        # ---------------------------------------------------------------------
        card2 = tk.Frame(content_frame, bg=self.COLOR_CARD, padx=16, pady=12, relief="solid", bd=1)
        card2.pack(fill="x", padx=16, pady=8)

        lbl_c2_title = tk.Label(
            card2,
            text="🛡️ 群管理者 (Master) 设置",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg=self.COLOR_CARD,
            fg=self.COLOR_HEADER
        )
        lbl_c2_title.pack(anchor="w")

        lbl_c2_desc = tk.Label(
            card2,
            text="💡 管理者 (Master) 权限：当管理者在群内 @某群成员 并发送【踢/拉黑】等指令时，机器人将自动将其移出群聊并拉黑。\n支持设置一个或多个成员为管理者 (可通过下方群成员下拉框快速挑选，或手动输入微信号/昵称)。",
            font=("Microsoft YaHei UI", 8),
            bg=self.COLOR_CARD,
            fg=self.COLOR_MUTED,
            justify="left"
        )
        lbl_c2_desc.pack(anchor="w", pady=(2, 8))

        m_split_frame = tk.Frame(card2, bg=self.COLOR_CARD)
        m_split_frame.pack(fill="x", pady=4)

        # 左侧：已配置的管理者列表
        m_left = tk.Frame(m_split_frame, bg=self.COLOR_CARD)
        m_left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        tk.Label(m_left, text="已授权管理者列表:", font=("Microsoft YaHei UI", 9, "bold"), bg=self.COLOR_CARD).pack(anchor="w")

        m_list_box_frame = tk.Frame(m_left, bg=self.COLOR_CARD)
        m_list_box_frame.pack(fill="both", expand=True, pady=4)

        listbox_masters = tk.Listbox(m_list_box_frame, height=5, font=("Microsoft YaHei UI", 9), selectmode="single")
        m_list_scroll = ttk.Scrollbar(m_list_box_frame, orient="vertical", command=listbox_masters.yview)
        listbox_masters.configure(yscrollcommand=m_list_scroll.set)
        listbox_masters.pack(side="left", fill="both", expand=True)
        m_list_scroll.pack(side="right", fill="y")

        for m_name in working_masters:
            listbox_masters.insert(tk.END, m_name)

        def remove_master():
            sel = listbox_masters.curselection()
            if not sel:
                messagebox.showwarning("提示", "请先在管理者列表中单击选中要移除的成员！", parent=dlg)
                return
            idx = sel[0]
            val = working_masters[idx]
            working_masters.pop(idx)
            listbox_masters.delete(idx)

        btn_del_master = tk.Button(
            m_left,
            text="➖ 移除选中管理者",
            command=remove_master,
            bg="#fef2f2",
            fg="#dc2626",
            font=("Microsoft YaHei UI", 8, "bold"),
            relief="solid",
            bd=1,
            padx=8,
            pady=3,
            cursor="hand2"
        )
        btn_del_master.pack(anchor="w", pady=4)

        # 右侧：添加新管理者
        m_right = tk.Frame(m_split_frame, bg=self.COLOR_CARD)
        m_right.pack(side="right", fill="both", expand=True, padx=(10, 0))

        tk.Label(m_right, text="添加管理者 (从群成员中选择):", font=("Microsoft YaHei UI", 9, "bold"), bg=self.COLOR_CARD).pack(anchor="w")

        member_options = ["(请选择本群成员...)"]
        member_map = {}
        seen_counts = {}
        for m in member_list:
            u_id = m.get("username", "")
            n_name = (m.get("nick_name") or "").strip()
            remark = (m.get("remark") or "").strip()

            # 存在备注名则直接显示其备注名称，如果没有则显示其昵称，其它的不需要显示
            disp = remark if remark else (n_name or u_id)
            if not disp:
                continue

            if disp in seen_counts:
                seen_counts[disp] += 1
                disp_key = f"{disp} #{seen_counts[disp]}"
            else:
                seen_counts[disp] = 1
                disp_key = disp

            member_options.append(disp_key)
            member_map[disp_key] = {"username": u_id, "name": disp, "nick_name": n_name, "remark": remark}

        var_selected_member = tk.StringVar(value=member_options[0])
        combo_members = ttk.Combobox(
            m_right,
            textvariable=var_selected_member,
            values=member_options,
            state="readonly",
            font=("Microsoft YaHei UI", 9)
        )
        combo_members.pack(fill="x", pady=4)

        tk.Label(m_right, text="或手动输入昵称/备注/微信号:", font=("Microsoft YaHei UI", 8), bg=self.COLOR_CARD, fg=self.COLOR_MUTED).pack(anchor="w", pady=(6, 2))
        var_input_master = tk.StringVar()
        ent_master = ttk.Entry(m_right, textvariable=var_input_master, font=("Microsoft YaHei UI", 9))
        ent_master.pack(fill="x", pady=2)

        def add_master():
            raw_input = var_input_master.get().strip()
            sel_opt = combo_members.get().strip()

            val = ""
            if raw_input:
                val = raw_input
            elif sel_opt and sel_opt in member_map:
                m_info = member_map[sel_opt]
                val = m_info["name"]

            if not val or val.startswith("(请选择"):
                messagebox.showwarning("提示", "请先从下拉列表中选择群成员，或在输入框中输入成员昵称/微信号！", parent=dlg)
                return

            if val in working_masters:
                messagebox.showinfo("提示", f"该成员【{val}】已在管理者列表中！", parent=dlg)
                return

            working_masters.append(val)
            listbox_masters.insert(tk.END, val)
            var_input_master.set("")
            combo_members.set(member_options[0])

        btn_add_master = tk.Button(
            m_right,
            text="➕ 添加为管理者",
            command=add_master,
            bg="#eff6ff",
            fg=self.COLOR_PRIMARY,
            font=("Microsoft YaHei UI", 9, "bold"),
            relief="solid",
            bd=1,
            padx=12,
            pady=4,
            cursor="hand2"
        )
        btn_add_master.pack(anchor="w", pady=6)

        # ---------------------------------------------------------------------
        # 卡片 3: 🚫 本群永久黑名单 (已被踢出或禁止进群成员)
        # ---------------------------------------------------------------------
        card3 = tk.Frame(content_frame, bg=self.COLOR_CARD, padx=16, pady=12, relief="solid", bd=1)
        card3.pack(fill="x", padx=16, pady=8)

        lbl_c3_title = tk.Label(
            card3,
            text="🚫 本群永久黑名单 (进群必踢与违规封锁)",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg=self.COLOR_CARD,
            fg="#dc2626"
        )
        lbl_c3_title.pack(anchor="w")

        lbl_c3_desc = tk.Label(
            card3,
            text="⚠️ 永久封锁机制：被标记为黑名单的成员后续将不允许进入此群聊，即使进入或在群内发言也会被机器人立即再次踢出！\n🔓 解除说明：除非在此界面中将其【移出黑名单】，否则将永久保持封锁状态。移出黑名单后恢复正常，不再被踢。",
            font=("Microsoft YaHei UI", 8),
            bg=self.COLOR_CARD,
            fg=self.COLOR_MUTED,
            justify="left"
        )
        lbl_c3_desc.pack(anchor="w", pady=(2, 6))

        # 黑名单表格
        b_tree_frame = tk.Frame(card3, bg=self.COLOR_CARD)
        b_tree_frame.pack(fill="x", pady=4)

        columns_b = ("name", "wxid", "kick_time", "kicked_by")
        tree_black = ttk.Treeview(b_tree_frame, columns=columns_b, show="headings", height=5, selectmode="extended")
        tree_black.heading("name", text="成员昵称/备注")
        tree_black.heading("wxid", text="微信 ID / 微信号")
        tree_black.heading("kick_time", text="拉黑时间")
        tree_black.heading("kicked_by", text="操作人 / 原因")

        tree_black.column("name", width=140, anchor="w")
        tree_black.column("wxid", width=180, anchor="w")
        tree_black.column("kick_time", width=140, anchor="center")
        tree_black.column("kicked_by", width=160, anchor="w")

        b_scroll = ttk.Scrollbar(b_tree_frame, orient="vertical", command=tree_black.yview)
        tree_black.configure(yscrollcommand=b_scroll.set)
        tree_black.pack(side="left", fill="x", expand=True)
        b_scroll.pack(side="right", fill="y")

        def refresh_blacklist_table():
            for itm in tree_black.get_children():
                tree_black.delete(itm)
            for i, b in enumerate(working_blacklist):
                b_n = b.get("name") or b.get("username") or "未知成员"
                b_u = b.get("username") or "-"
                b_t = b.get("kick_time") or "-"
                b_by = b.get("kicked_by") or "群管理者"
                tree_black.insert("", "end", iid=f"blk_{i}", values=(b_n, b_u, b_t, b_by))

        refresh_blacklist_table()

        # 黑名单操作栏 (关键功能：移出黑名单)
        b_act_bar = tk.Frame(card3, bg=self.COLOR_CARD)
        b_act_bar.pack(fill="x", pady=(6, 2))

        def remove_from_blacklist():
            selected_items = tree_black.selection()
            if not selected_items:
                messagebox.showwarning("提示", "请先在黑名单表格中单击选中要解除拉黑的成员！", parent=dlg)
                return

            indices = []
            names = []
            for item_id in selected_items:
                if item_id.startswith("blk_"):
                    try:
                        idx = int(item_id[4:])
                        indices.append(idx)
                        b_info = working_blacklist[idx]
                        names.append(b_info.get("name") or b_info.get("username") or "该成员")
                    except Exception:
                        pass

            if not indices:
                return

            confirm_msg = (
                f"确定要将以下成员从本群黑名单中【解除拉黑】吗？\n\n"
                f"• " + "\n• ".join(names) + "\n\n"
                f"解除后：\n"
                f"1. 该成员后续进入此群聊时将【不会再被自动踢出】；\n"
                f"2. 该成员在群内发言时也【不会再被秒踢】。"
            )
            if not messagebox.askyesno("解除黑名单确认", confirm_msg, parent=dlg):
                return

            for idx in sorted(indices, reverse=True):
                if 0 <= idx < len(working_blacklist):
                    working_blacklist.pop(idx)

            refresh_blacklist_table()
            messagebox.showinfo("解除成功", "已将选中成员移出黑名单！\n请点击底部【💾 保存此群专属配置】使其立即生效生效。", parent=dlg)

        btn_remove_black = tk.Button(
            b_act_bar,
            text="🔓 移出黑名单 (解除拉黑/允许进群)",
            command=remove_from_blacklist,
            bg="#fef2f2",
            fg="#dc2626",
            font=("Microsoft YaHei UI", 9, "bold"),
            relief="solid",
            bd=1,
            padx=14,
            pady=5,
            cursor="hand2"
        )
        btn_remove_black.pack(side="left", padx=(0, 10))

        def add_to_blacklist_manual():
            add_dlg = tk.Toplevel(dlg)
            add_dlg.title("手动添加黑名单成员")
            add_dlg.geometry("420x240")
            add_dlg.minsize(380, 220)
            add_dlg.configure(bg=self.COLOR_BG)
            add_dlg.transient(dlg)
            add_dlg.grab_set()

            tk.Label(add_dlg, text="成员昵称/备注:", bg=self.COLOR_BG, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=20, pady=(15, 2))
            var_b_name = tk.StringVar()
            ent_b_name = ttk.Entry(add_dlg, textvariable=var_b_name, font=("Microsoft YaHei UI", 9))
            ent_b_name.pack(fill="x", padx=20, pady=2)

            tk.Label(add_dlg, text="微信号/wxid (可选):", bg=self.COLOR_BG, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=20, pady=(8, 2))
            var_b_wxid = tk.StringVar()
            ent_b_wxid = ttk.Entry(add_dlg, textvariable=var_b_wxid, font=("Microsoft YaHei UI", 9))
            ent_b_wxid.pack(fill="x", padx=20, pady=2)

            def do_add_blk():
                name = var_b_name.get().strip()
                wxid = var_b_wxid.get().strip()
                if not name and not wxid:
                    messagebox.showwarning("提示", "成员昵称或微信号至少填写一项！", parent=add_dlg)
                    return
                for b in working_blacklist:
                    if (wxid and b.get("username") == wxid) or (name and b.get("name") == name):
                        messagebox.showinfo("提示", "该成员已在黑名单中！", parent=add_dlg)
                        return
                working_blacklist.append({
                    "username": wxid,
                    "name": name or wxid,
                    "kick_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "kicked_by": "手动添加(GUI)"
                })
                refresh_blacklist_table()
                add_dlg.destroy()

            btn_box = tk.Frame(add_dlg, bg=self.COLOR_BG)
            btn_box.pack(side="bottom", pady=15)
            tk.Button(btn_box, text="确定添加", font=("Microsoft YaHei UI", 9, "bold"), bg=self.COLOR_PRIMARY, fg="#ffffff", padx=16, pady=5, relief="flat", command=do_add_blk).pack(side="left", padx=8)
            tk.Button(btn_box, text="取消", font=("Microsoft YaHei UI", 9), bg="#e2e8f0", fg=self.COLOR_TEXT, padx=12, pady=5, relief="flat", command=add_dlg.destroy).pack(side="left", padx=8)

        btn_add_black = tk.Button(
            b_act_bar,
            text="➕ 手动添加黑名单",
            command=add_to_blacklist_manual,
            bg="#f1f5f9",
            fg=self.COLOR_TEXT,
            font=("Microsoft YaHei UI", 9),
            relief="solid",
            bd=1,
            padx=12,
            pady=5,
            cursor="hand2"
        )
        btn_add_black.pack(side="left", padx=4)

        var_auto_kick = tk.BooleanVar(value=g_cfg.auto_kick_on_rejoin)
        chk_rejoin_kick = tk.Checkbutton(
            card3,
            text="开启黑名单成员再次潜入群聊时自动秒踢 (永久封锁，防止被拉入或扫码复入)",
            variable=var_auto_kick,
            bg=self.COLOR_CARD,
            font=("Microsoft YaHei UI", 9, "bold"),
            fg="#dc2626"
        )
        chk_rejoin_kick.pack(anchor="w", pady=(8, 2))

        # ---------------------------------------------------------------------
        # 卡片 4: 踢人指令与自动通报文案定制
        # ---------------------------------------------------------------------
        card4 = tk.Frame(content_frame, bg=self.COLOR_CARD, padx=16, pady=12, relief="solid", bd=1)
        card4.pack(fill="x", padx=16, pady=(8, 16))

        lbl_c4_title = tk.Label(
            card4,
            text="⚙️ 踢人触发词与通报文案设置",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg=self.COLOR_CARD,
            fg=self.COLOR_HEADER
        )
        lbl_c4_title.pack(anchor="w")

        # 踢人关键词
        tk.Label(card4, text="触发踢人关键词 (逗号分隔):", font=("Microsoft YaHei UI", 9), bg=self.COLOR_CARD).pack(anchor="w", pady=(8, 2))
        var_kick_kws = tk.StringVar(value=g_cfg.kick_keywords)
        ent_kick_kws = ttk.Entry(card4, textvariable=var_kick_kws, font=("Microsoft YaHei UI", 9))
        ent_kick_kws.pack(fill="x", pady=2)
        tk.Label(card4, text="提示: 当管理者在群聊中 @某成员 时，消息包含以上关键词即触发踢出并拉黑 (如: @张三 踢 或 @李四 拉黑)", font=("Microsoft YaHei UI", 8), bg=self.COLOR_CARD, fg=self.COLOR_MUTED).pack(anchor="w")

        # 踢人成功群内通报
        tk.Label(card4, text="移出成员并拉黑后的群内通报文案:", font=("Microsoft YaHei UI", 9), bg=self.COLOR_CARD).pack(anchor="w", pady=(8, 2))
        var_kick_tpl = tk.StringVar(value=g_cfg.kick_notice_template)
        ent_kick_tpl = ttk.Entry(card4, textvariable=var_kick_tpl, font=("Microsoft YaHei UI", 9))
        ent_kick_tpl.pack(fill="x", pady=2)
        tk.Label(card4, text="支持变量: {target} 为被踢成员名称；留空则静默踢出，不在群内发送通报", font=("Microsoft YaHei UI", 8), bg=self.COLOR_CARD, fg=self.COLOR_MUTED).pack(anchor="w")

        # 黑名单复入自动踢群内通报
        tk.Label(card4, text="黑名单成员再次进群自动秒踢通报文案:", font=("Microsoft YaHei UI", 9), bg=self.COLOR_CARD).pack(anchor="w", pady=(8, 2))
        var_rejoin_tpl = tk.StringVar(value=g_cfg.rejoin_kick_template)
        ent_rejoin_tpl = ttk.Entry(card4, textvariable=var_rejoin_tpl, font=("Microsoft YaHei UI", 9))
        ent_rejoin_tpl.pack(fill="x", pady=2)
        tk.Label(card4, text="支持变量: {target} 为进群被踢者名称；留空则静默秒踢", font=("Microsoft YaHei UI", 8), bg=self.COLOR_CARD, fg=self.COLOR_MUTED).pack(anchor="w")

        # ---------------------------------------------------------------------
        # 底部操作按钮
        # ---------------------------------------------------------------------
        def do_save():
            g_cfg.is_admin_or_owner = var_is_admin_or_owner.get()
            g_cfg.masters = list(working_masters)
            g_cfg.blacklist = list(working_blacklist)
            g_cfg.kick_keywords = var_kick_kws.get().strip() or "踢,踢出,拉黑,移出,移出群聊"
            g_cfg.kick_notice_template = var_kick_tpl.get().strip()
            g_cfg.rejoin_kick_template = var_rejoin_tpl.get().strip()
            g_cfg.auto_kick_on_rejoin = var_auto_kick.get()

            self.config.groups_config[chatroom_id] = g_cfg
            self.config.save()

            # 刷新群聊列表的徽标
            self._render_groups_tree()

            messagebox.showinfo(
                "保存成功",
                f"群聊【{group_name}】专属管理配置已保存生效！\n\n"
                f"• 管理者(Master): {len(g_cfg.masters)} 人\n"
                f"• 永久黑名单: {len(g_cfg.blacklist)} 人\n"
                f"• 微信踢人权限: {'已启用' if g_cfg.is_admin_or_owner else '未启用'}",
                parent=dlg
            )
            dlg.destroy()

        btn_save = tk.Button(
            bottom_bar,
            text="💾 保存此群专属配置",
            font=("Microsoft YaHei UI", 10, "bold"),
            bg=self.COLOR_PRIMARY,
            fg="#ffffff",
            relief="flat",
            padx=24,
            pady=8,
            cursor="hand2",
            command=do_save
        )
        btn_save.pack(side="left", padx=(0, 12))

        btn_cancel = tk.Button(
            bottom_bar,
            text="取消",
            font=("Microsoft YaHei UI", 10),
            bg="#e2e8f0",
            fg=self.COLOR_TEXT,
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
            command=dlg.destroy
        )
        btn_cancel.pack(side="left")

    def _select_all_contacts(self, select: bool):
        for c in self.all_contacts:
            u = c["username"]
            if select:
                self.selected_users.add(u)
            else:
                self.selected_users.discard(u)
        self._render_contacts_tree()

    def _select_only_filehelper(self):
        self.selected_users.clear()
        self.selected_users.add("filehelper")
        self._render_contacts_tree()
        messagebox.showinfo("提示", "已切换为【仅文件传输助手】，推荐用于测试！")

    def _select_all_groups(self, select: bool):
        for g in self.all_groups:
            u = g["username"]
            if select:
                self.selected_groups.add(u)
            else:
                self.selected_groups.discard(u)
        self._render_groups_tree()

    def _on_save_targets_click(self):
        self.config.targets.whitelist_users = list(self.selected_users)
        self.config.targets.whitelist_groups = list(self.selected_groups)
        self.config.targets.reply_all_private = self.var_reply_all_private.get()
        self.config.targets.reply_all_groups = self.var_reply_all_groups.get()
        self.config.targets.group_at_only = self.var_group_at_only.get()
        self.config.targets.group_auto_at_sender = self.var_group_auto_at.get()
        self.config.save()
        messagebox.showinfo("成功", f"回复对象配置已成功保存！\n已勾选好友: {len(self.selected_users)} 人\n已勾选群聊: {len(self.selected_groups)} 个")

    # -------------------------------------------------------------------------
    # Tab 3: 大模型配置 (LLM Config)
    # -------------------------------------------------------------------------
    def _build_llm_tab(self):
        parent = self.tab_llm

        canvas = tk.Canvas(parent, bg=self.COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=self.COLOR_BG)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw", width=1100)
        canvas.configure(yscrollcommand=scrollbar.set)

        # 鼠标滚轮绑定
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda _: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # ---------------------------------------------------------------------
        # 卡片 1: 大语言模型连接与推理配置 (LLM API & Connection)
        # ---------------------------------------------------------------------
        card_llm = tk.Frame(scroll_frame, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        card_llm.pack(fill="x", padx=16, pady=(12, 6))

        tk.Label(card_llm, text="⚙️ 大语言模型接口与推理参数 (LLM API & Parameters)", font=("Microsoft YaHei UI", 11, "bold"), bg=self.COLOR_CARD, fg=self.COLOR_TEXT).pack(anchor="w", padx=16, pady=(12, 6))

        grid_f = tk.Frame(card_llm, bg=self.COLOR_CARD)
        grid_f.pack(fill="x", padx=16, pady=6)

        # API 地址
        tk.Label(grid_f, text="API 地址 (Base URL):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=6)
        self.var_api_url = tk.StringVar(value=self.config.llm.api_url or "")
        ent_api_url = ttk.Entry(grid_f, textvariable=self.var_api_url, width=50, font=("Consolas", 9))
        ent_api_url.grid(row=0, column=1, columnspan=2, sticky="we", padx=6, pady=6)

        # API Key
        tk.Label(grid_f, text="API Key (密钥):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=1, column=0, sticky="w", pady=6)
        self.var_api_key = tk.StringVar(value=self.config.llm.api_key or "")
        self.ent_api_key = ttk.Entry(grid_f, textvariable=self.var_api_key, width=42, show="*", font=("Consolas", 9))
        self.ent_api_key.grid(row=1, column=1, sticky="we", padx=6, pady=6)

        self.var_show_key = tk.BooleanVar(value=False)
        btn_show_key = tk.Checkbutton(grid_f, text="显示", variable=self.var_show_key, command=self._toggle_key_visibility, bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 8))
        btn_show_key.grid(row=1, column=2, sticky="w", pady=6)

        # 模型名称与一键获取上游模型
        tk.Label(grid_f, text="模型名称 (Model):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=2, column=0, sticky="w", pady=6)
        self.var_model_name = tk.StringVar(value=self.config.llm.model_name or "")
        self.cb_models = ttk.Combobox(grid_f, textvariable=self.var_model_name, width=36, font=("Consolas", 9))
        self.cb_models["values"] = [self.config.llm.model_name or "DeepSeek-V4-Flash", "DeepSeek-V4-Flash", "deepseek-chat", "deepseek-reasoner", "gpt-4o-mini", "qwen-plus"]
        self.cb_models.grid(row=2, column=1, sticky="we", padx=6, pady=6)

        # 一键获取上游模型按钮
        self.btn_fetch_models = tk.Button(
            grid_f,
            text="🔍 一键获取上游模型",
            command=self._on_fetch_upstream_models_click,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#0284c7",
            fg="#ffffff",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2"
        )
        self.btn_fetch_models.grid(row=2, column=2, sticky="w", padx=6, pady=6)

        # 连通性测试按钮
        self.btn_test_llm = tk.Button(
            grid_f,
            text="⚡ 测试连通性",
            command=self._on_test_llm_connection_click,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#475569",
            fg="#ffffff",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2"
        )
        self.btn_test_llm.grid(row=2, column=3, sticky="w", padx=6, pady=6)

        self.lbl_llm_test_result = tk.Label(grid_f, text="", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 8))
        self.lbl_llm_test_result.grid(row=3, column=1, columnspan=3, sticky="w", padx=6)

        grid_f.columnconfigure(1, weight=1)

        # 推理调节参数 (温度、MaxTokens)
        param_f = tk.Frame(card_llm, bg=self.COLOR_CARD)
        param_f.pack(fill="x", padx=16, pady=(4, 12))

        tk.Label(param_f, text="模型采样温度 (Temperature):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        self.var_temp = tk.DoubleVar(value=self.config.llm.temperature if self.config.llm.temperature is not None else 0.7)
        sp_temp = ttk.Spinbox(param_f, from_=0.0, to=2.0, increment=0.1, textvariable=self.var_temp, width=6)
        sp_temp.grid(row=0, column=1, padx=6)
        tk.Label(param_f, text="(0.0~2.0，建议0.7，值越低回答越严谨规范)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=0, column=2, sticky="w", padx=(0, 20))

        tk.Label(param_f, text="单次生成上限 (Max Tokens):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=3, sticky="w")
        self.var_max_tokens = tk.IntVar(value=self.config.llm.max_tokens or 1500)
        sp_tokens = ttk.Spinbox(param_f, from_=100, to=8192, increment=100, textvariable=self.var_max_tokens, width=8)
        sp_tokens.grid(row=0, column=4, padx=6)
        tk.Label(param_f, text="(单次最大生成Token数)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=0, column=5, sticky="w")

        # ---------------------------------------------------------------------
        # 卡片 2: 系统人设与业务提示词 (System Prompt & Persona)
        # ---------------------------------------------------------------------
        card_prompt = tk.Frame(scroll_frame, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        card_prompt.pack(fill="x", padx=16, pady=6)

        tk.Label(card_prompt, text="🎭 系统人设与业务提示词 (System Prompt & Persona)", font=("Microsoft YaHei UI", 11, "bold"), bg=self.COLOR_CARD, fg=self.COLOR_TEXT).pack(anchor="w", padx=16, pady=(12, 6))

        p_frame = tk.Frame(card_prompt, bg=self.COLOR_CARD)
        p_frame.pack(fill="x", padx=16, pady=4)

        tk.Label(p_frame, text="系统预设人设:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.var_preset = tk.StringVar(value=self.config.safety.preset_name or "通用全能助手")
        preset_names = list(self.presets.keys())
        if self.var_preset.get() not in preset_names and preset_names:
            self.var_preset.set(preset_names[0])

        self.cb_presets = ttk.Combobox(p_frame, textvariable=self.var_preset, values=preset_names, state="readonly", width=18)
        self.cb_presets.pack(side="left", padx=(0, 6))
        self.cb_presets.bind("<<ComboboxSelected>>", self._on_preset_selected)

        btn_add_preset = tk.Button(
            p_frame,
            text="➕ 新增人设",
            command=self._on_add_preset_click,
            bg="#f1f5f9",
            fg=self.COLOR_TEXT,
            activebackground="#e2e8f0",
            relief="flat",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2"
        )
        btn_add_preset.pack(side="left", padx=2)

        btn_update_preset = tk.Button(
            p_frame,
            text="💾 保存为人设模板",
            command=self._on_update_preset_click,
            bg="#f1f5f9",
            fg=self.COLOR_TEXT,
            activebackground="#e2e8f0",
            relief="flat",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2"
        )
        btn_update_preset.pack(side="left", padx=2)

        btn_rename_preset = tk.Button(
            p_frame,
            text="✏️ 重命名",
            command=self._on_rename_preset_click,
            bg="#f1f5f9",
            fg=self.COLOR_TEXT,
            activebackground="#e2e8f0",
            relief="flat",
            font=("Microsoft YaHei UI", 8),
            cursor="hand2"
        )
        btn_rename_preset.pack(side="left", padx=2)

        btn_del_preset = tk.Button(
            p_frame,
            text="🗑️ 删除人设",
            command=self._on_delete_preset_click,
            bg="#fef2f2",
            fg="#dc2626",
            activebackground="#fee2e2",
            relief="flat",
            font=("Microsoft YaHei UI", 8),
            cursor="hand2"
        )
        btn_del_preset.pack(side="left", padx=2)

        tk.Label(card_prompt, text="系统提示词 (System Prompt - 决定微信回复时的角色定位、专业范围与沟通口吻):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=16, pady=(10, 4))
        self.txt_prompt = scrolledtext.ScrolledText(card_prompt, wrap="word", height=5, font=("Microsoft YaHei UI", 9), bd=1, relief="solid")
        self.txt_prompt.pack(fill="x", padx=16, pady=(4, 12))
        self.txt_prompt.insert("1.0", self.config.safety.system_prompt or "")

        # ---------------------------------------------------------------------
        # 卡片 3: 消息安全、业务风控与防刷配置 (Safety & Risk Control)
        # ---------------------------------------------------------------------
        card_safety = tk.Frame(scroll_frame, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        card_safety.pack(fill="x", padx=16, pady=6)

        tk.Label(
            card_safety,
            text="🛡️ 消息安全、业务风控与防刷配置 (Safety & Risk Control)",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT
        ).pack(anchor="w", padx=16, pady=(12, 6))

        # 1. 人工接管与客服风控
        sec1 = tk.LabelFrame(card_safety, text=" 👤 人工接管与客服风控 (Human Handover) ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#1e40af", padx=12, pady=8)
        sec1.pack(fill="x", padx=16, pady=6)

        tk.Label(sec1, text="触发转人工关键词:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w", pady=4)
        self.var_handover_kw = tk.StringVar(value=getattr(self.config.safety, "handover_keyword", "转人工,人工客服,找人工") or "转人工")
        ent_handover_kw = ttk.Entry(sec1, textvariable=self.var_handover_kw, width=42, font=("Microsoft YaHei UI", 9))
        ent_handover_kw.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        tk.Label(sec1, text="(多词用逗号分隔，命中后暂停AI自动回复并转交人工接管)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=0, column=2, sticky="w", padx=6)

        tk.Label(sec1, text="转人工自动回复语:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", pady=4)
        self.var_handover_reply = tk.StringVar(value=getattr(self.config.safety, "handover_reply", "已为您转接人工客服，机器人已暂停自动回复，稍后人工人员将为您服务。") or "")
        ent_handover_reply = ttk.Entry(sec1, textvariable=self.var_handover_reply, width=58, font=("Microsoft YaHei UI", 9))
        ent_handover_reply.grid(row=1, column=1, columnspan=2, sticky="we", padx=6, pady=4)

        tk.Label(sec1, text="解除人工指令关键词:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=2, column=0, sticky="w", pady=4)
        self.var_reset_handover_kw = tk.StringVar(value=getattr(self.config.safety, "reset_handover_keyword", "恢复AI,退出人工,开启AI") or "恢复AI")
        ent_reset_kw = ttk.Entry(sec1, textvariable=self.var_reset_handover_kw, width=42, font=("Microsoft YaHei UI", 9))
        ent_reset_kw.grid(row=2, column=1, sticky="w", padx=6, pady=4)
        tk.Label(sec1, text="(微信发送此指令退出人工模式，重新激活AI自动回复)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=2, column=2, sticky="w", padx=6)

        # 2. 回复修饰与内容规范
        sec2 = tk.LabelFrame(card_safety, text=" 🏷️ 回复修饰与品牌标识 (Format & Branding) ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#0369a1", padx=12, pady=8)
        sec2.pack(fill="x", padx=16, pady=6)

        tk.Label(sec2, text="回复内容前缀 (Prefix):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w", pady=4)
        self.var_reply_prefix = tk.StringVar(value=getattr(self.config.safety, "reply_prefix", "") or "")
        ent_prefix = ttk.Entry(sec2, textvariable=self.var_reply_prefix, width=28, font=("Microsoft YaHei UI", 9))
        ent_prefix.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        tk.Label(sec2, text="(如 [AI助手] 或 🤖，留空不加前缀)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=0, column=2, sticky="w", padx=6)

        tk.Label(sec2, text="回复内容后缀 (Suffix):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", pady=4)
        self.var_reply_suffix = tk.StringVar(value=getattr(self.config.safety, "reply_suffix", "") or "")
        ent_suffix = ttk.Entry(sec2, textvariable=self.var_reply_suffix, width=28, font=("Microsoft YaHei UI", 9))
        ent_suffix.grid(row=1, column=1, sticky="w", padx=6, pady=4)
        tk.Label(sec2, text="(如 \\n(本回复由AI生成)，支持 \\n 换行，留空不加后缀)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=1, column=2, sticky="w", padx=6)

        tk.Label(sec2, text="单条回复最大字数限制:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=2, column=0, sticky="w", pady=4)
        self.var_max_length = tk.IntVar(value=getattr(self.config.safety, "max_reply_length", 0) or 0)
        sp_max_len = ttk.Spinbox(sec2, from_=0, to=3000, increment=50, textvariable=self.var_max_length, width=8)
        sp_max_len.grid(row=2, column=1, sticky="w", padx=6, pady=4)
        tk.Label(sec2, text="(0 表示不截断；超出字数自动截断并附带省略号，防大篇幅消息打扰好友)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=2, column=2, sticky="w", padx=6)

        # 3. 防高频冲击与频率风控
        sec3 = tk.LabelFrame(card_safety, text=" ⚡ 防刷频与频率风控 (Anti-Spam & Rate Limiting) ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#b45309", padx=12, pady=8)
        sec3.pack(fill="x", padx=16, pady=6)

        tk.Label(sec3, text="防刷冷却时间 (秒):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w", pady=4)
        self.var_cooldown = tk.DoubleVar(value=getattr(self.config.safety, "cooldown_seconds", 2.0) or 2.0)
        sp_cool = ttk.Spinbox(sec3, from_=0.5, to=60.0, increment=0.5, textvariable=self.var_cooldown, width=8)
        sp_cool.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        tk.Label(sec3, text="(单会话回复最小间隔，保护微信账号免受高频并发封禁，推荐 1.5~3.0 秒)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=0, column=2, sticky="w", padx=6)

        tk.Label(sec3, text="单会话单日回复上限 (次):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", pady=4)
        self.var_daily_limit = tk.IntVar(value=getattr(self.config.safety, "daily_chat_limit", 0) or 0)
        sp_daily = ttk.Spinbox(sec3, from_=0, to=1000, increment=10, textvariable=self.var_daily_limit, width=8)
        sp_daily.grid(row=1, column=1, sticky="w", padx=6, pady=4)
        tk.Label(sec3, text="(0 表示不限制；达到单日上限后自动停止回复该会话，防止被恶意刷爆Token)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=1, column=2, sticky="w", padx=6)

        # 4. 敏感词合规过滤
        sec4 = tk.LabelFrame(card_safety, text=" 🚫 敏感词合规过滤 (Content Moderation) ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#b91c1c", padx=12, pady=8)
        sec4.pack(fill="x", padx=16, pady=6)

        tk.Label(sec4, text="敏感词/黑名单词库:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w", pady=4)
        self.var_sensitive_words = tk.StringVar(value=getattr(self.config.safety, "sensitive_words", "") or "")
        ent_sensitive_words = ttk.Entry(sec4, textvariable=self.var_sensitive_words, width=42, font=("Microsoft YaHei UI", 9))
        ent_sensitive_words.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        tk.Label(sec4, text="(逗号分隔，如: 违法,涉黄,转账,退款,投诉,微信解封,密码)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=0, column=2, sticky="w", padx=6)

        tk.Label(sec4, text="命中敏感词处置策略:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", pady=4)
        action_raw = getattr(self.config.safety, "sensitive_action", "refuse") or "refuse"
        action_map = {
            "refuse": "婉拒回复 (友好说明)",
            "handover": "转接人工坐席",
            "ignore": "静默忽略 (不回复)"
        }
        self.var_sensitive_action = tk.StringVar(value=action_map.get(action_raw, "婉拒回复 (友好说明)"))
        self.cb_sensitive_action = ttk.Combobox(sec4, textvariable=self.var_sensitive_action, values=list(action_map.values()), state="readonly", width=22)
        self.cb_sensitive_action.grid(row=1, column=1, sticky="w", padx=6, pady=4)
        tk.Label(sec4, text="(命中敏感词时的处理机制)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=1, column=2, sticky="w", padx=6)

        tk.Label(sec4, text="敏感词婉拒回复话术:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=2, column=0, sticky="w", pady=4)
        self.var_sensitive_reply = tk.StringVar(value=getattr(self.config.safety, "sensitive_reply", "抱歉，该话题暂时无法通过AI助手解答，敬请谅解。") or "")
        ent_sensitive_reply = ttk.Entry(sec4, textvariable=self.var_sensitive_reply, width=58, font=("Microsoft YaHei UI", 9))
        ent_sensitive_reply.grid(row=2, column=1, columnspan=2, sticky="we", padx=6, pady=4)

        # 5. 插件扩展与工具能力
        sec5 = tk.LabelFrame(card_safety, text=" 🧩 扩展工具与插件能力 (Function Calling) ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#475569", padx=12, pady=8)
        sec5.pack(fill="x", padx=16, pady=(6, 12))

        self.var_enable_tools = tk.BooleanVar(value=bool(getattr(self.config.safety, "enable_tools", True)))
        chk_tools = tk.Checkbutton(
            sec5,
            text="启用扩展插件与工具调用能力 (允许大模型根据需要自主调用天气查询、计算器、专业分诊等内部函数工具)",
            variable=self.var_enable_tools,
            bg=self.COLOR_CARD,
            font=("Microsoft YaHei UI", 9)
        )
        chk_tools.pack(anchor="w", pady=2)

        # ---------------------------------------------------------------------
        # 底部大尺寸保存主按钮
        # ---------------------------------------------------------------------
        btn_save_llm = tk.Button(
            scroll_frame,
            text="💾 保存大模型与安全风控所有配置",
            command=self._on_save_llm_click,
            font=("Microsoft YaHei UI", 11, "bold"),
            bg=self.COLOR_PRIMARY,
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            relief="flat",
            padx=28,
            pady=10,
            cursor="hand2"
        )
        btn_save_llm.pack(pady=(12, 28))

    def _toggle_key_visibility(self):
        if self.var_show_key.get():
            self.ent_api_key.configure(show="")
        else:
            self.ent_api_key.configure(show="*")

    def _on_preset_selected(self, event=None):
        preset_name = self.var_preset.get().strip()
        if preset_name in self.presets:
            self.txt_prompt.delete("1.0", "end")
            self.txt_prompt.insert("1.0", self.presets[preset_name])

    def _refresh_presets_combobox(self, select_name: str = ""):
        preset_keys = list(self.presets.keys())
        self.cb_presets["values"] = preset_keys
        if select_name and select_name in preset_keys:
            self.var_preset.set(select_name)
        elif preset_keys:
            self.var_preset.set(preset_keys[0])

    def _on_add_preset_click(self):
        """新增预设人设"""
        new_name = simpledialog.askstring("新增人设", "请输入新的人设名称 (例如: 英语陪练助手、小红书文案专家):", parent=self.root)
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        if new_name in self.presets:
            messagebox.showwarning("提示", f"人设【{new_name}】已存在，请换一个名称！")
            return

        prompt_text = self.txt_prompt.get("1.0", "end").strip()
        if not prompt_text:
            prompt_text = f"你是一个专业的【{new_name}】，请用专业、亲切、高效的语气解答微信好友的提问。"
            self.txt_prompt.delete("1.0", "end")
            self.txt_prompt.insert("1.0", prompt_text)

        self.presets[new_name] = prompt_text
        self.config.safety.presets = dict(self.presets)
        self.config.safety.preset_name = new_name
        self.config.safety.system_prompt = prompt_text
        self.config.save()

        self._refresh_presets_combobox(new_name)
        messagebox.showinfo("成功", f"人设【{new_name}】已成功创建并保存！")

    def _on_update_preset_click(self):
        """保存当前提示词修改到选中的人设模板"""
        curr_name = self.var_preset.get().strip()
        if not curr_name:
            messagebox.showwarning("提示", "请先选择需要保存的人设！")
            return
        prompt_text = self.txt_prompt.get("1.0", "end").strip()
        if not prompt_text:
            messagebox.showwarning("提示", "系统提示词不能为空！")
            return

        self.presets[curr_name] = prompt_text
        self.config.safety.presets = dict(self.presets)
        self.config.safety.preset_name = curr_name
        self.config.safety.system_prompt = prompt_text
        self.config.save()
        messagebox.showinfo("成功", f"已成功将当前提示词更新保存至人设【{curr_name}】！")

    def _on_rename_preset_click(self):
        """重命名当前选中的人设"""
        old_name = self.var_preset.get().strip()
        if not old_name:
            messagebox.showwarning("提示", "请先选择需要重命名的人设！")
            return
        new_name = simpledialog.askstring("重命名人设", f"请输入【{old_name}】的新名称:", initialvalue=old_name, parent=self.root)
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        if new_name in self.presets:
            messagebox.showwarning("提示", f"已存在名为【{new_name}】的人设，请使用其他名称！")
            return

        prompt_content = self.presets.pop(old_name, self.txt_prompt.get("1.0", "end").strip())
        self.presets[new_name] = prompt_content
        self.config.safety.presets = dict(self.presets)
        self.config.safety.preset_name = new_name
        self.config.save()

        self._refresh_presets_combobox(new_name)
        messagebox.showinfo("成功", f"人设已成功重命名为【{new_name}】！")

    def _on_delete_preset_click(self):
        """删除当前选中的人设"""
        curr_name = self.var_preset.get().strip()
        if not curr_name:
            return
        if len(self.presets) <= 1:
            messagebox.showwarning("提示", "至少需保留一个人设模板，无法删除最后一个人设！")
            return

        if not messagebox.askyesno("删除确认", f"确定要删除预设人设【{curr_name}】吗？\n删除后不可恢复。"):
            return

        self.presets.pop(curr_name, None)
        remaining_keys = list(self.presets.keys())
        fallback_name = remaining_keys[0]

        self.config.safety.presets = dict(self.presets)
        self.config.safety.preset_name = fallback_name
        self.config.safety.system_prompt = self.presets[fallback_name]
        self.config.save()

        self._refresh_presets_combobox(fallback_name)
        self.txt_prompt.delete("1.0", "end")
        self.txt_prompt.insert("1.0", self.presets[fallback_name])
        messagebox.showinfo("成功", f"人设【{curr_name}】已成功删除！已自动切换至【{fallback_name}】。")

    def _on_fetch_upstream_models_click(self):
        """一键获取上游可用模型"""
        api_url = self.var_api_url.get().strip()
        api_key = self.var_api_key.get().strip()

        if not api_url:
            messagebox.showwarning("提示", "请先输入 API 地址！")
            return

        self.btn_fetch_models.configure(text="⏳ 获取中...", state="disabled")
        self.lbl_llm_test_result.configure(text="正在从上游服务端拉取模型清单...", fg=self.COLOR_MUTED)

        def worker():
            try:
                ok, model_list, msg = self.llm_client.get_models(api_url=api_url, api_key=api_key)
                def on_done():
                    self.btn_fetch_models.configure(text="🔍 一键获取上游模型", state="normal")
                    if ok and model_list:
                        self.cb_models["values"] = model_list
                        # 如果当前选中的模型不在列表中，自动选中第一个
                        if self.var_model_name.get() not in model_list:
                            self.var_model_name.set(model_list[0])
                        self.lbl_llm_test_result.configure(text=f"✅ 成功获取 {len(model_list)} 个可用模型！", fg=self.COLOR_SUCCESS)
                        messagebox.showinfo("成功", f"成功拉取到 {len(model_list)} 个上游可用大模型！\n已更新下拉列表。")
                    else:
                        self.lbl_llm_test_result.configure(text=f"⚠️ {msg}", fg=self.COLOR_WARNING)
                        messagebox.showwarning("提示", f"未能获取到模型列表:\n{msg}")
                self.dispatch_ui(on_done)
            except Exception as e:
                def on_err():
                    self.btn_fetch_models.configure(text="🔍 一键获取上游模型", state="normal")
                    self.lbl_llm_test_result.configure(text=f"❌ 获取失败: {e}", fg=self.COLOR_DANGER)
                    messagebox.showerror("获取失败", f"无法拉取上游模型列表:\n{e}")
                self.dispatch_ui(on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_llm_connection_click(self):
        """测试大模型连通性"""
        api_url = self.var_api_url.get().strip()
        api_key = self.var_api_key.get().strip()
        model_name = self.var_model_name.get().strip()

        if not api_url or not model_name:
            messagebox.showwarning("提示", "请填写完整的 API 地址和模型名称！")
            return

        self.btn_test_llm.configure(text="⚡ 测试中...", state="disabled")
        self.lbl_llm_test_result.configure(text="正在向模型发送探针请求...", fg=self.COLOR_MUTED)

        def worker():
            t0 = time.time()
            ok, msg, elapsed = self.llm_client.test_connection(api_url=api_url, api_key=api_key, model_name=model_name)
            latency_ms = int(elapsed) if elapsed else int((time.time() - t0) * 1000)

            def on_done():
                self.btn_test_llm.configure(text="⚡ 测试连通性", state="normal")
                if ok:
                    self.lbl_llm_test_result.configure(text=f"✅ 连通正常！响应耗时: {latency_ms}ms · 模型: {model_name}", fg=self.COLOR_SUCCESS)
                    messagebox.showinfo("连通测试成功", f"恭喜！大模型连接畅通无阻！\n耗时: {latency_ms} ms\n响应: {msg}")
                else:
                    self.lbl_llm_test_result.configure(text=f"❌ 连接失败: {msg}", fg=self.COLOR_DANGER)
                    messagebox.showerror("连通测试失败", f"连接大模型出现异常:\n{msg}")
            self.dispatch_ui(on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_save_llm_click(self):
        # 1. 保存 LLM 连接与推理参数
        self.config.llm.api_url = self.var_api_url.get().strip()
        self.config.llm.api_key = self.var_api_key.get().strip()
        self.config.llm.model_name = self.var_model_name.get().strip()
        self.config.llm.temperature = float(self.var_temp.get())
        self.config.llm.max_tokens = int(self.var_max_tokens.get())
        
        # 2. 保存人设与系统提示词
        curr_preset = self.var_preset.get().strip()
        curr_prompt = self.txt_prompt.get("1.0", "end").strip()
        self.config.safety.preset_name = curr_preset
        self.config.safety.system_prompt = curr_prompt
        if curr_preset:
            self.presets[curr_preset] = curr_prompt
            self.config.safety.presets = dict(self.presets)

        # 3. 保存安全与风控配置
        self.config.safety.handover_keyword = self.var_handover_kw.get().strip()
        self.config.safety.handover_reply = self.var_handover_reply.get().strip()
        self.config.safety.reset_handover_keyword = self.var_reset_handover_kw.get().strip()

        # 处理用户输入的前后缀换行符转义
        prefix_val = self.var_reply_prefix.get()
        suffix_val = self.var_reply_suffix.get()
        self.config.safety.reply_prefix = prefix_val.replace("\\n", "\n")
        self.config.safety.reply_suffix = suffix_val.replace("\\n", "\n")
        self.config.safety.max_reply_length = int(self.var_max_length.get())

        self.config.safety.cooldown_seconds = float(self.var_cooldown.get())
        self.config.safety.daily_chat_limit = int(self.var_daily_limit.get())

        self.config.safety.sensitive_words = self.var_sensitive_words.get().strip()
        action_rev_map = {
            "婉拒回复 (友好说明)": "refuse",
            "转接人工坐席": "handover",
            "静默忽略 (不回复)": "ignore"
        }
        self.config.safety.sensitive_action = action_rev_map.get(self.var_sensitive_action.get(), "refuse")
        self.config.safety.sensitive_reply = self.var_sensitive_reply.get().strip()
        self.config.safety.enable_tools = bool(self.var_enable_tools.get())

        # 4. 持久化与热重载
        self.config.save()
        self.llm_client.update_config(self.config.llm)
        self.lbl_status_right.configure(text="微信 4.x 自动化 | LLM: " + (self.config.llm.model_name or "未配置"))

        summary = (
            f"✅ 大模型与安全风控所有配置已成功保存并立即生效！\n\n"
            f"• 当前大模型: {self.config.llm.model_name or '未配置'}\n"
            f"• 当前人设模板: 【{curr_preset or '未命名'}】\n"
            f"• 转人工关键词: {self.config.safety.handover_keyword or '未配置'}\n"
            f"• 防刷冷却时间: {self.config.safety.cooldown_seconds} 秒\n"
            f"• 单会话日限频: {'无限制' if self.config.safety.daily_chat_limit == 0 else f'{self.config.safety.daily_chat_limit} 次/天'}\n"
            f"• 敏感词合规过滤: {'已启用 (' + self.config.safety.sensitive_action + ')' if self.config.safety.sensitive_words else '未设置'}\n"
            f"• 回复前缀/后缀: {'已启用' if (prefix_val or suffix_val) else '未启用'}\n"
            f"• 工具调用扩展: {'已开启' if self.config.safety.enable_tools else '已禁用'}"
        )
        messagebox.showinfo("配置保存成功", summary)

    # -------------------------------------------------------------------------
    # Tab 4: 本地知识库 (RAG)
    # -------------------------------------------------------------------------
    def _build_rag_tab(self):
        parent = self.tab_rag

        card = tk.Frame(parent, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        card.pack(fill="x", padx=16, pady=12)

        tk.Label(card, text="📚 本地 RAG 知识库检索增强设置", font=("Microsoft YaHei UI", 11, "bold"), bg=self.COLOR_CARD, fg=self.COLOR_TEXT).pack(anchor="w", padx=16, pady=(12, 6))

        # 启用开关
        self.var_rag_enabled = tk.BooleanVar(value=self.config.rag.enabled)
        chk_rag = tk.Checkbutton(card, text="启用本地 RAG 知识库功能 (知识库文档将参与大模型推理补充)", variable=self.var_rag_enabled, bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg=self.COLOR_PRIMARY)
        chk_rag.pack(anchor="w", padx=16, pady=4)

        # 文件夹选择区域
        f_dir = tk.Frame(card, bg=self.COLOR_CARD)
        f_dir.pack(fill="x", padx=16, pady=8)

        tk.Label(f_dir, text="知识库本地文件夹:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        self.var_rag_path = tk.StringVar(value=self.config.rag.kb_folder_path or "")
        ent_rag_path = ttk.Entry(f_dir, textvariable=self.var_rag_path, width=50, font=("Segoe UI", 9))
        ent_rag_path.pack(side="left", fill="x", expand=True, padx=8)

        btn_browse = tk.Button(
            f_dir,
            text="📂 选择本地文件夹",
            command=self._on_browse_rag_folder,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#e2e8f0",
            fg=self.COLOR_TEXT,
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2"
        )
        btn_browse.pack(side="left", padx=4)

        # 操作与统计条
        f_rag_ops = tk.Frame(card, bg=self.COLOR_CARD)
        f_rag_ops.pack(fill="x", padx=16, pady=6)

        self.btn_scan_docs = ttk.Button(f_rag_ops, text="🔍 扫描并查看文档", command=self._on_scan_docs_click)
        self.btn_scan_docs.pack(side="left", padx=(0, 6))

        self.btn_build_index = tk.Button(
            f_rag_ops,
            text="⚡ 建立/更新本地索引",
            command=self._on_build_rag_index_click,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg=self.COLOR_PRIMARY,
            fg="#ffffff",
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2"
        )
        self.btn_build_index.pack(side="left", padx=6)

        self.lbl_rag_status = tk.Label(f_rag_ops, text="当前知识库状态: 未建立索引", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9), fg=self.COLOR_MUTED)
        self.lbl_rag_status.pack(side="left", padx=12)

        # 知识库文档列表
        tk.Label(card, text="扫描到的文档列表:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=16, pady=(8, 2))
        self.tree_docs = ttk.Treeview(card, columns=("filename", "size", "ext"), show="headings", height=5)
        self.tree_docs.heading("filename", text="文件名称")
        self.tree_docs.heading("size", text="大小")
        self.tree_docs.heading("ext", text="格式")
        self.tree_docs.column("filename", width=450, anchor="w")
        self.tree_docs.column("size", width=100, anchor="center")
        self.tree_docs.column("ext", width=80, anchor="center")
        self.tree_docs.pack(fill="x", padx=16, pady=4)

        # 检索测试区
        ttk.Separator(card, orient="horizontal").pack(fill="x", padx=16, pady=10)
        tk.Label(card, text="🔍 知识库检索即时测试 (验证相关切片命中效果):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=16, pady=(4, 2))

        f_test = tk.Frame(card, bg=self.COLOR_CARD)
        f_test.pack(fill="x", padx=16, pady=4)

        self.var_rag_query = tk.StringVar()
        ent_query = ttk.Entry(f_test, textvariable=self.var_rag_query, width=50, font=("Microsoft YaHei UI", 9))
        ent_query.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_test_query = ttk.Button(f_test, text="🔍 检索测试", command=self._on_test_rag_query_click)
        btn_test_query.pack(side="left")

        self.txt_rag_results = scrolledtext.ScrolledText(card, wrap="word", height=5, font=("Microsoft YaHei UI", 9), bd=1, relief="solid")
        self.txt_rag_results.pack(fill="x", padx=16, pady=6)

        # 保存按钮
        btn_save_rag = tk.Button(
            card,
            text="💾 保存知识库配置",
            command=self._on_save_rag_click,
            font=("Microsoft YaHei UI", 10, "bold"),
            bg=self.COLOR_PRIMARY,
            fg="#ffffff",
            relief="flat",
            padx=20,
            pady=8,
            cursor="hand2"
        )
        btn_save_rag.pack(pady=12)

    def _on_browse_rag_folder(self):
        """原生 Windows 文件夹选择弹窗"""
        selected_dir = filedialog.askdirectory(
            title="选择本地知识库文件夹 (支持 .txt, .md, .pdf, .docx, .csv)",
            initialdir=self.var_rag_path.get() or BASE_DIR
        )
        if selected_dir:
            self.var_rag_path.set(selected_dir)
            self._on_scan_docs_click()

    def _on_scan_docs_click(self):
        folder = self.var_rag_path.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("提示", "请先选择有效的知识库文件夹路径！")
            return

        self.tree_docs.delete(*self.tree_docs.get_children())
        valid_exts = {".txt", ".md", ".pdf", ".docx", ".csv", ".json"}
        total_files = 0

        for root_dir, _, files in os.walk(folder):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in valid_exts:
                    full_p = os.path.join(root_dir, file)
                    rel_p = os.path.relpath(full_p, folder)
                    size_kb = round(os.path.getsize(full_p) / 1024, 1)
                    self.tree_docs.insert("", "end", values=(rel_p, f"{size_kb} KB", ext))
                    total_files += 1

        self.lbl_rag_status.configure(text=f"扫描完毕：共找到 {total_files} 个有效文档")

    def _on_build_rag_index_click(self):
        folder = self.var_rag_path.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("提示", "请先选择有效的知识库文件夹！")
            return

        self.btn_build_index.configure(text="⚡ 索引构建中...", state="disabled")
        self.lbl_rag_status.configure(text="正在读取并构建 BM25 索引，请稍候...", fg=self.COLOR_MUTED)

        def worker():
            try:
                self.config.rag.kb_folder_path = folder
                self.config.rag.enabled = True
                self.rag_engine.reload_config(self.config.rag)
                docs_count = len(self.rag_engine.chunks)
                def on_done():
                    self.btn_build_index.configure(text="⚡ 建立/更新本地索引", state="normal")
                    self.lbl_rag_status.configure(text=f"✅ 索引就绪：共 {docs_count} 个切片片段", fg=self.COLOR_SUCCESS)
                    messagebox.showinfo("成功", f"知识库索引构建完成！\n共切分为 {docs_count} 个知识切片。")
                self.dispatch_ui(on_done)
            except Exception as e:
                def on_err():
                    self.btn_build_index.configure(text="⚡ 建立/更新本地索引", state="normal")
                    self.lbl_rag_status.configure(text=f"❌ 构建失败: {e}", fg=self.COLOR_DANGER)
                    messagebox.showerror("构建失败", f"构建本地索引出现异常:\n{e}")
                self.dispatch_ui(on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_rag_query_click(self):
        query = self.var_rag_query.get().strip()
        if not query:
            messagebox.showwarning("提示", "请输入测试查询语句！")
            return

        hits = self.rag_engine.search(query, top_k=3)
        self.txt_rag_results.delete("1.0", "end")
        if not hits:
            self.txt_rag_results.insert("1.0", "未检索到匹配的知识库切片（可能相似度低于阈值或未建立索引）。")
        else:
            out_lines = []
            for i, h in enumerate(hits, 1):
                out_lines.append(f"【命中 {i}】相似度分数: {round(h.get('score', 0), 3)} | 来源: {h.get('metadata', {}).get('source', '未知')}\n{h.get('text', '')}\n")
            self.txt_rag_results.insert("1.0", "\n".join(out_lines))

    def _on_save_rag_click(self):
        self.config.rag.enabled = self.var_rag_enabled.get()
        self.config.rag.kb_folder_path = self.var_rag_path.get().strip()
        self.config.save()
        self.rag_engine.reload_config(self.config.rag)
        messagebox.showinfo("成功", "本地 RAG 知识库配置已成功保存！")

    # -------------------------------------------------------------------------
    # Tab 5: 多模态与媒体设置 (Multimodal & Media Settings)
    # -------------------------------------------------------------------------
    def _build_media_tab(self):
        parent = self.tab_media

        canvas = tk.Canvas(parent, bg=self.COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=self.COLOR_BG)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw", width=1100)
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda _: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 顶部操作栏
        top_bar = tk.Frame(scroll_frame, bg=self.COLOR_BG)
        top_bar.pack(fill="x", padx=16, pady=(12, 6))

        tk.Label(
            top_bar,
            text="🎙️ 微信语音识别 (ASR) 与 🖼️ 多模态图片理解 (Vision/OCR) 设置",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg=self.COLOR_BG,
            fg=self.COLOR_TEXT
        ).pack(side="left")

        btn_save_top = tk.Button(
            top_bar,
            text="💾 保存多模态设置",
            command=self._on_save_media_config_click,
            font=("Microsoft YaHei UI", 10, "bold"),
            bg=self.COLOR_PRIMARY,
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2"
        )
        btn_save_top.pack(side="right")

        # ---------------------------------------------------------------------
        # 卡片 1: 微信语音识别设置 (Voice ASR) 与音频测试
        # ---------------------------------------------------------------------
        card_voice = tk.Frame(scroll_frame, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        card_voice.pack(fill="x", padx=16, pady=6)

        tk.Label(card_voice, text="🎙️ 微信语音识别设置 (Voice ASR) 与测试", font=("Microsoft YaHei UI", 11, "bold"), bg=self.COLOR_CARD, fg=self.COLOR_TEXT).pack(anchor="w", padx=16, pady=(12, 6))

        # 启用开关
        self.var_voice_enabled = tk.BooleanVar(value=getattr(self.config.voice, "enabled", True))
        chk_voice = tk.Checkbutton(
            card_voice,
            text="启用微信语音识别 (收到微信语音消息时自动从底层提取 SILK 格式转写为文本并送入智能体回复)",
            variable=self.var_voice_enabled,
            bg=self.COLOR_CARD,
            font=("Microsoft YaHei UI", 9, "bold"),
            fg=self.COLOR_PRIMARY
        )
        chk_voice.pack(anchor="w", padx=16, pady=4)

        grid_v = tk.Frame(card_voice, bg=self.COLOR_CARD)
        grid_v.pack(fill="x", padx=16, pady=6)

        # 引擎选择
        tk.Label(grid_v, text="语音识别引擎:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=6)
        curr_eng = getattr(self.config.voice, "engine", "local")
        eng_display = "local (本地 faster-whisper [离线·极速·无需API])" if curr_eng != "cloud" else "cloud (在线云端 Whisper 接口 [兼容OpenAI])"
        self.var_voice_engine = tk.StringVar(value=eng_display)
        self.cb_voice_engine = ttk.Combobox(
            grid_v,
            textvariable=self.var_voice_engine,
            values=[
                "local (本地 faster-whisper [离线·极速·无需API])",
                "cloud (在线云端 Whisper 接口 [兼容OpenAI])"
            ],
            state="readonly",
            width=48,
            font=("Microsoft YaHei UI", 9)
        )
        self.cb_voice_engine.grid(row=0, column=1, columnspan=2, sticky="w", padx=6, pady=6)
        self.cb_voice_engine.bind("<<ComboboxSelected>>", self._on_voice_engine_changed)

        # 本地配置容器
        self.f_voice_local = tk.Frame(card_voice, bg=self.COLOR_CARD)
        self.f_voice_local.pack(fill="x", padx=16, pady=4)

        tk.Label(self.f_voice_local, text="本地 Whisper 模型规格:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w", pady=4)
        curr_m = getattr(self.config.voice, "whisper_model", "base") or "base"
        model_map = {
            "tiny": "tiny (极速 ~75MB)",
            "base": "base (推荐 ~145MB 速度与准确平衡)",
            "small": "small (~480MB 高精度)",
            "medium": "medium (~1.5GB 专业级)",
            "large-v3": "large-v3 (高显存需求)"
        }
        self.var_voice_model = tk.StringVar(value=model_map.get(curr_m, f"{curr_m}"))
        self.cb_voice_model = ttk.Combobox(
            self.f_voice_local,
            textvariable=self.var_voice_model,
            values=list(model_map.values()),
            state="readonly",
            width=36,
            font=("Microsoft YaHei UI", 9)
        )
        self.cb_voice_model.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        self.cb_voice_model.bind("<<ComboboxSelected>>", lambda e: self._update_model_status_label())

        self.lbl_voice_model_status = tk.Label(self.f_voice_local, text="", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 8, "bold"))
        self.lbl_voice_model_status.grid(row=1, column=1, sticky="w", padx=6, pady=(0, 4))
        self._update_model_status_label()

        tk.Label(self.f_voice_local, text="推理硬件设备:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=0, column=2, sticky="w", padx=(16, 0), pady=4)
        curr_dev = getattr(self.config.voice, "whisper_device", "auto") or "auto"
        dev_map = {
            "auto": "auto (自动检测：优先CUDA，无显卡自动CPU)",
            "cpu": "cpu (全兼容免显卡运行)",
            "cuda": "cuda (NVIDIA 独立显卡加速)"
        }
        self.var_voice_device = tk.StringVar(value=dev_map.get(curr_dev, f"{curr_dev}"))
        self.cb_voice_device = ttk.Combobox(
            self.f_voice_local,
            textvariable=self.var_voice_device,
            values=list(dev_map.values()),
            state="readonly",
            width=36,
            font=("Microsoft YaHei UI", 9)
        )
        self.cb_voice_device.grid(row=0, column=3, sticky="w", padx=6, pady=4)

        # 云端配置容器
        self.f_voice_cloud = tk.Frame(card_voice, bg=self.COLOR_CARD)
        tk.Label(self.f_voice_cloud, text="云端 ASR API Base URL:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w", pady=4)
        self.var_voice_cloud_url = tk.StringVar(value=getattr(self.config.voice, "cloud_api_url", "https://api.openai.com/v1") or "https://api.openai.com/v1")
        ttk.Entry(self.f_voice_cloud, textvariable=self.var_voice_cloud_url, width=42, font=("Consolas", 9)).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        tk.Label(self.f_voice_cloud, text="API Key:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=0, column=2, sticky="w", padx=(10, 0), pady=4)
        self.var_voice_cloud_key = tk.StringVar(value=getattr(self.config.voice, "cloud_api_key", "") or "")
        ttk.Entry(self.f_voice_cloud, textvariable=self.var_voice_cloud_key, width=30, show="*", font=("Consolas", 9)).grid(row=0, column=3, sticky="w", padx=6, pady=4)

        tk.Label(self.f_voice_cloud, text="云端模型名称:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", pady=4)
        self.var_voice_cloud_model = tk.StringVar(value=getattr(self.config.voice, "cloud_model_name", "whisper-1") or "whisper-1")
        ttk.Entry(self.f_voice_cloud, textvariable=self.var_voice_cloud_model, width=30, font=("Consolas", 9)).grid(row=1, column=1, sticky="w", padx=6, pady=4)

        if curr_eng == "cloud":
            self.f_voice_local.pack_forget()
            self.f_voice_cloud.pack(fill="x", padx=16, pady=4)

        # 语音转写测试工具沙盒
        lf_vtest = tk.LabelFrame(card_voice, text=" 🎵 音频文件选择与转写测试工具 ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#0284c7", padx=12, pady=8)
        lf_vtest.pack(fill="x", padx=16, pady=(10, 12))

        f_vt_in = tk.Frame(lf_vtest, bg=self.COLOR_CARD)
        f_vt_in.pack(fill="x", pady=4)

        tk.Label(f_vt_in, text="测试音频文件路径:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.var_voice_test_path = tk.StringVar(value="")
        ttk.Entry(f_vt_in, textvariable=self.var_voice_test_path, width=54, font=("Consolas", 9)).pack(side="left", padx=6, fill="x", expand=True)

        btn_browse_audio = tk.Button(
            f_vt_in,
            text="📂 弹窗选择音频文件",
            command=self._on_browse_audio_test,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#f1f5f9",
            fg=self.COLOR_TEXT,
            relief="flat",
            padx=10,
            pady=3,
            cursor="hand2"
        )
        btn_browse_audio.pack(side="left", padx=4)

        self.btn_run_voice_test = tk.Button(
            f_vt_in,
            text="⚡ 开始测试转写",
            command=self._on_run_audio_test,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg=self.COLOR_PRIMARY,
            fg="#ffffff",
            relief="flat",
            padx=12,
            pady=3,
            cursor="hand2"
        )
        self.btn_run_voice_test.pack(side="left", padx=4)

        tk.Label(lf_vtest, text="音频转写输出文本与用时反馈:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 8, "bold"), fg=self.COLOR_MUTED).pack(anchor="w", pady=(6, 2))
        self.txt_voice_test_result = scrolledtext.ScrolledText(lf_vtest, wrap="word", height=4, font=("Microsoft YaHei UI", 9), bd=1, relief="solid")
        self.txt_voice_test_result.pack(fill="x", pady=2)
        self.txt_voice_test_result.insert("1.0", "提示：点击上方【📂 弹窗选择音频文件】选取微信 .silk、.wav、.mp3 等音频文件，再点击【⚡ 开始测试转写】即可即时测试识别效果。")

        # ---------------------------------------------------------------------
        # 卡片 2: 微信图片识别设置 (Vision & OCR) 与测试
        # ---------------------------------------------------------------------
        card_image = tk.Frame(scroll_frame, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        card_image.pack(fill="x", padx=16, pady=6)

        tk.Label(card_image, text="🖼️ 微信图片识别与分析设置 (Vision & OCR) 与测试", font=("Microsoft YaHei UI", 11, "bold"), bg=self.COLOR_CARD, fg=self.COLOR_TEXT).pack(anchor="w", padx=16, pady=(12, 6))

        # 启用开关
        self.var_image_enabled = tk.BooleanVar(value=getattr(self.config.image, "enabled", True))
        chk_img = tk.Checkbutton(
            card_image,
            text="启用微信图片识别与分析 (收到图片时自动解密落地并由多模态视觉大模型/OCR提取理解后回复)",
            variable=self.var_image_enabled,
            bg=self.COLOR_CARD,
            font=("Microsoft YaHei UI", 9, "bold"),
            fg=self.COLOR_PRIMARY
        )
        chk_img.pack(anchor="w", padx=16, pady=4)

        grid_i = tk.Frame(card_image, bg=self.COLOR_CARD)
        grid_i.pack(fill="x", padx=16, pady=6)

        # 策略选择
        tk.Label(grid_i, text="图片处理策略:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=6)
        curr_strat = getattr(self.config.image, "strategy", "auto")
        strat_map = {
            "auto": "auto (主流：多模态视觉大模型优先，不支持时自动降级 WinRT OCR - 推荐)",
            "vision_only": "vision_only (仅使用多模态视觉大模型)",
            "ocr_only": "ocr_only (仅使用 Windows 原生硬件加速 WinRT OCR 离线纯文字提取)"
        }
        self.var_image_strategy = tk.StringVar(value=strat_map.get(curr_strat, strat_map["auto"]))
        self.cb_image_strategy = ttk.Combobox(
            grid_i,
            textvariable=self.var_image_strategy,
            values=list(strat_map.values()),
            state="readonly",
            width=65,
            font=("Microsoft YaHei UI", 9)
        )
        self.cb_image_strategy.grid(row=0, column=1, columnspan=2, sticky="w", padx=6, pady=6)
        self.cb_image_strategy.bind("<<ComboboxSelected>>", self._on_image_strategy_changed)

        # 视觉大模型配置区
        self.f_vision = tk.Frame(card_image, bg=self.COLOR_CARD)
        self.f_vision.pack(fill="x", padx=16, pady=4)

        tk.Label(self.f_vision, text="视觉大模型名称 (Vision Model):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w", pady=4)
        self.var_vision_model = tk.StringVar(value=getattr(self.config.image, "vision_model_name", "") or "")
        self.cb_vision_model = ttk.Combobox(
            self.f_vision,
            textvariable=self.var_vision_model,
            values=["qwen-vl-max", "gpt-4o", "gpt-4o-mini", "gemini-1.5-pro", "glm-4v"],
            width=28,
            font=("Consolas", 9)
        )
        self.cb_vision_model.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        tk.Label(self.f_vision, text="(留空则直接使用大模型配置页面的全局模型)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=0, column=2, sticky="w", padx=6)

        tk.Label(self.f_vision, text="视觉模型 API Base URL (可选):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", pady=4)
        self.var_vision_url = tk.StringVar(value=getattr(self.config.image, "vision_api_url", "") or "")
        ttk.Entry(self.f_vision, textvariable=self.var_vision_url, width=38, font=("Consolas", 9)).grid(row=1, column=1, sticky="w", padx=6, pady=4)
        tk.Label(self.f_vision, text="(留空继承全局大模型 API 地址)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=1, column=2, sticky="w", padx=6)

        tk.Label(self.f_vision, text="视觉模型 API Key (可选):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=2, column=0, sticky="w", pady=4)
        self.var_vision_key = tk.StringVar(value=getattr(self.config.image, "vision_api_key", "") or "")
        ttk.Entry(self.f_vision, textvariable=self.var_vision_key, width=38, show="*", font=("Consolas", 9)).grid(row=2, column=1, sticky="w", padx=6, pady=4)
        tk.Label(self.f_vision, text="(留空继承全局大模型 API Key)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=2, column=2, sticky="w", padx=6)

        # 自动降级选项
        self.var_fallback_ocr = tk.BooleanVar(value=getattr(self.config.image, "fallback_to_ocr", True))
        self.chk_fallback_ocr = tk.Checkbutton(
            card_image,
            text="启用自动降级：当视觉大模型报错或接入的为纯文本大模型(如DeepSeek-chat)时，自动启用 Windows 原生 WinRT OCR 提取图片中文字送入大模型",
            variable=self.var_fallback_ocr,
            bg=self.COLOR_CARD,
            font=("Microsoft YaHei UI", 8)
        )
        self.chk_fallback_ocr.pack(anchor="w", padx=16, pady=(4, 8))

        # 图片测试工具沙盒
        lf_itest = tk.LabelFrame(card_image, text=" 🖼️ 图片选择与识别解析测试工具 ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#7c3aed", padx=12, pady=8)
        lf_itest.pack(fill="x", padx=16, pady=(6, 12))

        f_it_in = tk.Frame(lf_itest, bg=self.COLOR_CARD)
        f_it_in.pack(fill="x", pady=4)

        tk.Label(f_it_in, text="测试图片文件路径:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.var_image_test_path = tk.StringVar(value="")
        ttk.Entry(f_it_in, textvariable=self.var_image_test_path, width=54, font=("Consolas", 9)).pack(side="left", padx=6, fill="x", expand=True)

        btn_browse_img = tk.Button(
            f_it_in,
            text="📂 弹窗选择图片文件",
            command=self._on_browse_image_test,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#f1f5f9",
            fg=self.COLOR_TEXT,
            relief="flat",
            padx=10,
            pady=3,
            cursor="hand2"
        )
        btn_browse_img.pack(side="left", padx=4)

        self.btn_run_image_test = tk.Button(
            f_it_in,
            text="⚡ 开始测试识别",
            command=self._on_run_image_test,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#7c3aed",
            fg="#ffffff",
            relief="flat",
            padx=12,
            pady=3,
            cursor="hand2"
        )
        self.btn_run_image_test.pack(side="left", padx=4)

        f_it_p = tk.Frame(lf_itest, bg=self.COLOR_CARD)
        f_it_p.pack(fill="x", pady=(2, 6))
        tk.Label(f_it_p, text="测试指导提示词 (可选):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.var_image_test_prompt = tk.StringVar(value="请分析这张图片中的内容，提取关键信息并给出简明解答：")
        ttk.Entry(f_it_p, textvariable=self.var_image_test_prompt, width=70, font=("Microsoft YaHei UI", 9)).pack(side="left", padx=6, fill="x", expand=True)

        tk.Label(lf_itest, text="图片识别解析输出 (策略方式、提取文字或视觉回答、耗时):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 8, "bold"), fg=self.COLOR_MUTED).pack(anchor="w", pady=(6, 2))
        self.txt_image_test_result = scrolledtext.ScrolledText(lf_itest, wrap="word", height=5, font=("Microsoft YaHei UI", 9), bd=1, relief="solid")
        self.txt_image_test_result.pack(fill="x", pady=2)
        self.txt_image_test_result.insert("1.0", "提示：点击上方【📂 弹窗选择图片文件】选取本地 .jpg、.png、.bmp 或微信图片，再点击【⚡ 开始测试识别】即可测试多模态大模型视觉理解或 WinRT OCR 离线提取。")

        # 底部保存大按钮
        f_save_bot = tk.Frame(scroll_frame, bg=self.COLOR_BG)
        f_save_bot.pack(fill="x", padx=16, pady=(10, 20))

        btn_save_bot = tk.Button(
            f_save_bot,
            text="💾 保存多模态与媒体设置并立即生效",
            command=self._on_save_media_config_click,
            font=("Microsoft YaHei UI", 11, "bold"),
            bg=self.COLOR_PRIMARY,
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            relief="flat",
            padx=24,
            pady=8,
            cursor="hand2"
        )
        btn_save_bot.pack(anchor="center")

    def _update_model_status_label(self):
        """检查并更新本地 Whisper 模型在项目 models/ 目录中的离线就绪状态"""
        if not hasattr(self, "lbl_voice_model_status") or not hasattr(self, "var_voice_model"):
            return
        raw_m = self.var_voice_model.get().split()[0].strip()
        project_root = os.path.dirname(os.path.abspath(__file__))
        models_dir = os.path.join(project_root, "models")
        cand1 = os.path.join(models_dir, f"whisper-{raw_m}")
        cand2 = os.path.join(models_dir, raw_m)
        
        is_ready = False
        for c in (cand1, cand2):
            if os.path.isdir(c) and os.path.exists(os.path.join(c, "model.bin")):
                is_ready = True
                break
                
        if is_ready:
            self.lbl_voice_model_status.config(text=f"● 本地离线已就绪 (已存入项目 models/whisper-{raw_m})", fg=self.COLOR_SUCCESS)
        else:
            self.lbl_voice_model_status.config(text="○ 本地未缓存 (首次运行将自动下载至 models/ 目录)", fg=self.COLOR_WARNING)

    def _on_voice_engine_changed(self, event=None):
        eng_sel = self.var_voice_engine.get().lower()
        if "cloud" in eng_sel:
            self.f_voice_local.pack_forget()
            self.f_voice_cloud.pack(fill="x", padx=16, pady=4)
        else:
            self.f_voice_cloud.pack_forget()
            self.f_voice_local.pack(fill="x", padx=16, pady=4)

    def _on_image_strategy_changed(self, event=None):
        strat_sel = self.var_image_strategy.get().lower()
        if "ocr_only" in strat_sel:
            self.f_vision.pack_forget()
            self.chk_fallback_ocr.pack_forget()
        else:
            self.f_vision.pack(fill="x", padx=16, pady=4)
            self.chk_fallback_ocr.pack(anchor="w", padx=16, pady=(4, 8))

    def _on_browse_audio_test(self):
        """弹窗选择待测试的音频文件"""
        selected = filedialog.askopenfilename(
            title="请选择用于测试识别的音频文件",
            filetypes=[
                ("常用音频文件", "*.silk;*.wav;*.mp3;*.m4a;*.ogg;*.flac"),
                ("微信 SILK 语音", "*.silk"),
                ("标准 WAV 音频", "*.wav"),
                ("MP3 音频", "*.mp3"),
                ("所有文件", "*.*")
            ],
            parent=self.root
        )
        if selected:
            norm_path = os.path.normpath(selected)
            self.var_voice_test_path.set(norm_path)

    def _on_run_audio_test(self):
        """异步执行语音识别转写测试"""
        audio_path = self.var_voice_test_path.get().strip()
        if not audio_path or not os.path.exists(audio_path):
            messagebox.showwarning("提示", "请先选择真实存在的测试音频文件！")
            return

        self.btn_run_voice_test.configure(text="⏳ 正在转写中...", state="disabled")
        self.txt_voice_test_result.delete("1.0", "end")
        self.txt_voice_test_result.insert("1.0", "正在调用语音识别引擎转写音频，请稍候...\n")

        # 抓取当前界面配置构造测试用 VoiceConfig
        cfg = self.config.voice.model_copy()
        cfg.engine = "cloud" if "cloud" in self.var_voice_engine.get().lower() else "local"
        raw_m = self.var_voice_model.get().split()[0].strip()
        cfg.whisper_model = raw_m
        raw_dev = self.var_voice_device.get().split()[0].strip().lower()
        cfg.whisper_device = raw_dev
        cfg.cloud_api_url = self.var_voice_cloud_url.get().strip()
        cfg.cloud_api_key = self.var_voice_cloud_key.get().strip()
        cfg.cloud_model_name = self.var_voice_cloud_model.get().strip() or "whisper-1"

        def worker():
            start_ts = time.time()
            try:
                from agent_core.media_engine import VoiceRecognizer
                recognizer = VoiceRecognizer(cfg)
                ok, text, eng = recognizer.transcribe(audio_path)
                cost = round((time.time() - start_ts) * 1000, 1)

                def on_done():
                    self.btn_run_voice_test.configure(text="⚡ 开始测试转写", state="normal")
                    self.txt_voice_test_result.delete("1.0", "end")
                    if ok:
                        content = (
                            f"✅ 【语音转写成功】\n"
                            f"• 使用引擎: {eng}\n"
                            f"• 转写耗时: {cost} 毫秒\n"
                            f"• 识别文本:\n{text}"
                        )
                    else:
                        content = (
                            f"❌ 【语音转写失败】\n"
                            f"• 使用引擎: {eng}\n"
                            f"• 耗时: {cost} 毫秒\n"
                            f"• 错误信息: {text}"
                        )
                    self.txt_voice_test_result.insert("1.0", content)
                self.dispatch_ui(on_done)
            except Exception as e:
                def on_err():
                    self.btn_run_voice_test.configure(text="⚡ 开始测试转写", state="normal")
                    self.txt_voice_test_result.delete("1.0", "end")
                    self.txt_voice_test_result.insert("1.0", f"❌ 异常报错: {e}")
                self.dispatch_ui(on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_browse_image_test(self):
        """弹窗选择待测试的图片文件"""
        selected = filedialog.askopenfilename(
            title="请选择用于测试识别的图片文件",
            filetypes=[
                ("常用图片文件", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"),
                ("PNG 图片", "*.png"),
                ("JPEG 图片", "*.jpg;*.jpeg"),
                ("所有文件", "*.*")
            ],
            parent=self.root
        )
        if selected:
            norm_path = os.path.normpath(selected)
            self.var_image_test_path.set(norm_path)

    def _on_run_image_test(self):
        """异步执行图片识别与多模态/OCR测试"""
        img_path = self.var_image_test_path.get().strip()
        if not img_path or not os.path.exists(img_path):
            messagebox.showwarning("提示", "请先选择真实存在的测试图片文件！")
            return

        user_prompt = self.var_image_test_prompt.get().strip()
        self.btn_run_image_test.configure(text="⏳ 正在识别中...", state="disabled")
        self.txt_image_test_result.delete("1.0", "end")
        self.txt_image_test_result.insert("1.0", "正在调用视觉大模型或启动 WinRT OCR 硬件加速识别，请稍候...\n")

        # 抓取当前界面配置构造测试用 ImageConfig
        img_cfg = self.config.image.model_copy()
        strat_val = self.var_image_strategy.get().lower()
        if "vision_only" in strat_val:
            img_cfg.strategy = "vision_only"
        elif "ocr_only" in strat_val:
            img_cfg.strategy = "ocr_only"
        else:
            img_cfg.strategy = "auto"
        img_cfg.vision_model_name = self.var_vision_model.get().strip()
        img_cfg.vision_api_url = self.var_vision_url.get().strip()
        img_cfg.vision_api_key = self.var_vision_key.get().strip()
        img_cfg.fallback_to_ocr = bool(self.var_fallback_ocr.get())

        def worker():
            start_ts = time.time()
            try:
                from agent_core.media_engine import ImageEngine
                engine = ImageEngine(img_cfg, self.config.llm)
                res = engine.process_image(img_path, user_prompt=user_prompt)
                cost = round((time.time() - start_ts) * 1000, 1)

                def on_done():
                    self.btn_run_image_test.configure(text="⚡ 开始测试识别", state="normal")
                    self.txt_image_test_result.delete("1.0", "end")
                    lines = [
                        f"【识别耗时】 {cost} 毫秒",
                        f"【采用策略方案】 {res.get('strategy')}",
                        f"【执行状态】 {'成功' if res.get('success') else '失败'}",
                    ]
                    strat = res.get("strategy")
                    if strat == "vision":
                        lines.append("\n" + "=" * 50)
                        lines.append("【多模态视觉大模型 (Vision LLM) 识别与直接回答】：")
                        lines.append(res.get("direct_reply", "(无回答)"))
                    elif strat in ("ocr_fallback", "ocr_only"):
                        lines.append("\n" + "=" * 50)
                        tag = "【WinRT OCR 硬件加速纯文字提取】" if strat == "ocr_only" else "【自动降级：WinRT OCR 提取文字】"
                        lines.append(tag)
                        lines.append(res.get("ocr_text", "(未识别到文字)"))
                    else:
                        lines.append("\n" + "=" * 50)
                        lines.append(f"【报错或回退信息】: {res.get('error') or res.get('direct_reply')}")
                    lines.append("=" * 50)
                    self.txt_image_test_result.insert("1.0", "\n".join(lines))
                self.dispatch_ui(on_done)
            except Exception as e:
                def on_err():
                    self.btn_run_image_test.configure(text="⚡ 开始测试识别", state="normal")
                    self.txt_image_test_result.delete("1.0", "end")
                    self.txt_image_test_result.insert("1.0", f"❌ 异常报错: {e}")
                self.dispatch_ui(on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_save_media_config_click(self):
        """保存多模态与媒体配置并热生效"""
        try:
            # 1. 语音配置
            self.config.voice.enabled = bool(self.var_voice_enabled.get())
            self.config.voice.engine = "cloud" if "cloud" in self.var_voice_engine.get().lower() else "local"
            raw_m = self.var_voice_model.get().split()[0].strip()
            self.config.voice.whisper_model = raw_m
            raw_dev = self.var_voice_device.get().split()[0].strip().lower()
            self.config.voice.whisper_device = raw_dev
            self.config.voice.cloud_api_url = self.var_voice_cloud_url.get().strip()
            self.config.voice.cloud_api_key = self.var_voice_cloud_key.get().strip()
            self.config.voice.cloud_model_name = self.var_voice_cloud_model.get().strip() or "whisper-1"

            # 2. 图片配置
            self.config.image.enabled = bool(self.var_image_enabled.get())
            strat_val = self.var_image_strategy.get().lower()
            if "vision_only" in strat_val:
                self.config.image.strategy = "vision_only"
            elif "ocr_only" in strat_val:
                self.config.image.strategy = "ocr_only"
            else:
                self.config.image.strategy = "auto"
            self.config.image.vision_model_name = self.var_vision_model.get().strip()
            self.config.image.vision_api_url = self.var_vision_url.get().strip()
            self.config.image.vision_api_key = self.var_vision_key.get().strip()
            self.config.image.fallback_to_ocr = bool(self.var_fallback_ocr.get())

            # 3. 持久化保存到 config.json
            self.config.save()

            # 4. 热生效到底层实例
            if hasattr(self.bridge, "voice_recognizer"):
                self.bridge.voice_recognizer.update_config(self.config.voice)
            if hasattr(self.pipeline, "image_engine"):
                self.pipeline.image_engine.update_config(self.config.image, self.config.llm)

            messagebox.showinfo(
                "成功",
                f"✅ 多模态与媒体设置已成功保存并立即生效！\n\n"
                f"• 语音识别: {'已开启' if self.config.voice.enabled else '已关闭'} ({self.config.voice.engine})\n"
                f"• 语音模型: {self.config.voice.whisper_model} ({self.config.voice.whisper_device})\n"
                f"• 图片识别: {'已开启' if self.config.image.enabled else '已关闭'} ({self.config.image.strategy})\n"
                f"• 自动OCR降级: {'开启' if self.config.image.fallback_to_ocr else '关闭'}"
            )
        except Exception as e:
            messagebox.showerror("保存失败", f"保存多模态设置时出错: {e}")

    # -------------------------------------------------------------------------
    # Tab 6: 交互测试沙盒 (Sandbox)
    # -------------------------------------------------------------------------
    def _build_sandbox_tab(self):
        parent = self.tab_sandbox

        card = tk.Frame(parent, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=16, pady=12)

        tk.Label(card, text="🧪 智能体全流程沙盒测试 (不打扰真实微信聊天)", font=("Microsoft YaHei UI", 11, "bold"), bg=self.COLOR_CARD, fg=self.COLOR_TEXT).pack(anchor="w", padx=16, pady=(12, 6))

        # 输入测试区
        in_frame = tk.Frame(card, bg=self.COLOR_CARD)
        in_frame.pack(fill="x", padx=16, pady=8)

        tk.Label(in_frame, text="模拟发送者姓名:", bg=self.COLOR_CARD).grid(row=0, column=0, sticky="w")
        self.var_sb_sender = tk.StringVar(value="测试用户张三")
        ttk.Entry(in_frame, textvariable=self.var_sb_sender, width=20).grid(row=0, column=1, sticky="w", padx=6)

        self.var_sb_is_group = tk.BooleanVar(value=False)
        chk_sb_grp = tk.Checkbutton(in_frame, text="模拟群聊消息", variable=self.var_sb_is_group, bg=self.COLOR_CARD)
        chk_sb_grp.grid(row=0, column=2, padx=10)

        self.var_sb_at_me = tk.BooleanVar(value=True)
        chk_sb_at = tk.Checkbutton(in_frame, text="模拟 @ 机器人", variable=self.var_sb_at_me, bg=self.COLOR_CARD)
        chk_sb_at.grid(row=0, column=3, padx=10)

        tk.Label(in_frame, text="输入测试问题:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.var_sb_query = tk.StringVar(value="请问头痛且伴有轻微发烧应该挂什么科？另外张医生明天出诊吗？")
        ent_sb_q = ttk.Entry(in_frame, textvariable=self.var_sb_query, width=65, font=("Microsoft YaHei UI", 9))
        ent_sb_q.grid(row=1, column=1, columnspan=3, sticky="we", padx=6, pady=(8, 0))

        self.btn_run_sandbox = tk.Button(
            in_frame,
            text="🚀 运行测试",
            command=self._on_run_sandbox_click,
            font=("Microsoft YaHei UI", 10, "bold"),
            bg=self.COLOR_PRIMARY,
            fg="#ffffff",
            relief="flat",
            padx=16,
            pady=4,
            cursor="hand2"
        )
        self.btn_run_sandbox.grid(row=1, column=4, padx=8, pady=(8, 0))

        # 结果与链路展示
        tk.Label(card, text="决策链路与输出结果展示:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
        self.txt_sb_result = scrolledtext.ScrolledText(card, wrap="word", font=("Microsoft YaHei UI", 9), bg="#f8fafc", bd=1, relief="solid")
        self.txt_sb_result.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _on_run_sandbox_click(self):
        query = self.var_sb_query.get().strip()
        if not query:
            messagebox.showwarning("提示", "请输入测试内容！")
            return

        sender = self.var_sb_sender.get().strip() or "测试好友"
        is_grp = self.var_sb_is_group.get()
        is_at = self.var_sb_at_me.get()

        self.btn_run_sandbox.configure(text="⏳ 推理中...", state="disabled")
        self.txt_sb_result.delete("1.0", "end")
        self.txt_sb_result.insert("1.0", "正在调用智能体流水线 (意图分析 -> RAG 检索 -> 工具调用 -> LLM 综合回复)...\n")

        def worker():
            try:
                res: PipelineResult = self.pipeline.process(
                    chat_id="sandbox_test",
                    sender_name=sender,
                    content=query,
                    is_group=is_grp,
                    is_at_me=is_at
                )
                def on_done():
                    self.btn_run_sandbox.configure(text="🚀 运行测试", state="normal")
                    self.txt_sb_result.delete("1.0", "end")
                    lines = [
                        f"【测试用时】 {round(res.duration_ms, 1)} 毫秒",
                        f"【是否触发回复】 {'是' if res.should_send else '否'}",
                        f"【意图分类】 {res.intent}",
                        f"【RAG 命中切片数】 {len(res.rag_hits)} 个",
                        f"【工具执行数】 {len(res.tool_executions)} 个",
                    ]
                    if res.tool_executions:
                        lines.append("【工具调用明细】")
                        for t in res.tool_executions:
                            lines.append(f"  - 工具: {t.get('tool_name')}({t.get('arguments')}) -> {t.get('result')}")
                    lines.append("\n" + "="*50)
                    lines.append("【AI 合成回复内容】")
                    lines.append(res.reply_text or "(无回复)")
                    lines.append("="*50)
                    self.txt_sb_result.insert("1.0", "\n".join(lines))
                self.dispatch_ui(on_done)
            except Exception as e:
                def on_err():
                    self.btn_run_sandbox.configure(text="🚀 运行测试", state="normal")
                    self.txt_sb_result.insert("end", f"\n❌ 推理出现异常:\n{e}")
                self.dispatch_ui(on_err)

        threading.Thread(target=worker, daemon=True).start()

    # -------------------------------------------------------------------------
    # 状态刷新与启停事件
    # -------------------------------------------------------------------------
    def _on_refresh_status_click(self):
        threading.Thread(target=self._async_initial_load, daemon=True).start()
        messagebox.showinfo("提示", "已触发状态与通讯录后台刷新！")

    def _on_toggle_autoreply_click(self):
        current = self.bridge.auto_reply_enabled
        new_state = not current
        ok, msg = self.bridge.set_auto_reply(new_state)

        if ok:
            if new_state:
                self.btn_toggle_autoreply.configure(
                    text="⏹ 暂停自动回复",
                    bg=self.COLOR_DANGER,
                    activebackground="#dc2626"
                )
                self.card_val_status.configure(text="运行中", fg=self.COLOR_SUCCESS)
                self._append_log("sent", "系统", "自动回复功能已【开启】！")
            else:
                self.btn_toggle_autoreply.configure(
                    text="▶ 开启自动回复",
                    bg=self.COLOR_SUCCESS,
                    activebackground="#059669"
                )
                self.card_val_status.configure(text="已暂停", fg=self.COLOR_MUTED)
                self._append_log("warning", "系统", "自动回复功能已【暂停】（仅监听记录，不发回复）。")
        else:
            messagebox.showerror("启动失败", msg)

    def _async_initial_load(self):
        """后台异步载入微信状态、启动消息监听并同步近期消息流与通讯录"""
        try:
            # 1. 检查微信登录状态
            status = self.bridge.get_status()
            wechat_detected = status.get("wechat_detected", False)
            self_name = status.get("self_name", "")
            self_wxid = status.get("self_wxid", "")

            def update_status():
                if wechat_detected:
                    display_name = self_name.strip() if self_name and self_name.strip() else self_wxid
                    title_text = f"● 微信已连接: {display_name} ({self_wxid})" if display_name != self_wxid else f"● 微信已连接: {self_wxid}"
                    self.lbl_wechat_status.configure(
                        text=title_text,
                        fg="#4ade80"
                    )
                    self._append_log("info", "系统", f"已连接微信: {display_name} ({self_wxid})，正在同步近期最新消息流...")
                else:
                    self.lbl_wechat_status.configure(
                        text="○ 未检测到登录的微信 (请确认微信客户端已在电脑登录)",
                        fg="#f87171"
                    )
            self.dispatch_ui(update_status)

            # 2. 若微信已连接，优先启动底层实时消息监听，并极速同步最新消息流到主看板
            if wechat_detected:
                self.bridge.start_listening()
                self._sync_recent_messages_internal(notify=False)
                def log_policy_tips():
                    if self.bridge.auto_reply_enabled:
                        self._append_log("success", "系统", "自动回复功能状态：【运行中】")
                    else:
                        self._append_log("warning", "系统", "自动回复功能当前处于【已暂停】状态，如需开启请点击右上角【▶ 开启自动回复】！")

                    if self.config.targets.reply_all_private:
                        self._append_log("info", "系统", "好友私聊回复策略：【允许自动回复所有好友私聊】")
                    else:
                        valid_cands = [u for u in self.config.targets.whitelist_users if u != self_wxid]
                        self._append_log("info", "系统", f"好友私聊回复策略：【仅限白名单】(当前已配置 {len(valid_cands)} 位好友)")
                self.dispatch_ui(log_policy_tips)

            # 3. 载入通讯录好友与群聊
            res = self.bridge.get_contacts_and_groups()
            self.all_contacts = res.get("contacts", [])
            self.all_groups = res.get("groups", [])

            def update_trees():
                self._render_contacts_tree()
                self._render_groups_tree()
            self.dispatch_ui(update_trees)

        except Exception as e:
            self.dispatch_ui(self._append_log, "error", "异常", f"加载初始数据失败: {e}")

    # -------------------------------------------------------------------------
    # 事件流分发 (主线程 Queue 处理)
    # -------------------------------------------------------------------------
    def dispatch_ui(self, fn, *args, **kwargs):
        """线程安全地派发任务到 Tkinter 主线程执行"""
        self.event_queue.put({
            "type": "_ui_call",
            "fn": fn,
            "args": args,
            "kwargs": kwargs
        })

    def _on_bridge_event(self, event: Dict[str, Any]):
        """来自底层 WeChatBridge 的回调，压入线程安全队列"""
        self.event_queue.put(event)

    def _process_events(self):
        """主线程定时拉取事件并刷新 UI"""
        try:
            while not self.event_queue.empty():
                event = self.event_queue.get_nowait()
                ev_type = event.get("type")
                data = event.get("data", {})

                if ev_type == "_ui_call":
                    fn = event.get("fn")
                    args = event.get("args", ())
                    kwargs = event.get("kwargs", {})
                    try:
                        if callable(fn):
                            fn(*args, **kwargs)
                    except Exception:
                        pass
                    continue

                if ev_type == "message_received":
                    self.stat_received += 1
                    self.card_val_received.configure(text=str(self.stat_received))
                    dt = data.get("display_title", "")
                    content = data.get("content", "")
                    self._append_log("received", f"📨 {dt}:", content)

                elif ev_type == "pipeline_finished":
                    title = data.get("display_title", "")
                    reply = data.get("reply_text", "")
                    dur = data.get("duration_ms", 0)
                    rag_cnt = data.get("rag_hits_count", 0)
                    tool_cnt = data.get("tools_count", 0)
                    self._append_log("pipeline", "🧠 [决策流水线]", f"耗时 {dur}ms | RAG命中 {rag_cnt}条 | 工具调用 {tool_cnt}个")
                    self._append_log("ai", f"🤖 AI 回复 [{title}]:", reply)

                elif ev_type == "message_sent":
                    self.stat_replied += 1
                    self.card_val_replied.configure(text=str(self.stat_replied))
                    target = data.get("target", "")
                    self._append_log("sent", "✅ [微信已发送]", f"成功送达 -> [{target}]")

                elif ev_type == "message_ignored":
                    self.stat_ignored += 1
                    self.card_val_ignored.configure(text=str(self.stat_ignored))
                    sender = data.get("sender_name", "")
                    reason = data.get("reason", "")
                    self._append_log("warning", "⚠️ [已忽略]", f"来自 [{sender}] 的消息被过滤: {reason}")

                elif ev_type == "log":
                    lvl = data.get("level", "info")
                    msg = data.get("message", "")
                    self._append_log(lvl, f"[{lvl.upper()}]", msg)

        except Exception as e:
            pass
        finally:
            self.root.after(50, self._process_events)

    def _periodic_heartbeat(self):
        """后台周期性心跳：若启动时未检测到微信，后续登录后自动建立监听与同步"""
        try:
            status = self.bridge.get_status()
            wechat_detected = status.get("wechat_detected", False)
            self_name = status.get("self_name", "")
            self_wxid = status.get("self_wxid", "")

            # 若当前尚未启动底层监听，但检测到了微信登录，则自动连通
            if wechat_detected and not self.bridge.is_running:
                display_name = self_name.strip() if self_name and self_name.strip() else self_wxid
                title_text = f"🟢 微信: {display_name} ({self_wxid})" if display_name != self_wxid else f"🟢 微信: {self_wxid}"
                self.lbl_wechat_status.configure(
                    text=title_text,
                    fg="#4ade80"
                )
                self._append_log("info", "系统", f"检测到微信已登录 ({display_name})，正在自动连接实时监听...")
                threading.Thread(target=self._async_initial_load, daemon=True).start()
        except Exception:
            pass
        finally:
            self.root.after(8000, self._periodic_heartbeat)


def main():
    try:
        root = tk.Tk()
        app = WeChatAIAgentApp(root)
        root.mainloop()
    except Exception as exc:
        import traceback
        err_msg = traceback.format_exc()
        sys.stderr.write("Fatal error during GUI startup:\n" + err_msg + "\n")
        try:
            with open("gui_crash.log", "w", encoding="utf-8") as f:
                f.write(err_msg)
        except Exception:
            pass
        try:
            from tkinter import messagebox
            err_root = tk.Tk()
            err_root.withdraw()
            messagebox.showerror(
                "WeChat-AIAgent 启动异常",
                f"程序启动发生异常，错误详情已记录至 gui_crash.log：\n\n{exc}\n\n请检查控制台或日志文件排查。"
            )
            err_root.destroy()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
