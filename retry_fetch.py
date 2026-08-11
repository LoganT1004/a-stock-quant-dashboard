# -*- coding: utf-8 -*-
"""多域名轮询重试拉取缺失的K线数据"""
import os, sys
import json, urllib.request, time, os, random, sys

DATA_DIR = r"os.path.dirname(os.path.abspath(__file__))\data"
hosts = ["push2his.eastmoney.com", "3.push2his.eastmoney.com", "13.push2his.eastmoney.com",
         "28.push2his.eastmoney.com", "50.push2his.eastmoney.com", "63.push2his.eastmoney.com",
         "84.push2his.eastmoney.com", "1.push2his.eastmoney.com", "7.push2his.eastmoney.com"]

targets = {"cybz": "0.399006", "kc50": "1.000688", "sox": "251.SOX", "ndi": "100.UDI",
           "ixic": "100.IXIC", "vxn": "100.VXN"}

def has_data(name):
    p = os.path.join(DATA_DIR, name + ".json")
    if not os.path.exists(p):
        return False
    try:
        d = json.load(open(p, encoding="utf-8"))
        return bool(d.get("data") and d["data"].get("klines"))
    except Exception:
        return False

def try_fetch(secid, rounds=2):
    for _ in range(rounds):
        for h in hosts:
            url = ("https://%s/api/qt/stock/kline/get?secid=%s&fields1=f1,f2,f3,f4,f5,f6"
                   "&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=1&beg=20250101&end=20261231&lmt=150" % (h, secid))
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Referer": "https://quote.eastmoney.com/"})
                d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
                if d.get("data") and d["data"].get("klines"):
                    return d, h
            except Exception:
                pass
            time.sleep(3 + random.random() * 2)
    return None, None

for name, secid in targets.items():
    if has_data(name):
        print("%s SKIP (already have data)" % name)
        continue
    d, h = try_fetch(secid)
    if not d and name == "sox":
        d, h = try_fetch("100.SOX", rounds=1)
    if d:
        with open(os.path.join(DATA_DIR, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        kl = d["data"]["klines"]
        print("%s OK via %s: %d bars, last=%s" % (name, h, len(kl), kl[-1][:10]))
    else:
        print("%s FAIL" % name)
    sys.stdout.flush()
    time.sleep(4)
print("DONE")
