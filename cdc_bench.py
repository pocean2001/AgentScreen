#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cdc_bench.py — 实测 USB-CDC 裸二进制流吞吐（绕过 REPL 的分块/base64 开销）

原理:
  1) Ctrl-A 进 raw REPL
  2) 把"读固定 N 字节并计时"的代码写进去 + \\x04 触发执行
  3) 板端 print READY -> 主机立刻裸写 N 字节 -> 板端计时读数
  4) 读回 BENCH 结果

安全设计:
  * 板端用 select.poll 做兜底: 超过 STALL_MS 没有数据就主动退出, 不会永久阻塞
  * 逐级测试 N, 每级跑完立刻做一次 status 健康检查
  * 出现任何异常立即停止, 不做后续级别

用法:
  python cdc_bench.py                 # 8K -> 32K -> 128K 递进
  python cdc_bench.py --n 8192        # 只测一级
  python cdc_bench.py --n 8192 --repeat 3
"""
import sys, os, time, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from k230_push import K230, detect_canmv_port, RAW_END

# 板端读测代码: 不进文件系统, 只读+计时, 带 poll 兜底超时
BOARD_CODE = r'''
import sys, time
N = %(n)d
STALL_MS = %(stall)d
try:
    import select
    _poll = select.poll()
    _poll.register(sys.stdin, select.POLLIN)
except Exception:
    _poll = None
print("READY")
b = sys.stdin.buffer
got = 0
chunks = 0
t0 = time.ticks_ms()
last = t0
stall_hit = False
while got < N:
    if _poll is not None:
        if not _poll.poll(500):
            if time.ticks_diff(time.ticks_ms(), last) > STALL_MS:
                stall_hit = True
                break
            continue
    try:
        d = b.read(512)
    except Exception:
        break
    if not d:
        if time.ticks_diff(time.ticks_ms(), last) > STALL_MS:
            stall_hit = True
            break
        continue
    got += len(d)
    chunks += 1
    last = time.ticks_ms()
dt = time.ticks_diff(time.ticks_ms(), t0)
kbps = got / 1024.0 / (dt / 1000.0) if dt > 0 else 0.0
print("BENCH got=%%d want=%%d ms=%%d chunks=%%d kbps=%%.1f stall=%%s" %% (
      got, N, dt, chunks, kbps, stall_hit))
'''


def payload(n):
    """可辨识的伪随机数据(非 0, 便于发现丢字节)"""
    buf = bytearray(n)
    for i in range(n):
        buf[i] = (i * 37 + 11) & 0xFF
    return bytes(buf)


def one_round(dev, n, stall_ms=6000, verbose=True):
    code = BOARD_CODE % {"n": n, "stall": stall_ms}
    dev.s.reset_input_buffer()
    dev.s.write(code.encode("utf-8"))
    dev.s.write(b"\x04")                     # 开始执行

    # 等板端 READY(确认已进入读取状态)
    ready = dev.read_until(b"READY", timeout=6)
    if b"READY" not in ready:
        raise RuntimeError("板端未就绪, 收到: %r" % ready[-120:])
    if verbose:
        print("      板端 READY 已到, 开始裸写 %d 字节..." % n)

    data = payload(n)
    t0 = time.time()
    try:
        dev.s.write(data)
        dev.s.flush()
    except Exception as e:
        raise RuntimeError("写数据失败: %r" % e)
    t_write = time.time() - t0

    out = dev.read_until(RAW_END, timeout=40)
    txt = out.decode("utf-8", "replace") if isinstance(out, bytes) else str(out)
    line = ""
    for ln in txt.split("\n"):
        if "BENCH" in ln:
            line = ln.strip()
    if not line:
        raise RuntimeError("没收到 BENCH 结果: %r" % txt[-200:])
    if verbose:
        print("      主机写耗时 %.3f s -> %s" % (t_write, line))
    return line, t_write


def health(dev):
    """一次 status 调用, 确认板子仍然正常"""
    try:
        out, err = dev.session(
            "import sys;sys.path.insert(0,'/sdcard');import agent_screen as A;"
            "print('H' + A.cmd('{\"op\":\"status\"}'))", timeout=15)
        txt = (out or b"").decode("utf-8", "replace")
        j = txt.find("{")
        if j >= 0:
            import json
            st = json.loads(txt[j:].strip())
            return "ok, now=%s info=%s行 err=%r" % (
                st.get("now"), st.get("info_total"), st.get("last_error"))
        return "返回异常: %r" % txt[-120:]
    except Exception as e:
        return "健康检查失败: %r" % e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="只测这一级(字节); 省略则 8K/32K/128K 递进")
    ap.add_argument("--stall", type=int, default=6000, help="板端无数据的兜底超时(ms)")
    ap.add_argument("--repeat", type=int, default=1, help="每级重复次数")
    ap.add_argument("--port", default=None)
    a = ap.parse_args()

    port = a.port or detect_canmv_port()
    if not port:
        print("[x] 未识别到 CanMV 串口")
        return 2
    print("[*] 端口 %s" % port)

    levels = [a.n] if a.n else [8 * 1024, 32 * 1024, 128 * 1024]
    dev = K230(port, 115200, fast=False)
    results = []
    try:
        dev._enter_raw()
        print("[*] 已进入 raw REPL")
        for n in levels:
            print("=== 测试 N = %d 字节 (%.1f KB) ===" % (n, n / 1024.0))
            for r in range(a.repeat):
                try:
                    line, tw = one_round(dev, n, a.stall)
                    results.append((n, line, tw))
                    dev._exit_raw()
                    time.sleep(0.4)
                    h = health(dev)
                    print("      健康检查: %s" % h)
                    if "ok," not in h:
                        print("[!] 板子状态异常, 停止后续测试")
                        raise SystemExit(1)
                    dev._enter_raw()
                except Exception as e:
                    print("[x] 第 %d 级失败: %r" % (n, e))
                    print("    若板子随之无响应, 需要物理断电重插")
                    raise SystemExit(1)
        print("\n=== 汇总 ===")
        for n, line, tw in results:
            print("  N=%-7d %s  (主机写 %.3fs)" % (n, line, tw))
    finally:
        try:
            dev._exit_raw()
            dev.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
