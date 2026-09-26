#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_sfx.py — 合成副屏用的状态提示音(不依赖外部素材)

规格刻意做小, 因为串口通道只有 ~2.4 KB/s:
    8 kHz / 16 bit / 单声道  ->  0.2 秒 ≈ 3.2 KB, 传 ~1.5 秒
(提示音是纯正弦, 4 kHz 带宽足够; 采样率低 = 传得快、板端解码也轻)

用法:
    python make_sfx.py              # 生成到 ./sfx/
    python make_sfx.py --rate 16000 # 换个采样率
"""
import os, math, wave, struct, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "sfx")


def tone(freq, dur, rate, amp=0.42, fade=0.006):
    """单音: 正弦 + 淡入淡出(避免爆音)"""
    n = max(1, int(rate * dur))
    nf = max(1, int(rate * fade))
    pcm = []
    for i in range(n):
        env = 1.0
        if i < nf:
            env = i / float(nf)
        elif i > n - nf:
            env = (n - i) / float(nf)
        pcm.append(int(32767 * amp * env * math.sin(2 * math.pi * freq * i / rate)))
    return pcm


def silence(dur, rate):
    return [0] * max(1, int(rate * dur))


def seq(parts, rate):
    """parts: [(freq, dur) 或 ("sil", dur)]"""
    out = []
    for p in parts:
        if p[0] == "sil":
            out += silence(p[1], rate)
        else:
            out += tone(p[0], p[1], rate)
    return out


def write_wav(path, pcm, rate):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % len(pcm), *pcm))


# 音效定义: (文件名, 说明, [(频率, 时长)...])
SFX = [
    ("ok",       "任务完成 / 成功",      [(660, 0.085), (880, 0.14)]),
    ("err",      "出错 / 失败",          [(392, 0.12), (294, 0.20)]),
    ("notify",   "收到消息 / 新内容",     [(1046, 0.10), ("sil", 0.03), (1318, 0.14)]),
    ("alert",    "需要你授权 / 弹框",     [(880, 0.07), ("sil", 0.05), (880, 0.07), ("sil", 0.05), (1174, 0.14)]),
    ("start",    "开始执行 / 已连接",     [(523, 0.06), (659, 0.06), (784, 0.10)]),
    ("tick",     "轻点 / 翻页",          [(1318, 0.04)]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=int, default=8000)
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    total = 0
    print("采样率 %d Hz / 16bit / 单声道" % a.rate)
    for name, desc, parts in SFX:
        pcm = seq(parts, a.rate)
        p = os.path.join(OUT_DIR, "%s.wav" % name)
        write_wav(p, pcm, a.rate)
        sz = os.path.getsize(p)
        total += sz
        print("  %-8s %-18s %5.2f s  %5d B" % (name + ".wav", desc, len(pcm) / float(a.rate), sz))
    print("合计 %d 个 / %.1f KB  (串口约需 ~%.0f 秒推送)" % (len(SFX), total / 1024.0, total / 1024.0 / 2.4))
    print("[v] 输出目录: %s" % OUT_DIR)


if __name__ == "__main__":
    main()
