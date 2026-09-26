#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codex_confirm_hook.py — 把 Codex 的授权请求弹到 K230D 副屏, 用板载键直接授权。

链路:
    Codex PermissionRequest Hook(事件 JSON 从 stdin)
      -> 本脚本: 经 broker(127.0.0.1:8720) 让副屏弹出确认框
         (direct 直选模式: K0=允许 / K1=拒绝, 不用移动高亮)
      -> 轮询 confirm_result 取回用户选择
      -> 往 stdout 输出 Codex 官方决策 JSON:
         {"hookSpecificOutput":{"hookEventName":"PermissionRequest",
                                "decision":{"behavior":"allow"|"deny"}}}

设计约定(与 codex_status_hook.py 一致):
  * **只在有明确结论时**才往 stdout 写那一行 JSON。超时 / 板子不在线 / 被 .as_quiet 关掉,
    都什么都不输出 → Codex 走它自己的 TUI 授权流程。宁可多问一次, 绝不误授权。
  * 只走 broker, 不直连串口(避免和连接器抢 COM14)。
  * 任何异常都静默 exit 0, 不阻塞 Codex。

用法:
  python codex_confirm_hook.py                 # 钩子入口(stdin 读事件 JSON)
  python codex_confirm_hook.py --json '{...}'  # 手动喂一个事件 JSON
  python codex_confirm_hook.py --json-file ev.json   # 同上, 从文件读(避免命令行引号问题)
  python codex_confirm_hook.py --check         # 自检: 经 broker 读板子状态
  python codex_confirm_hook.py --test          # 自检: 弹一个测试授权框并打印板上选择

环境变量:
  CODEX_SCREEN_APPROVE          置 0/off 关闭副屏授权(等于不输出决策)
  CODEX_SCREEN_APPROVE_TIMEOUT  副屏等待秒数(默认 120; hooks.json 的 timeout 要更大)
  AGENTSCREEN_BROKER_HOST/PORT  broker 地址(默认 127.0.0.1:8720)
  CODEX_STATUS_DEBUG            置 1 时把失败原因写到 _codex_status.log
"""
import sys
import os
import json
import time
import socket

HERE = os.path.dirname(os.path.abspath(__file__))
QUIET_FLAG = os.path.join(HERE, ".as_quiet")
LOG_FILE = os.path.join(HERE, "_codex_status.log")
TRACE_FILE = os.path.join(HERE, "_codex_confirm.log")   # 每次执行都留一行(排查"钩子到底跑没跑")

BROKER_HOST = os.environ.get("AGENTSCREEN_BROKER_HOST", "127.0.0.1")
BROKER_PORT = int(os.environ.get("AGENTSCREEN_BROKER_PORT", "8720"))
SOURCE = (os.environ.get("CODEX_SCREEN_SOURCE") or "codex").strip() or "codex"

OPT_ALLOW = "允许"
OPT_DENY = "拒绝"

STAGE_WAIT = [255, 208, 60]      # 等待授权(黄)
STAGE_ALLOW = [60, 220, 110]     # 已授权(绿)
STAGE_DENY = [240, 72, 72]       # 已拒绝(红)

TITLE_MAX = 40
CMD_MAX = 160


def dbg(msg):
    if not os.environ.get("CODEX_STATUS_DEBUG"):
        return
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def trace(msg):
    """无条件留痕: 钩子没跑 vs 跑了但没弹框, 靠这个区分(文件超 200KB 就清空重来)。"""
    try:
        if os.path.exists(TRACE_FILE) and os.path.getsize(TRACE_FILE) > 200000:
            os.remove(TRACE_FILE)
        with open(TRACE_FILE, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _clean(s, n):
    return " ".join(str(s or "").split())[:n]


def broker_call(obj, timeout=10.0):
    """经 broker 发一条命令并读回执。任何失败返回 None —— 不退化直连串口。
    broker 的应答格式: {"ok":bool, "result":{...}} / {"ok":false,"err":...}"""
    try:
        s = socket.create_connection((BROKER_HOST, BROKER_PORT), timeout)
    except Exception as e:
        dbg("broker connect failed: %r" % e)
        return None
    try:
        s.settimeout(timeout)
        s.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            d = s.recv(4096)
            if not d:
                break
            buf += d
    except Exception as e:
        dbg("broker io failed: %r" % e)
        return None
    finally:
        try:
            s.close()
        except Exception:
            pass
    line = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    if not line:
        return None
    try:
        r = json.loads(line)
    except Exception as e:
        dbg("broker bad reply %r: %r" % (line[:120], e))
        return None
    return r.get("result") if r.get("ok") else None


def stage(text, color):
    broker_call({"op": "stage", "text": "%s %s" % (SOURCE_TAG, text), "color": list(color),
                 "source": SOURCE, "agent": "codex"}, timeout=6)


SOURCE_TAG = "[%s]" % SOURCE


def summarize(tool_input):
    """把 tool_input 压成一行给副屏看(优先命令/路径这种关键字段)。"""
    if isinstance(tool_input, dict):
        for key in ("command", "cmd", "path", "file_path", "url", "query", "pattern"):
            v = tool_input.get(key)
            if isinstance(v, str) and v.strip():
                return _clean(v, CMD_MAX)
        try:
            return _clean(json.dumps(tool_input, ensure_ascii=False), CMD_MAX)
        except Exception:
            return ""
    if tool_input is None:
        return ""
    return _clean(tool_input, CMD_MAX)


def ask_board(tool, cmd, timeout):
    """弹框等用户选择。返回 '允许' / '拒绝' / None(超时或板子不可用)。"""
    text = "Codex 请求授权"
    if tool:
        text += ": " + tool
    if cmd:
        text += "\n" + cmd
    r = broker_call({"op": "confirm", "text": text[:TITLE_MAX + CMD_MAX + 32],
                     "options": [OPT_ALLOW, OPT_DENY], "direct": True,
                     "timeout": int(timeout)}, timeout=12)
    if r is None:
        dbg("confirm push failed (broker/board unavailable)")
        return None
    r = None
    t0 = time.time()
    while (time.time() - t0) < (timeout + 15):
        rr = broker_call({"op": "confirm_result"}, timeout=10)
        if rr and rr.get("answered"):
            r = rr.get("result")
            break
        time.sleep(0.3)
    broker_call({"op": "clear", "what": "confirm"}, timeout=10)
    dbg("board answer: %r" % (r,))
    return r if r in (OPT_ALLOW, OPT_DENY) else None


def emit(behavior, message=None):
    """按 Codex 官方 permission-request.command.output schema 输出决策。"""
    decision = {"behavior": behavior}
    if message:
        decision["message"] = message
    out = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(data):
    if str(data.get("hook_event_name") or "") != "PermissionRequest":
        return 0
    trace("event: PermissionRequest tool=%s" % _clean(data.get("tool_name"), TITLE_MAX))
    if os.path.exists(QUIET_FLAG):
        trace("skip: .as_quiet")
        return 0
    if str(os.environ.get("CODEX_SCREEN_APPROVE", "1")).lower() in ("0", "off", "no", "false"):
        trace("skip: CODEX_SCREEN_APPROVE=0")
        return 0
    tool = _clean(data.get("tool_name"), TITLE_MAX)
    cmd = summarize(data.get("tool_input"))
    try:
        timeout = int(os.environ.get("CODEX_SCREEN_APPROVE_TIMEOUT") or 120)
    except Exception:
        timeout = 120
    stage("等待授权… %s" % tool, STAGE_WAIT)
    ans = ask_board(tool, cmd, timeout)
    if ans == OPT_ALLOW:
        trace("answer: 允许 -> allow")
        stage("已授权: %s" % tool, STAGE_ALLOW)
        emit("allow")
    elif ans == OPT_DENY:
        trace("answer: 拒绝 -> deny")
        stage("已拒绝: %s" % tool, STAGE_DENY)
        emit("deny", "用户在 K230D 副屏上拒绝了该操作")
    else:
        trace("answer: 无(超时/板子不可用) -> 不输出决策")
        stage("授权超时, 交回 Codex 询问", STAGE_WAIT)
    return 0


def main(argv):
    if argv and argv[0] in ("--check", "--test"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if argv and argv[0] == "--check":
        r = broker_call({"op": "status"}, timeout=10)
        print(json.dumps(r, ensure_ascii=False, indent=2) if r is not None
              else "[错误] broker %s:%d 无应答 —— 副屏连接器没在跑, 或板子没连上"
                   "\n       (在 WSL/Codex 沙箱里这属正常: 沙箱禁 socket 与 Windows exe,"
                   " 改用 `python3 as_check.py status`, 它走 broker 的文件桥)"
                   % (BROKER_HOST, BROKER_PORT))
        return 0
    if argv and argv[0] == "--test":
        stage("等待授权… (自检)", STAGE_WAIT)
        ans = ask_board("自检", "python codex_confirm_hook.py --test", 60)
        print("板上选择: %s" % (ans or "超时/未选择"))
        return 0
    if argv and argv[0] == "--json-file":
        try:
            with open(argv[1], "rb") as f:
                raw = f.read().decode("utf-8", "replace")
        except Exception as e:
            dbg("read event file failed: %r" % e)
            return 0
    elif argv and argv[0] == "--json":
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
    try:
        return handle(data)
    except Exception as e:
        dbg("handle failed: %r" % e)
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
