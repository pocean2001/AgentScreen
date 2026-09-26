#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""disable_audio.py — 一键关闭副屏音频(删标志文件), 恢复到稳定状态。

背景: 这块板子上 pyaudio 播放路径会把板子挂死(实测 3 次), 所以默认关闭。
用法: python disable_audio.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from k230_push import K230, detect_canmv_port

CODE = '''
import uos
try:
    uos.remove("/sdcard/.as_media_on")
    print("REMOVED")
except Exception as e:
    print("ALREADY_OFF:", e)
'''

def main():
    port = detect_canmv_port()
    if not port:
        print("[x] 未识别到 CanMV 串口")
        return 2
    dev = K230(port)
    try:
        out, err = dev.session(CODE, timeout=15)
        txt = (out or b"").decode("utf-8", "replace")
        print("[v] 音频已关闭(标志文件已删)" if "REMOVED" in txt or "ALREADY_OFF" in txt
              else "[?] 结果: %r" % txt[:200])
        print("    重启板子后 ENABLE_MEDIA 即为 False, op=audio/op=sfx 都会被拒绝。")
    finally:
        dev.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
