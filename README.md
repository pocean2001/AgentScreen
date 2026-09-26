# AgentScreen — K230D 副屏的 **PC 端**工具

在电脑上运行的一套工具：把消息、状态、行情、要闻、天气、图标推送到 **K230D 副屏**（AgentScreen）。
通信只用一根 USB 线（USB-CDC 串口），不需要网络。

> ⚠️ **本仓库只包含 PC 端。**
> 板端服务（`agent_screen.py`、`board_main.py`）**不在本仓库**，需另行获取并部署到板子。
> 本文只讲 **PC 端怎么装、怎么用**。
> 本包已预置部署素材（图标库 / 状态提示音 / GB2312 补字库），装好即可用。

---

## 1. 前置条件

| 项 | 要求 |
|---|---|
| 电脑 | Windows 10/11 |
| Python | 3.9+（装了 WorkBuddy 的话自带一个可用 Python） |
| 依赖 | `pyserial`（串口）、`pillow`（图标生成/缩放） |
| **板子** | 正点原子 K230D，**且已运行 AgentScreen 板端服务**，USB 线连电脑 |
| 串口 | 插上后设备管理器出现 `CanMV (Interface 0) (COMx)` |
| WorkBuddy | 桌面版（用于 MCP 连接器 + 钩子，可选但强烈建议） |

> 板子上没跑 AgentScreen 服务的话，PC 端所有推送都会失败 —— 本仓库不含板端程序。

---

## 2. 安装（2 步）

```bat
:: ① 装依赖
python -m pip install -r requirements.txt

:: ② 装 WorkBuddy 集成（注册 MCP 连接器 + 编辑器钩子）
python install.py
```

`install.py` 会做这些事：

- 自检 Python / pyserial / pillow / 串口，缺什么直接告诉你
- **先备份**再写入 `%USERPROFILE%\.workbuddy\mcp.json` 与 `settings.json`
- 注册状态钩子（任务/思考/执行中/完成 → 副屏状态行）
- 重复执行安全（同名条目先删后写，换目录重装也没问题）

常用参数：

```bat
python install.py --pip             :: 缺依赖时自动 pip 安装
python install.py --startup         :: 顺带装"开机自启"（每 10 分钟刷新行情+要闻）
python install.py --dry-run         :: 只显示将要做什么，不写文件
python uninstall.py                 :: 卸载注册（不动程序文件）
```

> 装完后到 WorkBuddy「连接器管理 → 右上角自定义连接器」对 **AgentScreen** 点一下 **Trust**，
> 连接器才会在对话里生效（钩子不依赖 Trust，装完即刻可用）。

---

## 3. 文件清单

### 必需（程序本体）

| 文件 | 作用 |
|---|---|
| `k230_push.py` | 串口下发/读回底座（分块上传、raw REPL 会话），其它脚本都依赖它 |
| `agent_screen_mcp.py` | WorkBuddy 侧**连接器**（MCP stdio server），暴露 `screen_*` 工具 |
| `agentscreen_client.py` | 端口统一入口（连接器内置 broker，避免多进程抢串口） |
| `wb_status_hook.py` | 钩子：任务/思考/完成 → 状态行 |
| `wb_confirm_hook.py` | 钩子：执行中状态 + 高危命令副屏审批 |
| `codex_status_hook.py` / `codex_status.cmd` | Codex 运行状态 → 状态行 |
| `codex_confirm_hook.py` / `codex_confirm.cmd` | Codex 授权请求弹到副屏（K0=允许 / K1=拒绝） |
| `as_check.py` | 副屏自检/调试客户端（只用标准库），沙箱里也能用 |
| `install.py` / `uninstall.py` | 一键安装 / 卸载 WorkBuddy 注册 |
| `_python.cmd` | Python 定位器，给各 `.cmd` 双击启动用（**不要删**） |

### 可选（按需）

| 文件 | 作用 |
|---|---|
| `push_market.py` | 查美股三大指数并推屏（腾讯行情，自动判断盘前/盘中/收盘） |
| `push_digest.py` | 把「行情 + 要闻」合成一个滚动块推屏 |
| `digest_loop.py` / `digest_10min.cmd` | 常驻刷新器：每 10 分钟推一次行情+要闻（纯脚本，无 LLM 开销） |
| `push_weather.py` | 查天气并推到日期行（按出口 IP 自动定位城市） |
| `send_text.py` | 一行命令把文字推到信息栏 |
| `make_icon.py` | 生成 128×128 图标（可指定颜色） |
| `make_sfx.py` | 生成状态提示音（纯合成，无需素材） |
| `glyphcheck.py` | 实测板端字库有没有某个字的字形 |
| `cdc_bench.py` | USB-CDC 裸流吞吐测试（诊断用） |
| `disable_audio.py` | 关闭板端音频开关（见 §6 音频说明） |
| `_news.txt` | 要闻内容（每行一条；行首两空格 = 上一条的副标题） |
| `startup_digest.cmd` | 开机自启用的最小化启动器（`install.py --startup` 会引用） |

### 部署素材（要送到板子上）

| 目录 | 内容 | 送到哪 |
|---|---|---|
| `icons/` | 图标库（可自己往里加 PNG） | 推图标时由 `screen_icon` 上传 |
| `sfx/` | 6 个状态提示音（8 kHz/16 bit 单声道 WAV） | `/sdcard/sfx/` |
| `sdcard_font/` | GB2312 补字库（2 MB，解决板端字库缺字） | `/sdcard/res/font/` |

---

## 4. 日常使用

### 4.1 让 WorkBuddy 直接推（对话里说就行）

装好连接器并 Trust 后，可用这些工具：

| 工具 | 作用 |
|---|---|
| `screen_info(text/lines, append, auto)` | 设置信息栏（多行、超 4 行自动滚屏） |
| `screen_scroll(delta, auto, auto_ms)` | 信息栏翻页 / 开关自动滚屏 / 调速度 |
| `screen_stage(text, task, color, task_color, speed)` | 状态行（两段：任务 + 状态） |
| `screen_icon(path, box=128, ttl, clear)` | 推 128×128 图标到左下角 |
| `screen_weather(icon, text)` | 日期行后面加天气图标+文字 |
| `screen_clock(show)` / `screen_sync_time()` / `screen_set_time(v)` | 显示隐藏时钟 / 对时 |
| `screen_clear(what)` | 清除 overlays/info/stage/icon/weather/confirm/all |
| `screen_confirm(text, options, direct, timeout)` | 弹确认框（K0/K1 移动 + K2 确认；`direct` 模式直接选） |
| `screen_status()` | 查状态（时间、信息行、图标、状态行、错误） |

也可以直接在对话里说：「把 XX 推到副屏」「查下美股行情推副屏」「推个红五星图标」。

### 4.2 串口自动探测（未连接会明确报错）

所有入口脚本都会**自动识别板子接在哪个串口**，优先级：

1. 设备描述含 `canmv`（标准情况 `CanMV (Interface 0) (COMx)`）
2. VID/PID 匹配 `1209:ABD1`（描述不标准时兜底）
3. 上次成功用过的端口（记录在 `.as_port`，且该口仍存在）

**找不到就报错**，不静默失败：

```
[错误] 未检测到 K230D（CanMV）串口 —— 设备可能没有连接。
本机串口清单:
  COM14    CanMV (Interface 0) (COM14) [1209:abd1]   <-- 看起来就是 K230D
  COM8     蓝牙链接上的标准串行 (COM8)
请依次检查:
  1) USB 线是否插好（插板子的 USB-C 数据口，别用只供电的线/口）
  2) 设备管理器里是否出现 'CanMV (Interface 0) (COMx)'
  3) 该串口是否被占用（CanMV IDE / 串口助手 / 另一个脚本），关掉再试
  4) 板子是否卡死 -> 重插 USB 或断电重启
  5) 描述不标准/多块板子时，显式指定: set AGENTSCREEN_PORT=COM14
```

需要固定串口时：`set AGENTSCREEN_PORT=COM14`。

| 入口 | 未检测到设备时 |
|---|---|
| `install.py` | 打印错误 + 排查清单 |
| `digest_loop.py` | 错误写入控制台与 `_digest.log`，**之后每轮仍会重试**，插上板子自动恢复 |
| `push_digest.py` / `push_market.py` / `send_text.py` / `push_weather.py` | 打印「[错误] 推送失败 —— <原因 + 串口清单 + 排查清单>」，退出码 2 |
| `agent_screen_mcp.py`（连接器） | 工具调用返回带串口清单的错误文本，Agent 能看到原因 |

### 4.3 连上就自愈：自动补「时间 + 天气」

**任何一次连接器调用或 `push_digest.py` 推送**，都会先做一次自愈：

| 项 | 判定 | 动作 | 检查频率 |
|---|---|---|---|
| 时间 | 板子年份 < 2020（断电重启后 RTC 归零） | 同步为主机时间 | 30 秒 |
| 天气 | 板上没有天气文字（重启会清空） | 查天气并补推 | 300 秒 |

所以板子重启后屏上空白不用管，下一次推送会自动恢复：

```
$ python push_digest.py
推送: OK (52 行)
自愈: 时间=True 天气=True
```

常驻刷新器（每 10 分钟）会顺带自愈 —— 即使没人跟 Agent 说话，副屏时间和天气也会自己保持正确。

> **注意**：单次下发有 **约 4 KB 的硬上限**，超过会丢字节导致失败。多行信息是**分块下发**的
> （`screen_info` / `agentscreen_client.push_lines()` 自动分块）。自己写脚本推大内容请用 `push_lines()`。

### 4.4 推行情 / 要闻 / 天气

```bat
python push_digest.py            :: 行情 + 要闻 合并推（推荐）
python push_market.py            :: 只推美股三大指数
python push_market.py --dry      :: 只解析不推送，先看内容
python push_digest.py --status   :: 看要闻新鲜度/缓存状态
```

**城市识别**：`push_weather.py` 按**出口 IP** 自动定位（`ip-api.com` 中文接口 + 经纬度查 wttr.in），
结果缓存到 `.as_city`，无需配置。想固定：

```bat
set AGENTSCREEN_CITY=上海        :: 环境变量优先
python push_weather.py 上海      :: 或命令行指定一次
python push_weather.py --refresh :: 忽略缓存，重新按 IP 定位
```

**要闻**：`_news.txt` 每行一条，行首两空格表示是上一条的副标题/细节。
`push_digest.py` 发现要闻超过 30 分钟未更新时，输出末尾会带 `NEWS_STALE`（配合定时任务用 WebSearch 刷新）。

### 4.5 图标 / 提示音 / 补字库（部署素材）

```bat
python make_icon.py --list                    :: 看内置图标与颜色名
python make_icon.py star --color red          :: -> icons/star_red.png
python make_icon.py warn --color 255,140,0 --size 96
```
任意 PNG 放进 `icons/` 即可，推送时会自动缩放到 128×128。

```bat
python make_sfx.py                            :: 重新生成 6 个状态提示音到 sfx/
```
把 `sfx/*.wav` 拷到板子 `/sdcard/sfx/`（用板子的 **USB-CDC 大容量存储**模式，或拔 TF 卡用读卡器）。

补字库（解决屏上"少一个字"）：
把 `sdcard_font/_font_gb2312.ttf` 拷到板子 `/sdcard/res/font/`（**别覆盖**原有字体，那是回退点）。

> ⚠️ **别用串口传这些大文件**：实测 2 MB 走串口传到 65% 就失败，还会把板子搞到必须断电重启。
> 拷素材请走 USB 大容量存储 / 读卡器。

### 4.6 自动刷新（可选）

- **每 10 分钟**推「行情 + 要闻」：双击 `digest_10min.cmd`（窗口留着即可，关掉就停）。
  想开机自动跑：`python install.py --startup`
- **每小时**抓新要闻：在 WorkBuddy 里建定时任务，让它跑 `python push_digest.py`；
  若输出含 `NEWS_STALE`，就用 WebSearch 更新 `_news.txt` 再推一次。

### 4.7 Codex 在副屏授权（可选）

Codex 遇到需要授权的操作时，副屏弹确认框，**K0 = 允许、K1 = 拒绝**，选择结果作为 hook 决策返回。

安全约定：只有板上给出明确选择才返回决策；超时、broker 不在、`.as_quiet` 存在或
`CODEX_SCREEN_APPROVE=0` 时**不返回任何决策**，交回 Codex 自己的 TUI —— **绝不误授权**。
等待时长用 `CODEX_SCREEN_APPROVE_TIMEOUT`（默认 120 秒）调整。

自检：`codex_confirm.cmd --check`（通不通）、`codex_confirm.cmd --test`（弹测试授权框）。
在 **WSL / Codex 沙箱**里改用 `as_check.py`：

```bash
python3 as_check.py status          # 读板端状态
python3 as_check.py confirm -t 60   # 弹测试授权框，打印板上选择
python3 as_check.py stage "文本"     # 推一条状态行
```

---

## 5. 换电脑要改什么

程序本身**没有硬编码路径**（都用脚本自身所在目录）。换机只需处理 2 处：

1. **Python 路径**：`.cmd` 启动器已改成**自动查找**（WorkBuddy 自带 → PATH → `py`），一般不用改。
2. **WorkBuddy 配置**：`install.py` 会自动写入当前机器的绝对路径 —— **换机后重跑一次 `python install.py` 即可**
   （旧配置会备份成 `*.bak-时间戳`）。

> **串口号不用管**（自动识别）；**板子不随电脑搬家** —— 板端服务已经在板子上跑着。

---

## 6. 常见问题

| 现象 | 处理 |
|---|---|
| 提示找不到 CanMV 串口 | 换 USB 线/口；确认设备管理器有 `CanMV (Interface 0) (COMx)`；关掉占用该口的程序（CanMV IDE、串口助手） |
| 推送报"端口被占用" | 稍等重试（钩子与脚本会短暂抢口，已有退避重试）；关掉多余的手工脚本 |
| 板子完全没反应 / 推送一直失败 | **给板子断电重启或重插 USB**（软件救不回）。恢复后 `python -c "import k230_push;print(k230_push.detect_canmv_port())"` 看端口 |
| 重启板子后图标/天气/信息栏没了 | 正常（板端重启会清空屏上状态），跑 `python push_digest.py` 重推即可 |
| 屏上文字显示成方块 | 该字符不在板端字体里（emoji 一般没有）。放上 `sdcard_font/_font_gb2312.ttf` 可覆盖常用汉字；或用 `make_icon.py` 画图标 |
| 屏上"少了一个字" | 板端字库缺字形：用 `python glyphcheck.py "东莞"` 确认；补字库见 §4.5 |
| 中文乱码 | 脚本一律按 UTF-8 读写；自己写的脚本读 WorkBuddy 事件时记得 `sys.stdin.buffer.read().decode("utf-8")` |
| 信息栏内容不滚动 | 内容超过 4 行才会滚；确认 `screen_status()` 里 `info_auto` 为 true |
| 想临时停掉所有推送（刷机/联调时） | 在程序目录建一个空文件 `.as_quiet`，钩子检测到就直接退出；删掉即恢复 |
| 沙箱里跑 `codex_confirm.cmd --check` 报 `UtilBindVsockAnyPort: socket failed` | 沙箱禁了"调 Windows exe"和 socket，不是链路故障。改用 `python3 as_check.py status` |
| 推大段内容后板子没反应 | 单次下发超过约 4 KB 被截断。用 `screen_info` / `push_lines()`（已自动分块） |
| **音频/提示音没声音** | 板端音频**默认关闭**且**不可开启**：实测该板子上 `pyaudio` 播放会把板子挂死（需断电），所以源码里 `ENABLE_MEDIA` 默认 False。素材已备好（`sfx/`），但**暂时不要启用**；细节见 `docs/audio_stream_feasibility.md` |

---

## 7. 卸载

```bat
python uninstall.py          :: 移除 WorkBuddy 里的连接器 + 钩子 + 开机自启（先备份）
```

程序文件仍在原目录，直接删掉文件夹即可。板子上已部署的服务与素材不归本仓库管，按需自行清理。

---

## 8. 架构（PC 侧）

```
WorkBuddy / 脚本(电脑)                      K230D(板子)
┌────────────────────────────────────┐      ┌──────────────────────┐
│ 对话 → MCP 工具 screen_*           │      │ AgentScreen 板端服务  │
│        └→ agent_screen_mcp.py      │      │  (本仓库不含)         │
│             ├ 内置 broker          │      │                      │
│             │  (127.0.0.1:8720)  ──┼─串口─┤ 时钟/状态行/信息栏/   │
│             └ 上传下载             │ USB  │ 图标/确认框           │
│                (k230_push.py)      │ CDC  │                      │
│ 钩子 wb_status / wb_confirm        │115200│                      │
│        └→ agentscreen_client ──────┘      └──────────────────────┘
│ 常驻 digest_loop.py(每10分钟)      │
└────────────────────────────────────┘
```

- PC 侧全部通信走**串口 raw REPL**，因此板子能长期稳定运行。
- 连接器进程内的 broker 是串口的**唯一入口**，钩子和脚本都经它排队，不会互相抢口。

> 更多实现细节见 `docs/`：`audio_stream_feasibility.md`（副屏音频可行性评估）、
> `codex_status_hook.md`（Codex 在副屏上做授权确认）。

---

## 9. 许可证

[MIT License](LICENSE) © 2026 pocean2001
