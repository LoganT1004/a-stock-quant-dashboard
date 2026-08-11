# -*- coding: utf-8 -*-
"""一次性脚本：抓板块指数日K/US10Y/个股资金流向（东财push2his+ulist.np），落盘data/"""
import json, urllib.request, time, sys

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://quote.eastmoney.com/"}

def get(url, retry=3):
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"  retry{i}: {e}")
            time.sleep(2)
    return None

TODAY = "2026-08-10"
ok = True

# 1) 三大板块指数日K
for secid, fn in [("90.BK1326", "bk1326_raw.json"), ("90.BK1137", "bk1137_raw.json"), ("90.BK1136", "bk1136_raw.json")]:
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&beg=20250801&end=20261231"
    j = get(url)
    if j and j.get("data") and j["data"].get("klines"):
        d = j["data"]
        payload = {"code": d["code"], "name": d["name"], "klines": d["klines"]}
        with open(f"data/{fn}", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        last = d["klines"][-1].split(",")[0]
        print(f"{fn}: {d['name']} {len(d['klines'])} bars, last={last} {'OK' if last==TODAY else 'MISMATCH!'}")
        if last != TODAY:
            ok = False
    else:
        print(f"{fn}: FAILED")
        ok = False
    time.sleep(1)

# 2) US10Y 日K 补历史
url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=171.US10Y&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&beg=20250101&end=20261231"
j = get(url)
if j and j.get("data") and j["data"].get("klines"):
    with open("data/us10y_em.json", "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False)
    print(f"us10y_em.json: {len(j['data']['klines'])} bars, last={j['data']['klines'][-1].split(',')[0]}")
else:
    print("us10y_em.json: FAILED")

# 3) 个股资金流向 16家
secids = "0.002371,1.688012,1.688072,1.688120,0.300604,1.688361,1.688825,1.603986,1.688525,1.688766,0.001309,0.301308,0.300308,0.300502,0.300394,0.002281"
url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?secids={secids}&fields=f3,f12,f14,f62,f66,f72,f184&invt=2&fltt=2"
j = get(url)
if j and j.get("data") and j["data"].get("diff"):
    out = {}
    for it in j["data"]["diff"]:
        name = it.get("f14")
        if not name:
            continue
        out[name] = {
            "main": round((it.get("f62") or 0) / 1e8, 2),
            "super": round((it.get("f66") or 0) / 1e8, 2),
            "big": round((it.get("f72") or 0) / 1e8, 2),
            "pct": it.get("f3"),         # f3 才是涨跌幅%
            "ratio_pct": it.get("f184"),  # f184 是主力净流入占比%
            "date": TODAY,
            "src": "东方财富",
        }
    with open("data/stock_flows.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"stock_flows.json: {len(out)} stocks updated, date={TODAY}")
    for k, v in out.items():
        print(f"  {k}: 主力{v['main']}亿 pct={v['pct']}")
else:
    print("stock_flows.json: FAILED")
    ok = False

sys.exit(0 if ok else 1)
