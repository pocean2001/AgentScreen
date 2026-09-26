# AgentScreen — K230D 副屏（时钟 + 状态行 + 滚动信息栏 + 图标）

把 **正点原子 K230D（DNK230D，CanMV MicroPython）** 当电脑的第二块小屏用：

- 顶上大字体时钟（`HH:MM:SS.mmm`）+ 日期 + 天气
- **状态行**：绿色「当前任务」段 + 彩色「执行状态」段（思考中🔴 / 执行中🟡 / 完成🟢），超长自动横向慢速滚动
- **信息栏**：多行内容（最多存 80 行），超过 4 行自动**上下滚屏**，右侧带滚动条
- **左下角图标位**：可推 128×128 图标（内部已归一化）
- 可选的**触屏/按键确认框**，可用作"高危命令副屏审批"：授权类用**直选**（K0=允许 / K1=拒绝），
  多选项用**高亮选择**（K0/K1 移动 + K2 确认，超 4 项自动窗口滚动）

通信只用一根 USB 线（USB-CDC 串口），**不需要网络**。

---

## 1. 前置条件

| 项 | 要求 |
|---|---|
| 电脑 | Windows 10/11 |
| 板子 | 正点原子 K230D，烧好 CanMV MicroPython 固件，USB 线连电脑 |
| 串口 | 插上后设备管理器出现 `CanMV (Interface 0) (COMx)` |
| Python | 3.9+（装了 WorkBuddy 的话，自带一个可用的 Python） |
| 依赖 | `pyserial`（串口）、`pillow`（图标生成/缩放） |
| WorkBuddy | 桌面版（用于 MCP 连接器 + 钩子，可选但推荐） |

---

## 2. 安装（3 步）

```bat
:: ① 装依赖
python -m pip install -r requirements.txt

:: ② 装 WorkBuddy 集成（注册连接器 + 钩子）
python install.py

:: ③ 把板端程序烧进板子（只需要在首装/换机/改板端代码后做）
双击 redeploy_agentscreen.cmd     （或 python install.py --deploy）
```

`install.py` 还会做的事：

- 自检 Python / pyserial / pillow / 串口，并告诉你缺什么
- **自动备份**再写入 `%USERPROFILE%\.workbuddy\mcp.json` 与 `settings.json`
- 重复执行安全（同名条目会先删后写，换目录重装也没问题）

常用参数：

```bat
python install.py --pip                :: 缺依赖时自动 pip 安装
python install.py --startup            :: 同时装"开机自启"（每 10 分钟刷新行情+要闻）
python install.py --deploy --test      :: 装配置 + 上板 + 往副屏推一条测试
python install.py --dry-run            :: 只显示将要做什么，不写文件
python uninstall.py                    :: 卸载在 WorkBuddy 里的注册（不动程序文件）
```

装完后**到 WorkBuddy「连接器管理 → 右上角自定义连接器」对 `AgentScreen` 点一下 Trust**，
连接器才会在对话里生效（钩子不依赖 Trust，装完即刻可用）。

---

## 3. 文件清单（哪些是必需的）

### 必须有的（程序本体）

| 文件 | 作用 | 必需性 |
|---|---|---|
| `k230_push.py` | 串口下发/读回底座（分块上传、raw REPL 会话） | **核心**，其它脚本都依赖它 |
| `agent_screen_mcp.py` | WorkBuddy 侧**连接器**（MCP stdio server），暴露 `screen_*` 工具 | **核心** |
| `agentscreen_client.py` | 端口统一入口（连接器内置 broker，避免多进程抢 COM14） | **核心** |
| `board/agent_screen.py` | **板端服务**（时钟/状态行/信息栏/图标/确认框）→ 上传到 `/sdcard/agent_screen.py` | **核心** |
| `board/board_main.py` | 开机自启入口 → 上传到 `/sdcard/main.py` | **核心** |
| `redeploy_agentscreen.py` | 上板（上传上面两个文件 + soft reset 重载） | **核心** |
| `wb_status_hook.py` | 钩子：任务/思考/完成 状态推送到状态行 | 想要自动状态就必需 |
| `wb_confirm_hook.py` | 钩子：执行中状态 + 高危命令副屏审批 | 想要自动状态就必需 |
| `codex_status_hook.py` | Codex 钩子：把 Codex 的运行状态推到状态行（`codex_status.cmd` 是其 Windows 入口） | 用 Codex 就必需 |
| `codex_confirm_hook.py` | Codex 授权钩子：把授权请求弹到副屏，**K0=允许 / K1=拒绝**（`codex_confirm.cmd` 是入口） | 想在副屏直接授权就必需 |
| `as_check.py` | 副屏自检/调试客户端（只用标准库）：`python3 as_check.py status / confirm / stage / raw`。在 WSL 沙箱里跑不了 `codex_confirm.cmd --check` 时用它 | 联调排查用 |
| `.codex/hooks.json` | Codex 项目级钩子注册（在 `D:\K230D` 里启动 Codex 才生效） | 同上 |

### 可选（按需）

| 文件 | 作用 |
|---|---|
| `push_market.py` | 查美股三大指数并推屏（腾讯行情，自动判断盘前/盘中/收盘） |
| `push_digest.py` | 把「行情 + 要闻」合成一个滚动块推屏 |
| `digest_loop.py` | 常驻刷新器：每 10 分钟推一次行情+要闻（纯脚本，无 LLM 开销） |
| `send_text.py` | 一行命令把文字推到信息栏 |
| `make_icon.py` | 生成 128×128 图标（可指定颜色），推屏用 |
| `push_weather.py` | 查天气并推到日期行（wttr.in） |
| `_news.txt` | 要闻内容（每行一条；行首两空格=上一条的副标题） |
| `icons/` | 图标库（可自己往里加） |
| `_python.cmd` | Python 定位器，给各 `.cmd` 双击启动用（**不要删**） |
| `digest_10min.cmd` | 双击：开始每 10 分钟刷新 |
| `redeploy_agentscreen.cmd` | 双击：上板 / 重部署板端 |
| `startup_digest.cmd` | 最小化启动（开机自启用，`install.py --startup` 会引用） |
| `install.py` / `uninstall.py` | 一键安装 / 卸载 WorkBuddy 注册 |

---

## 4. 日常使用

### 4.1 让 WorkBuddy 直接推（对话里说就行）

装好连接器并 Trust 后，可直接用这些工具：

| 工具 | 作用 |
|---|---|
| `screen_info(text/lines, append, auto)` | 设置信息栏（多行、超 4 行自动滚屏） |
| `screen_scroll(delta, auto, auto_ms)` | 信息栏手动翻页 / 开关自动滚屏 / 调速度(ms/行) |
| `screen_stage(text, task, color, task_color, speed)` | 状态行（两段：任务 + 状态） |
| `screen_icon(path, box=128, ttl, clear)` | 推 128×128 图标到左下角 |
| `screen_weather(icon, text)` | 日期行后面加天气图标+文字 |
| `screen_clock(show)` / `screen_sync_time()` / `screen_set_time(v)` | 显示隐藏时钟 / 对时 |
| `screen_clear(what)` | 清除 overlays/info/stage/icon/weather/confirm/all |
| `screen_confirm(text, options, direct, timeout)` | 弹确认框：默认 K0/K1 移动高亮 + K2 确认；`direct=true` 时 K0/K1/K2 直接选第 1/2/3 项 |
| `screen_status()` | 查状态（时间、信息行、图标、状态行、错误） |

也可以直接在对话里说：「把 XX 推到副屏」「查下美股行情推副屏」「推个红五星图标」。

### 4.2 串口自动探测（启动即检测，未连接会报错）

所有入口脚本都会**自动识别板子接在哪个串口**，规则按优先级：

1. 设备描述里含 `canmv`（标准情况：`CanMV (Interface 0) (COMx)`）
2. VID/PID 匹配 `1209:ABD1`（描述不标准时的兜底）
3. 上次成功用过的端口（记录在同目录 `.as_port`，且该口仍存在）

**找不到设备就报错**，不会静默失败：

```
[错误] 未检测到 K230D（CanMV）串口 —— 设备可能没有连接。
本机串口清单:
  COM14    CanMV (Interface 0) (COM14) [1209:abd1]   <-- 看起来就是 K230D
  COM8     蓝牙链接上的标准串行 (COM8)
请依次检查:
  1) USB 线是否插好（插板子的 USB-C 数据口，别用只供电的线/口）
  2) 设备管理器里是否出现 'CanMV (Interface 0) (COMx)'；
     若显示'未知 USB 设备(设备描述符请求失败)'，是板子 USB 没起来 -> 给板子断电重启
  3) 该串口是否被占用（CanMV IDE / 串口助手 / 另一个脚本），关掉再试
  4) 板子是否卡死 -> 重插 USB 或断电重启
  5) 描述不标准/多块板子时，显式指定: set AGENTSCREEN_PORT=COM14
```

各入口的表现：

| 入口 | 未检测到设备时 |
|---|---|
| `install.py` | 打印上面那段错误；若同时用了 `--deploy/--test` 则以退出码 2 结束 |
| `digest_loop.py`（10 分钟刷新） | 启动时打印错误到控制台与 `_digest.log`，**之后每轮仍会重试**，插上板子自动恢复 |
| `push_digest.py` / `push_market.py` / `send_text.py` / `push_weather.py` | 打印「[错误] 推送失败 —— <原因 + 串口清单 + 排查清单>」，退出码 2 |
| `redeploy_agentscreen.py` | 打印错误并退出码 2 |
| `agent_screen_mcp.py`（连接器） | 工具调用返回带串口清单的错误文本，Agent 会看到具体原因 |

需要固定串口时（多块板子、或想跳过探测）：`set AGENTSCREEN_PORT=COM14`。

### 4.2.1 连上就自愈：自动补「时间 + 天气」

**只要有任何一次连接器调用或 `push_digest.py` 推送**，就会先做一次自愈：

| 项 | 判定 | 动作 | 检查频率 |
|---|---|---|---|
| 时间 | 板子年份 < 2020（断电重启后 RTC 归零） | 同步为主机时间 | 30 秒 |
| 天气 | 板上没有天气文字（soft reset / 重部署会清空） | 查天气并补推 | 300 秒 |

所以板子重启后屏上空白不用管，下一次推送就会自动恢复：

```
$ python push_digest.py
推送: OK (52 行)
自愈: 时间=True 天气=True
```

脚本侧同一套逻辑在 `agentscreen_client.ensure_ready()` —— 常驻刷新器（每 10 分钟）会顺带自愈，
因此即使没人跟我说话，副屏的时间/天气也会自己保持正确。

**注意**：板端 raw REPL 单次下发有 **约 4KB 的硬上限**，超过会丢字节 → 板端 `SyntaxError` 且会话挂住。
所以多行信息是**分块下发**的（`agentscreen_client.push_lines()` / `screen_info` 自动分块，每块 16 行）。
自己写脚本推大内容时请用 `push_lines()`，别直接拼一个巨大的 `info` 命令。

### 4.2.2 城市识别（按出口 IP）与日期行

日期行现在是：**日期 │ 城市 ﹝天气图标﹞ 天气文字**。
**注意排版区域**：整行只在一个**左区域**里居中（`DATE_L=12` … `DATE_R=WIDTH-104`），
右边专门给右上角的 WB 连接图标留位 —— 否则这一行变长时会顶到连接图标上。

城市**自动按出口 IP 定位**，无需配置：

| 步骤 | 实现 |
|---|---|
| IP 定位 | `http://ip-api.com/json/?lang=zh-CN`（返回中文：`中国/广东/东莞市` + 经纬度），结果缓存在 `.as_city`，避免每次都查 |
| 查天气 | 用定位到的**经纬度**查 wttr.in（避免同名城市查错），`%l` 只给经纬度所以不能直接用 |
| 定位失败 | 退回 wttr.in 自带 IP 定位（此时不显示城市）；极窄时先舍城市、再舍天气文字，保证日期一定显示 |
| **缺字避让** | 板端字体是裁剪过的（实测 **`莞`/`圳` 没有字形**，画出来是空白 → "东莞"看着像少一个字）。`glyphcheck.py` 会**实测板端字库覆盖**（离屏画字→导出→量墨迹），自动择优：**中文城市 → 中文省 → 英文城市**，并把结果缓存到 `.as_glyphs.json`。实测 `东莞` → 自动显示 `广东` |
| 槽位 | 城市固定占 **4 个字宽**（`CITY_SLOT_CH`），所以**天气不会因城市名长短而移动** —— 2 字城市与 4 字城市的天气图标位置完全一致 |

想固定城市（不跟随 IP）：

```bat
set AGENTSCREEN_CITY=上海            :: 环境变量优先
python push_weather.py 上海          :: 或命令行指定一次
python push_weather.py --refresh      :: 忽略缓存, 重新按 IP 定位
```

板端 `weather` 命令带 `city` 字段；只更新 icon/text 时会**保留已识别的城市**，不会被清掉。
连接器 `screen_weather(icon, text, city)` 同理。自愈逻辑也认城市：板上缺文字**或**缺城市都会补。

### 4.2.3 缺字（屏上"少一个字"）与补字库
**症状**：屏上文字像被遮掉一个字（如 `东莞` 只显示 `东`，`深圳` 只显示 `深`）。
**根因**：不是排版问题，是该字在板端字体里**没有字形** —— 实测缺字**推进宽度为 0**（整字消失，不占位）。
板端默认字体是 `/sdcard/res/font/SourceHanSansSC-Normal-Min.ttf`（思源黑体 **Min 裁剪子集**，1.86 MB），
它裁掉了 GB2312 **二级**字：`莞 圳 矽 穹 魅` 等都没有。

**解法**：放一个覆盖更全的字体，`agent_screen.py` 会自动优先用它。

| 项 | 说明 |
|---|---|
| 字体文件 | 包内 `sdcard_font/_font_gb2312.ttf`（2051 KB，含 ASCII + GB2312 全码位 + 常用符号） |
| 放到板子 | `/sdcard/res/font/_font_gb2312.ttf` |
| 放法 | ① 板子 USB 接电脑，用 **USB-CDC 大容量存储**直接拷；② 拔 TF 卡用读卡器拷 |
| ⚠️ 别用串口传 | 2 MB 走串口实测 **9 分钟传到 65% 失败**，还会把板子搞到必须断电重启 |
| 不装会怎样 | 不会坏：找不到该文件就**自动退回内置字体**，只是仍会缺字 |
| 换字体的代价 | 首次遇到某个新字要 26 ms 建缓存，之后 **0 ms**；内存几乎不占（freetype 按需读文件） |

自检：
```bat
python glyphcheck.py "东莞深圳"          :: 上板实测某几个字有没有字形(会自动用同一字体)
```
> 原字体文件**不要覆盖**，留着当回退点。

### 4.3 板载按键 / 触屏

| 操作 | 作用 |
|---|---|
| K0 / K1 | 信息栏上翻 / 下翻一行（手动后自动滚动暂停） |
| K2 | 开关信息栏自动滚动 |
| 确认框·直选 | K0 / K1 / K2 直接选第 1 / 2 / 3 项（授权框就是这种，K0=允许） |
| 确认框·高亮 | K0 / K1 上下移高亮（长按连发）、K2 确认；超 4 项窗口跟随滚动 |
| 触屏点按 | 两种模式下都可点按可见的任意选项行 |

### 4.4 自动刷新（可选）

- **每 10 分钟**推「行情 + 要闻」：双击 `digest_10min.cmd`，窗口留着即可（关掉就停）。
  想开机自动跑：`python install.py --startup`
- **每小时**用 WebSearch 抓新要闻：在 WorkBuddy 里建一个定时任务，让它运行
  `python push_digest.py`，若输出含 `NEWS_STALE` 就用 WebSearch 更新 `_news.txt` 再推一次。
- 只想推一次：`python push_digest.py`；只查行情：`python push_market.py`。

### 4.5 加新图标

```bat
python make_icon.py --list                          :: 看内置图标与颜色名
python make_icon.py heart                           :: -> icons/heart.png
python make_icon.py star --color red                :: 红五星
python make_icon.py warn --color 255,140,0 --size 96
```
也可以直接放任意 PNG 进 `icons/`，推的时候会自动缩放到 128×128。

---

### 4.6 Codex 在副屏授权（可选）

在 `D:\K230D` 里启动的 Codex（项目级 `.codex/hooks.json`）遇到需要授权的操作时，
副屏会弹出确认框，**直接按 K0 = 允许、K1 = 拒绝**（2 行各有自己的键，不用移动高亮，也可触屏点）。
选择结果会作为 Codex 的 hook 决策返回，Codex 那边就不再弹自己的授权提示。

安全约定：只有板上给出明确选择才返回决策；超时、broker 不在、`.as_quiet` 存在、
或 `CODEX_SCREEN_APPROVE=0` 时**不返回任何决策**，交回 Codex 自己的 TUI 询问 —— 绝不误授权。
等待时长用 `CODEX_SCREEN_APPROVE_TIMEOUT`（默认 120 秒）调整。

前提：在 WorkBuddy 里 AgentScreen 连接器处于运行状态（它才是 8720 broker、COM14 的唯一持有者）。
自检：`codex_confirm.cmd --check`（通不通）、`codex_confirm.cmd --test`（弹一个测试授权框）。
在 **WSL / Codex 沙箱**里（建不了 socket、也调不了 Windows 的 python.exe）改用 `as_check.py`：

```bash
python3 as_check.py status          # 经 broker 读板端状态
python3 as_check.py confirm -t 60   # 板上弹测试授权框，按 K0/K1，打印板上选择
python3 as_check.py stage "文本"     # 推一条状态行
```

它先试 TCP（127.0.0.1:8720），不通就退到 broker 的**文件桥**
（请求写 `_asbridge_in.json`、应答写 `_asbridge_out.json`，都在这两个程序目录里）。
文件桥要**新版 broker**：改完 `agent_screen_mcp.py` 后重启一次 AgentScreen 连接器才生效；
设 `AGENTSCREEN_BRIDGE=0` 可关掉它。

改过 `.codex/hooks.json` 后，Codex 会按内容哈希重新询问一次"是否信任这些钩子"，属正常现象。

---

## 5. 换电脑要改什么

程序本身**没有硬编码路径**（都用脚本自身所在目录）。换机需要处理的只有 3 处：

1. **Python 路径**：`.cmd` 启动器已改为**自动查找** Python（WorkBuddy 自带 → PATH → `py`），
   一般不用改。若找不到，装个 Python 3.9+ 并勾选加入 PATH。
2. **WorkBuddy 配置**：`install.py` 会自动写入当前机器的绝对路径 —— 所以**换机后重新跑一次
   `python install.py` 即可**（旧的备份文件会留在同目录 `*.bak-时间戳`）。
3. **串口号**：不用管，程序按设备描述自动识别 `CanMV` 串口；多块板子时用
   `set AGENTSCREEN_PORT=COM14` 指定。

> 首次在**新机器**上跑，建议顺序：`install.py --pip` → 双击 `redeploy_agentscreen.cmd`
> （把板端程序烧进板子，板子本身不随电脑搬家）→ `install.py --test` 验证。

---

## 6. 常见问题

| 现象 | 处理 |
|---|---|
| 提示找不到 CanMV 串口 | 换 USB 线/口；确认设备管理器里有 `CanMV (Interface 0) (COMx)`；关掉占用该口的程序（CanMV IDE、串口助手） |
| 推送报"端口被占用" | 稍等重试（钩子与脚本会短暂抢口，已有退避重试）；或关掉多余的手工脚本 |
| 板子完全没反应 / 进不去 REPL | **断电重启或重插 USB**（软件救不回）。恢复后 `python -c "import k230_push,sys;print(k230_push.detect_canmv_port())"` 看端口，再 `redeploy_agentscreen.cmd` |
| 重部署后图标/天气/信息栏没了 | 正常：soft reset 会清空屏上状态，跑 `python push_digest.py` 重推 |
| 屏上文字显示成方块 | 该字符不在板端字体里（emoji 一般没有）；改用中文/英文，或用 `make_icon.py` 画图标 |
| 屏上"少了一个字"/像被遮掉 | **板端字库缺字形**（不是排版问题）：实测 `莞`/`圳` 就没有，`东莞` 会显示成 `东`。用 `python glyphcheck.py "东莞"` 确认，天气脚本已自动避让（`中文城市→中文省→英文城市`）。自己写死字符串前先跑一次 `glyphcheck.py` |
| 中文乱码 | 钩子/脚本一律按 UTF-8 读写；若你自己写的脚本要读 WorkBuddy 事件，记得 `sys.stdin.buffer.read().decode("utf-8")` |
| 状态行颜色不对 | 状态段颜色建议显式传 `color`；板端兜底判色认「思考中 / 执行中」关键字 |
| 信息栏内容不滚动 | 内容超过 4 行才会滚；确认 `screen_status()` 里 `info_auto` 为 true，或按 K2 打开 |
| 高危命令被"卡住"等确认 | 这是副屏审批在起作用：看屏上确认框，按 K0（允许）/K1（拒绝），或 `set AGENTSCREEN_APPROVE_TIMEOUT=0` 关掉等待 |
| 想临时停掉所有推送（刷机时） | 在程序目录建一个空文件 `.as_quiet`，钩子检测到就直接退出；删掉即恢复 |
| 沙箱里跑 `codex_confirm.cmd --check` 报 `UtilBindVsockAnyPort: socket failed` | 沙箱禁了"调 Windows exe"和 socket，不是链路故障。改用 `python3 as_check.py status`（走文件桥） |
| 推大段内容后板子没反应 / 提示 `SyntaxError` | 单次下发超过约 4KB 被截断。用 `push_lines()` / `screen_info`（已自动分块），别直接下发巨大的 `info` 命令 |
| 串口会话突然变慢（0.2s → 1s+） | 多半是渲染线程被拖累：信息行折行、状态行文字宽度都有缓存，改动时别把缓存去掉；内容行数多时尤其明显 |

---

## 7. 卸载

```bat
python uninstall.py          :: 移除 WorkBuddy 里的连接器 + 钩子 + 开机自启（先备份）
```
程序文件仍在原目录，直接删掉文件夹即可。板子上的 `/sdcard/agent_screen.py`、`/sdcard/main.py`
可以留着（那本来就是开机自启的副屏服务），或自行删除。

---

## 8. 架构一览

```
WorkBuddy(电脑)                                    K230D(板子)
┌──────────────────────────────────────┐          ┌────────────────────────────┐
│ 对话 → MCP 工具 screen_*             │          │ /sdcard/main.py            │
│        └→ agent_screen_mcp.py        │          │   └→ agent_screen.py       │
│             ├ 内置 broker(127.0.0.1:8720) ────串口(USB-CDC, 115200)──→ cmd(json) │
│             └ 下载/上传(k230_push.py) │          │   · 渲染线程: 时钟/状态行/  │
│ 钩子 wb_status/wb_confirm            │          │     信息栏/图标/确认框      │
│        └→ agentscreen_client ────────┘          │   · 主线程回 REPL 待命      │
│ 常驻 digest_loop.py(每10分钟)        │          └────────────────────────────┘
└──────────────────────────────────────┘
```

- 全部通信走**串口 raw REPL**（不脱离 REPL、不用 `dupterm`），因此板子能长期稳定运行。
- 连接器进程内有个本地 broker，是 COM14 的**唯一入口**，钩子和脚本都经它排队，不再互相抢口。

> 更多实现细节见 `docs/`：`audio_stream_feasibility.md`（副屏音频可行性评估）、
> `codex_status_hook.md`（Codex 在副屏上做授权确认）。

---

## 9. 许可证

[MIT License](LICENSE) © 2026 pocean2001
