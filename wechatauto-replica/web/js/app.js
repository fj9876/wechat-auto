// ==========================================================================
// WeChat-AIAgent 客户端核心交互脚本 (app.js)
// ==========================================================================

document.addEventListener("DOMContentLoaded", () => {
  // 全局状态
  let currentConfig = null;
  let promptPresets = {};
  let allContacts = [];
  let allGroups = [];
  let botIsRunning = false;
  let socket = null;

  // ------------------------------------------------------------------------
  // 1. 选项卡切换
  // ------------------------------------------------------------------------
  const navTabs = document.querySelectorAll(".nav-tab");
  const tabPanes = document.querySelectorAll(".content-tab-pane");

  navTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const targetId = tab.getAttribute("data-tab");
      navTabs.forEach(t => t.classList.remove("active"));
      tabPanes.forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add("active");
    });
  });

  // ------------------------------------------------------------------------
  // 2. Toast 提示工具
  // ------------------------------------------------------------------------
  function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateX(50px)";
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  // ------------------------------------------------------------------------
  // 3. WebSocket 实时日志通道
  // ------------------------------------------------------------------------
  function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/logs`;
    
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      appendLog("info", "WebSocket 实时日志通道连接成功");
    };

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleSocketEvent(msg);
      } catch (e) {
        // 心跳回应
      }
    };

    socket.onclose = () => {
      appendLog("warning", "WebSocket 连接中断，3秒后尝试重连...");
      setTimeout(initWebSocket, 3000);
    };
  }

  function handleSocketEvent(payload) {
    const type = payload.type;
    const timeStr = payload.time_str || new Date().toLocaleTimeString();
    const data = payload.data || {};

    if (type === "log") {
      appendLog(data.level || "info", `[${timeStr}] ${data.message}`);
    } else if (type === "message_received") {
      const src = data.display_title || (data.is_group ? `[群聊: ${data.group_name || data.username}]` : `[好友: ${data.sender_name}]`);
      appendLog("info", `📩 【收到微信消息】 ${src}: ${data.content}`);
      highlightPipelineStep(1);
    } else if (type === "message_ignored") {
      appendLog("warning", `⚠️ [规则过滤] (${data.reason}): ${data.content}`);
    } else if (type === "pipeline_finished") {
      appendLog("success", `⚡ 智能体决策完成 (${data.duration_ms}ms) -> 生成回复: ${data.reply_text.substring(0, 50)}...`);
      updatePipelineVisual(data);
    } else if (type === "message_sent") {
      appendLog("success", `🚀 成功发送微信回复至 [${data.target}]: ${data.text.substring(0, 40)}...`);
      highlightPipelineStep(5);
    }
  }

  function appendLog(level, text) {
    const terminal = document.getElementById("logTerminal");
    if (!terminal) return;

    const row = document.createElement("div");
    row.className = `log-row ${level}`;
    
    const timeSpan = document.createElement("span");
    timeSpan.className = "log-time";
    timeSpan.textContent = new Date().toLocaleTimeString();

    const textSpan = document.createElement("span");
    textSpan.className = "log-text";
    textSpan.textContent = text;

    row.appendChild(timeSpan);
    row.appendChild(textSpan);
    terminal.appendChild(row);

    terminal.scrollTop = terminal.scrollHeight;
  }

  document.getElementById("clearLogsBtn").addEventListener("click", () => {
    const terminal = document.getElementById("logTerminal");
    if (terminal) terminal.innerHTML = "";
    showToast("已清空控制台日志", "info");
  });

  // ------------------------------------------------------------------------
  // 4. 流水线动画与详情更新
  // ------------------------------------------------------------------------
  function highlightPipelineStep(stepIndex) {
    for (let i = 1; i <= 5; i++) {
      const node = document.getElementById(`stepNode${i}`);
      if (node) {
        if (i <= stepIndex) {
          node.classList.add("active");
        } else {
          node.classList.remove("active");
        }
      }
    }
  }

  function updatePipelineVisual(data) {
    highlightPipelineStep(5);
    const box = document.getElementById("lastPipelineDetail");
    if (!box) return;

    let stepsHtml = "";
    if (data.steps && data.steps.length > 0) {
      stepsHtml = data.steps.map(s => `
        <div style="margin-bottom: 6px;">
          <span style="color: ${s.status === 'success' ? '#34d399' : s.status === 'failed' ? '#f87171' : '#94a3b8'}; font-weight:600;">
            [${s.name}] (${s.status}):
          </span>
          <span style="color: #cbd5e1;">${s.details}</span>
        </div>
      `).join("");
    }

    box.innerHTML = `
      <div style="display: flex; justify-content: space-between; margin-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 6px;">
        <strong>会话: ${data.sender_name} (${data.chat_id})</strong>
        <span style="color: #06b6d4;">全链路耗时: ${data.duration_ms} ms</span>
      </div>
      <div style="font-size: 12px; margin-bottom: 8px;">${stepsHtml}</div>
      <div style="background: rgba(0,0,0,0.3); padding: 10px; border-radius: 6px; color: #38bdf8;">
        <strong>最终生成回复:</strong><br>${data.reply_text.replace(/\n/g, '<br>')}
      </div>
    `;
  }

  // ------------------------------------------------------------------------
  // 5. 初始化与系统状态拉取
  // ------------------------------------------------------------------------
  async function fetchSystemStatus() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      
      // 更新微信状态指示
      const dot = document.getElementById("wechatDot");
      const accountText = document.getElementById("wechatAccountText");
      if (data.wechat && data.wechat.wechat_detected) {
        dot.className = "status-dot dot-online";
        accountText.textContent = `微信在线: ${data.wechat.self_name}`;
      } else {
        dot.className = "status-dot dot-offline";
        accountText.textContent = "微信未登录/未检测到";
      }

      // 机器人自动回复状态
      botIsRunning = Boolean(data.wechat && data.wechat.auto_reply_enabled);
      updateBotButtonUI(botIsRunning);

      // 看板小卡片数据
      document.getElementById("dashModelName").textContent = data.model_name || "--";
      document.getElementById("dashPresetName").textContent = data.preset_name || "--";
      const totalTargets = (data.targets_count?.users || 0) + (data.targets_count?.groups || 0);
      document.getElementById("dashTargetsCount").textContent = `${totalTargets} 个对象 (群@: ${data.targets_count?.group_at_only ? '开' : '关'})`;
      
      const ragStatus = data.rag;
      if (ragStatus && ragStatus.enabled) {
        document.getElementById("dashRAGStatus").textContent = `已启用 (${ragStatus.doc_count} 篇文档)`;
        document.getElementById("ragStatusChip").textContent = `已启用 (${ragStatus.doc_count})`;
        document.getElementById("ragStatusChip").style.background = "rgba(16, 185, 129, 0.2)";
        document.getElementById("ragStatusChip").style.color = "#10b981";
      } else {
        document.getElementById("dashRAGStatus").textContent = "未启用 (纯大模型模式)";
        document.getElementById("ragStatusChip").textContent = "可选未开启";
        document.getElementById("ragStatusChip").style.background = "rgba(255, 255, 255, 0.08)";
        document.getElementById("ragStatusChip").style.color = "#94a3b8";
      }
    } catch (e) {
      console.error("拉取状态失败", e);
    }
  }

  function updateBotButtonUI(running) {
    const btn = document.getElementById("toggleBotBtn");
    const text = document.getElementById("toggleBotText");
    const label = document.getElementById("botStatusLabel");
    if (running) {
      btn.className = "btn btn-outline";
      btn.style.borderColor = "#ef4444";
      btn.style.color = "#ef4444";
      text.textContent = "停止自动回复";
      label.textContent = "● 自动回复运行中";
      label.style.color = "#10b981";
    } else {
      btn.className = "btn btn-primary pulse-btn";
      btn.style.borderColor = "";
      btn.style.color = "";
      text.textContent = "开启自动回复";
      label.textContent = "自动回复已暂停";
      label.style.color = "#94a3b8";
    }
  }

  document.getElementById("toggleBotBtn").addEventListener("click", async () => {
    try {
      const endpoint = botIsRunning ? "/api/wechat/stop" : "/api/wechat/start";
      const res = await fetch(endpoint, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        showToast(data.message, "success");
        botIsRunning = !botIsRunning;
        updateBotButtonUI(botIsRunning);
      } else {
        showToast(data.message, "error");
      }
    } catch (e) {
      showToast(`操作失败: ${e.message}`, "error");
    }
  });

  // ------------------------------------------------------------------------
  // 6. 加载与保存配置
  // ------------------------------------------------------------------------
  async function loadConfig() {
    try {
      const res = await fetch("/api/config");
      const data = await res.json();
      currentConfig = data.config;
      promptPresets = data.prompt_presets || {};

      // 填充预设选择器
      const presetSelect = document.getElementById("presetSelect");
      presetSelect.innerHTML = "";
      for (const [name, text] of Object.entries(promptPresets)) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        if (name === currentConfig.safety.preset_name) {
          opt.selected = true;
        }
        presetSelect.appendChild(opt);
      }

      // 填充大模型配置
      document.getElementById("apiUrlInput").value = currentConfig.llm.api_url || "";
      document.getElementById("apiKeyInput").value = currentConfig.llm.api_key || "";
      document.getElementById("modelNameInput").value = currentConfig.llm.model_name || "deepseek-chat";
      document.getElementById("systemPromptInput").value = currentConfig.safety.system_prompt || "";
      document.getElementById("tempRange").value = currentConfig.llm.temperature || 0.7;
      document.getElementById("tempVal").textContent = currentConfig.llm.temperature || 0.7;
      document.getElementById("maxTokensInput").value = currentConfig.llm.max_tokens || 1500;
      document.getElementById("cooldownInput").value = currentConfig.safety.cooldown_seconds || 1.0;
      document.getElementById("prefixInput").value = currentConfig.safety.reply_prefix || "";
      document.getElementById("suffixInput").value = currentConfig.safety.reply_suffix || "";
      document.getElementById("handoverInput").value = currentConfig.safety.handover_keyword || "转人工";

      // 填充群聊与对象规则
      document.getElementById("groupAtOnlyCheckbox").checked = currentConfig.targets.group_at_only;
      document.getElementById("groupAutoAtSenderCheckbox").checked = currentConfig.targets.group_auto_at_sender;
      document.getElementById("replyAllPrivateCheckbox").checked = currentConfig.targets.reply_all_private;
      document.getElementById("replyAllGroupsCheckbox").checked = currentConfig.targets.reply_all_groups;

      // 填充 RAG 配置
      const ragEnabled = currentConfig.rag.enabled;
      document.getElementById("ragEnabledCheckbox").checked = ragEnabled;
      document.getElementById("kbFolderInput").value = currentConfig.rag.kb_folder_path || "";
      updateRAGUIState(ragEnabled);

      // 加载联系人列表
      await loadContacts();

    } catch (e) {
      showToast(`加载配置失败: ${e.message}`, "error");
    }
  }

  // 预设选择器事件
  document.getElementById("presetSelect").addEventListener("change", (e) => {
    const name = e.target.value;
    if (promptPresets[name]) {
      document.getElementById("systemPromptInput").value = promptPresets[name];
      showToast(`已切换助手预设为「${name}」`, "info");
    }
  });

  // 温度滑块事件
  document.getElementById("tempRange").addEventListener("input", (e) => {
    document.getElementById("tempVal").textContent = e.target.value;
  });

  // 模型快捷选择下拉
  document.getElementById("modelPresetSelect").addEventListener("change", (e) => {
    if (e.target.value) {
      document.getElementById("modelNameInput").value = e.target.value;
    }
  });

  // 一键获取上游大模型列表
  const fetchModelsBtn = document.getElementById("fetchModelsBtn");
  if (fetchModelsBtn) {
    fetchModelsBtn.addEventListener("click", async () => {
      const apiUrl = document.getElementById("apiUrlInput").value.trim();
      const apiKey = document.getElementById("apiKeyInput").value.trim();
      if (!apiUrl) {
        showToast("请先填写大模型 API Base URL", "warning");
        return;
      }
      fetchModelsBtn.disabled = true;
      fetchModelsBtn.textContent = "⏳ 正在获取...";
      try {
        const res = await fetch("/api/llm/models", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ api_url: apiUrl, api_key: apiKey }),
        });
        const data = await res.json();
        if (data.success && data.models && data.models.length > 0) {
          const select = document.getElementById("modelPresetSelect");
          select.innerHTML = '<option value="">-- 选择上游模型 --</option>';
          data.models.forEach(m => {
            const opt = document.createElement("option");
            opt.value = m;
            opt.textContent = m;
            select.appendChild(opt);
          });
          document.getElementById("modelNameInput").value = data.models[0];
          showToast(data.message, "success");
        } else {
          showToast(data.message || "未能获取到模型列表，请手动输入", "warning");
        }
      } catch (e) {
        showToast(`获取模型异常: ${e.message}`, "error");
      } finally {
        fetchModelsBtn.disabled = false;
        fetchModelsBtn.textContent = "🔍 获取模型列表";
      }
    });
  }

  // 密码显示切换
  document.getElementById("toggleApiKeyEye").addEventListener("click", () => {
    const input = document.getElementById("apiKeyInput");
    input.type = input.type === "password" ? "text" : "password";
  });

  // 保存大模型配置
  document.getElementById("saveLLMBtn").addEventListener("click", async () => {
    if (!currentConfig) return;
    currentConfig.llm.api_url = document.getElementById("apiUrlInput").value.trim();
    currentConfig.llm.api_key = document.getElementById("apiKeyInput").value.trim();
    currentConfig.llm.model_name = document.getElementById("modelNameInput").value.trim();
    currentConfig.llm.temperature = parseFloat(document.getElementById("tempRange").value);
    currentConfig.llm.max_tokens = parseInt(document.getElementById("maxTokensInput").value, 10);
    
    currentConfig.safety.preset_name = document.getElementById("presetSelect").value;
    currentConfig.safety.system_prompt = document.getElementById("systemPromptInput").value;
    currentConfig.safety.cooldown_seconds = parseFloat(document.getElementById("cooldownInput").value);
    currentConfig.safety.reply_prefix = document.getElementById("prefixInput").value;
    currentConfig.safety.reply_suffix = document.getElementById("suffixInput").value;
    currentConfig.safety.handover_keyword = document.getElementById("handoverInput").value.trim();

    await saveConfigToServer("大模型及安全配置已保存！");
  });

  // 测试大模型连通性
  document.getElementById("testLLMBtn").addEventListener("click", async () => {
    const btn = document.getElementById("testLLMBtn");
    const resultBox = document.getElementById("llmTestResultBox");
    const banner = document.getElementById("testResultBanner");

    const apiUrl = document.getElementById("apiUrlInput").value.trim();
    const apiKey = document.getElementById("apiKeyInput").value.trim();
    const modelName = document.getElementById("modelNameInput").value.trim();

    btn.disabled = true;
    btn.textContent = "⏳ 正在测试连接...";
    resultBox.style.display = "block";
    banner.className = "test-result-banner";
    banner.textContent = "正在向大模型接口发送心跳握手请求，请稍候...";

    try {
      const res = await fetch("/api/llm/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_url: apiUrl, api_key: apiKey, model_name: modelName }),
      });
      const data = await res.json();
      if (data.success) {
        banner.className = "test-result-banner success";
        banner.innerHTML = `✅ <strong>连接成功！</strong> (${data.latency_ms} ms)<br>${data.message}`;
      } else {
        banner.className = "test-result-banner error";
        banner.innerHTML = `❌ <strong>连接失败</strong> (${data.latency_ms} ms)<br>${data.message}`;
      }
    } catch (e) {
      banner.className = "test-result-banner error";
      banner.innerHTML = `❌ <strong>网络请求异常</strong>: ${e.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = "⚡ 测试连通性";
    }
  });

  async function saveConfigToServer(successMsg) {
    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentConfig),
      });
      const data = await res.json();
      if (data.success) {
        showToast(successMsg, "success");
        fetchSystemStatus();
      } else {
        showToast(data.message || "保存失败", "error");
      }
    } catch (e) {
      showToast(`网络保存错误: ${e.message}`, "error");
    }
  }

  // ------------------------------------------------------------------------
  // 7. 联系人与群聊白名单选择
  // ------------------------------------------------------------------------
  async function loadContacts() {
    try {
      const res = await fetch("/api/wechat/contacts");
      const data = await res.json();
      allContacts = data.contacts || [];
      allGroups = data.groups || [];

      document.getElementById("contactCount").textContent = allContacts.length;
      document.getElementById("groupCount").textContent = allGroups.length;

      renderTargetList();
      updateTargetBadge();
    } catch (e) {
      showToast("获取微信好友与群聊失败，请确认微信是否已启动", "warning");
    }
  }

  function renderTargetList(filterKeyword = "") {
    const kw = filterKeyword.toLowerCase().trim();
    const contactsContainer = document.getElementById("contactsList");
    const groupsContainer = document.getElementById("groupsList");

    const whitelistUsers = new Set(currentConfig.targets.whitelist_users || []);
    const whitelistGroups = new Set(currentConfig.targets.whitelist_groups || []);

    // 渲染好友
    contactsContainer.innerHTML = "";
    const filteredContacts = allContacts.filter(c => 
      !kw || c.name.toLowerCase().includes(kw) || c.username.toLowerCase().includes(kw)
    );

    if (filteredContacts.length === 0) {
      contactsContainer.innerHTML = '<div class="empty-hint">未找到匹配的好友</div>';
    } else {
      filteredContacts.forEach(c => {
        const isSelected = whitelistUsers.has(c.username) || whitelistUsers.has(c.name);
        const item = document.createElement("div");
        item.className = `target-item ${isSelected ? 'selected' : ''}`;
        item.innerHTML = `
          <input type="checkbox" ${isSelected ? 'checked' : ''}>
          <div class="target-avatar">👤</div>
          <div class="target-info">
            <div class="target-name">${c.name} ${c.username === 'filehelper' ? '<span class="badge" style="background:#10b981; color:#fff;">推荐安全测试</span>' : ''}</div>
            <div class="target-summary">${c.summary || c.username}</div>
          </div>
        `;
        const cb = item.querySelector("input[type='checkbox']");
        item.addEventListener("click", (e) => {
          if (e.target !== cb) cb.checked = !cb.checked;
          if (cb.checked) {
            whitelistUsers.add(c.username);
            item.classList.add("selected");
          } else {
            whitelistUsers.delete(c.username);
            whitelistUsers.delete(c.name);
            item.classList.remove("selected");
          }
          currentConfig.targets.whitelist_users = Array.from(whitelistUsers);
          updateTargetBadge();
        });
        contactsContainer.appendChild(item);
      });
    }

    // 渲染群聊
    groupsContainer.innerHTML = "";
    const filteredGroups = allGroups.filter(g => 
      !kw || g.name.toLowerCase().includes(kw) || g.username.toLowerCase().includes(kw)
    );

    if (filteredGroups.length === 0) {
      groupsContainer.innerHTML = '<div class="empty-hint">未找到匹配的微信群</div>';
    } else {
      filteredGroups.forEach(g => {
        const isSelected = whitelistGroups.has(g.username) || whitelistGroups.has(g.name);
        const item = document.createElement("div");
        item.className = `target-item ${isSelected ? 'selected' : ''}`;
        item.innerHTML = `
          <input type="checkbox" ${isSelected ? 'checked' : ''}>
          <div class="target-avatar">👥</div>
          <div class="target-info">
            <div class="target-name">${g.name}</div>
            <div class="target-summary">${g.remark || g.username}</div>
          </div>
        `;
        const cb = item.querySelector("input[type='checkbox']");
        item.addEventListener("click", (e) => {
          if (e.target !== cb) cb.checked = !cb.checked;
          if (cb.checked) {
            whitelistGroups.add(g.username);
            item.classList.add("selected");
          } else {
            whitelistGroups.delete(g.username);
            whitelistGroups.delete(g.name);
            item.classList.remove("selected");
          }
          currentConfig.targets.whitelist_groups = Array.from(whitelistGroups);
          updateTargetBadge();
        });
        groupsContainer.appendChild(item);
      });
    }
  }

  function updateTargetBadge() {
    const total = (currentConfig.targets.whitelist_users?.length || 0) + 
                  (currentConfig.targets.whitelist_groups?.length || 0);
    document.getElementById("targetBadge").textContent = total;
  }

  // 搜索框过滤
  document.getElementById("targetSearchInput").addEventListener("input", (e) => {
    renderTargetList(e.target.value);
  });

  // 快捷按钮：仅文件传输助手
  document.getElementById("selectOnlyFilehelperBtn").addEventListener("click", () => {
    currentConfig.targets.whitelist_users = ["filehelper"];
    currentConfig.targets.whitelist_groups = [];
    currentConfig.targets.reply_all_private = false;
    currentConfig.targets.reply_all_groups = false;
    document.getElementById("replyAllPrivateCheckbox").checked = false;
    document.getElementById("replyAllGroupsCheckbox").checked = false;
    renderTargetList();
    updateTargetBadge();
    showToast("已切换为【仅文件传输助手】模式，可在微信安全发消息调试！", "info");
  });

  // 全选好友
  document.getElementById("selectAllContactsBtn").addEventListener("click", () => {
    currentConfig.targets.whitelist_users = allContacts.map(c => c.username);
    renderTargetList();
    updateTargetBadge();
  });

  // 全选群聊
  document.getElementById("selectAllGroupsBtn").addEventListener("click", () => {
    currentConfig.targets.whitelist_groups = allGroups.map(g => g.username);
    renderTargetList();
    updateTargetBadge();
  });

  // 清空选择
  document.getElementById("clearAllTargetsBtn").addEventListener("click", () => {
    currentConfig.targets.whitelist_users = [];
    currentConfig.targets.whitelist_groups = [];
    renderTargetList();
    updateTargetBadge();
  });

  // 刷新会话
  document.getElementById("refreshContactsBtn").addEventListener("click", async () => {
    await loadContacts();
    showToast("已重新从微信拉取会话清单", "success");
  });

  // 保存回复对象配置
  document.getElementById("saveTargetsBtn").addEventListener("click", async () => {
    currentConfig.targets.group_at_only = document.getElementById("groupAtOnlyCheckbox").checked;
    currentConfig.targets.group_auto_at_sender = document.getElementById("groupAutoAtSenderCheckbox").checked;
    currentConfig.targets.reply_all_private = document.getElementById("replyAllPrivateCheckbox").checked;
    currentConfig.targets.reply_all_groups = document.getElementById("replyAllGroupsCheckbox").checked;

    await saveConfigToServer("自动回复对象与群聊@规则保存成功！");
  });

  // ------------------------------------------------------------------------
  // 8. 本地 RAG 知识库管理 (可选功能)
  // ------------------------------------------------------------------------
  function updateRAGUIState(enabled) {
    const badge = document.getElementById("ragBadgeState");
    const fields = document.getElementById("ragConfigFields");
    if (enabled) {
      badge.textContent = "状态：已开启";
      badge.className = "rag-state-badge active";
      fields.style.opacity = "1";
      fields.style.pointerEvents = "auto";
    } else {
      badge.textContent = "状态：已停用 (可选)";
      badge.className = "rag-state-badge";
      fields.style.opacity = "0.75";
    }
  }

  document.getElementById("ragEnabledCheckbox").addEventListener("change", (e) => {
    const enabled = e.target.checked;
    currentConfig.rag.enabled = enabled;
    updateRAGUIState(enabled);
  });

  // 弹窗选择知识库文件夹
  const selectFolderBtn = document.getElementById("selectFolderBtn");
  if (selectFolderBtn) {
    selectFolderBtn.addEventListener("click", async () => {
      selectFolderBtn.disabled = true;
      selectFolderBtn.textContent = "⏳ 等待选择...";
      showToast("已弹出文件夹选择框，请在弹出的系统窗口中选择文件夹", "info");
      try {
        const res = await fetch("/api/utils/select_folder", { method: "POST" });
        const data = await res.json();
        if (data.success && data.folder_path) {
          document.getElementById("kbFolderInput").value = data.folder_path;
          showToast(`已选择文件夹: ${data.folder_path}`, "success");
          // 自动触发扫描文档
          document.getElementById("scanFolderBtn").click();
        } else if (data.message) {
          showToast(data.message, "info");
        }
      } catch (e) {
        showToast(`选择文件夹异常: ${e.message}`, "error");
      } finally {
        selectFolderBtn.disabled = false;
        selectFolderBtn.textContent = "📂 弹窗选择文件夹";
      }
    });
  }

  // 扫描文件夹
  document.getElementById("scanFolderBtn").addEventListener("click", async () => {
    const folder = document.getElementById("kbFolderInput").value.trim();
    if (!folder) {
      showToast("请先填入知识库文件夹路径", "warning");
      return;
    }
    try {
      const res = await fetch("/api/rag/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder_path: folder }),
      });
      const data = await res.json();
      const listBox = document.getElementById("docListBox");
      if (data.success && data.files.length > 0) {
        listBox.innerHTML = data.files.map(f => `
          <div class="doc-item-row">
            <span>📄 <strong>${f.name}</strong> <span style="color:#64748b;">(${f.ext})</span></span>
            <span style="color: #94a3b8;">${(f.size_bytes / 1024).toFixed(1)} KB</span>
          </div>
        `).join("");
        showToast(data.message, "success");
      } else {
        listBox.innerHTML = `<div class="empty-hint">${data.message || '未扫描到文档'}</div>`;
        showToast(data.message || "未找到有效文档", "warning");
      }
    } catch (e) {
      showToast(`扫描失败: ${e.message}`, "error");
    }
  });

  // 重建索引
  document.getElementById("reindexBtn").addEventListener("click", async () => {
    const folder = document.getElementById("kbFolderInput").value.trim();
    if (!folder) {
      showToast("请先填入知识库文件夹路径", "warning");
      return;
    }
    const btn = document.getElementById("reindexBtn");
    btn.disabled = true;
    btn.textContent = "⏳ 正在构建索引...";
    try {
      const res = await fetch("/api/rag/reindex", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder_path: folder }),
      });
      const data = await res.json();
      if (data.success) {
        document.getElementById("ragDocCount").textContent = `${data.doc_count} 篇`;
        document.getElementById("ragChunkCount").textContent = `${data.chunk_count} 块`;
        document.getElementById("ragLastTime").textContent = data.last_index_time || "刚刚";
        showToast(data.message, "success");
        fetchSystemStatus();
      } else {
        showToast(data.message, "error");
      }
    } catch (e) {
      showToast(`索引异常: ${e.message}`, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "⚡ 建立/重建索引";
    }
  });

  // 检索测试
  document.getElementById("ragSearchTestBtn").addEventListener("click", async () => {
    const query = document.getElementById("ragTestQueryInput").value.trim();
    if (!query) {
      showToast("请输入测试检索问题", "warning");
      return;
    }
    try {
      const res = await fetch("/api/rag/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query, top_k: 3 }),
      });
      const data = await res.json();
      const resultBox = document.getElementById("ragSearchResultBox");
      resultBox.style.display = "block";

      if (data.results && data.results.length > 0) {
        resultBox.innerHTML = data.results.map((r, i) => `
          <div style="margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,0.06);">
            <div style="display:flex; justify-content:space-between; color:#38bdf8; font-weight:600; font-size:12px;">
              <span>#${i+1} 来自《${r.file_name}》</span>
              <span>相关度得分: ${r.score}</span>
            </div>
            <div style="color: #cbd5e1; font-size: 12px; margin-top: 4px; line-height: 1.5; white-space: pre-wrap;">${r.content}</div>
          </div>
        `).join("");
      } else {
        resultBox.innerHTML = '<div class="empty-hint">未检索到任何高于阈值的知识切片 (请确认是否已建立索引)</div>';
      }
    } catch (e) {
      showToast(`检索测试失败: ${e.message}`, "error");
    }
  });

  // 保存 RAG 配置
  document.getElementById("saveRAGBtn").addEventListener("click", async () => {
    currentConfig.rag.enabled = document.getElementById("ragEnabledCheckbox").checked;
    currentConfig.rag.kb_folder_path = document.getElementById("kbFolderInput").value.trim();
    await saveConfigToServer("本地 RAG 知识库配置已保存！");
  });

  // ------------------------------------------------------------------------
  // 9. 在线模拟沙盒测试
  // ------------------------------------------------------------------------
  const sandboxSendBtn = document.getElementById("sandboxSendBtn");
  const sandboxInput = document.getElementById("sandboxMessageInput");
  const sandboxChatArea = document.getElementById("sandboxChatArea");

  async function sendSandboxMessage() {
    const text = sandboxInput.value.trim();
    if (!text) return;

    const isGroup = document.getElementById("sandboxIsGroupCheckbox").checked;
    const senderName = isGroup ? "群成员·测试小王" : "测试用户";

    // 添加用户气泡
    appendChatBubble("user", senderName, text);
    sandboxInput.value = "";
    sandboxSendBtn.disabled = true;

    // 占位机器人思考中气泡
    const botBubble = appendChatBubble("bot", "AI 智能助手 (思考中...)", "正在分析意图并调用全流程决策流水线...");

    try {
      const res = await fetch("/api/chat/sandbox", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          is_group: isGroup,
          sender_name: senderName,
        }),
      });
      const data = await res.json();
      
      let reply = data.reply_text || "【系统提示】模型未返回文本";
      if (data.error) {
        reply = `❌ 发生错误: ${data.error}`;
      }

      botBubble.querySelector(".bubble-sender").textContent = `AI 智能助手 (${data.duration_ms} ms)`;
      botBubble.querySelector(".bubble-content").textContent = reply;

    } catch (e) {
      botBubble.querySelector(".bubble-content").textContent = `请求失败: ${e.message}`;
    } finally {
      sandboxSendBtn.disabled = false;
    }
  }

  function appendChatBubble(role, sender, text) {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${role}`;
    bubble.innerHTML = `
      <div class="bubble-sender">${sender}</div>
      <div class="bubble-content">${text}</div>
    `;
    sandboxChatArea.appendChild(bubble);
    sandboxChatArea.scrollTop = sandboxChatArea.scrollHeight;
    return bubble;
  }

  sandboxSendBtn.addEventListener("click", sendSandboxMessage);
  sandboxInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      sendSandboxMessage();
    }
  });

  // ------------------------------------------------------------------------
  // 启动流程
  // ------------------------------------------------------------------------
  initWebSocket();
  loadConfig();
  fetchSystemStatus();

  // 定时刷新系统状态
  setInterval(fetchSystemStatus, 8000);
});
