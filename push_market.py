#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""push_market.py — 查询美股三大指数行情, 把摘要推到 K230D 副屏信息栏。

用法:
  python push_market.py            # 查询并推送
  python push_market.py --dry      # 只打印, 不推送

数据源: 腾讯行情 http://qt.gtimg.cn  (返回含美东时间戳, 据此判断 盘前/盘中/收盘)
"""
import sys, os, re, json, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SYMS = ["usDJI", "usIXIC", "usINX"]
SHORT = {"usDJI": "道指", "usIXIC": "纳指", "usINX": "标普"}
API = "http://qt.gtimg.cn/q=" + ",".join(SYMS)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def fetch(timeout=8):
    req = urllib.request.Request(API, headers={"User-Agent": "Mozilla/5.0"})
    txt = urllib.request.urlopen(req, timeout=timeout).read().decode("gbk", "replace")
    out, ts = [], None
    for line in txt.split(";"):
        line = line.strip()
        m = re.match(r'v_(\w+)="(.*)"$', line)
        if not m:
            continue
        sym, body = m.group(1), m.group(2)
        f = body.split("~")
        try:
            price = float(f[3])
            prev = float(f[4])
        except Exception:
            continue
        chg = pct = None
        for i, v in enumerate(f):                 # 找到美东时间戳字段, 其后就是涨跌额/幅
            if DATE_RE.match(v):
                ts = v
                try:
                    chg, pct = float(f[i + 1]), float(f[i + 2])
                except Exception:
                    pass
                break
        if chg is None:                           # 兜底: 用昨收算
            chg = price - prev
            pct = (chg / prev * 100.0) if prev else 0.0
        out.append({"sym": sym, "name": f[1], "price": price, "chg": chg, "pct": pct})
    return out, ts


def session_label(ts):
    """按美东时间判断交易时段, 返回 (标题前缀, 是否为实时盘中)"""
    if not ts:
        return "美股行情", False
    d, t = ts.split(" ")
    mo, dd = int(d[5:7]), int(d[8:10])
    hh, mi = int(t[:2]), int(t[3:5])
    mins = hh * 60 + mi
    if 570 <= mins <= 960:                        # 09:30 - 16:00 ET
        st = "盘中"
    elif mins < 570:
        st = "盘前"
    else:
        st = "收盘"
    return "美股%d/%d%s" % (mo, dd, st), (st == "盘中")


def build_lines(data, ts):
    head, live = session_label(ts)
    ups = [d["pct"] > 0 for d in data]
    trend = "齐涨" if all(ups) else ("齐跌" if not any(ups) else "涨跌不一")
    lines = ["%s%s" % (head, trend)]
    for d in data:
        lines.append("%s%d %+.2f%%" % (SHORT.get(d["sym"], d["name"]),
                                       round(d["price"]), d["pct"]))
    return lines, live


def main():
    dry = "--dry" in sys.argv
    try:
        data, ts = fetch()
    except Exception as e:
        print("查询失败: %r" % e)
        return 1
    if len(data) < 3:
        print("数据不完整: %r" % data)
        return 1
    lines, live = build_lines(data, ts)
    for s in lines:
        w = sum(40 if ord(c) > 0x2E7F else 20 for c in s)
        print("  %-20s %3dpx %s" % (s, w, "OK" if w <= 456 else "!! 会换行"))
    print("源: qt.gtimg.cn  时间: %s (美东)%s" % (ts, "" if live else "  <非盘中, 为最近一次快照>"))
    if dry:
        return 0
    import agentscreen_client as C
    r = C.call({"op": "info", "lines": lines})
    if r:
        print("推送: OK")
        return 0
    print("[错误] 推送失败 —— " + C.explain())
    return 2


if __name__ == "__main__":
    sys.exit(main())
