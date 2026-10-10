# 🤖 WeChat-AIAgent · 微信 4.x 全功能 AI 智能助理

<div align="center">

> **专为微信 4.x Windows 客户端打造的个人 AI 智能助理**  
> 集成 **本地原生桌面 GUI (现代竖向导航)** · **多主流大模型 (LLM)** · **联系人专属立体画像与永久记忆 (Memory Engine)** · **本地私有知识库 (BM25 RAG)** · **📞 微信语音/视频电话自动接听与全双工实时 AI 对话 (VoIP & Video Agent)** · **📹 本地虚拟数字人多引擎实时推流 (LivePortrait / Wav2Lip-GAN / MuseTalk)** · **阿里 FunASR Paraformer 毫秒级口语识别 / Faster-Whisper** · **Kokoro-82M 超轻量超自然实时 TTS / Qwen3-TTS / Edge-TTS** · **多模态视觉与 OCR 解析** · **群管与自动踢人**

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue.svg)](https://microsoft.com/windows)
[![WeChat](https://img.shields.io/badge/WeChat-4.x%20(4.1.12%2B)-brightgreen.svg)](https://weixin.qq.com)
[![Python](https://img.shields.io/badge/Python-3.9%20~%203.12-blue.svg)](https://python.org)
[![FunASR](https://img.shields.io/badge/ASR-FunASR%20Paraformer-red.svg)](https://github.com/modelscope/FunASR)
[![Kokoro-82M](https://img.shields.io/badge/TTS-Kokoro--82M%20(Realtime)-blueviolet.svg)](https://github.com/hexgrad/kokoro)
[![Wav2Lip](https://img.shields.io/badge/Avatar-Wav2Lip--GAN%20%2F%20LivePortrait-orange.svg)](https://github.com/Rudrabha/Wav2Lip)
[![CUDA](https://img.shields.io/badge/CUDA-12.4%20%2F%20RTX%203060%2B-76B900.svg)](https://developer.nvidia.com/cuda-zone)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## 📖 项目简介

本项目底层自动化引擎深度衍生并重构自开源项目 [wechatauto-replica](https://github.com/fanyuantaier/wechatauto-replica)，突破了经典 wxauto 库因微信 4.x 换用自绘渲染引擎导致 UI 自动化树失效的限制，创新实现：

1. **本地内存解密**：从微信 4.x 进程提取密钥，无侵入解密 `contact.db`、`message_*.db`（SQLCipher 4），实现高速消息监听与会话捕获；
2. **混合发信驱动引擎**：结合 Qt 内存可访问性热激活、UIAutomation 与 WinRT OCR 屏幕文字定位技术，实现高稳定自动打字、发信与群成员管理。

在此基础上完成**全面产品级演进与智能化升级**：
- 沉浸式**原生桌面 GUI**（左侧垂直深色导航侧边栏 + 右侧功能面板现代化布局）；
- 完整 **AI Agent 决策管道**与**会话级多轮上下文记忆**；
- **联系人专属立体画像与永久记忆库**（Memory Engine）；
- **本地私有 BM25 检索增强知识库**（RAG）；
- 🆕 **微信语音/视频电话自动接听 + 实时全双工 AI 对话**（VoIP & Video Agent）：
  - 接入阿里 **FunASR Paraformer** 毫秒级非自回归中文口语识别模型（出字延迟 150~300ms）；
  - 引入 **Kokoro-82M** 超轻量实时发音引擎（RTF < 0.2）与 **Qwen3-TTS** 智能降级保护；
  - 接通瞬发礼貌问候、双层声学指纹消除 AI 自发音误打断、全链路自适应动态音量增益；
- 📹 **全矩阵虚拟数字人实时驱动与虚拟摄像头直推 (Digital Human Engine)**：
  - **多引擎无缝切换**：FasterLivePortrait ONNX 神经隐空间微表情重定向、**Wav2Lip-GAN 极速口型驱动 (35~50 FPS)**、MuseTalk 高质量扩散修复与零模型依赖拟真保底引擎；
  - **独创高保真唇红缘遮罩**：人中与下巴硬边界三向衰减保护，彻底根除 96 尺度插值导致的“融化发糊”边缘，100% 保持原生皮肤毛孔质感；
  - **真实物理摄像头动作驱动 (Webcam Tracker)**：自动探测并枚举本机真实摄像头硬件名称，支持真实视频画面作为动作源直接驱动数字人；
  - **DirectShow 零侵入虚拟推流**：标准 640x480 输出与智能等比自适应背景扩展，启动预充防绿屏，完美兼容微信 4.x 视频通话；
- **双模态语音转写**（阿里 FunASR / Faster-Whisper / 云端 ASR）；
- **多模态视觉大模型 + WinRT OCR** 图片综合理解；
- 全量内置**绿色便携 Python 运行时 (runtime)**，开箱即用。

---

## ✨ 核心功能全览

### 1. 🎛️ 现代原生桌面 GUI (竖向排列布局)

- **左侧深色垂直功能侧边栏**：告别顶部横向标签容易出现的文字截断与挤压，支持选中高亮微动效与鼠标悬浮响应，直观高效；
- **8 大核心功能面板**：

| 面板 | 功能说明 |
| :--- | :--- |
| 📊 **运行看板与实时日志** | 今日接收 / 自动回复 / 规则过滤三大指标卡，彩色实时日志流 |
| 👥 **回复对象与群管配置** | 联系人/群聊白名单精准勾选，群管理员授权，`@用户 踢` 自动踢人拉黑 |
| 🧠 **大模型接口配置** | 兼容 DeepSeek、OpenAI、通义千问等所有 OpenAI 规范 API，一键拉取模型，连通性测试 |
| 📚 **本地私有知识库 (RAG)** | BM25 稀疏检索切片，支持 `.txt` `.md` `.pdf` `.docx` `.csv`，磁盘索引缓存秒启 |
| 👤 **用户画像与永久记忆** | 联系人立体画像，增量自完善与认知纠偏，事实记忆碎片，历史记录全量建档 |
| 🎙️ **多模态与媒体设置** | 语音 ASR 引擎切换（FunASR / Whisper / 云端），缺模型自动唤起极速镜像下载，视觉/OCR 解析 |
| 📞 **音视频电话与虚拟数字人 (VoIP & Avatar)** | 微信语音/视频来电自动接听，本地虚拟数字人摄像头直推，LivePortrait / MuseTalk 双引擎运行时切换，ComfyUI 立绘联动，全双工音画同步 |
| 🧪 **交互测试沙盒** | 模拟消息输入，无缝测试 RAG 命中、画像记忆注入与 AI 回复效果 |

---

### 2. 📞 微信语音电话守护 (VoIP Agent) — 全新重磅升级

> 微信语音来电 → 毫秒级自动探测 → 物理鼠标精准点击接听 → 即刻礼貌开场问候 → 实时全双工双向语音对话。全程由 AI 接管，顺畅自然无冷场！

#### 完整技术架构

```
微信来电弹窗 (mmui::VOIPTrayWindow)
    │
    ▼
VoIPWatcher (Win32 + UIAutomation 毫秒级探测)
    │  白名单过滤 → 几何精确推算 (接听键=右侧86%) → 物理模拟鼠标点击
    ▼
AudioRouter (虚拟声卡双工音频路由 · VB-Audio CABLE)
    │  输入流: 对方语音 → STTWorker
    │  输出流: AI 合成语音 → 动态峰值保真增益 (0.88) → 注入微信麦克风
    ▼
STTWorker (阿里 FunASR Paraformer 毫秒级流式转写 / Faster-Whisper + Silero VAD)
    │  声学回声消除 (AcousticClassifier: F0基频 + MFCC + 频谱质心 + 波形互相关)
    │  防自发音误打断判定 (AI 正在播音时先行校验声学指纹，严禁掐断自身发音)
    ▼
DialogueEngine (大模型流式对话引擎)
    │  联系人画像与长期事实记忆注入 · 实时多轮上下文管理
    ▼
TTSManager (Kokoro-82M / Edge-TTS / Qwen3-TTS / 声音克隆)
    │  接通瞬间即刻推流开场问候 · 防卡死保底降级 · Generation ID 打断撤销机制
    ▼
AudioRouter.play_audio() → 动态音量归一化 → 推流至虚拟声卡注入微信
```

#### 核心技术亮点
- 🚀 **阿里 FunASR Paraformer 毫秒级流式 ASR**：针对中文口语深度优化，非自回归结构，出字延迟仅 150~300ms，显存占用远低于 Whisper，对方刚落音瞬间即可出字送入 LLM；
- ⚡ **即刻开场礼貌问候**：电话接通瞬间立即由 AI 异步合成并推流开场白（“喂，你好！我是微信电话助理，请问有什么可以帮您？”），彻底解决接通后的死寂冷场；
- 🛡️ **声学指纹防自打断 (Anti-Barge-in Misfire)**：预建 AI 音色声学指纹（F0 基频、MFCC 倒谱、频谱质心）并结合实时互相关校验。在 AI 发音期间若录到声学回声，先行判定为自身发音并过滤，彻底杜绝发音瞬间自我掐断的顽疾；
- 🔊 **全链路动态音量保真增益**：微信客户端具有激进的自适应降噪与 AGC，若声音微弱会被微信误判为底噪而静音。AudioRouter 引入峰值 0.88 自适应保真增益归一化与防爆音限制器，确保对方听到的 AI 声音清晰饱满；
- 🎙️ **超轻量 Kokoro-82M + Qwen3-TTS 保底守护**：
  - **Kokoro-82M**：参数量仅 82M，纯 CPU / 多线程推流极速（RTF < 0.2），音质自然纯净；
  - **Qwen3-TTS**：具备上下文韵律理解，结合 GGML/PyTorch 守护与防死寂超时自动回退机制；
  - **Edge-TTS / 声音克隆**：多种真人音色与音色克隆一键切换；
- 🔍 **精准无感接听**：多层 Win32/UIA 探测微信 4.x `mmui::VOIPTrayWindow` 弹窗，严格按几何推算坐标物理点击，杜绝误触挂断；
- 🛡️ **自动守护与挂断**：支持最大通话时长保护自动挂断、守护线程异常自愈、音频设备热插拔自恢复。

---

### 2.1 📹 微信视频电话接听与本地虚拟数字人接入 (AI Avatar & Webcam Tracker)

> 微信视频来电 → 自动识别视频呼叫 → 物理精准接听 → 激活虚拟摄像头推流 → 本地实时渲染虚拟数字人随 AI 发音实时口型同步 / 本地摄像头动作驱动。

#### 核心技术特性
- 🎬 **DirectShow 虚拟摄像头原生直推**：依托 `pyvirtualcam` 与 UnityCapture / OBS Virtual Camera，以严格的 DirectShow 行业标准 **640x480 @ 25 FPS** 稳定推流。内置智能等比自适应算法（Letterbox + 边缘暗色毛玻璃虚化扩展），1:1 立绘在 4:3 微信窗口中居中无畸变呈现；
- 🛡️ **推流管道预热防绿屏 (Anti-Green-Screen Protection)**：UnityCapture 虚拟摄像头在未初始化共享内存时会输出绿底测试条纹。本项目在推流器启动瞬间自动向 DirectShow 驱动预充 5 帧初始待机帧，彻底杜绝微信接通瞬间闪现绿幕；
- 👥 **全矩阵数字人驱动引擎自由切换**：
  - **Wav2Lip-GAN 极速口型引擎 (强烈推荐)**：
    - 基于 80-band Mel-Spectrogram (梅尔频谱) 细粒度预测发音唇形，在消费级显卡（RTX 3060/4060）上推流帧率高达 **35 ~ 50 FPS**；
    - **独创高精唇红缘遮罩 (Vermilion Border Mask)**：针对传统 Wav2Lip 在 96x96 局部上采样放大造成的“嘴周发糊/融化”缺陷，本项目实施精细化唇红缘几何收敛，并在**人中上方、下唇下方、嘴角两侧**施加严格的三向硬边界衰减截断，**100% 保持立绘原图人中与皮肤毛孔的高清锐度与胡茬纹理**；
    - **肤色动态钳位白平衡**：消除生成图层与原图底层的色偏灰雾，自然融为一体；
  - **LivePortrait-Realtime**：基于 FasterLivePortrait ONNX 隐空间面部表情重定向，毫秒级面部微形变与自然眨眼；
  - **MuseTalk**：基于潜在空间扩散特征的高保真口型修复模型；
  - **自适应拟真视觉动画引擎 (兜底保障)**：零模型权重依赖，自适应人脸特征定位，正弦微呼吸、自然眨眼与 TTS 能量驱动口型开合，保证开箱即用 100% 不崩溃；
- 📷 **真实物理摄像头动作驱动 (Webcam Tracker)**：
  - 通过 DirectShow 原生探测并枚举本机连接的物理摄像头真实设备名称（如 `Web Camera` 等）；
  - 支持通过真实物理摄像头捕获真实用户的面部动态作为输入动作源，直接驱动数字人形象；
  - GUI 面板提供 `🔄` 实时刷新与索引智能绑定，避免设备号混淆；
- 🎨 **正面立绘资产自由定制 + 本地 ComfyUI 一键联动**：
  - 支持用户自由选择本地高分辨率正面人物半身照 (`.png` / `.jpg` / `.webp`)；
  - 集成 `ComfyUIBridge`，在本地运行 ComfyUI (默认 `8188` 端口) 时，点击 GUI 按钮一键抓取 ComfyUI 最新生成的艺术人物立绘并即时应用；
- ⚡ **音画全双工协同与打断即时复位**：
  - TTS 音频推流虚拟声卡的同时，分发一份 PCM 块送入数字人引擎驱动唇型，声画时间戳硬件级同步；
  - 对方说话触发打断 (Barge-in) 时，毫秒级清空唇动缓冲，数字人嘴巴瞬时闭合并切回自然倾听待命状态。

---

### 3. 👤 联系人专属立体画像与永久记忆 (Memory Engine)

- **历史记录全量建档**：从已有聊天记录分析身份定位、性格特质、沟通偏好与核心事实记忆（Fact Memories）；
- **动态增量自完善与认知纠偏**：聊天开始即自动生效，智能体在后续每一轮对话中自发提取新事实，发现信息变更自动更新校准；
- **严格对齐微信命名规范**：界面与索引优先使用好友备注名，无备注显示微信昵称，绝不展示难认的原始 wxid；
- **群聊成员画像独立开关**：群聊成员画像默认关闭，避免浪费算力与存储；可针对核心群聊单独开启；
- **物理强隔离存储**：每个联系人独立存储为 `data/profiles/{safe_id}.json`，互不影响、绝不混淆。

---

### 4. 🤖 智能对话与群聊自动化

- **独立上下文多轮记忆**：每个好友、每个群聊均维持独立的对话历史滑动窗口；
- **群聊管理员与群管指令**：群管理员在群内发送 `@违规用户 踢` 时，智能体自动识别并将其**移出群聊并加入黑名单**；
- **私有知识优先回复**：收到消息后优先在本地 RAG 知识库中进行 BM25 检索，命中高相关切片直接回答，无匹配时由大模型自然发挥；
- **自动防风控与人性化延时**：模拟真人打字间隔与思考延迟，支持后台静默运行。

---

### 5. 🎙️ 语音识别与多模态图片

- **微信语音自动提取与转写**：底层提取加密 SILK 音频转为 WAV，送入本地 `faster-whisper`（支持 GPU CUDA / CPU）或云端 ASR；
- **缺失模型自动引导**：本地缺少模型时，点击测试自动唤起系统浏览器直达国内极速镜像下载页；
- **云端 ASR 一键获取**：支持从上游 API 一键拉取可用模型列表并在下拉栏便捷切换；
- **图片多模态与 OCR**：主流优先调用视觉大模型（如 `qwen-vl-max`, `gpt-4o` 等）理解图意；纯文本自动降级 Windows 原生硬件加速 **WinRT OCR** 离线提取。

---

### 6. 📹 微信视频电话接听与本地 AI 虚拟数字人 (Digital Human Engine)

- **毫秒级视频来电自动探测与接听**：自动区分微信语音通话与视频通话，精准完成接听与音视频链路接驳；
- **双引擎深度驱动架构 (LivePortrait-Realtime & MuseTalk)**：
  - **LivePortrait-Realtime**：基于 FasterLivePortrait ONNX 神经网络，单张正面立绘提取 3D 外观隐空间特征，通过 SPADE 神经形变解码器驱动下颌与唇形开合、眼部眨动及自然呼吸，逼真度高且兼顾极速推流；
  - **MuseTalk**：支持高质量口型同步深度生成模型，可自由在界面下拉菜单中无缝热切换；
- **用户正面立绘即时定制**：支持用户随时上传任意正面照片/二次元角色形象，自动完成五官关键点对齐与隐空间流形预提取；
- **虚拟摄像头免侵入直推**：原生配合轻量级 `UnityCapture`（仅 150KB）或 `OBS Virtual Camera` 驱动，微信客户端直接调用虚拟摄像头画面，无任何注入风险；
- **本地强隔离存储，C 盘 0 字节占用**：LivePortrait 与 MuseTalk 权重全量保存在项目 `models/` 目录下，彻底杜绝系统 C 盘空间膨胀。

---

## 🖥️ 软件界面预览

### 🎙️ 多模态与媒体设置面板 (展示竖向侧边栏与现代布局)
![竖向侧边栏与媒体配置面板](docs/vertical_gui_preview.png)

---

## 🛠️ 环境要求

| 项目 | 要求 | 说明 |
| :--- | :--- | :--- |
| **操作系统** | Windows 10 / Windows 11 (64位) | 推荐 Windows 10 20H2 及以上 / Windows 11 |
| **微信版本** | 微信 4.x Windows 客户端 (`Weixin.exe`) | 实测支持 4.1.12 及以上版本 |
| **登录状态** | 微信必须**已登录**并保持运行 | 本地数据库解密密钥存于进程内存中，请勿锁屏 |
| **Python** | 3.9 ~ 3.12 | 项目已全量内置便携式绿色运行环境，无需自行安装 |
| **虚拟声卡** | VB-Audio CABLE（用于语音电话守护） | 项目内置 `install_vbcable.bat` 一键自动安装 |

---

## 🚀 快速启动

### 方式一：开箱即用（推荐）

本项目已全量内置预配齐所有依赖的绿色便携 Python 运行时环境，无需配置环境变量：

1. **克隆本项目**：
   ```bash
   git clone https://github.com/fj9876/wechat-auto.git
   cd wechat-auto\wechatauto-replica
   ```

2. **安装虚拟声卡（如需语音电话功能）**：
   双击运行 👉 **`install_vbcable.bat`** 一键安装 VB-Audio CABLE 虚拟声卡驱动。

3. **一键启动客户端**：
   双击运行 👉 **`run_ui.bat`**，系统将自动使用内置 `runtime` 环境启动原生桌面 GUI！

### 方式二：自建 Python 虚拟环境（开发者）

```bash
cd wechatauto-replica
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install winsdk faster-whisper tokenizers
python gui_app.py
```

---

## 📋 详细使用步骤

### 第一步：配置大语言模型 (Tab: 🧠 大模型配置)
1. 点击左侧竖向导航【🧠 大模型配置】；
2. 填写 API 地址（如 DeepSeek 官方 `https://api.deepseek.com/v1`、硅基流动或 OpenAI 地址）与对应的 `API Key`；
3. 点击【🔍 一键拉取上游可用模型】或直接在下拉框选择所需模型；
4. 点击【⚡ 测试 API 连通性】，确认成功后点击【💾 保存大模型配置】。

### 第二步：配置回复对象白名单 (Tab: 👥 回复对象配置)
1. 点击左侧【👥 回复对象配置】；
2. 客户端会自动从本地微信数据库读取联系人与群聊列表（自动过滤公众号与服务号）；
3. 勾选需要开启 AI 自动回复的好友或群聊；
4. 如需启用群管指令，在右侧填入「群管理员微信昵称」，即可在群内使用 `@成员 踢` 执行踢人。

### 第三步：配置本地 RAG 知识库 (可选 · Tab: 📚 本地知识库)
1. 点击左侧【📚 本地知识库 (RAG)】并勾选「启用本地知识库检索」；
2. 点击【📂 选择本地文件夹】，选取产品手册或问答文档所在目录；
3. 点击【🔄 立即构建/重置知识库索引】，生成 BM25 稀疏索引与 `.rag_cache.json` 磁盘缓存。

### 第四步：管理用户画像与永久记忆 (Tab: 👤 用户画像)
1. 点击左侧【👤 联系人用户画像】；
2. 点击任意联系人，可查看身份定位、沟通偏好与事实记忆；
3. 点击【🔍 基于已有聊天记录分析/重建画像】可根据历史消息自动建档。

### 第五步：配置多模态与语音 ASR (可选 · Tab: 🎙️ 多模态与媒体设置)
1. 点击左侧【🎙️ 多模态与媒体设置】；
2. **语音识别**：选择 `local (本地 faster-whisper)` 引擎或云端 ASR。缺失模型点击测试将自动打开极速镜像下载页面；
3. **图片理解**：推荐使用 `auto` 策略，多模态大模型优先，纯文本平滑降级为 Windows 原生 WinRT OCR。

### 第六步：配置语音电话守护 (可选 · Tab: 📞 语音电话守护)
1. 确保已运行 `install_vbcable.bat` 安装虚拟声卡；
2. 在「自动接听白名单」中勾选允许自动接听的好友；
3. 选择 TTS 引擎（推荐默认 Edge-TTS，免费且发音极其自然）；
4. 检查音频设备：输入设备选择 `CABLE Output`，输出设备选择 `CABLE Input`；
5. 点击【▶ 开启电话守护】，守护线程开始探测微信语音来电并执行全自动接听与对话。

### 第七步：开启自动回复 (Tab: 📊 运行看板与实时日志)
- 回到【📊 运行看板与实时日志】面板，点击右上角绿色的 **【▶ 开启自动回复】** 按钮；
- 状态栏将变为绿色就绪状态，控制台将实时输出思考轨迹与回复记录！

---

## 📁 目录结构

```
wechat-auto/
├── README.md                      # 项目统一官方中文说明文档
├── LICENSE                        # MIT 开源许可证
├── run_ui.bat                     # 根目录一键启动快捷脚本
├── setup_env.bat                  # 环境配置脚本
├── install_vbcable.bat            # 虚拟声卡一键安装脚本
├── install_vcam.bat               # 虚拟摄像头 (UnityCapture) 一键秒装脚本
├── docs/                          # 文档与截图资源
│   └── vertical_gui_preview.png   # 原生桌面客户端界面预览图
├── tools/
│   ├── vbcable/                   # VB-Audio CABLE 官方驱动安装包
│   └── vcam/                      # UnityCapture 极速轻量级 DirectShow 滤镜驱动
└── wechatauto-replica/            # 核心应用程序工程
    ├── run_ui.bat                 # 核心启动脚本
    ├── setup_env.bat              # 便携环境安装与依赖配置脚本
    ├── install_vbcable.bat        # VB-Audio CABLE 驱动安装脚本
    ├── install_vcam.bat           # 虚拟摄像头驱动一键安装脚本
    ├── gui_app.py                 # 原生桌面客户端入口 (8 大功能面板)
    ├── config.json                # 全局应用配置持久化文件 (gitignore，本地生效)
    ├── config.example.json        # 官方脱敏配置模板 (可供参考配置)
    ├── requirements.txt           # 核心 Python 依赖清单
    │
    ├── agent_core/                # 智能体核心架构模块
    │   ├── config.py              # 配置数据模型 (LLM、RAG、画像、VoIP 等)
    │   ├── config_manager.py      # 配置持久化与热加载管理器
    │   ├── llm_client.py          # 大语言模型客户端与连通性检测
    │   ├── media_engine.py        # 语音转写 (faster-whisper) 与图片视觉/WinRT OCR
    │   ├── pipeline.py            # 对话上下文管理与 Agent 思考执行管道
    │   ├── profile_engine.py      # 用户画像与长期事实记忆引擎
    │   ├── rag_engine.py          # 本地 BM25 检索知识库与磁盘缓存
    │   ├── tools.py               # 群管踢人、群成员检测等工具执行器
    │   ├── wechat_bridge.py       # 微信底层消息监听与发信桥接层
    │   └── voice_call/            # 📞 语音电话守护核心模块
    │       ├── call_agent.py      # 语音/视频电话总控、开场问候与生命周期调度
    │       ├── voip_watcher.py    # 来电弹窗毫秒级探测与精准点击接听
    │       ├── audio_router.py    # 虚拟声卡双工音频路由、动态增益与设备自愈
    │       ├── stt_worker.py      # 实时语音识别 (阿里 FunASR Paraformer / Faster-Whisper)
    │       ├── dialogue_engine.py # 流式大模型对话生成引擎
    │       ├── tts_manager.py     # TTS 多引擎管理 (Kokoro-82M / Qwen3 / Edge-TTS)
    │       ├── acoustic_classifier.py # 声学回声消除判别器 (音色指纹+互相关)
    │       ├── voice_clone.py     # 声音克隆管理器
    │       └── voip_tab_builder.py# VoIP GUI 面板构建器 (含数字人画面预览与口型测试)
    │   └── video_call/            # 📹 视频电话虚拟数字人核心引擎
    │       ├── avatar_engine.py   # 数字人驱动总控管理器与拟真视觉渲染管线
    │       ├── video_router.py    # 虚拟摄像头 (DirectShow/UnityCapture) 推流路由器 (640x480标准输出)
    │       ├── webcam_tracker.py  # 真实物理摄像头硬件枚举探测与动作驱动器
    │       └── engines/           # 多引擎适配器目录
    │           ├── wav2lip_engine.py      # Wav2Lip-GAN 极速口型驱动引擎 (独创唇红缘保护)
    │           ├── liveportrait_engine.py # FasterLivePortrait ONNX 神经隐空间驱动引擎
    │           └── musetalk_engine.py     # MuseTalk 高质量口型修复驱动引擎
    │
    ├── scripts/                   # 辅助与模型下载脚本
    │   ├── download_tts_models.py    # Kokoro-82M 与 Qwen3-TTS 模型一键预下载
    │   └── download_avatar_models.py # LivePortrait 与 Wav2Lip/MuseTalk 模型极速下载器
    ├── tools/vcam/                # UnityCapture 驱动注册文件
    ├── data/profiles/             # 联系人专属立体画像独立存储目录 (*.json)
    ├── data/avatars/              # 虚拟数字人正面立绘角色图片库
    ├── models/                    # 本地 AI 模型目录 (Wav2Lip / LivePortrait / MuseTalk / TTS / ASR)
    ├── runtime/                   # 全量内置绿色免安装 Python 运行时环境
    └── wechatauto/                # 微信 4.x 底层自动化核心库 (DB解密/UIA驱动/发信)
```

---

## ❓ 常见问题 (FAQ)

### Q1: 提示“未检测到运行中的微信进程”？
请确认您的电脑已登录官方微信桌面客户端（任务管理器中进程名为 `Weixin.exe`，版本需为 4.x），微信保持在后台运行或常规窗口，请勿锁定 Windows 屏幕。

### Q2: 语音电话接听失败 / 鼠标没有动作？
- 确认已在【📞 语音电话守护】面板点击【▶ 开启电话守护】；
- 确认来电方已在「自动接听白名单」中勾选；
- 检查日志输出中是否包含 `几何推算坐标(接听=右侧86%)`；
- 建议屏幕 DPI 缩放保持在 100% 以获得最高精度的物理坐标点击。

### Q3: 微信电话接通后对方听不到 AI 声音，或者突然断掉？
请按照以下**四步检查链条**进行排查：
1. **检查虚拟声卡设备绑定（至关重要）**：
   - **微信客户端内设置**：进入微信 `设置 -> 声音与通话`，将**麦克风**设置为 `CABLE Output (VB-Audio Point)`，**扬声器**设置为 `CABLE Input (VB-Audio Point)`；
   - **本软件 VoIP 面板设置**：输入设备选择 `CABLE Output`，输出设备选择 `CABLE Input`；
2. **检查 Windows 麦克风隐私权限**：
   - 进入 Windows `设置 -> 隐私与安全性 -> 麦克风`，确保“允许桌面应用访问麦克风”处于开启状态；
3. **自发音误打断防线已升级**：
   - 旧版本在 AI 发音时，环境回声可能被误判为用户插话（Barge-in）从而在 160ms 内掐断发音。当前版本已全面接入**声学特征指纹过滤与互相关预检**，并在接通瞬间主动发送开场问候（"喂，你好！..."），确保开局绝不死寂；
4. **音频增益保障**：
   - 本项目已内置**峰值自适应保真增益**（动态放大至 0.88 并防爆音削峰），防止微信自带降噪 AGC 将声音当作环境底噪过滤。

### Q4: 实时语音识别（STT）选择 FunASR 还是 Faster-Whisper？
- **强烈推荐阿里 FunASR Paraformer**：针对中文普通话与日常口语深度优化，非自回归结构，出字时延仅 150~300ms（用户落音瞬间即可出字），显存占用极小（仅约 1.5GB），大幅降低对话感知延迟；
- **Faster-Whisper**：多语种识别能力全面，适合英文或多语种混合场景。在 VoIP 面板的「实时语音识别 (STT) 引擎」卡片中可随时一键切换。

### Q5: Kokoro-82M 与 Qwen3-TTS 离线模型如何下载？
- **Kokoro-82M**：超轻量 82M 参数量，纯 CPU / 多线程推流极速（RTF < 0.2），发音清晰自然，无独立显卡即可流畅运行；
- **模型自动下载**：可在终端运行 `python scripts/download_tts_models.py`，脚本将自动从 ModelScope / 国内极速源并行下载所需权重文件并自动就位。

### Q6: 语音识别缺少模型，如何手动下载？
在【🎙️ 多模态与媒体设置】中选择对应模型规格后，直接点击下方【🌐 打开模型极速下载网页】，软件将自动在本地浏览器打开国内极速镜像下载页。将权重文件放入 `models/whisper-{规格}` 目录后重新点击测试即可。

### Q7: 群聊踢人指令 `@用户 踢` 没有反应？
请确保当前运行机器人的微信号是该群的**群主或群管理员**，并在【👥 回复对象配置】面板右侧填入准确的「群管理员微信昵称」。

### Q8: 启动或调用时出现 `trust_remote_code: False` 告警？
这是 ModelScope / HuggingFace 模型加载时的标准安全策略提示，不影响任何功能。本项目已在全局日志体系中挂载过滤层，终端日志保持清爽无扰。

### Q9: 虚拟摄像头驱动如何安装？为什么推荐 UnityCapture？
- **首推方案（UnityCapture，仅 150KB）**：本项目已随附 UnityCapture DirectShow 滤镜驱动，点击【一键安装虚拟摄像头驱动】后选择 `1`，即可秒级免装生效，无需额外下载或安装 300MB+ 的 OBS 软件；
- **OBS Studio 驱动方案**：若选择通过 WinGet 安装 OBS，脚本已锁定 `--source winget` 官方源，彻底规避了 Windows 应用商店 (msstore) 的 `0x8a15005e` 证书报错；
- **微信中选择**：安装后，在微信 `设置 -> 声音与通话 -> 摄像头` 中选中 `Unity Video Capture` 或 `OBS Virtual Camera` 即可！

### Q10: 本项目的 AI 模型文件会占用系统 C 盘空间吗？
**绝不占用系统 C 盘**。本项目已在 Python 运行时、环境启动脚本及各个子引擎中实施严格的路径重定向策略：
- 全局环境变量 `MODELSCOPE_CACHE`、`HF_HOME`、`HUGGINGFACE_HUB_CACHE`、`TORCH_HOME` 全部强制锁定在本项目 `models/` 目录下；
- 阿里 FunASR Paraformer 中文识别模型、Faster-Whisper、ChatTTS、Qwen3-TTS、Kokoro-82M、Wav2Lip-GAN 等全量模型文件均统一保存在项目内，完全隔离且可随时随地整体迁移。

### Q11: 微信视频电话接通后本地画面出现绿幕或条纹测试图？
- **根因说明**：UnityCapture DirectShow 滤镜驱动在分辨率未协商成功或共享内存未被写入有效帧时，会显示其自带的绿色条纹缺省图案；
- **全链路优化方案**：
  1. 本项目已将虚拟摄像头推流输出规范为严格的 DirectShow 行业标准 **640x480 @ 25 FPS**，完美契合微信视频调用规范；
  2. 采用**启动预热机制**：推流中枢启动瞬间自动向虚拟摄像头预充 5 帧初始待机帧，彻底杜绝微信连入瞬间闪现绿幕；
  3. **接听必启动保障**：通话接通瞬间无论初检是语音还是视频，只要启用了数字人功能，推流中枢均常驻待命；
  4. **微信内检查**：在微信 `设置 -> 声音与通话 -> 摄像头` 中选中 `Unity Video Capture`，接听即可流畅呈现数字人。

### Q12: Wav2Lip-GAN 口型引擎与其他引擎相比有何优势？
- **极速流畅实时推流**：Wav2Lip-GAN 拥有极低推理延迟，在消费级独立显卡（如 RTX 3060 / 4060）上推流帧率高达 **35 ~ 50 FPS**，完全满足微信视频电话的 25 FPS 满帧要求；
- **独创高精唇红缘保护 (根除嘴周发糊)**：传统 Wav2Lip 在 96x96 局部上采样放大贴图时极易将低清插值像素溢出到人中与下巴，导致皮肤毛孔被抹平。本项目独创**三向硬边界衰减算法**，将替换区域严格限定在唇红缘内，**人中、鼻底、下巴与脸颊皮肤 100% 保持立绘原图的高清锐度与真实毛孔**；
- **平滑降级保障**：在无独立显卡或未下载权重时，系统自适应启用轻量拟真视觉动画管线，确保 100% 稳定运行。

---

## ⚖️ 免责声明与开源许可

1. **用途限制**：本项目仅供个人技术研究、编程学习及日常效率提升使用，使用者须严格遵循《微信个人账号使用规范》及相关法律法规；
2. **安全无侵入**：本项目未采用任何破坏微信进程安全机制的 DLL 注入手段，消息读取基于本地已授权数据库文件，驱动基于 Windows 原生无障碍可访问性接口；
3. **开源许可**：本项目基于 [MIT License](LICENSE) 协议开源。
