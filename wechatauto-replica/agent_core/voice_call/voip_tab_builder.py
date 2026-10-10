# -*- coding: utf-8 -*-
"""微信电话语音通话桌面 UI 面板构建器 (agent_core.voice_call.voip_tab_builder)

提供专业的桌面 GUI 控制面板：
1. 电话守护状态与一键启停开关 (⚪ 待命 / 🟢 通话中 / 🔴 暂停)
2. 自动接听对象规则控制 (与回复白名单对齐，群聊独立控制与默认关闭)
3. TTS 语音合成 (ChatTTS / Qwen3-TTS) 引擎切换、自动下载与进度指示
4. 声音克隆 (Voice Cloning) 样本配置、试听与音色管理
5. 虚拟声卡设备选择与刷新 (CABLE-A / CABLE-B)
6. 实时通话彩色字幕流与打断监听监控看板
"""
from __future__ import annotations

import os
import time
import queue
import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog, scrolledtext
from typing import Optional, Dict, Any, List
import numpy as np
import cv2

from agent_core.voice_call.audio_router import AudioRouter
from agent_core.voice_call.voice_clone import VoiceCloneManager

logger = logging.getLogger("VoIPTabBuilder")


class VoIPTabBuilder:
    """VoIP 控制面板构建器"""

    def __init__(self, app):
        self.app = app
        self.config = app.config
        self.call_agent = getattr(app, "call_agent", None)
        self.voice_clone_mgr = VoiceCloneManager()
        self._current_active_voice_id = getattr(self.config.voip, "active_cloned_voice_id", "")
        self._voices_cache = []

    def build_tab(self, parent: ttk.Frame):
        """在给定父容器内构建完整的语音通话管理面板"""
        canvas = tk.Canvas(parent, bg=self.app.COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=self.app.COLOR_BG)

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

        # ---------------------------------------------------------------------
        # 顶部操作栏
        # ---------------------------------------------------------------------
        top_bar = tk.Frame(scroll_frame, bg=self.app.COLOR_BG)
        top_bar.pack(fill="x", padx=16, pady=(12, 6))

        tk.Label(
            top_bar,
            text="📞 微信语音电话自动接听与实时对话智能体",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg=self.app.COLOR_BG,
            fg=self.app.COLOR_TEXT
        ).pack(side="left")

        # 状态指示胶囊
        self.lbl_voip_badge = tk.Label(
            top_bar,
            text="⚪ 待命监听中",
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#0F2444",
            fg="#7892B2",
            padx=10,
            pady=4
        )
        self.lbl_voip_badge.pack(side="left", padx=12)

        # 顶部按钮
        btn_save_top = tk.Button(
            top_bar,
            text="💾 保存通话设置",
            command=self.on_save_voip_config_click,
            font=("Microsoft YaHei UI", 10, "bold"),
            bg=self.app.COLOR_PRIMARY,
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=5,
            cursor="hand2"
        )
        btn_save_top.pack(side="right", padx=4)

        self.btn_toggle_agent = tk.Button(
            top_bar,
            text="▶ 开启电话守护",
            command=self.on_toggle_voip_agent_click,
            font=("Microsoft YaHei UI", 10, "bold"),
            bg=self.app.COLOR_SUCCESS,
            fg="#ffffff",
            activebackground="#059669",
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=5,
            cursor="hand2"
        )
        self.btn_toggle_agent.pack(side="right", padx=6)

        # ---------------------------------------------------------------------
        # 卡片 1: 自动接听对象与防骚扰规则 (与回复对象对齐 / 群聊独立)
        # ---------------------------------------------------------------------
        card_targets = tk.Frame(scroll_frame, bg=self.app.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.app.COLOR_BORDER, highlightthickness=1)
        card_targets.pack(fill="x", padx=16, pady=6)

        tk.Label(card_targets, text="👥 自动接听权限与呼叫过滤规则", font=("Microsoft YaHei UI", 11, "bold"), bg=self.app.COLOR_CARD, fg=self.app.COLOR_TEXT).pack(anchor="w", padx=16, pady=(12, 4))

        # 功能总开关
        self.var_voip_enabled = tk.BooleanVar(value=self.config.voip.enabled)
        chk_enabled = tk.Checkbutton(
            card_targets,
            text="启用微信语音电话自动接听与全双工实时对答",
            variable=self.var_voip_enabled,
            bg=self.app.COLOR_CARD,
            font=("Microsoft YaHei UI", 9, "bold"),
            fg=self.app.COLOR_PRIMARY
        )
        chk_enabled.pack(anchor="w", padx=16, pady=2)

        # 规则 1: 与回复对象对齐
        self.var_sync_reply = tk.BooleanVar(value=self.config.voip.sync_reply_targets)
        chk_sync = tk.Checkbutton(
            card_targets,
            text="自动接听对象与当前微信自动回复对象(白名单)保持一致 (推荐，严格对齐已勾选的好友)",
            variable=self.var_sync_reply,
            bg=self.app.COLOR_CARD,
            font=("Microsoft YaHei UI", 9)
        )
        chk_sync.pack(anchor="w", padx=16, pady=2)

        sync_hint = (
            f"ℹ️ 当前回复白名单共配置 {len(self.config.targets.whitelist_users)} 位私聊好友。"
            f"{' (已开启全量私聊回复，将接听所有好友)' if self.config.targets.reply_all_private else ' (仅自动接听白名单内好友来电，其余好友忽略)'}"
        )
        tk.Label(card_targets, text=sync_hint, bg=self.app.COLOR_CARD, fg=self.app.COLOR_MUTED, font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=32, pady=(0, 4))

        # 规则 2: 群聊独立控制 (默认忽略全部群聊)
        self.var_enable_group = tk.BooleanVar(value=self.config.voip.enable_group_call)
        chk_grp = tk.Checkbutton(
            card_targets,
            text="允许接听群聊语音通话 (默认严格关闭，忽略所有群聊来电，避免受到骚扰)",
            variable=self.var_enable_group,
            bg=self.app.COLOR_CARD,
            font=("Microsoft YaHei UI", 9),
            fg="#b91c1c" if not self.config.voip.enable_group_call else self.app.COLOR_TEXT
        )
        chk_grp.pack(anchor="w", padx=16, pady=2)

        grp_frame = tk.Frame(card_targets, bg=self.app.COLOR_CARD)
        grp_frame.pack(fill="x", padx=32, pady=(0, 6))
        tk.Label(grp_frame, text="允许接听的群聊列表 (以逗号分隔群名称或群ID):", bg=self.app.COLOR_CARD, font=("Microsoft YaHei UI", 8)).pack(side="left")
        self.var_whitelist_groups = tk.StringVar(value=", ".join(self.config.voip.whitelist_groups))
        ttk.Entry(grp_frame, textvariable=self.var_whitelist_groups, width=45).pack(side="left", padx=8)

        # 参数配置小栏
        param_bar = tk.Frame(card_targets, bg=self.app.COLOR_CARD)
        param_bar.pack(fill="x", padx=16, pady=(4, 10))

        tk.Label(param_bar, text="来电接听延迟 (秒):", bg=self.app.COLOR_CARD).grid(row=0, column=0, sticky="w")
        self.var_answer_delay = tk.DoubleVar(value=self.config.voip.auto_answer_delay_sec)
        ttk.Entry(param_bar, textvariable=self.var_answer_delay, width=6).grid(row=0, column=1, sticky="w", padx=(4, 16))

        tk.Label(param_bar, text="单次通话最大时长 (分钟):", bg=self.app.COLOR_CARD).grid(row=0, column=2, sticky="w")
        self.var_max_duration = tk.IntVar(value=self.config.voip.max_call_duration_min)
        ttk.Entry(param_bar, textvariable=self.var_max_duration, width=6).grid(row=0, column=3, sticky="w", padx=(4, 16))

        self.var_barge_in = tk.BooleanVar(value=self.config.voip.barge_in_enabled)
        chk_barge = tk.Checkbutton(param_bar, text="全双工智能打断 (对方插话瞬间停音)", variable=self.var_barge_in, bg=self.app.COLOR_CARD)
        chk_barge.grid(row=0, column=4, sticky="w")

        self.var_echo_cancel = tk.BooleanVar(value=getattr(self.config.voip, "echo_cancellation_enabled", True))
        chk_echo = tk.Checkbutton(param_bar, text="AI自发音回声智能过滤 (防扬声器串音误判)", variable=self.var_echo_cancel, bg=self.app.COLOR_CARD, fg=self.app.COLOR_PRIMARY)
        chk_echo.grid(row=0, column=5, sticky="w", padx=(12, 0))

        # ---------------------------------------------------------------------
        # 卡片 1.5: 实时语音识别 (STT) 引擎配置 (优先 GPU 加速)
        # ---------------------------------------------------------------------
        card_stt = tk.Frame(scroll_frame, bg=self.app.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.app.COLOR_BORDER, highlightthickness=1)
        card_stt.pack(fill="x", padx=16, pady=6)

        tk.Label(card_stt, text="👂 实时语音识别引擎 (STT / ASR 极速毫秒响应)", font=("Microsoft YaHei UI", 11, "bold"), bg=self.app.COLOR_CARD, fg=self.app.COLOR_TEXT).pack(anchor="w", padx=16, pady=(12, 6))

        stt_row = tk.Frame(card_stt, bg=self.app.COLOR_CARD)
        stt_row.pack(fill="x", padx=16, pady=4)

        curr_stt = getattr(self.config.voip, "stt_engine", "paraformer").lower()
        init_stt_val = "FunASR Paraformer (阿里中文口语 / 毫秒级极速响应 / 推荐)" if "paraformer" in curr_stt else "Faster-Whisper (全语种多规格 / 基础成熟)"
        self.var_stt_engine = tk.StringVar(value=init_stt_val)
        self.combo_stt_engine = ttk.Combobox(
            stt_row,
            textvariable=self.var_stt_engine,
            values=[
                "FunASR Paraformer (阿里中文口语 / 毫秒级极速响应 / 推荐)",
                "Faster-Whisper (全语种多规格 / 基础成熟)"
            ],
            state="readonly",
            width=46
        )
        self.combo_stt_engine.pack(side="left", padx=8)
        self.combo_stt_engine.bind("<<ComboboxSelected>>", lambda _: self._update_stt_status_ui())

        self.lbl_stt_status = tk.Label(stt_row, text="检测中...", bg=self.app.COLOR_CARD, fg=self.app.COLOR_MUTED)
        self.lbl_stt_status.pack(side="left", padx=8)

        self.btn_install_stt = tk.Button(
            stt_row,
            text="📦 自动补齐依赖 / 校验",
            command=self.on_install_stt_click,
            bg="#e0e7ff",
            fg="#3730a3",
            relief="flat",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2"
        )
        self.btn_install_stt.pack(side="left", padx=6)

        # ---------------------------------------------------------------------
        # 卡片 2: 语音合成 (TTS) 与声音克隆 (Voice Cloning)
        # ---------------------------------------------------------------------
        card_tts = tk.Frame(scroll_frame, bg=self.app.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.app.COLOR_BORDER, highlightthickness=1)
        card_tts.pack(fill="x", padx=16, pady=6)

        tk.Label(card_tts, text="🗣️ 语音合成引擎 (TTS) 与 🎭 声音克隆 (Voice Cloning)", font=("Microsoft YaHei UI", 11, "bold"), bg=self.app.COLOR_CARD, fg=self.app.COLOR_TEXT).pack(anchor="w", padx=16, pady=(12, 6))

        engine_row = tk.Frame(card_tts, bg=self.app.COLOR_CARD)
        engine_row.pack(fill="x", padx=16, pady=4)

        current_eng = self.config.voip.tts_engine.lower()
        if "kokoro" in current_eng:
            init_val = "Kokoro-82M (超轻量 82M / 极速低延迟 / CPU首选)"
        elif "edge" in current_eng:
            init_val = "Edge-TTS (微软高保真拟真 / 推荐)"
        elif "sapi" in current_eng:
            init_val = "Windows SAPI (本地系统语音 / 离线免配置)"
        elif "chattts" in current_eng:
            init_val = "ChatTTS (口语化拟真 / 喘气笑声)"
        else:
            init_val = "Qwen3-TTS (GGML C++ 量化 / 高保真多语言)"
        self.var_tts_engine = tk.StringVar(value=init_val)
        self.combo_tts_engine = ttk.Combobox(
            engine_row,
            textvariable=self.var_tts_engine,
            values=[
                "Edge-TTS (微软高保真拟真 / 推荐)",
                "Kokoro-82M (超轻量 82M / 极速低延迟 / CPU首选)",
                "Qwen3-TTS (GGML C++ 量化 / 高保真多语言)",
                "ChatTTS (口语化拟真 / 喘气笑声)",
                "Windows SAPI (本地系统语音 / 离线免配置)"
            ],
            state="readonly",
            width=42
        )
        self.combo_tts_engine.pack(side="left", padx=8)
        self.combo_tts_engine.bind("<<ComboboxSelected>>", lambda _: self._update_tts_status_ui())

        self.lbl_tts_status = tk.Label(engine_row, text="检测中...", bg=self.app.COLOR_CARD, fg=self.app.COLOR_MUTED)
        self.lbl_tts_status.pack(side="left", padx=8)

        self.btn_download_tts = tk.Button(
            engine_row,
            text="📥 自动下载并配置模型",
            command=self.on_download_tts_click,
            bg="#e0e7ff",
            fg="#3730a3",
            relief="flat",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2"
        )
        self.btn_download_tts.pack(side="left", padx=6)

        # 声音克隆区域 (支持多段音频融合与命名音色库)
        clone_box = tk.LabelFrame(card_tts, text=" 🎭 声音克隆与音色库管理 (支持多段音频智能融合克隆，声线更拟真) ", bg=self.app.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), padx=12, pady=8)
        clone_box.pack(fill="x", padx=16, pady=(4, 10))

        self.var_clone_enabled = tk.BooleanVar(value=self.config.voip.voice_clone_enabled)
        chk_clone = tk.Checkbutton(
            clone_box,
            text="启用声音克隆 (开启后，AI 接电话时将使用下方选定的音色声线发音)",
            variable=self.var_clone_enabled,
            bg=self.app.COLOR_CARD,
            font=("Microsoft YaHei UI", 9, "bold"),
            fg=self.app.COLOR_PRIMARY
        )
        chk_clone.pack(anchor="w", pady=(0, 6))

        # 1. 音色选择与命名工具栏
        voice_bar = tk.Frame(clone_box, bg=self.app.COLOR_CARD)
        voice_bar.pack(fill="x", pady=2)

        tk.Label(voice_bar, text="当前生效音色:", bg=self.app.COLOR_CARD, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.var_active_voice = tk.StringVar()
        self.combo_voices = ttk.Combobox(voice_bar, textvariable=self.var_active_voice, state="readonly", width=30)
        self.combo_voices.pack(side="left", padx=6)
        self.combo_voices.bind("<<ComboboxSelected>>", self.on_voice_selected)

        btn_new_voice = tk.Button(voice_bar, text="➕ 新建音色", command=self.on_new_voice_click, bg="#e0e7ff", fg="#3730a3", relief="flat", font=("Microsoft YaHei UI", 8, "bold"), cursor="hand2")
        btn_new_voice.pack(side="left", padx=3)

        btn_rename_voice = tk.Button(voice_bar, text="✏️ 重命名", command=self.on_rename_voice_click, bg="#f1f5f9", relief="flat", font=("Microsoft YaHei UI", 8), cursor="hand2")
        btn_rename_voice.pack(side="left", padx=3)

        btn_del_voice = tk.Button(voice_bar, text="🗑️ 删除音色", command=self.on_delete_voice_click, bg="#fee2e2", fg="#991b1b", relief="flat", font=("Microsoft YaHei UI", 8), cursor="hand2")
        btn_del_voice.pack(side="left", padx=3)

        btn_test_audio = tk.Button(voice_bar, text="🎧 试听当前音色", command=self.on_test_voice_click, bg="#dcfce7", fg="#15803d", relief="flat", font=("Microsoft YaHei UI", 8, "bold"), cursor="hand2")
        btn_test_audio.pack(side="right", padx=4)

        # 2. 多段音频片段管理区域
        self.lbl_clips_summary = tk.Label(clone_box, text="当前音色包含的音频片段 (支持批量上传多段音频，系统自动无缝融合拼接):", bg=self.app.COLOR_CARD, font=("Microsoft YaHei UI", 8), fg=self.app.COLOR_MUTED)
        self.lbl_clips_summary.pack(anchor="w", pady=(6, 2))

        clips_frame = tk.Frame(clone_box, bg=self.app.COLOR_CARD)
        clips_frame.pack(fill="x", pady=2)

        list_container = tk.Frame(clips_frame, bg=self.app.COLOR_CARD)
        list_container.pack(side="left", fill="both", expand=True)

        self.clips_listbox = tk.Listbox(list_container, height=3, selectmode=tk.SINGLE, font=("Consolas", 8), bg="#F8FAFC", bd=1, relief="solid")
        self.clips_listbox.pack(side="left", fill="both", expand=True)
        clips_scroll = ttk.Scrollbar(list_container, orient="vertical", command=self.clips_listbox.yview)
        clips_scroll.pack(side="left", fill="y")
        self.clips_listbox.config(yscrollcommand=clips_scroll.set)

        btn_clips_col = tk.Frame(clips_frame, bg=self.app.COLOR_CARD)
        btn_clips_col.pack(side="left", padx=8, fill="y")

        btn_add_clips = tk.Button(btn_clips_col, text="➕ 批量添加音频段...", command=self.on_add_audio_clips_click, bg="#f1f5f9", relief="flat", font=("Microsoft YaHei UI", 8), cursor="hand2")
        btn_add_clips.pack(fill="x", pady=1)

        btn_remove_clip = tk.Button(btn_clips_col, text="➖ 移除选中段", command=self.on_remove_audio_clip_click, bg="#f1f5f9", relief="flat", font=("Microsoft YaHei UI", 8), cursor="hand2")
        btn_remove_clip.pack(fill="x", pady=1)

        self.var_clone_path = tk.StringVar(value=self.config.voip.voice_clone_audio_path)

        # ---------------------------------------------------------------------
        # 卡片 3: 虚拟声卡设备路由 (Virtual Audio Cable)
        # ---------------------------------------------------------------------
        card_audio = tk.Frame(scroll_frame, bg=self.app.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.app.COLOR_BORDER, highlightthickness=1)
        card_audio.pack(fill="x", padx=16, pady=6)

        audio_head = tk.Frame(card_audio, bg=self.app.COLOR_CARD)
        audio_head.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(audio_head, text="🎛️ 虚拟声卡与音频路由设置 (Virtual Audio Cable)", font=("Microsoft YaHei UI", 11, "bold"), bg=self.app.COLOR_CARD, fg=self.app.COLOR_TEXT).pack(side="left")

        btn_install_cable = tk.Button(
            audio_head,
            text="🔊 一键安装 VB-CABLE 驱动",
            command=self.on_install_vbcable_click,
            bg="#dcfce7",
            fg="#15803d",
            activebackground="#bbf7d0",
            relief="flat",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2"
        )
        btn_install_cable.pack(side="right", padx=4)

        btn_open_win_mixer = tk.Button(
            audio_head,
            text="⚙️ 打开 Windows 音量合成器 (为微信指定声卡)",
            command=self.on_open_win_mixer_click,
            bg="#e0e7ff",
            fg="#3730a3",
            activebackground="#c7d2fe",
            relief="flat",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2"
        )
        btn_open_win_mixer.pack(side="right", padx=6)

        guide_txt = (
            "📌 微信音频路由特别说明：\n"
            "微信 4.x/当前版本设置页已移除了应用内独立的扬声器/麦克风选择菜单，微信默认继承 Windows 系统音频。\n"
            "【全自动免干扰推荐方案】点击右上方【⚙️ 打开 Windows 音量合成器】，在下方“应用”列表中找到微信：\n"
            "  • 微信输出设备 (扬声器) 选择: CABLE Input (VB-Audio Virtual Cable)\n"
            "  • 微信输入设备 (麦克风) 选择: CABLE Output (VB-Audio Virtual Cable)\n"
            "（Windows 系统将永久记住微信的专属绑定，完全不影响你日常听歌看剧与佩戴耳机使用！）"
        )
        tk.Label(card_audio, text=guide_txt, bg="#f8fafc", fg=self.app.COLOR_MUTED, font=("Microsoft YaHei UI", 8), justify="left", padx=10, pady=6).pack(fill="x", padx=16, pady=4)

        self.var_in_dev = tk.StringVar(value=self.config.voip.virtual_input_device)
        self.var_out_dev = tk.StringVar(value=self.config.voip.virtual_output_device)

        self.frame_audio_status = tk.Frame(card_audio, bg="#F0FDF4", bd=1, relief="solid", highlightbackground="#86EFAC")
        self.frame_audio_status.pack(fill="x", padx=16, pady=(4, 10))

        self.lbl_audio_status = tk.Label(
            self.frame_audio_status,
            text="🟢 声卡自动路由检测中...",
            bg="#F0FDF4",
            fg="#15803D",
            font=("Microsoft YaHei UI", 8, "bold"),
            padx=10,
            pady=6,
            anchor="w"
        )
        self.lbl_audio_status.pack(side="left", fill="x", expand=True)

        btn_recheck_devs = tk.Button(
            self.frame_audio_status,
            text="🔄 重新检测",
            command=self.refresh_audio_devices,
            bg="#ffffff",
            fg="#1e293b",
            activebackground="#f1f5f9",
            bd=1,
            relief="solid",
            highlightbackground="#cbd5e1",
            font=("Microsoft YaHei UI", 8),
            cursor="hand2"
        )
        btn_recheck_devs.pack(side="right", padx=8, pady=4)

        # ---------------------------------------------------------------------
        # 卡片 3.5: 📹 微信视频通话与本地虚拟数字人 (LivePortrait & MuseTalk)
        # ---------------------------------------------------------------------
        card_video = tk.Frame(scroll_frame, bg=self.app.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.app.COLOR_BORDER, highlightthickness=1)
        card_video.pack(fill="x", padx=16, pady=6)

        video_head = tk.Frame(card_video, bg=self.app.COLOR_CARD)
        video_head.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(video_head, text="📹 微信视频通话与本地虚拟数字人 (ComfyUI / LivePortrait / MuseTalk)", font=("Microsoft YaHei UI", 11, "bold"), bg=self.app.COLOR_CARD, fg=self.app.COLOR_TEXT).pack(side="left")

        # 视频通话开关与接听方式
        v_ctrl_row = tk.Frame(card_video, bg=self.app.COLOR_CARD)
        v_ctrl_row.pack(fill="x", padx=16, pady=4)

        self.var_video_enabled = tk.BooleanVar(value=getattr(self.config.voip, "video_enabled", True))
        chk_video = tk.Checkbutton(v_ctrl_row, text="启用微信视频通话接听与数字人推流", variable=self.var_video_enabled, bg=self.app.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold"), fg=self.app.COLOR_PRIMARY)
        chk_video.pack(side="left")

        tk.Label(v_ctrl_row, text="视频呼入接听动作:", bg=self.app.COLOR_CARD, font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(16, 4))
        curr_vmode = getattr(self.config.voip, "video_answer_mode", "video")
        init_vmode_str = "接听并开启视频 (数字人)" if curr_vmode == "video" else "以语音接听 (仅音频)"
        self.var_video_mode = tk.StringVar(value=init_vmode_str)
        self.combo_video_mode = ttk.Combobox(
            v_ctrl_row,
            textvariable=self.var_video_mode,
            values=["接听并开启视频 (数字人)", "以语音接听 (仅音频)"],
            state="readonly",
            width=22
        )
        self.combo_video_mode.pack(side="left", padx=4)

        # 引擎选择行
        eng_row = tk.Frame(card_video, bg=self.app.COLOR_CARD)
        eng_row.pack(fill="x", padx=16, pady=4)

        tk.Label(eng_row, text="数字人推理引擎:", bg=self.app.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        curr_av_eng = getattr(self.config.voip, "avatar_engine", "liveportrait").lower()
        if "wav2lip" in curr_av_eng:
            init_av_str = "Wav2Lip-Realtime (GAN 音素口型补全 / OpenTalking 推荐轻量级 / 30-50 FPS)"
        elif "liveportrait" in curr_av_eng:
            init_av_str = "LivePortrait-Realtime (毫秒级表情隐空间形变 / 25-30 FPS / 推荐)"
        else:
            init_av_str = "MuseTalk (UNet 深度自适应口型修复 / 20-25 FPS)"

        self.var_avatar_engine = tk.StringVar(value=init_av_str)
        self.combo_avatar_engine = ttk.Combobox(
            eng_row,
            textvariable=self.var_avatar_engine,
            values=[
                "LivePortrait-Realtime (毫秒级表情隐空间形变 / 25-30 FPS / 推荐)",
                "Wav2Lip-Realtime (GAN 音素口型补全 / OpenTalking 推荐轻量级 / 30-50 FPS)",
                "MuseTalk (UNet 深度自适应口型修复 / 20-25 FPS)"
            ],
            state="readonly",
            width=58
        )
        self.combo_avatar_engine.pack(side="left", padx=8)
        self.combo_avatar_engine.bind("<<ComboboxSelected>>", self.on_avatar_engine_changed)

        # 立绘资产配置行
        avatar_row = tk.Frame(card_video, bg=self.app.COLOR_CARD)
        avatar_row.pack(fill="x", padx=16, pady=4)

        tk.Label(avatar_row, text="正面立绘图片:", bg=self.app.COLOR_CARD, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.var_avatar_image = tk.StringVar(value=getattr(self.config.voip, "avatar_image_path", "data/avatars/default_avatar.png"))
        self.entry_avatar_image = ttk.Entry(avatar_row, textvariable=self.var_avatar_image, width=38)
        self.entry_avatar_image.pack(side="left", padx=6)

        btn_browse_avatar = tk.Button(
            avatar_row,
            text="📁 浏览选择正面立绘",
            command=self.on_browse_avatar_image_click,
            bg="#f1f5f9",
            relief="flat",
            font=("Microsoft YaHei UI", 8),
            cursor="hand2"
        )
        btn_browse_avatar.pack(side="left", padx=4)

        btn_import_comfyui = tk.Button(
            avatar_row,
            text="🎨 从本地 ComfyUI 一键导入最新立绘",
            command=self.on_import_comfyui_image_click,
            bg="#fdf2f8",
            fg="#be185d",
            activebackground="#fce7f3",
            relief="flat",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2"
        )
        btn_import_comfyui.pack(side="left", padx=6)

        # 虚拟摄像头状态与测试推流行
        vcam_row = tk.Frame(card_video, bg=self.app.COLOR_CARD)
        vcam_row.pack(fill="x", padx=16, pady=(6, 12))

        self.lbl_vcam_status = tk.Label(vcam_row, text="📷 正在检测虚拟摄像头驱动...", bg=self.app.COLOR_CARD, fg=self.app.COLOR_MUTED, font=("Microsoft YaHei UI", 9))
        self.lbl_vcam_status.pack(side="left")

        btn_install_vcam = tk.Button(
            vcam_row,
            text="🛠️ 一键安装虚拟摄像头驱动 (UnityCapture / OBS)",
            command=self.on_install_vcam_click,
            bg="#dcfce7",
            fg="#15803d",
            activebackground="#bbf7d0",
            relief="flat",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2"
        )
        btn_install_vcam.pack(side="left", padx=8)

        btn_preview_avatar = tk.Button(
            vcam_row,
            text="👁️ 启动实时测试预览窗口",
            command=self.on_preview_avatar_click,
            bg="#eff6ff",
            fg="#1d4ed8",
            activebackground="#dbeafe",
            relief="flat",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2"
        )
        btn_preview_avatar.pack(side="left", padx=6)

        # 本地物理摄像头真人动作捕捉驱动行
        webcam_row = tk.Frame(card_video, bg=self.app.COLOR_CARD)
        webcam_row.pack(fill="x", padx=16, pady=(4, 12))

        tk.Label(webcam_row, text="📹 本地摄像头驱动:", bg=self.app.COLOR_CARD, font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")

        # 动态探测当前电脑实际物理/虚拟摄像头设备及真实硬件名称
        cam_values = ["0: 默认摄像头"]
        try:
            from agent_core.video_call.webcam_tracker import probe_camera_devices
            devs = probe_camera_devices()
            if devs:
                cam_values = [friendly for _, friendly in devs]
        except Exception:
            pass

        self.var_webcam_device = tk.StringVar(value=cam_values[0])
        self.combo_webcam_device = ttk.Combobox(
            webcam_row,
            textvariable=self.var_webcam_device,
            values=cam_values,
            state="readonly",
            width=22
        )
        self.combo_webcam_device.pack(side="left", padx=6)

        btn_refresh_webcam = tk.Button(
            webcam_row,
            text="🔄",
            command=self.on_refresh_webcam_devices_click,
            bg="#f1f5f9",
            fg="#475569",
            relief="flat",
            font=("Microsoft YaHei UI", 8),
            cursor="hand2"
        )
        btn_refresh_webcam.pack(side="left", padx=(0, 6))

        self.btn_toggle_webcam_driver = tk.Button(
            webcam_row,
            text="📹 开启本地摄像头动作驱动",
            command=self.on_toggle_webcam_driver_click,
            bg="#f0fdf4",
            fg="#166534",
            activebackground="#dcfce7",
            relief="flat",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2"
        )
        self.btn_toggle_webcam_driver.pack(side="left", padx=6)

        self.lbl_webcam_driver_status = tk.Label(
            webcam_row,
            text="⚪ 未启动 (支持真人坐摄像头前，眨眼/说话/转头实时复刻驱动数字人)",
            bg=self.app.COLOR_CARD,
            fg=self.app.COLOR_MUTED,
            font=("Microsoft YaHei UI", 8)
        )
        self.lbl_webcam_driver_status.pack(side="left", padx=4)

        btn_download_models = tk.Button(
            vcam_row,
            text="📥 下载数字人模型 (LivePortrait / MuseTalk)",
            command=self.on_download_avatar_models_click,
            bg="#fef3c7",
            fg="#b45309",
            activebackground="#fde68a",
            relief="flat",
            font=("Microsoft YaHei UI", 8, "bold"),
            cursor="hand2"
        )
        btn_download_models.pack(side="left", padx=6)

        # ---------------------------------------------------------------------
        # 卡片 4: 实时通话字幕与对话监控看板
        # ---------------------------------------------------------------------
        card_log = tk.Frame(scroll_frame, bg=self.app.COLOR_CARD, bd=1, relief="solid", highlightbackground=self.app.COLOR_BORDER, highlightthickness=1)
        card_log.pack(fill="both", expand=True, padx=16, pady=6)

        log_head = tk.Frame(card_log, bg=self.app.COLOR_CARD)
        log_head.pack(fill="x", padx=16, pady=(10, 4))
        tk.Label(log_head, text="📜 实时通话字幕与状态监控流", font=("Microsoft YaHei UI", 11, "bold"), bg=self.app.COLOR_CARD, fg=self.app.COLOR_TEXT).pack(side="left")

        btn_clear_voip_log = tk.Button(
            log_head,
            text="🧹 清空通话记录",
            command=lambda: self.txt_voip_logs.delete("1.0", "end"),
            bg="#0F2444",
            fg="#8CCBFF",
            activebackground="#163866",
            activeforeground="#38BDF8",
            bd=1,
            relief="solid",
            highlightbackground="#1E4E8C",
            font=("Microsoft YaHei UI", 8),
            cursor="hand2"
        )
        btn_clear_voip_log.pack(side="right")

        self.txt_voip_logs = scrolledtext.ScrolledText(
            card_log,
            height=9,
            font=("Consolas", 9),
            bg="#06111F",
            fg="#A8C7E8",
            insertbackground="#00E5FF",
            selectbackground="#1E3A8A",
            selectforeground="#F3F7FF",
            bd=1,
            relief="solid",
            highlightbackground=self.app.COLOR_BORDER,
            highlightthickness=1,
            wrap="word"
        )
        self.txt_voip_logs.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        # 配置色彩标签 (深色高对比科技感)
        self.txt_voip_logs.tag_configure("caller", foreground="#38BDF8")     # 对方转写 (电光蓝)
        self.txt_voip_logs.tag_configure("ai", foreground="#00E6A7")         # AI 回复发音 (青绿)
        self.txt_voip_logs.tag_configure("barge", foreground="#FF5577")      # 打断 (霓虹红)
        self.txt_voip_logs.tag_configure("info", foreground="#607D9E")       # 系统状态 (蓝灰)

        self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 微信电话助理组件就绪 · 当前继承大模型配置: {self.config.llm.model_name}")

        # 初始加载
        self.refresh_audio_devices()
        self._update_stt_status_ui()
        self._update_tts_status_ui()
        self._update_vcam_status_ui()
        self._populate_voices_dropdown()

    # -------------------------------------------------------------------------
    # 事件处理与交互动作
    # -------------------------------------------------------------------------

    def _append_voip_log(self, tag: str, text: str):
        """写入电话监控日志流"""
        self.txt_voip_logs.insert("end", text + "\n", tag)
        self.txt_voip_logs.see("end")

    def _update_stt_status_ui(self):
        """更新 STT 引擎状态与运行环境 (多线程异步检测，避免 UI 卡顿)"""
        stt_str = self.var_stt_engine.get().lower()
        is_para = "paraformer" in stt_str
        self.lbl_stt_status.configure(text="🔍 正在校验 STT 状态...", fg=self.app.COLOR_MUTED)

        def _async_check():
            has_runtime = False
            has_model = False
            gpu_str = "CPU"

            try:
                # 优先检测 GPU 状态
                try:
                    import torch
                    if torch.cuda.is_available():
                        gpu_str = f"GPU: {torch.cuda.get_device_name(0)}"
                    else:
                        import ctranslate2
                        if ctranslate2.get_cuda_device_count() > 0:
                            gpu_str = "GPU: CUDA (CTranslate2)"
                except Exception:
                    pass

                if is_para:
                    try:
                        import funasr  # noqa: F401
                        import modelscope  # noqa: F401
                        has_runtime = True
                    except Exception:
                        has_runtime = False

                    from agent_core.voice_call.stt_worker import STTWorker
                    model_name = getattr(self.config.voip, "paraformer_model", "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch")
                    has_model = STTWorker.is_paraformer_downloaded(model_name)
                else:
                    try:
                        import faster_whisper  # noqa: F401
                        has_runtime = True
                    except Exception:
                        has_runtime = False
                    has_model = True
            except Exception as e:
                logger.debug(f"[VoIPTabBuilder] 异步校验 STT 状态异常: {e}")

            def _apply():
                current_stt = self.var_stt_engine.get().lower()
                if ("paraformer" in current_stt) != is_para:
                    return
                if is_para:
                    if has_runtime and has_model:
                        self.lbl_stt_status.configure(text=f"✅ FunASR 运行库与模型均已就绪 [{gpu_str}]", fg=self.app.COLOR_SUCCESS)
                        self.btn_install_stt.configure(text="✅ 已就绪 (可重新校验)")
                    elif has_runtime and not has_model:
                        self.lbl_stt_status.configure(text=f"⚠️ FunASR 依赖已就绪，未下载模型 [{gpu_str}]", fg=self.app.COLOR_PRIMARY)
                        self.btn_install_stt.configure(text="📥 自动下载并预热模型")
                    elif not has_runtime:
                        self.lbl_stt_status.configure(text="⚠️ 缺少 FunASR / ModelScope 运行依赖", fg=self.app.COLOR_WARNING)
                        self.btn_install_stt.configure(text="📦 一键自动补齐依赖")
                else:
                    if has_runtime:
                        self.lbl_stt_status.configure(text=f"✅ Faster-Whisper 运行就绪 [{gpu_str}]", fg=self.app.COLOR_SUCCESS)
                        self.btn_install_stt.configure(text="✅ 已就绪")
                    else:
                        self.lbl_stt_status.configure(text="⚠️ 缺少 faster-whisper 运行库", fg=self.app.COLOR_WARNING)
                        self.btn_install_stt.configure(text="📦 一键安装依赖")

            if hasattr(self.app, "root") and self.app.root:
                self.app.root.after(0, _apply)

        threading.Thread(target=_async_check, daemon=True, name="CheckSTT").start()

    def on_install_stt_click(self):
        """一键补齐 STT 所需依赖与模型"""
        stt_str = self.var_stt_engine.get().lower()
        is_para = "paraformer" in stt_str
        self.lbl_stt_status.configure(text="⏳ 正在配置与补齐 STT 环境...", fg=self.app.COLOR_PRIMARY)
        self.btn_install_stt.configure(state="disabled")

        def _do():
            try:
                from agent_core.voice_call.tts_manager import TTSManager
                if is_para:
                    TTSManager.auto_install_engine_wheel("funasr")
                    self.app.root.after(0, lambda: self.lbl_stt_status.configure(text="⏳ 正在从阿里开源镜像缓存 Paraformer 模型..."))
                    from funasr import AutoModel
                    target_model = getattr(self.config.voip, "paraformer_model", "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch")
                    AutoModel(
                        model=target_model,
                        disable_update=True,
                        disable_pbar=True,
                        trust_remote_code=False,
                    )
                else:
                    TTSManager.auto_install_engine_wheel("faster_whisper")

                self.app.root.after(0, lambda: [
                    self.lbl_stt_status.configure(text="✅ STT 依赖与模型配置就绪！", fg=self.app.COLOR_SUCCESS),
                    self.btn_install_stt.configure(state="normal", text="✅ 配置就绪"),
                    self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] STT 语音识别引擎校验配置通过")
                ])
            except Exception as e:
                err = str(e)
                self.app.root.after(0, lambda: [
                    self.lbl_stt_status.configure(text=f"❌ 安装校验异常: {err[:20]}...", fg=self.app.COLOR_DANGER),
                    self.btn_install_stt.configure(state="normal", text="重试安装"),
                    self._append_voip_log("barge", f"[{time.strftime('%H:%M:%S')}] STT 补齐异常: {err}")
                ])

        threading.Thread(target=_do, daemon=True, name="InstallSTT").start()

    def _update_tts_status_ui(self):
        """更新 TTS 模型下载就绪状态与运行库状态 (异步多线程检测，杜绝 UI 线程卡顿)"""
        engine_str = self.var_tts_engine.get().lower()
        if "edge" in engine_str:
            self.lbl_tts_status.configure(text="✅ Edge-TTS 微软高清语音就绪 (零显存/拟真/推荐)", fg=self.app.COLOR_SUCCESS)
            self.btn_download_tts.configure(text="✅ 云端极速直连 (免下载)", state="disabled")
            return
        elif "sapi" in engine_str:
            self.lbl_tts_status.configure(text="✅ Windows 系统内置语音就绪 (100%离线)", fg=self.app.COLOR_SUCCESS)
            self.btn_download_tts.configure(text="✅ 系统内置 (免下载)", state="disabled")
            return

        self.btn_download_tts.configure(state="normal")
        if "kokoro" in engine_str:
            engine = "kokoro"
        elif "chattts" in engine_str:
            engine = "chattts"
        else:
            engine = "qwen3_tts"

        # 立即反馈 UI，避免任何等待卡顿感
        self.lbl_tts_status.configure(text="🔍 正在校验模型状态...", fg=self.app.COLOR_MUTED)

        def _async_check():
            has_weights = self.call_agent.tts_manager.is_model_downloaded(engine) if self.call_agent else False
            has_runtime = self.call_agent.tts_manager.is_runtime_available(engine) if self.call_agent else False

            # 获取 GPU 状态标签
            dev_str, dev_name, _ = self.call_agent.tts_manager.get_optimal_device() if self.call_agent else ("cpu", "CPU", None)
            gpu_tag = f" [GPU: {dev_name}]" if dev_str.startswith("cuda") else ""

            def _apply():
                current_now = self.var_tts_engine.get().lower()
                if "kokoro" in current_now:
                    expected = "kokoro"
                elif "chattts" in current_now:
                    expected = "chattts"
                else:
                    expected = "qwen3_tts"
                if expected != engine:
                    return

                if engine == "kokoro":
                    if has_weights and has_runtime:
                        self.lbl_tts_status.configure(text=f"✅ Kokoro-82M 运行库与权重均已就绪{gpu_tag}", fg=self.app.COLOR_SUCCESS)
                        self.btn_download_tts.configure(text="✅ 已就绪 (可重新校验)")
                    elif has_runtime and not has_weights:
                        self.lbl_tts_status.configure(text=f"⚠️ Kokoro-82M 运行库就绪，权重未下载 (约85MB){gpu_tag}", fg=self.app.COLOR_WARNING)
                        self.btn_download_tts.configure(text="📥 自动下载并配置模型")
                    elif has_weights and not has_runtime:
                        self.lbl_tts_status.configure(text="⚠️ Kokoro-82M 缺少运行依赖 (kokoro-onnx)", fg=self.app.COLOR_WARNING)
                        self.btn_download_tts.configure(text="📦 一键安装运行库")
                    else:
                        self.lbl_tts_status.configure(text="⚠️ Kokoro-82M 权重未下载", fg=self.app.COLOR_WARNING)
                        self.btn_download_tts.configure(text="📥 自动下载并配置模型")
                elif engine == "chattts":
                    if has_weights and has_runtime:
                        self.lbl_tts_status.configure(text=f"✅ ChatTTS 运行库与权重均已就绪{gpu_tag}", fg=self.app.COLOR_SUCCESS)
                        self.btn_download_tts.configure(text="✅ 已就绪 (可重新校验)")
                    elif has_runtime and not has_weights:
                        self.lbl_tts_status.configure(text="⚠️ ChatTTS 运行库已就绪，权重未下载", fg=self.app.COLOR_WARNING)
                        self.btn_download_tts.configure(text="📥 自动下载并配置模型")
                    elif has_weights and not has_runtime:
                        self.lbl_tts_status.configure(text="💡 权重就绪 (通话中自动由 Edge-TTS 高保真发音)", fg=self.app.COLOR_PRIMARY)
                        self.btn_download_tts.configure(text="✅ 权重已就绪")
                    else:
                        self.lbl_tts_status.configure(text="⚠️ ChatTTS 权重未下载", fg=self.app.COLOR_WARNING)
                        self.btn_download_tts.configure(text="📥 自动下载并配置模型")
                else:  # qwen3_tts
                    if has_weights and has_runtime:
                        self.lbl_tts_status.configure(text=f"✅ Qwen3-TTS 运行库与权重均已就绪{gpu_tag}", fg=self.app.COLOR_SUCCESS)
                        self.btn_download_tts.configure(text="✅ 已就绪 (可重新校验)")
                    elif has_runtime and not has_weights:
                        self.lbl_tts_status.configure(text="⚠️ Qwen3-TTS 运行库已就绪，权重未下载", fg=self.app.COLOR_WARNING)
                        self.btn_download_tts.configure(text="📥 自动下载并配置模型")
                    elif has_weights and not has_runtime:
                        self.lbl_tts_status.configure(text="💡 权重就绪 (通话中自动由 Edge-TTS 高保真发音)", fg=self.app.COLOR_PRIMARY)
                        self.btn_download_tts.configure(text="✅ 权重已就绪")
                    else:
                        self.lbl_tts_status.configure(text="⚠️ Qwen3-TTS 权重未下载", fg=self.app.COLOR_WARNING)
                        self.btn_download_tts.configure(text="📥 自动下载并配置模型")

            if hasattr(self.app, "root") and self.app.root:
                self.app.root.after(0, _apply)

        threading.Thread(target=_async_check, daemon=True, name=f"CheckTTS-{engine}").start()

    def on_download_tts_click(self):
        """一键从镜像站自动下载模型"""
        engine_str = self.var_tts_engine.get().lower()
        if "kokoro" in engine_str:
            engine = "kokoro"
        elif "chattts" in engine_str:
            engine = "chattts"
        else:
            engine = "qwen3_tts"

        self.lbl_tts_status.configure(text=f"⏳ 正在从国内高速镜像下载 {engine.upper()}...", fg=self.app.COLOR_PRIMARY)
        self.btn_download_tts.configure(state="disabled")

        def _cb(status, prog):
            def _update():
                if status == "completed":
                    self.lbl_tts_status.configure(text=f"✅ {engine.upper()} 下载并配置就绪！", fg=self.app.COLOR_SUCCESS)
                    self.btn_download_tts.configure(state="normal", text="✅ 下载完成")
                    self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] {engine.upper()} 权重下载校验通过")
                elif status == "failed":
                    self.lbl_tts_status.configure(text="❌ 下载失败，请检查网络", fg=self.app.COLOR_DANGER)
                    self.btn_download_tts.configure(state="normal", text="重试下载")
                    self._append_voip_log("barge", f"[{time.strftime('%H:%M:%S')}] {engine.upper()} 下载异常")
                else:
                    self.lbl_tts_status.configure(text=f"⏳ 下载中 ({int(prog*100)}%)...", fg=self.app.COLOR_PRIMARY)
            if hasattr(self.app, "root") and self.app.root:
                self.app.root.after(0, _update)

        if self.call_agent:
            self.call_agent.tts_manager.auto_download_model(engine, background=True, progress_cb=_cb)

    def _populate_voices_dropdown(self):
        """刷新音色下拉框与音频片段列表"""
        self._voices_cache = self.voice_clone_mgr.list_voices()

        # 若无音色但历史配置中有单文件克隆音频，自动导入并建档
        if not self._voices_cache and self.config.voip.voice_clone_audio_path and os.path.exists(self.config.voip.voice_clone_audio_path):
            try:
                prof = self.voice_clone_mgr.import_voice_sample(
                    self.config.voip.voice_clone_audio_path,
                    "默认导入音色",
                    self.config.voip.voice_clone_prompt_text
                )
                self._current_active_voice_id = prof.voice_id
                self._voices_cache = self.voice_clone_mgr.list_voices()
            except Exception as e:
                logger.warning(f"导入历史参考音频失败: {e}")

        display_values = []
        target_idx = 0
        for idx, v in enumerate(self._voices_cache):
            cnt = len(v.get("audio_paths", []))
            display_values.append(f"🎭 {v['name']} ({cnt}段音频)")
            if v["voice_id"] == self._current_active_voice_id:
                target_idx = idx

        self.combo_voices["values"] = display_values
        if display_values:
            if not self._current_active_voice_id and self._voices_cache:
                self._current_active_voice_id = self._voices_cache[0]["voice_id"]
                target_idx = 0
            self.combo_voices.current(target_idx)
        else:
            self.var_active_voice.set("暂无克隆音色 (点击新建)")

        self._update_clips_listbox()

    def _update_clips_listbox(self):
        """更新当前音色包含的多段音频列表"""
        self.clips_listbox.delete(0, tk.END)
        prof = self.voice_clone_mgr.get_voice(self._current_active_voice_id) if self._current_active_voice_id else None
        if prof and prof.audio_paths:
            for idx, p in enumerate(prof.audio_paths):
                self.clips_listbox.insert(tk.END, f"{idx+1}. {os.path.basename(p)}  ({p})")
            self.lbl_clips_summary.configure(
                text=f"音色 【{prof.name}】 包含 {len(prof.audio_paths)} 段音频片段（已融合至主模型参考库）:",
                fg=self.app.COLOR_TEXT
            )
            self.var_clone_path.set(prof.audio_path)
            if self.call_agent:
                self.call_agent.tts_manager.set_voice_clone(prof.audio_path, prof.prompt_text)
        elif prof:
            self.lbl_clips_summary.configure(
                text=f"音色 【{prof.name}】 暂无音频片段，请点击下方【➕ 批量添加音频段...】:",
                fg="#dc2626"
            )
            self.var_clone_path.set("")
        else:
            self.lbl_clips_summary.configure(
                text="暂未选择或创建克隆音色，可点击右侧【➕ 新建音色】创建:",
                fg=self.app.COLOR_MUTED
            )
            self.var_clone_path.set("")

    def on_voice_selected(self, event=None):
        """用户在下拉框切换音色"""
        idx = self.combo_voices.current()
        if 0 <= idx < len(self._voices_cache):
            v = self._voices_cache[idx]
            self._current_active_voice_id = v["voice_id"]
            self._update_clips_listbox()
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 已切换当前生效克隆音色: 【{v['name']}】")

    def on_new_voice_click(self):
        """新建命名克隆音色"""
        name = simpledialog.askstring("新建克隆音色", "请输入新音色名称 (例如: 张总原声、客服专员、温柔女声):", parent=self.app.root)
        if not name or not name.strip():
            return
        name = name.strip()

        paths = filedialog.askopenfilenames(
            title=f"为音色【{name}】选择 1~多段音频文件 (支持多选)",
            filetypes=[("音频文件", "*.wav *.mp3 *.m4a *.aac *.flac"), ("所有文件", "*.*")]
        )
        if not paths:
            return

        try:
            prof = self.voice_clone_mgr.create_voice(name, list(paths))
            self._current_active_voice_id = prof.voice_id
            self._populate_voices_dropdown()
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 成功创建并融合音色: 【{prof.name}】(含 {len(paths)} 段音频)")
            messagebox.showinfo("成功", f"🎉 音色【{prof.name}】创建成功！\n已自动将 {len(paths)} 段音频高保真融合拼接。")
        except Exception as e:
            messagebox.showerror("创建失败", f"音色融合创建失败: {e}")

    def on_rename_voice_click(self):
        """重命名当前音色"""
        if not self._current_active_voice_id:
            messagebox.showwarning("提示", "请先选择要重命名的音色！")
            return
        prof = self.voice_clone_mgr.get_voice(self._current_active_voice_id)
        if not prof:
            return

        new_name = simpledialog.askstring("重命名音色", "请输入新的音色名称:", initialvalue=prof.name, parent=self.app.root)
        if new_name and new_name.strip() and new_name.strip() != prof.name:
            self.voice_clone_mgr.update_voice(prof.voice_id, name=new_name.strip())
            self._populate_voices_dropdown()
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 音色已重命名为: 【{new_name.strip()}】")

    def on_delete_voice_click(self):
        """删除当前音色"""
        if not self._current_active_voice_id:
            messagebox.showwarning("提示", "请先选择要删除的音色！")
            return
        prof = self.voice_clone_mgr.get_voice(self._current_active_voice_id)
        if not prof:
            return

        if messagebox.askyesno("删除确认", f"确定要删除音色【{prof.name}】及其已融合的声学样本吗？", parent=self.app.root):
            self.voice_clone_mgr.delete_voice(prof.voice_id)
            self._current_active_voice_id = ""
            self._populate_voices_dropdown()
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 已删除音色: 【{prof.name}】")

    def on_add_audio_clips_click(self):
        """向当前音色批量追加音频片段"""
        if not self._current_active_voice_id:
            messagebox.showwarning("提示", "请先在上方选择或新建一个音色！")
            return
        prof = self.voice_clone_mgr.get_voice(self._current_active_voice_id)
        if not prof:
            return

        paths = filedialog.askopenfilenames(
            title=f"为音色【{prof.name}】批量追加音频片段",
            filetypes=[("音频文件", "*.wav *.mp3 *.m4a *.aac *.flac"), ("所有文件", "*.*")]
        )
        if not paths:
            return

        try:
            new_paths = list(prof.audio_paths) + list(paths)
            self.voice_clone_mgr.update_voice(prof.voice_id, audio_paths=new_paths)
            self._populate_voices_dropdown()
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 音色【{prof.name}】已追加 {len(paths)} 段音频并重新融合")
        except Exception as e:
            messagebox.showerror("融合失败", f"音频融合异常: {e}")

    def on_remove_audio_clip_click(self):
        """从当前音色移除选中的音频片段"""
        if not self._current_active_voice_id:
            return
        sel = self.clips_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请在列表中点击选中要移除的音频段！")
            return
        idx = sel[0]
        prof = self.voice_clone_mgr.get_voice(self._current_active_voice_id)
        if not prof or idx >= len(prof.audio_paths):
            return

        new_paths = list(prof.audio_paths)
        removed_p = new_paths.pop(idx)
        if not new_paths:
            messagebox.showwarning("提示", "每个克隆音色至少需保留 1 段音频片段！若需彻底弃用请直接删除音色。")
            return

        try:
            self.voice_clone_mgr.update_voice(prof.voice_id, audio_paths=new_paths)
            self._populate_voices_dropdown()
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 已移除音频段: {os.path.basename(removed_p)}")
        except Exception as e:
            messagebox.showerror("移除失败", f"重新融合失败: {e}")

    def on_browse_audio_click(self):
        """保留单音频浏览兼容接口"""
        self.on_new_voice_click()

    def on_test_voice_click(self):
        """试听当前声音发音"""
        prof = self.voice_clone_mgr.get_voice(self._current_active_voice_id) if self._current_active_voice_id else None
        target_ref = prof.audio_path if (prof and prof.audio_path) else self.var_clone_path.get().strip()
        voice_title = prof.name if prof else "预设声音"

        test_text = "喂，你好！我是微信语音电话智能助理，很高兴为你提供帮助。"
        self._append_voip_log("ai", f"[{time.strftime('%H:%M:%S')}] 正在使用音色【{voice_title}】生成试听: 「{test_text}」...")

        def _do():
            try:
                if self.call_agent:
                    pcm, rate = self.call_agent.tts_manager.synthesize(
                        test_text,
                        ref_audio=target_ref if self.var_clone_enabled.get() else None
                    )
                    if pcm:
                        # 播放到默认声卡供用户试听
                        import sounddevice as sd
                        import numpy as np
                        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                        sd.play(samples, samplerate=rate)
                        sd.wait()
                        self.app.root.after(0, lambda: self._append_voip_log("ai", f"[{time.strftime('%H:%M:%S')}] 音色【{voice_title}】试听播放完毕"))
            except Exception as e:
                self.app.root.after(0, lambda: self._append_voip_log("barge", f"[{time.strftime('%H:%M:%S')}] 试听合成异常: {e}"))

        threading.Thread(target=_do, daemon=True).start()

    def refresh_audio_devices(self):
        """刷新声卡列表"""
        devs = AudioRouter.list_devices()
        in_names = []
        out_names = []
        for d in devs:
            name = d["name"]
            if d["max_inputs"] > 0:
                in_names.append(f"{d['id']}: {name}")
            if d["max_outputs"] > 0:
                out_names.append(f"{d['id']}: {name}")

        if hasattr(self, "combo_in_dev"):
            self.combo_in_dev["values"] = in_names
        if hasattr(self, "combo_out_dev"):
            self.combo_out_dev["values"] = out_names

        # 智能校验与校准当前所选声卡编号，防止设备编号漂移或遗留错误的 DirectSound/WASAPI 编号
        cur_in = self.var_in_dev.get().strip()
        if not cur_in or cur_in not in in_names or cur_in.startswith("9:") or cur_in.startswith("21:"):
            matched = False
            for n in in_names:
                if "cable output" in n.lower():
                    self.var_in_dev.set(n)
                    matched = True
                    break
            if not matched:
                for n in in_names:
                    if "cable" in n.lower():
                        self.var_in_dev.set(n)
                        break

        cur_out = self.var_out_dev.get().strip()
        if not cur_out or cur_out not in out_names or cur_out.startswith("13:") or cur_out.startswith("14:") or cur_out.startswith("17:"):
            matched = False
            for n in out_names:
                if "cable input" in n.lower():
                    self.var_out_dev.set(n)
                    matched = True
                    break
            if not matched:
                for n in out_names:
                    if "cable" in n.lower():
                        self.var_out_dev.set(n)
                        break

        # 更新声卡状态指示条
        has_in = bool(self.var_in_dev.get().strip())
        has_out = bool(self.var_out_dev.get().strip())
        if hasattr(self, "lbl_audio_status") and self.lbl_audio_status:
            if has_in and has_out:
                in_clean = self.var_in_dev.get().split(":", 1)[-1].strip()
                out_clean = self.var_out_dev.get().split(":", 1)[-1].strip()
                self.lbl_audio_status.config(
                    text=f"🟢 声卡自动路由已就绪：录音听对方=[{in_clean}] | 播放对微信=[{out_clean}]",
                    fg="#15803D"
                )
                if hasattr(self, "frame_audio_status"):
                    self.frame_audio_status.config(bg="#F0FDF4", highlightbackground="#86EFAC")
            else:
                self.lbl_audio_status.config(
                    text="🔴 未检测到 VB-CABLE 虚拟声卡！请点击右上角【🔊 一键安装 VB-CABLE 驱动】后点重新检测",
                    fg="#B91C1C"
                )
                if hasattr(self, "frame_audio_status"):
                    self.frame_audio_status.config(bg="#FEF2F2", highlightbackground="#FCA5A5")

    def on_install_vbcable_click(self):
        """一键运行 VB-CABLE 虚拟声卡安装向导"""
        import ctypes
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        exe_candidates = [
            os.path.join(base_dir, "tools", "vbcable", "VBCABLE_Setup_x64.exe"),
            os.path.join(base_dir, "wechatauto-replica", "tools", "vbcable", "VBCABLE_Setup_x64.exe"),
            os.path.join(os.getcwd(), "tools", "vbcable", "VBCABLE_Setup_x64.exe"),
            os.path.join(os.path.dirname(os.getcwd()), "tools", "vbcable", "VBCABLE_Setup_x64.exe"),
        ]
        setup_exe = None
        for cand in exe_candidates:
            if os.path.exists(cand):
                setup_exe = os.path.abspath(cand)
                break

        if setup_exe:
            try:
                # 使用 Windows 专属 Win32 ShellExecuteW 请求管理员权限运行，避免 cmd 批处理编码问题
                ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", setup_exe, None, None, 1)
                if ret > 32:
                    self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 已直接唤起 VB-CABLE 官方安装器，请在弹出的窗口中点击【Install Driver】")
                    return
            except Exception as e:
                logger.warning(f"ShellExecuteW runas failed: {e}")

        # 备选路径：运行修复后的 GBK 批处理脚本
        bat_candidates = [
            os.path.join(os.getcwd(), "install_vbcable.bat"),
            os.path.join(base_dir, "install_vbcable.bat"),
            os.path.join(base_dir, "wechatauto-replica", "install_vbcable.bat"),
        ]
        for bat_path in bat_candidates:
            if os.path.exists(bat_path):
                os.system(f'start "" "{bat_path}"')
                self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 正在唤起 VB-CABLE 安装向导...")
                return

        messagebox.showerror("未找到安装程序", "未找到 VBCABLE_Setup_x64.exe 或 install_vbcable.bat！")

    def on_open_win_mixer_click(self):
        """打开 Windows 音量合成器 (设置微信进程专属声卡)"""
        try:
            # 优先打开 Windows 10/11 应用音量与设备首选项
            os.system("start ms-settings:apps-volume")
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 已为您打开 Windows 音量合成器，请在下方【微信】一栏中绑定 CABLE 设备")
        except Exception:
            os.system("start ms-settings:sound")

    def _update_vcam_status_ui(self):
        """检测虚拟摄像头驱动状态"""
        def _check():
            try:
                from agent_core.video_call.video_router import check_virtual_camera_available
                ok, msg = check_virtual_camera_available()
            except Exception as e:
                ok, msg = False, str(e)

            def _apply():
                if hasattr(self, "lbl_vcam_status") and self.lbl_vcam_status:
                    if ok:
                        self.lbl_vcam_status.configure(text=f"✅ 虚拟摄像头已就绪 ({msg})", fg=self.app.COLOR_SUCCESS)
                    else:
                        self.lbl_vcam_status.configure(text=f"⚠️ {msg}", fg=self.app.COLOR_WARNING)

            if hasattr(self.app, "root") and self.app.root:
                self.app.root.after(0, _apply)

        threading.Thread(target=_check, daemon=True, name="CheckVCam").start()

    def on_avatar_engine_changed(self, event=None):
        """用户在运行时切换数字人引擎 (异步后台加载与预热，杜绝 UI 界面卡死)"""
        val = self.var_avatar_engine.get().lower()
        if "wav2lip" in val:
            target_eng = "wav2lip"
        elif "liveportrait" in val:
            target_eng = "liveportrait"
        else:
            target_eng = "musetalk"

        self.combo_avatar_engine.config(state="disabled")
        self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] ⏳ 正在后台切换并预热数字人推理引擎 [{target_eng}]，界面保持流畅...")

        def _bg_switch():
            try:
                if self.call_agent and hasattr(self.call_agent, "avatar_manager") and self.call_agent.avatar_manager:
                    self.call_agent.avatar_manager.set_engine_type(target_eng)
                def _ui_done():
                    self.combo_avatar_engine.config(state="readonly")
                    self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 🎨 ✅ 数字人驱动引擎已成功切换并预热就绪: [{target_eng}]")
                self.app.root.after(0, _ui_done)
            except Exception as ex:
                def _ui_err():
                    self.combo_avatar_engine.config(state="readonly")
                    self._append_voip_log("barge", f"[{time.strftime('%H:%M:%S')}] ⚠️ 引擎切换异常: {ex}")
                self.app.root.after(0, _ui_err)

        threading.Thread(target=_bg_switch, daemon=True, name="SwitchAvatarEngine").start()

    def on_toggle_webcam_driver_click(self):
        """用户开关本地真实物理摄像头动作驱动数字人"""
        if not self.call_agent or not hasattr(self.call_agent, "avatar_manager") or not self.call_agent.avatar_manager:
            messagebox.showinfo("提示", "数字人总控管理器尚未初始化！")
            return

        mgr = self.call_agent.avatar_manager
        is_active = hasattr(mgr, "webcam_tracker") and mgr.webcam_tracker and mgr.webcam_tracker.is_running

        if is_active:
            mgr.stop_webcam_driver()
            self.btn_toggle_webcam_driver.config(text="📹 开启本地摄像头动作驱动", bg="#f0fdf4", fg="#166534")
            self.lbl_webcam_driver_status.config(text="⚪ 已关闭本地摄像头驱动", fg=self.app.COLOR_MUTED)
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] ⏹️ 已关闭本地物理摄像头动作捕捉驱动")
        else:
            dev_str = self.var_webcam_device.get()
            dev_idx = 0
            try:
                import re
                m = re.search(r'\d+', dev_str)
                if m:
                    dev_idx = int(m.group())
            except Exception:
                dev_idx = 0

            ok = mgr.start_webcam_driver(device_index=dev_idx)
            if ok:
                self.btn_toggle_webcam_driver.config(text="⏹️ 停止摄像头动作驱动", bg="#fef2f2", fg="#991b1b")
                self.lbl_webcam_driver_status.config(text=f"🟢 正在实时捕捉本地摄像头 [{dev_str}] 动作驱动数字人中...", fg="#16a34a")
                self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 📹 成功开启本地物理摄像头 [{dev_str}] 动作捕捉驱动数字人！")
            else:
                messagebox.showwarning("摄像头打开失败", f"无法打开本地摄像头设备 [{dev_str}]，请检查是否已被其他软件占用。")

    def on_refresh_webcam_devices_click(self):
        """刷新探测本地物理/虚拟摄像头设备列表"""
        try:
            from agent_core.video_call.webcam_tracker import probe_camera_devices
            devs = probe_camera_devices()
            vals = [friendly for _, friendly in devs] if devs else ["0: 默认摄像头"]
            self.combo_webcam_device['values'] = vals
            cur = self.var_webcam_device.get()
            if cur not in vals:
                self.var_webcam_device.set(vals[0])
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 🔄 已刷新本地摄像头设备: {', '.join(vals)}")
        except Exception as e:
            logger.debug(f"[VoIPTabBuilder] 刷新摄像头列表异常: {e}")

    def on_browse_avatar_image_click(self):
        """浏览选择本地正面立绘"""
        path = filedialog.askopenfilename(
            title="选择人物正面立绘 (推荐 512x512 或 720x720 正面清晰半身照)",
            filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.webp"), ("All files", "*.*")]
        )
        if path:
            self.var_avatar_image.set(path)
            if self.call_agent and hasattr(self.call_agent, "avatar_manager") and self.call_agent.avatar_manager:
                ok = self.call_agent.avatar_manager.set_character_image(path)
                if ok:
                    self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] ✅ 成功更新正面人物立绘: {os.path.basename(path)}")
                else:
                    self._append_voip_log("barge", f"[{time.strftime('%H:%M:%S')}] ⚠️ 人物立绘加载失败: {path}")

    def on_import_comfyui_image_click(self):
        """从本地 ComfyUI 一键拉取最新生成的图像并设为立绘"""
        def _fetch():
            from agent_core.video_call.comfyui_bridge import ComfyUIBridge
            c_url = getattr(self.config.voip, "comfyui_url", "http://127.0.0.1:8188")
            bridge = ComfyUIBridge(c_url)
            if not bridge.check_connection():
                self.app.root.after(0, lambda: messagebox.showwarning("ComfyUI 未连接", "未检测到本地 ComfyUI 服务 (默认 http://127.0.0.1:8188)！\n请确保 ComfyUI 正在运行中。"))
                return

            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 🎨 正在从 ComfyUI 获取最新生成人物立绘...")
            dest = bridge.fetch_latest_output_image("data/avatars")
            if dest:
                def _done():
                    self.var_avatar_image.set(dest)
                    if self.call_agent and hasattr(self.call_agent, "avatar_manager") and self.call_agent.avatar_manager:
                        self.call_agent.avatar_manager.set_character_image(dest)
                    self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] ✅ 成功从 ComfyUI 导入最新立绘: {os.path.basename(dest)}")
                    messagebox.showinfo("导入成功", f"✅ 已成功导入 ComfyUI 最新生成的立绘！\n路径: {dest}")
                self.app.root.after(0, _done)
            else:
                self.app.root.after(0, lambda: messagebox.showinfo("暂无图片", "ComfyUI 最近无图片生成历史，请在 ComfyUI 中运行一次工作流后再试。"))

        threading.Thread(target=_fetch, daemon=True, name="FetchComfyUI").start()

    def on_install_vcam_click(self):
        """弹出虚拟摄像头驱动安装与选择对话框"""
        win = tk.Toplevel(self.app.root)
        win.title("🛠️ 安装虚拟摄像头驱动")
        win.geometry("560x430")
        win.configure(bg="#0F172A")
        win.resizable(False, False)
        win.transient(self.app.root)
        win.grab_set()

        # 头部标题
        header = tk.Frame(win, bg="#0F172A")
        header.pack(fill="x", padx=24, pady=(20, 12))
        tk.Label(
            header,
            text="🎥 微信虚拟数字人视频驱动安装",
            font=("Microsoft YaHei UI", 13, "bold"),
            bg="#0F172A",
            fg="#F8FAFC"
        ).pack(anchor="w")
        tk.Label(
            header,
            text="微信视频通话需要 DirectShow 虚拟摄像头驱动将数字人实时图像推送至通话窗口。",
            font=("Microsoft YaHei UI", 9),
            bg="#0F172A",
            fg="#94A3B8"
        ).pack(anchor="w", pady=(4, 0))

        # 方案 1: UnityCapture (强烈推荐)
        card1 = tk.Frame(win, bg="#1E293B", bd=1, relief="solid", highlightbackground="#334155", highlightthickness=1)
        card1.pack(fill="x", padx=24, pady=8)

        info1 = tk.Frame(card1, bg="#1E293B")
        info1.pack(side="left", padx=16, pady=12, fill="both", expand=True)
        tk.Label(info1, text="⚡ 方案 1: UnityCapture 独立驱动 (极力推荐)", font=("Microsoft YaHei UI", 10, "bold"), bg="#1E293B", fg="#38BDF8").pack(anchor="w")
        tk.Label(info1, text="• 超轻量级 (仅 150KB)，无需下载安装 300MB 的 OBS 软件\n• 点击后弹出 Windows 管理员授权，1秒内极速注册生效", font=("Microsoft YaHei UI", 8), bg="#1E293B", fg="#CBD5E1", justify="left").pack(anchor="w", pady=(4, 0))

        def _do_install_unity():
            win.destroy()
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 正在请求管理员权限注册 UnityCapture 驱动...")

            def _bg():
                try:
                    from tools.vcam.setup_vcam import install_unitycapture
                    ok, msg = install_unitycapture()

                    def _cb():
                        self._update_vcam_status_ui()
                        self._append_voip_log("info" if ok else "barge", f"[{time.strftime('%H:%M:%S')}] {msg}")
                        if ok:
                            messagebox.showinfo("安装完成", f"✅ {msg}\n\n请在微信客户端【设置 -> 声音与通话 -> 摄像头】中选择「Unity Video Capture」即可！")
                        else:
                            messagebox.showwarning("提示", f"注册结果: {msg}")

                    self.app.root.after(0, _cb)
                except Exception as ex:
                    self.app.root.after(0, lambda: messagebox.showerror("错误", f"安装异常: {ex}"))

            threading.Thread(target=_bg, daemon=True, name="InstallUnityVCam").start()

        btn_u = tk.Button(
            card1,
            text="🚀 一键秒级注册",
            command=_do_install_unity,
            bg="#0284C7",
            fg="#FFFFFF",
            activebackground="#0369A1",
            font=("Microsoft YaHei UI", 9, "bold"),
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=6
        )
        btn_u.pack(side="right", padx=16)

        # 方案 2: WinGet OBS Studio
        card2 = tk.Frame(win, bg="#1E293B", bd=1, relief="solid", highlightbackground="#334155", highlightthickness=1)
        card2.pack(fill="x", padx=24, pady=6)

        info2 = tk.Frame(card2, bg="#1E293B")
        info2.pack(side="left", padx=16, pady=10, fill="both", expand=True)
        tk.Label(info2, text="🎥 方案 2: OBS Studio 官方虚拟摄像头", font=("Microsoft YaHei UI", 10, "bold"), bg="#1E293B", fg="#A78BFA").pack(anchor="w")
        tk.Label(info2, text="• 通过 WinGet 自动安装 OBS (已锁定官方 winget 源，避开商店报错)\n• 安装后需在 OBS 点击一次【启动虚拟摄像机】", font=("Microsoft YaHei UI", 8), bg="#1E293B", fg="#CBD5E1", justify="left").pack(anchor="w", pady=(4, 0))

        def _do_winget():
            from tools.vcam.setup_vcam import install_obs_winget
            install_obs_winget()
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 已打开 WinGet 安装终端...")

        btn_w = tk.Button(
            card2,
            text="📦 WinGet 安装",
            command=_do_winget,
            bg="#7C3AED",
            fg="#FFFFFF",
            activebackground="#6D28D9",
            font=("Microsoft YaHei UI", 9, "bold"),
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=6
        )
        btn_w.pack(side="right", padx=16)

        # 底部操作栏: 浏览器官网下载 / 打开控制台菜单 / 取消
        bottom = tk.Frame(win, bg="#0F172A")
        bottom.pack(fill="x", padx=24, pady=(18, 12))

        def _open_web():
            from tools.vcam.setup_vcam import open_obs_download
            open_obs_download()

        def _open_bat():
            win.destroy()
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            bat = os.path.join(base_dir, "install_vcam.bat")
            if os.path.exists(bat):
                os.system(f'start "" "{bat}"')

        tk.Button(bottom, text="🌐 浏览器前往 OBS 官网", command=_open_web, bg="#334155", fg="#94A3B8", relief="flat", font=("Microsoft YaHei UI", 8), cursor="hand2").pack(side="left")
        tk.Button(bottom, text="💻 打开终端管理菜单", command=_open_bat, bg="#334155", fg="#94A3B8", relief="flat", font=("Microsoft YaHei UI", 8), cursor="hand2", padx=6).pack(side="left", padx=8)
        tk.Button(bottom, text="关闭", command=win.destroy, bg="#1E293B", fg="#E2E8F0", relief="flat", font=("Microsoft YaHei UI", 8), cursor="hand2", padx=12).pack(side="right")

    def on_preview_avatar_click(self):
        """打开实时数字人预览窗口并支持音画同步口型播音测试"""
        if not self.call_agent or not hasattr(self.call_agent, "avatar_manager") or not self.call_agent.avatar_manager:
            messagebox.showwarning("组件未初始化", "数字人总控引擎尚未完成初始化！")
            return

        preview_win = tk.Toplevel(self.app.root)
        preview_win.title("👁️ 实时虚拟数字人画面预览与口型测试 (25 FPS)")
        preview_win.geometry("520x600")
        preview_win.configure(bg="#0F172A")
        preview_win.resizable(False, False)

        canvas = tk.Canvas(preview_win, width=460, height=460, bg="#000000", highlightthickness=0)
        canvas.pack(pady=12)

        ctrl_frame = tk.Frame(preview_win, bg="#0F172A")
        ctrl_frame.pack(fill="x", padx=20, pady=8)

        lbl_fps = tk.Label(ctrl_frame, text="🟢 25 FPS 实时渲染中", bg="#0F172A", fg="#38BDF8", font=("Microsoft YaHei UI", 9))
        lbl_fps.pack(side="left")

        # 线程安全的发音嘴型帧缓冲队列
        preview_frames_queue: queue.Queue = queue.Queue(maxsize=1200)

        def _test_speech():
            txt = "你好！我是微信电话虚拟数字人助手，当前正在测试音画同步口型！"
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 正在准备测试音频并实时驱动数字人嘴唇...")
            btn_speak.config(state="disabled", text="🔊 正在实时驱动口型与发音...")
            lbl_fps.config(text="🗣️ 嘴唇口型实时驱动中...", fg="#00E6A7")

            def _speak():
                try:
                    pcm = None
                    rate = 24000
                    # 优先读取预置/缓存的高保真口型测试音频 (0ms 零延迟极速响应)
                    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    cached_wav = os.path.join(base_dir, "models", "test_avatar_speech.wav")
                    if os.path.exists(cached_wav):
                        try:
                            import soundfile as sf
                            data, sr = sf.read(cached_wav, dtype='int16')
                            pcm = data.tobytes()
                            rate = sr
                        except Exception as e:
                            logger.debug(f"读取缓存测试音频跳过: {e}")

                    if not pcm:
                        # 调用 TTS 引擎生成高保真音频
                        pcm, rate = self.call_agent.tts_manager.synthesize(txt)

                    if pcm:
                        # 2. 将音频切片交由数字人驱动引擎提取能量与音画口型帧
                        frames = self.call_agent.avatar_manager.process_audio_chunk(pcm, sample_rate=rate)

                        # 清空旧队列并存入口型帧序列
                        while not preview_frames_queue.empty():
                            try:
                                preview_frames_queue.get_nowait()
                            except Exception:
                                break

                        # 3. 驱动扬声器真实播放声音 (实现人耳听感与画面嘴型完全同步)
                        try:
                            import sounddevice as sd
                            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                            # 非阻塞启动播放
                            sd.play(samples, samplerate=rate)
                        except Exception as snd_err:
                            logger.debug(f"测试声音播放跳过: {snd_err}")

                        for f in frames:
                            try:
                                preview_frames_queue.put(f, timeout=0.05)
                            except queue.Full:
                                break

                        # 语音结束追加 5 帧自然平滑闭嘴收口帧，杜绝画面定格在张大嘴状态
                        idle_base = self.call_agent.avatar_manager.generate_idle_frame()
                        if frames and len(frames) > 0:
                            last_f = frames[-1]
                            for c_idx in range(1, 6):
                                alpha = (5 - c_idx) / 5.0
                                fade_f = cv2.addWeighted(last_f, alpha, idle_base, 1.0 - alpha, 0.0)
                                try:
                                    preview_frames_queue.put(fade_f, timeout=0.05)
                                except queue.Full:
                                    break

                        # 4. 若真实视频通话推流器正在工作中，亦同步注入
                        if hasattr(self.call_agent, "video_router") and self.call_agent.video_router and self.call_agent.video_router.is_running:
                            self.call_agent.video_router.put_audio(pcm, sample_rate=rate)

                        # 阻塞等待声音播放完毕
                        try:
                            import sounddevice as sd
                            sd.wait()
                        except Exception:
                            pass

                        self.app.root.after(0, lambda: self._append_voip_log("ai", f"[{time.strftime('%H:%M:%S')}] 口型测试演示完成 (生成 {len(frames)} 帧)"))
                except Exception as ex:
                    logger.error(f"口型发音测试异常: {ex}", exc_info=True)
                finally:
                    def _reset():
                        try:
                            if preview_win.winfo_exists():
                                btn_speak.config(state="normal", text="🗣️ 播放测试语句验证口型")
                                lbl_fps.config(text="🟢 25 FPS 实时渲染中", fg="#38BDF8")
                        except Exception:
                            pass
                    self.app.root.after(0, _reset)

            threading.Thread(target=_speak, daemon=True, name="PreviewAvatarSpeech").start()

        btn_speak = tk.Button(
            ctrl_frame,
            text="🗣️ 播放测试语句验证口型",
            command=_test_speech,
            bg="#2563EB",
            fg="#FFFFFF",
            relief="flat",
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=10,
            pady=4,
            cursor="hand2"
        )
        btn_speak.pack(side="right")

        # 实时循环刷新画面 (严格 25 FPS = 40ms，单项画布复用消除内存与卡顿)
        is_preview_running = [True]
        from PIL import Image, ImageTk
        canvas_img_id = [None]
        photo_ref = [None]

        def _update_frame():
            if not is_preview_running[0]:
                return
            try:
                frame_rgb = None
                # 若发音队列有待播放口型帧，优先取出播放；无发音帧时平滑过渡回待机微动
                if not preview_frames_queue.empty():
                    try:
                        frame_rgb = preview_frames_queue.get_nowait()
                    except Exception:
                        pass
                elif getattr(self.call_agent.avatar_manager, "_latest_webcam_driven_frame", None) is not None:
                    frame_rgb = self.call_agent.avatar_manager._latest_webcam_driven_frame

                if frame_rgb is None:
                    frame_rgb = self.call_agent.avatar_manager.generate_idle_frame()

                if frame_rgb is not None:
                    im = Image.fromarray(frame_rgb)
                    im = im.resize((460, 460), Image.Resampling.BILINEAR)
                    photo = ImageTk.PhotoImage(im)
                    photo_ref[0] = photo
                    if canvas_img_id[0] is None:
                        canvas_img_id[0] = canvas.create_image(0, 0, anchor="nw", image=photo)
                    else:
                        canvas.itemconfig(canvas_img_id[0], image=photo)
                    canvas.image = photo
            except Exception:
                pass
            if is_preview_running[0]:
                preview_win.after(40, _update_frame)

        def _on_close():
            is_preview_running[0] = False
            preview_win.destroy()

        preview_win.protocol("WM_DELETE_WINDOW", _on_close)
        preview_win.after(50, _update_frame)

    def on_download_avatar_models_click(self):
        """弹出数字人模型下载管理器"""
        from scripts.download_avatar_models import (
            check_liveportrait_status,
            check_wav2lip_status,
            check_musetalk_status,
            download_liveportrait,
            download_wav2lip,
            download_musetalk,
        )

        win = tk.Toplevel(self.app.root)
        win.title("📥 数字人驱动模型高速下载器")
        win.geometry("580x520")
        win.configure(bg="#0F172A")
        win.resizable(False, False)
        win.transient(self.app.root)
        win.grab_set()

        # 头部
        header = tk.Frame(win, bg="#0F172A")
        header.pack(fill="x", padx=24, pady=(20, 10))
        tk.Label(header, text="🧠 下载离线开源数字人驱动模型", font=("Microsoft YaHei UI", 13, "bold"), bg="#0F172A", fg="#F8FAFC").pack(anchor="w")
        tk.Label(header, text="所有模型文件均直接保存在本项目 models/ 目录下，绝不占用系统 C 盘空间！", font=("Microsoft YaHei UI", 9), bg="#0F172A", fg="#38BDF8").pack(anchor="w", pady=(2, 0))

        # 卡片 1: LivePortrait-Realtime
        card_lp = tk.Frame(win, bg="#1E293B", bd=1, relief="solid", highlightbackground="#334155", highlightthickness=1)
        card_lp.pack(fill="x", padx=24, pady=6)

        info_lp = tk.Frame(card_lp, bg="#1E293B")
        info_lp.pack(side="left", padx=16, pady=10, fill="both", expand=True)
        tk.Label(info_lp, text="⚡ LivePortrait-Realtime (FasterLivePortrait ONNX)", font=("Microsoft YaHei UI", 10, "bold"), bg="#1E293B", fg="#38BDF8").pack(anchor="w")
        tk.Label(info_lp, text="• 显存需求: 1.5GB ~ 2GB | 纯 ONNX GPU 极速推理 (30+ FPS)\n• 规格大小: ~642 MB (全脸表情与头部微动)", font=("Microsoft YaHei UI", 8), bg="#1E293B", fg="#CBD5E1", justify="left").pack(anchor="w", pady=(2, 0))

        lp_ok, lp_found, lp_total = check_liveportrait_status()
        lbl_lp_st = tk.Label(info_lp, text=f"状态: {'✅ 已完整就绪' if lp_ok else f'⚠️ 尚未下载 ({lp_found}/{lp_total} 文件)'}", font=("Microsoft YaHei UI", 8, "bold"), bg="#1E293B", fg="#10B981" if lp_ok else "#F59E0B")
        lbl_lp_st.pack(anchor="w", pady=(3, 0))

        def _do_dl_lp():
            btn_dl_lp.config(state="disabled", text="⏳ 正在下载...")
            def _prog(msg, p):
                lbl_lp_st.config(text=f"进度: {msg} ({int(p*100)}%)", fg="#38BDF8")
            def _worker():
                download_liveportrait(_prog)
                def _done():
                    ok, f, t = check_liveportrait_status()
                    btn_dl_lp.config(state="normal", text="🚀 开始高速下载")
                    lbl_lp_st.config(text=f"状态: {'✅ 已完整就绪' if ok else f'⚠️ 未完成 ({f}/{t})'}", fg="#10B981" if ok else "#F59E0B")
                    if ok:
                        messagebox.showinfo("下载完成", "✅ LivePortrait-Realtime 模型已全部下载并就绪！")
                self.app.root.after(0, _done)
            threading.Thread(target=_worker, daemon=True).start()

        btn_dl_lp = tk.Button(card_lp, text="🚀 开始高速下载", command=_do_dl_lp, bg="#0284C7", fg="#FFFFFF", relief="flat", font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2", padx=10, pady=5)
        btn_dl_lp.pack(side="right", padx=16)

        # 卡片 2: Wav2Lip-Realtime (GAN 高清修复 / OpenTalking 推荐)
        card_w2l = tk.Frame(win, bg="#1E293B", bd=1, relief="solid", highlightbackground="#334155", highlightthickness=1)
        card_w2l.pack(fill="x", padx=24, pady=6)

        info_w2l = tk.Frame(card_w2l, bg="#1E293B")
        info_w2l.pack(side="left", padx=16, pady=10, fill="both", expand=True)
        tk.Label(info_w2l, text="👄 Wav2Lip-Realtime (GAN 音素口型补全 / OpenTalking 推荐)", font=("Microsoft YaHei UI", 10, "bold"), bg="#1E293B", fg="#34D399").pack(anchor="w")
        tk.Label(info_w2l, text="• 显存需求: 1GB ~ 2GB | 纯音频梅尔频谱音素级精准对齐 (30~50 FPS)\n• 规格大小: ~415 MB (单机消费卡推荐，原图高频细节 100% 保持)", font=("Microsoft YaHei UI", 8), bg="#1E293B", fg="#CBD5E1", justify="left").pack(anchor="w", pady=(2, 0))

        w2l_ok, w2l_found, w2l_total = check_wav2lip_status()
        lbl_w2l_st = tk.Label(info_w2l, text=f"状态: {'✅ 已完整就绪' if w2l_ok else '⚠️ 尚未下载 (wav2lip_gan.pth)'}", font=("Microsoft YaHei UI", 8, "bold"), bg="#1E293B", fg="#10B981" if w2l_ok else "#F59E0B")
        lbl_w2l_st.pack(anchor="w", pady=(3, 0))

        def _do_dl_w2l():
            btn_dl_w2l.config(state="disabled", text="⏳ 正在下载...")
            def _prog(msg, p):
                lbl_w2l_st.config(text=f"进度: {msg} ({int(p*100)}%)", fg="#34D399")
            def _worker():
                download_wav2lip(_prog)
                def _done():
                    ok, f, t = check_wav2lip_status()
                    btn_dl_w2l.config(state="normal", text="🚀 开始高速下载")
                    lbl_w2l_st.config(text=f"状态: {'✅ 已完整就绪' if ok else '⚠️ 未完成'}", fg="#10B981" if ok else "#F59E0B")
                    if ok:
                        messagebox.showinfo("下载完成", "✅ Wav2Lip-GAN 权重已全部下载就绪！\n可直接在界面选择 Wav2Lip 引擎驱动数字人。")
                self.app.root.after(0, _done)
            threading.Thread(target=_worker, daemon=True).start()

        btn_dl_w2l = tk.Button(card_w2l, text="🚀 开始高速下载", command=_do_dl_w2l, bg="#059669", fg="#FFFFFF", relief="flat", font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2", padx=10, pady=5)
        btn_dl_w2l.pack(side="right", padx=16)

        # 卡片 3: MuseTalk
        card_mt = tk.Frame(win, bg="#1E293B", bd=1, relief="solid", highlightbackground="#334155", highlightthickness=1)
        card_mt.pack(fill="x", padx=24, pady=6)

        info_mt = tk.Frame(card_mt, bg="#1E293B")
        info_mt.pack(side="left", padx=16, pady=10, fill="both", expand=True)
        tk.Label(info_mt, text="🎭 MuseTalk (Tencent / UNet 唇形在屏修复)", font=("Microsoft YaHei UI", 10, "bold"), bg="#1E293B", fg="#A78BFA").pack(anchor="w")
        tk.Label(info_mt, text="• 显存需求: 4GB ~ 6GB | 基于音频潜变量的重绘修复\n• 规格大小: ~3.2 GB (高精修复模型)", font=("Microsoft YaHei UI", 8), bg="#1E293B", fg="#CBD5E1", justify="left").pack(anchor="w", pady=(2, 0))

        mt_ok, mt_found, mt_total = check_musetalk_status()
        lbl_mt_st = tk.Label(info_mt, text=f"状态: {'✅ 已完整就绪' if mt_ok else f'⚠️ 尚未下载 ({mt_found}/{mt_total} 文件)'}", font=("Microsoft YaHei UI", 8, "bold"), bg="#1E293B", fg="#10B981" if mt_ok else "#F59E0B")
        lbl_mt_st.pack(anchor="w", pady=(3, 0))

        def _do_dl_mt():
            btn_dl_mt.config(state="disabled", text="⏳ 正在下载...")
            def _prog(msg, p):
                lbl_mt_st.config(text=f"进度: {msg} ({int(p*100)}%)", fg="#A78BFA")
            def _worker():
                download_musetalk(_prog)
                def _done():
                    ok, f, t = check_musetalk_status()
                    btn_dl_mt.config(state="normal", text="🚀 开始高速下载")
                    lbl_mt_st.config(text=f"状态: {'✅ 已完整就绪' if ok else f'⚠️ 未完成 ({f}/{t})'}", fg="#10B981" if ok else "#F59E0B")
                    if ok:
                        messagebox.showinfo("下载完成", "✅ MuseTalk 模型已全部下载并就绪！")
                self.app.root.after(0, _done)
            threading.Thread(target=_worker, daemon=True).start()

        btn_dl_mt = tk.Button(card_mt, text="🚀 开始高速下载", command=_do_dl_mt, bg="#7C3AED", fg="#FFFFFF", relief="flat", font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2", padx=10, pady=5)
        btn_dl_mt.pack(side="right", padx=16)

        # 底部
        bottom = tk.Frame(win, bg="#0F172A")
        bottom.pack(fill="x", padx=24, pady=(16, 12))
        tk.Button(bottom, text="关闭窗口", command=win.destroy, bg="#334155", fg="#E2E8F0", relief="flat", font=("Microsoft YaHei UI", 9), cursor="hand2", padx=14).pack(side="right")

    def on_toggle_webcam_driver_click(self):
        """开启或关闭本地物理摄像头动作捕捉驱动数字人"""
        if not self.call_agent or not hasattr(self.call_agent, "avatar_manager") or not self.call_agent.avatar_manager:
            messagebox.showwarning("组件未初始化", "数字人总控引擎尚未完成初始化！")
            return

        av_mgr = self.call_agent.avatar_manager
        is_running = hasattr(av_mgr, "webcam_tracker") and av_mgr.webcam_tracker and av_mgr.webcam_tracker.is_running

        if is_running:
            av_mgr.stop_webcam_driver()
            self.btn_toggle_webcam_driver.config(
                text="📹 开启本地摄像头动作驱动",
                bg="#f0fdf4",
                fg="#166534",
                activebackground="#dcfce7"
            )
            self.lbl_webcam_driver_status.config(
                text="⚪ 未启动 (支持真人坐摄像头前，眨眼/说话/转头实时复刻驱动数字人)",
                fg=self.app.COLOR_MUTED
            )
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 📹 本地摄像头数字人动作驱动已停止")
        else:
            dev_str = self.var_webcam_device.get()
            try:
                dev_idx = int(dev_str.replace("摄像头", "").strip())
            except Exception:
                dev_idx = 0

            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 正在探测并启动本地物理摄像头设备 [{dev_str}]...")
            ok = av_mgr.start_webcam_driver(device_index=dev_idx)
            if ok:
                self.btn_toggle_webcam_driver.config(
                    text="⏹ 停止本地摄像头动作驱动",
                    bg="#fef2f2",
                    fg="#b91c1c",
                    activebackground="#fee2e2"
                )
                self.lbl_webcam_driver_status.config(
                    text="🟢 动作驱动中 (真人眨眼/张嘴/头部转动实时驱动中，可点击上方「👁️ 启动实时测试预览窗口」查看)",
                    fg="#10B981"
                )
                self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] ✅ 本地摄像头动作驱动已启动，已开启 25 FPS 动作重定向！")
            else:
                self.lbl_webcam_driver_status.config(
                    text=f"❌ 无法打开设备 [{dev_str}]，请确认摄像头未被其它软件独占",
                    fg="#EF4444"
                )
                self._append_voip_log("barge", f"[{time.strftime('%H:%M:%S')}] ⚠️ 打开本地摄像头 {dev_idx} 失败，请确认设备连接正常")
                messagebox.showerror("摄像头打开失败", f"无法打开物理摄像头 [{dev_str}]！\n请确认摄像头已插好且未被其他视频软件独占。")

    def on_save_voip_config_click(self):
        """保存电话智能体配置"""
        try:
            cfg = self.config.voip
            cfg.enabled = self.var_voip_enabled.get()
            cfg.sync_reply_targets = self.var_sync_reply.get()
            cfg.enable_group_call = self.var_enable_group.get()
            raw_groups = self.var_whitelist_groups.get()
            cfg.whitelist_groups = [g.strip() for g in raw_groups.split(",") if g.strip()]

            eng_str = self.var_tts_engine.get().lower()
            if "kokoro" in eng_str:
                cfg.tts_engine = "kokoro"
            elif "edge" in eng_str:
                cfg.tts_engine = "edge_tts"
            elif "sapi" in eng_str:
                cfg.tts_engine = "sapi"
            elif "chattts" in eng_str:
                cfg.tts_engine = "chattts"
            else:
                cfg.tts_engine = "qwen3_tts"

            stt_str = self.var_stt_engine.get().lower()
            if "paraformer" in stt_str:
                cfg.stt_engine = "paraformer"
            else:
                cfg.stt_engine = "faster_whisper"

            cfg.voice_clone_enabled = self.var_clone_enabled.get()
            cfg.active_cloned_voice_id = getattr(self, "_current_active_voice_id", "")
            # 若有激活音色，将主融合音频路径同步至 voice_clone_audio_path
            if cfg.active_cloned_voice_id:
                active_p = self.voice_clone_mgr.get_voice(cfg.active_cloned_voice_id)
                if active_p:
                    cfg.voice_clone_audio_path = active_p.audio_path
                    cfg.voice_clone_prompt_text = active_p.prompt_text
            else:
                cfg.voice_clone_audio_path = self.var_clone_path.get().strip()

            cfg.echo_cancellation_enabled = self.var_echo_cancel.get()
            cfg.auto_answer_delay_sec = float(self.var_answer_delay.get())
            cfg.max_call_duration_min = int(self.var_max_duration.get())
            cfg.barge_in_enabled = self.var_barge_in.get()

            cfg.virtual_input_device = self.var_in_dev.get().strip()
            cfg.virtual_output_device = self.var_out_dev.get().strip()

            if hasattr(self, "var_video_enabled"):
                cfg.video_enabled = self.var_video_enabled.get()
                av_val = self.var_avatar_engine.get().lower()
                if "wav2lip" in av_val:
                    cfg.avatar_engine = "wav2lip"
                elif "liveportrait" in av_val:
                    cfg.avatar_engine = "liveportrait"
                else:
                    cfg.avatar_engine = "musetalk"
                cfg.avatar_image_path = self.var_avatar_image.get().strip()

            self.config.save()
            if self.call_agent:
                self.call_agent.reload_config(self.config)

            messagebox.showinfo("成功", "✅ 微信语音电话配置已成功保存并立即生效！")
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 配置已成功持久化至 config.json")
        except Exception as e:
            messagebox.showerror("保存失败", f"配置格式错误: {e}")

    def on_toggle_voip_agent_click(self):
        """开启或停止语音电话守护"""
        if not self.call_agent:
            return

        if self.call_agent._running:
            self.call_agent.stop()
            self.btn_toggle_agent.configure(
                text="▶ 开启电话守护",
                bg=self.app.COLOR_SUCCESS,
                activebackground="#00B380"
            )
            self.lbl_voip_badge.configure(text="⚪ 已停止", bg="#0F2444", fg="#7892B2")
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 语音电话守护已停止")
        else:
            self.call_agent.start()
            self.btn_toggle_agent.configure(
                text="⏸ 停止电话守护",
                bg=self.app.COLOR_DANGER,
                activebackground="#D93D5E"
            )
            self.lbl_voip_badge.configure(text="🟢 待命监听中", bg="#06382B", fg="#00E6A7")
            self._append_voip_log("info", f"[{time.strftime('%H:%M:%S')}] 微信语音电话守护已启动，正在探测来电窗口...")

    def handle_event(self, event: Dict[str, Any]):
        """处理分发给 UI 的电话流水线事件"""
        ev_type = event.get("type")
        data = event.get("data", {})
        now_str = time.strftime("%H:%M:%S")

        if ev_type == "call_incoming":
            caller = data.get("caller", "微信好友")
            is_group = data.get("is_group", False)
            is_video = data.get("is_video", False)
            tag_name = "微信视频" if is_video else ("群聊语音" if is_group else "微信语音")
            self.lbl_voip_badge.configure(text=f"📞 来电振铃中: {caller}", bg="#4A1D96", fg="#C084FC")
            self._append_voip_log("info", f"[{now_str}] 🔔 【检测到{tag_name}来电】 来自 [{caller}]，正在准备执行自动接听...")

        elif ev_type == "call_connected":
            caller = data.get("caller", "")
            is_group = data.get("is_group", False)
            is_video = data.get("is_video", False)
            tag_name = "微信视频" if is_video else ("群聊通话" if is_group else "微信通话")
            self.lbl_voip_badge.configure(text=f"🔵 正在通话: {caller}", bg="#0D2750", fg="#38BDF8")
            self._append_voip_log("info", f"[{now_str}] 📞 【{tag_name}已接通】 开始与 [{caller}] 实时对话")

        elif ev_type == "barge_in":
            msg = data.get("message", "对方插话，打断AI")
            self._append_voip_log("barge", f"[{now_str}] ⚡ 【智能打断】 {msg}")

        elif ev_type == "caller_transcript":
            text = data.get("text", "")
            self._append_voip_log("caller", f"[{now_str}] 👤 对方说: 「{text}」")

        elif ev_type == "ai_sentence":
            sent = data.get("sentence", "")
            self._append_voip_log("ai", f"[{now_str}] 🤖 AI发音: 「{sent}」")

        elif ev_type == "call_ended":
            caller = data.get("caller", "")
            dur = int(data.get("duration", 0))
            self.lbl_voip_badge.configure(text="🟢 待命监听中", bg="#06382B", fg="#00E6A7")
            self._append_voip_log("info", f"[{now_str}] 📴 【通话结束】 好友=[{caller}], 通话时长={dur}秒")
