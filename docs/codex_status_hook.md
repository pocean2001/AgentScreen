# Codex → K230D 副屏 状态推送

把 Codex 的**任务运行状态**推到 AgentScreen 副屏（和 WorkBuddy 的推送共用同一条链路、
同一个 broker），消息统一标注来源 `codex`。

## 链路

```
Codex Hook 事件(JSON/UTF-8, stdin)
  -> codex_status_hook.py            (解析状态, 加 [codex] 前缀 + source 字段)
  -> 127.0.0.1:8720 broker           (agent_screen_mcp.py 内的唯一入口, 独占 COM14)
  -> 板端 agent_screen.cmd({"op":"stage", ...})  -> 状态行(任务段 + 彩色状态段)
```

broker 不通时，脚本会另起一个 detached 子进程补发，并在子进程里退化为直连串口
（复用 `agentscreen_client.py` 的端口统一逻辑），本进程立即返回、绝不阻塞 Codex。

## 文件

| 文件 | 作用 |
|---|---|
| `codex_status_hook.py` | 钩子入口 + 发送逻辑（含 `--check` / `--test` 自检） |
| `codex_status.cmd` | Windows 侧启动器（自动找 Python，手动测试用） |
| `as_check.py` | 副屏自检 / 调试客户端（**只用标准库**）：`status` / `confirm` / `stage` / `raw` |
| `.codex/hooks.json` | 项目级钩子注册（Codex 在 D:\K230D 里启动时生效） |

## 生效条件

1. 在 **D:\K230D** 目录里启动 Codex（项目级 `.codex/hooks.json` 才会被读）；
   想在所有项目里生效，就把 `.codex/hooks.json` 里的条目合并到 `~/.codex/hooks.json`。
2. 首次运行会提示**信任这些钩子**（Codex 按内容哈希记录信任，改过 `hooks.json` 后会再问一次）。
   项目本身也要在 Codex 里处于 trusted。
3. 前提是 WorkBuddy 里 AgentScreen 连接器在跑（它才是 8720 broker、COM14 的唯一持有者）。

## 自检

```bat
:: 在 D:\K230D，用 WorkBuddy 自带的 Python（或任意 3.9+）
python codex_status_hook.py --check          :: 经 broker 读板子状态(含当前状态行)
python codex_status_hook.py --test 连路自检    :: 往状态行推一条
echo {"hook_event_name":"Stop"} | python codex_status_hook.py   :: 模拟一次钩子事件
```

WSL 里可以直接调 Windows 侧那条命令（就是 `hooks.json` 里的原文）：

```bash
/mnt/c/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
  'D:/K230D/codex_status_hook.py' --check
```

### 沙箱里怎么自检（文件桥）

Codex 的沙箱会同时禁掉 **socket**（`PermissionError: Operation not permitted`）和
**调用 Windows exe**（`UtilBindVsockAnyPort: socket failed`），所以上面那条命令在沙箱里跑不通
（是沙箱限制，不是链路故障）。但 `D:\K230D` 与 `/mnt/d/K230D` 是同一个目录，于是
broker 额外开了一条**文件桥**：

```
as_check.py  --(原子写 _asbridge_in.json)-->  broker 持锁开串口执行
as_check.py  <--(原子写 _asbridge_out.json, 带同一个 id)--  broker
```

```bash
python3 as_check.py status          # broker/板子通不通 + 板端状态(含当前状态行)
python3 as_check.py confirm -t 60   # 板上弹测试授权框, 按 K0/K1, 打印板上选择
python3 as_check.py stage "文本"     # 推一条状态行
python3 as_check.py raw '{"op":"status"}'   # 任意板端命令
```

先试 TCP `127.0.0.1:8720`，连不上才退到文件桥；`as_check.py` 只用标准库（不需要 pyserial）。
文件桥由 `agent_screen_mcp.py` 里的 `_bridge_loop` 提供，`AGENTSCREEN_BRIDGE=0` 可关闭；
**改完要重启一次 AgentScreen 连接器**才生效（旧 broker 只会看到 `_asbridge_in.json` 没人理）。
同一时刻只支持一个文件桥客户端（请求文件是单份的）。
安全上不多开口子：能往这个目录写文件的进程，本来就能直接改钩子脚本 / 抢 COM14，
文件桥仍在同一个本地信任边界内（板上按 K0/K1 的仍是人）。

## 事件 → 屏上文案

| Codex 事件 | 状态行文本 | 颜色 |
|---|---|---|
| `SessionStart` | `[codex] 已连接` | 绿 |
| `UserPromptSubmit` | `[codex] 思考中…`（任务段=提示词摘要） | 红 |
| `PreToolUse` | `[codex] 执行中… <工具名>` | 黄 |
| `PermissionRequest` | `[codex] 等待授权… <工具名>` | 黄 |
| `PostToolUse` / `PreCompact` | `[codex] 思考中…` / `压缩上下文…` | 红 |
| `SubagentStart` / `SubagentStop` | `[codex] 子任务开始…` / `子任务完成` | 黄 / 绿 |
| `Stop` | `[codex] 任务完成` | 绿 |
| `SessionEnd` | `[codex] 会话结束` | 绿 |
| `Interrupt` | `[codex] 已中断` | 绿 |

## 副屏授权(PermissionRequest → K0 直接允许)

`PermissionRequest` 事件不走状态推送, 而是走**副屏授权**: `codex_confirm_hook.py` 让副屏
弹出确认框(直选模式), 用户在板上按键后把结果作为 Codex 的 hook 决策返回。

```
Codex PermissionRequest(stdin JSON, 含 tool_name / tool_input)
  -> codex_confirm_hook.py
  -> broker 8720: {"op":"confirm","options":["允许","拒绝"],"direct":true}
  -> 板上: K0=允许 / K1=拒绝 (2 行各有自己的键, 不用移动高亮; 触屏同样可点)
  -> 轮询 {"op":"confirm_result"} 取回选择
  -> stdout: {"hookSpecificOutput":{"hookEventName":"PermissionRequest",
                                    "decision":{"behavior":"allow"|"deny"}}}
```

决策 JSON 的字段取自 Codex 官方 schema `permission-request.command.output`
(`decision.behavior` 只接受 `allow` / `deny`)。

**安全约定**: 只有板子明确回了「允许 / 拒绝」才输出决策;
超时、broker 不在、`CODEX_SCREEN_APPROVE=0`、存在 `.as_quiet` —— 一律**不输出任何内容**,
交回 Codex 自己的 TUI 授权流程。宁可多问一次, 绝不误授权。

副屏等待时长由 `CODEX_SCREEN_APPROVE_TIMEOUT`(默认 120s)决定;
`.codex/hooks.json` 里该钩子的 `timeout` 必须比它大(当前 180), 否则 Codex 会先杀掉钩子进程。

直选模式(`direct: true`)的行数为 3 键 + 1 触摸行, 所以**最多 4 个选项**;
超过 3 个选项、又需要键盘翻页的场景请用默认模式(K0/K1 移动 + K2 确认)。

自检:

```bat
codex_confirm.cmd --check     :: 看 broker/板子通不通
codex_confirm.cmd --test      :: 弹一个测试授权框, 打印板上选择(不输出决策 JSON)
```

## 可选环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `CODEX_SCREEN_SOURCE` | `codex` | 来源标注（改前缀文本与 `source` 字段） |
| `AGENTSCREEN_BROKER_HOST` | `127.0.0.1` | broker 主机 |
| `AGENTSCREEN_BROKER_PORT` | `8720` | broker 端口 |
| `CODEX_STATUS_DEBUG` | 关 | 置 1 时把发送失败原因写到 `_codex_status.log` |

## 注意事项

- **钩子脚本平时不往 stdout 输出任何内容**：PreToolUse/PermissionRequest 的 stdout 会被
  Codex 当作决策 JSON 解析，写错就报 `hook returned invalid ... JSON output`。
  唯一的例外是授权钩子：`codex_confirm_hook.py` 只在板上给出明确选择时才输出那一行决策 JSON。
  需要调试请用 `CODEX_STATUS_DEBUG=1` 看日志。
- 想临时全停（刷机/联调）：在程序目录建空文件 `.as_quiet`（与 WorkBuddy 钩子共用），删掉即恢复。
- `PreToolUse` / `PostToolUse` 每次工具调用都会起一次钩子进程（约 0.1–0.6s 开销）。
  嫌吵/嫌慢就把 `.codex/hooks.json` 里这两个事件删掉，只留 SessionStart / UserPromptSubmit / Stop。
- 如果改用 **Windows 版 Codex**（CODEX_HOME 在 Windows 侧），把 `hooks.json` 里的 command 换成：
  `cmd /d /s /c "D:\K230D\codex_status.cmd"`（授权那一条用 `codex_confirm.cmd`），
  WSL 调 Windows 的写法在纯 Windows 下不可用。
