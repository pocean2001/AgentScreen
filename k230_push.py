#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
k230_push.py — K230D (正点原子 DNK230D) CanMV MicroPython 下发 / 运行 工具（自包含）

依赖: pyserial  (python -m pip install pyserial)

用法示例:
  python k230_push.py --list                       # 列出串口, 找 CanMV 口
  python k230_push.py --selftest                   # 下发内置自检脚本并回读输出
  python k230_push.py --file app.py                # RAM 中运行(前台, 回读 stdout); 适用于会结束的脚本
  python k230_push.py --file clock.py --persist    # 固化到 /sdcard/main.py(开机自启), 不立即运行
  python k230_push.py --file clock.py --dest /sdcard/clock.py --run
                                                   # 分块上传到指定路径并在后台线程启动 main()
  python k230_push.py --port COM14 --file x.py     # 手动指定串口

关键设计(踩坑得到的经验):
  * 开串口固定 dtr=False/rts=False —— 否则会复位/卡死板子。
  * raw REPL 回包协议异于标准 MicroPython: OK + stdout + \\x04\\x04 + '>'。
  * 写文件一律用 "分块 + 每块独立会话", 避免: 大 paste 丢字节 / 单会话多次 exec 卡死。
  * 死循环脚本(如时钟显示)用后台线程启动, 主线程立即返回。
"""
import sys, os, time, argparse, base64

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.stderr.write("缺少 pyserial, 请先: python -m pip install pyserial\n")
    raise

BAUD = 115200
CHUNK = 2048                      # 每块原始字节; b64 后约 2731 字符, 单条 paste ~2.8KB(< ~4KB 丢字节阈值)
MAX_CODE = 3600                   # 单次 exec 的代码上限(字节)。实测 >=4KB 板端 CDC 丢字节 ->
                                  # 板端 SyntaxError 且会话挂住等到 timeout。超长内容要分块下发,
                                  # 见 agentscreen_client.push_lines()。
READ_TMO = 0.05                   # 串口读超时(秒)。必须小: read(n) 凑不满 n 字节时会白等到 timeout
RAW_END = b"\x04\x04"             # 本固件 raw REPL 结束符(双 0x04)
RAW_BANNER = b"raw REPL; CTRL-B to exit"

SELFTEST = (
    "import sys, os\n"
    "print('=== K230D link selftest ===')\n"
    "print('OK from host')\n"
    "print('Python:', sys.version)\n"
    "try:\n"
    "    print('uname:', os.uname())\n"
    "except Exception as e:\n"
    "    print('uname err:', e)\n"
    "print('=== END ===')\n"
)


CANMV_VIDPID = ((0x1209, 0xABD1),)   # 实测 K230D CanMV CDC 的 VID/PID(描述不标准时的兜底)
_PORT_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".as_port")


def port_infos():
    """本机所有串口 + 描述 + VID/PID"""
    out = []
    for p in list_ports.comports():
        out.append({"device": p.device, "desc": (p.description or "").strip(),
                    "vid": p.vid, "pid": p.pid})
    return out


def list_all_ports():
    return [(i["device"], i["desc"]) for i in port_infos()]


def _port_score(i):
    """3=描述含 canmv / 2=VID:PID 匹配 / 1=像 USB 串口 / 0=其它"""
    d = i["desc"].lower()
    if "canmv" in d:
        return 3
    if i["vid"] is not None and (i["vid"], i["pid"]) in CANMV_VIDPID:
        return 2
    if "usb serial" in d or "cdc" in d or "composite" in d:
        return 1
    return 0


def read_port_cache():
    try:
        with open(_PORT_CACHE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def write_port_cache(port):
    try:
        with open(_PORT_CACHE, "w", encoding="utf-8") as f:
            f.write(port)
    except OSError:
        pass


def detect_canmv_port():
    """自动识别 K230D 所在串口；找不到返回 None。
    顺序: 唯一描述含 canmv > 唯一 VID/PID 匹配 > 上次成功的端口(且仍在)"""
    infos = port_infos()
    best = [i for i in infos if _port_score(i) >= 3]
    if len(best) == 1:
        return best[0]["device"]
    vp = [i for i in infos if _port_score(i) >= 2]
    if len(vp) == 1:
        return vp[0]["device"]
    cached = read_port_cache()
    if cached and any(i["device"] == cached for i in infos):
        return cached
    return None


def port_report():
    """给报错用的可读串口清单"""
    infos = port_infos()
    if not infos:
        return "  (本机没有枚举到任何串口)"
    lines = []
    for i in infos:
        s = _port_score(i)
        tag = "   <-- 看起来就是 K230D" if s >= 3 else ("   <-- VID/PID 像 CanMV" if s == 2 else "")
        vp = " [%04x:%04x]" % (i["vid"], i["pid"]) if i["vid"] is not None else ""
        lines.append("  %-8s %s%s%s" % (i["device"], i["desc"] or "(无描述)", vp, tag))
    return "\n".join(lines)


def require_canmv_port():
    """探测板子串口；找不到则打印可操作的报错并退出（供各入口脚本启动时调用）"""
    p = detect_canmv_port()
    if p:
        return p
    raise SystemExit(
        "[错误] 未检测到 K230D（CanMV）串口 —— 设备可能没有连接。\n"
        "本机串口清单:\n" + port_report() + "\n"
        "请依次检查:\n"
        "  1) USB 线是否插好（插板子的 USB-C 数据口，别用只供电的线/口）\n"
        "  2) 设备管理器里是否出现 'CanMV (Interface 0) (COMx)'；\n"
        "     若显示'未知 USB 设备(设备描述符请求失败)'，是板子 USB 没起来 -> 给板子断电重启\n"
        "  3) 该串口是否被占用（CanMV IDE / 串口助手 / 另一个脚本），关掉再试\n"
        "  4) 板子是否卡死 -> 重插 USB 或断电重启\n"
        "  5) 描述不标准/多块板子时，显式指定: set AGENTSCREEN_PORT=COM14\n")


class K230:
    def __init__(self, port, baud=BAUD, timeout=2, fast=False):
        attempts = 2 if fast else 14     # 端口常被钩子/连接器瞬时占用, 退避重试(~5s)
        last = None
        for _ in range(attempts):
            try:
                self.s = serial.Serial(port, baud, timeout=timeout)
                break
            except serial.SerialException as e:
                last = e
                time.sleep(0.4)
        else:
            raise SystemExit(
                "无法打开 %s: %s\n"
                "  → 端口不存在/未枚举: 重插 USB、换线/换口、板子断电重启。\n"
                "  → 被占用(常见: 钩子/连接器/串口助手同时占用): 关掉占用程序或稍后重试。" % (port, last))
        self.s.dtr = False            # 防 DTR 复位
        self.s.rts = False
        self.port = port
        write_port_cache(port)        # 记住这个能用的口, 下次描述不标准时兜底
        # 关键: 串口读超时设小。read(64) 在只收到几个字节时会阻塞到超时;
        # 用 2s 时每个 exec 会白等 ~2s(实测 5.9s/会话的主因)。外层 read_until 本就轮询。
        self.s.timeout = READ_TMO
        self.fast = fast              # True=少重试、短超时(hook 等不能拖慢流程的场景)
        time.sleep(0.2)

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass

    # ---------- 底层 ----------
    def read_until(self, marker, timeout=8):
        buf = b""
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                c = self.s.read(64)
            except Exception:
                c = b""
            if not c:
                time.sleep(0.005)
                continue
            buf += c
            if marker in buf[-(len(marker) + 128):]:
                return buf
        return buf

    def _at_prompt(self):
        """前台 REPL 是否已在 '>>>' 提示符(应用跑在后台线程时通常就是)。
        是则无需 Ctrl-C 突发, 可省 ~1.8s/会话。"""
        try:
            self.s.flushInput()
            self.s.write(b"\r\n")
            return b">>>" in self.read_until(b">>>", timeout=1.2)
        except Exception:
            return False

    def _enter_raw(self):
        """打断前台代码并进入 raw REPL。只等 banner(可靠同步点), 不等 '>' 提示符。
        注意: 板子若在前台跑死循环(main.py), Ctrl-C 有时会触发 soft reboot, 需多发几次、
        每次留足时间, 再重试几次 Ctrl-A, 否则容易误判为"卡死"。"""
        if self.fast:                     # 快速模式: 最坏 ~2s 就放弃, 绝不拖慢调用方
            self.s.write(b"\x03\x03")
            time.sleep(0.2)
            self.s.flushInput()
            self.s.write(b"\r\x01")
            if RAW_BANNER in self.read_until(RAW_BANNER, timeout=1.5):
                return
            raise RuntimeError("进入 raw REPL 失败(fast)")
        if self._at_prompt():             # 已在提示符 -> 直接进 raw REPL
            self.s.write(b"\r\x01")
            if RAW_BANNER in self.read_until(RAW_BANNER, timeout=2):
                return
        for _ in range(6):
            self.s.write(b"\x03")
            time.sleep(0.3)
        self.s.flushInput()
        for _ in range(3):
            self.s.write(b"\r\x01")       # Ctrl-A 进 raw REPL
            if RAW_BANNER in self.read_until(RAW_BANNER, timeout=3):
                return
            time.sleep(0.3)
            self.s.flushInput()
        raise RuntimeError("进入 raw REPL 失败(板子可能卡死, 需物理重插/断电)")

    def _exit_raw(self):
        self.s.write(b"\x02")             # Ctrl-B 回正常 REPL
        time.sleep(0.05)
        self.s.flushInput()

    def exec_raw(self, code, run_timeout=30):
        """在 raw REPL 下执行代码, 返回 (stdout_bytes, error_bytes)"""
        if isinstance(code, str):
            code = code.encode("utf-8")
        self.s.write(code)
        self.s.write(b"\x04")
        data = self.read_until(RAW_END, timeout=run_timeout)
        if data.startswith(b"\x04"):
            data = data[1:]
        if data.endswith(b">"):
            data = data[:-1]
        if data.endswith(RAW_END):
            data = data[:-2]
        elif data.endswith(b"\x04"):
            data = data[:-1]
        if data.startswith(b"OK"):
            return data[2:], None
        return b"", data

    def session(self, code, timeout=30):
        """独立会话: 打断 -> 进 raw -> exec -> 退 raw (每次 exec 独立, 防卡死)"""
        if len(code) > MAX_CODE:
            # 不拦的话会静默丢字节 -> 板端 SyntaxError + 会话挂住, 很难查
            raise ValueError("单次下发 %d 字节, 超过上限 %d —— 请分块下发"
                             "(多行信息用 agentscreen_client.push_lines)" % (len(code), MAX_CODE))
        self._enter_raw()
        try:
            return self.exec_raw(code, run_timeout=timeout)
        finally:
            self._exit_raw()

    # ---------- 高层 ----------
    def run_ram(self, path):
        """把 .py 直接送到 RAM 运行(前台), 返回 (out, err)。仅适用于会结束的脚本。"""
        src = open(path, "rb").read().decode("utf-8")
        self._enter_raw()
        try:
            return self.exec_raw(src, run_timeout=30)
        finally:
            self._exit_raw()

    def upload(self, path, dest):
        """分块上传(每块独立会话)并校验大小, 返回 (bytes, chunks)"""
        data = open(path, "rb").read()
        chunks = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)]
        for i, ch in enumerate(chunks):
            mode = "wb" if i == 0 else "ab"
            b64 = base64.b64encode(ch).decode()
            code = ("import base64\n"
                    "f=open(%r,%r)\n"
                    "f.write(base64.b64decode(%r))\n"
                    "f.close()\n" % (dest, mode, b64))
            t0 = time.time()
            out, err = self.session(code, timeout=20)
            if err:
                raise RuntimeError("块 %d/%d 写入失败: %s"
                                   % (i + 1, len(chunks), err.decode("utf-8", "replace")))
            sys.stderr.write("  [%d/%d] %.1fs\n" % (i + 1, len(chunks), time.time() - t0))
            sys.stderr.flush()
        # 校验大小 + 内容校验和(防 paste 丢字节导致内容损坏)
        local_sum = sum(data) & 0xFFFFFFFF
        chk = ("import uos\n"
               "print('SIZE', uos.stat(%r)[6])\n"
               "f=open(%r,'rb'); s=0\n"
               "while True:\n"
               " b=f.read(256)\n"
               " if not b: break\n"
               " s=(s+sum(b))&0xffffffff\n"
               "f.close()\n"
               "print('SUM', s)\n" % (dest, dest))
        out, err = self.session(chk)
        toks = out.decode("utf-8", "replace").split()
        size, rsum = -1, -1
        for i, t in enumerate(toks):
            if t == "SIZE" and i + 1 < len(toks):
                size = int(toks[i + 1])
            if t == "SUM" and i + 1 < len(toks):
                rsum = int(toks[i + 1])
        if size != len(data):
            raise RuntimeError("大小校验失败: 板载 %d != 本地 %d" % (size, len(data)))
        if rsum != local_sum:
            raise RuntimeError("内容校验和失败: 板载 %d != 本地 %d" % (rsum, local_sum))
        return len(data), len(chunks)

    def download(self, remote, local, chunk=2048):
        """从板子读回文件(分块 base64)到本地, 返回字节数。用于回读截图/日志取证。"""
        out = bytearray()
        pos = 0
        while True:
            code = ("import base64\n"
                    "f=open(%r,'rb')\n"
                    "f.seek(%d)\n"
                    "d=f.read(%d)\n"
                    "f.close()\n"
                    "print('\\n@@B64@@' + base64.b64encode(d).decode())\n" % (remote, pos, chunk))
            o, e = self.session(code, timeout=20)
            if e:
                raise RuntimeError("读取 %s 失败: %s" % (remote, e.decode("utf-8", "replace")))
            txt = o.decode("utf-8", "replace")
            if "@@B64@@" not in txt:
                raise RuntimeError("未收到数据: " + txt)
            b64 = txt.split("@@B64@@", 1)[1].strip().split("\n")[0].strip()
            d = base64.b64decode(b64) if b64 else b""
            if not d:
                break
            out += d
            pos += len(d)
            if len(d) < chunk:
                break
        with open(local, "wb") as f:
            f.write(bytes(out))
        return len(out)

    def copy_remote(self, src, dst):
        out, err = self.session(
            "d=open(%r,'rb').read()\nopen(%r,'wb').write(d)\nprint('COPIED', len(d))\n" % (src, dst))
        if err:
            raise RuntimeError("复制 %s -> %s 失败: %s" % (src, dst, err.decode("utf-8", "replace")))
        return out.decode("utf-8", "replace").strip()

    def start_module(self, dest, func="main", timeout=15):
        """import 指定模块并在后台线程启动 func(), 主线程立即返回。适用于死循环脚本。"""
        mdir = dest.rsplit("/", 1)[0] or "/"
        mod = os.path.basename(dest)
        if mod.endswith(".py"):
            mod = mod[:-3]
        code = ("import sys\n"
                "sys.path.insert(0, %r)\n"
                "import %s\n"
                "try:\n"
                "    import _thread\n"
                "    _thread.start_new_thread(%s.%s, ())\n"
                "    print('STARTED')\n"
                "except Exception as e:\n"
                "    print('START_FAIL', repr(e))\n" % (mdir, mod, mod, func))
        out, err = self.session(code, timeout=timeout)
        if err:
            raise RuntimeError("启动失败: " + err.decode("utf-8", "replace"))
        return out.decode("utf-8", "replace").strip()


def main():
    ap = argparse.ArgumentParser(description="K230D CanMV MicroPython 下发/运行工具")
    ap.add_argument("--port", default=None, help="串口(如 COM14); 省略则自动识别 CanMV 口")
    ap.add_argument("--baud", type=int, default=BAUD)
    ap.add_argument("--file", default=None, help="要下发的本地 .py")
    ap.add_argument("--dest", default=None, help="远端路径; 给出则分块上传(不直接跑)")
    ap.add_argument("--persist", action="store_true", help="固化到 /sdcard/main.py(开机自启)")
    ap.add_argument("--run", action="store_true", help="上传后 import 并在后台线程启动 entry()")
    ap.add_argument("--entry", default="main", help="后台启动的入口函数名(默认 main)")
    ap.add_argument("--to-main", action="store_true", help="上传后同时复制为 /sdcard/main.py")
    ap.add_argument("--selftest", action="store_true", help="下发内置自检脚本并回读")
    ap.add_argument("--rm", default=None, metavar="PATH", help="删除远端文件后退出")
    ap.add_argument("--get", nargs=2, default=None, metavar=("REMOTE", "LOCAL"),
                    help="从板子读回文件(如截图): --get /sdcard/_shot.png shot.png")
    ap.add_argument("--list", action="store_true", help="仅列出本机串口")
    args = ap.parse_args()

    if args.list:
        print("=== 本机串口 ===")
        rows = list_all_ports() or []
        if not rows:
            print("(无)")
        for d, desc in rows:
            print("%-8s %s%s" % (d, desc, "   <-- CanMV?" if "canmv" in desc.lower() else ""))
        return 0

    if not args.file and not args.selftest and not args.rm and not args.get:
        ap.error("需要 --file / --selftest / --rm / --get")

    port = args.port or detect_canmv_port()
    if not port:
        print("[!] 未自动识别 CanMV 口, 候选:")
        for d, desc in list_all_ports():
            print("    %-8s %s" % (d, desc))
        print("请用 --port COMx 指定。")
        return 2

    dev = K230(port, args.baud)
    try:
        print("[*] 端口 %s" % port)
        if args.get:
            n = dev.download(args.get[0], args.get[1])
            print("[✓] 读回 %s -> %s (%d 字节)" % (args.get[0], args.get[1], n))
            return 0
        if args.rm:
            out, err = dev.session(
                "import uos\ntry:\n uos.remove(%r)\n print('REMOVED')\nexcept Exception as e:\n print('RM_FAIL', repr(e))\n"
                % args.rm)
            print("  " + (out.decode("utf-8", "replace").strip() or
                          err.decode("utf-8", "replace").strip()))
            return 0
        if args.selftest:
            out, err = dev.session(SELFTEST)
            sys.stdout.write(out.decode("utf-8", "replace"))
            if err:
                sys.stderr.write("[异常]\n" + err.decode("utf-8", "replace"))
                return 1
            return 0

        dest = "/sdcard/main.py" if args.persist else args.dest
        if dest:
            nbytes, nchunks = dev.upload(args.file, dest)
            print("[*] 上传 %s -> %s (%d 字节, %d 块, 校验通过)" % (args.file, dest, nbytes, nchunks))
            if args.to_main and dest != "/sdcard/main.py":
                print("[*] " + dev.copy_remote(dest, "/sdcard/main.py"))
            if args.run:
                print("[*] 后台启动 %s.%s()" % (os.path.basename(dest), args.entry))
                print("    " + dev.start_module(dest, args.entry))
            print("[✓] 完成")
        else:
            print("[*] RAM 运行 %s" % args.file)
            out, err = dev.run_ram(args.file)
            if out:
                sys.stdout.write("[stdout]\n" + out.decode("utf-8", "replace"))
            if err:
                sys.stdout.write("[异常/错误]\n" + err.decode("utf-8", "replace"))
                return 1
            print("\n[✓] 执行完成")
        return 0
    except RuntimeError as e:
        sys.stderr.write("[失败] %s\n" % e)
        return 1
    finally:
        dev.close()


if __name__ == "__main__":
    sys.exit(main())
