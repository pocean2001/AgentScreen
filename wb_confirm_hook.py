#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wb_confirm_hook.py — WorkBuddy PreToolUse 钩子 (副屏"正在执行"状态 + 高危审批)

1) 状态: 每次工具调用都把「⚙ 正在执行: <简述>」异步推到副屏动态信息行(不阻塞)。
2) 审批: 对"有风险"的 Bash 命令(删除/格式化/推送/关机等), 在副屏弹确认框, 等用户
   触屏点按或按板载 K0/K1/K2, 把结果作为 permissionDecision 返回; 非风险命令直接放行。

子进程模式: --status "<msg>" 只推送状态(异步子进程用)。
任何时候都 exit 0; 出错静默。
"""
import sys, os, json, re, time, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
QUIET_FLAG = os.path.join(HERE, ".as_quiet")   # 存在则该标志时不推送(刷机/联调专用, 避免抢串口)
TIMEOUT = int(os.environ.get("AGENTSCREEN_APPROVE_TIMEOUT", "60"))
OPT_ALLOW, OPT_DENY = "允许", "拒绝"
_DETACHED = 0x00000008 | 0x00000200        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

RISKY = [
    r"rm\s+-[a-zA-Z]*[rR]",          # rm 带 r(递归): -r/-rf/-fr
    r"\brm\s+/(?:\s|$)",             # rm /
    r"\bdel\b.*\s/s\b", r"\brmdir\b.*\s/s\b",
    r"\bformat\b", r"\bmkfs", r"\bdiskpart\b", r"\bdd\s+if=", r">\s*/dev/sd",
    r"\bcipher\b\s*/w", r"\bvssadmin\b", r"\bbcdedit\b",
    r"git\s+push", r"git\s+reset\s+--hard",
    r"\bshutdown\b", r"\breboot\b", r"reg\s+delete", r"Remove-Item.*-Recurse",
]
_RISKY_RE = [re.compile(p, re.IGNORECASE) for p in RISKY]

# 状态行三色(与板端一致)
STAGE_RED    = [240, 72, 72]
STAGE_YELLOW = [255, 208, 60]
STAGE_GREEN  = [60, 220, 110]

TASK_FILE = os.path.join(HERE, "_task.txt")   # 当前任务摘要(wb_status_hook 写入, 这里读)


def read_task():
    try:
        with open(TASK_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def stage_color(msg):
    """思考中=红 / 执行中=黄 / 其它=绿。用"包含"判断, 加任务前缀也不会判错色。"""
    m = str(msg)
    if "思考中" in m:
        return STAGE_RED
    if "执行中" in m:
        return STAGE_YELLOW
    return STAGE_GREEN


def is_risky(tool, ti):
    return tool == "Bash" and any(r.search(str(ti.get("command", ""))) for r in _RISKY_RE)


def brief_of(tool, ti):
    """给状态行用的简短描述(纯文本, 避免字体无对应字形)。
    放宽到 120 字 —— 状态行超长会自动水平慢速滚动, 不必截太短。"""
    one = lambda s: " ".join(str(s).split())[:120]
    if tool == "Bash":
        return "执行中: " + one(ti.get("command", ""))
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return "执行中: 写 " + one(ti.get("file_path", tool))
    if tool == "Read":
        return "执行中: 读 " + one(os.path.basename(str(ti.get("file_path", ""))) or "file")
    if tool == "WebFetch":
        return "执行中: 访问 " + one(ti.get("url", "web"))
    if tool == "WebSearch":
        return "执行中: 搜索 " + one(ti.get("query", "search"))
    return ("执行中: " + one(tool)) if tool else None


def _session_code(obj):
    return ("import sys\nsys.path.insert(0,'/sdcard')\nimport agent_screen as A\n"
            "print('ASR'+A.cmd(%r))\n" % json.dumps(obj, ensure_ascii=False))


def _push(msg):
    """真正推送到副屏状态行(在子进程里跑)"""
    task = read_task()
    try:
        sys.path.insert(0, HERE)
        from k230_push import K230, detect_canmv_port
        port = os.environ.get("AGENTSCREEN_PORT") or detect_canmv_port()
        if not port:
            return
        dev = K230(port, 115200, fast=True)
        try:
            dev.session(_session_code({"op": "stage", "text": msg,
                                       "color": stage_color(msg), "task": task}), timeout=6)
        finally:
            dev.close()
    except Exception:
        pass


def _spawn_status(msg):
    try:
        kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)
        if os.name == "nt":
            kw["creationflags"] = _DETACHED
        else:
            kw["start_new_session"] = True
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--status", msg], **kw)
    except Exception:
        pass


def _notify(msg):
    """优先经连接器 broker 发送(快、统一端口); broker 不通再起 detached 子进程直接推"""
    try:
        sys.path.insert(0, HERE)
        import agentscreen_client as C
        if C.fire({"op": "stage", "text": msg, "color": stage_color(msg),
                   "task": read_task()}):
            return
    except Exception:
        pass
    _spawn_status(msg)


def _send(dev, obj):
    out, err = dev.session(_session_code(obj), timeout=8)
    txt = out.decode("utf-8", "replace")
    j = txt.rfind("ASR")
    if j < 0:
        return None
    k = txt.find("{", j)
    if k < 0:
        return None
    try:
        return json.loads(txt[k:].strip())
    except Exception:
        return None


def ask_board(text):
    """返回 '允许' / '拒绝' / None"""
    try:
        sys.path.insert(0, HERE)
        from k230_push import K230, detect_canmv_port
        port = os.environ.get("AGENTSCREEN_PORT") or detect_canmv_port()
        if not port:
            return None
        dev = K230(port, 115200, fast=True)
        try:
            # direct: K0 直接允许 / K1 直接拒绝(不移动高亮), 与 README 的按键说明一致
            _send(dev, {"op": "confirm", "text": text, "options": [OPT_ALLOW, OPT_DENY],
                        "direct": True, "timeout": TIMEOUT})
            t0 = time.time()
            while (time.time() - t0) < TIMEOUT:
                r = _send(dev, {"op": "confirm_result"})
                if r and r.get("answered"):
                    _send(dev, {"op": "clear", "what": "confirm"})
                    return r.get("result")
                time.sleep(0.3)
            _send(dev, {"op": "clear", "what": "confirm"})
        finally:
            dev.close()
    except Exception:
        pass
    return None


def main():
    if os.path.exists(QUIET_FLAG):
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "--status":
        _push(sys.argv[2])
        return 0
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", "replace")
        data = json.loads(raw) if raw and raw.strip() else {}
    except Exception:
        return 0
    if data.get("hook_event_name") != "PreToolUse":
        return 0
    tool = data.get("tool_name", "") or ""
    ti = data.get("tool_input", {}) or {}

    b = brief_of(tool, ti)                     # 1) 状态: 异步推, 不阻塞
    if b:
        _notify(b)

    if not is_risky(tool, ti):                 # 2) 非风险: 直接放行
        return 0
    res = ask_board("允许执行?  %s\n%s" % (tool, str(ti.get("command", ""))[:60]))
    if res == OPT_ALLOW:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "permissionDecisionReason": "副屏审批: 允许"}}, ensure_ascii=False))
    elif res == OPT_DENY:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "副屏审批: 拒绝"}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
