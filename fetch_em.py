# -*- coding: utf-8 -*-
"""东财数据多域名轮询采集（应对本机 push2 系列偶发断连）"""
import os, sys
import urllib.request, json, os, time

DATA = r"os.path.dirname(os.path.abspath(__file__))\data"
HOSTS_HIS = ["push2his", "1.push2his", "3.push2his", "13.push2his", "17.push2his", "61.push2his", "71.push2his"]
HOSTS_RT = ["push2", "1.push2", "3.push2", "13.push2", "17.push2"]

def get(url, timeout=15):
    req = urllib.request.Request(url, headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")

def fetch_kline(secid, beg, end, tries=2):
    for h in HOSTS_HIS:
        for _ in range(tries):
            try:
                url = ("https://%s.eastmoney.com/api/qt/stock/kline/get?secid=%s&fields1=f1,f2,f3,f4,f5,f6"
                       "&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&beg=%s&end=%s" % (h, secid, beg, end))
                body = get(url)
                d = json.loads(body)
                if d.get("data") and d["data"].get("klines"):
                    return d["data"]
            except Exception:
                time.sleep(0.5)
    return None

def fetch_fflow(secid, tries=2):
    for h in HOSTS_RT:
        for _ in range(tries):
            try:
                url = ("https://%s.eastmoney.com/api/qt/stock/fflow/daykline/get?secid=%s&fields1=f1,f2,f3,f7"
                       "&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&lmt=5" % (h, secid))
                body = get(url)
                d = json.loads(body)
                if d.get("data") and d["data"].get("klines"):
                    return d["data"]
            except Exception:
                time.sleep(0.8)
    return None

def main():
    # 1) 三只代表性ETF日K
    etfs = {"etf_sb": ("0.159516", "半导体设备ETF国泰"), "etf_cc": ("0.159995", "芯片ETF华夏"), "etf_cm": ("1.515880", "通信ETF国泰")}
    etf_out = {}
    for key, (secid, name) in etfs.items():
        d = fetch_kline(secid, "20250801", "20260804")
        if d:
            etf_out[key] = d
            ks = d["klines"]
            print(key, name, "OK", len(ks), "bars | last:", ks[-1].split(",")[0], ks[-1].split(",")[2])
        else:
            print(key, name, "FAIL")
        time.sleep(0.5)
    json.dump(etf_out, open(os.path.join(DATA, "etf_klines.json"), "w", encoding="utf-8"), ensure_ascii=False)

    # 2) 美债10Y
    d = fetch_kline("171.US10Y", "20250801", "20260804")
    if d:
        json.dump({"data": d}, open(os.path.join(DATA, "us10y_em.json"), "w", encoding="utf-8"))
        ks = d["klines"]
        print("US10Y OK", len(ks), "bars | last:", ks[-1].split(",")[0], ks[-1].split(",")[2])
    else:
        print("US10Y FAIL")

    # 3) 16家个股资金流向（降速）
    codes = {"sz002371": "0.002371", "sh688012": "1.688012", "sh688072": "1.688072", "sh688120": "1.688120",
             "sz300604": "0.300604", "sh688361": "1.688361", "sh688825": "1.688825", "sh603986": "1.603986",
             "sh688525": "1.688525", "sh688766": "1.688766", "sz001309": "0.001309", "sz301308": "0.301308",
             "sz300308": "0.300308", "sz300502": "0.300502", "sz300394": "0.300394", "sz002281": "0.002281"}
    flows = json.load(open(os.path.join(DATA, "stock_flows.json"), encoding="utf-8")) if os.path.exists(os.path.join(DATA, "stock_flows.json")) else {}
    for c, secid in codes.items():
        d = fetch_fflow(secid)
        if d:
            last = d["klines"][-1].split(",")
            flows[d["name"]] = {"main": round(float(last[1]) / 1e8, 2), "pct": float(last[6]), "date": last[0], "src": "东方财富"}
            print("fflow", d["name"], flows[d["name"]]["main"], "亿")
        else:
            print("fflow", c, "FAIL")
        time.sleep(1.2)
    json.dump(flows, open(os.path.join(DATA, "stock_flows.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok = sum(1 for v in flows.values() if isinstance(v, dict) and "main" in v)
    print("fflow done:", ok, "/", len(codes))

if __name__ == "__main__":
    main()
