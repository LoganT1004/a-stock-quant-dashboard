# -*- coding: utf-8 -*-
"""从东方财富拉取日K线数据，保存到 data/ 目录"""
import os, sys
import json, os, urllib.request

DATA_DIR = r"os.path.dirname(os.path.abspath(__file__))\data"
os.makedirs(DATA_DIR, exist_ok=True)

targets = {
    "szzs": "1.000001",   # 上证指数
    "cybz": "0.399006",   # 创业板指
    "kc50": "1.000688",   # 科创50
    "ndx":  "100.NDX",    # 纳斯达克100
    "sox":  "251.SOX",    # 费城半导体(备选100.SOX)
    "ndi":  "100.UDI",    # 美元指数
    "ixic": "100.IXIC",   # 纳斯达克综合
    "vxn":  "100.VXN",    # 纳指波动率VXN
}

def fetch(secid, retries=4):
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
           "?secid=%s&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
           "&klt=101&fqt=1&beg=20250101&end=20261231&lmt=150" % secid)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last_err = e
            time.sleep(2 + attempt * 2)
    raise last_err

import time
for name, secid in targets.items():
    try:
        d = fetch(secid)
        if (not d.get("data") or not d["data"].get("klines")) and name == "sox":
            time.sleep(2)
            d = fetch("100.SOX")  # 备选secid
        if d.get("data") and d["data"].get("klines"):
            with open(os.path.join(DATA_DIR, name + ".json"), "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            kl = d["data"]["klines"]
            print("%s OK: %s bars, name=%s, last=%s" % (name, len(kl), d["data"].get("name"), kl[-1][:10]))
        else:
            print("%s EMPTY secid=%s" % (name, secid))
    except Exception as e:
        print("%s ERROR: %s" % (name, e))
    time.sleep(1.5)
