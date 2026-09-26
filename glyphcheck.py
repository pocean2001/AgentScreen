#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glyphcheck.py — 实测板端字库里**有没有某个字的字形**。

为什么需要: 板端字体是裁剪过的, 有些常用字没字形 —— 实测 **莞 / 圳 画出来是空白**,
于是"东莞"显示成"东"、看着像被遮掉一个字。板端 get_pixel 取不到数据, 所以只能:
    离屏画布上把待测字逐个画进格子 -> to_png 导出 -> 回传 -> 主机量每格墨迹

用法(库):
    from glyphcheck import supported, first_supported
    supported("莞")                      # -> False
    first_supported(["东莞", "广东"])     # -> "广东" (挑第一个每个字都有字形的)

缓存: .as_glyphs.json (字 -> True/False), 避免每次重复上板探测。
"""
import os, sys, json, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CACHE = os.path.join(HERE, ".as_glyphs_ttf.json")   # 注意: 换字体后必须换缓存名, 否则旧的缺字结论会一直生效
CELL = 48          # 每个字一格, 格宽 48px
SIZE = 32          # 与日期行字号一致(DATE_SIZE)
REMOTE = "/sdcard/_gc.png"
INK_MIN = 6        # 格子里墨迹像素数低于此值算"没有字形"

# 探测必须用**实际渲染时用的那个字体** —— 否则测的是内置裁剪字库, 会误判成缺字。
SUBFONT = "/sdcard/res/font/_font_gb2312.ttf"

_PROBE = """import image
_fp = None
try:
    import uos
    _p = %r
    if uos.stat(_p)[6] > 1000:
        _fp = _p
except Exception:
    pass
S = %r
CELL = %d
SIZE = %d
c = image.Image(CELL * len(S), CELL + 8, image.RGB565)
c.clear()
for i, ch in enumerate(S):
    if _fp:
        c.draw_string_advanced(i * CELL + 4, 4, SIZE, ch, color=(255, 255, 255), font=_fp)
    else:
        c.draw_string_advanced(i * CELL + 4, 4, SIZE, ch, color=(255, 255, 255))
b = c.to_png()
f = open(%r, 'wb')
f.write(b)
f.close()
print('GC', len(S))
"""


def _load():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(cache):
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, sort_keys=True)
    except OSError:
        pass


def probe(chars):
    """把 chars 逐个画到板子离屏画布的一格格里, 回传后量墨迹 -> [bool,...]"""
    chars = [c for c in chars]
    if not chars:
        return []
    from k230_push import K230, detect_canmv_port
    port = detect_canmv_port()
    if not port:
        raise RuntimeError("未识别 K230D 串口, 无法探测字库")
    dev = K230(port)
    try:
        out, err = dev.session(_PROBE % (SUBFONT, "".join(chars), CELL, SIZE, REMOTE), timeout=20)
        if err:
            raise RuntimeError(err.decode("utf-8", "replace")[:200])
        local = os.path.join(tempfile.gettempdir(), "_glyphcheck.png")
        dev.download(REMOTE, local)
    finally:
        dev.close()
    from PIL import Image
    im = Image.open(local).convert("RGB")
    px = im.load()
    res = []
    for i in range(len(chars)):
        ink = 0
        for x in range(i * CELL, (i + 1) * CELL):
            for y in range(CELL + 8):
                if sum(px[x, y]) > 60:
                    ink += 1
                    if ink > INK_MIN:
                        break
            if ink > INK_MIN:
                break
        res.append(ink > INK_MIN)
    return res


def probe_cached(chars):
    """带缓存的批量探测; 板子不可用时抛异常(调用方自己兜底)"""
    cache = _load()
    todo = []
    for c in chars:
        if c not in cache and c not in todo:
            todo.append(c)
    if todo:
        for c, ok in zip(todo, probe(todo)):
            cache[c] = bool(ok)
        _save(cache)
    return [cache.get(c, True) for c in chars]


def supported(ch):
    try:
        return probe_cached([ch])[0]
    except Exception:
        return True          # 探测不了就假定支持(不阻塞正常显示)


def all_supported(s):
    """s 里每个字都有字形? (板子不可用时返回 True, 不阻塞显示)"""
    if not s:
        return False
    try:
        ok = dict(zip(s, probe_cached(list(s))))
        return all(ok.get(c, True) for c in s)
    except Exception:
        return True


def first_supported(cands):
    """从候选里挑第一个"每个字都有字形"的; 都不行返回其第一个非空候选(兜底)。
    板子不可用时返回第一个非空候选 —— 宁可显示缺字也不要不显示。"""
    cands = [c for c in cands if c]
    if not cands:
        return ""
    try:
        all_chars = "".join(cands)
        ok = dict(zip(all_chars, probe_cached(all_chars)))
        for s in cands:
            if all(ok.get(c, True) for c in s):
                return s
    except Exception:
        pass
    return cands[0]


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(0)
    if args[0] == "--first":
        print("first_supported(%r) -> %r" % (args[1:], first_supported(args[1:])))
    else:
        s = args[0]
        for c, ok in zip(s, probe_cached(s)):
            print("  %s  %s" % (c, "有字形" if ok else "*** 缺字 ***"))
