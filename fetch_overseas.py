# -*- coding: utf-8 -*-
"""海外行情统一刷新（NDX/SOX/DXY/WTI/US10Y）：
权威源 = 新浪财经 secid（与东方财富APP同源数据）
辅助源 = 东方财富 push2his（251.SOX / 100.UDI / 171.US10Y / 102.CL00Y）

设计原则：
1. 实时值用新浪 hq.sinajs.cn（直接 urllib，无需 WebFetch）抓取，最准且不被封
2. 历史值用东财 push2his（保留现有数据），结尾 bar 用新浪覆盖为最新值
3. 任何抓取失败都不报错，使用 fallback（已有数据或上一个值）

注意：sina secid 里的 `$` 在 URL 中需要 URL 编码为 %24，否则部分环境下会被 shell 吞掉
"""
import os, sys
import json, os, re, time, urllib.request, ssl
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      "Referer": "https://finance.sina.com.cn/"}
EA = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}


def safe_get(url, headers=None, timeout=15, retries=2):
    """通用GET，自动重试"""
    h = {**UA, **(headers or {})}
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return urllib.request.urlopen(req, timeout=timeout, context=ctx).read().decode("utf-8", errors="ignore")
        except Exception as e:
            last_err = str(e)[:120]
            time.sleep(1.2 * (i + 1))
    return None


def parse_sina_line(line):
    """解析新浪 hq.sinajs.cn 单行；返回 dict(code, name, price, pct, open, high, low, prev, date, time) 或 None"""
    m = re.search(r'hq_str_(\S+)="(.*)"', line.strip())
    if not m or not m.group(2).strip():
        return None
    code, raw = m.group(1), m.group(2)
    parts = raw.split(",")
    if code.startswith("DINIW"):
        # 外汇：DINIW 字段顺序: 时间,最新,昨收,涨跌额,成交量,?,?,?,?,名称,日期
        return {
            "code": code, "name": parts[9] if len(parts) >= 10 else "美元指数",
            "price": float(parts[1]), "pct": 0,
            "open": float(parts[3]), "high": float(parts[6]),
            "low": float(parts[7]), "prev": float(parts[2]),
            "date": parts[10] if len(parts) >= 11 else "",
        }
    # 美股指数/股票 (gb_$xxx)
    # parts[3] = 北京时间数据采集时间 "2026-08-08 09:47:52"
    # parts[30] = 昨收（数字）；parts[33] = 美东时间字符串 "Aug 07 05:15PM EDT"
    # 优先用 parts[3]（北京时间），fallback parts[33]（美东时间字符串）
    date_str = parts[3] if len(parts) > 3 else ""
    if not date_str or not date_str.replace("-", "").replace(":", "").replace(" ", "").isdigit():
        # parts[3] 不是日期格式，可能是数字（如涨跌幅），fallback 美东时间字符串
        date_str = parts[33] if len(parts) > 33 else ""
    return {
        "code": code, "name": parts[0] if parts else "",
        "price": _try_float(parts[1]), "pct": _try_float(parts[2]),
        "change": _try_float(parts[4]), "open": _try_float(parts[5]),
        "high": _try_float(parts[6]), "low": _try_float(parts[7]),
        "prev": _try_float(parts[30]) if len(parts) > 30 else _try_float(parts[4]),
        "date": date_str,
    }


def parse_sina_futures(line):
    """解析 hf_* 期货（含WTI）；字段顺序：最新,?,开盘,昨收,最高,最低,时间..."""
    m = re.search(r'hq_str_(\S+)="(.*)"', line.strip())
    if not m or not m.group(2).strip():
        return None
    code, raw = m.group(1), m.group(2)
    parts = raw.split(",")
    # WTI 格式 [最新, ?, 开盘, 昨收, 最高, 最低, 时间, ?, ?, ?, ?, ?, 日期, 名称, ...]
    prev = _try_float(parts[3])
    price = _try_float(parts[0])
    pct = (price / prev - 1) * 100 if (price and prev) else None
    return {
        "code": code, "name": parts[13] if len(parts) > 13 else parts[0],
        "price": price, "prev": prev, "pct": pct,
        "open": _try_float(parts[2]),
        "high": _try_float(parts[4]),
        "low": _try_float(parts[5]),
        "date": parts[12] if len(parts) > 12 else "",
    }


def _try_float(s):
    try:
        return float(s) if s and s != "--" and s != "" else None
    except Exception:
        return None


def fetch_sina(codes):
    """批量抓新浪 secid；codes=['gb_$ndx','gb_$sox','DINIW',...]"""
    code_str = ",".join(codes)
    url = "https://hq.sinajs.cn/list=" + code_str
    text = safe_get(url, timeout=10, retries=3)
    if not text:
        return {}
    out = {}
    for line in text.splitlines():
        # 期货 (hf_*) 用单独解析器
        if "hf_str_" in line or "'hf_" in line:
            pass
        # 通过 code 前缀区分
        r = None
        m = re.search(r'hq_str_(\S+?)="(.*)"', line.strip())
        if m and m.group(1).startswith("hf_"):
            r = parse_sina_futures(line)
        else:
            r = parse_sina_line(line)
        if r:
            out[r["code"]] = r
    return out


def push2his(secid, beg="20250101", end="20261231", klt=101, fqt=1):
    """东财 push2his 日K，返回原始klines字符串列表；失败 None"""
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
           "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56"
           f"&klt={klt}&fqt={fqt}&beg={beg}&end={end}")
    text = safe_get(url, headers=EA, timeout=20)
    if not text:
        return None
    try:
        d = json.loads(text)
        if d.get("data") and d["data"].get("klines"):
            return d["data"]["klines"]
    except Exception:
        pass
    return None


def upsert_bar(filepath, secid_key, code_field, new_date, new_val, key_in_klines=2):
    """把指定文件的最新bar覆盖为(new_date, new_val)；保留其它历史bar
    文件结构：data[secid_key].klines = ["date,open,close,high,low,vol", ...]"""
    d = json.load(open(filepath, encoding="utf-8"))
    klines = d["data"][secid_key]["klines"] if "data" in d and secid_key in d.get("data", {}) else d.get("klines", [])
    if not klines:
        return False
    last = klines[-1].split(",")
    last_date = last[0]
    if last_date == new_date:
        last[key_in_klines] = "%.4f" % new_val
        klines[-1] = ",".join(last)
    else:
        # 追加新bar
        klines.append(f"{new_date},{last[1] if len(last) > 1 else new_val},{new_val},{last[3] if len(last) > 3 else new_val},{last[4] if len(last) > 4 else new_val},0")
    if "data" in d:
        d["data"][secid_key]["klines"] = klines
    else:
        d["klines"] = klines
    json.dump(d, open(filepath, "w", encoding="utf-8"), ensure_ascii=False)
    return True


results = []


def parse_us_market_date(s):
    """从新浪 secid 返回的 parts[3] (北京时间数据时间 '2026-08-08 09:47:52') 解析美股交易日。
    规则：
    - 北京时间周六/周日 → 数据是上周五美股收盘（取上一周五）
    - 北京时间周一/二/三/四 09:30-21:30 → 美股盘中或盘前 → 美股交易日 = 北京时间前一日
    - 北京时间周一/二/三/四 21:30-次日09:30 → 美股盘后/盘前 → 美股交易日 = 北京时间当日
    - 北京时间周五 09:30-21:30 → 美股收盘前 → 美股交易日 = 北京时间前一日（周四，但美股周四是数据还没）
    """
    if not s or len(s) < 10:
        return None
    try:
        from datetime import datetime, timedelta
        dt = datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")
        bj_date = dt.date()
        bj_weekday = dt.weekday()  # 0=周���
        bj_hour = dt.hour
        # 周末（周六=5, 周日=6）→ 数据是上周五
        if bj_weekday == 5:  # 周六
            target = bj_date - timedelta(days=1)
        elif bj_weekday == 6:  # 周日
            target = bj_date - timedelta(days=2)
        elif bj_weekday == 4 and bj_hour >= 21:  # 周五晚
            target = bj_date
        elif bj_hour >= 21 or bj_hour < 9:  # 工作日21:30-次日09:00 之前
            target = bj_date
        else:  # 工作日 09:30-21:00
            target = bj_date - timedelta(days=1)
        return target.strftime("%Y-%m-%d")
    except Exception as e:
        return None


# ========== 1) SOX 费城半导体 (251.SOX) ==========
secid = "251.SOX"
print(f"\n[1] SOX {secid}")
sox_fp = os.path.join(DATA, "sox_em.json")
hist_ok = False
kl = push2his(secid, beg="20250101")
if kl:
    payload = {"name": "费城半导体SOX", "code": secid, "src": "东方财富-push2his",
               "dates": [k.split(",")[0] for k in kl],
               "closes": [float(k.split(",")[2]) for k in kl],
               "volumes": [float(k.split(",")[5]) for k in kl]}
    json.dump(payload, open(sox_fp, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  东财历史OK: {len(kl)} bars, last={kl[-1].split(',')[0]}={kl[-1].split(',')[2]}")
    hist_ok = True
else:
    print(f"  东财历史失败，尝试从archive恢复")
    if not os.path.exists(sox_fp):
        # 从 sox_sina.txt 旧格式转
        old = os.path.join(DATA, "sox_sina.txt")
        if os.path.exists(old):
            raw = open(old, encoding="utf-8", errors="ignore").read()
            try:
                arr = json.loads(raw[raw.find("["):raw.rfind("]") + 1])
                # 去重（同一日期取最后一次出现）
                seen = {}
                for r in arr:
                    seen[r["d"]] = float(r["c"])
                dates = list(seen.keys())
                closes = list(seen.values())
                payload = {"name": "费城半导体SOX", "code": secid, "src": "sina-archive",
                           "dates": dates, "closes": closes}
                json.dump(payload, open(sox_fp, "w", encoding="utf-8"), ensure_ascii=False)
                hist_ok = True
                print(f"  从sina archive恢复OK: {len(arr)} bars (去重后 {len(dates)} bars)")
            except Exception as e:
                print(f"  sina archive也失败: {e}")
    else:
        # sox_fp 已存在，但里面可能有重复date的脏数据，先清理一次
        payload = json.load(open(sox_fp, encoding="utf-8"))
        seen = {}
        for d, c in zip(payload["dates"], payload["closes"]):
            seen[d] = c
        dates = list(seen.keys())
        closes = list(seen.values())
        if len(seen) != len(payload["dates"]):
            payload["dates"] = dates
            payload["closes"] = closes
            json.dump(payload, open(sox_fp, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  清理 sox_em.json 重复bar: {len(payload['dates'])}→{len(seen)}")
# 用新浪实时覆盖最后bar
sina = fetch_sina(["gb_$sox"])
if sina.get("gb_$sox"):
    s = sina["gb_$sox"]
    # 关键：用 sina 返回的 date 字段解析"上次美股交易日"，不用 datetime.now()
    # sina['date'] 形如 '2026-08-08 09:47:52'（北京时间）
    sox_doc_date = parse_us_market_date(s.get("date", ""))
    if not sox_doc_date:
        sox_doc_date = datetime.now().strftime("%Y-%m-%d")
    payload = json.load(open(sox_fp, encoding="utf-8"))
    if payload["closes"]:
        # 1) 删除与 sina 解析出的美股交易日重复的旧bar（避免 8/7 重复）
        new = []
        seen_dates = set()
        for i in range(len(payload["dates"])):
            d = payload["dates"][i]
            if d == sox_doc_date:
                if d not in seen_dates:
                    new.append((d, payload["closes"][i]))
                    seen_dates.add(d)
            else:
                new.append((d, payload["closes"][i]))
        # 2) 追加/更新 sina 数据
        if sox_doc_date in seen_dates:
            # 替换最后一条
            new[-1] = (sox_doc_date, s["price"])
        else:
            new.append((sox_doc_date, s["price"]))
        payload["dates"] = [x[0] for x in new]
        payload["closes"] = [x[1] for x in new]
    json.dump(payload, open(sox_fp, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  新浪覆盖: SOX {s['price']:.2f} ({s['pct']:+.2f}%) @ {sox_doc_date}")
    results.append({"name": "SOX", "price": s["price"], "pct": s["pct"], "date": sox_doc_date})
elif not hist_ok:
    print(f"  全部失败，保留旧值")


# ========== 2) NDX 纳斯达克100 ==========
print(f"\n[2] NDX100")
# NDX 历史来源 us.NDX (旧 push2his，已停返 null) → 保留 ndx100_full.json
# 或主动试 push2his 100.NDX 看看是否恢复
ndx_fp = os.path.join(DATA, "ndx100_full.json")
hist_us_ndx = push2his("us.NDX", beg="20250101")
hist_100_ndx = push2his("100.NDX", beg="20250101")
# 优先 us.NDX (true NDX100 secid)
if hist_us_ndx:
    payload = {"code": 0, "msg": "", "data": {"us.NDX": {
        "day": [r.split(",") + [{}] * (11 - len(r.split(","))) for r in hist_us_ndx],
        "qfqday": [r.split(",") + [{}] * (11 - len(r.split(","))) for r in hist_us_ndx]
    }}}
    # day 元素 ["日期","开","收","高","低","成交量",{}, ...]
    def _row(r):
        ks = r.split(",")
        while len(ks) < 11:
            ks.append("0" if ks.count(",") >= 5 else "{}")
        return [ks[0], ks[1], ks[2], ks[3], ks[4], ks[5]] + ["0"] * 5
    payload["data"]["us.NDX"]["day"] = [_row(r) for r in hist_us_ndx]
    payload["data"]["us.NDX"]["qfqday"] = [_row(r) for r in hist_us_ndx]
    json.dump(payload, open(ndx_fp, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  us.NDX 历史OK: {len(hist_us_ndx)} bars, last={hist_us_ndx[-1].split(',')[0]}={hist_us_ndx[-1].split(',')[2]}")
else:
    print(f"  us.NDX 历史拉取失败，保留 {os.path.exists(ndx_fp)} 文件")
# 用新浪实时覆盖最后bar
sina = fetch_sina(["gb_$ndx"])
if sina.get("gb_$ndx"):
    s = sina["gb_$ndx"]
    # 关键：用 sina date 字段解析美股交易日，不用 datetime.now()
    ndx_close_date = parse_us_market_date(s.get("date", ""))
    if not ndx_close_date:
        ndx_close_date = datetime.now().strftime("%Y-%m-%d")
    payload = json.load(open(ndx_fp, encoding="utf-8"))
    day = payload.get("data", {}).get("us.NDX", {}).get("day") or payload.get("data", {}).get("us.NDX", {}).get("qfqday")
    if day is None:
        # file 缺失或结构异常，跳过
        print(f"  ndx100_full.json 结构异常，跳过写入")
    else:
        # 找到最后一个 <= ndx_close_date 的 bar，覆盖其收盘
        written = False
        for i in range(len(day) - 1, -1, -1):
            if day[i][0] <= ndx_close_date:
                day[i][2] = "%.2f" % s["price"]  # 收
                day[i][3] = "%.2f" % s["high"]  # 高
                day[i][4] = "%.2f" % s["low"]   # 低
                day[i][1] = "%.2f" % s["open"] # 开
                written = True
                print(f"  新浪NDX覆盖最近bar: {day[i][0]} {s['price']:.2f}")
                break
        if not written:
            # 添加新bar
            day.append([ndx_close_date, "%.2f" % s["open"], "%.2f" % s["price"],
                        "%.2f" % s["high"], "%.2f" % s["low"], "0", "{}", "0.00", "0", "0", "0"])
            print(f"  新浪NDX追加新bar: {ndx_close_date} {s['price']:.2f}")
        if "qfqday" in payload.get("data", {}).get("us.NDX", {}):
            qf = payload["data"]["us.NDX"]["qfqday"]
            qf[:len(day)] = day
        json.dump(payload, open(ndx_fp, "w", encoding="utf-8"), ensure_ascii=False)
        results.append({"name": "NDX", "price": s["price"], "pct": s["pct"], "date": ndx_close_date})


# ========== 3) DXY 美元指数 (DINIW) ==========
print(f"\n[3] DXY")
dxy_fp = os.path.join(DATA, "dxy_em.json")
hist_ok = False
kl = push2his("100.UDI", beg="20250101")
if kl:
    payload = {"name": "美元指数DXY", "code": "100.UDI", "src": "东方财富-push2his",
               "dates": [k.split(",")[0] for k in kl],
               "closes": [float(k.split(",")[2]) for k in kl]}
    json.dump(payload, open(dxy_fp, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  100.UDI历史OK: {len(kl)} bars, last={kl[-1].split(',')[0]}={kl[-1].split(',')[2]}")
    hist_ok = True
sina = fetch_sina(["DINIW"])
if sina.get("DINIW"):
    s = sina["DINIW"]
    dxy_doc_date = s["date"]
    payload = json.load(open(dxy_fp, encoding="utf-8"))
    if payload["dates"] and payload["dates"][-1] == dxy_doc_date:
        payload["closes"][-1] = s["price"]
    else:
        payload["dates"].append(dxy_doc_date)
        payload["closes"].append(s["price"])
    json.dump(payload, open(dxy_fp, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  新浪DINIW覆盖: DXY {s['price']:.2f} @ {dxy_doc_date}")
    results.append({"name": "DXY", "price": s["price"], "pct": 0, "date": dxy_doc_date})


# ========== 4) WTI 原油 (102.CL00Y + sina hf_CL) ==========
print(f"\n[4] WTI")
wti_fp = os.path.join(DATA, "wti.json")
hist_ok = False
kl = push2his("102.CL00Y", beg="20250101")
if kl:
    payload = {"name": "WTI原油", "code": "102.CL00Y", "src": "东方财富-push2his",
               "dates": [k.split(",")[0] for k in kl],
               "closes": [float(k.split(",")[2]) for k in kl]}
    json.dump(payload, open(wti_fp, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  102.CL00Y历史OK: {len(kl)} bars, last={kl[-1].split(',')[0]}={kl[-1].split(',')[2]}")
    hist_ok = True
sina = fetch_sina(["hf_CL"])
if sina.get("hf_CL"):
    s = sina["hf_CL"]
    # hf_CL 没有 date 字段，用今天
    wti_doc_date = datetime.now().strftime("%Y-%m-%d")
    payload = json.load(open(wti_fp, encoding="utf-8"))
    if payload["dates"] and payload["dates"][-1] == wti_doc_date:
        payload["closes"][-1] = s["price"]
    else:
        payload["dates"].append(wti_doc_date)
        payload["closes"].append(s["price"])
    json.dump(payload, open(wti_fp, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  新浪hf_CL覆盖: WTI {s['price']:.2f} @ {wti_doc_date}")
    results.append({"name": "WTI", "price": s["price"], "pct": s["pct"] or 0, "date": wti_doc_date})


# ========== 5) US10Y 美债 (171.US10Y) ==========
print(f"\n[5] US10Y")
u10_fp = os.path.join(DATA, "us10y_em.json")
kl = push2his("171.US10Y", beg="20250101")
if kl:
    payload = {"code": 0, "msg": "", "data": {"klines": kl}}
    json.dump(payload, open(u10_fp, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  171.US10Y历史OK: {len(kl)} bars, last={kl[-1].split(',')[0]}={kl[-1].split(',')[2]}")
    # 用 push2 实时快照覆盖最后bar
    snap_text = safe_get("https://push2.eastmoney.com/api/qt/stock/get?secid=171.US10Y&fields=f43,f60", headers=EA, timeout=10)
    if snap_text:
        try:
            d = json.loads(snap_text)
            data = d.get("data", {})
            f43 = _try_float(data.get("f43"))
            # v1.1 修复：f43 异常值过滤（典���单位误返回为 bps=基点的污染数据）
            # 10Y国债收益率正常范围 0.5%~10%；超过 20 或小于 0.1 视为异常
            if f43 and 0.1 < f43 < 20:
                payload["data"]["klines"][-1] = f"{kl[-1].split(',')[0]},{kl[-1].split(',')[1]},{f43:.4f},{kl[-1].split(',')[3]},{kl[-1].split(',')[4]},{kl[-1].split(',')[5]}"
                json.dump(payload, open(u10_fp, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  push2快照覆盖US10Y={f43:.4f}")
            elif f43:
                print(f"  push2快照US10Y={f43} 超出正常范围[0.1,20]，丢弃（疑似单位污染bps=基点）")
        except Exception:
            pass


print("\n=== 实时覆盖结果汇总 ===")
for r in results:
    print(f"  {r['name']}: {r['price']:.2f} {r['pct']:+.2f}% @ {r['date']}")
