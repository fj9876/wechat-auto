# -*- coding: utf-8 -*-
"""微信语音来电监听与自动接听执行器 (agent_core.voice_call.voip_watcher)

1. Win32 / UIAutomation 毫秒级探测微信语音/视频通话来电弹窗
2. 权限过滤：与当前微信自动回复白名单联动，群聊独立控制（默认忽略全部群聊）
3. 模拟真人延迟自动点击「接听」，生命周期追踪与超时强制挂断保护
"""
from __future__ import annotations

import re
import time
import logging
import threading
import ctypes
from typing import Optional, Callable, Dict, Any, Tuple, List

# 确保在 Windows 环境下启用高 DPI 感知 (Per-Monitor DPI Aware)，防止坐标因缩放产生偏移
try:
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

logger = logging.getLogger("VoIPWatcher")


class VoIPCallState:
    """通话状态机"""
    IDLE = "IDLE"                      # 空闲待命
    INCOMING = "INCOMING"              # 振铃呼入中
    IN_PROGRESS = "IN_PROGRESS"        # 通话进行中
    ENDED = "ENDED"                    # 通话已结束


class VoIPWatcher:
    """微信通话监控器"""

    def __init__(
        self,
        config,
        wechat_bridge=None,
        on_incoming_call: Optional[Callable[[str, bool], bool]] = None,
        on_call_answered: Optional[Callable[[str, bool], None]] = None,
        on_call_ended: Optional[Callable[[str, float], None]] = None,
    ):
        self.config = config
        self.bridge = wechat_bridge
        self.on_incoming_call = on_incoming_call
        self.on_call_answered = on_call_answered
        self.on_call_ended = on_call_ended

        self.state = VoIPCallState.IDLE
        self.current_caller = ""
        self.current_is_group = False
        self.current_wnd_hwnd = 0
        self.call_start_time = 0.0

        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """启动来电轮询监听线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="VoIPWatcherThread")
        self._thread.start()
        logger.info("[VoIPWatcher] 微信来电监视守护线程已启动")

    def stop(self):
        """停止监视"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self.state = VoIPCallState.IDLE

    # -------------------------------------------------------------------------
    # 白名单匹配与自动接听决策 (用户指令要求核心)
    # -------------------------------------------------------------------------

    def should_answer(self, caller_name: str, is_group: bool) -> Tuple[bool, str]:
        """判定该呼叫是否满足自动接听条件
        
        规则：
        1. 群聊通话：严格受 enable_group_call 控制，默认忽略全部群聊；仅在开启且命中 whitelist_groups 时接听
        2. 私聊通话：受 sync_reply_targets 控制，自动与当前消息回复对象白名单对齐
        """
        voip_cfg = self.config.voip

        if not voip_cfg.enabled:
            return False, "语音通话总开关已关闭"

        # 1. 群聊来电判定
        if is_group:
            if not voip_cfg.enable_group_call:
                return False, f"群聊通话默认全部忽略 (群聊: {caller_name})"
            # 群聊白名单匹配
            wl_groups = voip_cfg.whitelist_groups or []
            if caller_name in wl_groups or any(g in caller_name for g in wl_groups):
                return True, f"群聊 [{caller_name}] 命中群通话白名单"
            return False, f"群聊 [{caller_name}] 未在群通话白名单中"

        # 2. 私聊来电判定
        if voip_cfg.sync_reply_targets:
            # 与当前回复对象严格一致
            targets = self.config.targets
            if targets.reply_all_private:
                return True, f"私聊已开启全量回复，自动接听好友 [{caller_name}]"

            # 校验私聊白名单 (支持从 contact.db 解析的 username, 昵称, 备注)
            if self._is_user_in_reply_whitelist(caller_name):
                return True, f"好友 [{caller_name}] 命中自动回复白名单"
            return False, f"好友 [{caller_name}] 不在自动回复白名单中"
        else:
            # 使用独立设置的通话白名单
            wl_users = voip_cfg.whitelist_users or []
            if not wl_users or caller_name in wl_users:
                return True, f"好友 [{caller_name}] 命中独立通话白名单"
            return False, f"好友 [{caller_name}] 不在独立通话白名单中"

    def _is_user_in_reply_whitelist(self, caller_name: str) -> bool:
        """检查来电人是否匹配 targets.whitelist_users"""
        wl = self.config.targets.whitelist_users or []
        if not wl:
            return False

        if caller_name in wl:
            return True

        # 若有 bridge 且有通讯录缓存，用通讯录反查
        if self.bridge:
            try:
                data = self.bridge.get_contacts_and_groups(force_refresh=False)
                for c in data.get("contacts", []):
                    u = c.get("username", "")
                    n = c.get("name", "")
                    r = c.get("remark", "")
                    nk = c.get("nick_name", "")
                    if caller_name in (u, n, r, nk) or any(caller_name in x for x in (n, r, nk) if x):
                        if u in wl or n in wl or r in wl or nk in wl:
                            return True
            except Exception:
                pass

        # 若有 bridge / db，进一步通过备注、昵称与 wxid 反查
        if self.bridge and hasattr(self.bridge, "_db") and self.bridge._db:
            try:
                conn = self.bridge._db._contact_conn()
                if conn:
                    row = conn.execute(
                        "SELECT username, nick_name, remark FROM contact WHERE nick_name = ? OR remark = ? OR username = ?",
                        (caller_name, caller_name, caller_name)
                    ).fetchone()
                    if row:
                        u = row["username"]
                        if u in wl or row["nick_name"] in wl or row["remark"] in wl:
                            return True
            except Exception as e:
                logger.debug(f"[VoIPWatcher] DB 匹配联系人失败: {e}")

        # 模糊部分匹配
        for item in wl:
            if item and (item in caller_name or caller_name in item):
                return True
        return False

    # -------------------------------------------------------------------------
    # 核心探测与接听自动化循环
    # -------------------------------------------------------------------------

    def _get_wechat_pids(self) -> set:
        """获取并缓存当前运行的微信进程 PID 集合（10秒高速缓存，避免频繁调用 psutil 造成系统开销）"""
        now = time.time()
        if not hasattr(self, "_cached_wx_pids") or now - getattr(self, "_wx_pids_time", 0) > 10.0:
            pids = set()
            try:
                import psutil
                for p in psutil.process_iter(['pid', 'name']):
                    try:
                        pname = (p.info['name'] or "").lower()
                        if "weixin" in pname or "wechat" in pname:
                            pids.add(p.info['pid'])
                    except Exception:
                        pass
            except Exception:
                pass
            self._cached_wx_pids = pids
            self._wx_pids_time = now
        return self._cached_wx_pids

    def _watch_loop(self):
        """主轮询循环"""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        try:
            import win32service, win32con
            hwinsta = win32service.OpenWindowStation('WinSta0', True, win32con.MAXIMUM_ALLOWED)
            hwinsta.SetProcessWindowStation()
            hdesk = win32service.OpenDesktop('default', 0, True, win32con.MAXIMUM_ALLOWED)
            hdesk.SetThreadDesktop()
        except Exception:
            pass

        try:
            import uiautomation as uia
            with uia.UIAutomationInitializerInThread():
                while self._running:
                    try:
                        if self.state == VoIPCallState.IDLE:
                            self._detect_incoming_call()
                            time.sleep(1.0)
                        elif self.state == VoIPCallState.IN_PROGRESS:
                            self._monitor_active_call()
                            time.sleep(0.8)
                        else:
                            time.sleep(0.5)
                    except Exception as e:
                        logger.debug(f"[VoIPWatcher] 监视循环异常: {e}")
                        time.sleep(1.0)
        except Exception as e:
            logger.error(f"[VoIPWatcher] 监视守护线程异常: {e}")
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def _is_active_call_window(self, hwnd: int) -> bool:
        """极速鉴别某窗口是否为正在进行中的微信通话主窗口（微信 4.0 Qt5 架构与 3.x 统一兼容）
        
        特征：
        1. 微信进程或有效 Qt/VOIP 窗口，尺寸合理 (宽 180~650, 高 250~950)
        2. 含有通话计时器文本 (如 "00:57", "01:23")，或含有麦克风/扬声器状态
        3. 绝不包含 "接听", "接受", "邀请你", "邀请您" (那些是来电振铃小窗特征)
        """
        try:
            import win32gui
            if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                return False

            l, t, r, b = win32gui.GetWindowRect(hwnd)
            w, h = r - l, b - t
            if not (180 <= w <= 650 and 250 <= h <= 950):
                return False

            cls = win32gui.GetClassName(hwnd) or ""
            cls_lower = cls.lower()
            if "voipwindow" in cls_lower and "tray" not in cls_lower:
                return True

            title = (win32gui.GetWindowText(hwnd) or "").strip()
            title_lower = title.lower()

            # 快速排除非微信及常规主聊天/托盘窗口
            if cls in ("WeChatMainWndForPC", "mmui::MainWindow") or "main" in cls_lower or "tray" in cls_lower:
                return False

            # UIA 快速浅层扫描 (maxDepth=4，耗时极短 < 2ms)
            import uiautomation as uia
            win = uia.ControlFromHandle(hwnd)
            if not win or not win.Exists(0, 0):
                return False

            has_timer = False
            has_call_controls = False
            has_incoming_keywords = False
            timer_pattern = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")

            for ctrl, depth in uia.WalkControl(win, maxDepth=4):
                try:
                    cname = (ctrl.Name or "").strip()
                    if not cname:
                        continue
                    if timer_pattern.match(cname):
                        has_timer = True
                        break
                    if any(kw in cname for kw in ["邀请你", "邀请您", "接听", "接受", "Answer"]):
                        has_incoming_keywords = True
                        break
                    if any(kw in cname for kw in ["麦克风已开", "麦克风已关", "扬声器已开", "扬声器已关", "静音", "挂断", "结束通话"]):
                        has_call_controls = True
                except Exception:
                    pass

            if has_incoming_keywords:
                return False

            if has_timer or has_call_controls:
                return True

            # 备用判定：如果标题明确为 "语音通话" 或 "视频通话"，且高度较大 (h > 400)，且无接听字样
            if any(kw in title for kw in ["语音通话", "视频通话"]) and h > 400:
                return True

            return False
        except Exception:
            return False

    def _find_active_call_window(self) -> Optional[int]:
        """遍历查找当前正在进行中的微信通话主窗口 HWND"""
        try:
            import win32gui, win32process
            wx_pids = self._get_wechat_pids()
            found_hwnd = None

            def _search_proc(hwnd, _):
                nonlocal found_hwnd
                if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                    return True
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                w, h = r - l, b - t
                if not (180 <= w <= 650 and 250 <= h <= 950):
                    return True
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if wx_pids and pid not in wx_pids:
                    return True
                if self._is_active_call_window(hwnd):
                    found_hwnd = hwnd
                    return False  # 停止遍历
                return True

            win32gui.EnumWindows(_search_proc, None)
            return found_hwnd
        except Exception as e:
            logger.debug(f"[VoIPWatcher] 检索活跃通话窗口异常: {e}")
            return None

    def _detect_incoming_call(self):
        """探测微信来电振铃小窗并执行精准物理接听 (兼顾 0% CPU 占用与 100% 硬件级鼠标送达)"""
        try:
            import uiautomation as uia
            import psutil
            import win32api, win32con, win32gui

            try:
                screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
                screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            except Exception:
                screen_w = 1920
                screen_h = 1080

            # 遍历所有顶层窗口，寻找属于 WeChat/Weixin 且包含接听控件的弹窗
            for win in uia.GetRootControl().GetChildren():
                if not win.Exists(0, 0):
                    continue
                name = win.Name or ""
                class_name = win.ClassName or ""
                rect = win.BoundingRectangle

                # 1. 判定是否为微信进程或特征类名 (覆盖 Weixin.exe, WeChat.exe 及 Qt/Voip 等类名)
                is_wechat_wnd = False
                try:
                    pname = psutil.Process(win.ProcessId).name().lower()
                    if any(proc in pname for proc in ["weixin", "wechat"]):
                        is_wechat_wnd = True
                except Exception:
                    pass

                if not is_wechat_wnd:
                    if any(kw in class_name for kw in ["Qt", "WeChat", "Weixin", "Voip", "VOIP"]):
                        is_wechat_wnd = True
                    elif any(kw in name for kw in ["微信", "语音通话", "视频通话", "邀请你"]):
                        is_wechat_wnd = True

                if not is_wechat_wnd:
                    continue

                # 微信 4.0 主窗口不包含来电接听弹窗，宽度一般大于 500 且类名为 mmui::MainWindow 或大尺寸，直接跳过以彻底避免高 CPU 占用
                win_w = rect.right - rect.left
                win_h = rect.bottom - rect.top
                if (class_name == "mmui::MainWindow" or "main" in class_name.lower()) and win_w > 500:
                    continue
                if win_w > 550 and win_h > 450:
                    continue
                if win_w <= 30 or win_h <= 30:
                    continue

                # 2. 深入控件树探查是否包含来电特征文本与按钮 (maxDepth=4 浅层遍历，耗时仅 ~1ms，CPU 0%)
                all_texts = []
                buttons = []

                try:
                    for ctrl, depth in uia.WalkControl(win, maxDepth=4):
                        try:
                            raw_name = getattr(ctrl, "Name", "")
                            cname = (raw_name if isinstance(raw_name, str) else "").strip()
                            raw_cls = getattr(ctrl, "ClassName", "")
                            ccls = raw_cls if isinstance(raw_cls, str) else ""
                            raw_id = getattr(ctrl, "AutomationId", "")
                            cid = (raw_id if isinstance(raw_id, str) else "").lower()
                            cname_lower = cname.lower()

                            if cname:
                                all_texts.append(cname)

                            # 排除标题栏辅助按钮（关闭、最小化、稍后提醒等）
                            if any(kw in cname_lower for kw in [
                                "关闭", "close", "最小化", "minimize", "最大化", "maximize", "还原", "restore",
                                "pin", "置顶", "暂不处理", "稍后处理", "稍后提醒", "稍后", "忽略", "提醒"
                            ]):
                                continue
                            if any(kw in cid for kw in ["close", "min", "max", "pin", "defer", "ignore"]):
                                continue

                            if ctrl.ControlType == uia.ControlType.ButtonControl or "Button" in ccls or any(kw in cname for kw in ["接听", "挂断", "拒绝", "接受", "Answer"]):
                                buttons.append(ctrl)
                        except Exception:
                            pass
                except Exception as err:
                    logger.debug(f"[VoIPWatcher] 遍历窗口控件异常: {err}")

                # 关键判别: 如果这是正在通话中的主面板 (含通话计时器或麦克风控制且高度 > 250)
                timer_pattern = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
                is_active_call_panel = ("voipwindow" in class_name.lower() and "tray" not in class_name.lower()) or (
                    (any(timer_pattern.match(t) for t in all_texts) or any("麦克风" in t for t in all_texts)) and win_h > 250
                )
                if is_active_call_panel:
                    logger.info(f"[VoIPWatcher] 捕获到正在进行中的微信通话窗口 ({class_name})，自动同步通话状态")
                    self.state = VoIPCallState.IN_PROGRESS
                    self.call_start_time = time.time()
                    self._last_active_detect_time = time.time()
                    self.current_wnd_hwnd = win.NativeWindowHandle
                    if not self.current_caller:
                        self.current_caller = self._get_caller_from_wechat_chat_list() or self._get_caller_from_recent_sessions() or "微信好友"
                    if self.on_call_answered:
                        self.on_call_answered(self.current_caller, False)
                    return

                # 判定条件 1: 微信专属来电振铃悬浮窗类名特征
                is_tray_class = any(kw.lower() in class_name.lower() for kw in [
                    "voiptray", "p2pvoiptray", "mtvoiptray"
                ])

                # 判定条件 2: 微信进程且物理坐标位于屏幕右下象限的小弹窗 (例如 362x190)
                is_corner_popup = (
                    is_wechat_wnd
                    and (rect.right >= screen_w - 550 or rect.left >= screen_w - 550)
                    and (rect.bottom >= screen_h - 450 or rect.top >= screen_h - 450)
                    and (100 < win_w < 550 and 40 < win_h < 400)
                )

                # 判定条件 3: 标题或子控件含来电文字特征
                has_call_text = any(kw in name for kw in ["邀请你", "语音通话", "视频通话", "邀请您"])
                if not has_call_text and all_texts:
                    has_call_text = any(any(kw in t for kw in ["邀请你", "语音通话", "视频通话", "邀请您"]) for t in all_texts)

                is_call_popup = is_tray_class or is_corner_popup or has_call_text

                if not is_call_popup:
                    continue

                # 3. 解析来电人与是否群聊
                caller_name, is_group = self._parse_caller_info_from_texts(name, all_texts)
                if not caller_name or self._is_invalid_caller_name(caller_name) or caller_name == "微信好友":
                    top_caller = self._get_caller_from_wechat_chat_list()
                    if top_caller and not self._is_invalid_caller_name(top_caller):
                        caller_name = top_caller

                if not caller_name or self._is_invalid_caller_name(caller_name) or caller_name == "微信好友":
                    recent_caller = self._get_caller_from_recent_sessions()
                    if recent_caller:
                        caller_name = recent_caller

                logger.info(f"[VoIPWatcher] 🚨 捕获到微信来电弹窗！类名={class_name}, 坐标=({rect.left},{rect.top},{rect.right},{rect.bottom}), 来电方={caller_name}, 群聊={is_group}")

                # 触发实时来电回调 (通知 UI 主控制台展示来电事件)
                if self.state != VoIPCallState.INCOMING and self.on_incoming_call:
                    try:
                        self.on_incoming_call(caller_name, is_group)
                    except Exception as err:
                        logger.debug(f"[VoIPWatcher] on_incoming_call 异常: {err}")

                self.state = VoIPCallState.INCOMING
                self.current_caller = caller_name
                self.current_is_group = is_group
                self.current_wnd_hwnd = win.NativeWindowHandle

                # 4. 定位接听按钮与点击坐标
                answer_btn = None
                for btn in buttons:
                    raw_bname = getattr(btn, "Name", "")
                    bname = raw_bname if isinstance(raw_bname, str) else ""
                    raw_bid = getattr(btn, "AutomationId", "")
                    bid = raw_bid if isinstance(raw_bid, str) else ""
                    if any(kw in bname for kw in ["接听", "接受", "Answer"]):
                        answer_btn = btn
                        break
                    if bid in ("answer_button", "btn_accept", "AcceptButton"):
                        answer_btn = btn
                        break

                if answer_btn is None and len(buttons) >= 2:
                    try:
                        non_hangup = [b for b in buttons if not any(k in (b.Name or "") for k in ["挂断", "拒绝", "Decline", "Hangup"])]
                        if non_hangup:
                            # 接听按钮在最右侧，取 X 坐标最大的
                            non_hangup.sort(key=lambda b: b.BoundingRectangle.left)
                            answer_btn = non_hangup[-1]
                            logger.info(f"[VoIPWatcher] 按最右侧非挂断按钮推断接听: {getattr(answer_btn, 'Name', '')}")
                        else:
                            # 所有按钮均无法区分，取最右侧
                            buttons.sort(key=lambda b: b.BoundingRectangle.left)
                            answer_btn = buttons[-1]
                            logger.info(f"[VoIPWatcher] 无法区分按钮，取最右侧: {getattr(answer_btn, 'Name', '')}")
                    except Exception:
                        buttons.sort(key=lambda b: b.BoundingRectangle.left)
                        answer_btn = buttons[-1]

                if answer_btn is None and len(buttons) == 1:
                    bname = buttons[0].Name or ""
                    if not any(kw in bname for kw in ["挂断", "拒绝", "Decline", "Hangup"]):
                        answer_btn = buttons[0]

                # 计算接听物理坐标 (优先使用绿色按键高精几何中心算法)
                center_x = 0
                center_y = 0
                if answer_btn is not None:
                    try:
                        b_rect = answer_btn.BoundingRectangle
                        val_x = b_rect.xcenter() if callable(getattr(b_rect, "xcenter", None)) else None
                        bx = int(val_x) if isinstance(val_x, (int, float)) else (b_rect.left + b_rect.right) // 2
                        val_y = b_rect.ycenter() if callable(getattr(b_rect, "ycenter", None)) else None
                        by = int(val_y) if isinstance(val_y, (int, float)) else (b_rect.top + b_rect.bottom) // 2

                        # 严格门禁：必须在右半区且在下半区才采纳
                        if (rect.left + int(win_w * 0.45) <= bx <= rect.right - 5) and (rect.top + int(win_h * 0.45) <= by <= rect.bottom - 5):
                            center_x, center_y = bx, by
                            logger.info(f"[VoIPWatcher] 成功获取接听控件物理坐标: ({center_x}, {center_y})")
                        elif (int(win_w * 0.45) <= bx <= win_w) and (int(win_h * 0.45) <= by <= win_h):
                            center_x = rect.left + bx
                            center_y = rect.top + by
                            logger.info(f"[VoIPWatcher] 接听控件坐标为客户区偏移，已平移屏幕物理坐标: ({center_x}, {center_y})")
                    except Exception:
                        pass

                # 几何推算高精物理中心
                # 微信 4.0 mmui::VOIPTrayWindow 来电弹窗实测布局 (375x132):
                #   [头像/名字区域 0~60%]  [🔴挂断 ~71%]  [🟢接听 ~86%]
                if center_x <= 0 or center_y <= 0:
                    if win_h >= 100:
                        center_x = rect.left + int(win_w * 0.86)
                        center_y = rect.top + int(win_h * 0.76)
                    else:
                        center_x = rect.right - 28
                        center_y = (rect.top + rect.bottom) // 2
                    logger.info(f"[VoIPWatcher] 几何推算坐标(接听=右侧86%): ({center_x}, {center_y}) [窗口={win_w}x{win_h}]")

                should, reason = self.should_answer(caller_name, is_group)
                logger.info(f"[VoIPWatcher] 自动接听规则判定: should={should}, reason={reason}")

                if should:
                    delay = self.config.voip.auto_answer_delay_sec
                    if delay > 0:
                        logger.info(f"[VoIPWatcher] 延迟 {delay} 秒后自动执行接听...")
                        time.sleep(delay)

                    # 再次确认窗口仍存在（避免等待期间对方已主动取消）
                    if not win.Exists(0, 0):
                        logger.info(f"[VoIPWatcher] 来电窗口已消失，对方已取消通话或已挂断")
                        self.state = VoIPCallState.IDLE
                        return

                    logger.info(f"[VoIPWatcher] 🚀 正在向微信来电窗口发送物理鼠标点击: ({center_x}, {center_y})")

                    # 激活并置顶弹窗
                    _hwnd_for_click = win.NativeWindowHandle
                    try:
                        if _hwnd_for_click:
                            import win32gui as _wg, win32con as _wc
                            _wg.ShowWindow(_hwnd_for_click, _wc.SW_RESTORE)
                            _wg.SetForegroundWindow(_hwnd_for_click)
                    except Exception:
                        pass
                    time.sleep(0.08)

                    # 执行多层冗余点击 (每次点击间隔 100ms，共尝试最多 6 次不同策略+坐标)
                    click_success = self._physical_click_with_retry(
                        center_x, center_y, rect, win_w, win_h,
                        hwnd=_hwnd_for_click, answer_btn=answer_btn
                    )

                    # 等待弹窗消失（最多 3 秒）作为真实成功判定
                    answered = False
                    for _wait_i in range(15):
                        time.sleep(0.2)
                        try:
                            if not win.Exists(0, 0):
                                answered = True
                                break
                        except Exception:
                            answered = True
                            break

                    if answered:
                        self.state = VoIPCallState.IN_PROGRESS
                        self.call_start_time = time.time()
                        self._last_active_detect_time = time.time()
                        self.current_wnd_hwnd = _hwnd_for_click
                        logger.info(f"[VoIPWatcher] ✅ 来电弹窗已消失，确认接通好友 [{caller_name}] 语音通话！")
                        if self.on_call_answered:
                            self.on_call_answered(caller_name, is_group)
                    else:
                        # 弹窗未消失，扫射式多点尝试（以 86% 为中心向两侧扫射）
                        logger.warning(f"[VoIPWatcher] ⚠️ 弹窗尚未消失，追加多点扫射点击...")
                        offsets = [0.86, 0.89, 0.83, 0.92, 0.80]
                        for ox in offsets:
                            cx_retry = rect.left + int(win_w * ox)
                            cy_retry = rect.top + int(win_h * 0.76)
                            self._physical_click(cx_retry, cy_retry)
                            time.sleep(0.18)
                            try:
                                if not win.Exists(0, 0):
                                    answered = True
                                    break
                            except Exception:
                                answered = True
                                break

                        if answered:
                            self.state = VoIPCallState.IN_PROGRESS
                            self.call_start_time = time.time()
                            self._last_active_detect_time = time.time()
                            self.current_wnd_hwnd = _hwnd_for_click
                            logger.info(f"[VoIPWatcher] ✅ 扫射点击后确认接通好友 [{caller_name}] 语音通话！")
                            if self.on_call_answered:
                                self.on_call_answered(caller_name, is_group)
                        else:
                            logger.error(f"[VoIPWatcher] ❌ 所有点击策略均失败，来电弹窗仍未消失，重置状态等待下次轮询")
                            self.state = VoIPCallState.IDLE
                else:
                    logger.info(f"[VoIPWatcher] 忽略该来电: {reason}")
                    time.sleep(3.0)
                    self.state = VoIPCallState.IDLE
                return

        except Exception as e:
            logger.debug(f"[VoIPWatcher] 探测窗口出错: {e}")

    def _monitor_active_call(self):
        """监视进行中的通话，检测挂断与超时保护 (Win32 轻量级监测，0% CPU 占用)"""
        now = time.time()
        elapsed = now - self.call_start_time
        max_duration = self.config.voip.max_call_duration_min * 60

        if elapsed > max_duration:
            logger.warning(f"[VoIPWatcher] 通话已达到最大保护时长 ({self.config.voip.max_call_duration_min}分钟)，执行自动挂断！")
            self._hangup_active_call()
            return

        # 通话初期 8 秒内允许微信窗口切换与初始化，不触发挂断判定
        if elapsed < 8.0:
            self._last_active_detect_time = now
            # 尝试在初期尽快绑定通话主大窗
            if not self.current_wnd_hwnd or not win32gui.IsWindow(self.current_wnd_hwnd):
                act_wnd = self._find_active_call_window()
                if act_wnd:
                    self.current_wnd_hwnd = act_wnd
            return

        try:
            import win32gui
            call_active = False

            # 1. 优先极速直接校验当前已持有的通话窗口 HWND (耗时 0.001ms, 0% CPU)
            if self.current_wnd_hwnd and win32gui.IsWindow(self.current_wnd_hwnd) and win32gui.IsWindowVisible(self.current_wnd_hwnd):
                call_active = True
            else:
                # 2. 当前 HWND 失效时，扫描寻找新的活跃通话主窗口
                active_hwnd = self._find_active_call_window()
                if active_hwnd:
                    call_active = True
                    self.current_wnd_hwnd = active_hwnd
                    logger.info(f"[VoIPWatcher] 通话监控已接管并绑定通话主大窗: HWND={active_hwnd}")

            if call_active:
                self._last_active_detect_time = now
            else:
                last_time = getattr(self, "_last_active_detect_time", None)
                if last_time is None:
                    self._last_active_detect_time = now
                elif now - last_time > 5.0:
                    logger.info(f"[VoIPWatcher] 微信通话已结束，总时长: {int(elapsed)}秒")
                    self.state = VoIPCallState.ENDED
                    if self.on_call_ended:
                        self.on_call_ended(self.current_caller, elapsed)
                    self.state = VoIPCallState.IDLE
                    self.current_caller = ""
                    self.current_wnd_hwnd = 0
        except Exception as e:
            logger.debug(f"[VoIPWatcher] 监控通话状态异常: {e}")

    def _physical_click(self, x: int, y: int) -> bool:
        """使用多重策略发送一次真实物理鼠标左键点击到屏幕绝对坐标 (x, y)。
        
        关键修复：win32api.mouse_event 使用 MOUSEEVENTF_ABSOLUTE 标志时坐标需归一化到 0~65535。
        不使用该标志时，x/y 参数是"相对于当前位置的增量像素"而非屏幕像素，故之前无效。
        """
        try:
            import win32api, win32con
            # 获取屏幕分辨率用于归一化
            _sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN) or 1920
            _sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN) or 1080
            # 归一化到 0~65535
            nx = int(x * 65535 / _sw)
            ny = int(y * 65535 / _sh)
            # 先移动光标到目标位置（通过 SetCursorPos 设置真实像素坐标）
            win32api.SetCursorPos((x, y))
            time.sleep(0.03)
            # 使用 MOUSEEVENTF_ABSOLUTE + 归一化坐标发送绝对点击
            _abs_flag = win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_LEFTDOWN
            win32api.mouse_event(_abs_flag, nx, ny, 0, 0)
            time.sleep(0.05)
            _abs_flag2 = win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_LEFTUP
            win32api.mouse_event(_abs_flag2, nx, ny, 0, 0)
            logger.info(f"[VoIPWatcher] 物理点击(ABSOLUTE)已送达: 像素({x},{y}) 归一化({nx},{ny})")
            return True
        except Exception as e:
            logger.debug(f"[VoIPWatcher] _physical_click win32 失败: {e}")

        # 备用: pyautogui（禁用 FAILSAFE 防止角落位置异常）
        try:
            import pyautogui
            _prev_failsafe = pyautogui.FAILSAFE
            pyautogui.FAILSAFE = False
            pyautogui.moveTo(x, y, duration=0.08)
            time.sleep(0.03)
            pyautogui.click(x, y)
            pyautogui.FAILSAFE = _prev_failsafe
            logger.info(f"[VoIPWatcher] 物理点击(pyautogui)已送达: ({x},{y})")
            return True
        except Exception as e:
            logger.debug(f"[VoIPWatcher] _physical_click pyautogui 失败: {e}")
        return False

    def _physical_click_with_retry(
        self, cx: int, cy: int, win_rect, win_w: int, win_h: int,
        hwnd: int = 0, answer_btn=None
    ) -> bool:
        """多策略冗余点击，按优先级尝试: UIA Invoke → UIA Click → SendMessage → ABSOLUTE mouse_event
        
        这是自动接听的核心执行器，所有策略都应当被尝试，不因为前一个成功而跳过后续。
        """
        import ctypes

        # 策略 0: UIAutomation Invoke (对于标准 Win32/UIA 控件最可靠)
        if answer_btn is not None:
            try:
                invk = answer_btn.GetInvokePattern()
                if invk:
                    invk.Invoke()
                    logger.info("[VoIPWatcher] UIA Invoke 已发送")
                    time.sleep(0.1)
            except Exception:
                pass
            try:
                answer_btn.Click()
                logger.info("[VoIPWatcher] UIA Click 已发送")
                time.sleep(0.1)
            except Exception:
                pass

        # 策略 1: SendMessage WM_LBUTTONDOWN/UP (对 Qt 隐式窗口最有效，不依赖前台焦点)
        if hwnd:
            try:
                import win32gui, win32con
                # 将屏幕绝对坐标转换为窗口客户区坐标
                _pt = win32gui.ScreenToClient(hwnd, (cx, cy))
                _lparam = (_pt[1] << 16) | (_pt[0] & 0xFFFF)
                win32gui.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, _lparam)
                time.sleep(0.06)
                win32gui.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, _lparam)
                logger.info(f"[VoIPWatcher] SendMessage WM_LBUTTONDOWN/UP 已发送到 HWND={hwnd}, 客户区坐标={_pt}")
                time.sleep(0.08)
            except Exception as e:
                logger.debug(f"[VoIPWatcher] SendMessage 失败: {e}")

        # 策略 2: SetCursorPos + ABSOLUTE mouse_event (通用硬件级，所有窗口类型均支持)
        self._physical_click(cx, cy)
        time.sleep(0.1)

        # 策略 3: 小幅偏移再次尝试（应对按钮中心与实际可点击区域轻微偏差）
        for dx, dy in [(5, 0), (-5, 0), (0, 5), (0, -5)]:
            self._physical_click(cx + dx, cy + dy)
            time.sleep(0.06)

        return True

    def _hangup_active_call(self):
        """点击挂断按钮挂断通话"""
        try:
            import win32gui
            import uiautomation as uia

            target_hwnd = self.current_wnd_hwnd
            if not target_hwnd or not win32gui.IsWindow(target_hwnd):
                return

            win = uia.ControlFromHandle(target_hwnd)
            if not win or not win.Exists(0, 0):
                return

            for ctrl, depth in uia.WalkControl(win, maxDepth=8):
                d_name = ctrl.Name or ""
                if ctrl.ControlType == uia.ControlType.ButtonControl and (any(kw in d_name for kw in ["挂断", "结束通话"]) or ctrl.AutomationId in ("hangup_button", "btn_hangup")):
                    try:
                        ctrl.Click()
                    except Exception:
                        r = ctrl.BoundingRectangle
                        cx = r.xcenter() if callable(getattr(r, "xcenter", None)) else (r.left + r.right) // 2
                        cy = r.ycenter() if callable(getattr(r, "ycenter", None)) else (r.top + r.bottom) // 2
                        try:
                            import pyautogui
                            pyautogui.click(cx, cy)
                        except Exception:
                            pass
                    logger.info("[VoIPWatcher] 已触发自动挂断操作")
                    return
        except Exception as e:
            logger.error(f"[VoIPWatcher] 挂断操作失败: {e}")

    def _find_active_call_window(self) -> Optional[int]:
        """寻找当前处于活动通话状态的微信通话主大窗 HWND"""
        try:
            import win32gui, win32process, psutil, ctypes

            user32 = ctypes.windll.user32
            h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if h_desk:
                user32.SetThreadDesktop(h_desk)

            pids = {p.pid for p in psutil.process_iter(['name', 'pid']) if any(k in (p.info.get('name') or '').lower() for k in ['weixin', 'wechat'])}
            if not pids:
                return None

            active_hwnd = None

            def enum_cb(hwnd, _):
                nonlocal active_hwnd
                if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                    return True
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid not in pids:
                    return True

                rect = win32gui.GetWindowRect(hwnd)
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                # 过滤零尺寸或极小窗口
                if w <= 100 or h <= 100:
                    return True

                cls = win32gui.GetClassName(hwnd)
                title = win32gui.GetWindowText(hwnd)

                # 排除微信主界面 (通常尺寸较大，如 800x600+)
                if "MainWindow" in cls or (w >= 700 and h >= 550 and title in ("微信", "WeChat")):
                    return True

                # 排除纯托盘/系统消息类
                if any(k in cls.lower() for k in ["tray", "message", "ime", "power", "displayicc", "chrome_"]):
                    return True

                # 微信通话主窗口特征:
                # 1. 明确类名包含 voipwindow (如 mmui::VOIPWindow)
                if "voipwindow" in cls.lower() and "tray" not in cls.lower():
                    active_hwnd = hwnd
                    return False

                # 2. Qt 独立通话面板特征: 高度通常在 300~750，宽度在 200~550 之间
                if 200 <= w <= 600 and 300 <= h <= 800:
                    # 检查是否为来电弹窗（来电弹窗高度一般小于 220，如 362x190）
                    if h < 220:
                        return True
                    active_hwnd = hwnd
                    return False

                return True

            if h_desk:
                user32.EnumDesktopWindows(h_desk, ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(enum_cb), 0)
            else:
                win32gui.EnumWindows(enum_cb, 0)

            return active_hwnd
        except Exception as e:
            logger.debug(f"[VoIPWatcher] 寻找通话主窗口异常: {e}")
            return None

    @staticmethod
    def _is_invalid_caller_name(name: str) -> bool:
        """识别并过滤 Qt 窗口类名、通话计时器等系统技术标识，防止误当做联系人名字"""
        if not name or not name.strip():
            return True
        s = name.strip()
        s_lower = s.lower()

        # 1. 严格过滤通话时长计时器 (如 00:07, 00:12, 00:39, 01:23:45)
        if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', s):
            return True

        # 2. 严格过滤弹窗操作按钮与状态词
        invalid_words = {
            "挂断", "接听", "拒绝", "接受", "取消", "结束通话",
            "暂不处理", "稍后处理", "稍后提醒", "稍后", "忽略", "提醒",
            "收起", "最小化", "最大化", "还原", "关闭", "全屏", "置顶",
            "麦克风已开", "麦克风已关", "扬声器已开", "扬声器已关", "静音", "开麦",
            "摄像头已开", "摄像头已关", "切换到语音通话", "切换到视频通话"
        }
        if s in invalid_words or s_lower in invalid_words:
            return True

        # 3. 过滤包含操作词且较短的词语（比如 "暂不处理", "稍后处理" 等）
        if any(op in s for op in ["暂不处理", "稍后", "处理", "提醒", "忽略", "挂断", "接听", "邀请你", "邀请您"]) and len(s) <= 8:
            return True

        # 4. 过滤系统与 Qt 内部技术类名/标识
        technical_names = {
            "mmuirendersubwindowhw", "mmuirendersubwindow", "qt51514qwindowicon",
            "qt51514qwindowtoolsavebits", "mmui::voiptraywindow", "voiptraywindow",
            "mmui::voipwindow", "voipwindow", "weixin", "wechat", "微信",
            "base_powermessagewindow", "wxtrayiconmessagewindow",
            "msctfime ui", "default ime", "gdi+ window (weixin.exe)",
            "displayicc_systemmessagewindow", "chrome_systemmessagewindow",
            "p2pvoiptrayview", "mtvoiptrayview"
        }
        if s_lower in technical_names:
            return True

        for kw in ["subwindow", "windowicon", "toolsavebits", "qwindow", "traywindow", "voip", "render", "messagewindow", "hw"]:
            if kw in s_lower and len(s) >= 4:
                return True

        # 5. 纯符号或纯数字排除
        if re.match(r'^[\d\s\:\-\.\_]+$', s):
            return True

        return False

    def _parse_caller_info_from_texts(self, win_title: str, all_texts: List[str]) -> Tuple[str, bool]:
        """从弹窗标题与所有内部文本元素精准解析呼叫人名称与是否为群聊"""
        is_group = "群" in win_title or any("群" in t for t in all_texts)
        caller = ""

        # 正则提取模式（匹配 "xxx 邀请你语音通话", "xxx 邀请您进行视频通话", "来自 xxx 的语音通话" 等复合文本）
        invite_patterns = [
            # 模式 1: "xxx 邀请你语音通话" / "xxx 邀请您进行语音通话" / "xxx 邀请你加入群聊语音通话"
            re.compile(r'^(.*?)\s*(?:邀请[你您]|发起了|发起|呼叫)\s*(?:进行|加入)?\s*(?:群聊)?\s*(?:语音|视频)?\s*通话'),
            # 模式 2: "xxx 邀请你..."
            re.compile(r'^(.*?)\s*邀请[你您]'),
            # 模式 3: "来自 xxx 的语音通话"
            re.compile(r'^来自\s*(.*?)\s*的\s*(?:语音|视频)?\s*通话'),
            # 模式 4: "xxx 正在呼叫"
            re.compile(r'^(.*?)\s*(?:正在呼叫|呼叫中|来电)'),
        ]

        # 策略 1: 遍历 all_texts 与 win_title，优先通过复合提示文本中的前缀提取联系人名字
        text_sources = list(all_texts)
        if win_title and win_title not in text_sources:
            text_sources.insert(0, win_title)

        for text in text_sources:
            t = text.strip()
            if not t:
                continue
            for pattern in invite_patterns:
                m = pattern.search(t)
                if m:
                    cand = m.group(1).strip()
                    cand = re.sub(r'^(来自|从)\s*', '', cand).strip()
                    if cand and not self._is_invalid_caller_name(cand) and cand != "微信好友":
                        logger.info(f"[VoIPWatcher] 从复合文本 [{t}] 成功提取来电方: [{cand}]")
                        return cand, is_group

        # 策略 2: 遍历独立文本元素，寻找非动作词、非系统类名的纯名称元素
        candidate_names = []
        for t in all_texts:
            raw = t.strip()
            if not raw:
                continue
            if self._is_invalid_caller_name(raw):
                continue
            # 排除含有动作/状态特征的短语
            if any(kw in raw for kw in [
                "邀请", "通话", "微信", "视频", "语音", "发起了", "呼叫",
                "暂不处理", "稍后", "处理", "提醒", "忽略", "点击", "按键"
            ]):
                continue
            candidate_names.append(raw)

        if candidate_names:
            caller = candidate_names[0].strip()
            logger.info(f"[VoIPWatcher] 从独立控件文本中提取到来电方: [{caller}]")
            return caller, is_group

        # 策略 3: 若 win_title 本身是有效名字且非系统标题
        if win_title and not self._is_invalid_caller_name(win_title):
            cleaned_title = win_title.strip()
            if not any(kw in cleaned_title for kw in ["微信", "通话", "Qt", "Window"]):
                caller = cleaned_title
                logger.info(f"[VoIPWatcher] 从窗口标题提取到来电方: [{caller}]")
                return caller, is_group

        return "微信好友", is_group

    def _get_caller_from_wechat_chat_list(self) -> str:
        """当来电弹窗未暴露可访问文本时，从微信主界面会话列表中提取当前处于来电状态的好友名称 (兼容 3.x 与 4.0)"""
        try:
            import uiautomation as uia
            for win in uia.GetRootControl().GetChildren():
                cls = win.ClassName or ""
                if cls in ("mmui::MainWindow", "WeChatMainWndForPC") or "mainwindow" in cls.lower() or "wechat" in cls.lower():
                    for ctrl, depth in uia.WalkControl(win, maxDepth=10):
                        cname = (ctrl.Name or "").strip()
                        if "[语音通话]" in cname or "[视频通话]" in cname:
                            cleaned = cname.replace("[语音通话]", "").replace("[视频通话]", "").strip()
                            if cleaned and not self._is_invalid_caller_name(cleaned):
                                return cleaned
                        if "语音通话" in cname and 0 < len(cname) < 25:
                            cleaned = cname.replace("语音通话", "").strip()
                            if cleaned and not self._is_invalid_caller_name(cleaned):
                                return cleaned
        except Exception:
            pass
        return ""

    def _get_caller_from_recent_sessions(self) -> str:
        """从微信最新活跃会话中精准锁定当前发起来电的好友"""
        try:
            if self.bridge:
                res = self.bridge.get_contacts_and_groups(force_refresh=True)
                contacts = res.get("contacts", [])
                for c in contacts:
                    uname = c.get("username", "")
                    if uname in ("filehelper", "fmessage") or uname.startswith("gh_"):
                        continue
                    disp = (c.get("remark") or c.get("name") or c.get("nick_name") or "").strip()
                    if disp and not self._is_invalid_caller_name(disp):
                        logger.info(f"[VoIPWatcher] 成功通过微信最近活跃会话锁定来电好友: [{disp}] ({uname})")
                        return disp
        except Exception as e:
            logger.debug(f"[VoIPWatcher] 从最近会话提取联系人异常: {e}")
        return "微信好友"

