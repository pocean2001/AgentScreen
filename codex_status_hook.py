#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codex_status_hook.py — 把 Codex 的运行状态推到 K230D 副屏(AgentScreen)。

链路:
    Codex Hook 事件(JSON/UTF-8, stdin)
      -> 本脚本(解析出状态文本, 统一标注来源 codex)
      -> 设备串口的 broker 127.0.0.1:8720  (agent_screen_mcp.py 里的唯一入口, 持有 COM14)
      -> 板端 agent_screen.cmd({"op":"stage", ...})  -> 状态行

设计约定:
  * 钩子必须立刻返回: 快路径是 broker 的 fire-and-forget(不等回执); broker 不通时另起
    detached 子进程补发(子进程里再退化为直连串口)。本进程绝不阻塞 Codex。
  * 任何异常都静默 exit 0, 且**不往 stdout 写任何内容** —— 免得被 Codex 当成 hook 决策 JSON。
  * 消息统一带 source="codex", 状态行文本前缀 "[codex] ...", 和 WorkBuddy 的推送区分开。

用法:
  python codex_status_hook.py                  # Codex Hook 入口: 事件 JSON 从 stdin 读
  python codex_status_hook.py --json '{...}'   # 手动喂一个事件 JSON
  python codex_status_hook.py --check          # 自检: 经 broker 读板子状态并打印
  python codex_status_hook.py --test [文本]     # 自检: 推一条到状态行
  python codex_status_hook.py --send-json '{}'  # 内部用: 补发一个 payload

环境变量:
  CODEX_SCREEN_SOURCE       来源名(默认 codex)
  AGENTSCREEN_BROKER_HOST   broker 主机(默认 127.0.0.1)
  AGENTSCREEN_BROKER_PORT   broker 端口(默认 8720)
  CODEX_STATUS_DEBUG=1      出错时追加写 _codex_status.log
"""
import sys
import os
import json
import time
import socket
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
QUIET_FLAG = os.path.join(HERE, ".as_quiet")        # 存在则完全不推(刷机/联调)
LOG_FILE = os.path.join(HERE, "_codex_status.log")

BROKER_HOST = os.environ.get("AGENTSCREEN_BROKER_HOST", "127.0.0.1")
BROKER_PORT = int(os.environ.get("AGENTSCREEN_BROKER_PORT", "8720"))
SOURCE = (os.environ.get("CODEX_SCREEN_SOURCE") or "codex").strip() or "codex"
TAG = "[%s]" % SOURCE

TASK_MAX = 24        # 任务摘要截断长度
TOOL_MAX = 16        # 工具名截断长度
MSG_MAX = 60         # 通知文本截断长度

RED = [240, 72, 72]          # 思考中
YELLOW = [255, 208, 60]      # 执行中
GREEN = [60, 220, 110]       # 完成/提示

# Codex hook 事件 -> (状态行文本, 颜色)
EVENTS = {
    "SessionStart":      ("已连接", GREEN),
    "UserPromptSubmit":  ("思考中…", RED),
    "PreToolUse":        ("执行中…", YELLOW),
    "PermissionRequest": ("等待授权…", YELLOW),
    "PostToolUse":       ("思考中…", RED),
    "PreCompact":        ("压缩上下文…", RED),
    "PostCompact":       ("继续思考…", RED),
    "SubagentStart":     ("子任务开始…", YELLOW),
    "SubagentStop":      ("子任务完成", GREEN),
    "Stop":              ("任务完成", GREEN),
    "SessionEnd":        ("会话结束", GREEN),
    "Interrupt":         ("已中断", GREEN),
}

# Windows: DETACHED_PROCESS(0x8) | CREATE_NEW_PROCESS_GROUP(0x200)
_DETACHED = 0x00000008 | 0x00000200


def dbg(msg):
    if not os.environ.get("CODEX_STATUS_DEBUG"):
        return
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def _clean(s, n):
    return " ".join(str(s or "").split())[:n]


def build_payload(data):
    """Codex 事件 JSON -> 板端 stage 命令(带来源标注)。不认识的/无需展示的事件返回 None。"""
    data = data or {}
    ev = str(data.get("hook_event_name") or "").strip()
    if ev == "Notification":
        msg = _clean(data.get("message") or data.get("notification"), MSG_MAX)
        if not msg:
            return None
        text, color = "提示: " + msg, GREEN
    elif ev in EVENTS:
        text, color = EVENTS[ev]
    else:
        return None

    if ev in ("PreToolUse", "PermissionRequest"):
        tool = _clean(data.get("tool_name"), TOOL_MAX)
        if tool:
            text = "%s %s" % (text, tool)

    payload = {"op": "stage",
               "text": "%s %s" % (TAG, text),
               "color": list(color),
               "source": SOURCE,          # 板端忽略未知字段, 供上层/日志识别来源
               "agent": "codex"}
    if ev == "UserPromptSubmit":
        task = _clean(data.get("prompt") or data.get("user_prompt"), TASK_MAX)
        if task:
            payload["task"] = task         # 状态行的"当前任务"段
    return payload


def fire(payload, timeout=2.0):
    """经 broker 直发, 不等回执。True = 已交给 broker。"""
    try:
        s = socket.create_connection((BROKER_HOST, BROKER_PORT), timeout)
    except Exception as e:
        dbg("broker connect failed: %r" % e)
        return False
    try:
        s.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        return True
    except Exception as e:
        dbg("broker send failed: %r" % e)
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def spawn_send(payload):
    """broker 不通: 起 detached 子进程补发(子进程里会退化成直连串口)。"""
    try:
        kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)
        if os.name == "nt":
            kw["creationflags"] = _DETACHED
        else:
            kw["start_new_session"] = True
        subprocess.Popen([sys.executable, os.path.abspath(__file__),
                          "--send-json", json.dumps(payload, ensure_ascii=False)], **kw)
    except Exception as e:
        dbg("spawn failed: %r" % e)


def send_via_client(payload):
    """补发: 先 broker, 再退回直连串口(复用 agentscreen_client 的端口统一逻辑)。"""
    if fire(payload):
        return True
    try:
        sys.path.insert(0, HERE)
        import agentscreen_client as C
        return bool(C.call(payload, timeout=8))
    except Exception as e:
        dbg("direct send failed: %r" % e)
        return False


def broker_raw(obj, timeout=10.0):
    """同步发一条命令并等原始回执(仅自检用)。无回执返回 None。"""
    s = socket.create_connection((BROKER_HOST, BROKER_PORT), timeout)
    buf = b""
    try:
        s.settimeout(timeout)
        s.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        while b"\n" not in buf:
            d = s.recv(4096)
            if not d:
                break
            buf += d
    finally:
        try:
            s.close()
        except Exception:
            pass
    line = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    return json.loads(line) if line else None


def main(argv):
    if argv and argv[0] in ("--check", "--test"):
        try:                       # 手动自检时按 UTF-8 输出, 免得中文变成乱码
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if argv and argv[0] == "--send-json":
        send_via_client(json.loads(argv[1]))
        return 0

    if argv and argv[0] == "--check":
        try:
            r = broker_raw({"op": "status"})
        except Exception as e:
            r = None
            dbg("check failed: %r" % e)
        if r is None:
            print("[错误] broker %s:%d 无应答 —— 副屏连接器没在跑, 或板子没连上"
                  "\n       (在 WSL/Codex 沙箱里这属正常: 沙箱禁 socket 与 Windows exe,"
                  " 改用 `python3 as_check.py status`, 它走 broker 的文件桥)"
                  % (BROKER_HOST, BROKER_PORT))
        elif not r.get("ok"):
            print("[错误] broker 回执失败: %s" % r.get("err"))
        else:
            print(json.dumps(r.get("result"), ensure_ascii=False, indent=2))
        return 0

    if argv and argv[0] == "--test":
        text = _clean(argv[1] if len(argv) > 1 else "连路自检", MSG_MAX)
        payload = {"op": "stage", "text": "%s %s" % (TAG, text), "color": list(GREEN),
                   "source": SOURCE, "agent": "codex"}
        if send_via_client(payload):
            print("已发送: " + json.dumps(payload, ensure_ascii=False))
        else:
            print("[错误] 发送失败 —— broker/串口都不通")
        return 0

    if os.path.exists(QUIET_FLAG):          # 静默开关(与 WorkBuddy 钩子共用)
        return 0

    if argv and argv[0] == "--json":
        raw = argv[1]
    else:
        try:
            raw = sys.stdin.buffer.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
    try:
        data = json.loads(raw) if raw and raw.strip() else {}
    except Exception as e:
        dbg("bad event json: %r" % e)
        data = {}

    payload = build_payload(data)
    if not payload:
        return 0
    if not fire(payload):
        spawn_send(payload)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:
        dbg("fatal: %r" % e)
        sys.exit(0)
