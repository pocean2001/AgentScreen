#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""redeploy_agentscreen.py — 把板端服务上传到 K230D 并 soft reset 让其重新加载。

上传: agent_screen.py -> /sdcard/agent_screen.py
      board_main.py   -> /sdcard/main.py   (开机自启入口)
板端文件查找顺序: 本目录 -> ./board -> ../board  (兼容打包后的目录结构)

注意: soft reset 会清空屏上的 图标/天气/信息栏, 之后可运行 push_digest.py 重推。
"""
import sys, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import serial
from k230_push import K230, detect_canmv_port, BAUD


def find_board_file(name):
    for d in (HERE, os.path.join(HERE, "board"), os.path.join(os.path.dirname(HERE), "board")):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    raise SystemExit("找不到板端文件 %s（应位于 %s 或 ./board 或 ../board）" % (name, HERE))


def main():
    port = detect_canmv_port()
    if not port:
        print("[!] 未识别 K230D CanMV 串口；请插好 USB，或用 AGENTSCREEN_PORT=COMx 指定")
        return 2
    a = find_board_file("agent_screen.py")
    m = find_board_file("board_main.py")
    dev = K230(port)
    try:
        print("[*] 端口 %s" % port)
        print("[1] 上传 %s -> /sdcard/agent_screen.py" % a)
        print("   ", dev.upload(a, "/sdcard/agent_screen.py"))
        print("[2] 上传 %s -> /sdcard/main.py (开机自启)" % m)
        print("   ", dev.upload(m, "/sdcard/main.py"))
    finally:
        dev.close()
    print("[3] soft reset (Ctrl-D) 重新加载")
    s = serial.Serial(port, BAUD, timeout=1)
    s.dtr = False
    s.rts = False
    s.write(b"\x02")
    time.sleep(0.3)
    s.write(b"\x04")
    time.sleep(0.3)
    s.close()
    time.sleep(3)
    print("[v] 完成：板子已重新加载 AgentScreen 服务")
    print("    提示：soft reset 会清空屏上的图标/天气/信息栏，可运行 push_digest.py 重推")
    return 0


if __name__ == "__main__":
    sys.exit(main())
