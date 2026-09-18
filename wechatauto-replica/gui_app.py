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
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext, simpledialog
from typing import Dict, Any, List, Optional
from PIL import Image, ImageTk, ImageDraw

# =========================================================================
# Cyberpunk Neon Glassmorphism 自绘高质感组件体系 (对齐图 B 视觉标杆)
# =========================================================================

class CyberAvatar:
    """顶部机器人拟态徽章 (圆角发光暗蓝容器 + 亮蓝霓虹外框)"""
    def __init__(self, parent, size=44, bg="#FFFFFF"):
        self.canvas = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0)
        img = Image.new("RGBA", (size*2, size*2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Keep the existing footprint, but render a restrained inner-glass highlight
        # so the badge reads as a control-center mark instead of a flat emoji tile.
        draw.rounded_rectangle([2, 2, size*2-3, size*2-3], radius=24, fill=(237, 242, 255, 255), outline=(99, 102, 241, 255), width=3)
        draw.rounded_rectangle([7, 7, size*2-8, size*2-8], radius=19, outline=(99, 102, 241, 100), width=2)
        self.tk_img = ImageTk.PhotoImage(img.resize((size, size), Image.Resampling.LANCZOS))
        self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")
        self.canvas.create_text(size//2, size//2, text="🤖", fill="#6366F1", font=("Segoe UI Emoji", 16))
    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

class CyberPillButton:
    """头部控制胶囊按钮 (主CTA蓝紫霓虹渐变 / 次级深蓝发光玻璃)"""
    def __init__(self, parent, text, command, w=145, h=34, is_cta=True, bg="#FFFFFF"):
        self.canvas = tk.Canvas(parent, width=w, height=h, bg=bg, highlightthickness=0, cursor="hand2")
        self.w, self.h = w, h
        self.text = text
        self.command = command
        self.is_cta = is_cta
        self.is_paused = False
        self._render()
        self.canvas.bind("<Button-1>", lambda e: self.command() if self.command else None)
        self.canvas.bind("<Enter>", lambda e: self._render(hover=True))
        self.canvas.bind("<Leave>", lambda e: self._render(hover=False))

    def _render(self, hover=False):
        w, h = self.w, self.h
        img = Image.new("RGBA", (w*2, h*2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        r = h*2
        if self.is_cta:
            c1 = (168, 85, 247) if self.is_paused else (99, 102, 241)
            c2 = (99, 102, 241) if self.is_paused else (59, 130, 246)
            if hover:
                c1 = (min(255, c1[0]+25), min(255, c1[1]+25), min(255, c1[2]+25))
                c2 = (min(255, c2[0]+25), min(255, c2[1]+25), min(255, c2[2]+25))
            for x in range(w*2):
                t = x / (w*2)
                cr = int(c1[0] * (1-t) + c2[0] * t)
                cg = int(c1[1] * (1-t) + c2[1] * t)
                cb = int(c1[2] * (1-t) + c2[2] * t)
                draw.line([(x, 0), (x, h*2)], fill=(cr, cg, cb, 255))
            mask = Image.new("L", (w*2, h*2), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, w*2-1, h*2-1], radius=r, fill=255)
            img.putalpha(mask)
        else:
            fill_c = (255, 255, 255, 245) if hover else (255, 255, 255, 220)
            border_c = (99, 102, 241, 255) if hover else (203, 213, 255, 255)
            draw.rounded_rectangle([2, 2, w*2-3, h*2-3], radius=r, fill=fill_c, outline=border_c, width=3)

        self.tk_img = ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS))
        self.canvas.btn_img = self.tk_img
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")
        txt_c = "#FFFFFF" if self.is_cta else ("#4F46E5" if hover else "#475569")
        self.txt_id = self.canvas.create_text(w//2, h//2, text=self.text, fill=txt_c, font=("Microsoft YaHei UI", 9, "bold"))

    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.text = kwargs["text"]
            if "暂停" in self.text or "关闭" in self.text:
                self.is_paused = True
            else:
                self.is_paused = False
            self._render()
        if "bg" in kwargs:
            if "#6D" in str(kwargs["bg"]).upper() or "PURPLE" in str(kwargs["bg"]).upper():
                self.is_paused = True
            else:
                self.is_paused = False
            self._render()

    def cget(self, key):
        if key == "text":
            return self.text
        return ""

class CyberSidebarItem:
    """侧边栏导航项 (选中态为高饱和电光蓝圆角发光胶囊)"""
    def __init__(self, parent, text, command, w=204, h=38, is_active=False):
        self.parent = parent
        self.text = text
        self.command = command
        self.w, self.h = w, h
        self.is_active = is_active
        self.canvas = tk.Canvas(parent, width=w, height=h, bg="#FFFFFF", highlightthickness=0, cursor="hand2")
        self._render()
        self.canvas.bind("<Button-1>", lambda e: self.command())
        self.canvas.bind("<Enter>", lambda e: self._on_enter())
        self.canvas.bind("<Leave>", lambda e: self._on_leave())

    def _render(self, hover=False):
        w, h = self.w, self.h
        img = Image.new("RGBA", (w*2, h*2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        r = 18
        if self.is_active:
            draw.rounded_rectangle([2, 2, w*2-3, h*2-3], radius=r, fill=(99, 102, 241, 235), outline=(129, 140, 248, 255), width=3)
            txt_color = "#FFFFFF"
        elif hover:
            draw.rounded_rectangle([2, 2, w*2-3, h*2-3], radius=r, fill=(238, 242, 255, 220), outline=(199, 210, 254, 220), width=2)
            txt_color = "#4F46E5"
        else:
            txt_color = "#64748B"

        self.tk_img = ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS))
        self.canvas.btn_img = self.tk_img
        self.canvas.delete("all")
        if self.is_active or hover:
            self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")
        self.canvas.create_text(16, h//2, text=self.text, fill=txt_color, font=("Microsoft YaHei UI", 9, "bold" if self.is_active else "normal"), anchor="w")

    def set_active(self, active: bool):
        self.is_active = active
        self._render()

    def _on_enter(self):
        if not self.is_active:
            self._render(hover=True)

    def _on_leave(self):
        if not self.is_active:
            self._render(hover=False)

    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.text = kwargs["text"]
            self._render()

class DynamicCyberCard:
    """四张核心指标卡 (圆角拟态玻璃 + 左侧发光圆环徽章 + 右侧大字号数值)"""
    def __init__(self, parent, title, value, val_color, icon_char, bg_color, border_color, badge_color, is_switch=False):
        # 初始 width 设为小值，交由外层 grid/pack 依据实际窗口宽度 1/4 等比例弹性拉伸
        self.canvas = tk.Canvas(parent, width=10, height=76, bg="#F5F7FF", highlightthickness=0)
        self.title = title
        self.curr_text = value
        self.curr_fg = val_color
        self.icon_char = icon_char
        self.bg_color = bg_color
        self.border_color = border_color
        self.badge_color = badge_color
        self.is_switch = is_switch
        self.switch_text = "[ ○ 关 ]"
        self.switch_fg = "#7892B2"
        self.last_w = 0
        self.val_id = None
        self.pill_id = None
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Enter>", lambda e: self._redraw(hover=True))
        self.canvas.bind("<Leave>", lambda e: self._redraw(hover=False))

    def _on_resize(self, event):
        w, h = event.width, event.height
        if w < 40 or abs(w - self.last_w) < 2:
            return
        self.last_w = w
        self._redraw(w, h)

    def _redraw(self, w=None, h=76, hover=False):
        if w is None:
            w = self.canvas.winfo_width()
        if w < 40:
            w = 120
        img = Image.new("RGBA", (max(10, w*2), max(10, h*2)), (7, 18, 37, 0))
        draw = ImageDraw.Draw(img)
        base = self.bg_color
        if hover:
            base = tuple(min(255, c + 7) for c in base)
        draw.rounded_rectangle([5, 8, w*2-1, h*2+5], radius=28, fill=(99, 102, 241, 24))
        draw.rounded_rectangle([2, 2, w*2-3, h*2-3], radius=28, fill=base, outline=self.border_color, width=3)
        draw.line([(18, 5), (max(20, w*2-28), 5)], fill=(255, 255, 255, 210), width=2)
        bx, by, br = 46, h, 28
        draw.ellipse([bx-br, by-br, bx+br, by+br], fill=self.badge_color)
        self.tk_img = ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS))
        self.canvas.card_img = self.tk_img
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")
        self.canvas.create_text(23, h//2, text=self.icon_char, fill="#FFFFFF", font=("Segoe UI Emoji", 13))
        self.canvas.create_text(56, 20, text=self.title, fill="#94A3B8", font=("Microsoft YaHei UI", 8), anchor="w")
        val_font_size = 15 if w > 160 else 13
        self.val_id = self.canvas.create_text(56, 42 if not self.is_switch else 38, text=self.curr_text, fill=self.curr_fg, font=("Segoe UI", val_font_size if not self.is_switch else 12, "bold"), anchor="w")
        if self.is_switch:
            self.pill_id = self.canvas.create_text(56, 56, text=self.switch_text, fill=self.switch_fg, font=("Microsoft YaHei UI", 8, "bold"), anchor="w")

    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

    def grid(self, **kwargs):
        self.canvas.grid(**kwargs)

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.curr_text = str(kwargs["text"])
            if self.val_id:
                self.canvas.itemconfig(self.val_id, text=self.curr_text)
            else:
                self._redraw()
        if "fg" in kwargs:
            self.curr_fg = kwargs["fg"]
            if self.val_id:
                self.canvas.itemconfig(self.val_id, fill=self.curr_fg)

    def cget(self, key):
        if key == "text":
            return self.curr_text
        if key == "fg":
            return self.curr_fg
        return ""


class CyberSwitchPillProxy:
    """自动回复运行中/关闭胶囊指示器代理"""
    def __init__(self, card: DynamicCyberCard):
        self.card = card

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.card.switch_text = kwargs["text"]
            if self.card.pill_id:
                self.card.canvas.itemconfig(self.card.pill_id, text=self.card.switch_text)
        if "fg" in kwargs:
            self.card.switch_fg = kwargs["fg"]
            if self.card.pill_id:
                self.card.canvas.itemconfig(self.card.pill_id, fill=self.card.switch_fg)

    def cget(self, key):
        if key == "text":
            return self.card.switch_text
        if key == "fg":
            return self.card.switch_fg
        return ""

    def pack(self, **kwargs):
        pass


# faster-whisper 模型极速镜像下载地址 (直达模型文件列表，支持单文件高速下载)
WHISPER_MODEL_DOWNLOAD_URLS: Dict[str, str] = {
    "tiny": "https://hf-mirror.com/Systran/faster-whisper-tiny",
    "base": "https://hf-mirror.com/Systran/faster-whisper-base",
    "small": "https://hf-mirror.com/Systran/faster-whisper-small",
    "medium": "https://hf-mirror.com/Systran/faster-whisper-medium",
    "large-v3": "https://hf-mirror.com/Systran/faster-whisper-large-v3",
    "large-v2": "https://hf-mirror.com/Systran/faster-whisper-large-v2",
    "large-v1": "https://hf-mirror.com/Systran/faster-whisper-large-v1",
}

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
from agent_core.profile_engine import ProfileEngine, ContactProfile
from agent_core.tools import ToolExecutor
from agent_core.pipeline import AgentPipeline, PipelineResult
from agent_core.wechat_bridge import WeChatBridge
from agent_core.config_manager import ConfigManager


class WeChatAIAgentApp:
    """WeChat-AIAgent 原生桌面应用主窗口"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("WeChat-AIAgent 微信智能自动回复助手 v2.0")
        self.root.geometry("1440x900")
        self.root.minsize(1180, 760)

        # 核心引擎组件初始化
        self.config = AppConfig.load()
        self.llm_client = LLMClient(self.config.llm)
        self.rag_engine = RAGEngine(self.config.rag)
        self.profile_engine = ProfileEngine(self.config.profile, self.llm_client)
        self.tools = ToolExecutor
        self.pipeline = AgentPipeline(self.config, self.llm_client, self.rag_engine, self.profile_engine)
        self.bridge = WeChatBridge(self.config, self.pipeline)
        if hasattr(self.bridge, "_db") and self.bridge._db:
            self.profile_engine.set_db(self.bridge._db)
        self.presets: Dict[str, str] = self.config.safety.get_presets()

        # 语音通话全双工智能体初始化
        from agent_core.voice_call.call_agent import WeChatCallAgent
        from agent_core.voice_call.voip_tab_builder import VoIPTabBuilder
        self.call_agent = WeChatCallAgent(
            app_config=self.config,
            profile_engine=self.profile_engine,
            wechat_bridge=self.bridge,
            on_event_cb=self._on_bridge_event
        )
        self.voip_builder = VoIPTabBuilder(self)

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
        self._create_light_background()

        # 构建 UI 界面
        self._create_header_bar()
        self._create_vertical_layout()
        self._create_status_bar()
        self._apply_light_surface_theme()

        # 启动后台事件轮询与心跳
        self.root.after(50, self._process_events)
        self.root.after(1000, self._periodic_heartbeat)

        # 窗口关闭时自动将当前 UI 已调整的配置数据持久化保存
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        # 异步加载初始数据 (联系人与微信状态)
        threading.Thread(target=self._async_initial_load, daemon=True).start()

    # -------------------------------------------------------------------------
    # 样式配置
    # -------------------------------------------------------------------------
    def _create_light_background(self):
        """Paint a subtle VisionOS-style background behind the existing packed layout."""
        self._background_canvas = tk.Canvas(self.root, highlightthickness=0, bd=0)
        self._background_canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        # Do not call Canvas.lower() here: in Tkinter it targets canvas items
        # (tag_lower) rather than the widget stacking order and raises TclError.
        self._background_canvas.bind("<Configure>", self._redraw_light_background)

    def _redraw_light_background(self, event=None):
        width = max(1, self.root.winfo_width())
        height = max(1, self.root.winfo_height())

        # 尺寸变化防抖：若尺寸未发生实质变动，直接跳过重绘，耗时 0ms
        last_size = getattr(self, "_last_bg_size", None)
        if last_size == (width, height):
            return
        self._last_bg_size = (width, height)

        # 高性能 1D 线性插值生成单列梯度切片，再通过 PIL C 底层双线性插值快速拉伸铺满，耗时从 340ms 降至 20ms
        grad_1d = Image.new("RGB", (1, height), "#F5F7FF")
        pixels = grad_1d.load()
        start = (248, 250, 255)
        middle = (238, 242, 255)
        end = (245, 243, 255)
        for y in range(height):
            t = y / max(1, height - 1)
            if t < 0.55:
                u = t / 0.55
                color = tuple(int(start[i] * (1 - u) + middle[i] * u) for i in range(3))
            else:
                u = (t - 0.55) / 0.45
                color = tuple(int(middle[i] * (1 - u) + end[i] * u) for i in range(3))
            pixels[0, y] = color

        image = grad_1d.resize((width, height), Image.Resampling.BILINEAR)
        glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.ellipse((-220, -150, 520, 520), fill=(190, 201, 255, 38))
        glow_draw.ellipse((width - 520, height - 420, width + 170, height + 220), fill=(216, 190, 255, 32))
        image = Image.alpha_composite(image.convert("RGBA"), glow)
        self._background_image = ImageTk.PhotoImage(image)
        self._background_canvas.delete("all")
        self._background_canvas.create_image(0, 0, image=self._background_image, anchor="nw")

    def _apply_light_surface_theme(self):
        """Restyle already-built Tk surfaces without changing their geometry or callbacks."""
        surface_map = {
            "#071225": self.COLOR_BG, "#07152B": "#FFFFFF", "#050F23": self.COLOR_HEADER,
            "#050D1C": "#F0F3FF", "#0B1D3A": self.COLOR_CARD, "#06111F": "#F8FAFC",
            "#091B36": "#F1F4FF", "#0F2444": "#FFFFFF", "#143565": "#EEF2FF",
            "#091830": "#FFFFFF", "#0E2344": "#EEF2FF", "#2E1120": "#FFF1F2",
            "#0C2B54": "#E0E7FF", "#061326": "#F8FAFC",
        }
        text_map = {
            "#F3F7FF": self.COLOR_TEXT, "#DCEEFF": "#334155", "#A8C7E8": "#64748B",
            "#9FB4D0": "#64748B", "#7892B2": "#64748B", "#7E97B8": "#64748B",
            "#4A6588": "#94A3B8", "#8CCBFF": "#4F46E5", "#60A5FA": "#6366F1",
            "#38BDF8": "#6366F1", "#93C5FD": "#4F46E5", "#67A8FF": "#64748B",
        }

        def restyle(widget):
            try:
                options = widget.keys()
                if "background" in options:
                    current = str(widget.cget("background")).upper()
                    if current in surface_map:
                        widget.configure(background=surface_map[current])
                if "bg" in options:
                    current = str(widget.cget("bg")).upper()
                    if current in surface_map:
                        widget.configure(bg=surface_map[current])
                for option in ("foreground", "fg", "activeforeground", "insertbackground"):
                    if option in options:
                        current = str(widget.cget(option)).upper()
                        if current in text_map:
                            widget.configure(**{option: text_map[current]})
                if "highlightbackground" in options and str(widget.cget("highlightbackground")).upper() == "#1E5FA8":
                    widget.configure(highlightbackground="#D7DDF5")
                if "selectcolor" in options and str(widget.cget("selectcolor")).upper() in surface_map:
                    widget.configure(selectcolor="#EEF2FF")
            except tk.TclError:
                pass
            for child in widget.winfo_children():
                restyle(child)

        restyle(self.root)

        # The dashboard log has semantic colors; keep them vivid on the light console.
        if hasattr(self, "txt_logs"):
            self.txt_logs.configure(bg="#F8FAFC", fg="#475569", insertbackground="#6366F1")
            for tag, color in {
                "time": "#94A3B8", "system": "#64748B", "info": "#3B82F6",
                "success": "#16A34A", "received": "#2563EB", "pipeline": "#7C3AED",
                "ai": "#8B5CF6", "sent": "#16A34A", "warning": "#D97706", "error": "#DC2626",
            }.items():
                self.txt_logs.tag_config(tag, foreground=color)

    def _setup_styles(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Light AI SaaS / VisionOS glass palette.
        self.COLOR_BG = "#F5F7FF"
        self.COLOR_CARD = "#FFFFFF"
        self.COLOR_HEADER = "#F8FAFF"
        self.COLOR_PRIMARY = "#6366F1"
        self.COLOR_SECONDARY = "#3B82F6"
        self.COLOR_SUCCESS = "#22C55E"
        self.COLOR_WARNING = "#F59E0B"
        self.COLOR_DANGER = "#EF4444"
        self.COLOR_TEXT = "#17213A"
        self.COLOR_MUTED = "#64748B"
        self.COLOR_BORDER = "#DDE4FA"

        self.root.configure(bg=self.COLOR_BG)

        # ttk 控件样式
        self.style.configure("TFrame", background=self.COLOR_BG)
        self.style.configure("Card.TFrame", background=self.COLOR_CARD, relief="flat")
        self.style.configure("TLabel", background=self.COLOR_BG, foreground=self.COLOR_TEXT, font=("Microsoft YaHei UI", 9))
        self.style.configure("Card.TLabel", background=self.COLOR_CARD, foreground=self.COLOR_TEXT, font=("Microsoft YaHei UI", 9))
        self.style.configure("Header.TLabel", background=self.COLOR_HEADER, foreground=self.COLOR_TEXT, font=("Microsoft YaHei UI", 12, "bold"))
        self.style.configure("Muted.TLabel", background=self.COLOR_CARD, foreground=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8))

        # Native ttk controls use the same visual language as the dashboard.
        # This changes only chrome; widget geometry and command bindings remain intact.
        self.style.configure(
            "TEntry", fieldbackground="#FFFFFF", foreground=self.COLOR_TEXT,
            insertcolor="#6366F1", bordercolor="#D7DDF5", lightcolor="#D7DDF5",
            darkcolor="#FFFFFF", padding=[7, 4]
        )
        self.style.map("TEntry", fieldbackground=[("focus", "#FFFFFF")], bordercolor=[("focus", "#A5B4FC")])
        self.style.configure(
            "TCombobox", fieldbackground="#FFFFFF", background="#FFFFFF",
            foreground=self.COLOR_TEXT, arrowcolor="#6366F1", bordercolor="#D7DDF5",
            lightcolor="#D7DDF5", darkcolor="#FFFFFF", padding=[6, 3]
        )
        self.style.map("TCombobox", fieldbackground=[("readonly", "#FFFFFF"), ("focus", "#FFFFFF")], foreground=[("readonly", self.COLOR_TEXT)])
        self.style.configure(
            "TButton", background="#FFFFFF", foreground="#4F46E5",
            bordercolor="#D7DDF5", lightcolor="#D7DDF5", darkcolor="#FFFFFF",
            padding=[10, 5], font=("Microsoft YaHei UI", 9, "bold")
        )
        self.style.map("TButton", background=[("active", "#EEF2FF"), ("pressed", "#E0E7FF")], foreground=[("active", "#4338CA")], bordercolor=[("active", "#A5B4FC")])
        self.style.configure("TCheckbutton", background=self.COLOR_CARD, foreground="#64748B", font=("Microsoft YaHei UI", 9))
        self.style.map("TCheckbutton", background=[("active", self.COLOR_CARD)], foreground=[("active", "#4338CA")])
        self.style.configure("TSpinbox", fieldbackground="#FFFFFF", foreground=self.COLOR_TEXT, arrowsize=12)
        self.style.configure("Horizontal.TScale", background=self.COLOR_CARD, troughcolor="#E7EAF8", sliderlength=16)
        self.style.configure("Cyber.Vertical.TScrollbar", background="#C7D2FE", troughcolor="#EEF2FF", bordercolor="#EEF2FF", arrowcolor="#6366F1", width=8)
        self.style.configure("TLabelframe", background=self.COLOR_CARD, foreground="#64748B", bordercolor="#D7DDF5")
        self.style.configure("TLabelframe.Label", background=self.COLOR_CARD, foreground="#6366F1", font=("Microsoft YaHei UI", 9, "bold"))

        self.style.configure("TNotebook", background=self.COLOR_BG, borderwidth=0)
        self.style.configure("TNotebook.Tab", padding=[16, 8], font=("Microsoft YaHei UI", 10, "bold"), background="#EEF2FF", foreground="#64748B")
        self.style.map("TNotebook.Tab", background=[("selected", self.COLOR_CARD)], foreground=[("selected", "#6366F1")])

        self.style.configure("Primary.TButton", font=("Microsoft YaHei UI", 9, "bold"), padding=[10, 5])
        self.style.configure("Success.TButton", font=("Microsoft YaHei UI", 9, "bold"), padding=[12, 6])
        self.style.configure("Danger.TButton", font=("Microsoft YaHei UI", 9, "bold"), padding=[12, 6])

        # Treeview 表格行高与现代深色样式配置
        self.style.configure(
            "Treeview",
            background="#FFFFFF",
            foreground=self.COLOR_TEXT,
            fieldbackground="#FFFFFF",
            font=("Microsoft YaHei UI", 9),
            rowheight=28
        )
        self.style.configure(
            "Treeview.Heading",
            background="#EEF2FF",
            foreground="#4F46E5",
            font=("Microsoft YaHei UI", 9, "bold")
        )
        self.style.map(
            "Treeview",
            background=[("selected", "#E0E7FF")],
            foreground=[("selected", "#4338CA")]
        )

    # -------------------------------------------------------------------------
    # 顶部状态与控制栏 (深色 AI 科技控制台设计)
    # -------------------------------------------------------------------------
    def _create_header_bar(self):
        header_frame = tk.Frame(self.root, bg=self.COLOR_HEADER, height=66)
        header_frame.pack(fill="x", side="top")

        # 左侧 LOGO 与主标题 (参考图 B 现代拟态微章设计)
        left_box = tk.Frame(header_frame, bg=self.COLOR_HEADER)
        left_box.pack(side="left", padx=20, pady=10)

        # 拟态发光机器人头像微章 (圆角发光暗蓝底 + 霓虹微光边框)
        f_avatar = CyberAvatar(left_box, size=44, bg=self.COLOR_HEADER)
        f_avatar.pack(side="left", padx=(0, 12))

        title_box = tk.Frame(left_box, bg=self.COLOR_HEADER)
        title_box.pack(side="left")

        lbl_title = tk.Label(
            title_box,
            text="WeChat-AIAgent 微信智能自动回复助手 v2.0",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg=self.COLOR_HEADER,
            fg=self.COLOR_TEXT
        )
        lbl_title.pack(anchor="w")

        self.lbl_wechat_status = tk.Label(
            title_box,
            text="● 正在检测微信状态...",
            font=("Microsoft YaHei UI", 9),
            bg=self.COLOR_HEADER,
            fg=self.COLOR_MUTED
        )
        self.lbl_wechat_status.pack(anchor="w")

        # 右侧操作区 (配置导出导入、主控制开关与刷新)
        right_box = tk.Frame(header_frame, bg=self.COLOR_HEADER)
        right_box.pack(side="right", padx=20, pady=10)

        self.btn_export = CyberPillButton(
            right_box,
            text="📤 导出配置",
            command=self._on_export_config_click,
            w=112,
            h=34,
            is_cta=False,
            bg=self.COLOR_HEADER
        )
        self.btn_export.pack(side="left", padx=5)

        self.btn_import = CyberPillButton(
            right_box,
            text="📥 导入配置",
            command=self._on_import_config_click,
            w=112,
            h=34,
            is_cta=False,
            bg=self.COLOR_HEADER
        )
        self.btn_import.pack(side="left", padx=5)

        self.btn_refresh = CyberPillButton(
            right_box,
            text="🔄 刷新状态",
            command=self._on_refresh_status_click,
            w=118,
            h=34,
            is_cta=False,
            bg=self.COLOR_HEADER
        )
        self.btn_refresh.pack(side="left", padx=8)

        self.btn_toggle_autoreply = CyberPillButton(
            right_box,
            text="▶ 开启自动回复",
            command=self._on_toggle_autoreply_click,
            w=152,
            h=34,
            is_cta=True,
            bg=self.COLOR_HEADER
        )
        self.btn_toggle_autoreply.pack(side="left", padx=8)

        # 底部科技蓝分割线
        tk.Frame(self.root, bg=self.COLOR_BORDER, height=1).pack(fill="x", side="top")

    # -------------------------------------------------------------------------
    # 主体竖向导航布局 (左侧功能侧边栏 + 右侧功能内容区)
    # -------------------------------------------------------------------------
    def _create_vertical_layout(self):
        self.main_container = tk.Frame(self.root, bg=self.COLOR_BG)
        self.main_container.pack(fill="both", expand=True)

        # 1. 左侧竖向功能导航菜单侧边栏 (固定宽度，浅色玻璃卡片)
        self.sidebar_frame = tk.Frame(self.main_container, bg="#FFFFFF", width=220, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1.5)
        self.sidebar_frame.pack(side="left", fill="y", padx=(10, 0), pady=(8, 8))
        self.sidebar_frame.pack_propagate(False)

        # 侧边栏顶部小标题指示
        nav_header = tk.Frame(self.sidebar_frame, bg="#FFFFFF", height=44)
        nav_header.pack(fill="x", side="top")
        tk.Label(
            nav_header,
            text="🎛️  功能导航菜单",
            font=("Microsoft YaHei UI", 10, "bold"),
            bg="#FFFFFF",
            fg="#334155"
        ).pack(side="left", padx=16, pady=11)

        # 竖向菜单项定义 (依序排列 8 个主要功能)
        self.nav_items = [
            ("dashboard", "📊  运行看板与实时日志"),
            ("targets",   "👥  回复对象配置"),
            ("llm",       "🧠  大模型配置"),
            ("rag",       "📚  本地知识库 (RAG)"),
            ("profiles",  "👤  联系人画像与记忆"),
            ("media",     "🎙️  多模态与媒体设置"),
            ("voip",      "📞  语音通话智能体"),
            ("sandbox",   "🧪  交互测试沙盒"),
        ]

        # 导航按钮容器
        btn_list_box = tk.Frame(self.sidebar_frame, bg="#FFFFFF")
        btn_list_box.pack(fill="x", padx=8, pady=10)

        self.nav_buttons: Dict[str, Any] = {}
        self.active_tab = "dashboard"

        for key, text in self.nav_items:
            btn = CyberSidebarItem(
                btn_list_box,
                text=text,
                command=lambda k=key: self._switch_tab(k),
                w=204,
                h=38,
                is_active=(key == self.active_tab)
            )
            btn.pack(fill="x", pady=2)
            self.nav_buttons[key] = btn

        # 侧边栏底部版本与就绪提示 (参考图 B 设计)
        side_footer = tk.Frame(self.sidebar_frame, bg="#FFFFFF")
        side_footer.pack(side="bottom", fill="x", pady=18, padx=12)
        tk.Label(
            side_footer,
            text="WeChat-AIAgent v2.0\nAI 让沟通更敏捷",
            font=("Microsoft YaHei UI", 8),
            bg="#FFFFFF",
            fg="#94A3B8",
            justify="center"
        ).pack(anchor="center")

        # 2. 右侧功能内容区域
        self.content_container = tk.Frame(self.main_container, bg=self.COLOR_BG)
        self.content_container.pack(side="right", fill="both", expand=True, padx=(8, 10), pady=(6, 8))

        # 构建 7 个功能子面板容器 (完全保留原有各面板内部控件树与事件处理)
        self.tab_dashboard = ttk.Frame(self.content_container)
        self._build_dashboard_tab()

        self.tab_targets = ttk.Frame(self.content_container)
        self._build_targets_tab()

        self.tab_llm = ttk.Frame(self.content_container)
        self._build_llm_tab()

        self.tab_rag = ttk.Frame(self.content_container)
        self._build_rag_tab()

        self.tab_profiles = ttk.Frame(self.content_container)
        self._build_profiles_tab()

        self.tab_media = ttk.Frame(self.content_container)
        self._build_media_tab()

        self.tab_voip = ttk.Frame(self.content_container)
        self.voip_builder.build_tab(self.tab_voip)

        self.tab_sandbox = ttk.Frame(self.content_container)
        self._build_sandbox_tab()

        self.tab_panels: Dict[str, ttk.Frame] = {
            "dashboard": self.tab_dashboard,
            "targets": self.tab_targets,
            "llm": self.tab_llm,
            "rag": self.tab_rag,
            "profiles": self.tab_profiles,
            "media": self.tab_media,
            "voip": self.tab_voip,
            "sandbox": self.tab_sandbox,
        }

        # 兼容性包装类 (防止旧逻辑引用 self.notebook 发生 AttributeError)
        class _NotebookCompat:
            def __init__(self, app):
                self.app = app
            def select(self, tab=None):
                if tab is not None:
                    for k, p in self.app.tab_panels.items():
                        if p == tab or k == tab:
                            self.app._switch_tab(k)
                            break
            def index(self, tab):
                return 0
        self.notebook = _NotebookCompat(self)

        # 默认激活 Tab 1: 运行看板与实时日志
        self._switch_tab("dashboard")

    def _switch_tab(self, tab_key: str):
        """切换右侧内容面板并更新左侧垂直导航项高亮"""
        if tab_key not in self.tab_panels:
            return
        self.active_tab = tab_key

        # 隐藏所有面板，展示当前选中的面板
        for key, panel in self.tab_panels.items():
            if key == tab_key:
                panel.pack(fill="both", expand=True)
            else:
                panel.pack_forget()

        # 更新左侧导航按钮视觉高亮 (深色 AI 科技蓝霓虹高亮)
        for key, btn in self.nav_buttons.items():
            if hasattr(btn, "set_active"):
                btn.set_active(key == tab_key)
            elif hasattr(btn, "configure"):
                if key == tab_key:
                    btn.configure(bg="#007BFF", fg="#ffffff")
                else:
                    btn.configure(bg="#07152B", fg="#7E97B8")

    # -------------------------------------------------------------------------
    # 底部状态栏
    # -------------------------------------------------------------------------
    def _create_status_bar(self):
        # 顶部精致科技蓝分割线
        tk.Frame(self.root, bg=self.COLOR_BORDER, height=1).pack(fill="x", side="bottom")

        status_bar = tk.Frame(self.root, bg="#F0F3FF", height=26)
        status_bar.pack(fill="x", side="bottom")

        self.lbl_status_left = tk.Label(
            status_bar,
            text="● 就绪 · 本地原生桌面 GUI",
            font=("Microsoft YaHei UI", 8),
            bg="#F0F3FF",
            fg="#16A34A"
        )
        self.lbl_status_left.pack(side="left", padx=12, pady=4)

        self.lbl_status_right = tk.Label(
            status_bar,
            text="微信 4.x 自动化 | 智能体架构正常 | LLM: " + (self.config.llm.model_name or "未配置"),
            font=("Microsoft YaHei UI", 8),
            bg="#F0F3FF",
            fg="#64748B"
        )
        self.lbl_status_right.pack(side="right", padx=12, pady=4)

    # -------------------------------------------------------------------------
    # Tab 1: 实时监控与日志看板
    # -------------------------------------------------------------------------
    def _build_dashboard_tab(self):
        parent = self.tab_dashboard

        # 顶部指标卡片 (参考图二深色霓虹玻璃拟态：圆角玻璃卡片 + 左侧发光圆环徽章 + 右侧大字号电光数值)
        metrics_frame = tk.Frame(parent, bg=self.COLOR_BG)
        metrics_frame.pack(fill="x", pady=(0, 6))

        # 4 列等权均分自适应，支持窗口拉动时动态伸缩且默认全部完整展示
        for i in range(4):
            metrics_frame.grid_columnconfigure(i, weight=1, uniform="stat_cards")

        self.card_val_received = DynamicCyberCard(metrics_frame, "今日接收消息", "0", "#3B82F6", "💬", (249, 251, 255), (199, 210, 254), (96, 165, 250))
        self.card_val_received.grid(row=0, column=0, sticky="nsew", padx=4, pady=2)

        self.card_val_replied = DynamicCyberCard(metrics_frame, "自动成功回复", "0", "#16A34A", "⚡", (247, 253, 249), (187, 247, 208), (74, 222, 128))
        self.card_val_replied.grid(row=0, column=1, sticky="nsew", padx=4, pady=2)

        self.card_val_ignored = DynamicCyberCard(metrics_frame, "规则过滤/忽略", "0", "#D97706", "⚠️", (255, 252, 246), (253, 230, 138), (251, 191, 36))
        self.card_val_ignored.grid(row=0, column=2, sticky="nsew", padx=4, pady=2)

        self.card_val_status = DynamicCyberCard(metrics_frame, "自动回复开关", "已暂停", "#64748B", "🛡️", (250, 248, 255), (221, 214, 254), (129, 140, 248), is_switch=True)
        self.card_val_status.grid(row=0, column=3, sticky="nsew", padx=4, pady=2)

        self.lbl_switch_pill = CyberSwitchPillProxy(self.card_val_status)

        # 日志流主区域 (深色 AI Agent 决策控制台，外包科技蓝霓虹边框)
        log_container = tk.Frame(parent, bg="#FFFFFF", bd=1, relief="solid", highlightbackground="#D7DDF5", highlightthickness=1.5)
        log_container.pack(fill="both", expand=True, padx=4, pady=2)

        # 日志工具栏 (⚡ 实时微信消息通知与智能体决策链路)
        tool_bar = tk.Frame(log_container, bg="#F1F4FF", height=36)
        tool_bar.pack(fill="x", side="top", padx=1, pady=1)

        tk.Label(
            tool_bar,
            text="⚡ 实时微信消息通知与智能体决策链路",
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#F1F4FF",
            fg="#334155"
        ).pack(side="left", padx=10, pady=5)

        self.var_autoscroll = tk.BooleanVar(value=True)
        chk_scroll = tk.Checkbutton(
            tool_bar,
            text="自动滚屏",
            variable=self.var_autoscroll,
            bg="#F1F4FF",
            fg="#64748B",
            selectcolor="#E0E7FF",
            activebackground="#F1F4FF",
            activeforeground="#334155",
            font=("Microsoft YaHei UI", 8)
        )
        chk_scroll.pack(side="right", padx=6)

        btn_copy = tk.Button(
            tool_bar,
            text="📋 复制日志",
            command=self._on_copy_logs,
            bg="#FFFFFF",
            fg="#4F46E5",
            activebackground="#EEF2FF",
            activeforeground="#4338CA",
            bd=1,
            relief="solid",
            highlightbackground="#D7DDF5",
            font=("Microsoft YaHei UI", 8),
            cursor="hand2",
            padx=8,
            pady=2
        )
        btn_copy.pack(side="right", padx=4)
        btn_copy.bind("<Enter>", lambda e, b=btn_copy: b.configure(bg="#EEF2FF", highlightbackground="#A5B4FC"))
        btn_copy.bind("<Leave>", lambda e, b=btn_copy: b.configure(bg="#FFFFFF", highlightbackground="#D7DDF5"))

        btn_clear = tk.Button(
            tool_bar,
            text="🧹 清空日志",
            command=self._on_clear_logs,
            bg="#FFFFFF",
            fg="#4F46E5",
            activebackground="#EEF2FF",
            activeforeground="#4338CA",
            bd=1,
            relief="solid",
            highlightbackground="#D7DDF5",
            font=("Microsoft YaHei UI", 8),
            cursor="hand2",
            padx=8,
            pady=2
        )
        btn_clear.pack(side="right", padx=4)
        btn_clear.bind("<Enter>", lambda e, b=btn_clear: b.configure(bg="#EEF2FF", highlightbackground="#A5B4FC"))
        btn_clear.bind("<Leave>", lambda e, b=btn_clear: b.configure(bg="#FFFFFF", highlightbackground="#D7DDF5"))

        btn_sync = tk.Button(
            tool_bar,
            text="🔄 同步微信最新消息",
            command=self._on_sync_recent_messages_click,
            bg="#EEF2FF",
            fg="#4F46E5",
            activebackground="#E0E7FF",
            activeforeground="#4338CA",
            bd=1,
            relief="solid",
            highlightbackground="#C7D2FE",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2",
            padx=10,
            pady=3
        )
        btn_sync.pack(side="right", padx=6)
        btn_sync.bind("<Enter>", lambda e, b=btn_sync: b.configure(bg="#E0E7FF", highlightbackground="#A5B4FC"))
        btn_sync.bind("<Leave>", lambda e, b=btn_sync: b.configure(bg="#EEF2FF", highlightbackground="#C7D2FE"))

        # 彩色日志输出框 (深色 AI Agent 实时决策控制台)
        self.txt_logs = scrolledtext.ScrolledText(
            log_container,
            wrap="word",
            bg="#F8FAFC",
            fg="#475569",
            font=("Consolas", 9),
            insertbackground="#6366F1",
            selectbackground="#C7D2FE",
            selectforeground="#1E1B4B",
            padx=10,
            pady=8,
            bd=0
        )
        self.txt_logs.pack(fill="both", expand=True, padx=1, pady=1)
        # Tk's native scrollbar has no CSS equivalent; style the existing
        # scrollbar in place so its width and geometry stay unchanged.
        self.txt_logs.vbar.configure(
            width=8, bg="#C7D2FE", troughcolor="#EEF2FF",
            activebackground="#818CF8", bd=0, relief="flat",
            highlightthickness=0
        )

        # 配置日志色彩标签 (严格遵循规范：深色背景高对比科技语法配色)
        self.txt_logs.tag_config("time", foreground="#607D9E")
        self.txt_logs.tag_config("system", foreground="#67A8FF")
        self.txt_logs.tag_config("info", foreground="#35B8FF")
        self.txt_logs.tag_config("success", foreground="#00E6A7", font=("Consolas", 9, "bold"))
        self.txt_logs.tag_config("received", foreground="#60A5FA", font=("Consolas", 9, "bold"))
        self.txt_logs.tag_config("pipeline", foreground="#B388FF")
        self.txt_logs.tag_config("ai", foreground="#B88CFF", font=("Consolas", 9, "bold"))
        self.txt_logs.tag_config("sent", foreground="#00E6A7", font=("Consolas", 9, "bold"))
        self.txt_logs.tag_config("warning", foreground="#FFB84D")
        self.txt_logs.tag_config("error", foreground="#FF5577", font=("Consolas", 9, "bold"))

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
        f_header = tk.Frame(left_frame, bg="#091B36")
        f_header.pack(fill="x", padx=8, pady=6)
        self.lbl_contacts_header = tk.Label(
            f_header,
            text="👤 通讯录真实好友 (已勾选: 0 / 共 0 人)",
            font=("Microsoft YaHei UI", 10, "bold"),
            bg="#091B36",
            fg="#DCEEFF"
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
            fg=self.COLOR_TEXT,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
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

        # 配置选中行与未选中行的高对比色彩 Tag (Cyberpunk 深蓝科技主题)
        self.tree_contacts.tag_configure("checked", background="#0C2B54", foreground="#38BDF8")
        self.tree_contacts.tag_configure("unchecked", background="#091830", foreground="#F3F7FF")

        c_scroll = ttk.Scrollbar(c_tree_frame, orient="vertical", command=self.tree_contacts.yview)
        self.tree_contacts.configure(yscrollcommand=c_scroll.set)
        self.tree_contacts.pack(side="left", fill="both", expand=True)
        c_scroll.pack(side="right", fill="y")

        self.tree_contacts.bind("<ButtonRelease-1>", self._on_contact_tree_click)

        # ----------------- 右侧：微信群聊列表 -----------------
        right_frame = tk.Frame(paned, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        paned.add(right_frame, minsize=420)

        g_header = tk.Frame(right_frame, bg="#091B36")
        g_header.pack(fill="x", padx=8, pady=6)
        self.lbl_groups_header = tk.Label(
            g_header,
            text="👥 微信群聊会话 (已勾选: 0 / 共 0 个)",
            font=("Microsoft YaHei UI", 10, "bold"),
            bg="#091B36",
            fg="#DCEEFF"
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
        chk_all_groups = tk.Checkbutton(
            g_options,
            text="允许回复所有群聊",
            variable=self.var_reply_all_groups,
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
            font=("Microsoft YaHei UI", 8)
        )
        chk_all_groups.pack(side="left", padx=2)

        self.var_group_at_only = tk.BooleanVar(value=self.config.targets.group_at_only)
        chk_at_only = tk.Checkbutton(
            g_options,
            text="仅在被 @ 时才回复 (推荐)",
            variable=self.var_group_at_only,
            bg=self.COLOR_CARD,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
            font=("Microsoft YaHei UI", 8, "bold"),
            fg=self.COLOR_PRIMARY
        )
        chk_at_only.pack(side="left", padx=8)

        self.var_group_auto_at = tk.BooleanVar(value=self.config.targets.group_auto_at_sender)
        chk_auto_at = tk.Checkbutton(
            g_options,
            text="回复时自动 @ 提问者",
            variable=self.var_group_auto_at,
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
            font=("Microsoft YaHei UI", 8)
        )
        chk_auto_at.pack(side="left", padx=2)

        # 鼠标右键设置快捷提示
        g_hint_bar = tk.Frame(right_frame, bg=self.COLOR_CARD)
        g_hint_bar.pack(fill="x", padx=8, pady=(0, 2))
        lbl_hint_g = tk.Label(
            g_hint_bar,
            text="💡 提示：在任意群聊名称上【鼠标右键】可弹出【单独设置此群聊】(管理者Master与黑名单)",
            bg=self.COLOR_CARD,
            fg="#38BDF8",
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

        # 配置群聊选中行与未选中行的高对比色彩 Tag (Cyberpunk 深蓝科技主题)
        self.tree_groups.tag_configure("checked", background="#0C2B54", foreground="#38BDF8")
        self.tree_groups.tag_configure("unchecked", background="#091830", foreground="#F3F7FF")

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
            activebackground="#6D35FF",
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
            fg=self.COLOR_TEXT
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
            fg=self.COLOR_TEXT
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
            fg=self.COLOR_TEXT
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
        # 卡片 5: 群成员专属用户画像与永久记忆开关 (默认全部关闭，需自定义开启)
        # ---------------------------------------------------------------------
        card5 = tk.Frame(content_frame, bg=self.COLOR_CARD, padx=16, pady=12, relief="solid", bd=1)
        card5.pack(fill="x", padx=16, pady=(8, 16))

        lbl_c5_title = tk.Label(
            card5,
            text="👤 群成员专属用户画像与永久记忆设置",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT
        )
        lbl_c5_title.pack(anchor="w")

        var_enable_member_profile = tk.BooleanVar(value=getattr(g_cfg, "enable_member_profile", False))
        chk_member_profile = tk.Checkbutton(
            card5,
            text="启用本群群成员专属画像与永久记忆 (默认关闭)",
            variable=var_enable_member_profile,
            bg=self.COLOR_CARD,
            font=("Microsoft YaHei UI", 9, "bold"),
            fg=self.COLOR_PRIMARY
        )
        chk_member_profile.pack(anchor="w", pady=(8, 2))
        tk.Label(
            card5,
            text="提示: 开启后，AI将根据每位群成员历史发言建立独立档案，持续自完善并在回复时注入记忆；默认关闭以节省Token和算力。",
            font=("Microsoft YaHei UI", 8),
            bg=self.COLOR_CARD,
            fg=self.COLOR_MUTED
        ).pack(anchor="w")

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
            g_cfg.enable_member_profile = var_enable_member_profile.get()

            self.config.groups_config[chatroom_id] = g_cfg
            self.config.save()

            # 刷新群聊列表的徽标
            self._render_groups_tree()

            messagebox.showinfo(
                "保存成功",
                f"群聊【{group_name}】专属管理配置已保存生效！\n\n"
                f"• 管理者(Master): {len(g_cfg.masters)} 人\n"
                f"• 永久黑名单: {len(g_cfg.blacklist)} 人\n"
                f"• 微信踢人权限: {'已启用' if g_cfg.is_admin_or_owner else '未启用'}\n"
                f"• 群成员专属画像: {'已启用' if g_cfg.enable_member_profile else '已关闭'}",
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
        if hasattr(self, "call_agent") and self.call_agent:
            self.call_agent.reload_config(self.config)
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
        canvas_win = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_win, width=e.width))
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
        btn_show_key = tk.Checkbutton(
            grid_f,
            text="显示",
            variable=self.var_show_key,
            command=self._toggle_key_visibility,
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
            font=("Microsoft YaHei UI", 8)
        )
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
            bg="#007BFF",
            fg="#ffffff",
            activebackground="#6D35FF",
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
            bg="#0F2444",
            fg="#8CCBFF",
            activebackground="#163866",
            activeforeground="#38BDF8",
            bd=1,
            relief="solid",
            highlightbackground="#1E4E8C",
            padx=10,
            pady=4,
            cursor="hand2"
        )
        self.btn_test_llm.grid(row=2, column=3, sticky="w", padx=6, pady=6)

        self.lbl_llm_test_result = tk.Label(grid_f, text="", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 8))
        self.lbl_llm_test_result.grid(row=3, column=1, columnspan=3, sticky="w", padx=6)

        grid_f.columnconfigure(1, weight=1)

        # 推理调节参数 (温度)
        param_f = tk.Frame(card_llm, bg=self.COLOR_CARD)
        param_f.pack(fill="x", padx=16, pady=(4, 12))

        tk.Label(param_f, text="模型采样温度 (Temperature):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        self.var_temp = tk.DoubleVar(value=self.config.llm.temperature if self.config.llm.temperature is not None else 0.7)
        sp_temp = ttk.Spinbox(param_f, from_=0.0, to=2.0, increment=0.1, textvariable=self.var_temp, width=6)
        sp_temp.grid(row=0, column=1, padx=6)
        tk.Label(param_f, text="(0.0~2.0，建议0.7，值越低回答越严谨规范；生成长度由模型根据实际情况自适应判定)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=0, column=2, sticky="w", padx=(0, 20))

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
            bg="#0F2444",
            fg="#8CCBFF",
            activebackground="#163866",
            activeforeground="#38BDF8",
            bd=1,
            relief="solid",
            highlightbackground="#1E4E8C",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2",
            padx=8,
            pady=3
        )
        btn_add_preset.pack(side="left", padx=2)

        btn_update_preset = tk.Button(
            p_frame,
            text="💾 保存为人设模板",
            command=self._on_update_preset_click,
            bg="#0F2444",
            fg="#8CCBFF",
            activebackground="#163866",
            activeforeground="#38BDF8",
            bd=1,
            relief="solid",
            highlightbackground="#1E4E8C",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2",
            padx=8,
            pady=3
        )
        btn_update_preset.pack(side="left", padx=2)

        btn_rename_preset = tk.Button(
            p_frame,
            text="✏️ 重命名",
            command=self._on_rename_preset_click,
            bg="#0F2444",
            fg="#8CCBFF",
            activebackground="#163866",
            activeforeground="#38BDF8",
            bd=1,
            relief="solid",
            highlightbackground="#1E4E8C",
            font=("Microsoft YaHei UI", 8),
            cursor="hand2",
            padx=8,
            pady=3
        )
        btn_rename_preset.pack(side="left", padx=2)

        btn_del_preset = tk.Button(
            p_frame,
            text="🗑️ 删除人设",
            command=self._on_delete_preset_click,
            bg="#2E1120",
            fg="#FF5577",
            activebackground="#451825",
            activeforeground="#FF5577",
            bd=1,
            relief="solid",
            highlightbackground="#5C1D30",
            font=("Microsoft YaHei UI", 8),
            cursor="hand2",
            padx=8,
            pady=3
        )
        btn_del_preset.pack(side="left", padx=2)

        btn_restore_presets = tk.Button(
            p_frame,
            text="↺ 恢复内置",
            command=self._on_restore_default_presets_click,
            bg="#0F2444",
            fg="#8CCBFF",
            activebackground="#163866",
            activeforeground="#38BDF8",
            bd=1,
            relief="solid",
            highlightbackground="#1E4E8C",
            font=("Microsoft YaHei UI", 8),
            cursor="hand2",
            padx=8,
            pady=3
        )
        btn_restore_presets.pack(side="left", padx=2)

        tk.Label(card_prompt, text="系统提示词 (System Prompt - 决定微信回复时的角色定位、专业范围与沟通口吻):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=16, pady=(10, 4))
        self.txt_prompt = scrolledtext.ScrolledText(
            card_prompt,
            wrap="word",
            height=5,
            font=("Microsoft YaHei UI", 9),
            bg="#06111F",
            fg="#A8C7E8",
            insertbackground="#00E5FF",
            selectbackground="#1E3A8A",
            selectforeground="#F3F7FF",
            bd=1,
            relief="solid",
            highlightbackground=self.COLOR_BORDER,
            highlightthickness=1
        )
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
        sec1 = tk.LabelFrame(card_safety, text=" 👤 人工接管与客服风控 (Human Handover) ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#38BDF8", padx=12, pady=8)
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
        sec2 = tk.LabelFrame(card_safety, text=" 🏷️ 回复修饰与品牌标识 (Format & Branding) ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#60A5FA", padx=12, pady=8)
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
        sec3 = tk.LabelFrame(card_safety, text=" ⚡ 防刷频与频率风控 (Anti-Spam & Rate Limiting) ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#FFB84D", padx=12, pady=8)
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
        sec4 = tk.LabelFrame(card_safety, text=" 🚫 敏感词合规过滤 (Content Moderation) ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#FF5577", padx=12, pady=8)
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
        sec5 = tk.LabelFrame(card_safety, text=" 🧩 扩展工具与插件能力 (Function Calling) ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#A78BFA", padx=12, pady=8)
        sec5.pack(fill="x", padx=16, pady=(6, 12))

        self.var_enable_tools = tk.BooleanVar(value=bool(getattr(self.config.safety, "enable_tools", True)))
        chk_tools = tk.Checkbutton(
            sec5,
            text="启用扩展插件与工具调用能力 (允许大模型根据需要自主调用天气查询、计算器、专业分诊等内部函数工具)",
            variable=self.var_enable_tools,
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
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
            activebackground="#6D35FF",
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

    def _on_restore_default_presets_click(self):
        """恢复并补齐所有官方内置预设提示词模板"""
        if not messagebox.askyesno("恢复内置人设", "是否确认补齐所有官方内置预设人设？\n现有自定义人设仍会予以保留。"):
            return
        from agent_core.config import PROMPT_PRESETS
        for k, v in PROMPT_PRESETS.items():
            if k not in self.presets:
                self.presets[k] = v
        self.config.safety.presets = dict(self.presets)
        self.config.save()
        curr_selected = self.var_preset.get().strip()
        if curr_selected not in self.presets:
            curr_selected = list(self.presets.keys())[0]
        self._refresh_presets_combobox(curr_selected)
        messagebox.showinfo("成功", "已成功补齐所有官方内置人设！")

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

    def _on_fetch_voice_cloud_models_click(self):
        """一键获取云端 ASR 上游可用模型列表（复用 LLM get_models 接口）"""
        api_url = self.var_voice_cloud_url.get().strip()
        api_key = self.var_voice_cloud_key.get().strip()

        if not api_url:
            messagebox.showwarning("提示", "请先填写云端 ASR API Base URL！")
            return

        self.btn_fetch_voice_cloud_models.configure(text="⏳ 获取中...", state="disabled")

        def worker():
            try:
                ok, model_list, msg = self.llm_client.get_models(api_url=api_url, api_key=api_key)
                def on_done():
                    self.btn_fetch_voice_cloud_models.configure(text="🔍 获取模型", state="normal")
                    if ok and model_list:
                        # 过滤出常见语音识别相关模型（优先展示），其余追加
                        asr_keywords = ["whisper", "audio", "transcribe", "asr", "speech"]
                        asr_models = [m for m in model_list if any(k in m.lower() for k in asr_keywords)]
                        other_models = [m for m in model_list if m not in asr_models]
                        sorted_list = asr_models + other_models
                        self.cb_voice_cloud_model["values"] = sorted_list
                        # 当前值不在列表中则自动选第一个
                        if self.var_voice_cloud_model.get() not in sorted_list and sorted_list:
                            self.var_voice_cloud_model.set(sorted_list[0])
                        messagebox.showinfo("成功", f"成功拉取到 {len(sorted_list)} 个可用模型！\n已更新下拉列表，语音识别相关模型已优先排序。")
                    else:
                        messagebox.showwarning("提示", f"未能获取到模型列表：\n{msg}")
                self.dispatch_ui(on_done)
            except Exception as e:
                def on_err():
                    self.btn_fetch_voice_cloud_models.configure(text="🔍 获取模型", state="normal")
                    messagebox.showerror("获取失败", f"无法拉取上游模型列表：\n{e}")
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
        if hasattr(self, "var_max_tokens"):
            try:
                self.config.llm.max_tokens = int(self.var_max_tokens.get())
            except Exception:
                self.config.llm.max_tokens = None
        else:
            self.config.llm.max_tokens = None
        
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
        if hasattr(self, "call_agent") and self.call_agent:
            self.call_agent.reload_config(self.config)
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
        chk_rag = tk.Checkbutton(
            card,
            text="启用本地 RAG 知识库功能 (知识库文档将参与大模型推理补充)",
            variable=self.var_rag_enabled,
            bg=self.COLOR_CARD,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
            font=("Microsoft YaHei UI", 9, "bold"),
            fg=self.COLOR_PRIMARY
        )
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
            bg="#0F2444",
            fg="#8CCBFF",
            activebackground="#163866",
            activeforeground="#38BDF8",
            bd=1,
            relief="solid",
            highlightbackground="#1E4E8C",
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
            activebackground="#6D35FF",
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

        self.txt_rag_results = scrolledtext.ScrolledText(
            card,
            wrap="word",
            height=5,
            font=("Microsoft YaHei UI", 9),
            bg="#06111F",
            fg="#A8C7E8",
            insertbackground="#00E5FF",
            selectbackground="#1E3A8A",
            selectforeground="#F3F7FF",
            bd=1,
            relief="solid",
            highlightbackground=self.COLOR_BORDER,
            highlightthickness=1
        )
        self.txt_rag_results.pack(fill="x", padx=16, pady=6)

        # 保存按钮
        btn_save_rag = tk.Button(
            card,
            text="💾 保存知识库配置",
            command=self._on_save_rag_click,
            font=("Microsoft YaHei UI", 10, "bold"),
            bg=self.COLOR_PRIMARY,
            fg="#ffffff",
            activebackground="#6D35FF",
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
                res = self.rag_engine.reindex(folder, force=True)
                if not res.get("success", False):
                    raise RuntimeError(res.get("message", "构建索引失败"))

                # 保存配置
                self.config.save()
                doc_cnt = res.get("doc_count", 0)
                chunk_cnt = res.get("chunk_count", 0)

                def on_done():
                    self.var_rag_enabled.set(True)
                    self.btn_build_index.configure(text="⚡ 建立/更新本地索引", state="normal")
                    self.lbl_rag_status.configure(text=f"✅ 索引就绪：共 {doc_cnt} 个文档，{chunk_cnt} 个切片片段", fg=self.COLOR_SUCCESS)
                    messagebox.showinfo("构建完成", f"知识库索引构建成功！\n\n- 文档数: {doc_cnt}\n- 知识切片数: {chunk_cnt}\n- 知识库已自动开启，将在自动回复时生效。")
                self.dispatch_ui(on_done)
            except Exception as e:
                err_msg = str(e)
                def on_err():
                    self.btn_build_index.configure(text="⚡ 建立/更新本地索引", state="normal")
                    self.lbl_rag_status.configure(text=f"❌ 构建失败: {err_msg[:40]}", fg=self.COLOR_DANGER)
                    messagebox.showerror("构建失败", f"构建本地知识库索引出现异常:\n{err_msg}")
                self.dispatch_ui(on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_rag_query_click(self):
        query = self.var_rag_query.get().strip()
        if not query:
            messagebox.showwarning("提示", "请输入测试查询语句！")
            return

        if not self.rag_engine.is_indexed:
            self.txt_rag_results.delete("1.0", "end")
            self.txt_rag_results.insert("1.0", "⚠️ 当前知识库尚未建立索引！\n请先在上方点击【⚡ 建立/更新本地索引】后再进行检索测试。")
            return

        hits = self.rag_engine.search(query, top_k=3, ignore_enabled_flag=True)
        self.txt_rag_results.delete("1.0", "end")
        if not hits:
            self.txt_rag_results.insert("1.0", "未检索到匹配的知识库切片（可能相似度低于阈值，或知识库中无相关内容）。\n建议尝试更换更精准的关键词。")
        else:
            out_lines = []
            for i, h in enumerate(hits, 1):
                score = h.get("score", 0.0)
                fname = h.get("file_name") or h.get("metadata", {}).get("source", "未知文档")
                content = h.get("content") or h.get("text", "")
                out_lines.append(f"【命中 {i}】相似度: {score} | 来源文档: 《{fname}》\n--------------------------------------------------\n{content.strip()}\n")
            self.txt_rag_results.insert("1.0", "\n".join(out_lines))

    def _on_save_rag_click(self):
        self.config.rag.enabled = self.var_rag_enabled.get()
        new_path = self.var_rag_path.get().strip()
        path_changed = (new_path != (self.config.rag.kb_folder_path or ""))
        self.config.rag.kb_folder_path = new_path
        self.config.save()
        self.rag_engine.reload_config(self.config.rag)
        if path_changed and new_path and os.path.isdir(new_path):
            if messagebox.askyesno("知识库路径已更改", "检测到知识库文件夹路径已更新，是否立即重新构建本地索引？"):
                self._on_build_rag_index_click()
                return
        messagebox.showinfo("成功", "本地 RAG 知识库配置已成功保存！")

    # -------------------------------------------------------------------------
    # Tab: 联系人专属画像与永久记忆 (Contact Profiles & Long-term Memory)
    # -------------------------------------------------------------------------
    def _build_profiles_tab(self):
        parent = self.tab_profiles

        # 1. 顶部全局配置栏
        card_cfg = tk.Frame(parent, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        card_cfg.pack(fill="x", padx=16, pady=(10, 6))

        top_header = tk.Frame(card_cfg, bg=self.COLOR_CARD)
        top_header.pack(fill="x", padx=14, pady=(8, 4))

        tk.Label(
            top_header,
            text="👤 联系人专属用户画像与永久记忆库 (Memory Engine)",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT
        ).pack(side="left")

        btn_save_pcfg = tk.Button(
            top_header,
            text="💾 保存画像全局配置",
            command=self._on_save_profile_global_config,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg=self.COLOR_PRIMARY,
            fg="#ffffff",
            activebackground="#6D35FF",
            relief="flat",
            padx=12,
            pady=3,
            cursor="hand2"
        )
        btn_save_pcfg.pack(side="right")

        f_switches = tk.Frame(card_cfg, bg=self.COLOR_CARD)
        f_switches.pack(fill="x", padx=14, pady=(2, 8))

        self.var_profile_enabled = tk.BooleanVar(value=self.config.profile.enabled)
        chk_p_en = tk.Checkbutton(
            f_switches,
            text="启用联系人画像总开关",
            variable=self.var_profile_enabled,
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
            font=("Microsoft YaHei UI", 9, "bold")
        )
        chk_p_en.pack(side="left", padx=(0, 16))

        self.var_profile_private = tk.BooleanVar(value=self.config.profile.enable_private_chat)
        chk_p_priv = tk.Checkbutton(
            f_switches,
            text="私聊好友自动启用画像",
            variable=self.var_profile_private,
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
            font=("Microsoft YaHei UI", 9)
        )
        chk_p_priv.pack(side="left", padx=(0, 16))

        self.var_profile_auto_refine = tk.BooleanVar(value=self.config.profile.auto_refine)
        chk_p_refine = tk.Checkbutton(
            f_switches,
            text="对话中自动增量自完善/纠偏",
            variable=self.var_profile_auto_refine,
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
            font=("Microsoft YaHei UI", 9)
        )
        chk_p_refine.pack(side="left", padx=(0, 16))

        self.var_profile_inject = tk.BooleanVar(value=self.config.profile.inject_prompt)
        chk_p_inj = tk.Checkbutton(
            f_switches,
            text="将记忆摘要注入大模型Prompt",
            variable=self.var_profile_inject,
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
            font=("Microsoft YaHei UI", 9)
        )
        chk_p_inj.pack(side="left")

        # 提示语
        tk.Label(
            card_cfg,
            text="💡 说明: 群聊成员画像默认全部关闭，请在「👥 回复对象配置」中选中群聊并在专属设置中按需开启。",
            font=("Microsoft YaHei UI", 8),
            bg=self.COLOR_CARD,
            fg=self.COLOR_MUTED
        ).pack(anchor="w", padx=14, pady=(0, 6))

        # 2. 下方主双栏容器 (左侧搜索与列表，右侧立体画像卡片)
        main_body = tk.Frame(parent, bg=self.COLOR_BG)
        main_body.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        # -------------------- 左栏: 联系人搜索与选择列表 --------------------
        left_panel = tk.Frame(main_body, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1, width=350)
        left_panel.pack(side="left", fill="y", padx=(0, 8))
        left_panel.pack_propagate(False)

        # 搜索过滤条
        f_p_search = tk.Frame(left_panel, bg=self.COLOR_CARD)
        f_p_search.pack(fill="x", padx=10, pady=(10, 6))

        self.var_profile_search = tk.StringVar()
        self.var_profile_search.trace_add("write", self._on_profile_search_change)
        ent_p_search = ttk.Entry(f_p_search, textvariable=self.var_profile_search, font=("Microsoft YaHei UI", 9))
        ent_p_search.pack(fill="x")

        # 类别筛选标签
        f_p_filter = tk.Frame(left_panel, bg=self.COLOR_CARD)
        f_p_filter.pack(fill="x", padx=10, pady=(0, 6))

        self.var_profile_filter_type = tk.StringVar(value="all")
        for val, label in [("all", "全部"), ("profiles", "已建档"), ("private", "私聊"), ("group", "群成员")]:
            rb = tk.Radiobutton(
                f_p_filter,
                text=label,
                variable=self.var_profile_filter_type,
                value=val,
                command=self._load_profiles_into_tree,
                bg=self.COLOR_CARD,
                fg=self.COLOR_TEXT,
                selectcolor="#06111F",
                activebackground=self.COLOR_CARD,
                activeforeground="#38BDF8",
                font=("Microsoft YaHei UI", 8)
            )
            rb.pack(side="left", padx=2)

        # Treeview 表格
        tree_scroll = ttk.Scrollbar(left_panel)
        tree_scroll.pack(side="right", fill="y")

        self.tree_profiles = ttk.Treeview(
            left_panel,
            columns=("name", "type", "identity", "facts"),
            show="headings",
            selectmode="browse",
            yscrollcommand=tree_scroll.set
        )
        tree_scroll.config(command=self.tree_profiles.yview)

        self.tree_profiles.heading("name", text="姓名/实体")
        self.tree_profiles.heading("type", text="类别")
        self.tree_profiles.heading("identity", text="身份定位")
        self.tree_profiles.heading("facts", text="记忆数")

        self.tree_profiles.column("name", width=145, anchor="w")
        self.tree_profiles.column("type", width=50, anchor="center")
        self.tree_profiles.column("identity", width=95, anchor="w")
        self.tree_profiles.column("facts", width=55, anchor="center")

        self.tree_profiles.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.tree_profiles.bind("<<TreeviewSelect>>", self._on_profile_tree_select)

        # 底部操作栏
        f_p_bops = tk.Frame(left_panel, bg=self.COLOR_CARD)
        f_p_bops.pack(fill="x", padx=10, pady=8)

        ttk.Button(f_p_bops, text="🔄 刷新列表", command=self._load_profiles_into_tree).pack(side="left", padx=(0, 6))
        ttk.Button(f_p_bops, text="➕ 手动建档", command=self._on_manual_create_profile).pack(side="left")

        # -------------------- 右栏: 立体画像详情卡片 --------------------
        self.right_profile_panel = tk.Frame(main_body, bg=self.COLOR_BG)
        self.right_profile_panel.pack(side="right", fill="both", expand=True)

        # 空白未选提示
        self.p_empty_tip = tk.Frame(self.right_profile_panel, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        self.p_empty_tip.pack(fill="both", expand=True)

        tk.Label(
            self.p_empty_tip,
            text="👈 请从左侧列表中选择或搜索联系人\n\n以查看、编辑该对象的专属立体画像、永久事实记忆与自完善历史",
            font=("Microsoft YaHei UI", 11),
            bg=self.COLOR_CARD,
            fg=self.COLOR_MUTED,
            justify="center"
        ).pack(expand=True)

        # 详情卡片主容器 (可垂直滚动)
        self.p_detail_frame = tk.Frame(self.right_profile_panel, bg=self.COLOR_BG)

        p_canvas = tk.Canvas(self.p_detail_frame, bg=self.COLOR_BG, highlightthickness=0)
        p_scroll = ttk.Scrollbar(self.p_detail_frame, orient="vertical", command=p_canvas.yview)
        self.p_scroll_content = tk.Frame(p_canvas, bg=self.COLOR_BG)

        self.p_scroll_content.bind(
            "<Configure>",
            lambda e: p_canvas.configure(scrollregion=p_canvas.bbox("all"))
        )
        p_canvas_win = p_canvas.create_window((0, 0), window=self.p_scroll_content, anchor="nw")
        p_canvas.bind("<Configure>", lambda e: p_canvas.itemconfig(p_canvas_win, width=e.width))
        p_canvas.configure(yscrollcommand=p_scroll.set)

        p_canvas.pack(side="left", fill="both", expand=True)
        p_scroll.pack(side="right", fill="y")

        # 当前选中的联系人数据缓存
        self.current_selected_person_id = ""
        self.current_selected_profile: Optional[ContactProfile] = None

        # 构造右侧画像各卡片控件
        self._build_profile_card_widgets(self.p_scroll_content)

        # 初始加载树
        self.root.after(200, self._load_profiles_into_tree)

    def _build_profile_card_widgets(self, parent: tk.Frame):
        """构建右侧画像卡片的内部控件"""
        # 卡片 1: 顶部 Header 与操作栏
        card1 = tk.Frame(parent, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        card1.pack(fill="x", pady=(0, 8))

        f_hdr = tk.Frame(card1, bg=self.COLOR_CARD)
        f_hdr.pack(fill="x", padx=16, pady=10)

        self.lbl_p_avatar = tk.Label(f_hdr, text="👤", font=("Microsoft YaHei UI", 26), bg="#0D2750", fg="#38BDF8", width=3)
        self.lbl_p_avatar.pack(side="left", padx=(0, 12))

        f_hdr_txt = tk.Frame(f_hdr, bg=self.COLOR_CARD)
        f_hdr_txt.pack(side="left", fill="x", expand=True)

        self.lbl_p_name = tk.Label(f_hdr_txt, text="联系人姓名", font=("Microsoft YaHei UI", 13, "bold"), bg=self.COLOR_CARD, fg=self.COLOR_TEXT)
        self.lbl_p_name.pack(anchor="w")

        self.lbl_p_meta = tk.Label(f_hdr_txt, text="实体ID: xxx | 类型: 私聊 | 互动: 0次", font=("Microsoft YaHei UI", 8), bg=self.COLOR_CARD, fg=self.COLOR_MUTED)
        self.lbl_p_meta.pack(anchor="w", pady=(2, 0))

        # 按钮栏
        f_actions = tk.Frame(card1, bg=self.COLOR_CARD)
        f_actions.pack(fill="x", padx=16, pady=(0, 10))

        self.btn_p_rebuild = tk.Button(
            f_actions,
            text="🔍 基于已有聊天记录分析/重建画像",
            command=self._on_rebuild_selected_profile,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#0F2444",
            fg="#8CCBFF",
            activebackground="#163866",
            activeforeground="#38BDF8",
            bd=1,
            relief="solid",
            highlightbackground="#1E4E8C",
            padx=12,
            pady=5,
            cursor="hand2"
        )
        self.btn_p_rebuild.pack(side="left", padx=(0, 8))

        btn_p_save = tk.Button(
            f_actions,
            text="💾 保存手动调整",
            command=self._on_save_selected_profile,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#00E6A7",
            fg="#050B18",
            activebackground="#059669",
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=5,
            cursor="hand2"
        )
        btn_p_save.pack(side="left", padx=(0, 8))

        btn_p_del = tk.Button(
            f_actions,
            text="🗑️ 清除该画像记忆",
            command=self._on_delete_selected_profile,
            font=("Microsoft YaHei UI", 9),
            bg="#2E1120",
            fg="#FF5577",
            activebackground="#451825",
            activeforeground="#FF5577",
            bd=1,
            relief="solid",
            highlightbackground="#5C1D30",
            padx=10,
            pady=5,
            cursor="hand2"
        )
        btn_p_del.pack(side="right")

        # 卡片 2: 多维立体属性表单
        card2 = tk.Frame(parent, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        card2.pack(fill="x", pady=(0, 8))

        tk.Label(card2, text="📋 核心属性与偏好画像", font=("Microsoft YaHei UI", 10, "bold"), bg=self.COLOR_CARD, fg=self.COLOR_TEXT).pack(anchor="w", padx=16, pady=(10, 6))

        f_grid = tk.Frame(card2, bg=self.COLOR_CARD)
        f_grid.pack(fill="x", padx=16, pady=(0, 12))

        # 身份属性
        tk.Label(f_grid, text="身份定位:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=4)
        self.var_p_identity = tk.StringVar()
        ent_p_id = ttk.Entry(f_grid, textvariable=self.var_p_identity, font=("Microsoft YaHei UI", 9), width=35)
        ent_p_id.grid(row=0, column=1, sticky="ew", padx=(8, 20), pady=4)

        # 标签
        tk.Label(f_grid, text="标签 (逗号隔开):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=2, sticky="w", pady=4)
        self.var_p_tags = tk.StringVar()
        ent_p_tags = ttk.Entry(f_grid, textvariable=self.var_p_tags, font=("Microsoft YaHei UI", 9), width=35)
        ent_p_tags.grid(row=0, column=3, sticky="ew", padx=(8, 0), pady=4)

        # 性格特质
        tk.Label(f_grid, text="性格特点:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=1, column=0, sticky="w", pady=4)
        self.var_p_personality = tk.StringVar()
        ent_p_pers = ttk.Entry(f_grid, textvariable=self.var_p_personality, font=("Microsoft YaHei UI", 9), width=35)
        ent_p_pers.grid(row=1, column=1, sticky="ew", padx=(8, 20), pady=4)

        # 沟通偏好
        tk.Label(f_grid, text="沟通风格偏好:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=1, column=2, sticky="w", pady=4)
        self.var_p_comm_style = tk.StringVar()
        ent_p_comm = ttk.Entry(f_grid, textvariable=self.var_p_comm_style, font=("Microsoft YaHei UI", 9), width=35)
        ent_p_comm.grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=4)

        # 兴趣业务
        tk.Label(f_grid, text="业务/兴趣关注:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=2, column=0, sticky="w", pady=4)
        self.var_p_interests = tk.StringVar()
        ent_p_int = ttk.Entry(f_grid, textvariable=self.var_p_interests, font=("Microsoft YaHei UI", 9), width=35)
        ent_p_int.grid(row=2, column=1, sticky="ew", padx=(8, 20), pady=4)

        # 当前核心事项
        tk.Label(f_grid, text="当前核心事项:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).grid(row=2, column=2, sticky="w", pady=4)
        self.var_p_focus = tk.StringVar()
        ent_p_foc = ttk.Entry(f_grid, textvariable=self.var_p_focus, font=("Microsoft YaHei UI", 9), width=35)
        ent_p_foc.grid(row=2, column=3, sticky="ew", padx=(8, 0), pady=4)

        f_grid.columnconfigure(1, weight=1)
        f_grid.columnconfigure(3, weight=1)

        # 卡片 3: 关键事实永久记忆清单 (Fact Memories)
        card3 = tk.Frame(parent, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        card3.pack(fill="x", pady=(0, 8))

        f_c3_top = tk.Frame(card3, bg=self.COLOR_CARD)
        f_c3_top.pack(fill="x", padx=16, pady=(10, 4))

        tk.Label(f_c3_top, text="📌 关键事实永久记忆清单 (Fact Memories)", font=("Microsoft YaHei UI", 10, "bold"), bg=self.COLOR_CARD, fg=self.COLOR_TEXT).pack(side="left")
        tk.Label(f_c3_top, text="(大模型在每次交互时将优先调取这些关键背景)", font=("Microsoft YaHei UI", 8), bg=self.COLOR_CARD, fg=self.COLOR_MUTED).pack(side="left", padx=8)

        # 记忆条目展示区
        self.f_facts_container = tk.Frame(card3, bg=self.COLOR_CARD)
        self.f_facts_container.pack(fill="x", padx=16, pady=(0, 8))

        # 手工追加事实输入条
        f_add_fact = tk.Frame(card3, bg=self.COLOR_CARD)
        f_add_fact.pack(fill="x", padx=16, pady=(0, 12))

        self.var_new_fact = tk.StringVar()
        ent_new_fact = ttk.Entry(f_add_fact, textvariable=self.var_new_fact, font=("Microsoft YaHei UI", 9))
        ent_new_fact.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_add_fact = tk.Button(
            f_add_fact,
            text="➕ 添加一条记忆事实",
            command=self._on_add_single_fact,
            font=("Microsoft YaHei UI", 8, "bold"),
            bg="#0F2444",
            fg="#8CCBFF",
            activebackground="#163866",
            activeforeground="#38BDF8",
            bd=1,
            relief="solid",
            highlightbackground="#1E4E8C",
            padx=10,
            pady=3,
            cursor="hand2"
        )
        btn_add_fact.pack(side="left")

        # 卡片 4: 自完善与历史纠偏记录
        card4 = tk.Frame(parent, bg=self.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.COLOR_BORDER, highlightthickness=1)
        card4.pack(fill="x", pady=(0, 8))

        tk.Label(card4, text="🔄 AI自完善与纠偏演进记录", font=("Microsoft YaHei UI", 10, "bold"), bg=self.COLOR_CARD, fg=self.COLOR_TEXT).pack(anchor="w", padx=16, pady=(10, 4))

        self.txt_p_refinements = scrolledtext.ScrolledText(
            card4,
            wrap="word",
            height=4,
            font=("Microsoft YaHei UI", 8),
            bg="#06111F",
            fg="#A8C7E8",
            insertbackground="#00E5FF",
            selectbackground="#1E3A8A",
            selectforeground="#F3F7FF",
            bd=1,
            relief="solid",
            highlightbackground=self.COLOR_BORDER,
            highlightthickness=1
        )
        self.txt_p_refinements.pack(fill="x", padx=16, pady=(0, 12))

    def _on_save_profile_global_config(self):
        """保存全局用户画像配置"""
        self.config.profile.enabled = self.var_profile_enabled.get()
        self.config.profile.enable_private_chat = self.var_profile_private.get()
        self.config.profile.auto_refine = self.var_profile_auto_refine.get()
        self.config.profile.inject_prompt = self.var_profile_inject.get()
        self.config.save()
        self.profile_engine.update_config(self.config.profile, self.llm_client)
        messagebox.showinfo("成功", "联系人用户画像全局配置已保存生效！")

    def _resolve_contact_display_name(self, person_id: str, default_name: str = "") -> str:
        """解析联系人显示名称（严格遵循微信规则：有备注的显示备注，无备注的显示其本身的昵称）"""
        if not person_id:
            return default_name or ""

        target_wxid = person_id.split(":")[-1] if person_id.startswith("group_member:") else person_id

        # 1. 优先从内存通讯录 all_contacts 查询
        if hasattr(self, "all_contacts") and self.all_contacts:
            for c in self.all_contacts:
                if c.get("username") == target_wxid:
                    remark = (c.get("remark") or "").strip()
                    nick = (c.get("nick_name") or "").strip() or (c.get("name") or "").strip()
                    if remark:
                        return remark
                    if nick and not nick.startswith("wxid_"):
                        return nick

        # 2. 如果是群聊或在 all_groups 中
        if hasattr(self, "all_groups") and self.all_groups:
            for g in self.all_groups:
                if g.get("username") == target_wxid:
                    remark = (g.get("remark") or "").strip()
                    nick = (g.get("nick_name") or "").strip() or (g.get("name") or "").strip()
                    if remark:
                        return remark
                    if nick:
                        return nick

        # 3. 从本地微信 SQLite 数据库 contact 表查询
        if hasattr(self, "bridge") and self.bridge and getattr(self.bridge, "_db", None):
            try:
                conn = self.bridge._db._contact_conn()
                if conn:
                    row = conn.execute(
                        "SELECT nick_name, remark FROM contact WHERE username=? LIMIT 1",
                        (target_wxid,),
                    ).fetchone()
                    if row:
                        remark = (row["remark"] or "").strip()
                        nick = (row["nick_name"] or "").strip()
                        if remark:
                            return remark
                        if nick and not nick.startswith("wxid_"):
                            return nick
            except Exception:
                pass

        # 4. 兜底回退
        if default_name and not default_name.startswith("wxid_") and default_name != person_id:
            return default_name

        return target_wxid

    def _load_profiles_into_tree(self):
        """加载联系人画像列表到左侧 Treeview"""
        filter_type = self.var_profile_filter_type.get()
        kw = self.var_profile_search.get().strip().lower()

        self.tree_profiles.delete(*self.tree_profiles.get_children())

        # 1. 获取所有已建档的 profiles
        persisted = self.profile_engine.list_profiles()
        persisted_map = {p["person_id"]: p for p in persisted}

        # 2. 获取通讯录联系人 (私聊好友)
        all_items = []
        seen_ids = set()
        seen_names = set()

        # 优先放入已建档的实体
        for p in persisted:
            pid = p["person_id"]
            if pid in seen_ids or pid == "test_user_001" or pid == "filehelper":
                continue
            seen_ids.add(pid)
            # 有备注的显示备注，无备注的显示其本身的昵称
            resolved_name = self._resolve_contact_display_name(pid, default_name=p.get("remark") or p.get("name") or pid)
            if resolved_name in seen_names:
                continue
            seen_names.add(resolved_name)
            all_items.append({
                "person_id": pid,
                "name": resolved_name,
                "type": "群成员" if p.get("chat_type") == "group" else "私聊",
                "identity": p.get("identity") or "微信联系人",
                "facts": p.get("facts_count", 0),
                "is_profiled": True,
            })

        # 其次放入通讯录中的私聊联系人 (未建档)
        if hasattr(self, "all_contacts") and self.all_contacts:
            for c in self.all_contacts:
                u = c.get("username") or ""
                # 排除系统号、文件助手、公众号、群聊、已建档ID
                if not u or u in seen_ids or u == "filehelper" or u.endswith("@chatroom") or u.startswith("gh_"):
                    continue
                # 有备注的显示备注，无备注的显示其本身的昵称
                disp_name = self._resolve_contact_display_name(
                    u,
                    default_name=c.get("remark") or c.get("nick_name") or c.get("name") or u
                )
                if not disp_name or disp_name in seen_names or "测试助手" in disp_name:
                    continue
                seen_names.add(disp_name)
                all_items.append({
                    "person_id": u,
                    "name": disp_name,
                    "type": "私聊",
                    "identity": "未建档",
                    "facts": 0,
                    "is_profiled": False,
                })

        # 过滤筛选
        for item in all_items:
            # 类型过滤
            if filter_type == "profiles" and not item["is_profiled"]:
                continue
            if filter_type == "private" and item["type"] != "私聊":
                continue
            if filter_type == "group" and item["type"] != "群成员":
                continue

            # 关键字搜索
            if kw:
                haystack = f"{item['name']} {item['person_id']} {item['identity']}".lower()
                if kw not in haystack:
                    continue

            self.tree_profiles.insert(
                "",
                "end",
                iid=item["person_id"],
                values=(item["name"], item["type"], item["identity"], str(item["facts"]))
            )

    def _on_profile_search_change(self, *args):
        self._load_profiles_into_tree()

    def _on_profile_tree_select(self, event):
        """选中左侧树项目，展示右侧画像卡片"""
        selected = self.tree_profiles.selection()
        if not selected:
            return

        person_id = selected[0]
        self.current_selected_person_id = person_id

        # 切换右侧展示容器
        self.p_empty_tip.pack_forget()
        self.p_detail_frame.pack(fill="both", expand=True)

        profile = self.profile_engine.load_profile(person_id)
        if not profile:
            # 尚未建档，生成雏形（严格遵循微信命名规则）
            disp_name = self._resolve_contact_display_name(person_id)
            profile = ContactProfile(
                person_id=person_id,
                name=disp_name,
                chat_type="group" if person_id.startswith("group_member:") else "private",
                identity="尚未分析",
                tags=["未建档"],
                personality="待分析",
                communication_style="待分析",
                current_focus="",
                facts=[],
                refinements=[]
            )
        else:
            # 若已有 profile 缺少规范名称，自动补全最新备注或昵称
            if not profile.name or profile.name == person_id or profile.name.startswith("wxid_"):
                profile.name = self._resolve_contact_display_name(person_id, default_name=profile.name)

        self.current_selected_profile = profile
        self._render_profile_details(profile)

    def _render_profile_details(self, profile: ContactProfile):
        """将 profile 填入右侧各表单与记忆列表"""
        type_str = "群成员" if profile.chat_type == "group" else "私聊好友"
        disp_name = self._resolve_contact_display_name(profile.person_id, default_name=profile.name or profile.person_id)
        self.lbl_p_name.configure(text=disp_name)
        self.lbl_p_meta.configure(text=f"实体ID: {profile.person_id} | 类型: {type_str} | 累计互动: {profile.interaction_count}次 | 最近更新: {profile.updated_at or '未建立'}")

        self.var_p_identity.set(profile.identity)
        self.var_p_tags.set(", ".join(profile.tags))
        self.var_p_personality.set(profile.personality)
        self.var_p_comm_style.set(profile.communication_style)
        self.var_p_interests.set(", ".join(profile.interests))
        self.var_p_focus.set(profile.current_focus)

        # 渲染事实清单
        for widget in self.f_facts_container.winfo_children():
            widget.destroy()

        if not profile.facts:
            tk.Label(self.f_facts_container, text="暂无确切事实记忆 (可在下方输入添加，或点击上方按钮基于历史记录分析)", font=("Microsoft YaHei UI", 8), bg=self.COLOR_CARD, fg=self.COLOR_MUTED).pack(anchor="w", pady=4)
        else:
            for idx, fact_item in enumerate(profile.facts):
                row = tk.Frame(self.f_facts_container, bg=self.COLOR_CARD)
                row.pack(fill="x", pady=2)

                tk.Label(row, text=f"• {fact_item}", font=("Microsoft YaHei UI", 9), bg=self.COLOR_CARD, fg=self.COLOR_TEXT, anchor="w").pack(side="left", fill="x", expand=True)

                btn_del_fact = tk.Button(
                    row,
                    text="✕",
                    command=lambda i=idx: self._on_delete_single_fact(i),
                    font=("Microsoft YaHei UI", 7),
                    bg=self.COLOR_CARD,
                    fg="#ef4444",
                    bd=0,
                    cursor="hand2"
                )
                btn_del_fact.pack(side="right", padx=4)

        # 渲染自完善历史
        self.txt_p_refinements.delete("1.0", "end")
        if not profile.refinements:
            self.txt_p_refinements.insert("1.0", "暂无自完善演进记录。")
        else:
            lines = []
            for r in reversed(profile.refinements):
                t = r.get("time", "")
                note = r.get("note", "")
                lines.append(f"[{t}] {note}")
            self.txt_p_refinements.insert("1.0", "\n".join(lines))

    def _on_rebuild_selected_profile(self):
        """点击基于已有历史聊天记录分析/重建画像"""
        if not self.current_selected_person_id:
            return

        person_id = self.current_selected_person_id
        target_name = self._resolve_contact_display_name(
            person_id,
            default_name=self.current_selected_profile.name if self.current_selected_profile else person_id
        )

        self.btn_p_rebuild.configure(text="⏳ 正在分析历史记录...", state="disabled")

        def worker():
            try:
                profile = self.profile_engine.build_profile_from_history(
                    person_id=person_id,
                    name=target_name,
                    chat_type="group" if person_id.startswith("group_member:") else "private",
                    last_chat_id=person_id.replace("group_member:", "") if ":" in person_id else person_id
                )
                def on_done():
                    self.btn_p_rebuild.configure(text="🔍 基于已有聊天记录分析/重建画像", state="normal")
                    self.current_selected_profile = profile
                    self._render_profile_details(profile)
                    self._load_profiles_into_tree()
                    messagebox.showinfo(
                        "画像构建成功",
                        f"已为联系人【{profile.name}】建立专属立体画像！\n\n"
                        f"- 身份定位: {profile.identity}\n"
                        f"- 性格特质: {profile.personality}\n"
                        f"- 关键事实: 共提炼 {len(profile.facts)} 条永久事实记忆"
                    )
                self.dispatch_ui(on_done)
            except Exception as e:
                err_msg = str(e)
                def on_err():
                    self.btn_p_rebuild.configure(text="🔍 基于已有聊天记录分析/重建画像", state="normal")
                    messagebox.showerror("分析失败", f"分析历史记录构建画像出现异常:\n{err_msg}")
                self.dispatch_ui(on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_save_selected_profile(self):
        """保存右侧表单的手工调整"""
        if not self.current_selected_profile:
            return

        p = self.current_selected_profile
        p.identity = self.var_p_identity.get().strip() or "普通联系人"
        p.tags = [t.strip() for t in self.var_p_tags.get().replace("，", ",").split(",") if t.strip()]
        p.personality = self.var_p_personality.get().strip() or "礼貌友好"
        p.communication_style = self.var_p_comm_style.get().strip() or "偏好直接简短回答"
        p.interests = [i.strip() for i in self.var_p_interests.get().replace("，", ",").split(",") if i.strip()]
        p.current_focus = self.var_p_focus.get().strip()

        p.refinements.append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "管理员在控制台手动调整了画像属性与偏好"
        })

        self.profile_engine.save_profile(p)
        self._load_profiles_into_tree()
        self._render_profile_details(p)
        messagebox.showinfo("成功", f"【{p.name}】的画像记忆调整已保存！")

    def _on_delete_selected_profile(self):
        """清除当前联系人的画像记忆"""
        if not self.current_selected_person_id:
            return

        pid = self.current_selected_person_id
        if messagebox.askyesno("确认清除", f"确认要清空联系人 [{self.lbl_p_name.cget('text')}] 的全部专属画像与永久事实记忆吗？此操作无法撤销。"):
            self.profile_engine.delete_profile(pid)
            self._load_profiles_into_tree()
            self.p_detail_frame.pack_forget()
            self.p_empty_tip.pack(fill="both", expand=True)
            messagebox.showinfo("已清除", "该联系人的画像记忆已成功清空。")

    def _on_add_single_fact(self):
        """添加单条事实记忆"""
        if not self.current_selected_profile:
            return

        new_f = self.var_new_fact.get().strip()
        if not new_f:
            return

        self.current_selected_profile.facts.append(new_f)
        self.current_selected_profile.refinements.append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": f"手动录入了事实记忆: {new_f}"
        })
        self.profile_engine.save_profile(self.current_selected_profile)
        self.var_new_fact.set("")
        self._render_profile_details(self.current_selected_profile)
        self._load_profiles_into_tree()

    def _on_delete_single_fact(self, index: int):
        """删除单条事实记忆"""
        if not self.current_selected_profile or index >= len(self.current_selected_profile.facts):
            return

        del self.current_selected_profile.facts[index]
        self.profile_engine.save_profile(self.current_selected_profile)
        self._render_profile_details(self.current_selected_profile)
        self._load_profiles_into_tree()

    def _on_manual_create_profile(self):
        """手动为某个微信号/群成员创建画像档案"""
        pid = simpledialog.askstring("手动建档", "请输入联系人的 wxid、微信号或群成员ID:", parent=self.root)
        if not pid or not pid.strip():
            return
        pid = pid.strip()
        disp_name = self._resolve_contact_display_name(pid)
        p = self.profile_engine.build_profile_from_history(person_id=pid, name=disp_name)
        self._load_profiles_into_tree()
        self.tree_profiles.selection_set(pid)
        self._on_profile_tree_select(None)

    # -------------------------------------------------------------------------
    # Tab 6: 多模态与媒体设置 (Multimodal & Media Settings)
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
        canvas_win = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_win, width=e.width))
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
            activebackground="#6D35FF",
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
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
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
            width=28,
            font=("Microsoft YaHei UI", 9)
        )
        self.cb_voice_model.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        self.cb_voice_model.bind("<<ComboboxSelected>>", lambda e: self._update_model_status_label())

        f_model_status_box = tk.Frame(self.f_voice_local, bg=self.COLOR_CARD)
        f_model_status_box.grid(row=1, column=1, columnspan=3, sticky="w", padx=6, pady=(0, 4))

        self.lbl_voice_model_status = tk.Label(f_model_status_box, text="", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 8, "bold"))
        self.lbl_voice_model_status.pack(side="left")

        self.btn_open_model_download = tk.Button(
            f_model_status_box,
            text="🌐 打开模型极速下载网页",
            command=self._on_open_model_download_url,
            font=("Microsoft YaHei UI", 8, "bold"),
            bg="#0F2444",
            fg="#8CCBFF",
            activebackground="#163866",
            activeforeground="#38BDF8",
            bd=1,
            relief="solid",
            highlightbackground="#1E4E8C",
            padx=8,
            pady=1,
            cursor="hand2"
        )
        self.btn_open_model_download.pack(side="left", padx=10)
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
            width=28,
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
        self.cb_voice_cloud_model = ttk.Combobox(
            self.f_voice_cloud,
            textvariable=self.var_voice_cloud_model,
            values=[getattr(self.config.voice, "cloud_model_name", "whisper-1") or "whisper-1",
                    "whisper-1", "whisper-large-v3", "gpt-4o-audio-preview", "gpt-4o-transcribe"],
            width=28,
            font=("Consolas", 9)
        )
        self.cb_voice_cloud_model.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        self.btn_fetch_voice_cloud_models = tk.Button(
            self.f_voice_cloud,
            text="🔍 获取模型",
            command=self._on_fetch_voice_cloud_models_click,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#007BFF",
            fg="#ffffff",
            activebackground="#6D35FF",
            relief="flat",
            padx=10,
            pady=3,
            cursor="hand2"
        )
        self.btn_fetch_voice_cloud_models.grid(row=1, column=2, sticky="w", padx=6, pady=4)

        if curr_eng == "cloud":
            self.f_voice_local.pack_forget()
            self.f_voice_cloud.pack(fill="x", padx=16, pady=4)

        # 语音转写测试工具沙盒
        lf_vtest = tk.LabelFrame(card_voice, text=" 🎵 音频文件选择与转写测试工具 ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#38BDF8", padx=12, pady=8)
        lf_vtest.pack(fill="x", padx=16, pady=(10, 12))

        f_vt_in = tk.Frame(lf_vtest, bg=self.COLOR_CARD)
        f_vt_in.pack(fill="x", pady=4)

        tk.Label(f_vt_in, text="测试音频文件路径:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.btn_run_voice_test = tk.Button(
            f_vt_in,
            text="⚡ 开始测试转写",
            command=self._on_run_audio_test,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg=self.COLOR_PRIMARY,
            fg="#ffffff",
            activebackground="#6D35FF",
            relief="flat",
            padx=12,
            pady=3,
            cursor="hand2"
        )
        self.btn_run_voice_test.pack(side="right", padx=4)

        btn_browse_audio = tk.Button(
            f_vt_in,
            text="📂 弹窗选择音频文件",
            command=self._on_browse_audio_test,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#0F2444",
            fg="#8CCBFF",
            activebackground="#163866",
            activeforeground="#38BDF8",
            bd=1,
            relief="solid",
            highlightbackground="#1E4E8C",
            padx=10,
            pady=3,
            cursor="hand2"
        )
        btn_browse_audio.pack(side="right", padx=4)

        self.var_voice_test_path = tk.StringVar(value="")
        ttk.Entry(f_vt_in, textvariable=self.var_voice_test_path, font=("Consolas", 9)).pack(side="left", padx=6, fill="x", expand=True)

        tk.Label(lf_vtest, text="音频转写输出文本与用时反馈:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 8, "bold"), fg=self.COLOR_MUTED).pack(anchor="w", pady=(6, 2))
        self.txt_voice_test_result = scrolledtext.ScrolledText(
            lf_vtest,
            wrap="word",
            height=4,
            font=("Microsoft YaHei UI", 9),
            bg="#06111F",
            fg="#A8C7E8",
            insertbackground="#00E5FF",
            selectbackground="#1E3A8A",
            selectforeground="#F3F7FF",
            bd=1,
            relief="solid",
            highlightbackground=self.COLOR_BORDER,
            highlightthickness=1
        )
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
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
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

        # 一键获取上游视觉模型按钮
        self.btn_fetch_vision_models = tk.Button(
            self.f_vision,
            text="🔍 一键获取上游模型",
            command=self._on_fetch_upstream_vision_models_click,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#007BFF",
            fg="#ffffff",
            activebackground="#6D35FF",
            relief="flat",
            padx=10,
            pady=3,
            cursor="hand2"
        )
        self.btn_fetch_vision_models.grid(row=0, column=2, sticky="w", padx=6, pady=4)

        tk.Label(self.f_vision, text="(留空则直接使用大模型配置页面的全局模型)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=0, column=3, sticky="w", padx=6)

        tk.Label(self.f_vision, text="视觉模型 API Base URL (可选):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", pady=4)
        self.var_vision_url = tk.StringVar(value=getattr(self.config.image, "vision_api_url", "") or "")
        ttk.Entry(self.f_vision, textvariable=self.var_vision_url, width=38, font=("Consolas", 9)).grid(row=1, column=1, sticky="w", padx=6, pady=4)
        tk.Label(self.f_vision, text="(留空继承全局大模型 API 地址)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=1, column=2, columnspan=2, sticky="w", padx=6)

        tk.Label(self.f_vision, text="视觉模型 API Key (可选):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).grid(row=2, column=0, sticky="w", pady=4)
        self.var_vision_key = tk.StringVar(value=getattr(self.config.image, "vision_api_key", "") or "")
        ttk.Entry(self.f_vision, textvariable=self.var_vision_key, width=38, show="*", font=("Consolas", 9)).grid(row=2, column=1, sticky="w", padx=6, pady=4)
        tk.Label(self.f_vision, text="(留空继承全局大模型 API Key)", bg=self.COLOR_CARD, fg=self.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=2, column=2, columnspan=2, sticky="w", padx=6)

        # 自动降级选项
        self.var_fallback_ocr = tk.BooleanVar(value=getattr(self.config.image, "fallback_to_ocr", True))
        self.chk_fallback_ocr = tk.Checkbutton(
            card_image,
            text="启用自动降级：当视觉大模型报错或接入的为纯文本大模型(如DeepSeek-chat)时，自动启用 Windows 原生 WinRT OCR 提取图片中文字送入大模型",
            variable=self.var_fallback_ocr,
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8",
            font=("Microsoft YaHei UI", 8)
        )
        self.chk_fallback_ocr.pack(anchor="w", padx=16, pady=(4, 8))

        # 图片测试工具沙盒
        lf_itest = tk.LabelFrame(card_image, text=" 🖼️ 图片选择与识别解析测试工具 ", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg="#A78BFA", padx=12, pady=8)
        lf_itest.pack(fill="x", padx=16, pady=(6, 12))

        f_it_in = tk.Frame(lf_itest, bg=self.COLOR_CARD)
        f_it_in.pack(fill="x", pady=4)

        tk.Label(f_it_in, text="测试图片文件路径:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.btn_run_image_test = tk.Button(
            f_it_in,
            text="⚡ 开始测试识别",
            command=self._on_run_image_test,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#6D35FF",
            fg="#ffffff",
            activebackground="#5821D8",
            relief="flat",
            padx=12,
            pady=3,
            cursor="hand2"
        )
        self.btn_run_image_test.pack(side="right", padx=4)

        btn_browse_img = tk.Button(
            f_it_in,
            text="📂 弹窗选择图片文件",
            command=self._on_browse_image_test,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#0F2444",
            fg="#8CCBFF",
            activebackground="#163866",
            activeforeground="#38BDF8",
            bd=1,
            relief="solid",
            highlightbackground="#1E4E8C",
            padx=10,
            pady=3,
            cursor="hand2"
        )
        btn_browse_img.pack(side="right", padx=4)

        self.var_image_test_path = tk.StringVar(value="")
        ttk.Entry(f_it_in, textvariable=self.var_image_test_path, font=("Consolas", 9)).pack(side="left", padx=6, fill="x", expand=True)

        f_it_p = tk.Frame(lf_itest, bg=self.COLOR_CARD)
        f_it_p.pack(fill="x", pady=(2, 6))
        tk.Label(f_it_p, text="测试指导提示词 (可选):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.var_image_test_prompt = tk.StringVar(value="请分析这张图片中的内容，提取关键信息并给出简明解答：")
        ttk.Entry(f_it_p, textvariable=self.var_image_test_prompt, width=70, font=("Microsoft YaHei UI", 9)).pack(side="left", padx=6, fill="x", expand=True)

        tk.Label(lf_itest, text="图片识别解析输出 (策略方式、提取文字或视觉回答、耗时):", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 8, "bold"), fg=self.COLOR_MUTED).pack(anchor="w", pady=(6, 2))
        self.txt_image_test_result = scrolledtext.ScrolledText(
            lf_itest,
            wrap="word",
            height=5,
            font=("Microsoft YaHei UI", 9),
            bg="#06111F",
            fg="#A8C7E8",
            insertbackground="#00E5FF",
            selectbackground="#1E3A8A",
            selectforeground="#F3F7FF",
            bd=1,
            relief="solid",
            highlightbackground=self.COLOR_BORDER,
            highlightthickness=1
        )
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
            activebackground="#6D35FF",
            activeforeground="#ffffff",
            relief="flat",
            padx=24,
            pady=8,
            cursor="hand2"
        )
        btn_save_bot.pack(anchor="center")

    def _check_whisper_model_ready(self, raw_m: str) -> tuple[bool, str]:
        """检查指定规格的 Whisper 模型是否已完整离线存在于本地 models/ 目录"""
        project_root = os.path.dirname(os.path.abspath(__file__))
        models_dir = os.path.join(project_root, "models")
        cand1 = os.path.join(models_dir, f"whisper-{raw_m}")
        cand2 = os.path.join(models_dir, raw_m)
        cand3 = os.path.join(models_dir, f"faster-whisper-{raw_m}")
        
        for c in (cand1, cand2, cand3):
            if os.path.isdir(c) and (
                os.path.exists(os.path.join(c, "model.bin")) or 
                os.path.exists(os.path.join(c, "model.safetensors"))
            ):
                return True, c
        target_path = os.path.join(models_dir, f"whisper-{raw_m}")
        return False, target_path

    def _on_open_model_download_url(self):
        """主动调用默认浏览器打开当前选中 Whisper 模型的极速镜像下载页面"""
        raw_m = self.var_voice_model.get().split()[0].strip()
        url = WHISPER_MODEL_DOWNLOAD_URLS.get(raw_m, f"https://hf-mirror.com/Systran/faster-whisper-{raw_m}")
        webbrowser.open(url)

    def _update_model_status_label(self):
        """检查并更新本地 Whisper 模型在项目 models/ 目录中的离线就绪状态"""
        if not hasattr(self, "lbl_voice_model_status") or not hasattr(self, "var_voice_model"):
            return
        raw_m = self.var_voice_model.get().split()[0].strip()
        is_ready, target_dir = self._check_whisper_model_ready(raw_m)

        if is_ready:
            self.lbl_voice_model_status.config(
                text=f"● 本地离线已就绪 (已存入项目 models/whisper-{raw_m})", 
                fg=self.COLOR_SUCCESS
            )
            if hasattr(self, "btn_open_model_download"):
                self.btn_open_model_download.config(
                    text="🌐 查看模型源网页",
                    fg="#2563eb"
                )
        else:
            self.lbl_voice_model_status.config(
                text="○ 本地缺失模型 (点击测试将自动调用浏览器下载)", 
                fg=self.COLOR_WARNING
            )
            if hasattr(self, "btn_open_model_download"):
                self.btn_open_model_download.config(
                    text="🌐 打开浏览器下载此模型",
                    fg="#dc2626"
                )

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
        """异步执行语音识别转写测试 (当本地缺失模型时自动调用本地浏览器打开下载地址)"""
        audio_path = self.var_voice_test_path.get().strip()
        if not audio_path or not os.path.exists(audio_path):
            messagebox.showwarning("提示", "请先选择真实存在的测试音频文件！")
            return

        is_local = "cloud" not in self.var_voice_engine.get().lower()
        raw_m = self.var_voice_model.get().split()[0].strip()

        # 本地模式下，若本地缺失该模型文件，自动调用默认浏览器跳转下载
        if is_local:
            is_ready, target_dir = self._check_whisper_model_ready(raw_m)
            if not is_ready:
                dl_url = WHISPER_MODEL_DOWNLOAD_URLS.get(raw_m, f"https://hf-mirror.com/Systran/faster-whisper-{raw_m}")
                webbrowser.open(dl_url)

                # 收集当前本地已就绪的模型列表提供给用户快速选择
                ready_list = []
                for m_cand in ["tiny", "base", "small", "medium", "large-v3"]:
                    ok_cand, _ = self._check_whisper_model_ready(m_cand)
                    if ok_cand:
                        ready_list.append(m_cand)
                ready_tip = f"【当前本地已就绪模型】: {', '.join(ready_list)}" if ready_list else "当前本地 models/ 目录暂无已下载模型"

                tip_info = (
                    f"⚠️ 【检测到本地缺失模型】: whisper-{raw_m}\n"
                    f"----------------------------------------------------------------------\n"
                    f"🌐 已自动为您调用本地系统默认浏览器打开该模型下载页面：\n"
                    f"👉 {dl_url}\n\n"
                    f"📁 【下载后模型存放路径】:\n"
                    f"请将下载的模型权重与配置文件 (主要包含 model.bin, config.json, vocabulary.json 等) 放入：\n"
                    f"👉 {target_dir}\n\n"
                    f"💡 贴士：{ready_tip}\n"
                    f"• 如需立即体验转写，可直接在上方下拉框切换为已就绪模型；\n"
                    f"• 或待浏览器下载文件并放入上述文件夹后，重新点击【⚡ 开始测试转写】即可秒速离线识别！"
                )
                self.txt_voice_test_result.delete("1.0", "end")
                self.txt_voice_test_result.insert("1.0", tip_info)

                messagebox.showinfo(
                    "模型下载已自动唤起",
                    f"检测到本地缺少 whisper-{raw_m} 模型文件。\n\n"
                    f"已自动为您在浏览器中打开极速镜像下载地址：\n{dl_url}\n\n"
                    f"下载后请将文件放置于项目目录：\n{target_dir}\n\n"
                    f"{ready_tip}"
                )
                return

        self.btn_run_voice_test.configure(text="⏳ 正在转写中...", state="disabled")
        self.txt_voice_test_result.delete("1.0", "end")
        self.txt_voice_test_result.insert("1.0", "正在调用语音识别引擎转写音频，请稍候...\n")

        # 抓取当前界面配置构造测试用 VoiceConfig
        cfg = self.config.voice.model_copy()
        cfg.engine = "local" if is_local else "cloud"
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
                        err_str = str(text)
                        if is_local and any(k in err_str.lower() for k in ("not found", "model", "download", "connection", "huggingface", "url")):
                            dl_url = WHISPER_MODEL_DOWNLOAD_URLS.get(raw_m, f"https://hf-mirror.com/Systran/faster-whisper-{raw_m}")
                            webbrowser.open(dl_url)
                            content = (
                                f"❌ 【语音转写失败 - 本地模型缺失或下载受阻】\n"
                                f"• 错误详情: {err_str}\n\n"
                                f"🌐 已自动为您调用系统默认浏览器打开该模型下载页面：\n{dl_url}\n"
                                f"请下载后放入项目 models/whisper-{raw_m} 文件夹中重新测试。"
                            )
                        else:
                            content = (
                                f"❌ 【语音转写失败】\n"
                                f"• 使用引擎: {eng}\n"
                                f"• 耗时: {cost} 毫秒\n"
                                f"• 错误信息: {err_str}"
                            )
                    self.txt_voice_test_result.insert("1.0", content)
                self.dispatch_ui(on_done)
            except Exception as e:
                def on_err():
                    self.btn_run_voice_test.configure(text="⚡ 开始测试转写", state="normal")
                    self.txt_voice_test_result.delete("1.0", "end")
                    err_str = str(e)
                    if is_local and any(k in err_str.lower() for k in ("not found", "model", "download", "connection", "huggingface", "url")):
                        dl_url = WHISPER_MODEL_DOWNLOAD_URLS.get(raw_m, f"https://hf-mirror.com/Systran/faster-whisper-{raw_m}")
                        webbrowser.open(dl_url)
                        self.txt_voice_test_result.insert(
                            "1.0",
                            f"❌ 【本地语音模型异常】: {err_str}\n\n"
                            f"🌐 已自动为您调用浏览器打开下载页面：{dl_url}\n"
                            f"请下载模型后放置于 models/whisper-{raw_m} 目录。"
                        )
                    else:
                        self.txt_voice_test_result.insert("1.0", f"❌ 异常报错: {err_str}")
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

    def _on_fetch_upstream_vision_models_click(self):
        """图片识别配置：一键获取上游可用视觉大模型列表"""
        api_url = self.var_vision_url.get().strip() or self.var_api_url.get().strip()
        api_key = self.var_vision_key.get().strip() or self.var_api_key.get().strip()

        if not api_url:
            messagebox.showwarning("提示", "请先在上方输入【视觉模型 API Base URL】（或在大模型配置页面输入全局 API 地址）！")
            return

        self.btn_fetch_vision_models.configure(text="⏳ 获取中...", state="disabled")

        def worker():
            try:
                ok, model_list, msg = self.llm_client.get_models(api_url=api_url, api_key=api_key)
                def on_done():
                    self.btn_fetch_vision_models.configure(text="🔍 一键获取上游模型", state="normal")
                    if ok and model_list:
                        # 识别常见多模态视觉模型关键词并优先排在顶部
                        vision_keywords = ("vl", "vision", "4o", "gemini", "claude", "glm-4v", "omni", "qvq")
                        sorted_models = sorted(
                            model_list,
                            key=lambda m: (0 if any(k in m.lower() for k in vision_keywords) else 1, m)
                        )
                        self.cb_vision_model["values"] = sorted_models
                        if self.var_vision_model.get() not in sorted_models:
                            v_cands = [m for m in sorted_models if any(k in m.lower() for k in vision_keywords)]
                            self.var_vision_model.set(v_cands[0] if v_cands else sorted_models[0])
                        messagebox.showinfo("成功", f"成功拉取到 {len(sorted_models)} 个上游可用模型！\n已更新视觉大模型下拉列表。")
                    else:
                        messagebox.showwarning("提示", f"未能获取到模型列表:\n{msg}")
                self.dispatch_ui(on_done)
            except Exception as e:
                def on_err():
                    self.btn_fetch_vision_models.configure(text="🔍 一键获取上游模型", state="normal")
                    messagebox.showerror("获取失败", f"无法拉取上游视觉模型列表:\n{e}")
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
        chk_sb_grp = tk.Checkbutton(
            in_frame,
            text="模拟群聊消息",
            variable=self.var_sb_is_group,
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8"
        )
        chk_sb_grp.grid(row=0, column=2, padx=10)

        self.var_sb_at_me = tk.BooleanVar(value=True)
        chk_sb_at = tk.Checkbutton(
            in_frame,
            text="模拟 @ 机器人",
            variable=self.var_sb_at_me,
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            selectcolor="#06111F",
            activebackground=self.COLOR_CARD,
            activeforeground="#38BDF8"
        )
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
            activebackground="#6D35FF",
            relief="flat",
            padx=16,
            pady=4,
            cursor="hand2"
        )
        self.btn_run_sandbox.grid(row=1, column=4, padx=8, pady=(8, 0))

        # 结果与链路展示
        tk.Label(card, text="决策链路与输出结果展示:", bg=self.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
        self.txt_sb_result = scrolledtext.ScrolledText(
            card,
            wrap="word",
            font=("Microsoft YaHei UI", 9),
            bg="#06111F",
            fg="#A8C7E8",
            insertbackground="#00E5FF",
            selectbackground="#1E3A8A",
            selectforeground="#F3F7FF",
            bd=1,
            relief="solid",
            highlightbackground=self.COLOR_BORDER,
            highlightthickness=1
        )
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
    # 配置持久化与导出/导入 (严格校验同一微信账号，支持全模块数据同步)
    # -------------------------------------------------------------------------
    def _flush_all_ui_to_config(self):
        """将当前界面各个选项卡中已设置的所有数据完整持久化同步至 self.config 并保存到磁盘"""
        # 1. 回复对象白名单与群聊策略
        if hasattr(self, "selected_users"):
            self.config.targets.whitelist_users = list(self.selected_users)
        if hasattr(self, "selected_groups"):
            self.config.targets.whitelist_groups = list(self.selected_groups)
        if hasattr(self, "var_reply_all_private"):
            self.config.targets.reply_all_private = bool(self.var_reply_all_private.get())
        if hasattr(self, "var_reply_all_groups"):
            self.config.targets.reply_all_groups = bool(self.var_reply_all_groups.get())
        if hasattr(self, "var_group_at_only"):
            self.config.targets.group_at_only = bool(self.var_group_at_only.get())
        if hasattr(self, "var_group_auto_at"):
            self.config.targets.group_auto_at_sender = bool(self.var_group_auto_at.get())

        # 2. 大模型配置与提示词
        if hasattr(self, "var_api_url"):
            self.config.llm.api_url = self.var_api_url.get().strip()
        if hasattr(self, "var_api_key"):
            self.config.llm.api_key = self.var_api_key.get().strip()
        if hasattr(self, "var_model_name"):
            self.config.llm.model_name = self.var_model_name.get().strip()
        if hasattr(self, "var_temp"):
            try:
                self.config.llm.temperature = float(self.var_temp.get())
            except (ValueError, TypeError):
                pass
        if hasattr(self, "var_max_tokens"):
            try:
                self.config.llm.max_tokens = int(self.var_max_tokens.get())
            except (ValueError, TypeError):
                pass

        if hasattr(self, "var_preset"):
            curr_preset = self.var_preset.get().strip()
            self.config.safety.preset_name = curr_preset
            if hasattr(self, "txt_prompt"):
                curr_prompt = self.txt_prompt.get("1.0", "end").strip()
                self.config.safety.system_prompt = curr_prompt
                if curr_preset and hasattr(self, "presets"):
                    self.presets[curr_preset] = curr_prompt
                    self.config.safety.presets = dict(self.presets)

        # 3. 安全与风控配置
        if hasattr(self, "var_handover_kw"):
            self.config.safety.handover_keyword = self.var_handover_kw.get().strip()
        if hasattr(self, "var_handover_reply"):
            self.config.safety.handover_reply = self.var_handover_reply.get().strip()
        if hasattr(self, "var_reset_handover_kw"):
            self.config.safety.reset_handover_keyword = self.var_reset_handover_kw.get().strip()
        if hasattr(self, "var_reply_prefix"):
            self.config.safety.reply_prefix = self.var_reply_prefix.get().replace("\\n", "\n")
        if hasattr(self, "var_reply_suffix"):
            self.config.safety.reply_suffix = self.var_reply_suffix.get().replace("\\n", "\n")
        if hasattr(self, "var_max_length"):
            try:
                self.config.safety.max_reply_length = int(self.var_max_length.get())
            except (ValueError, TypeError):
                pass
        if hasattr(self, "var_cooldown"):
            try:
                self.config.safety.cooldown_seconds = float(self.var_cooldown.get())
            except (ValueError, TypeError):
                pass
        if hasattr(self, "var_daily_limit"):
            try:
                self.config.safety.daily_chat_limit = int(self.var_daily_limit.get())
            except (ValueError, TypeError):
                pass
        if hasattr(self, "var_sensitive_words"):
            self.config.safety.sensitive_words = self.var_sensitive_words.get().strip()
        if hasattr(self, "var_sensitive_action"):
            action_rev_map = {
                "婉拒回复 (友好说明)": "refuse",
                "转接人工坐席": "handover",
                "静默忽略 (不回复)": "ignore"
            }
            self.config.safety.sensitive_action = action_rev_map.get(self.var_sensitive_action.get(), "refuse")
        if hasattr(self, "var_sensitive_reply"):
            self.config.safety.sensitive_reply = self.var_sensitive_reply.get().strip()
        if hasattr(self, "var_enable_tools"):
            self.config.safety.enable_tools = bool(self.var_enable_tools.get())

        # 4. RAG 本地知识库配置
        if hasattr(self, "var_rag_enabled"):
            self.config.rag.enabled = bool(self.var_rag_enabled.get())
        if hasattr(self, "var_rag_path"):
            self.config.rag.kb_folder_path = self.var_rag_path.get().strip()

        # 5. 联系人专属画像与全局配置
        if hasattr(self, "var_profile_enabled"):
            self.config.profile.enabled = bool(self.var_profile_enabled.get())
        if hasattr(self, "var_profile_private"):
            self.config.profile.enable_private_chat = bool(self.var_profile_private.get())
        if hasattr(self, "var_profile_auto_refine"):
            self.config.profile.auto_refine = bool(self.var_profile_auto_refine.get())
        if hasattr(self, "var_profile_inject"):
            self.config.profile.inject_prompt = bool(self.var_profile_inject.get())

        # 若右侧联系人详情面板当前正在编辑某人画像，同步保存当前画像
        if getattr(self, "current_selected_profile", None) and hasattr(self, "var_p_identity"):
            try:
                p = self.current_selected_profile
                p.identity = self.var_p_identity.get().strip() or "普通联系人"
                p.tags = [t.strip() for t in self.var_p_tags.get().replace("，", ",").split(",") if t.strip()]
                p.personality = self.var_p_personality.get().strip() or "礼貌友好"
                p.communication_style = self.var_p_comm_style.get().strip() or "偏好直接简短回答"
                p.interests = [i.strip() for i in self.var_p_interests.get().replace("，", ",").split(",") if i.strip()]
                p.current_focus = self.var_p_focus.get().strip()
                self.profile_engine.save_profile(p)
            except Exception:
                pass

        # 6. 多模态与媒体配置 (语音与视觉)
        if hasattr(self, "var_voice_enabled"):
            self.config.voice.enabled = bool(self.var_voice_enabled.get())
        if hasattr(self, "var_voice_engine"):
            self.config.voice.engine = "cloud" if "cloud" in self.var_voice_engine.get().lower() else "local"
        if hasattr(self, "var_voice_model"):
            self.config.voice.whisper_model = self.var_voice_model.get().split()[0].strip()
        if hasattr(self, "var_voice_device"):
            self.config.voice.whisper_device = self.var_voice_device.get().split()[0].strip().lower()
        if hasattr(self, "var_voice_cloud_url"):
            self.config.voice.cloud_api_url = self.var_voice_cloud_url.get().strip()
        if hasattr(self, "var_voice_cloud_key"):
            self.config.voice.cloud_api_key = self.var_voice_cloud_key.get().strip()
        if hasattr(self, "var_voice_cloud_model"):
            self.config.voice.cloud_model_name = self.var_voice_cloud_model.get().strip() or "whisper-1"

        if hasattr(self, "var_image_enabled"):
            self.config.image.enabled = bool(self.var_image_enabled.get())
        if hasattr(self, "var_image_strategy"):
            strat_val = self.var_image_strategy.get().lower()
            if "vision" in strat_val or "视觉" in strat_val:
                self.config.image.strategy = "vision_only"
            elif "ocr_only" in strat_val or ("ocr" in strat_val and "auto" not in strat_val):
                self.config.image.strategy = "ocr_only"
            else:
                self.config.image.strategy = "auto"
        if hasattr(self, "var_vision_model"):
            self.config.image.vision_model_name = self.var_vision_model.get().strip()
        if hasattr(self, "var_vision_url"):
            self.config.image.vision_api_url = self.var_vision_url.get().strip()
        if hasattr(self, "var_vision_key"):
            self.config.image.vision_api_key = self.var_vision_key.get().strip()
        if hasattr(self, "var_fallback_ocr"):
            self.config.image.fallback_to_ocr = bool(self.var_fallback_ocr.get())

        # 7. 语音通话智能体配置 (VoIP)
        if hasattr(self, "voip_builder") and self.voip_builder:
            vb = self.voip_builder
            cfg = self.config.voip
            if hasattr(vb, "var_voip_enabled"):
                cfg.enabled = bool(vb.var_voip_enabled.get())
            if hasattr(vb, "var_sync_reply"):
                cfg.sync_reply_targets = bool(vb.var_sync_reply.get())
            if hasattr(vb, "var_enable_group"):
                cfg.enable_group_call = bool(vb.var_enable_group.get())
            if hasattr(vb, "var_whitelist_groups"):
                raw_groups = vb.var_whitelist_groups.get()
                cfg.whitelist_groups = [g.strip() for g in raw_groups.split(",") if g.strip()]
            if hasattr(vb, "var_tts_engine"):
                eng_str = vb.var_tts_engine.get().lower()
                if "edge" in eng_str:
                    cfg.tts_engine = "edge_tts"
                elif "sapi" in eng_str:
                    cfg.tts_engine = "sapi"
                elif "chattts" in eng_str:
                    cfg.tts_engine = "chattts"
                else:
                    cfg.tts_engine = "qwen3_tts"
            if hasattr(vb, "var_clone_enabled"):
                cfg.voice_clone_enabled = bool(vb.var_clone_enabled.get())
            if hasattr(vb, "var_clone_path"):
                cfg.voice_clone_audio_path = vb.var_clone_path.get().strip()
            if hasattr(vb, "var_answer_delay"):
                try:
                    cfg.auto_answer_delay_sec = float(vb.var_answer_delay.get())
                except (ValueError, TypeError):
                    pass
            if hasattr(vb, "var_max_duration"):
                try:
                    cfg.max_call_duration_min = int(vb.var_max_duration.get())
                except (ValueError, TypeError):
                    pass
            if hasattr(vb, "var_barge_in"):
                cfg.barge_in_enabled = bool(vb.var_barge_in.get())
            if hasattr(vb, "var_in_dev"):
                cfg.virtual_input_device = vb.var_in_dev.get().strip()
            if hasattr(vb, "var_out_dev"):
                cfg.virtual_output_device = vb.var_out_dev.get().strip()

        # 8. 执行物理持久化写入
        self.config.save()

    def _on_window_close(self):
        """窗口关闭前自动持久化存储所有配置并退出"""
        try:
            if hasattr(self, "call_agent") and self.call_agent:
                self.call_agent.stop()
        except Exception:
            pass
        try:
            self._flush_all_ui_to_config()
        except Exception:
            pass
        self.root.destroy()

    def _on_export_config_click(self):
        """导出完整配置包 (包含所有大模型/回复对象/媒体/安全配置与联系人专属画像记忆)"""
        try:
            # 1. 确保当前界面上所有已调整的数据立即持久化保存
            self._flush_all_ui_to_config()

            # 2. 获取当前微信账号信息
            status = self.bridge.get_status(force_refresh=True)
            self_wxid = status.get("self_wxid") or getattr(self.bridge, "self_wxid", "")
            self_name = status.get("self_name") or getattr(self.bridge, "self_name", "")

            if not self_wxid:
                tip = (
                    "当前未检测到电脑端登录的微信账号。\n"
                    "导出无账号绑定的备份包后，后续将无法在有严格账号校验的模式下导入验证。\n\n"
                    "是否仍要继续导出当前通用配置？"
                )
                if not messagebox.askyesno("未登录微信提示", tip):
                    return

            # 3. 弹出保存路径选择框
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            clean_id = self_wxid.replace(":", "_").replace("/", "_") if self_wxid else "unbound"
            default_fname = f"WeChatAI_Backup_{clean_id}_{timestamp}.zip"

            save_path = filedialog.asksaveasfilename(
                title="导出 WeChat-AIAgent 完整配置包",
                defaultextension=".zip",
                initialfile=default_fname,
                filetypes=[("WeChatAI 备份包", "*.zip"), ("所有文件", "*.*")]
            )
            if not save_path:
                return

            # 4. 执行备份打包
            meta = ConfigManager.export_backup_package(
                out_path=save_path,
                self_wxid=self_wxid,
                self_name=self_name
            )

            p_count = meta.get("profiles_count", 0)
            log_msg = f"全部配置与画像数据已成功导出至备份包: {os.path.basename(save_path)} (归属微信: {self_name or self_wxid or '未绑定'})"
            self._append_log("success", "配置中心", log_msg)

            messagebox.showinfo(
                "导出成功",
                f"🎉 WeChat-AIAgent 完整配置已成功导出！\n\n"
                f"• 归属微信: {self_name or '无'} ({self_wxid or '未绑定'})\n"
                f"• 导出文件: {save_path}\n"
                f"• 联系人画像数: {p_count} 个\n"
                f"• 备份时间: {meta.get('timestamp')}\n\n"
                f"已包含：回复对象、大模型密钥、系统人设、知识库、安全风控、多模态媒体、VoIP电话及所有联系人记忆。"
            )
        except Exception as e:
            messagebox.showerror("导出失败", f"导出配置备份包时发生异常:\n{e}")
            self._append_log("warning", "配置中心", f"导出失败: {e}")

    def _on_import_config_click(self):
        """导入配置包 (必须识别确认登录的是同一微信账号，不是同一个账号严格禁止导入)"""
        try:
            # 1. 选择备份包文件
            file_path = filedialog.askopenfilename(
                title="选择要导入的 WeChat-AIAgent 完整配置备份包",
                filetypes=[("WeChatAI 备份包", "*.zip"), ("所有文件", "*.*")]
            )
            if not file_path:
                return

            # 2. 预检备份包完整性与元数据
            meta = ConfigManager.inspect_backup_package(file_path)
            if not meta:
                messagebox.showerror("格式错误", "所选文件不是有效的 WeChat-AIAgent 配置备份包，缺少关键配置清单！")
                return

            # 3. 严格校验微信登录账号一致性 (不是同一个账号不能导入)
            status = self.bridge.get_status(force_refresh=True)
            curr_wxid = status.get("self_wxid") or getattr(self.bridge, "self_wxid", "")
            curr_name = status.get("self_name") or getattr(self.bridge, "self_name", "")
            wechat_detected = status.get("wechat_detected", False)

            is_valid, reason, _ = ConfigManager.validate_account_match(
                backup_path=file_path,
                current_wxid=curr_wxid,
                wechat_detected=wechat_detected
            )

            if not is_valid:
                # 严格拦截导入并弹窗警告
                backup_wxid = meta.get("self_wxid", "未知")
                backup_name = meta.get("self_name", "未知")
                err_detail = (
                    f"⛔ 【账号不匹配 · 严格禁止导入】\n\n"
                    f"原因: {reason}\n\n"
                    f"----------------------------------------\n"
                    f"• 当前电脑端登录微信: {curr_name or '未知'} (wxid: {curr_wxid or '未登录'})\n"
                    f"• 备份包归属微信账号: {backup_name} (wxid: {backup_wxid})\n"
                    f"----------------------------------------\n\n"
                    f"【安全策略提示】：为防止联系人好友画像错乱、敏感群聊越权以及隐私数据交叉泄漏，"
                    f"系统要求必须登录与备份包完全一致的微信账号方可恢复导入！"
                )
                messagebox.showerror("禁止导入 · 微信账号不匹配", err_detail)
                self._append_log("warning", "配置中心", f"导入被安全策略拦截: {reason}")
                return

            # 4. 二次确认弹窗
            backup_wxid = meta.get("self_wxid", "")
            backup_name = meta.get("self_name", "")
            backup_time = meta.get("timestamp", "")
            p_count = meta.get("profiles_count", 0)

            confirm_msg = (
                f"✅ 微信账号一致性验证通过！\n\n"
                f"• 当前微信账号: {curr_name or backup_name} ({curr_wxid})\n"
                f"• 备份生成时间: {backup_time}\n"
                f"• 包含联系人画像: {p_count} 个\n\n"
                f"⚠️ 注意：导入将完全覆盖本地当前的全局配置、安全策略与联系人记忆库。\n"
                f"是否确认恢复并立即生效？"
            )
            if not messagebox.askyesno("确认恢复导入配置", confirm_msg):
                return

            # 5. 执行解压与覆盖
            ok, msg = ConfigManager.import_backup_package(file_path)
            if not ok:
                messagebox.showerror("导入失败", f"解压还原配置数据时出错:\n{msg}")
                self._append_log("warning", "配置中心", f"导入失败: {msg}")
                return

            # 6. 热重载所有引擎并全量刷新 UI
            self._reload_and_refresh_all_settings()

            self._append_log("success", "配置中心", f"配置与联系人专属记忆已成功还原生效！(共导入 {p_count} 个联系人画像)")
            messagebox.showinfo(
                "导入成功",
                f"🎉 配置与联系人记忆库已成功恢复！\n\n"
                f"• 恢复归属微信: {curr_name or backup_name} ({curr_wxid})\n"
                f"• 成功恢复画像: {p_count} 个\n"
                f"• 状态: 基础大模型、白名单、多模态、VoIP与安全风控已全部热生效！"
            )
        except Exception as e:
            messagebox.showerror("导入异常", f"导入配置过程中发生未预期异常:\n{e}")
            self._append_log("warning", "配置中心", f"导入异常: {e}")

    def _reload_and_refresh_all_settings(self):
        """重新加载磁盘上的 config.json 与联系人画像，并全量刷新应用内各引擎与所有 UI 控件"""
        # 1. 重新从磁盘载入配置
        self.config = AppConfig.load()

        # 2. 热重载底层各个引擎
        self.llm_client.update_config(self.config.llm)
        self.rag_engine.reload_config(self.config.rag)
        self.profile_engine.update_config(self.config.profile, self.llm_client)
        self.pipeline.config = self.config
        self.bridge.config = self.config
        if hasattr(self, "call_agent") and self.call_agent:
            self.call_agent.reload_config(self.config)

        # 3. 刷新 Tab 1 (Dashboard) 状态显示
        if hasattr(self, "lbl_status_right"):
            self.lbl_status_right.configure(text="微信 4.x 自动化 | LLM: " + (self.config.llm.model_name or "未配置"))

        # 4. 刷新 Tab 2 (Targets)
        if hasattr(self, "selected_users"):
            self.selected_users = set(self.config.targets.whitelist_users)
        if hasattr(self, "selected_groups"):
            self.selected_groups = set(self.config.targets.whitelist_groups)
        if hasattr(self, "var_reply_all_private"):
            self.var_reply_all_private.set(self.config.targets.reply_all_private)
        if hasattr(self, "var_reply_all_groups"):
            self.var_reply_all_groups.set(self.config.targets.reply_all_groups)
        if hasattr(self, "var_group_at_only"):
            self.var_group_at_only.set(self.config.targets.group_at_only)
        if hasattr(self, "var_group_auto_at"):
            self.var_group_auto_at.set(self.config.targets.group_auto_at_sender)
        if hasattr(self, "_render_contacts_tree"):
            self._render_contacts_tree()
        if hasattr(self, "_render_groups_tree"):
            self._render_groups_tree()

        # 5. 刷新 Tab 3 (LLM & Safety)
        if hasattr(self, "var_api_url"):
            self.var_api_url.set(self.config.llm.api_url or "")
        if hasattr(self, "var_api_key"):
            self.var_api_key.set(self.config.llm.api_key or "")
        if hasattr(self, "var_model_name"):
            self.var_model_name.set(self.config.llm.model_name or "")
        if hasattr(self, "var_temp"):
            self.var_temp.set(float(self.config.llm.temperature))
        if hasattr(self, "var_max_tokens"):
            self.var_max_tokens.set(int(self.config.llm.max_tokens))

        self.presets = self.config.safety.get_presets()
        if hasattr(self, "cbo_preset"):
            self.cbo_preset["values"] = list(self.presets.keys())
        if hasattr(self, "var_preset"):
            self.var_preset.set(self.config.safety.preset_name or "通用友好助手")
        if hasattr(self, "txt_prompt"):
            self.txt_prompt.delete("1.0", "end")
            self.txt_prompt.insert("1.0", self.config.safety.system_prompt or "")

        if hasattr(self, "var_handover_kw"):
            self.var_handover_kw.set(self.config.safety.handover_keyword or "")
        if hasattr(self, "var_handover_reply"):
            self.var_handover_reply.set(self.config.safety.handover_reply or "")
        if hasattr(self, "var_reset_handover_kw"):
            self.var_reset_handover_kw.set(self.config.safety.reset_handover_keyword or "")
        if hasattr(self, "var_reply_prefix"):
            self.var_reply_prefix.set(self.config.safety.reply_prefix.replace("\n", "\\n") if self.config.safety.reply_prefix else "")
        if hasattr(self, "var_reply_suffix"):
            self.var_reply_suffix.set(self.config.safety.reply_suffix.replace("\n", "\\n") if self.config.safety.reply_suffix else "")
        if hasattr(self, "var_max_length"):
            self.var_max_length.set(int(self.config.safety.max_reply_length))
        if hasattr(self, "var_cooldown"):
            self.var_cooldown.set(float(self.config.safety.cooldown_seconds))
        if hasattr(self, "var_daily_limit"):
            self.var_daily_limit.set(int(self.config.safety.daily_chat_limit))
        if hasattr(self, "var_sensitive_words"):
            self.var_sensitive_words.set(self.config.safety.sensitive_words or "")
        if hasattr(self, "var_sensitive_action"):
            action_map = {
                "refuse": "婉拒回复 (友好说明)",
                "handover": "转接人工坐席",
                "ignore": "静默忽略 (不回复)"
            }
            self.var_sensitive_action.set(action_map.get(self.config.safety.sensitive_action, "婉拒回复 (友好说明)"))
        if hasattr(self, "var_sensitive_reply"):
            self.var_sensitive_reply.set(self.config.safety.sensitive_reply or "")
        if hasattr(self, "var_enable_tools"):
            self.var_enable_tools.set(bool(self.config.safety.enable_tools))

        # 6. 刷新 Tab 4 (RAG)
        if hasattr(self, "var_rag_enabled"):
            self.var_rag_enabled.set(self.config.rag.enabled)
        if hasattr(self, "var_rag_path"):
            self.var_rag_path.set(self.config.rag.kb_folder_path or "")

        # 7. 刷新 Tab 5 (Profiles)
        if hasattr(self, "var_profile_enabled"):
            self.var_profile_enabled.set(self.config.profile.enabled)
        if hasattr(self, "var_profile_private"):
            self.var_profile_private.set(self.config.profile.enable_private_chat)
        if hasattr(self, "var_profile_auto_refine"):
            self.var_profile_auto_refine.set(self.config.profile.auto_refine)
        if hasattr(self, "var_profile_inject"):
            self.var_profile_inject.set(self.config.profile.inject_prompt)
        if hasattr(self, "_load_profiles_into_tree"):
            self._load_profiles_into_tree()
        if hasattr(self, "p_detail_frame") and hasattr(self, "p_empty_tip"):
            self.p_detail_frame.pack_forget()
            self.p_empty_tip.pack(fill="both", expand=True)

        # 8. 刷新 Tab 6 (Media)
        if hasattr(self, "var_voice_enabled"):
            self.var_voice_enabled.set(bool(self.config.voice.enabled))
        if hasattr(self, "var_voice_engine"):
            self.var_voice_engine.set("云端 API (极速/轻量)" if self.config.voice.engine == "cloud" else "本地 Faster-Whisper (离线/高保密)")
        if hasattr(self, "var_voice_model"):
            self.var_voice_model.set(self.config.voice.whisper_model or "tiny")
        if hasattr(self, "var_voice_device"):
            self.var_voice_device.set(self.config.voice.whisper_device or "cpu")
        if hasattr(self, "var_voice_cloud_url"):
            self.var_voice_cloud_url.set(self.config.voice.cloud_api_url or "")
        if hasattr(self, "var_voice_cloud_key"):
            self.var_voice_cloud_key.set(self.config.voice.cloud_api_key or "")
        if hasattr(self, "var_voice_cloud_model"):
            self.var_voice_cloud_model.set(self.config.voice.cloud_model_name or "whisper-1")

        if hasattr(self, "var_image_enabled"):
            self.var_image_enabled.set(bool(self.config.image.enabled))
        if hasattr(self, "var_image_strategy"):
            strat_map = {
                "vision_only": "仅视觉分析 (Vision API)",
                "ocr_only": "仅OCR文字识别 (RapidOCR)",
                "auto": "智能融合 (优先OCR，无文字走视觉)"
            }
            self.var_image_strategy.set(strat_map.get(self.config.image.strategy, "智能融合 (优先OCR，无文字走视觉)"))
        if hasattr(self, "var_vision_model"):
            self.var_vision_model.set(self.config.image.vision_model_name or "")
        if hasattr(self, "var_vision_url"):
            self.var_vision_url.set(self.config.image.vision_api_url or "")
        if hasattr(self, "var_vision_key"):
            self.var_vision_key.set(self.config.image.vision_api_key or "")
        if hasattr(self, "var_fallback_ocr"):
            self.var_fallback_ocr.set(bool(self.config.image.fallback_to_ocr))

        # 9. 刷新 Tab 7 (VoIP)
        if hasattr(self, "voip_builder") and self.voip_builder:
            vb = self.voip_builder
            cfg = self.config.voip
            if hasattr(vb, "var_voip_enabled"): vb.var_voip_enabled.set(cfg.enabled)
            if hasattr(vb, "var_sync_reply"): vb.var_sync_reply.set(cfg.sync_reply_targets)
            if hasattr(vb, "var_enable_group"): vb.var_enable_group.set(cfg.enable_group_call)
            if hasattr(vb, "var_whitelist_groups"): vb.var_whitelist_groups.set(", ".join(cfg.whitelist_groups))
            if hasattr(vb, "var_tts_engine"):
                eng_val = cfg.tts_engine.lower()
                if "edge" in eng_val:
                    vb.var_tts_engine.set("Edge-TTS (微软高保真拟真 / 推荐)")
                elif "sapi" in eng_val:
                    vb.var_tts_engine.set("Windows SAPI (本地系统语音 / 离线免配置)")
                elif "chattts" in eng_val:
                    vb.var_tts_engine.set("ChatTTS (口语化拟真 / 喘气笑声)")
                else:
                    vb.var_tts_engine.set("Qwen3-TTS (高保真多语言 / 极速推理)")
            if hasattr(vb, "var_clone_enabled"): vb.var_clone_enabled.set(cfg.voice_clone_enabled)
            if hasattr(vb, "var_clone_path"): vb.var_clone_path.set(cfg.voice_clone_audio_path)
            if hasattr(vb, "var_answer_delay"): vb.var_answer_delay.set(cfg.auto_answer_delay_sec)
            if hasattr(vb, "var_max_duration"): vb.var_max_duration.set(cfg.max_call_duration_min)
            if hasattr(vb, "var_barge_in"): vb.var_barge_in.set(cfg.barge_in_enabled)
            if hasattr(vb, "var_in_dev"): vb.var_in_dev.set(cfg.virtual_input_device)
            if hasattr(vb, "var_out_dev"): vb.var_out_dev.set(cfg.virtual_output_device)
            if hasattr(vb, "_update_tts_status_ui"): vb._update_tts_status_ui()

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
                    text="⏸ 暂停自动回复",
                    bg="#6D35FF",
                    activebackground="#5821D8"
                )
                self.card_val_status.configure(text="运行中", fg="#00E6A7")
                if hasattr(self, "lbl_switch_pill"):
                    self.lbl_switch_pill.configure(text="[ 🟢 运行中 ]", bg="#06382B", fg="#00E6A7")
                self._append_log("sent", "系统", "自动回复功能已【开启】！")

                # 同步启动语音电话自动接听守护 (若开启)
                if hasattr(self, "call_agent") and self.call_agent and self.config.voip.enabled:
                    if not self.call_agent._running:
                        self.call_agent.start()
                        if hasattr(self, "voip_builder") and hasattr(self.voip_builder, "btn_toggle_agent"):
                            self.voip_builder.btn_toggle_agent.configure(
                                text="⏸ 停止电话守护",
                                bg=self.COLOR_DANGER,
                                activebackground="#D93D5E"
                            )
                            self.voip_builder.lbl_voip_badge.configure(text="🟢 待命监听中", bg="#06382B", fg="#00E6A7")
                        self._append_log("info", "系统", "微信语音电话自动接听守护已同步启动！")
            else:
                self.btn_toggle_autoreply.configure(
                    text="▶ 开启自动回复",
                    bg=self.COLOR_PRIMARY,
                    activebackground="#0056B3"
                )
                self.card_val_status.configure(text="已暂停", fg="#7892B2")
                if hasattr(self, "lbl_switch_pill"):
                    self.lbl_switch_pill.configure(text="[ ○ 关 ]", bg="#0F2444", fg="#7892B2")
                self._append_log("warning", "系统", "自动回复功能已【暂停】（仅监听记录，不发回复）。")

                # 同步暂停语音电话自动接听守护
                if hasattr(self, "call_agent") and self.call_agent:
                    if self.call_agent._running:
                        self.call_agent.stop()
                        if hasattr(self, "voip_builder") and hasattr(self.voip_builder, "btn_toggle_agent"):
                            self.voip_builder.btn_toggle_agent.configure(
                                text="▶ 开启电话守护",
                                bg=self.COLOR_SUCCESS,
                                activebackground="#00B380"
                            )
                            self.voip_builder.lbl_voip_badge.configure(text="⚪ 已停止", bg="#0F2444", fg="#7892B2")
                        self._append_log("warning", "系统", "微信语音电话守护已暂停。")
        else:
            messagebox.showerror("启动失败", msg)

    def _async_initial_load(self):
        """后台异步载入微信状态、启动消息监听并同步近期消息流与通讯录"""
        if getattr(self, "_is_initial_loading", False):
            return
        self._is_initial_loading = True
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
                        fg="#00E6A7"
                    )
                    self._append_log("info", "系统", f"已连接微信: {display_name} ({self_wxid})，正在同步近期最新消息流...")
                else:
                    self.lbl_wechat_status.configure(
                        text="○ 未检测到登录的微信 (请确认微信客户端已在电脑登录)",
                        fg="#FF5577"
                    )
            self.dispatch_ui(update_status)

            # 2. 若微信已连接，优先启动底层实时消息监听，并极速同步最新消息流到主看板
            if wechat_detected:
                self.bridge.start_listening()
                self._sync_recent_messages_internal(notify=False)

                # 自动启动语音电话来电守护 (若配置启用)
                if hasattr(self, "call_agent") and self.call_agent and self.config.voip.enabled:
                    if not self.call_agent._running:
                        self.call_agent.start()
                        def _update_voip_ui():
                            if hasattr(self, "voip_builder") and hasattr(self.voip_builder, "btn_toggle_agent"):
                                self.voip_builder.btn_toggle_agent.configure(
                                    text="⏸ 停止电话守护",
                                    bg=self.COLOR_DANGER,
                                    activebackground="#D93D5E"
                                )
                                self.voip_builder.lbl_voip_badge.configure(text="🟢 待命监听中", bg="#06382B", fg="#00E6A7")
                        self.dispatch_ui(_update_voip_ui)
                        self._append_log("info", "系统", "微信语音电话自动接听守护已伴随系统启动并进入待命监听！")

                def log_policy_tips():
                    if self.bridge.auto_reply_enabled:
                        self.btn_toggle_autoreply.configure(text="⏸ 暂停自动回复", bg="#6D35FF")
                        self.card_val_status.configure(text="运行中", fg="#00E6A7")
                        if hasattr(self, "lbl_switch_pill"):
                            self.lbl_switch_pill.configure(text="[ 🟢 运行中 ]", bg="#06382B", fg="#00E6A7")
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
                self._load_profiles_into_tree()
            self.dispatch_ui(update_trees)

            # 4. 若已配置知识库，在后台自动加载/预热索引并填充文档列表
            if self.config.rag.kb_folder_path and os.path.isdir(self.config.rag.kb_folder_path):
                try:
                    rag_res = self.rag_engine.reindex(self.config.rag.kb_folder_path, force=False)
                    if rag_res.get("success"):
                        doc_cnt = rag_res.get("doc_count", 0)
                        chunk_cnt = rag_res.get("chunk_count", 0)
                        def update_rag_status():
                            self.lbl_rag_status.configure(
                                text=f"✅ 索引就绪：共 {doc_cnt} 个文档，{chunk_cnt} 个切片片段",
                                fg=self.COLOR_SUCCESS
                            )
                            # 自动刷新扫描文档表格
                            self._on_scan_docs_click()
                        self.dispatch_ui(update_rag_status)
                except Exception as ex:
                    print(f"[RAG] 启动初始化加载知识库索引失败: {ex}")

        except Exception as e:
            self.dispatch_ui(self._append_log, "error", "异常", f"加载初始数据失败: {e}")
        finally:
            self._is_initial_loading = False

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

                if ev_type in (
                    "call_incoming", "call_connected", "barge_in", "caller_transcript",
                    "ai_sentence", "call_ended", "call_agent_started", "call_agent_stopped"
                ):
                    if hasattr(self, "voip_builder") and self.voip_builder:
                        self.voip_builder.handle_event(event)
                    if ev_type == "call_incoming":
                        caller = data.get("caller", "微信好友")
                        self._append_log("pipeline", "🔔 [来电振铃中]", f"检测到微信语音来电请求 (来自: [{caller}])，正在准备自动接听...")
                    elif ev_type == "call_connected":
                        caller = data.get("caller", "")
                        self._append_log("pipeline", "📞 [电话已接通]", f"开始与 [{caller}] 实时语音对答")
                    elif ev_type == "call_ended":
                        caller = data.get("caller", "")
                        dur = int(data.get("duration", 0))
                        self._append_log("sent", "📴 [电话已挂断]", f"与 [{caller}] 通话结束 (时长: {dur}秒)")
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

            # 若当前尚未启动底层监听，但检测到了微信登录，则自动连通 (带 _is_initial_loading 防抖锁)
            if wechat_detected and not self.bridge.is_running and not getattr(self, "_is_initial_loading", False):
                display_name = self_name.strip() if self_name and self_name.strip() else self_wxid
                title_text = f"🟢 微信: {display_name} ({self_wxid})" if display_name != self_wxid else f"🟢 微信: {self_wxid}"
                self.lbl_wechat_status.configure(
                    text=title_text,
                    fg="#00E6A7"
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
