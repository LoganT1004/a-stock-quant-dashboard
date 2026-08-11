# -*- coding: utf-8 -*-
"""补齐缺失K线：创业板指/科创50走腾讯日线（转为东财格式）；SOX/DXY再试东财"""
import os, sys
import json, urllib.request, time, os, random, sys

DATA_DIR = r"os.path.dirname(os.path.abspath(__file__))\data"

def urlopen_json(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://quote.eastmoney.com/"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))

def save_em_format(name, disp_name, code, klines):
    d = {"rc": 0, "data": {"code": code, "name": disp_name, "klines": klines}}
    with open(os.path.join(DATA_DIR, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    print("%s saved: %d bars, last=%s" % (name, len(klines), klines[-1][:10]))
    sys.stdout.flush()

# 1) 腾讯日线补齐 A 股指数
tx_targets = {"cybz": ("sz399006", "创业板指"), "kc50": ("sh000688", "科创50")}
for name, (code, disp) in tx_targets.items():
    try:
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,400,qfq" % code
        d = urlopen_json(url)
        node = d["data"][code]
        rows = node.get("qfqday") or node.get("day")
        klines = []
        for r in rows:
            # r: [date, open, close, high, low, vol, ...]
            amt = r[8] if len(r) > 8 else "0"
            klines.append("%s,%s,%s,%s,%s,%s,%s" % (r[0], r[1], r[2], r[3], r[4], r[5], amt))
        save_em_format(name, disp, code, klines)
    except Exception as e:
        print("%s TX ERR: %s" % (name, e))
    time.sleep(2)

# 2) SOX / DXY 再试东财多域名
hosts = ["push2his.eastmoney.com", "5.push2his.eastmoney.com", "19.push2his.eastmoney.com",
         "41.push2his.eastmoney.com", "58.push2his.eastmoney.com", "76.push2his.eastmoney.com",
         "90.push2his.eastmoney.com", "2.push2his.eastmoney.com"]
em_targets = {"sox": ["251.SOX", "100.SOX"], "ndi": ["100.UDI"]}
for name, secids in em_targets.items():
    ok = False
    for secid in secids:
        for h in hosts:
            try:
                url = ("https://%s/api/qt/stock/kline/get?secid=%s&fields1=f1,f2,f3,f4,f5,f6"
                       "&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=1&beg=20250101&end=20261231&lmt=150" % (h, secid))
                d = urlopen_json(url, timeout=15)
                if d.get("data") and d["data"].get("klines"):
                    with open(os.path.join(DATA_DIR, name + ".json"), "w", encoding="utf-8") as f:
                        json.dump(d, f, ensure_ascii=False)
                    kl = d["data"]["klines"]
                    print("%s OK via %s secid=%s: %d bars, last=%s" % (name, h, secid, len(kl), kl[-1][:10]))
                    sys.stdout.flush()
                    ok = True
                    break
            except Exception:
                pass
            time.sleep(3 + random.random() * 2)
        if ok:
            break
    if not ok:
        print("%s FAIL (will mark as unavailable)" % name)
        sys.stdout.flush()
    time.sleep(3)
print("DONE")
