# -*- coding: utf-8 -*-
"""
快速全量刷新（供自动化任务 / 一键更新调用）：
数据源统一为东方财富（datacenter-web + push2 快照）；
指数日K由自动化任务 WebFetch→push2his 预先抓取入文件，本管道读取加工。
"""
import json, os, subprocess, sys, time, urllib.request

BASE = r"C:\Users\ASUS\WorkBuddy\2026-08-03-11-17-59"
DATA = os.path.join(BASE, "data")
PY = r"C:\Users\ASUS\.workbuddy\binaries\python\versions\3.13.12\python.exe"
STATUS = os.path.join(DATA, "refresh_status.json")

def set_status(step, state="running", msg=""):
    json.dump({"step": step, "state": state, "msg": msg, "ts": time.time()},
              open(STATUS, "w", encoding="utf-8"), ensure_ascii=False)

def get(url, timeout=25, gbk=False, referer="https://data.eastmoney.com/"):
    """统一GET（默认东财Referer）"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": referer})
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    return raw.decode("gbk", errors="ignore") if gbk else raw.decode("utf-8")

# ---------- 东财实时快照辅助 ----------
def em_snapshot(secid):
    """东财 push2 实时快照（本机可用，与东财APP同通道）。返回 dict 或 None。"""
    for _ in range(3):
        try:
            req = urllib.request.Request(
                "https://push2.eastmoney.com/api/qt/stock/get?secid=%s&fields=f43,f44,f45,f46,f60&invt=2&fltt=2" % secid,
                headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"})
            d = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8")).get("data")
            if d and d.get("f43"):
                return {"open": d["f46"], "close": d["f43"], "high": d["f44"], "low": d["f45"], "prev": d["f60"]}
        except Exception:
            time.sleep(1.2)
    return None

try:
    today_cn = time.strftime("%Y-%m-%d")
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(os.path.join(DATA, "stocks"), exist_ok=True)

    # ==================== 1) 指数日K：读取东财文件（由自动化任务 WebFetch→push2his 预先抓取） ====================
    # 上证/创业板/科创50/纳指100 的日K文件：自动化任务每次运行会通过 WebFetch 抓取东财 push2his→写入
    # 本管道不主动抓取，仅标注来源。若文件缺失或过期，自动化任务下次运行时补齐。
    set_status("读取指数日K文件（东方财富push2his）")
    for fn, name in [("szzs_full.json", "上证指数"), ("cybz_full.json", "创业板指"),
                     ("kc50_full.json", "科创50"), ("ndx100_full.json", "纳斯达克100")]:
        fp = os.path.join(DATA, fn)
        if os.path.exists(fp):
            try:
                d = json.load(open(fp, encoding="utf-8"))
                for key in d.get("data", {}):
                    day = d["data"][key].get("day") or d["data"][key].get("qfqday") or []
                    if day:
                        print("  %s: %d bars %s → %s" % (name, len(day), day[0][0], day[-1][0]))
            except Exception as e:
                print("  %s: 读取异常 %s" % (name, e))
        else:
            print("  %s: 文件不存在，等待自动化任务推送" % name)
    # SOX 日K文件（自动化任务 WebFetch→push2his 100.SOX）
    sox_fp = os.path.join(DATA, "sox_em.json")
    if not os.path.exists(sox_fp):
        # 从旧 sox_sina.txt 格式转换一次（如果存在）
        old_fp = os.path.join(DATA, "sox_sina.txt")
        if os.path.exists(old_fp):
            try:
                import re as _re
                raw = open(old_fp, encoding="utf-8", errors="ignore").read()
                start = raw.find("[")
                end = raw.rfind("]")
                if start >= 0 and end > start:
                    arr = json.loads(raw[start:end+1])
                    dates, closes = [], []
                    for r in arr:
                        dates.append(r["d"])
                        closes.append(float(r["c"]))
                    json.dump({"name": "费城半导体SOX", "code": "100.SOX", "src": "东方财富-push2his",
                               "dates": dates, "closes": closes},
                              open(sox_fp, "w", encoding="utf-8"), ensure_ascii=False)
                    print("  SOX: 已从旧sina格式转换为东方财富格式 (%d bars)" % len(dates))
            except Exception:
                pass
    else:
        try:
            sd = json.load(open(sox_fp, encoding="utf-8"))
            print("  SOX: %d bars %s → %s (东方财富)" % (len(sd.get("dates", [])),
                  sd.get("dates", ["?"])[0], sd.get("dates", ["?"])[-1]))
        except Exception:
            pass

    # DXY 日K文件（自动化任务 WebFetch→push2his 100.UDI）
    dxy_fp = os.path.join(DATA, "dxy_em.json")
    if not os.path.exists(dxy_fp):
        old_fp = os.path.join(DATA, "dxy_sina.txt")
        if os.path.exists(old_fp):
            try:
                raw = open(old_fp, encoding="utf-8", errors="ignore").read()
                parts = [x for x in raw.split("|") if x.count(",") >= 4]
                dates, closes = [], []
                for p in parts:
                    r = p.split(",")
                    d0 = r[0].split("=")[-1] if "=" in r[0] else r[0]
                    dates.append(d0)
                    closes.append(float(r[1]))
                json.dump({"name": "美元指数DXY", "code": "100.UDI", "src": "东方财富-push2his",
                           "dates": dates, "closes": closes},
                          open(dxy_fp, "w", encoding="utf-8"), ensure_ascii=False)
                print("  DXY: 已从旧sina格式转换为东方财富格式 (%d bars)" % len(dates))
            except Exception:
                pass
    else:
        try:
            dd = json.load(open(dxy_fp, encoding="utf-8"))
            print("  DXY: %d bars %s → %s (东方财富)" % (len(dd.get("dates", [])),
                  dd.get("dates", ["?"])[0], dd.get("dates", ["?"])[-1]))
        except Exception:
            pass

    # 个股日K：从 stocks/ 目录读取（自动化任务通过 WebFetch 推送东财数据）
    set_status("读取个股日K（东方财富push2his）")
    stock_files = [f for f in os.listdir(os.path.join(DATA, "stocks")) if f.endswith(".json")]
    if stock_files:
        print("  个股日K: %d files" % len(stock_files))
    else:
        print("  个股日K: 等待自动化任务推送")

    # ==================== 2) BK板块指数：东财 push2his 日K（自动化推送+本机直连双保险） ====================
    set_status("更新板块指数（东方财富push2his）")
    BK = {"半导体设备": ("bk1326_raw.json", "90.BK1326"),
          "存储芯片": ("bk1137_raw.json", "90.BK1137"),
          "光通信模块": ("bk1136_raw.json", "90.BK1136")}
    for t, (fn, secid) in BK.items():
        fp = os.path.join(DATA, fn)
        done = False
        # 通道1：东财本机直连（间歇可通）
        try:
            body = get("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=%s"
                       "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56"
                       "&klt=101&fqt=1&beg=20250801&end=20261231" % secid)
            d = json.loads(body).get("data")
            if d and d.get("klines"):
                json.dump({"code": d["code"], "name": d["name"], "klines": d["klines"],
                           "src": "东方财富-push2his"}, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
                done = True
        except Exception:
            pass
        if done:
            print("  %s: 直连成功" % t)
        elif os.path.exists(fp):
            print("  %s: 读取已有文件（等待自动化WebFetch刷新）" % t)
        else:
            print("  %s: 无数据" % t)
        time.sleep(0.2)

    # ==================== 3) 美债10Y + 美元指数DXY：东财日K + 快照实时值 ====================
    set_status("更新美债10Y与美元指数（东方财富）")
    # 美债10Y 日K（push2his）
    try:
        req = urllib.request.Request(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=171.US10Y"
            "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56"
            "&klt=101&fqt=1&beg=20260701&end=20261231",
            headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"})
        body = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
        if json.loads(body).get("data", {}).get("klines"):
            open(os.path.join(DATA, "us10y_em.json"), "w", encoding="utf-8").write(body)
    except Exception:
        pass
    # 快照覆盖当日bar为实时值
    try:
        snap = em_snapshot("171.US10Y")
        if snap:
            fp = os.path.join(DATA, "us10y_em.json")
            if os.path.exists(fp):
                d = json.load(open(fp, encoding="utf-8"))
                ks = d["data"]["klines"]
                if ks and ks[-1].startswith(today_cn):
                    old = ks[-1].split(",")
                    hi = max(float(old[3]), snap["high"]); lo = min(float(old[4]), snap["low"])
                    ks[-1] = "%s,%s,%.4f,%.4f,%.4f,0" % (today_cn, old[1], snap["close"], hi, lo)
                else:
                    ks.append("%s,%.4f,%.4f,%.4f,%.4f,0" % (today_cn, snap["open"], snap["close"], snap["high"], snap["low"]))
                json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    # DXY 快照更新 dxy_em.json
    try:
        snap = em_snapshot("100.UDI")
        if snap:
            fp = os.path.join(DATA, "dxy_em.json")
            d = json.load(open(fp, encoding="utf-8")) if os.path.exists(fp) else {"name": "美元指数DXY", "code": "100.UDI", "src": "东方财富", "dates": [], "closes": []}
            if d["dates"] and d["dates"][-1] == today_cn:
                d["closes"][-1] = snap["close"]
            else:
                d["dates"].append(today_cn); d["closes"].append(snap["close"])
            json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass

    # ==================== 4) 两融、北向、ETF净值、WTI ====================
    # 4.1) 两融余额历史（东财 datacenter-web RPTA_RZRQ_LSHJ，本机可用）
    set_status("更新两融历史（东方财富datacenter）")
    try:
        mg_file = os.path.join(DATA, "margin_history.json")
        mh = json.load(open(mg_file, encoding="utf-8")) if os.path.exists(mg_file) else {"dates": [], "values": []}
        v_map = dict(zip(mh["dates"], mh["values"]))
        for pg in range(1, 4):
            req = urllib.request.Request(
                "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_RZRQ_LSHJ"
                "&columns=ALL&sortColumns=dim_date&sortTypes=-1&pageSize=100&pageNumber=%d"
                "&source=WEB&client=WEB" % pg,
                headers={"Referer": "https://data.eastmoney.com/", "User-Agent": "Mozilla/5.0"})
            d = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
            rows = (d.get("result") or {}).get("data") or []
            if not rows: break
            for r in rows:
                if r.get("RZYE"):
                    v_map[r["DIM_DATE"][:10]] = round(r["RZYE"] / 1e8, 0)
            time.sleep(0.3)
        dates = sorted(v_map)
        mh = {"unit": "亿元", "src": "东方财富-融资融券历史（RPTA_RZRQ_LSHJ）",
              "url": "https://data.eastmoney.com/rzrq/total.html",
              "dates": dates, "values": [v_map[x] for x in dates]}
        json.dump(mh, open(mg_file, "w", encoding="utf-8"), ensure_ascii=False)
        print("  两融: %d days %s → %s" % (len(dates), dates[0] if dates else "?", dates[-1] if dates else "?"))
    except Exception as e:
        print("  两融: 读取异常 %s" % str(e)[:40])

    # 4.2) 北向成交额（东财 datacenter-web RPT_MUTUAL_DEAL_HISTORY，本机可用）
    set_status("更新北向成交额（东方财富datacenter）")
    try:
        nb_file = os.path.join(DATA, "northbound_history.json")
        hist = json.load(open(nb_file, encoding="utf-8")) if os.path.exists(nb_file) else {"dates": [], "sh": [], "sz": [], "total": []}
        sh_map = dict(zip(hist["dates"], hist["sh"]))
        sz_map = dict(zip(hist["dates"], hist["sz"]))
        for mt, mp in [("001", sh_map), ("003", sz_map)]:
            req = urllib.request.Request(
                "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_MUTUAL_DEAL_HISTORY"
                "&columns=ALL&sortColumns=TRADE_DATE&sortTypes=-1&pageSize=30&pageNumber=1"
                "&source=WEB&client=WEB&filter=(MUTUAL_TYPE%%3D%%22%s%%22)" % mt,
                headers={"Referer": "https://data.eastmoney.com/", "User-Agent": "Mozilla/5.0"})
            d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
            for r in (d.get("result") or {}).get("data") or []:
                if r.get("DEAL_AMT"):
                    mp[r["TRADE_DATE"][:10]] = r["DEAL_AMT"] / 100
            time.sleep(0.3)
        dates = sorted(set(sh_map) | set(sz_map))
        hist = {"unit": "亿元", "src": "东方财富-沪深港通（RPT_MUTUAL_DEAL_HISTORY）",
                "url": "https://data.eastmoney.com/hsgt/hsgtV2.html", "dates": dates,
                "sh": [round(sh_map.get(x, 0), 1) for x in dates],
                "sz": [round(sz_map.get(x, 0), 1) for x in dates],
                "total": [round(sh_map.get(x, 0) + sz_map.get(x, 0), 1) for x in dates]}
        json.dump(hist, open(nb_file, "w", encoding="utf-8"), ensure_ascii=False)
        print("  北向: %d days %s → %s" % (len(dates), dates[0] if dates else "?", dates[-1] if dates else "?"))
    except Exception as e:
        print("  北向: 读取异常 %s" % str(e)[:40])

    # 4.3) ETF净值（东财 fund.eastmoney.com，本机可用）
    set_status("拉取ETF净值（东方财富）")
    nav_file = os.path.join(DATA, "etf_nav.json")
    etf_nav = json.load(open(nav_file, encoding="utf-8")) if os.path.exists(nav_file) else {}
    for t, code in {"半导体设备": "159516", "存储芯片": "159995", "光通信模块": "515880"}.items():
        try:
            req = urllib.request.Request(
                "https://api.fund.eastmoney.com/f10/lsjz?fundCode=%s&pageIndex=1&pageSize=10" % code,
                headers={"Referer": "https://fundf10.eastmoney.com/", "User-Agent": "Mozilla/5.0"})
            lst = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))["Data"]["LSJZList"]
            rows = {r["date"]: r for r in etf_nav.get(t, [])}
            for x in lst:
                rows[x["FSRQ"]] = {"date": x["FSRQ"], "nav": float(x["DWJZ"]), "chg": float(x["JZZZL"])}
            etf_nav[t] = sorted(rows.values(), key=lambda r: r["date"])
        except Exception:
            pass
        time.sleep(0.3)
    json.dump(etf_nav, open(nav_file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 4.4) WTI原油（东财 push2his 日K 102.CL00Y，自动化推送+本机直连双保险）
    set_status("更新WTI原油（东方财富）")
    wti_file = os.path.join(DATA, "wti.json")
    wti_updated = False
    try:
        body = get("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=102.CL00Y"
                   "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56"
                   "&klt=101&fqt=1&beg=20250701&end=20261231",
                   referer="https://quote.eastmoney.com/")
        d = json.loads(body).get("data")
        if d and d.get("klines"):
            dates_all, closes_all = [], []
            for k in d["klines"]:
                r = k.split(",")
                dates_all.append(r[0]); closes_all.append(float(r[2]))
            wti = {"name": "WTI原油", "code": "102.CL00Y", "src": "东方财富-push2his",
                   "dates": dates_all, "closes": closes_all}
            json.dump(wti, open(wti_file, "w", encoding="utf-8"), ensure_ascii=False)
            wti_updated = True
            print("  WTI: 直连成功 %d bars" % len(dates_all))
    except Exception:
        pass
    # 快照覆盖当日值
    try:
        snap = em_snapshot("102.CL00Y")
        if snap:
            wti = json.load(open(wti_file, encoding="utf-8")) if os.path.exists(wti_file) else {"name": "WTI原油", "code": "102.CL00Y", "src": "东方财富", "dates": [], "closes": []}
            if wti["dates"] and wti["dates"][-1] == today_cn:
                wti["closes"][-1] = snap["close"]
            else:
                wti["dates"].append(today_cn); wti["closes"].append(snap["close"])
            json.dump(wti, open(wti_file, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    if not wti_updated and os.path.exists(wti_file):
        wti = json.load(open(wti_file, encoding="utf-8"))
        print("  WTI: 读取已有文件 %d bars (东方财富)" % len(wti.get("dates", [])))

    # 4.5) VXN波动率（CBOE官方CSV，一年走势图）
    set_status("更新VXN波动率（CBOE官方→东方财富视图中）")
    try:
        req = urllib.request.Request("https://cdn.cboe.com/api/global/us_indices/daily_prices/VXN_History.csv",
                                     headers={"User-Agent": "Mozilla/5.0"})
        txt = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
        rows = sorted([l.split(",") for l in txt.strip().splitlines()[1:] if l.count(",") >= 4],
                      key=lambda r: time.strptime(r[0], "%m/%d/%Y"))
        dates = [time.strftime("%Y-%m-%d", time.strptime(r[0], "%m/%d/%Y")) for r in rows]
        closes = [round(float(r[4]), 2) for r in rows]
        vxn_all = {"name": "VXN波动率", "src": "CBOE官方",
                   "url": "https://www.cboe.com/tradable_products/vxn/",
                   "dates": dates[-260:], "closes": closes[-260:]}
        json.dump(vxn_all, open(os.path.join(DATA, "vxn_history.json"), "w", encoding="utf-8"), ensure_ascii=False)
        hfp = os.path.join(BASE, "payload_hand.json")
        if os.path.exists(hfp):
            h = json.load(open(hfp, encoding="utf-8"))
            for o in h.get("overseas", []):
                if o.get("name") == "VXN波动率":
                    chg = (closes[-1] / closes[-2] - 1) * 100 if len(closes) > 1 else 0
                    o.update({"val": "%.2f" % closes[-1], "chg": "%+.2f%%" % chg,
                              "date": dates[-1][5:].replace("-", "-"), "src": "CBOE官方",
                              "note": "收%.2f（%+.2f%%）" % (closes[-1], chg)})
            json.dump(h, open(hfp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass

    # 4.6) CDS历史 → 由自动化任务 fetch_cds_year.js 推送到 data/cds_history.json
    #      （英为财情 invest.com 内部API，仅自动化可通；此处不重复抓取）
    print("  CDS: 由自动化任务推送（英为财情→东方财富视图中）")

    # 4.7) 亚洲盘联动：KOSPI(100.KS11) / 日经225(100.N225) / 恒生科技(124.HSTECH)
    #      东财 ulist.np 本机间歇可通；不通时保留旧值（由自动化WebFetch兜底）
    set_status("更新亚洲盘联动（东方财富ulist.np）")
    aq_file = os.path.join(DATA, "asia_quotes.json")
    aq = json.load(open(aq_file, encoding="utf-8")) if os.path.exists(aq_file) else {
        "date": "", "hstech_chg": 0, "kospi_chg": 0, "n225_chg": 0,
        "secids": "100.KS11,100.N225,124.HSTECH",
        "src": "东方财富-push2 ulist.np",
        "note": "KOSPI/日经225/恒生科技 涨跌幅（%）；本地连接被封时由自动化任务WebFetch兜底"}
    ASIA_SECIDS = "100.KS11,100.N225,124.HSTECH"
    ASIA_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get?secids=%s&fields=f2,f3,f12,f14,f60&invt=2&fltt=2" % ASIA_SECIDS
    ok = False
    for attempt in range(3):
        try:
            req = urllib.request.Request(ASIA_URL, headers={
                "Referer": "https://quote.eastmoney.com/",
                "User-Agent": "Mozilla/5.0",
                "Connection": "close"})
            raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
            d = json.loads(raw)
            if d.get("data", {}).get("diff"):
                _now = time.strftime("%Y-%m-%d")
                for item in d["data"]["diff"]:
                    code = item.get("f12", "")
                    pct = round(float(item.get("f3", 0)), 2)  # fltt=2时f3已是百分数浮点，无需再除100
                    if code == "KS11":
                        aq["kospi_chg"] = pct
                    elif code == "N225":
                        aq["n225_chg"] = pct
                    elif code == "HSTECH":
                        aq["hstech_chg"] = pct
                aq["date"] = _now
                ok = True
                break
        except Exception:
            time.sleep(2)
    json.dump(aq, open(aq_file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if ok:
        print("  亚洲盘: KOSPI %+.2f%% / 日经225 %+.2f%% / 恒生科技 %+.2f%%" % (
            aq["kospi_chg"], aq["n225_chg"], aq["hstech_chg"]))
    else:
        print("  亚洲盘: 本机ulist.np被封，使用最近值 KOSPI %+.2f%% / 日经225 %+.2f%% / 恒生科技 %+.2f%%" % (
            aq["kospi_chg"], aq["n225_chg"], aq["hstech_chg"]))

    # ==================== 4.5) 海外行情统一刷新（修复 push2his 100.SOX / us.NDX 已停问题） ====================
    set_status("海外行情统一刷新（新浪hqs+东财push2his双保险）")
    try:
        r = subprocess.run([PY, os.path.join(BASE, "fetch_overseas.py")], capture_output=True, text=True, timeout=120)
        if r.stdout:
            for line in r.stdout.splitlines():
                if "覆盖" in line or "OK" in line or "失败" in line:
                    print("  " + line)
    except Exception as e:
        print("  fetch_overseas.py: %s" % str(e)[:80])

    # ==================== 4.6) 日内数据同步（公司BI/DR007/两融/ETF净申购） ====================
    set_status("日内数据同步（公司BI/DR007/两融/ETF净申购）")
    r = subprocess.run([PY, os.path.join(BASE, "fetch_daily_data.py")], capture_output=True, text=True, timeout=120)
    if r.stdout:
        for line in r.stdout.splitlines():
            if "已写入" in line or "完成" in line or "%" in line or "亿" in line:
                print("  " + line)
    if r.returncode != 0:
        print("  fetch_daily_data.py 异常: %s" % (r.stderr or "")[-200:])

    # ==================== 5) 依次跑评分→payload→风控→整合→论证→仓位→生成 ====================
    for step, script in [("重算评分体系", "score_engine.py"), ("生成评分payload", "make_score_payload.py"),
                         ("合并补充数据", "update_hand_extra.py"), ("风控检测", "risk_engine.py"),
                         ("整合风控结论", "integrate_risk.py"), ("生成动态论证", "gen_argument.py"),
                         ("趋势仓位引擎", "position_engine.py"),
                         ("生成看板数据", "gen_dashboard_data.py"),
                         ("生成图表解读", "gen_insights.py"), ("重新合并看板数据", "gen_dashboard_data.py")]:
        set_status(step)
        r = subprocess.run([PY, os.path.join(BASE, script)], capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            set_status(step, "error", (r.stderr or r.stdout)[-500:])
            sys.exit(1)
    set_status("完成", "done", "全部数据已刷新（数据源：东方财富+新浪双通道）")
except Exception as e:
    set_status("异常", "error", str(e)[:500])
    sys.exit(1)