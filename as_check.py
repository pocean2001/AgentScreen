#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""as_check.py — AgentScreen 副屏自检 / 调试客户端（只用标准库, 不需要 pyserial）

为什么要有它:
  Codex 在 WSL 沙箱里跑时, 既不能建 socket(Operation not permitted), 也不能调
  Windows 的 python.exe(UtilBindVsockAnyPort: socket failed) —— 于是
  `codex_confirm_hook.py --check` 这类自检在沙箱里跑不起来。
  但 D:\\K230D 与 /mnt/d/K230D 是同一个目录, 所以 broker 额外开了一条**文件桥**:
    请求 -> 原子写 _asbridge_in.json  -> broker 持锁开串口执行
    应答 -> broker 原子写 _asbridge_out.json -> 本脚本按 id 认领
  本脚本两条通道都试: 先 socket(127.0.0.1:8720), 不通自动退到文件桥。

用法:
  python3 as_check.py status                 # broker/板子通不通 + 板端状态
  python3 as_check.py confirm [-t 60]        # 板上弹测试授权框, 打印板上选择(K0=允许)
  python3 as_check.py stage "执行中: 自检"    # 推一条状态行
  python3 as_check.py raw '{"op":"status"}'  # 任意板端命令(调试用)
退出码: 0=成功, 2=超时/无应答
"""
import json
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE_IN = os.path.join(HERE, "_asbridge_in.json")
BRIDGE_OUT = os.path.join(HERE, "_asbridge_out.json")
BRIDGE_POLL = 0.2

HOST = os.environ.get("AGENTSCREEN_BROKER_HOST", "127.0.0.1")
PORT = int(os.environ.get("AGENTSCREEN_BROKER_PORT", "8720"))

CH_SOCKET = "socket %s:%d" % (HOST, PORT)
CH_BRIDGE = "文件桥 %s" % BRIDGE_IN

USED = [None]          # 记录最终用的是哪条通道


def call_socket(obj, timeout):
    """经 TCP broker 发一条命令。连不上返回 (None, 'unreachable'), 其余返回 (结果, 错误)。"""
    try:
        s = socket.create_connection((HOST, PORT), timeout)
    except Exception:
        return None, "unreachable"
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
        return None, "socket io failed: %r" % (e,)
    finally:
        try:
            s.close()
        except Exception:
            pass
    line = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    if not line:
        return None, "broker 空应答"
    try:
        rep = json.loads(line)
    except Exception as e:
        return None, "broker 应答不是 JSON(%r): %s" % (e, line[:120])
    USED[0] = CH_SOCKET
    if rep.get("ok"):
        return rep.get("result"), None
    return None, "broker 报错: %s" % rep.get("err")


def call_bridge(obj, timeout):
    """经共享目录里的文件桥发一条命令(broker 需要是新版, 已含 _bridge_loop)。"""
    rid = "%d-%d" % (os.getpid(), int(time.time() * 1000) % 100000000)
    req = dict(obj)
    req["id"] = rid
    req["ts"] = time.time()          # broker 用它丢弃"客户端已超时"的过期请求
    for p in (BRIDGE_IN, BRIDGE_OUT):
        try:
            os.remove(p)
        except OSError:
            pass
    tmp = BRIDGE_IN + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(req, ensure_ascii=False))
    os.replace(tmp, BRIDGE_IN)
    t0 = time.time()
    while (time.time() - t0) < timeout:
        raw = ""
        if os.path.exists(BRIDGE_OUT):
            try:
                with open(BRIDGE_OUT, "r", encoding="utf-8") as f:
                    raw = f.read()
                os.remove(BRIDGE_OUT)
            except OSError:
                raw = ""
        if raw.strip():
            try:
                rep = json.loads(raw)
            except ValueError:
                rep = None
            if isinstance(rep, dict) and rep.get("id") == rid:
                USED[0] = CH_BRIDGE
                if rep.get("ok"):
                    return rep.get("result"), None
                return None, "broker 报错: %s" % rep.get("err")
        time.sleep(BRIDGE_POLL)
    try:
        os.remove(BRIDGE_IN)         # 别留过期请求给以后的 broker 执行
    except OSError:
        pass
    return None, None


def call(obj, timeout=15.0):
    r, err = call_socket(obj, timeout)
    if err != "unreachable":
        return r, err
    return call_bridge(obj, timeout)


def die(msg, hint=True):
    sys.stdout.write("[错误] %s\n" % msg)
    if hint:
        sys.stdout.write("       (broker 没跑 / 板子没连 / 文件桥未启用 —— 新版 broker 要重启一次"
                         " AgentScreen 连接器才带上文件桥)\n")
    return 2


def cmd_status():
    r, err = call({"op": "status"}, 15)
    if err or r is None:
        return die(err or "无应答", hint=(err is None))
    print("通道: %s" % USED[0])
    print(json.dumps(r, ensure_ascii=False, indent=2, sort_keys=True))
    stage = (r.get("stage") or {}) if isinstance(r, dict) else {}
    if isinstance(stage, dict) and stage.get("text"):
        print("状态行: %s" % stage.get("text"))
    return 0


def cmd_stage(text):
    r, err = call({"op": "stage", "text": text, "source": "as_check", "agent": "script"}, 15)
    if err or r is None:
        return die(err or "无应答", hint=(err is None))
    print("通道: %s -> 状态行已推送: %s" % (USED[0], text))
    return 0


def cmd_confirm(wait):
    r, err = call({"op": "confirm", "text": "AgentScreen 自检\npython3 as_check.py confirm",
                   "options": ["允许", "拒绝"], "direct": True, "timeout": int(wait)}, 15)
    if err or r is None:
        return die(err or "无应答", hint=(err is None))
    print("通道: %s -> 板上已弹框, 按 K0=允许 / K1=拒绝 (等 %ds)…" % (USED[0], int(wait)))
    ans = None
    t0 = time.time()
    while (time.time() - t0) < (wait + 10):
        rr, e2 = call({"op": "confirm_result"}, 10)
        if e2:
            print("[警告] 轮询出错: %s" % e2)
        if rr and rr.get("answered"):
            ans = rr.get("result")
            break
        time.sleep(0.4)
    call({"op": "clear", "what": "confirm"}, 10)
    print("板上选择: %s" % (ans or "超时/未选择"))
    return 0 if ans else 2


def cmd_raw(args):
    try:
        obj = json.loads(args)
    except ValueError as e:
        return die("JSON 解析失败: %r" % (e,))
    r, err = call(obj, 20)
    if err or r is None:
        return die(err or "无应答", hint=(err is None))
    print("通道: %s" % USED[0])
    print(json.dumps(r, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    name, rest = argv[0], argv[1:]
    if name == "status":
        return cmd_status()
    if name == "stage":
        if not rest:
            return die("用法: as_check.py stage \"文本\"")
        return cmd_stage(" ".join(rest))
    if name == "confirm":
        wait = 60
        if rest and rest[0] in ("-t", "--timeout"):
            try:
                wait = int(rest[1])
            except Exception:
                return die("-t 后面要跟秒数")
        return cmd_confirm(wait)
    if name == "raw":
        if not rest:
            return die("用法: as_check.py raw '{\"op\":\"status\"}'")
        return cmd_raw(" ".join(rest))
    return die("未知子命令: %s (可用: status / confirm / stage / raw)" % name)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
