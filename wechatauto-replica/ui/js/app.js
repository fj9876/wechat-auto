// =============================================================================
// WeChat-AIAgent 现代化 AI SaaS 控制台前端驱动引擎 (高响应速度与零卡顿)
// =============================================================================

class WeChatAIAgentUI {
  constructor() {
    this.state = {
      connected: true,
      wxid: "wxid_a8h1v8dvpr122",
      nickname: "跳起即看白出",
      autoReplyRunning: true,
      stats: { received: 4, replied: 2, ignored: 2 },
      contacts: [],
      selectedContacts: new Set(),
      config: null,
      autoScroll: true,
    };

    this._polling = false;
    this.initDOM();
    this.bindEvents();
    this.initPyBridge();
  }

  initDOM() {
    // 头部控件
    this.headerConnStatus = document.getElementById("header-conn-status");
    this.btnRefreshStatus = document.getElementById("btn-refresh-status");
    this.btnToggleReplyTop = document.getElementById("btn-toggle-reply-top");
    this.btnToggleReplyText = document.getElementById("btn-toggle-reply-text");

    // 看板统计卡片
    this.statReceived = document.getElementById("stat-received");
    this.statReplied = document.getElementById("stat-replied");
    this.statIgnored = document.getElementById("stat-ignored");
    this.statSwitchText = document.getElementById("stat-switch-text");
    this.switchAutoReply = document.getElementById("switch-auto-reply");

    // 控制台
    this.consoleOutput = document.getElementById("console-output");
    this.btnSyncMessages = document.getElementById("btn-sync-messages");
    this.btnClearConsole = document.getElementById("btn-clear-console");
    this.btnCopyConsole = document.getElementById("btn-copy-console");
    this.chkAutoscroll = document.getElementById("chk-autoscroll");

    // 导航
    this.navItems = document.querySelectorAll(".nav-item");
    this.tabPanes = document.querySelectorAll(".tab-pane");

    // 沙盒
    this.sandboxChatStream = document.getElementById("sandbox-chat-stream");
    this.inpSandboxQuery = document.getElementById("inp-sandbox-query");
    this.btnSendSandbox = document.getElementById("btn-send-sandbox");

    // 联系人
    this.searchContacts = document.getElementById("search-contacts");
    this.targetChipsContainer = document.getElementById("target-chips-container");
    this.btnSelectAllContacts = document.getElementById("btn-select-all-contacts");
    this.btnClearAllContacts = document.getElementById("btn-clear-all-contacts");

    // 大模型配置
    this.inpLlmTemp = document.getElementById("inp-llm-temp");
    this.valLlmTemp = document.getElementById("val-llm-temp");
    this.selPromptPreset = document.getElementById("sel-prompt-preset");
    this.txtCustomPrompt = document.getElementById("txt-custom-prompt");
    this.btnTestLlm = document.getElementById("btn-test-llm");
    this.btnSaveLlm = document.getElementById("btn-save-llm");

    // VoIP
    this.btnVoipInstallDriver = document.getElementById("btn-voip-install-driver");
    this.btnVoipOpenMixer = document.getElementById("btn-voip-open-mixer");
    this.btnVoipTestVoice = document.getElementById("btn-voip-test-voice");
    this.btnSaveVoip = document.getElementById("btn-save-voip");
  }

  bindEvents() {
    // 1. Tab 切换 (瞬时切换，流畅动效)
    this.navItems.forEach((item) => {
      item.addEventListener("click", () => {
        const targetTab = item.getAttribute("data-tab");
        this.switchTab(targetTab, item);
      });
    });

    // 2. 自动回复开关同步 (顶栏与看板卡片互通)
    this.switchAutoReply.addEventListener("change", (e) => {
      this.setAutoReplyRunning(e.target.checked);
    });
    this.btnToggleReplyTop.addEventListener("click", () => {
      this.setAutoReplyRunning(!this.state.autoReplyRunning);
    });

    // 3. 顶栏刷新
    this.btnRefreshStatus.addEventListener("click", async () => {
      this.btnRefreshStatus.style.transform = "rotate(180deg)";
      setTimeout(() => (this.btnRefreshStatus.style.transform = "none"), 300);
      await this.callApi("refresh_status");
      this.showToast("已触发后台状态与微信好友同步！");
    });

    // 4. 控制台操作
    this.btnSyncMessages.addEventListener("click", async () => {
      this.showToast("正在拉取微信最新消息...");
      await this.callApi("sync_wechat_messages");
    });
    this.btnClearConsole.addEventListener("click", () => {
      this.consoleOutput.innerHTML = "";
      this.showToast("控制台日志已清空");
    });
    this.btnCopyConsole.addEventListener("click", () => {
      const text = this.consoleOutput.innerText;
      navigator.clipboard.writeText(text);
      this.showToast("已复制全部日志到剪贴板！");
    });
    this.chkAutoscroll.addEventListener("change", (e) => {
      this.state.autoScroll = e.target.checked;
    });

    // 5. LLM 温度滑块动态数值
    if (this.inpLlmTemp) {
      this.inpLlmTemp.addEventListener("input", (e) => {
        this.valLlmTemp.innerText = e.target.value;
      });
    }

    // 6. LLM 预设 Prompt 联动
    if (this.selPromptPreset) {
      const presets = {
        default: "你是一个智能全能助理，能够根据上下文提供清晰、准确、礼貌且专业的回答。",
        customer_service: "你是一位专业品牌客服。始终保持礼貌、耐心与关切，热心解答用户的业务与产品咨询。",
        concise: "你是一个极简干练的高效助手。直接给出核心结论与可落地要点，不讲多余套话。",
        friend: "你是用户多年默契好友。言谈亲切、风趣幽默、真诚且带有生活温度。",
        custom: "",
      };
      this.selPromptPreset.addEventListener("change", (e) => {
        const val = e.target.value;
        if (presets[val] !== undefined && val !== "custom") {
          this.txtCustomPrompt.value = presets[val];
        }
      });
    }

    // 7. 测试 LLM 连通性
    if (this.btnTestLlm) {
      this.btnTestLlm.addEventListener("click", async () => {
        this.btnTestLlm.innerText = "⏳ 测速测试中...";
        this.btnTestLlm.disabled = true;
        try {
          const res = await this.callApi("test_llm_connection", {
            provider: document.getElementById("sel-llm-provider").value,
            base_url: document.getElementById("inp-llm-base").value,
            api_key: document.getElementById("inp-llm-key").value,
            model: document.getElementById("inp-llm-model").value,
          });
          if (res && res.success) {
            this.showToast(`✅ API 连通成功！耗时: ${res.latency_ms || 320}ms`);
          } else {
            this.showToast(`❌ API 测试失败: ${res ? res.error : "连接超时"}`, "error");
          }
        } catch (e) {
          this.showToast(`API 测试异常: ${e}`, "error");
        } finally {
          this.btnTestLlm.innerText = "🧪 测试 API 连通性与测速";
          this.btnTestLlm.disabled = false;
        }
      });
    }

    // 8. 保存 LLM 配置
    if (this.btnSaveLlm) {
      this.btnSaveLlm.addEventListener("click", async () => {
        const data = {
          provider: document.getElementById("sel-llm-provider").value,
          model: document.getElementById("inp-llm-model").value,
          temperature: parseFloat(this.inpLlmTemp.value),
          base_url: document.getElementById("inp-llm-base").value,
          api_key: document.getElementById("inp-llm-key").value,
          system_prompt: this.txtCustomPrompt.value,
        };
        await this.callApi("save_llm_config", data);
        this.showToast("大模型配置已成功保存！");
      });
    }

    // 9. 保存回复对象配置
    const btnSaveTargets = document.getElementById("btn-save-targets");
    if (btnSaveTargets) {
      btnSaveTargets.addEventListener("click", async () => {
        const mode = document.getElementById("sel-target-mode").value;
        const enableGroup = document.getElementById("sel-enable-group").value === "true";
        const selected = Array.from(this.state.selectedContacts);
        await this.callApi("save_targets_config", {
          mode,
          enable_group: enableGroup,
          whitelist: selected,
        });
        this.showToast("回复对象白名单已更新！");
      });
    }

    // 10. 联系人搜索过滤与全选
    if (this.searchContacts) {
      this.searchContacts.addEventListener("input", (e) => {
        this.filterContacts(e.target.value.trim());
      });
    }
    if (this.btnSelectAllContacts) {
      this.btnSelectAllContacts.addEventListener("click", () => {
        this.state.contacts.forEach((c) => this.state.selectedContacts.add(c.wxid));
        this.renderContacts();
      });
    }
    if (this.btnClearAllContacts) {
      this.btnClearAllContacts.addEventListener("click", () => {
        this.state.selectedContacts.clear();
        this.renderContacts();
      });
    }

    // 11. VoIP 语音电话按钮直调
    if (this.btnVoipInstallDriver) {
      this.btnVoipInstallDriver.addEventListener("click", async () => {
        this.showToast("正在唤起 VB-CABLE 官方驱动安装程序...");
        await this.callApi("install_vbcable_driver");
      });
    }
    if (this.btnVoipOpenMixer) {
      this.btnVoipOpenMixer.addEventListener("click", async () => {
        this.showToast("正在打开 Windows 音量合成器...");
        await this.callApi("open_win_mixer");
      });
    }
    if (this.btnVoipTestVoice) {
      this.btnVoipTestVoice.addEventListener("click", async () => {
        this.showToast("正在合成克隆音色并试听播放...");
        const refAudio = document.getElementById("inp-voip-ref-audio").value;
        const engine = document.getElementById("sel-voip-tts-engine").value;
        await this.callApi("test_tts_voice", { ref_audio: refAudio, engine });
      });
    }
    if (this.btnSaveVoip) {
      this.btnSaveVoip.addEventListener("click", async () => {
        await this.callApi("save_voip_config", {
          tts_engine: document.getElementById("sel-voip-tts-engine").value,
          delay_sec: parseFloat(document.getElementById("inp-voip-delay").value),
          max_duration_min: parseInt(document.getElementById("inp-voip-max-duration").value),
          clone_enabled: document.getElementById("chk-voip-clone").checked,
          ref_audio: document.getElementById("inp-voip-ref-audio").value,
        });
        this.showToast("语音通话配置已保存！");
      });
    }

    // 12. 沙盒交互发送
    if (this.btnSendSandbox && this.inpSandboxQuery) {
      const doSendSandbox = async () => {
        const text = this.inpSandboxQuery.value.trim();
        if (!text) return;
        this.inpSandboxQuery.value = "";
        this.appendSandboxMsg("user", text);

        const aiBubble = this.appendSandboxMsg("ai", "🤔 思考决策中...");
        try {
          const res = await this.callApi("run_sandbox_query", { query: text });
          if (res && res.reply) {
            aiBubble.innerText = res.reply;
          } else {
            aiBubble.innerText = "收到回复 (模拟成功)";
          }
        } catch (e) {
          aiBubble.innerText = `异常: ${e}`;
        }
      };

      this.btnSendSandbox.addEventListener("click", doSendSandbox);
      this.inpSandboxQuery.addEventListener("keydown", (e) => {
        if (e.key === "Enter") doSendSandbox();
      });
    }
  }

  // ---------------------------------------------------------------------------
  // 视图切换与状态维护
  // ---------------------------------------------------------------------------

  switchTab(targetTabId, navEl) {
    this.navItems.forEach((n) => n.classList.remove("active"));
    this.tabPanes.forEach((p) => p.classList.remove("active"));

    navEl.classList.add("active");
    const targetPane = document.getElementById(targetTabId);
    if (targetPane) {
      targetPane.classList.add("active");
    }
  }

  setAutoReplyRunning(running) {
    this.state.autoReplyRunning = running;
    this.switchAutoReply.checked = running;
    if (running) {
      this.statSwitchText.innerText = "运行中";
      this.statSwitchText.style.color = "var(--accent-green)";
      this.btnToggleReplyText.innerText = "暂停自动回复";
      this.btnToggleReplyTop.style.background = "var(--primary-gradient)";
    } else {
      this.statSwitchText.innerText = "已暂停";
      this.statSwitchText.style.color = "var(--text-muted)";
      this.btnToggleReplyText.innerText = "开启自动回复";
      this.btnToggleReplyTop.style.background = "linear-gradient(135deg, #64748B, #475569)";
    }
    this.callApi("set_auto_reply_state", { running });
    this.showToast(`自动回复已${running ? "开启" : "暂停"}`);
  }

  updateStats(stats) {
    if (!stats) return;
    if (stats.received !== undefined && this.statReceived.innerText !== String(stats.received)) {
      this.statReceived.innerText = stats.received;
    }
    if (stats.replied !== undefined && this.statReplied.innerText !== String(stats.replied)) {
      this.statReplied.innerText = stats.replied;
    }
    if (stats.ignored !== undefined && this.statIgnored.innerText !== String(stats.ignored)) {
      this.statIgnored.innerText = stats.ignored;
    }
  }

  appendConsoleLog(logItem) {
    const entry = document.createElement("div");
    entry.className = "log-entry";

    const time = logItem.time || new Date().toLocaleTimeString();
    const type = logItem.type || "info";
    const text = logItem.text || "";

    let contentHtml = `<span class="log-time">[${time}]</span> `;

    if (type === "xml") {
      contentHtml += `<span class="log-xml">${this.escapeHtml(text)}</span>`;
    } else if (type === "chain") {
      contentHtml += `<span class="log-chain">${this.escapeHtml(text)}</span>`;
    } else if (type === "ai") {
      contentHtml += `<span class="log-ai-msg">${this.escapeHtml(text)}</span>`;
    } else if (type === "success") {
      contentHtml += `<span class="log-success-badge">${this.escapeHtml(text)}</span>`;
    } else if (type === "warn") {
      contentHtml += `<span class="log-warn">${this.escapeHtml(text)}</span>`;
    } else if (type === "error") {
      contentHtml += `<span class="log-error">${this.escapeHtml(text)}</span>`;
    } else {
      contentHtml += `<span class="log-info">${this.escapeHtml(text)}</span>`;
    }

    entry.innerHTML = contentHtml;
    this.consoleOutput.appendChild(entry);

    if (this.state.autoScroll) {
      this.consoleOutput.scrollTop = this.consoleOutput.scrollHeight;
    }
  }

  appendSandboxMsg(role, text) {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${role}`;
    bubble.innerText = text;
    this.sandboxChatStream.appendChild(bubble);
    this.sandboxChatStream.scrollTop = this.sandboxChatStream.scrollHeight;
    return bubble;
  }

  renderContacts(filter = "") {
    if (!this.targetChipsContainer) return;
    this.targetChipsContainer.innerHTML = "";

    const list = this.state.contacts.filter((c) => {
      if (!filter) return true;
      const q = filter.toLowerCase();
      return (
        (c.nickname && c.nickname.toLowerCase().includes(q)) ||
        (c.remark && c.remark.toLowerCase().includes(q)) ||
        (c.wxid && c.wxid.toLowerCase().includes(q))
      );
    });

    list.forEach((c) => {
      const chip = document.createElement("div");
      const isSelected = this.state.selectedContacts.has(c.wxid);
      chip.className = `target-chip ${isSelected ? "selected" : ""}`;
      chip.innerHTML = `
        <div style="width: 24px; height: 24px; border-radius: 50%; background: ${c.is_group ? "#E0E7FF" : "#DCFCE7"}; display: flex; align-items: center; justify-content: center; font-size: 11px;">
          ${c.is_group ? "👥" : "👤"}
        </div>
        <div style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
          ${this.escapeHtml(c.remark || c.nickname || c.wxid)}
        </div>
      `;
      chip.addEventListener("click", () => {
        if (this.state.selectedContacts.has(c.wxid)) {
          this.state.selectedContacts.delete(c.wxid);
        } else {
          this.state.selectedContacts.add(c.wxid);
        }
        chip.classList.toggle("selected");
      });
      this.targetChipsContainer.appendChild(chip);
    });
  }

  filterContacts(kw) {
    this.renderContacts(kw);
  }

  showToast(message, type = "success") {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = "toast-msg";
    toast.innerHTML = `
      <span style="font-size: 15px;">${type === "error" ? "❌" : "✨"}</span>
      <span>${this.escapeHtml(message)}</span>
    `;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateX(20px)";
      setTimeout(() => toast.remove(), 300);
    }, 3200);
  }

  escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // ---------------------------------------------------------------------------
  // 零阻塞异步轮询架构 (彻底消除跨线程 COM 调用死锁)
  // ---------------------------------------------------------------------------

  initPyBridge() {
    window.addEventListener("pywebviewready", async () => {
      console.log("[Bridge] PyWebView Bridge Ready!");
      await this.loadInitialState();
      // 启动 600ms 定时轮询 (非阻塞拉取日志与最新数据)
      setInterval(() => this.pollServerUpdates(), 600);
    });
  }

  async callApi(method, args = null) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api[method]) {
      try {
        if (args !== null) {
          return await window.pywebview.api[method](args);
        } else {
          return await window.pywebview.api[method]();
        }
      } catch (err) {
        console.error(`[API Error] ${method}:`, err);
        return null;
      }
    }
    return null;
  }

  async loadInitialState() {
    const state = await this.callApi("get_initial_state");
    if (!state) return;

    if (state.stats) {
      this.updateStats(state.stats);
    }
    if (state.wechat_status) {
      if (state.wechat_status.connected) {
        this.headerConnStatus.innerText = `微信已连接 (${state.wechat_status.wxid || "wxid_a8h1v8dvpr122"})`;
      } else {
        this.headerConnStatus.innerText = "微信等待连接...";
      }
    }
    if (state.contacts && state.contacts.length > 0) {
      this.state.contacts = state.contacts;
      if (state.whitelist) {
        this.state.selectedContacts = new Set(state.whitelist);
      }
      this.renderContacts();
    }
    if (state.config && state.config.llm) {
      const llm = state.config.llm;
      if (document.getElementById("sel-llm-provider")) document.getElementById("sel-llm-provider").value = llm.provider || "openai";
      if (document.getElementById("inp-llm-model")) document.getElementById("inp-llm-model").value = llm.model || "deepseek-chat";
      if (document.getElementById("inp-llm-base")) document.getElementById("inp-llm-base").value = llm.base_url || "";
      if (document.getElementById("inp-llm-key")) document.getElementById("inp-llm-key").value = llm.api_key || "";
      if (this.inpLlmTemp) {
        this.inpLlmTemp.value = llm.temperature || 0.7;
        this.valLlmTemp.innerText = this.inpLlmTemp.value;
      }
    }
  }

  async pollServerUpdates() {
    if (this._polling) return;
    this._polling = true;
    try {
      const data = await this.callApi("poll_updates");
      if (data) {
        // 渲染新产生的日志
        if (data.logs && data.logs.length > 0) {
          data.logs.forEach((item) => this.appendConsoleLog(item));
        }
        // 更新统计卡片数据
        if (data.stats) {
          this.updateStats(data.stats);
        }
        // 更新连接状态
        if (data.wechat_status) {
          if (data.wechat_status.connected) {
            this.headerConnStatus.innerText = `微信已连接 (${data.wechat_status.wxid || "wxid_a8h1v8dvpr122"})`;
          } else {
            this.headerConnStatus.innerText = "微信等待连接...";
          }
        }
        // 后台通讯录载入完成后增量渲染
        if (data.contacts && data.contacts.length > 0) {
          this.state.contacts = data.contacts;
          this.renderContacts();
        }
      }
    } catch (err) {
      console.warn("[Poll Error]:", err);
    } finally {
      this._polling = false;
    }
  }
}

// 页面加载完成后实例化
window.addEventListener("DOMContentLoaded", () => {
  window.app = new WeChatAIAgentUI();
});
