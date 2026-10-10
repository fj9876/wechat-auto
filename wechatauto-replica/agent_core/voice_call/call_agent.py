# -*- coding: utf-8 -*-
"""微信电话实时对话总控中心 (agent_core.voice_call.call_agent)

统筹调度整个语音电话全双工流水线：
1. VoIPWatcher 来电自动探测与接听决策
2. AudioRouter 虚拟音频跳线与双工声卡推流 (含残响延时保护)
3. STTWorker (Faster-Whisper + Silero VAD) 实时识别与打断探测
4. 智能自发音回声消除与防打断过滤 (Semantic Echo Cancellation)
5. 串行有序 TTS 队列与 Generation ID 打断取消控制
6. DialogueEngine 当前配置大模型流式思考与画像记忆注入
7. TTSManager (ChatTTS / Qwen3-TTS / Edge-TTS) 多音色与声音克隆发音
"""
from __future__ import annotations

import re
import time
import queue
import difflib
import logging
import threading
import collections
from typing import Optional, Callable, Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor

from agent_core.voice_call.voip_watcher import VoIPWatcher, VoIPCallState
from agent_core.voice_call.audio_router import AudioRouter
from agent_core.voice_call.stt_worker import STTWorker
from agent_core.voice_call.dialogue_engine import DialogueEngine
from agent_core.voice_call.tts_manager import TTSManager
from agent_core.voice_call.voice_clone import VoiceCloneManager
from agent_core.voice_call.acoustic_classifier import AcousticClassifier

logger = logging.getLogger("WeChatCallAgent")


class WeChatCallAgent:
    """微信电话智能对话总控引擎"""

    def __init__(self, app_config, profile_engine=None, wechat_bridge=None, on_event_cb: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.config = app_config
        self.profile_engine = profile_engine
        self.bridge = wechat_bridge
        self.on_event_cb = on_event_cb

        # 0. 基于声波波形与音调基频的声学说话人判别器 (严格区分 AI 声音 vs 真人用户人声)
        self.acoustic_classifier = AcousticClassifier(sample_rate=16000)

        # 1. 声音克隆与 TTS 管理器
        self.voice_clone_mgr = VoiceCloneManager()
        self.tts_manager = TTSManager(default_engine=self.config.voip.tts_engine)
        self._sync_voice_clone_config()

        # 2. 对话引擎 (严格使用当前大模型配置)
        self.dialogue_engine = DialogueEngine(
            llm_config=self.config.llm,
            profile_engine=self.profile_engine,
            on_sentence_ready=self._on_ai_sentence_ready,
            on_reply_finished=self._on_ai_reply_finished,
        )

        # 3. 语音识别 Worker (支持 FunASR Paraformer 与 Faster-Whisper，注入声学判别器与全生命周期状态)
        device = self.config.voice.whisper_device
        if device == "auto":
            device = "cuda"
        stt_eng = getattr(self.config.voip, "stt_engine", "paraformer")
        para_model = getattr(self.config.voip, "paraformer_model", "paraformer-zh")
        self.stt_worker = STTWorker(
            whisper_model_name=self.config.voice.whisper_model,
            device=device,
            on_speech_started=self._on_caller_speech_started,
            on_transcription=self._on_caller_transcription,
            is_ai_speaking_fn=lambda: self.is_ai_speaking,
            barge_in_enabled=bool(getattr(self.config.voip, "barge_in_enabled", False)),
            acoustic_classifier=self.acoustic_classifier,
            stt_engine=stt_eng,
            paraformer_model_name=para_model,
        )

        # 4. 虚拟音频路由器 (注入残响延时保护与参考声波采集)
        hangover = getattr(self.config.voip, "echo_hangover_sec", 1.2)
        self.audio_router = AudioRouter(
            input_device_name=self.config.voip.virtual_input_device,
            output_device_name=self.config.voip.virtual_output_device,
            sample_rate=16000,
            on_audio_captured=self.stt_worker.put_audio,
            acoustic_classifier=self.acoustic_classifier,
        )
        self.audio_router.hangover_sec = hangover

        # 4.1 虚拟数字人与视频流路由器 (LivePortrait-Realtime & MuseTalk)
        try:
            import os
            from agent_core.video_call.avatar_engine import AvatarEngineManager
            from agent_core.video_call.video_router import VideoRouter
            self.avatar_manager = AvatarEngineManager(config=self.config)
            cam_w = getattr(self.config.voip, "virtual_camera_width", 640)
            cam_h = getattr(self.config.voip, "virtual_camera_height", 480)
            cam_fps = getattr(self.config.voip, "virtual_camera_fps", 25)
            self.video_router = VideoRouter(
                app_config=self.config,
                avatar_manager=self.avatar_manager,
                width=cam_w,
                height=cam_h,
                fps=cam_fps
            )
            char_img = getattr(self.config.voip, "avatar_image_path", "data/avatars/default_avatar.png")
            if os.path.exists(char_img):
                self.avatar_manager.set_character_image(char_img)
            logger.info("[CallAgent] ✅ 虚拟数字人与视频路由中枢就绪")
        except Exception as e:
            logger.warning(f"[CallAgent] 视频数字人组件初始化跳过: {e}")
            self.avatar_manager = None
            self.video_router = None

        # 5. 来电检测器
        self.voip_watcher = VoIPWatcher(
            config=self.config,
            wechat_bridge=self.bridge,
            on_incoming_call=self._on_call_incoming,
            on_call_answered=self._on_call_answered,
            on_call_ended=self._on_call_ended,
        )

        # 6. 回声自发音防串音队列与多线程流水线并发有序 TTS
        self._recent_ai_utterances: collections.deque[Tuple[str, float]] = collections.deque(maxlen=30)
        self._current_gen_id = 0
        self._current_sentence_seq = 0
        self._next_play_seq = 0
        self._tts_queue: queue.Queue = queue.Queue()
        self._tts_results: Dict[int, Tuple[bytes, int, str]] = {}
        self._tts_results_lock = threading.Lock()
        self._tts_dispatch_event = threading.Event()
        self._tts_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="TTSPipeline")
        self._tts_thread: Optional[threading.Thread] = None
        self._running = False
        self._is_synthesizing_tts: bool = False
        self._active_synth_count = 0
        self._synth_count_lock = threading.Lock()
        self._last_ai_speech_end_time: float = 0.0

    @property
    def is_ai_speaking(self) -> bool:
        """全局全周期判定 AI 当前是否正在发声或处于发声准备/网络残响期 (100% 阻断时序空窗)"""
        # 1. 大模型正在思考流式生成回复
        if getattr(self, "dialogue_engine", None) and getattr(self.dialogue_engine, "is_generating", False):
            return True
        # 2. TTS 待合成队列非空
        if getattr(self, "_tts_queue", None) and not self._tts_queue.empty():
            return True
        # 3. TTS 线程正在网络合成音频
        if getattr(self, "_is_synthesizing_tts", False):
            return True
        with self._synth_count_lock:
            if self._active_synth_count > 0:
                return True
        # 4. 流水线中有已合成待播放或等待保序分发的音频块
        with self._tts_results_lock:
            if self._tts_results or self._next_play_seq < self._current_sentence_seq:
                return True
        # 5. AudioRouter 声卡播放队列非空或正在推流播放
        if getattr(self, "audio_router", None) and self.audio_router.is_playing:
            return True
        # 6. 播音结束后的微信网络 RTT 往返时延与残响保护期 (2.0 秒)
        if (time.time() - self._last_ai_speech_end_time) < 2.0:
            return True
        return False

    def _sync_voice_clone_config(self):
        """同步多段克隆音色库与当前生效音色"""
        if not self.config.voip.voice_clone_enabled:
            self.tts_manager.set_voice_clone("")
            return

        ref_path = ""
        prompt_text = ""
        active_id = getattr(self.config.voip, "active_cloned_voice_id", "")
        if active_id:
            profile = self.voice_clone_mgr.get_voice(active_id)
            if profile and profile.audio_path:
                ref_path = profile.audio_path
                prompt_text = profile.prompt_text

        # 备用回退单文件配置
        if not ref_path and self.config.voip.voice_clone_audio_path:
            ref_path = self.config.voip.voice_clone_audio_path
            prompt_text = self.config.voip.voice_clone_prompt_text

        if ref_path:
            self.tts_manager.set_voice_clone(ref_path, prompt_text)
        else:
            self.tts_manager.set_voice_clone("")

    def emit_event(self, event_type: str, data: Dict[str, Any]):
        """分发事件给外部 UI 或日志组件"""
        if self.on_event_cb:
            try:
                self.on_event_cb({"type": event_type, "data": data})
            except Exception:
                pass

    def start(self):
        """启动微信电话守护智能体"""
        if self._running:
            return
        self._running = True

        # 重归时重置 TTS 流水线状态，防止旧事件遗留干扰
        self._tts_dispatch_event.clear()
        try:
            while not self._tts_queue.empty():
                self._tts_queue.get_nowait()
        except Exception:
            pass
        with self._tts_results_lock:
            self._tts_results.clear()
        self._current_gen_id += 1
        self._current_sentence_seq = 0
        self._next_play_seq = 0
        self._active_synth_count = 0

        logger.info("[CallAgent] 启动微信语音电话智能总控...")

        # 启动有序 TTS 流水线分发消费线程
        self._tts_thread = threading.Thread(target=self._tts_dispatcher_loop, daemon=True, name="TTSDispatcherLoop")
        self._tts_thread.start()

        self.voip_watcher.start()
        self.emit_event("call_agent_started", {"status": "listening"})

        # 异步预热 STT Faster-Whisper 模型到 GPU，避免通话刚接通时有 3 秒初始化延迟
        try:
            threading.Thread(target=self.stt_worker.initialize_model, daemon=True, name="PrewarmWhisper").start()
        except Exception as e:
            logger.debug(f"[CallAgent] 预热 Whisper 线程创建异常: {e}")

    def stop(self):
        """停止守护"""
        self._running = False  # 必须先置 False，此后 start() 才能重新进入
        self._current_gen_id += 1
        with self._synth_count_lock:
            self._active_synth_count = 0
        self._last_ai_speech_end_time = 0.0
        self.acoustic_classifier.clear()
        with self._tts_results_lock:
            self._tts_results.clear()

        # 唯醒 TTS 分发线程让其自然退出 (daemon 线程不需强杀)
        self._tts_dispatch_event.set()
        # 清空旧队列，备下次重启时用全新的空队列
        try:
            while not self._tts_queue.empty():
                self._tts_queue.get_nowait()
        except Exception:
            pass
        self._tts_thread = None

        self.voip_watcher.stop()
        self.audio_router.stop()
        if getattr(self, "video_router", None):
            self.video_router.stop()
        self.stt_worker.stop()
        self.dialogue_engine.cancel()
        self._recent_ai_utterances.clear()
        self._current_sentence_seq = 0
        self._next_play_seq = 0
        logger.info("[CallAgent] 微信语音电话智能总控已停止")
        self.emit_event("call_agent_stopped", {"status": "stopped"})

    def reload_config(self, new_config):
        """配置热重载"""
        self.config = new_config
        self.voip_watcher.config = new_config
        self.dialogue_engine.update_config(new_config.llm)
        self.tts_manager.current_engine = new_config.voip.tts_engine.lower()
        self.tts_manager.kokoro_voice = getattr(new_config.voip, "kokoro_voice", "zf_xiaobei")
        self.stt_worker.stt_engine = getattr(new_config.voip, "stt_engine", "paraformer").lower()
        self.stt_worker.paraformer_model_name = getattr(new_config.voip, "paraformer_model", "paraformer-zh")
        self.audio_router.hangover_sec = getattr(new_config.voip, "echo_hangover_sec", 1.2)
        self.audio_router.input_device_name = new_config.voip.virtual_input_device
        self.audio_router.output_device_name = new_config.voip.virtual_output_device
        self.stt_worker.barge_in_enabled = bool(getattr(new_config.voip, "barge_in_enabled", False))
        self._sync_voice_clone_config()
        if getattr(self, "avatar_manager", None):
            try:
                import os
                eng_type = getattr(new_config.voip, "avatar_engine", "liveportrait")
                self.avatar_manager.set_engine_type(eng_type)
                img_path = getattr(new_config.voip, "avatar_image_path", "data/avatars/default_avatar.png")
                if os.path.exists(img_path):
                    self.avatar_manager.set_character_image(img_path)
            except Exception as e:
                logger.debug(f"[CallAgent] 热重载数字人配置异常: {e}")
        logger.info(f"[CallAgent] 配置热重载完成: 识别引擎=[{self.stt_worker.stt_engine}], 发音引擎=[{self.tts_manager.current_engine}], 打断模式=[{self.stt_worker.barge_in_enabled}]")

    # -------------------------------------------------------------------------
    # 状态与流水线协同回调
    # -------------------------------------------------------------------------

    def _on_call_incoming(self, caller_name: str, is_group: bool, is_video: bool = False):
        """来电实时感知事件 (振铃中)"""
        call_type = "视频" if is_video else "语音"
        logger.info(f"[CallAgent] 🔔 捕获到微信{call_type}来电请求: 来电方=[{caller_name}], 是否群聊={is_group}")
        self.emit_event("call_incoming", {"caller": caller_name, "is_group": is_group, "is_video": is_video})

    def _on_call_answered(self, caller_name: str, is_group: bool, is_video: bool = False):
        """电话接通事件"""
        call_type = "视频" if is_video else "语音"
        logger.info(f"[CallAgent] {call_type}电话已接通: 开始与 [{caller_name}] 实时对话 (is_group={is_group}, is_video={is_video})")
        self.emit_event("call_connected", {"caller": caller_name, "is_group": is_group, "is_video": is_video})

        self._recent_ai_utterances.clear()
        self.acoustic_classifier.clear()
        with self._synth_count_lock:
            self._active_synth_count = 0
        self._last_ai_speech_end_time = 0.0
        self._current_gen_id += 1
        self._current_sentence_seq = 0
        self._next_play_seq = 0
        with self._tts_results_lock:
            self._tts_results.clear()
        self._tts_dispatch_event.set()

        # 【关键】在启动录音流之前，提前合成一段短语音，建立 AI 音色声学指纹
        # 这样不依赖 AI 实际播音时序，从第一句话起就能识别 AI 自身回声
        self._build_ai_voice_fingerprint_async()

        # 启动对话会话、音频流与 STT
        self.dialogue_engine.start_call_session(caller_name)
        self.audio_router.start()
        self.stt_worker.start()

        # 若开启了视频数字人功能，电话接通时保持虚拟摄像头推流待命，彻底杜绝微信连入绿幕
        if getattr(self.config.voip, "video_enabled", True):
            if getattr(self, "video_router", None) and not self.video_router.is_running:
                logger.info(f"[CallAgent] 📹 通话接通 (is_video={is_video})，立即启动虚拟数字人视频推流中枢")
                self.video_router.start()

    def _on_caller_speech_started(self):
        """对方开始说话 -> 触发全双工打断 (Barge-in)"""
        if self.config.voip.barge_in_enabled:
            logger.info("[CallAgent] 收到打断信号: 立即废弃未播旧句，停止 AI 发声与生成")
            self._current_gen_id += 1
            self._current_sentence_seq = 0
            self._next_play_seq = 0
            with self._synth_count_lock:
                self._active_synth_count = 0
            with self._tts_results_lock:
                self._tts_results.clear()
            self._tts_dispatch_event.set()
            self._last_ai_speech_end_time = 0.0
            # 重要: 不能 clear() 声学分类器 — barge-in 后声卡仍有残响，必须继续用参考波形判别和阻断
            # 只刷新时间戳，让已缓存的 AI 声波指纹继续发挥作用
            self.acoustic_classifier.reset_timer_only()
            self.audio_router.interrupt()
            if getattr(self, "video_router", None) and self.video_router.is_running:
                self.video_router.interrupt()
            self.dialogue_engine.cancel()
            self.emit_event("barge_in", {"message": "对方说话，AI 语音已被打断"})

    def _build_ai_voice_fingerprint_async(self):
        """在后台线程中合成接通问候语，提前建立 AI 音色声学指纹并主动向电话对面播放问候"""
        def _build():
            try:
                # 使用当前配置的 TTS 引擎合成一段自然的开场短句（既建立 MFCC/F0 声学指纹，又作为开场礼貌问候）
                greeting_text = "喂，你好！我是微信电话助理，请问有什么可以帮您？"
                logger.info(f"[CallAgent] 🔊 正在合成接通问候语并建立 AI 声学指纹...")
                pcm_bytes, sample_rate = self.tts_manager.synthesize(greeting_text)
                if pcm_bytes and len(pcm_bytes) > 3200:
                    ok = self.acoustic_classifier.build_voice_fingerprint(pcm_bytes, orig_rate=sample_rate)
                    if ok:
                        logger.info("[CallAgent] ✅ AI 音色指纹预建立成功，可在 AI 第一句话播出前即识别回声")
                    else:
                        logger.warning("[CallAgent] ⚠️ AI 音色指纹建立失败，将退化为实时波形互相关模式")

                    # 只要当前通话处于接通中，立即向电话输出端推流播放问候语，确保对面第一时间听到声音
                    if self._running and getattr(self.voip_watcher, "state", "") == "IN_PROGRESS":
                        if not getattr(self.audio_router, "_running", False):
                            self.audio_router.start()
                        self._recent_ai_utterances.append((greeting_text, time.time()))
                        self.emit_event("ai_sentence", {"sentence": greeting_text})
                        logger.info(f"[CallAgent] 🔊 电话接通主动向微信注入问候: 「{greeting_text}」")
                        self.audio_router.play_audio(pcm_bytes, orig_rate=sample_rate)
                        if getattr(self, "video_router", None) and self.video_router.is_running:
                            self.video_router.put_audio(pcm_bytes, sample_rate=sample_rate)
                        self._last_ai_speech_end_time = time.time()
                else:
                    logger.warning(f"[CallAgent] ⚠️ TTS 合成问候音频失败或过短 ({len(pcm_bytes) if pcm_bytes else 0} bytes)")
            except Exception as e:
                logger.error(f"[CallAgent] AI 音色指纹与开场问候异常: {e}", exc_info=True)

        t = threading.Thread(target=_build, daemon=True, name="ai-voice-fingerprint-builder")
        t.start()

    T2S_MAP = str.maketrans({
        '個': '个', '劇': '剧', '數': '数', '據': '据', '備': '备', '說': '说', '話': '话',
        '這': '这', '點': '点', '麼': '么', '樣': '样', '來': '来', '為': '为', '與': '与',
        '時': '时', '隨': '随', '聽': '听', '聲': '声', '嗎': '吗', '會': '会', '學': '学',
        '還': '还', '幫': '帮', '寫': '写', '碼': '码', '創': '创', '意': '意', '練': '练',
        '試': '试', '塊': '块', '題': '题', '問': '问', '後': '后', '端': '端', '錯': '错',
        '總': '总', '報': '报', '真': '真', '順': '顺', '序': '序', '走': '走', '聖': '圣',
        '誕': '诞', '節': '节', '萬': '万', '員': '员', '頁': '页', '夜': '页', '八': '8'
    })

    @classmethod
    def _normalize_echo_text(cls, text: str) -> str:
        """规范化繁简、标点与数字表达"""
        t = re.sub(r'[\s，。？！、\.\?!,\-_:：\"\'“”‘’\(\)（）]', '', text).lower()
        t = t.translate(cls.T2S_MAP)
        t = t.replace("18", "8").replace("十八", "8")
        return t

    def _is_ai_echo(self, text: str) -> bool:
        """判断转写文本是否属于 AI 自身声音经由扬声器/虚拟声卡回流产生的回音"""
        if not getattr(self.config.voip, "echo_cancellation_enabled", True):
            return False

        clean_t = self._normalize_echo_text(text)
        if len(clean_t) < 2:
            return False

        now = time.time()
        for ai_text, t_stamp in list(self._recent_ai_utterances):
            # 仅比对近 15 秒内 AI 发音过的子句
            if now - t_stamp > 15.0:
                continue

            clean_ai = self._normalize_echo_text(ai_text)
            if not clean_ai:
                continue

            # 1. 直接子串匹配: 转写文本是 AI 句子的字面子串或超集
            if clean_t in clean_ai or (clean_ai in clean_t and len(clean_ai) >= 3):
                logger.warning(f"[CallAgent] 🛡️ 拦截过滤 AI 自发音回声子串: 「{text}」 (源于 AI 发音: 「{ai_text}」)")
                return True

            # 2. 相似度检测 (Levenshtein / SequenceMatcher ratio >= 0.55)
            ratio = difflib.SequenceMatcher(None, clean_t, clean_ai).ratio()
            if ratio >= 0.55 and min(len(clean_t), len(clean_ai)) >= 3:
                logger.warning(f"[CallAgent] 🛡️ 拦截过滤 AI 相似发音回声: 「{text}」 (相似度={ratio:.2f}, 源于: 「{ai_text}」)")
                return True

            # 3. 字符覆盖率/交集比对 (针对繁简转换、同音错字与 Whisper 识别误差)
            set_ai = set(clean_ai)
            set_tr = set(clean_t)
            if len(set_tr) >= 3:
                common = set_ai & set_tr
                overlap = len(common) / len(set_tr)
                # 若转写内容与 AI 近期发音高度重合 (>=48% 且至少5字相同，或至少9字重合)，且时间间隔在 12 秒内
                if ((overlap >= 0.48 and len(common) >= 5) or len(common) >= 9) and (now - t_stamp <= 12.0):
                    logger.warning(f"[CallAgent] 🛡️ 拦截过滤 AI 字符高重合回声: 「{text}」 (覆盖度={overlap:.2f}, 相同字数={len(common)}, 源于: 「{ai_text}」)")
                    return True

        return False

    def _on_caller_transcription(self, text: str):
        """对方说完了话，转写完成 -> 校验回声后推送给大模型思考"""
        if self._is_ai_echo(text):
            logger.info(f"[CallAgent] 对方说话转写文本判定为 AI 扬声器回音，已安全忽略: 「{text}」")
            return

        # 对方发话成功确认，废弃旧轮次代号与流水线残留
        self._current_gen_id += 1
        self._current_sentence_seq = 0
        self._next_play_seq = 0
        with self._tts_results_lock:
            self._tts_results.clear()
        self._tts_dispatch_event.set()

        logger.info(f"[CallAgent] 👤 确认对面真实用户发话: 「{text}」 -> 触发大模型思考回复")
        self.emit_event("caller_transcript", {"text": text})
        self.dialogue_engine.on_user_speech(text)

    def _on_ai_sentence_ready(self, sentence: str):
        """大模型生成了一个完整句子 -> 提交多线程流水线并发预合成"""
        self._recent_ai_utterances.append((sentence, time.time()))
        self.emit_event("ai_sentence", {"sentence": sentence})
        gen_id = self._current_gen_id
        seq = self._current_sentence_seq
        self._current_sentence_seq += 1
        logger.info(f"[CallAgent] 流式提交并发合成: 「{sentence}」 (代号={gen_id}, 序号={seq})")
        self._tts_executor.submit(self._async_synthesize_task, gen_id, seq, sentence)

    def _async_synthesize_task(self, gen_id: int, seq: int, sentence: str):
        """后台异步并发 TTS 任务 (各句子并发拉取，前序播放时后序已在内存等待)"""
        if gen_id != self._current_gen_id or not self._running:
            return

        with self._synth_count_lock:
            self._active_synth_count += 1
        try:
            pcm_bytes, rate = self.tts_manager.synthesize(sentence)
            if gen_id == self._current_gen_id and self._running and pcm_bytes:
                with self._tts_results_lock:
                    self._tts_results[seq] = (pcm_bytes, rate, sentence)
                self._tts_dispatch_event.set()
            else:
                logger.debug(f"[CallAgent] 丢弃已过期并发合成结果 (seq={seq}): 「{sentence}」")
        except Exception as e:
            logger.error(f"[CallAgent] 并发 TTS 合成异常 (seq={seq}): {e}")
        finally:
            with self._synth_count_lock:
                self._active_synth_count = max(0, self._active_synth_count - 1)

    def _tts_dispatcher_loop(self):
        """有序流水线分发器：按原始语义序号保序推送到 AudioRouter，实现无缝连续播音"""
        while self._running:
            self._tts_dispatch_event.wait(timeout=0.5)
            self._tts_dispatch_event.clear()

            while self._running:
                ready_item = None
                with self._tts_results_lock:
                    if self._next_play_seq in self._tts_results:
                        ready_item = self._tts_results.pop(self._next_play_seq)
                        cur_seq = self._next_play_seq
                        self._next_play_seq += 1

                if ready_item is None:
                    break

                pcm_bytes, rate, sentence = ready_item
                if pcm_bytes and self._running:
                    if not getattr(self.audio_router, "_running", False) and getattr(self.voip_watcher, "state", "") == "IN_PROGRESS":
                        logger.warning("[CallAgent] 通话进行中但音频路由处于停止态，自动恢复启动音频路由...")
                        self.audio_router.start()
                    logger.info(f"[CallAgent] 🔊 向微信声卡注入语音(流水线就绪): 「{sentence}」 (序号={cur_seq}, 长度={len(pcm_bytes)}字节, 采样率={rate})")
                    self.audio_router.play_audio(pcm_bytes, orig_rate=rate)
                    if getattr(self, "video_router", None) and self.video_router.is_running:
                        self.video_router.put_audio(pcm_bytes, sample_rate=rate)
                    self._last_ai_speech_end_time = time.time()

    def _on_ai_reply_finished(self, full_reply: str):
        """大模型完整回复完毕"""
        self.emit_event("ai_reply_complete", {"reply": full_reply})

    def _on_call_ended(self, caller_name: str, duration_sec: float):
        """通话结束事件"""
        logger.info(f"[CallAgent] 通话结束: 好友={caller_name}, 时长={int(duration_sec)}秒")
        self.emit_event("call_ended", {"caller": caller_name, "duration": duration_sec})

        # 停止音频流与 STT，清空声学分类器与状态
        self._is_synthesizing_tts = False
        self._last_ai_speech_end_time = 0.0
        self.acoustic_classifier.clear()
        self.audio_router.stop()
        if getattr(self, "video_router", None):
            self.video_router.stop()
        self.stt_worker.stop()
        self.dialogue_engine.cancel()
        self._recent_ai_utterances.clear()
