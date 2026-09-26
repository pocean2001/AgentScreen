#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""push_digest.py — 把「美股行情 + 要闻」合成一个滚动摘要, 推到 K230D 副屏信息栏。

用法:
  python push_digest.py              # 合成并推送; 要闻过期时额外打印 NEWS_STALE
  python push_digest.py --no-news    # 只推行情
  python push_digest.py --status     # 只报告要闻新鲜度, 不推送(给自动化判断用)

要闻文件 _news.txt: 每行一条(用两个空格缩进的行作为副标题/细节行)
过期判定: _news.txt 修改时间距今 > NEWS_GAP_MIN 分钟 -> 打印 NEWS_STALE
         (真正的"抓要闻"由 WorkBuddy Agent 用 WebSearch 完成, 见自动化任务说明)

合并成一个 info 块推送的原因: 分开推会互相覆盖(后推的替换整块)。
"""
import sys, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import push_market as PM

NEWS_FILE = os.path.join(HERE, "_news.txt")
NEWS_GAP_MIN = 30          # 要闻超过这个分钟数就算过期 -> 提示 Agent 去抓新的
SEP = "── 要闻 ──"


def news_age_min():
    """要闻文件的年龄(分钟); 不存在返回 None"""
    try:
        return (time.time() - os.path.getmtime(NEWS_FILE)) / 60.0
    except OSError:
        return None


def read_news():
    try:
        with open(NEWS_FILE, encoding="utf-8") as f:
            return [ln.rstrip() for ln in f if ln.strip()]
    except OSError:
        return []


def build(with_news=True):
    lines, meta = [], []
    try:
        data, ts = PM.fetch()
        mkt, live = PM.build_lines(data, ts)
        lines += mkt
        meta.append("源:腾讯行情 %s(美东)%s" % (ts, "" if live else " 快照"))
    except Exception as e:
        lines.append("行情获取失败")
        meta.append("行情错误: %r" % e)
    if with_news:
        news = read_news()
        if news:
            lines.append(SEP)
            lines += news
        age = news_age_min()
        if age is None:
            meta.append("要闻: 无")
        else:
            meta.append("要闻: %.0f 分钟前更新" % age)
    return lines, meta


def main():
    a = sys.argv[1:]
    age = news_age_min()
    stale = (age is None) or (age > NEWS_GAP_MIN)

    if "--status" in a:
        print("NEWS_STALE" if stale else "NEWS_FRESH",
              "(要闻%s)" % ("缺失" if age is None else "%.0f 分钟前" % age))
        return 0

    lines, meta = build(with_news=("--no-news" not in a))
    for s in lines:
        print("  " + s)
    for m in meta:
        print("[%s]" % m)
    import agentscreen_client as C
    r = C.push_lines(lines)            # 分块下发: 内容多时单次 paste 过大会丢字节
    if r:
        print("推送: OK (%d 行)" % len(lines))
        # 连上副屏就自愈: 时间不对就同步、天气缺失就补拉(默认 300s 内不重复做)
        rd = C.ensure_ready()
        if not rd.get("skipped"):
            print("自愈: 时间=%s 天气=%s%s" % (rd.get("time"), rd.get("weather"),
                                             (" " + str(rd["weather_text"])) if rd.get("weather_text") else ""))
    else:
        print("[错误] 推送失败 —— " + C.explain())
    if stale:
        print("NEWS_STALE")            # 自动化据此决定是否去 WebSearch 抓要闻
    return 0 if r else 2


if __name__ == "__main__":
    sys.exit(main())
