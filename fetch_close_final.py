# -*- coding: utf-8 -*-
"""收盘终值抓取：BK板块指数+美债10Y（东财，本机直连带重试）"""
import urllib.request, json, time, os

DATA = r"C:\Users\ASUS\WorkBuddy\2026-08-03-11-17-59\data"

def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")

for secid, fn in [("90.BK1326", "bk1326_raw.json"), ("90.BK1137", "bk1137_raw.json"),
                  ("90.BK1136", "bk1136_raw.json"), ("171.US10Y", "us10y_em.json")]:
    done = False
    for attempt in range(3):
        try:
            body = get("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=%s&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&beg=20250801&end=20261231" % secid)
            d = json.loads(body).get("data")
            if d and d.get("klines"):
                json.dump({"code": d["code"], "name": d["name"], "klines": d["klines"]},
                          open(os.path.join(DATA, fn), "w", encoding="utf-8"), ensure_ascii=False)
                k = d["klines"][-1].split(","); k2 = d["klines"][-2].split(",")
                print(secid, d["name"], k[0], "close", k[2], "chg: %.2f%%" % ((float(k[2]) / float(k2[2]) - 1) * 100))
                done = True
                break
        except Exception as e:
            print(secid, "attempt", attempt + 1, str(e)[:40])
            time.sleep(2)
    if not done:
        print(secid, "FAILED all attempts")
