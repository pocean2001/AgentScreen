#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent_screen_mcp.py — WorkBuddy 侧 "AgentScreen" 连接器 (MCP stdio server)
把消息文字 / 图片 / 音频 / 时钟指令推送到 K230D 副屏(COM14)。

设计: 通过 K230D 的 raw REPL 调用板上 agent_screen.cmd(json) (不占用/脱离 REPL, 避免卡死板子)。
      host <--USB-CDC COM14--> K230D (agent_screen.py 后台线程渲染)
"""
import sys, os, json, base64, zlib, tempfile, time as _time
import socket as _socket, threading as _threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from k230_push import K230, detect_canmv_port  # 复用已验证的安全串口通道

PORT = os.environ.get("AGENTSCREEN_PORT") or None   # 可环境变量指定, 否则自动识别 CanMV 口
BAUD = int(os.environ.get("AGENTSCREEN_BAUD", "115200"))
UPLOAD_PREFIX = "/sdcard/as_"

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {"name": "screen_text", "description": "在副屏指定位置显示一段文字",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string"},
         "x": {"type": "integer", "default": 20}, "y": {"type": "integer", "default": 20},
         "size": {"type": "integer", "default": 40},
         "color": {"type": "array", "items": {"type": "integer"}, "default": [255, 255, 255]},
         "ttl": {"type": "integer", "default": 0, "description": "存活秒数, 0=常驻"}},
         "required": ["text"]}},
    {"name": "screen_image", "description": "把本地图片推到副屏指定位置显示(自动上传到板子)",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "本地图片路径(png/jpg)"},
         "x": {"type": "integer", "default": 0}, "y": {"type": "integer", "default": 0},
         "scale": {"type": "number", "default": 1.0},
         "ttl": {"type": "integer", "default": 0}},
         "required": ["path"]}},
    {"name": "screen_audio", "description": "把本地 wav 推到副屏播放",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}}, "required": ["path"]}},
    {"name": "screen_info", "description": "设置/追加副屏『动态信息行』文字(支持多行, 留空清除)。超过 4 行会在信息区自动上下滚屏查看",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string"},
         "lines": {"type": "array", "items": {"type": "string"},
                   "description": "一次性设置多行(优先于 text); 可给几十行, 屏上滚动查看"},
         "append": {"type": "boolean", "default": False, "description": "true=追加一行, false=替换整块"},
         "auto": {"type": "boolean", "default": True, "description": "推入后是否自动滚屏(默认开)"}},
         "required": []}},
    {"name": "screen_scroll", "description": "副屏信息栏上下滚屏(内容超过可见 4 行时)。也可用板载 K0=上翻 / K1=下翻 / K2=开关自动滚",
     "inputSchema": {"type": "object", "properties": {
         "delta": {"type": "integer", "default": 1, "description": "行数, 正=下翻, 负=上翻"},
         "auto": {"type": "boolean", "description": "是否开启自动滚屏; 省略则手动翻页后自动关闭"},
         "auto_ms": {"type": "integer", "description": "自动滚屏速度(毫秒/行), 省略则沿用当前值(默认2800)"}},
         "required": []}},
    {"name": "screen_stage", "description": "设置副屏『状态行』(独立一行, 位于信息区上方)。分两段: task 段固定绿色、text 段按状态着色(思考中=红/执行=黄/其它=绿)",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string", "description": "状态段文字, 如 '执行中: python x.py'"},
         "task": {"type": "string", "description": "当前任务段(固定绿色); 传空串清除"},
         "color": {"type": "array", "items": {"type": "integer"},
                   "description": "[r,g,b], 省略则按文字自动着色"},
         "task_color": {"type": "array", "items": {"type": "integer"},
                        "description": "任务段颜色 [r,g,b], 省略则沿用当前值(默认绿色)"},
         "speed": {"type": "number",
                   "description": "超长时水平滚动速度(像素/秒), 省略则沿用当前值(默认45)"}},
         "required": ["text"]}},
    {"name": "screen_clock", "description": "显示/隐藏副屏大字体时钟",
     "inputSchema": {"type": "object", "properties": {
         "show": {"type": "boolean", "default": True}}, "required": []}},
    {"name": "screen_set_time", "description": "对时: 设置板子 RTC 时间(YYYY-MM-DD HH:MM:SS)",
     "inputSchema": {"type": "object", "properties": {
         "value": {"type": "string"}}, "required": ["value"]}},
    {"name": "screen_sync_time", "description": "对时: 把副屏时钟同步为当前主机时间",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "screen_clear", "description": "清除副屏叠加层(overlays/info/confirm/all)",
     "inputSchema": {"type": "object", "properties": {
         "what": {"type": "string", "default": "overlays"}}, "required": []}},
    {"name": "screen_weather", "description": "在日期行显示 城市+天气图标+文字(如 city=东莞, icon=sun, text='26° 晴'); 不传则清除",
     "inputSchema": {"type": "object", "properties": {
         "icon": {"type": "string", "description": "sun/clear/cloud/overcast/rain/shower/snow/thunder/fog/moon/wind"},
         "text": {"type": "string", "description": "如 '26° 晴'"},
         "city": {"type": "string", "description": "城市名(留空则沿用板上已有的, 或用 push_weather 自动按 IP 定位)"}},
         "required": []}},
    {"name": "screen_icon", "description": "推送一张小图标到副屏『下半部分图标位』(左下角); 自动等比缩放到图标框内再上传",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "本地图片路径(png/jpg/bmp)"},
         "box": {"type": "integer", "default": 0, "description": "统一尺寸(px), 0=默认 128x128"},
         "ttl": {"type": "integer", "default": 0, "description": "存活秒数, 0=常驻"},
         "clear": {"type": "boolean", "default": False, "description": "true=清除图标(可不传 path)"}},
         "required": []}},
    {"name": "screen_confirm", "description": "在副屏弹出确认框, 等用户在板上选择后返回。默认: K0/K1 上下移高亮(长按连发)、K2 确认, 选项超 4 个自动窗口滚动; direct=true 时改为直选: K0/K1/K2 直接对应第 1/2/3 项(授权场景按 K0 即允许)。两种模式都可触屏点按",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string"},
         "options": {"type": "array", "items": {"type": "string"},
                     "description": "候选选项(最多 16 个, 一屏显示 4 行, 其余滚动查看; direct=true 时最多 4 个); 省略则用 yes/no"},
         "yes": {"type": "string", "default": "是"},
         "no": {"type": "string", "default": "否"},
         "direct": {"type": "boolean", "default": False,
                    "description": "true=直选模式: K0/K1/K2 直接命中前 3 个选项, 不需要移动高亮"},
         "timeout": {"type": "integer", "default": 60, "description": "等待秒数"}},
         "required": ["text"]}},
    {"name": "screen_status", "description": "查询副屏服务状态",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _conn(fast=False):
    port = PORT or detect_canmv_port()
    if not port:
        raise RuntimeError(require_canmv_port_err())
    # fast=True: 少重试。broker 里必须用 —— 它在持锁状态下开串口, 默认 14 次重试
    # 会让锁被占住好几秒, 把并发请求排成长队(实测会拖到客户端超时).
    return K230(port, BAUD, fast=fast)


def require_canmv_port_err():
    """板子没连上时给 Agent 一段可读的报错(含串口清单)"""
    try:
        from k230_push import port_report
        return ("未检测到 K230D（CanMV）串口 —— 设备可能没有连接。\n本机串口:\n"
                + port_report() +
                "\n请检查: USB 线/口、设备管理器是否有 'CanMV (Interface 0) (COMx)'、"
                "串口是否被 CanMV IDE 等占用、板子是否卡死(重插/断电重启);"
                " 或设 AGENTSCREEN_PORT=COMx 指定串口")
    except Exception:
        return "未识别 K230D CanMV 串口, 请设 AGENTSCREEN_PORT=COMx"


_last_time_check = [0.0]
_last_weather_check = [0.0]


def _ensure_ready(dev, force=False):
    """连接后自愈（"连上副屏就自动更新时间和天气"）:
      ① 时间: 距上次检查超过 30s 就查一次, 年份<2020 则同步为主机时间
      ② 天气: 距上次检查超过 300s 就查一次, 板上没有天气就补拉并推送
    首次调用即生效; 板子重启(soft reset 清空天气)后也会自动补回。"""
    now = _time.time()
    want_time = force or (now - _last_time_check[0]) >= 30
    want_weather = force or (now - _last_weather_check[0]) >= 300
    if not (want_time or want_weather):
        return
    try:
        st = _exec_cmd(dev, {"op": "status"}) or {}
    except Exception:
        return
    if want_time:
        _last_time_check[0] = now
        s = str(st.get("now", ""))
        y = int(s[:4]) if s[:4].isdigit() else 0
        if y < 2020:
            import datetime
            v = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _exec_cmd(dev, {"op": "time", "value": v})
    if want_weather:
        _last_weather_check[0] = now
        w = st.get("weather") or {}
        if not w.get("text") or not w.get("city"):        # 缺文字或缺城市都补
            try:
                import push_weather as W          # 延迟导入, 避免循环依赖
                icon, text, city = W.fetch_weather()      # city 由出口 IP 定位
                _exec_cmd(dev, {"op": "weather", "icon": icon, "text": text, "city": city})
            except Exception:
                pass


def _exec_cmd(dev, obj):
    code = ("import sys\nsys.path.insert(0,'/sdcard')\n"
            "import agent_screen as A\nprint('ASR'+A.cmd(%r))\n" % json.dumps(obj, ensure_ascii=False))
    out, err = dev.session(code, timeout=20)
    if err:
        raise RuntimeError("板端执行错误: " + err.decode("utf-8", "replace"))
    txt = out.decode("utf-8", "replace")
    i = txt.rfind("ASR")
    if i < 0:
        raise RuntimeError("未收到板端应答: " + txt)
    return json.loads(txt[i + 3:].strip())


def _upload(dev, local):
    if not os.path.isfile(local):
        raise RuntimeError("本地文件不存在: " + local)
    dest = UPLOAD_PREFIX + os.path.basename(local)
    n, c = dev.upload(local, dest)
    return dest, n


ICON_BOX_DEFAULT = int(os.environ.get("AGENTSCREEN_ICON_BOX", "128"))


def _prep_icon(local, box):
    """把图标统一归一化成 box x box 的不透明 PNG（等比缩放 + 黑底居中补边）。
    没有 Pillow / 处理失败则原样返回本地路径。输出到临时目录, 不污染源目录。"""
    try:
        from PIL import Image as _PILImage
    except Exception:
        return local
    try:
        im = _PILImage.open(local)
        w, h = im.size
        if w <= 0 or h <= 0:
            return local
        # 统一尺寸: 等比缩放进 box 方框, 再居中贴到 box x box 画布(黑底)
        sc = min(float(box) / w, float(box) / h)
        nw, nh = max(1, int(round(w * sc))), max(1, int(round(h * sc)))
        if (nw, nh) != (w, h):
            im = im.resize((nw, nh), _PILImage.LANCZOS)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            src = _PILImage.new("RGB", im.size, (0, 0, 0))
            src.paste(im, mask=im.split()[3])         # alpha 合成到黑底
        else:
            src = im.convert("RGB")
        canvas = _PILImage.new("RGB", (box, box), (0, 0, 0))
        canvas.paste(src, ((box - src.size[0]) // 2, (box - src.size[1]) // 2))
        tag = "%08x" % (zlib.crc32(os.path.abspath(local).encode("utf-8")) & 0xFFFFFFFF)
        out = os.path.join(tempfile.gettempdir(), "as_icon_%s_%d.png" % (tag, box))
        canvas.save(out, "PNG", optimize=True)
        return out
    except Exception:
        return local


def _confirm(dev, text, yes="是", no="否", timeout=60, options=None, direct=False):
    """弹确认框并轮询结果(每次轮询约 4s, 与板端节奏一致)。
    默认: K0/K1 移动高亮 + K2 确认; direct=True: K0/K1/K2 直接选第 1/2/3 项。"""
    obj = {"op": "confirm", "text": text, "yes": yes, "no": no, "timeout": timeout}
    if options:
        obj["options"] = options
    if direct:
        obj["direct"] = True
    _exec_cmd(dev, obj)
    t0 = _time.time()
    while (_time.time() - t0) < (timeout + 15):
        r = _exec_cmd(dev, {"op": "confirm_result"})
        if r.get("answered"):
            _exec_cmd(dev, {"op": "clear", "what": "confirm"})
            return r
        _time.sleep(0.3)
    _exec_cmd(dev, {"op": "clear", "what": "confirm"})
    return {"answered": False, "result": "timeout"}


def dispatch(name, args):
    dev = _conn()
    try:
        if name != "screen_status":
            _ensure_ready(dev)         # 连接后自愈: 自动对时 + 缺天气就补拉(首次/每30s·每300s自检)
        if name == "screen_text":
            return _exec_cmd(dev, {"op": "text", "text": args["text"],
                                   "x": args.get("x", 20), "y": args.get("y", 20),
                                   "size": args.get("size", 40),
                                   "color": args.get("color", [255, 255, 255]),
                                   "ttl": args.get("ttl", 0)})
        if name == "screen_info":
            obj = {"op": "info", "append": args.get("append", False)}
            if "auto" in args:
                obj["auto"] = args["auto"]
            if "lines" in args:
                lines = [str(x) for x in args["lines"]]
                # 内容多时必须分块: 板端 raw REPL 单次 paste 超过约 4KB 会丢字节 -> SyntaxError
                if len(json.dumps(lines, ensure_ascii=False)) > 3400:
                    r = None
                    for i in range(0, len(lines), 16):
                        part = {"op": "info", "lines": lines[i:i + 16]}
                        if i or obj["append"]:
                            part["append"] = True
                        if "auto" in args:
                            part["auto"] = args["auto"]
                        r = _exec_cmd(dev, part)
                        if not r:
                            return r
                    return r
                obj["lines"] = lines
            else:
                obj["text"] = args.get("text", "")
            return _exec_cmd(dev, obj)
        if name == "screen_scroll":
            obj = {"op": "scroll", "delta": args.get("delta", 1)}
            if "auto" in args:
                obj["auto"] = args["auto"]
            if args.get("auto_ms"):
                obj["auto_ms"] = args["auto_ms"]
            return _exec_cmd(dev, obj)
        if name == "screen_stage":
            obj = {"op": "stage", "text": args.get("text", "")}
            if args.get("color"):
                obj["color"] = args["color"]
            if args.get("speed"):
                obj["speed"] = args["speed"]
            if "task" in args:
                obj["task"] = args.get("task") or ""
            if args.get("task_color"):
                obj["task_color"] = args["task_color"]
            return _exec_cmd(dev, obj)
        if name == "screen_clock":
            return _exec_cmd(dev, {"op": "clock", "show": args.get("show", True)})
        if name == "screen_set_time":
            return _exec_cmd(dev, {"op": "time", "value": args["value"]})
        if name == "screen_sync_time":
            import datetime
            v = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return _exec_cmd(dev, {"op": "time", "value": v})
        if name == "screen_clear":
            return _exec_cmd(dev, {"op": "clear", "what": args.get("what", "overlays")})
        if name == "screen_weather":
            obj = {"op": "weather", "icon": args.get("icon"), "text": args.get("text")}
            if args.get("city") is not None:
                obj["city"] = args.get("city")
            return _exec_cmd(dev, obj)
        if name == "screen_confirm":
            return _confirm(dev, args["text"], args.get("yes", "是"),
                            args.get("no", "否"), int(args.get("timeout", 60)),
                            args.get("options"), bool(args.get("direct")))
        if name == "screen_status":
            return _exec_cmd(dev, {"op": "status"})
        if name == "screen_image":
            _exec_cmd(dev, {"op": "pause"})          # 暂停渲染 -> 上传提速约 10x
            try:
                dest, n = _upload(dev, args["path"])
            finally:
                _exec_cmd(dev, {"op": "resume"})
            return _exec_cmd(dev, {"op": "image", "path": dest,
                                   "x": args.get("x", 0), "y": args.get("y", 0),
                                   "scale": args.get("scale", 1.0),
                                   "ttl": args.get("ttl", 0)})
        if name == "screen_icon":
            if args.get("clear") or not args.get("path"):
                return _exec_cmd(dev, {"op": "icon"})        # 无 path = 清除图标
            box = int(args.get("box") or ICON_BOX_DEFAULT)
            src = _prep_icon(args["path"], box)
            _exec_cmd(dev, {"op": "pause"})              # 暂停渲染 -> 上传提速
            try:
                dest, n = _upload(dev, src)
            except Exception:
                _exec_cmd(dev, {"op": "resume"})
                raise
            # resume 合并进 icon 命令, 省一次串口会话
            r = _exec_cmd(dev, {"op": "icon", "path": dest, "box": box,
                                "ttl": args.get("ttl", 0), "resume": True})
            if isinstance(r, dict):
                r["uploaded"] = {"src": src, "bytes": n, "dest": dest}
            return r
        if name == "screen_audio":
            _exec_cmd(dev, {"op": "pause"})
            try:
                dest, n = _upload(dev, args["path"])
            finally:
                _exec_cmd(dev, {"op": "resume"})
            return _exec_cmd(dev, {"op": "audio", "path": dest})
        raise RuntimeError("未知工具: " + name)
    finally:
        dev.close()


# ------------------------- MCP stdio -------------------------
def _write(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(msg_id, result):
    _write({"jsonrpc": "2.0", "id": msg_id, "result": result})


def _error(msg_id, code, message):
    _write({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        _result(mid, {"protocolVersion": PROTOCOL_VERSION,
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "AgentScreen", "version": "1.0.0"}})
    elif method == "tools/list":
        _result(mid, {"tools": TOOLS})
    elif method == "tools/call":
        p = msg.get("params", {})
        name = p.get("name")
        args = p.get("arguments", {}) or {}
        try:
            res = dispatch(name, args)
            _result(mid, {"content": [{"type": "text",
                                       "text": json.dumps(res, ensure_ascii=False)}],
                          "isError": False})
        except Exception as e:
            _result(mid, {"content": [{"type": "text", "text": "[AgentScreen错误] " + repr(e)}],
                          "isError": True})
    elif method in ("notifications/initialized", "notifications/cancelled"):
        pass
    elif method == "ping":
        _result(mid, {})
    else:
        if mid is not None:
            _error(mid, -32601, "method not found: %s" % method)


# ------------------------- 端口 broker (COM14 唯一入口) -------------------------
BROKER_PORT = int(os.environ.get("AGENTSCREEN_BROKER_PORT", "8720"))
_BROKER_LOCK = _threading.Lock()

# 文件桥: 给"没有 socket 权限 / 调不了 Windows exe"的一侧(WSL 沙箱里的 Codex)留一条旁路。
# 请求方把 {"id":..., "op":...} 原子写入 _asbridge_in.json, broker 执行完写 _asbridge_out.json。
BRIDGE_IN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_asbridge_in.json")
BRIDGE_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_asbridge_out.json")
BRIDGE_POLL = 0.2
BRIDGE_STALE = 30.0                 # 请求超过这个岁数就丢弃(客户端早超时了, 免得事后突然弹框)


def _broker_handle(conn):
    """处理一个客户端请求: 串行化, 打开->执行->关闭 (不在请求间长期占用端口)"""
    try:
        data = b""
        while b"\n" not in data and len(data) < 65536:
            d = conn.recv(4096)
            if not d:
                break
            data += d
        if not data:
            return
        obj = json.loads(data.split(b"\n", 1)[0].decode("utf-8", "replace"))
        res = _run_op(obj)
        try:
            conn.sendall((json.dumps({"ok": True, "result": res}, ensure_ascii=False) + "\n").encode("utf-8"))
        except Exception:
            pass                       # 客户端 fire-and-forget 已关闭, 正常
    except Exception as e:
        try:
            conn.sendall((json.dumps({"ok": False, "err": repr(e)}, ensure_ascii=False) + "\n").encode("utf-8"))
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _run_op(obj):
    """持有 broker 锁 -> 开关一次串口 -> 执行一条板端命令。
    socket broker 与文件桥共用: 无论从哪条路进来, COM14 都只有一个使用者。"""
    with _BROKER_LOCK:
        dev = _conn(fast=True)              # 持锁期间开串口要快, 否则请求排队超时
        try:
            return _exec_cmd(dev, obj)
        finally:
            dev.close()


def _bridge_write(obj):
    tmp = BRIDGE_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False))
    os.replace(tmp, BRIDGE_OUT)             # 原子替换: 读方不会看到半截 JSON


def _bridge_loop():
    """文件桥轮询线程(每 BRIDGE_POLL 秒看一眼 _asbridge_in.json)。"""
    while True:
        try:
            if os.path.exists(BRIDGE_IN):
                raw = ""
                try:
                    with open(BRIDGE_IN, "r", encoding="utf-8") as f:
                        raw = f.read()
                except Exception:
                    pass
                try:
                    os.remove(BRIDGE_IN)    # 立刻摘掉, 免得下轮重复执行
                except Exception:
                    pass
                req = None
                if raw.strip():
                    try:
                        req = json.loads(raw)
                    except Exception:
                        req = None
                if isinstance(req, dict) and req.get("id") is not None:
                    ts = req.get("ts")
                    if isinstance(ts, (int, float)) and (_time.time() - ts) > BRIDGE_STALE:
                        req = None          # 过期请求(客户端已超时) -> 丢掉
                if isinstance(req, dict) and req.get("id") is not None:
                    obj = dict((k, v) for k, v in req.items() if k != "id")
                    rid = req.get("id")
                    try:
                        res = _run_op(obj)
                        _bridge_write({"id": rid, "ok": True, "result": res})
                    except Exception as e:
                        _bridge_write({"id": rid, "ok": False, "err": repr(e)})
        except Exception:
            pass
        _time.sleep(BRIDGE_POLL)


def _broker_loop(port):
    try:
        srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(16)
    except Exception:
        return                          # 端口被占(已有 broker) 就静默退出
    while True:
        try:
            conn, _ = srv.accept()
        except Exception:
            continue
        _threading.Thread(target=_broker_handle, args=(conn,), daemon=True).start()


def main():
    _threading.Thread(target=_broker_loop, args=(BROKER_PORT,), daemon=True).start()
    if str(os.environ.get("AGENTSCREEN_BRIDGE", "1")).lower() not in ("0", "off", "no", "false"):
        _threading.Thread(target=_bridge_loop, daemon=True).start()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        try:
            handle(msg)
        except Exception as e:
            sys.stderr.write("handle err: %r\n" % e)
            sys.stderr.flush()


if __name__ == "__main__":
    main()
