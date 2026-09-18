# -*- coding: utf-8 -*-
"""基于声波波形与音调基频的声学说话人判别器 (agent_core.voice_call.acoustic_classifier)

判别策略分为两层，优先级从高到低：

【第一层：预建立 AI 音色指纹 (Proactive Fingerprint)】
  - 通话接通时，调用 build_voice_fingerprint(pcm_bytes, sample_rate) 用真实的 TTS 合成
    音频（或克隆音色音频）提前建立 AI 的声学特征指纹：
      · 基频 F0 中位数 (fundamental frequency)
      · 频谱质心 (spectral centroid) 中位数
      · 梅尔倒谱系数 MFCC 均值向量 (13维)
  - 不依赖播音时序，能在 AI 第一句话甚至还没说出口时就识别。

【第二层：实时参考声波互相关 (Reactive Cross-Correlation)】
  - AI 播音时注入参考声波样本 (put_reference_audio)
  - 对录音做 FFT 滑动互相关，高度相关 (>=0.45) 则判为 AI 回声。
  - 作为第一层的补充，对轻微失真的回声同样有效。

两层任一触发即判定为 AI 声音，从底层物理阻断录音进入 Whisper。
"""
from __future__ import annotations

import time
import logging
import threading
import collections
import numpy as np
import scipy.signal
from typing import Tuple, Optional, List

logger = logging.getLogger("AcousticClassifier")


class AcousticClassifier:
    """声学说话人判别器：双层策略（预建立音色指纹 + 实时波形互相关）"""

    def __init__(
        self,
        sample_rate: int = 16000,
        max_reference_sec: float = 6.0,
        correlation_threshold: float = 0.45,
    ):
        self.sample_rate = sample_rate
        self.max_reference_sec = max_reference_sec
        self.correlation_threshold = correlation_threshold

        self._lock = threading.Lock()

        # --- 第一层：预建立 AI 音色指纹 ---
        self._fp_ready: bool = False
        self._fp_f0_median: float = 0.0
        self._fp_spectral_centroid: float = 0.0
        self._fp_mfcc_mean: Optional[np.ndarray] = None
        self._fp_rms: float = 0.0

        # --- 第二层：实时参考声波互相关 ---
        self._reference_buffer = collections.deque(maxlen=int(self.sample_rate * self.max_reference_sec))
        self._last_ref_put_time = 0.0
        self._ai_pitch_history: collections.deque = collections.deque(maxlen=20)
        self._current_ai_pitch: float = 0.0

    # =========================================================================
    # 第一层：预建立 AI 音色指纹
    # =========================================================================

    def build_voice_fingerprint(self, pcm_bytes: bytes, orig_rate: int = 24000) -> bool:
        """
        通话接通前，用 TTS 合成的短语音（或克隆音色参考音频）预建立 AI 音色指纹。
        调用时机：_on_call_answered 中，在 audio_router.start() 之前调用。
        """
        if not pcm_bytes or len(pcm_bytes) < 3200:
            logger.warning("[AcousticClassifier] 预建指纹音频过短，跳过")
            return False

        try:
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if orig_rate != self.sample_rate:
                num_target = int(len(samples) * self.sample_rate / orig_rate)
                samples = scipy.signal.resample(samples, num_target)

            # 去静音段：只保留 RMS > 0.01 的语音帧
            frame_len = 512
            voiced = []
            for i in range(0, len(samples) - frame_len, frame_len):
                frame = samples[i:i + frame_len]
                if np.sqrt(np.mean(frame ** 2)) > 0.01:
                    voiced.append(frame)

            if len(voiced) < 5:
                logger.warning("[AcousticClassifier] 有效语音帧过少，指纹建立失败")
                return False

            voiced_samples = np.concatenate(voiced)

            # 1. 基频 F0 序列
            f0_values = []
            hop = 1600
            win = 3200
            for i in range(0, len(voiced_samples) - win, hop):
                f0 = self._estimate_pitch(voiced_samples[i:i + win], self.sample_rate)
                if f0 > 60.0:
                    f0_values.append(f0)
            fp_f0 = float(np.median(f0_values)) if f0_values else 0.0

            # 2. 频谱质心
            centroid_values = []
            for i in range(0, len(voiced_samples) - win, hop):
                c = self._spectral_centroid(voiced_samples[i:i + win], self.sample_rate)
                if c > 0:
                    centroid_values.append(c)
            fp_centroid = float(np.median(centroid_values)) if centroid_values else 0.0

            # 3. MFCC 均值向量（13维）
            fp_mfcc = self._compute_mfcc_mean(voiced_samples, self.sample_rate, n_mfcc=13)

            # 4. RMS 整体能量
            fp_rms = float(np.sqrt(np.mean(voiced_samples ** 2)))

            with self._lock:
                self._fp_f0_median = fp_f0
                self._fp_spectral_centroid = fp_centroid
                self._fp_mfcc_mean = fp_mfcc
                self._fp_rms = fp_rms
                self._fp_ready = True
                # 同时注入实时参考缓冲，增强第二层覆盖
                self._reference_buffer.extend(voiced_samples)
                self._last_ref_put_time = time.time()

            logger.info(
                f"[AcousticClassifier] ✅ AI 音色指纹建立完成 | "
                f"F0={fp_f0:.1f}Hz  质心={fp_centroid:.0f}Hz  "
                f"MFCC范数={np.linalg.norm(fp_mfcc):.2f}  RMS={fp_rms:.4f}"
            )
            return True

        except Exception as e:
            logger.error(f"[AcousticClassifier] 建立音色指纹失败: {e}", exc_info=True)
            return False

    @staticmethod
    def _spectral_centroid(samples: np.ndarray, sample_rate: int) -> float:
        """计算频谱质心 (Hz)"""
        try:
            s = samples - np.mean(samples)
            if np.max(np.abs(s)) < 1e-5:
                return 0.0
            mag = np.abs(np.fft.rfft(s))
            freqs = np.fft.rfftfreq(len(s), 1.0 / sample_rate)
            total = np.sum(mag)
            if total < 1e-9:
                return 0.0
            return float(np.sum(freqs * mag) / total)
        except Exception:
            return 0.0

    @staticmethod
    def _compute_mfcc_mean(samples: np.ndarray, sample_rate: int, n_mfcc: int = 13) -> np.ndarray:
        """轻量 MFCC 均值（纯 numpy/scipy，无需 librosa）"""
        try:
            n_fft = 512
            hop = 160
            n_mels = 40
            fmin, fmax = 80.0, float(sample_rate // 2)

            frames = []
            window = np.hanning(n_fft)
            for i in range(0, len(samples) - n_fft, hop):
                frames.append(samples[i:i + n_fft] * window)
            if not frames:
                return np.zeros(n_mfcc)

            spec = np.abs(np.fft.rfft(np.array(frames), n=n_fft)) ** 2

            mel_min = 2595.0 * np.log10(1.0 + fmin / 700.0)
            mel_max = 2595.0 * np.log10(1.0 + fmax / 700.0)
            mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
            hz_points = 700.0 * (10.0 ** (mel_points / 2595.0) - 1.0)
            bin_points = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)
            bin_points = np.clip(bin_points, 0, spec.shape[1] - 1)

            mel_fb = np.zeros((n_mels, spec.shape[1]))
            for m in range(1, n_mels + 1):
                f_m_minus = bin_points[m - 1]
                f_m = bin_points[m]
                f_m_plus = bin_points[m + 1]
                for k in range(f_m_minus, f_m):
                    if f_m != f_m_minus:
                        mel_fb[m - 1, k] = (k - f_m_minus) / (f_m - f_m_minus)
                for k in range(f_m, f_m_plus):
                    if f_m_plus != f_m:
                        mel_fb[m - 1, k] = (f_m_plus - k) / (f_m_plus - f_m)

            mel_energy = np.dot(spec, mel_fb.T)
            mel_energy = np.where(mel_energy > 1e-9, mel_energy, 1e-9)
            log_mel = np.log(mel_energy)

            n = np.arange(n_mels)
            k = np.arange(1, n_mfcc + 1)
            dct_matrix = np.cos(np.pi * k[:, None] * (2 * n[None, :] + 1) / (2 * n_mels))
            mfcc = np.dot(log_mel, dct_matrix.T)
            return mfcc.mean(axis=0)

        except Exception as e:
            logger.debug(f"[AcousticClassifier] MFCC 计算异常: {e}")
            return np.zeros(n_mfcc)

    def _match_fingerprint(self, samples: np.ndarray) -> Tuple[bool, str]:
        """用预建立的 AI 音色指纹与录音段做多维特征匹配"""
        with self._lock:
            if not self._fp_ready:
                return False, "指纹未就绪"
            fp_f0 = self._fp_f0_median
            fp_centroid = self._fp_spectral_centroid
            fp_mfcc = self._fp_mfcc_mean
            fp_rms = self._fp_rms

        rec_f0 = self._estimate_pitch(samples, self.sample_rate)
        rec_centroid = self._spectral_centroid(samples, self.sample_rate)
        rec_mfcc = self._compute_mfcc_mean(samples, self.sample_rate, n_mfcc=13)
        rec_rms = float(np.sqrt(np.mean(samples ** 2)))

        hits = 0
        details: List[str] = []

        # 1. F0 基频匹配
        if fp_f0 > 60.0 and rec_f0 > 60.0:
            diff = abs(rec_f0 - fp_f0)
            if diff <= 20.0:
                hits += 1
                details.append(f"F0匹配(Δ={diff:.0f}Hz)")
            else:
                details.append(f"F0不符(Δ={diff:.0f}Hz)")
        else:
            details.append("F0不可用")

        # 2. 频谱质心匹配
        if fp_centroid > 100.0 and rec_centroid > 100.0:
            rel_diff = abs(rec_centroid - fp_centroid) / max(fp_centroid, 1.0)
            if rel_diff < 0.18:
                hits += 1
                details.append(f"质心匹配(Δ={rel_diff*100:.0f}%)")
            else:
                details.append(f"质心不符(Δ={rel_diff*100:.0f}%)")

        # 3. MFCC 余弦相似度（权重最高，命中+2）
        if fp_mfcc is not None and fp_mfcc.shape == rec_mfcc.shape:
            norm_fp = np.linalg.norm(fp_mfcc)
            norm_rec = np.linalg.norm(rec_mfcc)
            if norm_fp > 1e-6 and norm_rec > 1e-6:
                cosine = float(np.dot(fp_mfcc, rec_mfcc) / (norm_fp * norm_rec))
                if cosine >= 0.82:
                    hits += 2
                    details.append(f"MFCC匹配(cos={cosine:.2f})")
                elif cosine >= 0.70:
                    hits += 1
                    details.append(f"MFCC弱匹配(cos={cosine:.2f})")
                else:
                    details.append(f"MFCC不符(cos={cosine:.2f})")

        # 4. 能量过低 → 环境噪音，放行
        if fp_rms > 0 and rec_rms < fp_rms * 0.05:
            return False, f"录音能量过低(rec_rms={rec_rms:.4f})"

        # 满分 4 分，>=3 分判为 AI 音色
        reason = f"指纹评分={hits}/4 [{', '.join(details)}]"
        return (hits >= 3), reason

    # =========================================================================
    # 第二层辅助：实时参考声波互相关
    # =========================================================================

    def clear(self):
        """清空全部状态（通话结束时调用）"""
        with self._lock:
            self._reference_buffer.clear()
            self._ai_pitch_history.clear()
            self._current_ai_pitch = 0.0
            self._last_ref_put_time = 0.0
            self._fp_ready = False
            self._fp_f0_median = 0.0
            self._fp_spectral_centroid = 0.0
            self._fp_mfcc_mean = None
            self._fp_rms = 0.0

    def reset_timer_only(self):
        """仅重置最后参考注入时间（软打断：保留波形与指纹，继续拦截残响）"""
        with self._lock:
            self._last_ref_put_time = time.time()

    def clear_reference_only(self):
        """打断后清空实时参考声波缓冲和时间戳（保留 AI 音色指纹以备下次通话复用）。
        AI 已被打断停止发音，不再需要实时声波匹配；同时将指纹有效时间窗置为 0
        确保指纹层不在 AI 停止后继续误判用户人声。"""
        with self._lock:
            self._reference_buffer.clear()
            self._last_ref_put_time = 0.0  # 置 0 确保互相关层不再拦截

    def put_reference_audio(self, pcm_bytes: bytes, orig_rate: int = 16000):
        """接收 AI 实际向声卡推流播放的原始 PCM 声波数据作为实时比对基准"""
        if not pcm_bytes:
            return
        try:
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if orig_rate != self.sample_rate and len(samples) > 0:
                num_target = int(len(samples) * self.sample_rate / orig_rate)
                samples = scipy.signal.resample(samples, num_target)

            now = time.time()
            pitch = self._estimate_pitch(samples, self.sample_rate)

            with self._lock:
                self._reference_buffer.extend(samples)
                self._last_ref_put_time = now
                if pitch > 50.0:
                    self._ai_pitch_history.append(pitch)
                    self._current_ai_pitch = float(np.median(self._ai_pitch_history))
                    # EMA 平滑更新指纹 F0
                    if self._fp_ready:
                        self._fp_f0_median = 0.9 * self._fp_f0_median + 0.1 * pitch
        except Exception as e:
            logger.debug(f"[AcousticClassifier] 注入参考声波异常: {e}")

    @staticmethod
    def _estimate_pitch(samples: np.ndarray, sample_rate: int = 16000,
                        fmin: float = 65.0, fmax: float = 380.0) -> float:
        """基于归一化自相关 (ACF) 快速估算音频段的主音调基频"""
        if len(samples) < int(sample_rate / fmin):
            return 0.0
        try:
            s = samples - np.mean(samples)
            if np.max(np.abs(s)) < 1e-4:
                return 0.0
            corr = scipy.signal.correlate(s, s, mode='full')
            corr = corr[len(corr) // 2:]
            min_lag = int(sample_rate / fmax)
            max_lag = int(sample_rate / fmin)
            if max_lag >= len(corr):
                max_lag = len(corr) - 1
            if min_lag >= max_lag:
                return 0.0
            search_slice = corr[min_lag:max_lag]
            if len(search_slice) == 0:
                return 0.0
            peak_lag = min_lag + int(np.argmax(search_slice))
            if corr[0] > 0 and (corr[peak_lag] / corr[0]) >= 0.25:
                return float(sample_rate / peak_lag)
        except Exception:
            pass
        return 0.0

    def compute_waveform_correlation(self, rec_samples: np.ndarray) -> float:
        """计算录音声波与 AI 最近播出的参考声波之间的最大归一化互相关系数"""
        with self._lock:
            if len(self._reference_buffer) < 800 or len(rec_samples) < 800:
                return 0.0
            ref_array = np.array(self._reference_buffer, dtype=np.float32)
        try:
            s_rec = rec_samples.astype(np.float32)
            s_ref = ref_array
            rec_std = np.std(s_rec)
            ref_std = np.std(s_ref)
            if rec_std < 1e-6 or ref_std < 1e-6:
                return 0.0
            s_rec = (s_rec - np.mean(s_rec)) / rec_std
            s_ref = (s_ref - np.mean(s_ref)) / ref_std
            ds_step = max(1, len(s_rec) // 512)
            s_rec_ds = s_rec[::ds_step]
            s_ref_ds = s_ref[::ds_step]
            n_rec_ds = len(s_rec_ds)
            corr = scipy.signal.fftconvolve(s_ref_ds, s_rec_ds[::-1], mode='valid')
            if len(corr) == 0:
                return 0.0
            return max(0.0, float(np.max(corr)) / float(n_rec_ds))
        except Exception as e:
            logger.debug(f"[AcousticClassifier] 计算声波互相关异常: {e}")
            return 0.0

    # =========================================================================
    # 核心判别接口
    # =========================================================================

    def classify(self, pcm_bytes: bytes, rate: int = 16000) -> Tuple[bool, float, float, float, str]:
        """
        双层声学判别接口：
        返回 (is_ai_voice, correlation, rec_pitch, ai_pitch, reason)
        """
        if not pcm_bytes:
            return False, 0.0, 0.0, 0.0, "无音频"

        try:
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if rate != self.sample_rate and len(samples) > 0:
                num_target = int(len(samples) * self.sample_rate / rate)
                samples = scipy.signal.resample(samples, num_target)

            rec_pitch = self._estimate_pitch(samples, self.sample_rate)

            with self._lock:
                time_since_ref = time.time() - self._last_ref_put_time
                ai_pitch = self._current_ai_pitch
                ref_len = len(self._reference_buffer)
                fp_ready = self._fp_ready

            # --- 第一层：预建立音色指纹（随时可判，无需播音时序） ---
            if fp_ready:
                is_ai_fp, fp_reason = self._match_fingerprint(samples)
                if is_ai_fp:
                    # 安全守护：若 AI 已停止发音超过 2 秒，即使指纹匹配也放行用户语音
                    # 防止打断后旧指纹永久误判用户语音导致对话永久卡死
                    if time_since_ref > 2.0:
                        logger.debug(f"[AcousticClassifier] 指纹匹配但 AI 已停止发音 {time_since_ref:.1f}s 前，放行用户语音")
                    else:
                        logger.debug(f"[AcousticClassifier] 🚫 指纹层命中: {fp_reason}")
                        return True, 0.0, rec_pitch, ai_pitch, f"[指纹层] {fp_reason}"

            # --- 第二层：实时声波互相关（AI 播音后补充兜底） ---
            if time_since_ref <= 8.0 and ref_len >= 800:
                corr = self.compute_waveform_correlation(samples)

                if corr >= self.correlation_threshold:
                    return True, corr, rec_pitch, ai_pitch, \
                        f"[互相关层] 声波高度吻合(corr={corr:.2f})"

                if time_since_ref <= 2.5 and ai_pitch > 60.0 and rec_pitch > 60.0:
                    pitch_diff = abs(rec_pitch - ai_pitch)
                    if pitch_diff <= 15.0 and corr >= 0.28:
                        return True, corr, rec_pitch, ai_pitch, \
                            f"[互相关层] 残响期音调一致(Δ={pitch_diff:.0f}Hz,corr={corr:.2f})"

                return False, corr, rec_pitch, ai_pitch, \
                    f"[互相关层] 声波独立(corr={corr:.2f},rec_pitch={rec_pitch:.1f}Hz)"

            return False, 0.0, rec_pitch, ai_pitch, \
                f"[放行] 指纹未命中且无有效参考(time_since_ref={time_since_ref:.1f}s)"

        except Exception as e:
            logger.error(f"[AcousticClassifier] 声学分类异常: {e}", exc_info=True)
            return False, 0.0, 0.0, 0.0, f"异常: {e}"
