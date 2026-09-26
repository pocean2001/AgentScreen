#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agentscreen_client.py — AgentScreen 端口统一入口

优先走"连接器里的 broker"(本地 socket, 连接器是 COM14 的唯一持有者, 内部串行化),
broker 不可用时才退回直接开串口。这样钩子/脚本就不会各自抢 COM14。
协议: 每行一个 JSON; 请求体就是 agent_screen.cmd 的 op dict。
"""
import sys, os, json, socket, time

HERE = os.path.dirname(os.path.abspath(__file__))
BROKER_PORT = int(os.environ.get("AGENTSCREEN_BROKER_PORT", "8720"))
READY_STAMP = os.path.join(HERE, ".as_ready")   # "已做过自愈" 的时间戳(避免频繁重做)
last_error = ""      # 最近一次失败的原因(给调用方做可读报错)


INFO_CHUNK = 16      # 每块行数: 保证单次下发 < ~3.6KB(板端 CDC 超 ~4KB 会丢字节)


def push_lines(lines, chunk=INFO_CHUNK, auto=True):
    """分块推送多行信息(首块替换, 其余追加)。

    为什么要分块: 板端 raw REPL 单次 paste 超过约 4KB 就会丢字节 -> SyntaxError + 会话挂住。
    内容一多(几十行)必须拆开传。
    """
    lines = [str(x) for x in lines if str(x) != ""]
    if not lines:
        return call({"op": "info", "text": ""})
    r = None
    for i in range(0, len(lines), chunk):
        obj = {"op": "info", "lines": lines[i:i + chunk], "auto": auto}
        if i:
            obj["append"] = True
        r = call(obj)
        if not r:
            return None
    return r


def _touch_ready():
    try:
        with open(READY_STAMP, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def ready_plan(st):
    """根据 status 返回值判断需要补什么 -> (need_time, need_weather)
    天气缺"文字"或"城市"都算需要补(城市由 IP 定位, 首次会有)"""
    year = 0
    try:
        year = int(str((st or {}).get("now") or "")[:4])
    except Exception:
        pass
    w = (st or {}).get("weather") or {}
    return (year < 2020), (not w.get("text") or not w.get("city"))


def ensure_ready(max_age=300, force=False, verbose=False):
    """连上副屏后自愈: 时间不对就同步、天气没值就补拉。

    默认 300 秒内不重复做（避免每次推送都多跑两次串口会话）。
    返回 dict，例如 {"time": "ok"|True|False, "weather": "ok"|True|False,"error":...}
    """
    try:
        if not force and (time.time() - os.path.getmtime(READY_STAMP)) < max_age:
            return {"skipped": True}
    except OSError:
        pass

    res = {}
    st = call({"op": "status"}, timeout=6)
    if not st:
        res["error"] = last_error or "板子无应答"
        return res
    need_time, need_weather = ready_plan(st)
    if need_time:
        res["time"] = bool(call({"op": "time"}, timeout=6))
    else:
        res["time"] = "ok"
    if need_weather:
        try:
            sys.path.insert(0, HERE)
            import push_weather as W                      # 延迟导入, 避免循环依赖
            icon, text, city = W.fetch_weather()          # city 由出口 IP 定位
            res["weather"] = bool(call({"op": "weather", "icon": icon,
                                        "text": text, "city": city}, timeout=8))
            res["weather_city"] = city
            if verbose:
                res["weather_text"] = text
        except Exception as e:
            res["weather"] = "err %r" % e
    else:
        res["weather"] = "ok"
    _touch_ready()
    return res


def explain():
    """推送失败时返回一段可读的排查说明(设备未连接 / 串口被占 / 板子卡死)"""
    msgs = []
    if last_error:
        msgs.append("原因: %s" % last_error)
    try:
        sys.path.insert(0, HERE)
        from k230_push import detect_canmv_port, port_report
        if not detect_canmv_port():
            msgs.append("[错误] 未检测到 K230D（CanMV）串口 —— 设备可能没有连接。本机串口:")
            msgs.append(port_report())
            msgs.append("请检查: 1) USB 线/口是否插好  2) 设备管理器是否有 'CanMV (Interface 0) (COMx)'"
                        "  3) 串口是否被 CanMV IDE/串口助手占用  4) 板子是否卡死(重插 USB 或断电重启)")
        else:
            msgs.append("串口存在但通信失败: 板子可能卡死(重插 USB / 断电重启), 或端口被其它程序占用")
    except Exception as e:
        msgs.append("(无法进一步诊断: %r)" % e)
    return "\n".join(msgs)


def fire(obj, timeout=1.5):
    """发完就走(不等回复) —— 适合状态推送这类不关心结果、且不能阻塞的场景。返回是否已发出"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", BROKER_PORT))
        s.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        s.close()
        return True
    except Exception:
        return False


def call(obj, timeout=12.0):
    """发并等结果; broker 不通则退回直接开串口。失败返回 None(原因见 last_error / explain())
    超时给到 12s: 钩子会密集占用串口, broker 排队可能要等好几秒"""
    global last_error
    last_error = ""
    r = _broker_call(obj, timeout=timeout)
    if r is not None:
        return r
    return _direct(obj)


def _broker_call(obj, timeout=12.0):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", BROKER_PORT))
        s.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            d = s.recv(4096)
            if not d:
                break
            buf += d
        s.close()
        line = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
        if not line:
            return None
        r = json.loads(line)
        return r.get("result") if r.get("ok") else None
    except Exception:
        return None


def _direct(obj, timeout=8, retries=3):
    """直连兜底: 串口可能被 broker / 钩子的事务瞬时占用, 退避重试几次再报错"""
    global last_error
    r = None
    for i in range(max(1, retries)):
        r = _direct_once(obj, timeout)
        if r is not None:
            return r
        if i + 1 < retries:
            time.sleep(1.5)      # 等别人那次 open→exec→close 走完
    return None


def _direct_once(obj, timeout=8):
    global last_error
    try:
        sys.path.insert(0, HERE)
        from k230_push import K230, detect_canmv_port
        port = os.environ.get("AGENTSCREEN_PORT") or detect_canmv_port()
        if not port:
            last_error = "未识别到 K230D（CanMV）串口（设备未连接？）"
            return None
        dev = K230(port, 115200, fast=False)   # 多试几次, 抗钩子瞬时占用
        try:
            code = ("import sys\nsys.path.insert(0,'/sdcard')\nimport agent_screen as A\n"
                    "print('ASR'+A.cmd(%r))\n" % json.dumps(obj, ensure_ascii=False))
            out, err = dev.session(code, timeout=timeout)
            txt = out.decode("utf-8", "replace")
            j = txt.rfind("ASR")
            if j < 0:
                last_error = "板子无应答（可能卡死/被占用）: %s" % txt.strip()[:120]
                return None
            k = txt.find("{", j)
            return json.loads(txt[k:].strip()) if k >= 0 else None
        finally:
            dev.close()
    except Exception as e:
        last_error = "%r" % e
        return None
