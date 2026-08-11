# -*- coding: utf-8 -*-
"""拉取日K线：腾讯ifzq(A股/纳指) + 新浪(SOX/DXY/VXN)，统一转为东财格式存入 data/"""
import json, os, urllib.request

DATA_DIR = r"C:\Users\ASUS\WorkBuddy\2026-08-03-11-17-59\data"
os.makedirs(DATA_DIR, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://finance.sina.com.cn"}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="ignore")

def save_em_format(fname, name, rows):
    """rows: list of dict(date,open,close,high,low,vol)"""
    klines = ["%s,%s,%s,%s,%s,%s,0" % (r["date"], r["open"], r["close"], r["high"], r["low"], r["vol"]) for r in rows]
    obj = {"data": {"name": name, "klines": klines}}
    with open(os.path.join(DATA_DIR, fname + ".json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    print("%s saved: %d bars, last=%s close=%s" % (fname, len(rows), rows[-1]["date"], rows[-1]["close"]))

def fetch_tencent(fname, symbol, cname, n=150):
    if symbol.startswith("us"):
        url = "https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get?param=" + symbol + ",day,,," + str(n) + ",qfq"
    else:
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=" + symbol + ",day,,," + str(n) + ",qfq"
    d = json.loads(get(url))
    raw = d["data"][symbol]
    arr = raw.get("qfqday") or raw.get("day")
    rows = [{"date": x[0], "open": x[1], "close": x[2], "high": x[3], "low": x[4], "vol": x[5]} for x in arr]
    save_em_format(fname, cname, rows)

def fetch_sina_us(fname, symbol, cname, n=150):
    url = "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var%20x=/US_MinKService.getDailyK?symbol=" + symbol
    txt = get(url)
    s = txt[txt.index("([") + 1: txt.rindex(")") ]
    arr = json.loads(s)
    rows = [{"date": x["d"], "open": x["o"], "close": x["c"], "high": x["h"], "low": x["l"], "vol": x.get("v", "0")} for x in arr[-n:]]
    save_em_format(fname, cname, rows)

def fetch_sina_forex(fname, symbol, cname, n=150):
    url = "https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/var%20d=/NewForexService.getDayKLine?symbol=" + symbol
    txt = get(url)
    s = txt[txt.index('("') + 2: txt.rindex('")')]
    parts = [p for p in s.split("|") if p.strip()]
    rows = []
    for p in parts[-n:]:
        f = p.split(",")
        # 格式: date,open,low,high,close
        rows.append({"date": f[0], "open": f[1], "close": f[4], "high": f[3], "low": f[2], "vol": "0"})
    save_em_format(fname, cname, rows)

jobs = [
    ("tencent", "szzs", "sh000001", "上证指数"),
    ("tencent", "cybz", "sz399006", "创业板指"),
    ("tencent", "kc50", "sh000688", "科创50"),
    ("tencent", "ndx",  "usNDX",   "纳斯达克100"),
    ("tencent", "ixic", "usIXIC",  "纳斯达克综合"),
    ("sina_us", "sox",  ".SOX",    "费城半导体SOX"),
    ("sina_forex", "ndi", "DINIW", "美元指数DXY"),
    ("sina_us", "vxn",  ".VXN",    "纳指波动率VXN"),
]
for kind, fname, sym, cname in jobs:
    try:
        if kind == "tencent":
            fetch_tencent(fname, sym, cname)
        elif kind == "sina_us":
            fetch_sina_us(fname, sym, cname)
        else:
            fetch_sina_forex(fname, sym, cname)
    except Exception as e:
        print("%s ERROR: %s" % (fname, e))
