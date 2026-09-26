# 副屏流式音频下发 — 技术可行性评估

> 评估日期：2026-09-26　目标板：正点原子 K230D（CanMV，固件含 freetype / 音频 MPI）
> 关联内容：AgentScreen 副屏服务 `agent_screen.py`（已具备音频队列与播放线程）

## 0. 结论摘要

| 结论 | 说明 |
|---|---|
| **板端播放能力** | ✅ **完全具备流式播放**（`PyAudio.open(output=True)` + `stream.write()` 逐块写 PCM） |
| **板端解码能力** | ✅ 硬件 AO / ADEC / AENC 全套；payload 覆盖 **Opus / AAC / MP3 / G711 / G726 / AMR / LPCM** 等 |
| **唯一真正瓶颈** | ⚠️ **主机→板子的数据通道带宽**，不是板子 |
| **走现有 REPL 通道** | ❌ 实测仅 **2.4~3 KB/s** → 连 8 kHz/16bit PCM（16 KB/s）都喂不动，只够 Opus@16kbps 级别且无余量 |
| **实测结论** | ❌ **USB-CDC 裸流已否决**（2026-09-26 实测：代码执行期间主机数据到不了板端 stdin，且阻塞 read 会把板子搞到必须断电）→ **改走方案 C：独立硬件 UART** |

---

## 1. 板端能力实勘（已在真机确认）

### 1.1 软件 API（`media.pyaudio`）— 官方例程 `/sdcard/examples/02-Media/audio.py`

```python
from media.pyaudio import PyAudio, paInt16
p = PyAudio(); p.initialize(CHUNK)
stream = p.open(format=paInt16, channels=1, rate=16000, output=True, frames_per_buffer=CHUNK)
stream.volume(vol=85)
stream.write(pcm_bytes)        # ← 逐块写, 这就是流式播放的基础
...
stream.stop_stream(); stream.close(); p.terminate()
```

- `Write_stream` 方法集：`write / read / stop_stream / start_stream / volume / swap_left_right / dev_chn_enable`
- 支持格式常量：`paInt16 / paInt24 / paInt32`；`p.get_format_from_width(w)` 可换算
- **采样率由参数决定**（例程直接取 wav 的 `get_framerate()`），不是硬编码

### 1.2 硬件/驱动层（`/dev` 与 `media.player` 常量表）

| 设备节点 | 用途 |
|---|---|
| `ao_device` / `ai_device` | 音频输出 / 输入 |
| `adec_device` / `aenc_device` | 音频解码 / 编码 |
| `acodec_device` | 音频 codec（板载 codec，`K_AIO_I2STYPE_INNERCODEC`） |

Python 可达的底层 MPI（节选，均为 `media.player` 导出）：
`kd_mpi_ao_enable/disable/set_pub_attr/send_frame`、`kd_mpi_adec_create_chn/send_stream/get_frame/release_frame`、
`kd_mpi_aenc_*`、`kd_mpi_ai_*`；解码模式 `K_ADEC_MODE_STREAM`（**流式**）/ `K_ADEC_MODE_PACK`。

**payload 类型（说明编解码能力）**：`K_PT_OPUS`、`K_PT_AAC`、`K_PT_HEAAC`、`K_PT_MP3`、`K_PT_G711A/U`、
`K_PT_G726`、`K_PT_G722`、`K_PT_AMR/AMRWB`、`K_PT_LPCM`、`K_PT_PCMU/PCMA` 等。

**容器级播放**：`media.player.Player` 有 `load / start / pause / resume / stop / set_event_callback`，
事件 `K_PLAYER_EVENT_EOF / PROGRESS`（可播文件，但不适合"边下边播"的实时流）。

### 1.3 现有代码基础

`agent_screen.py` 里已有：`ST.audio_q`（队列）+ `_play_loop()`（消费线程）+ `_play_wav(path)`。
**关键约束**：播放期间持 `MEDIA_LOCK` —— 注释写明"独占媒体子系统（播放期间显示暂停刷新）"。

---

## 2. 瓶颈分析：通道带宽

### 2.1 各通道实测/理论能力

| 通道 | 速度 | 来源 |
|---|---|---|
| **现有 REPL 分块上传** | **~2.4 KB/s** | 实测：2 MB 字体传到 65%(1.3 MB) 用 8m45s；小文件 3.7 KB / 1.2 s |
| **USB-CDC 裸二进制流**（绕过 REPL） | **未测**，理论 USB-FS 12 Mbps ≈ 1.2 MB/s，实际受 MicroPython `stdin.buffer.read` 与驱动缓冲限制 | 待实测（见 §5） |
| **额外硬件 UART**（`/dev/uart0..4` + USB-TTL） | 921600 bps ≈ **90 KB/s**；1500000 bps ≈ 146 KB/s | 需接线 |

### 2.2 音频码率需求（单声道）

| 格式 | 码率 | REPL 2.4 KB/s | 裸 CDC（若 100 KB/s） | 硬件 UART 92 KB/s |
|---|---|---|---|---|
| 16 kHz / 16 bit PCM | 32 KB/s | ❌ | ✅（余量 3×） | ✅ |
| 16 kHz / 8 bit (G711A) | 16 KB/s | ❌ | ✅ | ✅ |
| 8 kHz / 16 bit PCM | 16 KB/s | ❌ | ✅ | ✅ |
| AAC @32 kbps | 4 KB/s | ⚠️ 勉强 | ✅ | ✅ |
| **Opus @16 kbps** | **2 KB/s** | ⚠️ 临界（无余量） | ✅ | ✅ |
| MP3 @64 kbps | 8 KB/s | ❌ | ✅ | ✅ |

### 2.3 延迟/缓冲推算（流式可用性的真正判据）

要在播放中不欠载（underrun），**先缓冲**的时长 ≈ 单段音频时长 × (码率 ÷ 通道速率)：

| 通道速率 | 播 3 秒的 16k/16bit PCM（96 KB）需先缓冲 | 可用性 |
|---|---|---|
| 2.4 KB/s（REPL） | **40 秒** | ❌ 完全不可用 |
| 32 KB/s | 3 秒 | ⚠️ 临界（等于实时） |
| 100 KB/s | ~1 秒 | ✅ 可用（首字延迟 ~1s） |
| 92 KB/s（UART） | ~1 秒 | ✅ 可用 |

→ **判断标准**：通道速率至少要为码率的 **2~3 倍**，才能既流式又不断音。

---

## 3. 三条候选方案

### 方案 A：USB-CDC 裸流 + PCM（推荐先验证）
- **主机**：`serial.write(pcm_bytes)` 直接写二进制（不经 base64、不经 REPL）
- **板端**：收到 `audio_begin` 命令后 `os.dupterm(None, 1)` **暂时解绑 REPL** → `sys.stdin.buffer.read(N)` → `stream.write()` → 结束时恢复 dupterm
- **优点**：零额外硬件，延迟最低，PCM 无需编解码
- **门槛**：实测吞吐必须 > 64 KB/s（32 KB/s 码率的 2 倍）
- **风险**：`os.dupterm` 接管期间 REPL 不可用（若异常退出需断电恢复）；此前已有"大 payload 把板子搞卡"的先例

### 方案 B：压缩音频 + 现有 REPL 通道
- 主机侧用 Opus @16 kbps（或 AAC @32 kbps）编码 → 走现有通道
- 板端用 ADEC 解 `K_PT_OPUS` 再送 AO
- **优点**：不动通道，不用接线
- **缺点/风险**：REPL 2.4 KB/s 对 Opus 16 kbps **毫无余量**（音画/控制命令一挤就断音）；
  且 ADEC 的 Python 调用链（`k_mpi_adec_*` 需要构造 `k_adec_chn_attr` 等 ctypes 结构）**复杂度高**，调通成本大
- **评价**：技术可行但工程性价比低

### 方案 C：独立硬件 UART 通道
- 从板子引出 UART（`/dev/uart*`）+ 一个 USB-TTL 模块，921600 bps
- **优点**：带宽充裕（90 KB/s）；**控制通道（USB-REPL）与音频通道彻底分离**，互不干扰；验证/调试最容易
- **缺点**：需接线（对硬件工程师成本很低）
- **评价**：**最稳妥、最可预期**的方案

---

## 4. 其它需要一并确认的约束

1. **播放时显示会停**：`MEDIA_LOCK` 使播放期间渲染暂停。要"边说边显示"需改造（拆分锁粒度或让 AO 与 VO 共存）——需实测 K230 的 VO/AO 能否并行。
2. **音频输出硬件**：需确认 K230D 板上是**喇叭 / 耳机口 / 功放**，以及实际音质（板载 codec 输出电平）。
3. **内存**：MicroPython 堆 ~3.7 MB 可用。流式方案只要**环形缓冲**（几十 KB）即可，压力很小。
4. **无压缩库**：板端**没有 `uzlib`/`zlib`** → 不能"主机压缩、板端解压"这条省带宽的路（`Opus` 只能靠硬件 ADEC，不能靠 Python 解）。
5. **时序**：`CHUNK=1024` 帧 @16 kHz = **64 ms/块**；通道需稳定保证 64 ms 内送到一块，否则欠载破音。

---

## 5. 建议的下一步验证（按风险从低到高）

| # | 验证项 | 方法 | 风险 |
|---|---|---|---|
| 1 | **USB-CDC 裸流吞吐**（决定性） | 板端后台线程 `dupterm(None)` 后 `read(N)` 计时；主机随后写 N 字节。**从 8 KB 起步，逐级 32 KB → 128 KB** | 中（可能需断电） |
| 2 | AO 与显示能否并行 | 播放期间观察渲染是否继续（当前必然停） | 低 |
| 3 | 实际音质/音量 | 播 `as_beep.wav` 与一段 16k PCM，人耳确认 | 无 |
| 4 | UART 备用通道 | 若有第二块 USB-TTL：接线 + 921600 测速 | 低 |

**决策规则**：
- 若 #1 实测 ≥ 64 KB/s → **走方案 A**（PCM 直传，最省事）
- 若 #1 只有 8~20 KB/s → **走方案 C**（UART）或用 **G711A 16 KB/s** 勉强跑
- 若 #1 不稳（时断时续）→ **走方案 C**

---

## 5.5 实测结果（2026-09-26 23:0x）— USB-CDC 裸流：❌ **此路不通**

**实验 1（8 KB 裸写）**
- 主机写 8192 字节仅耗时 **0.001 s**（数据进了主机/USB 缓冲，未真正送达）
- 板端 `select.poll` 注册成功但**永不触发** → 读循环空转 → `got=0`，6 s 后兜底超时退出
- 说明：**`select.poll` 对 `sys.stdin` 不可用**

**实验 2（探针：`read(1)` 阻塞性与可达性）**
| 观察 | 结果 |
|---|---|
| 板端 `print("T1")` | ✅ 正常到达（代码确实在执行） |
| 板端 `sys.stdin.buffer.read(1)` | ⏳ **阻塞 3 秒不返回** → read 是阻塞式 |
| 主机随后发 1 字节 | ❌ 板端**毫无反应**，没有输出 T2 |

**结论**
1. **代码执行期间，主机写入的数据无法到达板端 `sys.stdin`** —— 「进 raw REPL → 写代码 → 发裸数据」这条路径**不成立**。
2. 推测原因：REPL 与用户程序**共享同一个 USB-CDC stdin**；raw REPL 处于"执行代码"状态时，输入不会交给 `sys.stdin.buffer`（被 REPL 侧吞掉/未开启接收）。
3. **副作用**：阻塞中的 `read(1)` **无法用 Ctrl-C 中断** → 板子卡死，**必须物理断电重插**才能恢复。

**对方案选型的影响**

| 方案 | 修订后结论 |
|---|---|
| **A. USB-CDC 裸流** | ❌ **否决**（实测数据不可达 + 会把板子搞死） |
| **B. 压缩音频走 REPL** | ⚠️ 仍只是"理论可行"：2.4 KB/s 对 Opus@16kbps 无余量，ADEC 的 Python 调用链复杂 |
| **C. 独立硬件 UART** | ✅ **唯一推荐路径**（`machine.UART` 独立于 REPL，921600 bps ≈ 90 KB/s，控制与音频物理分离） |
| **D. `os.dupterm(None)` 让位** | ⚠️ 理论可行但**风险更高**（REPL 可能永久失效；且输出一并被摘掉，只能靠文件回读）；**不建议盲试** |
| **E. USB 大容量存储（MSC）传文件** | ⚠️ 可传但不实时（需切换 USB 模式），只适合"先下载再播放" |

**下一步建议**：改走**方案 C** —— 接线（UART TX/RX + GND 接 USB-TTL），板端用 `machine.UART(波特率=921600)` 收流，
主机侧 `pyserial` 写到那个口。这条路不需要 REPL、不共享 stdin，风险最低，且带宽（~90 KB/s）足够直传 16 kHz/16 bit PCM。


---

## 6. 参考：板端现成资产

| 路径 | 内容 |
|---|---|
| `/sdcard/examples/02-Media/audio.py` | 官方录音+播放例程（`p.open(...)` / `stream.write()` 用法） |
| `/sdcard/examples/utils/*.wav` | `wow_new.wav` / `stop_new.wav` / `wozai.wav` / `go_new.wav`（测试音） |
| `/sdcard/as_beep.wav` | 本项目提示音（已在 `_play_wav` 使用） |
| `agent_screen.py` | `audio_q` / `_play_loop` / `_play_wav`（已有音频队列骨架，可直接扩展） |
