#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wb_status_hook.py — WorkBuddy 状态钩子: 自动把"任务运行状态"推到 K230D 副屏(AgentScreen)

由 WorkBuddy Hooks 调用: 从 stdin 读事件 JSON -> 解析出状态文本 -> **异步**(detached 子进程)
推送到副屏动态信息行。钩子本体立刻返回(约 0.4s), 绝不阻塞 WorkBuddy; 出错一律静默 exit 0。

子进程模式: 本脚本带 --push "<msg>" 参数时, 才真正经 COM14 发送。
"""
import sys, os, json, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
QUIET_FLAG = os.path.join(HERE, ".as_quiet")   # 存在则不推送(刷机/联调专用, 避免抢串口)
TASK_FILE = os.path.join(HERE, "_task.txt")    # 当前任务摘要(两个钩子共享, 让状态栏能显示"在做什么")
TASK_MAX = 28                                  # 任务摘要截断长度
MAXLEN = 90        # 状态行超长会自动水平慢速滚动, 不必截太短

# 状态行三色(与板端 STAGE_THINK/RUN/OTHER 一致)
STAGE_RED    = [240, 72, 72]
STAGE_YELLOW = [255, 208, 60]
STAGE_GREEN  = [60, 220, 110]


def set_task(t):
    try:
        with open(TASK_FILE, "w", encoding="utf-8") as f:
            f.write(t)
    except Exception:
        pass


def clear_task():
    try:
        os.remove(TASK_FILE)
    except Exception:
        pass


def read_task():
    try:
        with open(TASK_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def cur_task(use_task=True):
    """状态行的"当前任务"段 —— 作为独立字段下发, 由板端用固定浅蓝单独着色"""
    return read_task() if use_task else ""


def stage_color(msg):
    """思考中=红 / 执行中=黄 / 其它(任务完成·连接·提示等)=绿"""
    m = str(msg)
    if "思考中" in m:
        return STAGE_RED
    if "执行中" in m:
        return STAGE_YELLOW
    return STAGE_GREEN

# Windows: DETACHED_PROCESS(0x8) | CREATE_NEW_PROCESS_GROUP(0x200)
_DETACHED = 0x00000008 | 0x00000200


def build_message(data):
    event = data.get("hook_event_name", "") or ""
    tool = data.get("tool_name", "") or ""
    ti = data.get("tool_input", {}) or {}
    if event == "SessionStart":
        return "副屏已连接"
    if event == "UserPromptSubmit":
        return "思考中…"                     # 收到指令, 开始推理
    if event in ("PostToolUse", "PreCompact"):
        return "思考中…"                     # 工具跑完, 回到推理
    if event == "Stop":
        return "任务完成"
    if event == "SubagentStop":
        return "子任务完成"
    if event == "SessionEnd":
        return "会话结束"
    if event == "Notification":
        n = data.get("message") or data.get("notification") or ""
        return "提示: " + " ".join(str(n).split())[:MAXLEN]
    return None


def push(msg, use_task=True):
    """真正发送(在 detached 子进程里执行)"""
    task = cur_task(use_task)
    try:
        sys.path.insert(0, HERE)
        from k230_push import K230, detect_canmv_port
        port = os.environ.get("AGENTSCREEN_PORT") or detect_canmv_port()
        if not port:
            return
        dev = K230(port, 115200, fast=True)
        try:
            code = ("import sys\nsys.path.insert(0,'/sdcard')\nimport agent_screen as A\n"
                    "print('H'+A.cmd(%r))\n"
                    % json.dumps({"op": "stage", "text": msg,
                                  "color": stage_color(msg), "task": task}))
            dev.session(code, timeout=6)
        finally:
            dev.close()
    except Exception:
        pass


def _spawn(msg, use_task=True):
    """异步: 起一个 detached 子进程去推送, 本体立刻返回"""
    try:
        kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)
        if os.name == "nt":
            kw["creationflags"] = _DETACHED
        else:
            kw["start_new_session"] = True
        arg = "--push" if use_task else "--push-notask"
        subprocess.Popen([sys.executable, os.path.abspath(__file__), arg, msg], **kw)
    except Exception:
        pass


def _notify(msg, use_task=True):
    """优先经连接器 broker 发送(快、统一端口); broker 不通再起 detached 子进程直接推"""
    try:
        sys.path.insert(0, HERE)
        import agentscreen_client as C
        if C.fire({"op": "stage", "text": msg, "color": stage_color(msg),
                   "task": cur_task(use_task)}):
            return
    except Exception:
        pass
    _spawn(msg, use_task)


def main():
    if os.path.exists(QUIET_FLAG):
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] in ("--push", "--push-notask"):
        push(sys.argv[2], use_task=(sys.argv[1] == "--push"))
        return 0
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", "replace")  # 必须按 UTF-8 读, 否则中文乱码
        data = json.loads(raw) if raw and raw.strip() else {}
    except Exception:
        return 0
    event = data.get("hook_event_name", "") or ""
    if event == "SessionStart":
        clear_task()                            # 新会话: 清掉上一轮的任务摘要
    elif event == "UserPromptSubmit":
        p = data.get("prompt") or data.get("user_prompt") or ""
        p = " ".join(str(p).split())[:TASK_MAX]
        if p:
            set_task(p)                         # 记下"当前任务", 之后的状态行都会带上
    msg = build_message(data)
    if msg:
        # 完成/结束类事件不带任务前缀, 保持简短
        _notify(msg, use_task=(event not in ("Stop", "SubagentStop", "SessionEnd")))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
