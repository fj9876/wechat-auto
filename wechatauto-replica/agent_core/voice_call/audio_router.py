# -*- coding: utf-8 -*-
"""虚拟音频路由与声卡双向跳线模块 (agent_core.voice_call.audio_router)

基于 sounddevice 实现低延迟音频输入输出：
1. 录音流 (Capture): 从虚拟声卡输入端 (微信扬声器输出) 捕获对方说话音频
2. 播放流 (Playback): 将 AI 合成的 TTS 语音推流注入虚拟声卡输出端 (微信麦克风，供对方收听)
3. 本地监听流 (Local Monitor): 可选将 AI 发音同步镜像写入电脑物理扬声器，方便现场测试
4. 智能打断缓冲清空: 对方插话瞬间清空播放队列与声卡流缓冲
"""
from __future__ import annotations

import re
import time
import queue
import logging
import threading
import numpy as np
from typing import Optional, Callable, List, Dict, Any

logger = logging.getLogger("AudioRouter")


class AudioRouter:
    """音频流跳线路由器"""

    def __init__(
        self,
        input_device_name: str = "",
        output_device_name: str = "",
        sample_rate: int = 16000,
        on_audio_captured: Optional[Callable[[bytes], None]] = None,
        enable_local_monitor: bool = True,
        monitor_device_name: str = "",
        acoustic_classifier: Optional[Any] = None,
    ):
        self.input_device_name = input_device_name
        self.output_device_name = output_device_name
        self.sample_rate = sample_rate
        self.on_audio_captured = on_audio_captured
        self.enable_local_monitor = enable_local_monitor
        self.monitor_device_name = monitor_device_name
        self.acoustic_classifier = acoustic_classifier

        self._input_stream = None
        self._output_stream = None
        self._monitor_stream = None
        self._playback_queue: queue.Queue = queue.Queue()
        self._running = False
        self._playback_thread: Optional[threading.Thread] = None
        self._is_playing: bool = False
        self._last_active_time: float = 0.0
        self.hangover_sec: float = 1.2

    @staticmethod
    def list_devices() -> List[Dict[str, Any]]:
        """枚举当前系统所有可用的输入与输出音频设备 (优先 MME 稳固驱动并补全截断全名)"""
        devices = []
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            if not devs:
                return []

            # 建立全名映射表 (DirectSound / WASAPI 包含未被 Windows 31字符限制截断的完整设备名)
            full_name_map = {}
            for d in devs:
                raw_n = d["name"].strip()
                prefix = raw_n[:26].lower()
                if len(raw_n) > len(full_name_map.get(prefix, "")):
                    full_name_map[prefix] = raw_n

            # 优先枚举 MME (hostapi == 0) 设备
            mme_devs = [idx for idx, d in enumerate(devs) if d.get("hostapi", 0) == 0]
            target_indices = mme_devs if mme_devs else list(range(len(devs)))

            for idx in target_indices:
                d = devs[idx]
                name = d["name"].strip()
                prefix = name[:26].lower()
                full_name = full_name_map.get(prefix, name)

                devices.append({
                    "id": idx,
                    "name": full_name,
                    "max_inputs": d["max_input_channels"],
                    "max_outputs": d["max_output_channels"],
                    "default_samplerate": d["default_samplerate"],
                    "hostapi": d.get("hostapi", 0),
                })
        except Exception as e:
            logger.error(f"[AudioRouter] 枚举声卡设备失败: {e}")
        return devices

    def _resolve_device_id(self, name_hint: Any, kind: str = "input") -> Optional[int]:
        """根据名称关键词、前缀编号或纯净设备名智能匹配设备 ID (虚拟声卡强制锁定 MME 驱动)"""
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            if not devs:
                return None

            name_str = str(name_hint).strip() if name_hint is not None else ""
            id_hint = None
            clean_name = name_str

            if isinstance(name_hint, int):
                id_hint = name_hint
                clean_name = ""
            elif name_str.isdigit():
                id_hint = int(name_str)
                clean_name = ""
            elif name_str:
                m = re.match(r"^(\d+)\s*:\s*(.*)$", name_str)
                if m:
                    id_hint = int(m.group(1))
                    clean_name = m.group(2).strip()

            target = clean_name.lower() if clean_name else ""
            # 若未指定设备名称，默认自动探测并锁定 VB-CABLE 虚拟声卡
            if not target and id_hint is None:
                is_cable = True
            else:
                is_cable = "cable" in target or "vb-audio" in target or "virtual" in target

            # 若传入了旧 ID (如 9 或 13)，检查该 ID 是否指向虚拟声卡
            if id_hint is not None and 0 <= id_hint < len(devs):
                d_name = devs[id_hint]["name"].lower()
                if "cable" in d_name or "vb-audio" in d_name or "virtual" in d_name:
                    is_cable = True
                    if not target:
                        target = d_name

            # 核心机制：Windows DirectSound (1) 与 WASAPI (2) 在虚拟声卡上存在严重静音与采样率冲突 Bug；
            # 虚拟声卡必须且只能通过原生 MME (0) 驱动推流与捕获！
            if is_cable:
                # 寻找匹配输入/输出的 MME 虚拟声卡设备
                for idx, d in enumerate(devs):
                    if d.get("hostapi", 0) != 0:
                        continue
                    ch = d["max_input_channels"] if kind == "input" else d["max_output_channels"]
                    if ch <= 0:
                        continue
                    d_name = d["name"].lower()
                    if kind == "input" and ("cable output" in d_name or "cable" in d_name):
                        return idx
                    elif kind == "output" and ("cable input" in d_name or "cable" in d_name):
                        return idx

            # 1. 优先校验候选 ID 是否依然有效且为 MME (0) 驱动
            if id_hint is not None and 0 <= id_hint < len(devs):
                d = devs[id_hint]
                ch = d["max_input_channels"] if kind == "input" else d["max_output_channels"]
                if ch > 0 and d.get("hostapi", 0) == 0:
                    if not clean_name:
                        return id_hint
                    d_lower = d["name"].lower()
                    c_lower = clean_name.lower()
                    if c_lower in d_lower or d_lower in c_lower:
                        return id_hint

            # 2. 候选 ID 发生漂移或仅传入文本名称：在所有可用设备中根据关键词与通道进行智能评分 (优先 MME)
            candidates = []
            for idx, d in enumerate(devs):
                ch = d["max_input_channels"] if kind == "input" else d["max_output_channels"]
                if ch <= 0 or d.get("hostapi", 0) == 3:  # 排除不可用的 WDM-KS
                    continue

                d_name = d["name"].lower()
                score = 0
                if target and target == d_name:
                    score = 100
                elif target and (target in d_name or d_name in target):
                    score = 80
                elif "cable input" in target and "cable input" in d_name:
                    score = 75
                elif "cable output" in target and "cable output" in d_name:
                    score = 75
                elif "cable" in target and "cable" in d_name:
                    score = 50
                elif not target:
                    score = 10

                if score > 0:
                    # 极度优先 MME (0)，DirectSound 次之
                    if d.get("hostapi", 0) == 0:
                        score += 30
                    elif d.get("hostapi", 0) == 1:
                        score += 10
                    candidates.append((score, idx, d["name"], d.get("hostapi", 0)))

            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                return candidates[0][1]

        except Exception as e:
            logger.warning(f"[AudioRouter] 解析设备 ID 失败: {e}")
        return None

    def _find_physical_output_device(self) -> Optional[int]:
        """自动探测本地物理扬声器或耳机设备 (用于双路实时监听，优先 MME)"""
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            # 优先查找非虚拟声卡的物理扬声器/耳机 (优先 MME)
            for idx, d in enumerate(devs):
                if d["max_output_channels"] <= 0 or d.get("hostapi", 0) != 0:
                    continue
                name_l = d["name"].lower()
                if any(v in name_l for v in ["cable", "virtual", "loopback"]):
                    continue
                if any(k in name_l for k in ["realtek", "speaker", "扬声器", "headphone", "耳机"]):
                    return idx

            # 备选：任何具备输出通道的非虚拟声卡 (MME)
            for idx, d in enumerate(devs):
                if d["max_output_channels"] <= 0 or d.get("hostapi", 0) != 0:
                    continue
                name_l = d["name"].lower()
                if not any(v in name_l for v in ["cable", "virtual", "loopback"]):
                    return idx

            # 兜底：允许 DirectSound 物理设备
            for idx, d in enumerate(devs):
                if d["max_output_channels"] <= 0 or d.get("hostapi", 0) == 3:
                    continue
                name_l = d["name"].lower()
                if not any(v in name_l for v in ["cable", "virtual", "loopback"]):
                    return idx
        except Exception as e:
            logger.debug(f"[AudioRouter] 探测物理扬声器异常: {e}")
        return None

    def start(self):
        """启动录音捕获与发声播放音频流"""
        if self._running:
            return
        self._running = True

        import sounddevice as sd

        in_dev = self._resolve_device_id(self.input_device_name, kind="input")
        out_dev = self._resolve_device_id(self.output_device_name, kind="output")

        logger.info(
            f"[AudioRouter] 启动音频流: 录音输入={in_dev} ({self.input_device_name}), "
            f"电话主输出={out_dev} ({self.output_device_name})"
        )

        # 1. 录音流回调
        def _in_callback(indata, frames, time_info, status):
            if status:
                logger.debug(f"[AudioRouter] Input status: {status}")
            if self._running and self.on_audio_captured:
                # 转为 16-bit PCM 单声道
                pcm16 = (indata[:, 0] * 32767.0).astype(np.int16).tobytes()
                try:
                    self.on_audio_captured(pcm16)
                except Exception:
                    pass

        try:
            self._input_stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                device=in_dev,
                blocksize=1024,
                callback=_in_callback,
            )
            self._input_stream.start()
        except Exception as e:
            logger.error(f"[AudioRouter] 开启录音流失败: {e}")

        # 2. 播放线程 (负责向电话输出端推流，并可选同步本地监听)
        self._playback_thread = threading.Thread(
            target=self._playback_loop,
            args=(out_dev,),
            daemon=True,
            name="AudioPlaybackLoop"
        )
        self._playback_thread.start()

    def _playback_loop(self, out_dev):
        """向目标声卡推流播放 AI 语音 (支持主虚拟声卡 + 本地物理扬声器双路推流)"""
        import sounddevice as sd

        # 1. 打开主输出流 (推向微信麦克风虚拟声卡 CABLE Input，让对方听到)
        try:
            self._output_stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                device=out_dev,
                blocksize=1024,
            )
            self._output_stream.start()
            logger.info(f"[AudioRouter] ✅ 电话主推流已建立: Device={out_dev}")
        except Exception as e:
            logger.error(f"[AudioRouter] ❌ 开启电话主播放流失败 (Device={out_dev}): {e}")

        # 2. 若配置了本地监听，开启物理扬声器镜像流 (供坐在电脑前的人实时收听 AI 发音)
        mon_dev = None
        if self.enable_local_monitor:
            if self.monitor_device_name:
                mon_dev = self._resolve_device_id(self.monitor_device_name, kind="output")
            if mon_dev is None:
                mon_dev = self._find_physical_output_device()

            if mon_dev is not None and mon_dev != out_dev:
                try:
                    self._monitor_stream = sd.OutputStream(
                        samplerate=self.sample_rate,
                        channels=1,
                        dtype="float32",
                        device=mon_dev,
                        blocksize=1024,
                    )
                    self._monitor_stream.start()
                    logger.info(f"[AudioRouter] 🔊 本地物理扬声器同步监听已就绪: Device={mon_dev}")
                except Exception as e:
                    logger.warning(f"[AudioRouter] 开启本地扬声器监听流失败 (Device={mon_dev}): {e}")
                    self._monitor_stream = None

        while self._running:
            try:
                # 获取待播放的 pcm16 音频切片 (bytes, rate)
                item = self._playback_queue.get(timeout=0.1)
            except queue.Empty:
                self._is_playing = False
                continue

            if not item:
                self._is_playing = False
                continue

            pcm_bytes, orig_rate = item
            if not pcm_bytes:
                self._is_playing = False
                continue

            self._is_playing = True

            # 转换为 float32 并重采样 (若采样率不一致)
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            # 动态人声音量保真增益 (防止微信软件端 AGC 门限将轻微发音当作背景噪声滤除)
            if len(samples) > 0:
                max_peak = float(np.max(np.abs(samples)))
                if 0.01 < max_peak < 0.70:
                    gain = min(2.5, 0.88 / max_peak)
                    samples = samples * gain

            if orig_rate != self.sample_rate and len(samples) > 0:
                try:
                    import scipy.signal
                    num_target = int(len(samples) * self.sample_rate / orig_rate)
                    samples = scipy.signal.resample(samples, num_target).astype(np.float32)
                except Exception:
                    # 简易线性插值兜底
                    duration = len(samples) / orig_rate
                    target_len = int(duration * self.sample_rate)
                    samples = np.interp(
                        np.linspace(0, len(samples), target_len, endpoint=False),
                        np.arange(len(samples)),
                        samples
                    ).astype(np.float32)

            # 分块平滑推入声卡
            chunk_size = 1024
            for i in range(0, len(samples), chunk_size):
                if not self._running or not self._is_playing:
                    break
                block = samples[i:i + chunk_size]
                if len(block) < chunk_size:
                    block = np.pad(block, (0, chunk_size - len(block)))

                out_block = block.reshape(-1, 1)

                # 1. 写入主电话输出声卡 (微信麦克风)
                if self._output_stream:
                    try:
                        if not self._output_stream.active:
                            self._output_stream.start()
                        self._output_stream.write(out_block)
                        self._last_active_time = time.time()
                    except Exception as e:
                        logger.warning(f"[AudioRouter] 主流播放写入错误: {e}，尝试完整重建输出流...")
                        try:
                            # MME error 33 需要完整关闭并重建流，单纯 abort+start 无法恢复
                            self._output_stream.abort()
                            self._output_stream.close()
                        except Exception:
                            pass
                        import sounddevice as sd
                        try:
                            out_dev = self._resolve_device_id(self.output_device_name, kind="output")
                            if out_dev is None:
                                out_dev = sd.default.device[1]
                            self._output_stream = sd.OutputStream(
                                samplerate=self.sample_rate, channels=1,
                                dtype="float32", device=out_dev, blocksize=1024,
                            )
                            self._output_stream.start()
                            logger.info("[AudioRouter] 输出流已完整重建")
                        except Exception as re_err:
                            logger.error(f"[AudioRouter] 重建输出流失败: {re_err}")
                        break

                # 2. 同步写入本地监听声卡 (电脑喇叭/耳机)
                if self._monitor_stream:
                    try:
                        self._monitor_stream.write(out_block)
                    except Exception:
                        pass

            if self._playback_queue.empty():
                self._is_playing = False

    @property
    def is_playing(self) -> bool:
        """当前是否正在播放 AI 语音 (包含声卡缓冲区输出与环境残响保护尾期)"""
        in_hangover = (time.time() - self._last_active_time) < self.hangover_sec if self._last_active_time > 0 else False
        return self._is_playing or (not self._playback_queue.empty()) or in_hangover

    def play_audio(self, pcm_bytes: bytes, orig_rate: int = 24000):
        """将合成的音频块投入播放队列并向声学判别器更新参考波形 (具备未启动自动拉起自愈机制)"""
        if not pcm_bytes:
            return
        if not self._running:
            logger.warning("[AudioRouter] 收到发音数据但音频流未启动，正在自动启动声卡音频路由...")
            self.start()
        if self.acoustic_classifier:
            try:
                self.acoustic_classifier.put_reference_audio(pcm_bytes, orig_rate=orig_rate)
            except Exception:
                pass
        self._playback_queue.put((pcm_bytes, orig_rate))

    def interrupt(self):
        """打断正在进行的播音，瞬间清空队列与流缓冲区"""
        logger.info("[AudioRouter] 触发音频打断: 清空发声缓冲区")
        self._is_playing = False
        self._last_active_time = 0.0
        if self.acoustic_classifier:
            try:
                # 打断 = AI 已停止发音。必须清空参考缓冲，否则后续用户说话会被
                # 旧指纹层误判为 AI 回声导致对话永久卡死
                self.acoustic_classifier.clear_reference_only()
            except Exception:
                pass
        while not self._playback_queue.empty():
            try:
                self._playback_queue.get_nowait()
            except queue.Empty:
                break
        if self._output_stream:
            try:
                self._output_stream.abort()
                self._output_stream.start()
            except Exception:
                pass
        if self._monitor_stream:
            try:
                self._monitor_stream.abort()
                self._monitor_stream.start()
            except Exception:
                pass

    def stop(self):
        """关闭所有音频流"""
        self._running = False
        self.interrupt()

        if self._input_stream:
            try:
                self._input_stream.stop()
                self._input_stream.close()
            except Exception:
                pass
            self._input_stream = None

        if self._output_stream:
            try:
                self._output_stream.stop()
                self._output_stream.close()
            except Exception:
                pass
            self._output_stream = None

        if self._monitor_stream:
            try:
                self._monitor_stream.stop()
                self._monitor_stream.close()
            except Exception:
                pass
            self._monitor_stream = None
