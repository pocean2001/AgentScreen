# 用法: python push_weather.py [城市]     # 省略城市则按出口 IP 自动定位
# 查询当天天气(含城市)并推到副屏 -> 日期行显示: 日期 | 城市 + 图标 + 文字
import sys, os, json, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agentscreen_client as C

GEO_API = "http://ip-api.com/json/?lang=zh-CN&fields=status,country,regionName,city,lat,lon"
GEO_API_EN = "http://ip-api.com/json/?fields=status,city,regionName"   # 英文兜底(中文都缺字时用)
CITY_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".as_city")

ZH = [("thunder", "雷"), ("snow", "雪"), ("sleet", "雨夹雪"), ("rain", "雨"),
      ("drizzle", "毛毛雨"), ("shower", "阵雨"), ("fog", "雾"), ("mist", "薄雾"),
      ("haze", "霾"), ("overcast", "阴"), ("cloud", "多云"), ("clear", "晴"),
      ("sunny", "晴"), ("wind", "风")]

def map_icon(cond):
    c = (cond or "").lower()
    if any(k in c for k in ("雷", "thunder", "storm")):
        return "thunder"
    if any(k in c for k in ("雪", "snow", "sleet", "冰")):
        return "snow"
    if any(k in c for k in ("雨", "rain", "drizzle", "shower")):
        return "rain"
    if any(k in c for k in ("雾", "霾", "fog", "mist", "haze", "smoky")):
        return "fog"
    if any(k in c for k in ("阴", "overcast")):
        return "overcast"
    if any(k in c for k in ("云", "cloud")):
        return "cloud"
    if any(k in c for k in ("晴", "clear", "sunny")):
        return "sun"
    return "cloud"

def to_zh(cond):
    """英文天气描述转中文(已是中文则原样返回)"""
    c = cond or ""
    low = c.lower()
    for en, zh in ZH:
        if en in low:
            return zh
    return c.strip()

def _get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace").strip()


def _clean_city(s):
    """去掉"市/地区"等后缀, 让屏上更紧凑(东莞市 -> 东莞)"""
    s = (s or "").strip()
    for suf in ("市", "地区", "自治州", "特别行政区"):
        if len(s) > len(suf) + 1 and s.endswith(suf):
            return s[:-len(suf)]
    return s


def read_city():
    try:
        with open(CITY_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def detect_city(force=False, timeout=8):
    """按**出口 IP** 定位城市(中文, 带缓存避免每次调 API)。失败返回 None。"""
    if not force:
        c = read_city()
        if c and c.get("city"):
            return c
    try:
        d = json.loads(_get(GEO_API, timeout))
        if d.get("status") != "success":
            return None
        info = {"city": _clean_city(d.get("city")), "region": _clean_city(d.get("regionName")),
                "country": d.get("country") or "", "lat": d.get("lat"), "lon": d.get("lon")}
        if info["city"]:
            try:
                with open(CITY_CACHE, "w", encoding="utf-8") as f:
                    json.dump(info, f, ensure_ascii=False)
            except OSError:
                pass
            return info
    except Exception:
        pass
    return None


def detect_city_en(timeout=8):
    """英文城市名(兜底用: 中文名在板端字库里缺字时)"""
    try:
        d = json.loads(_get(GEO_API_EN, timeout))
        if d.get("status") == "success":
            return (d.get("city") or "").strip()
    except Exception:
        pass
    return ""


def pick_city_name(info):
    """挑一个**板端字库画得出来**的显示名: 中文城市 -> 中文省 -> 英文城市。

    板端字体是裁剪过的: 实测"莞""圳"没有字形, 直接显示"东莞"会变成"东"+空白,
    看着像被遮掉一个字。所以这里用 glyphcheck 实测覆盖后择优。
    """
    cands = [info.get("city"), info.get("region")]
    try:
        import glyphcheck as GC
        for s in cands:
            if s and GC.all_supported(s):
                return s
        en = detect_city_en()
        if en and GC.all_supported(en):
            return en
    except Exception:
        pass
    return info.get("city") or info.get("region") or ""


def fetch_weather(city="", timeout=12):
    """查天气 -> (icon, text, city_display)。

    city 为空时: 优先环境变量 AGENTSCREEN_CITY, 否则按出口 IP 定位; 都拿不到就不显示城市。
    定位到经纬度时用经纬度查天气(避免同名城市查错)。
    """
    disp = q = ""
    if city:
        disp = q = city
    else:
        env = os.environ.get("AGENTSCREEN_CITY")
        if env:
            disp = q = env
        else:
            info = detect_city()
            if info:
                disp = pick_city_name(info)
                q = ("%s,%s" % (info["lat"], info["lon"])
                     if info.get("lat") is not None and info.get("lon") is not None else disp)
    raw = _get("https://wttr.in/%s?format=%%C;%%t&lang=zh" % urllib.parse.quote(q), timeout)
    parts = raw.split(";")
    cond = parts[0].strip() if parts else ""
    temp = parts[1].strip() if len(parts) > 1 else ""
    return map_icon(cond), ("%s %s" % (temp.replace("+", ""), to_zh(cond))).strip(), disp


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--refresh" in sys.argv:                 # 忽略城市缓存, 重新按 IP 定位
        try:
            os.remove(CITY_CACHE)
        except OSError:
            pass
    city = args[0] if args else ""
    try:
        icon, text, disp = fetch_weather(city)
    except Exception as e:
        print("[weather] 查询失败:", repr(e))
        return 1
    print("[weather] 城市=%s icon=%s text=%s" % (disp or "(未识别)", icon, text))
    r = C.call({"op": "weather", "icon": icon, "text": text, "city": disp})
    if r:
        print(r)
        return 0
    print("[错误] 推送失败 —— " + C.explain())
    return 2

if __name__ == "__main__":
    sys.exit(main())
