#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_icon.py — 生成 128x128 图标(参数化绘制 + 超采样抗锯齿), 供推到 K230D 副屏。

用法:
  python make_icon.py --list                       # 列出内置图标
  python make_icon.py heart                        # -> icons/heart.png (128x128)
  python make_icon.py star icons/star_red.png      # 指定输出
  python make_icon.py star --color red             # 指定颜色(名称或 R,G,B)
  python make_icon.py star --color 218,36,42
  python make_icon.py warn --color orange --size 96

内置: heart star check warn info cross music bell arrow
颜色名: red green blue yellow orange purple white cyan pink
"""
import sys, os, math
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = 128
SS = 4                      # 超采样倍数(抗锯齿)
BG = (0, 0, 0)              # 黑底(与副屏背景一致, 补边不留方框)

NAMED = {
    "red":    (218, 36, 42),
    "green":  (60, 210, 110),
    "blue":   (70, 150, 235),
    "yellow": (255, 205, 60),
    "orange": (255, 150, 40),
    "purple": (170, 110, 235),
    "white":  (240, 240, 245),
    "cyan":   (110, 220, 240),
    "pink":   (250, 110, 150),
}


def parse_color(s):
    """'red' 或 '218,36,42' -> (r,g,b); 失败返回 None"""
    if not s:
        return None
    t = s.strip().lower()
    if t in NAMED:
        return NAMED[t]
    try:
        p = [int(x) for x in t.split(",")]
        if len(p) == 3:
            return tuple(max(0, min(255, v)) for v in p)
    except Exception:
        pass
    return None


def lighten(c, f=0.45):
    return tuple(min(255, int(v + (255 - v) * f)) for v in c)


def darken(c, f=0.45):
    return tuple(max(0, int(v * (1 - f))) for v in c)


def _canvas(margin=8):
    n = SIZE * SS
    im = Image.new("RGB", (n, n), BG)
    return im, ImageDraw.Draw(im), n, margin * SS


def _fit(points, n, margin):
    """把点集等比缩放并居中放进 n x n 画布"""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if w <= 0 or h <= 0:
        return points
    s = min((n - 2 * margin) / w, (n - 2 * margin) / h)
    cx, cy = (max(xs) + min(xs)) / 2.0, (max(ys) + min(ys)) / 2.0
    return [((x - cx) * s + n / 2.0, (y - cy) * s + n / 2.0) for x, y in points]


# ------------------------- 各图标 -------------------------
def ic_heart(color=None):
    c = color or (232, 46, 66)
    im, d, n, m = _canvas()
    pts = []
    for i in range(721):
        t = i * math.pi / 360.0
        pts.append((16 * math.sin(t) ** 3,
                    13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
    pts = _fit([(x, -y) for x, y in pts], n, m)
    d.polygon(pts, fill=c)
    hl = [(x * 0.55 + n * 0.30, y * 0.55 + n * 0.28) for x, y in pts]
    d.polygon(hl, fill=lighten(c))
    return im


def ic_star(color=None):
    c = color or (255, 205, 60)
    im, d, n, m = _canvas()
    pts = []
    for i in range(11):
        r = 1.0 if i % 2 == 0 else 0.42
        a = -math.pi / 2 + i * math.pi / 5
        pts.append((r * math.cos(a), r * math.sin(a)))
    pts = _fit(pts, n, m)
    d.polygon(pts, fill=c)
    # 左上棱面加一点高光, 让五角星有立体感
    inner = []
    for i in range(11):
        r = (0.62 if i % 2 == 0 else 0.30)
        a = -math.pi / 2 + i * math.pi / 5
        inner.append((r * math.cos(a) - 0.10, r * math.sin(a) + 0.16))
    inner = _fit([(x, y) for x, y in inner], n, m)
    hl = Image.new("L", (n, n), 0)
    hd = ImageDraw.Draw(hl)
    hd.polygon(inner, fill=90)
    im.paste(Image.new("RGB", (n, n), lighten(c, 0.35)), (0, 0), hl)
    return im


def ic_check(color=None):
    c = color or (60, 210, 110)
    im, d, n, m = _canvas(margin=14)
    pts = _fit([(0.0, 0.10), (0.34, 0.46), (0.92, -0.36)], n, m)
    d.line(pts, fill=c, width=int(n * 0.11), joint="curve")
    for p in pts:
        d.ellipse((p[0] - n * 0.055, p[1] - n * 0.055, p[0] + n * 0.055, p[1] + n * 0.055), fill=c)
    return im


def ic_cross(color=None):
    c = color or (228, 62, 62)
    im, d, n, m = _canvas(margin=16)
    w = int(n * 0.10)
    d.line(_fit([(-0.6, -0.6), (0.6, 0.6)], n, m), fill=c, width=w)
    d.line(_fit([(-0.6, 0.6), (0.6, -0.6)], n, m), fill=c, width=w)
    return im


def ic_warn(color=None):
    c = color or (255, 190, 45)
    fg = darken(c, 0.78)
    im, d, n, m = _canvas(margin=10)
    d.polygon(_fit([(0.0, -0.92), (0.88, 0.62), (-0.88, 0.62)], n, m), fill=c)
    x = n / 2.0
    d.rectangle((x - n * 0.035, n * 0.36, x + n * 0.035, n * 0.66), fill=fg)
    d.ellipse((x - n * 0.042, n * 0.72, x + n * 0.042, n * 0.80), fill=fg)
    return im


def ic_info(color=None):
    c = color or (70, 150, 235)
    fg = (255, 255, 255)
    im, d, n, m = _canvas(margin=8)
    d.ellipse((m, m, n - m, n - m), fill=c)
    x = n / 2.0
    d.ellipse((x - n * 0.045, n * 0.22, x + n * 0.045, n * 0.31), fill=fg)
    d.rectangle((x - n * 0.05, n * 0.38, x + n * 0.05, n * 0.76), fill=fg)
    return im


def ic_music(color=None):
    c = color or (150, 215, 255)
    im, d, n, m = _canvas(margin=12)
    x = n * 0.62
    d.rectangle((x - n * 0.045, n * 0.20, x + n * 0.02, n * 0.72), fill=c)
    d.polygon([(x + n * 0.02, n * 0.20), (n * 0.86, n * 0.13), (n * 0.86, n * 0.28),
               (x + n * 0.02, n * 0.35)], fill=c)
    for cxp, cyp in ((n * 0.40, n * 0.74), (x - n * 0.04, n * 0.66)):
        r = n * 0.115
        d.ellipse((cxp - r, cyp - r, cxp + r, cyp + r), fill=c)
    return im


def ic_bell(color=None):
    c = color or (255, 210, 90)
    c2 = darken(c, 0.16)
    im, d, n, m = _canvas(margin=12)
    d.pieslice((n * 0.20, n * 0.14, n * 0.80, n * 0.86), 180, 360, fill=c)
    d.rectangle((n * 0.20, n * 0.50, n * 0.80, n * 0.72), fill=c)
    d.rectangle((n * 0.16, n * 0.72, n * 0.84, n * 0.78), fill=c2)
    d.ellipse((n * 0.44, n * 0.78, n * 0.56, n * 0.90), fill=c2)
    return im


def ic_arrow(color=None):
    c = color or (120, 255, 170)
    im, d, n, m = _canvas(margin=14)
    d.polygon(_fit([(0.0, -0.9), (0.8, 0.05), (0.28, 0.05), (0.28, 0.9),
                    (-0.28, 0.9), (-0.28, 0.05), (-0.8, 0.05)], n, m), fill=c)
    return im


BUILTIN = {"heart": ic_heart, "star": ic_star, "check": ic_check, "cross": ic_cross,
           "warn": ic_warn, "info": ic_info, "music": ic_music, "bell": ic_bell,
           "arrow": ic_arrow}


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if a[0] == "--list":
        print("内置图标:", ", ".join(sorted(BUILTIN)))
        print("颜色名  :", ", ".join(sorted(NAMED)))
        return 0

    color = None
    size = SIZE
    rest = []
    i = 0
    while i < len(a):
        if a[i] == "--color" and i + 1 < len(a):
            color = parse_color(a[i + 1])
            if color is None:
                print("无法识别颜色 %r" % a[i + 1])
                return 2
            i += 2
            continue
        if a[i] == "--size" and i + 1 < len(a):
            size = int(a[i + 1])
            i += 2
            continue
        rest.append(a[i])
        i += 1

    if not rest:
        print(__doc__)
        return 0
    name = rest[0]
    if name not in BUILTIN:
        print("未知图标 %r; 可用: %s" % (name, ", ".join(sorted(BUILTIN))))
        return 2
    if len(rest) > 1:
        out = rest[1]
    else:
        suffix = ""
        for k, v in NAMED.items():
            if color == v:
                suffix = "_" + k
                break
        out = os.path.join(HERE, "icons", name + suffix + ".png")

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    im = BUILTIN[name](color)
    if im.size != (size, size):                      # 超采样画布(SS 倍) -> 目标尺寸
        im = im.resize((size, size), Image.LANCZOS)
    im.save(out, "PNG", optimize=True)
    print("OK %s%s -> %s (%d bytes, %dx%d)"
          % (name, ("/" + str(color)) if color else "", out,
             os.path.getsize(out), size, size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
