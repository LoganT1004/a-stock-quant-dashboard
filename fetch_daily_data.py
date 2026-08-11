# -*- coding: utf-8 -*-
"""每日收盘后同步数据（每个交易日收盘后 15:30 由 quick_refresh.py 自动调用）：
1) 16家赛道公司涨跌幅+主力净流入（新浪 hq.sinajs.cn 替代东财 ulist.np，本机不被封）
2) DR007（同业拆借利率，全国银行间/新华财经）
3) ETF 净申购（追加到 etf_flow_history.json）
4) 两融余额（重试东财 datacenter-web RPTA_RZRQ_LSHJ）

设计原则：
- 所有外部抓取失败都 graceful fallback，不报错
- 公司实时数据用 sina secid（最稳）；ulist.np 数据用 sina 数据二次校准
"""
import os, sys
import json, os, re, time, urllib.request, ssl
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      "Referer": "https://finance.sina.com.cn/"}
EA = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/",
      "Referer2": "https://quote.eastmoney.com/"}

# 16 家赛道公司 secid 映射（sina）
STOCKS = {
    "北方华创": "sz002371",
    "中微公司": "sh688012",
    "拓荆科技": "sh688072",
    "华海清科": "sh688120",
    "长川科技": "sz300604",
    "中科飞测": "sh688361",
    "长鑫科技": "sh688825",
    "兆易创新": "sh603986",
    "佰维存储": "sh688525",
    "普冉股份": "sh688766",
    "德明利":   "sz001309",
    "江波龙":   "sz301308",
    "中际旭创": "sz300308",
    "新易盛":   "sz300502",
    "天孚通信": "sz300394",
    "光迅科技": "sz002281",
}


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


def fetch_sina(codes):
    """批量抓新浪 secid"""
    code_str = ",".join(codes)
    url = "https://hq.sinajs.cn/list=" + code_str
    text = safe_get(url, timeout=10, retries=3)
    if not text:
        return {}
    out = {}
    for line in text.splitlines():
        m = re.search(r'hq_str_(\w+)="(.*)"', line.strip())
        if not m or not m.group(2).strip():
            continue
        code, raw = m.group(1), m.group(2)
        parts = raw.split(",")
        # 沪深指数/股票字段顺序：名称,今开,昨收,最新,最高,最低,买一,...
        # A股字段：parts[0]=名称 parts[1]=今开 parts[2]=昨收 parts[3]=最新 parts[4]=最高 parts[5]=最低
        # parts[29]=日期 parts[30]=时间
        try:
            prev = float(parts[2]) if parts[2] and parts[2] != "--" else None
            cur = float(parts[3]) if parts[3] and parts[3] != "--" else None
            pct = (cur / prev - 1) * 100 if (cur and prev) else None
            out[code] = {
                "name": parts[0], "price": cur, "prev": prev, "pct": pct,
                "open": float(parts[1]) if parts[1] and parts[1] != "--" else None,
                "high": float(parts[4]) if parts[4] and parts[4] != "--" else None,
                "low":  float(parts[5]) if parts[5] and parts[5] != "--" else None,
                "date": parts[29] if len(parts) > 29 else "",
                "time": parts[30] if len(parts) > 30 else "",
            }
        except Exception:
            continue
    return out


def fetch_dr007():
    """DR007 (银行间7天回购利率)。
    数据源：全国银行间同业拆借中心 chinamoney.com.cn (公开 API，本机可用)
    """
    fp = os.path.join(DATA, "dr007.json")
    today = datetime.now().strftime("%Y-%m-%d")
    # 抓过去 30 天的 DR007
    from datetime import timedelta
    start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    end = today
    url = f"https://www.chinamoney.com.cn/ags/ms/cm-u-bk-shibor/ShiborHis?lang=cn&bondType=DR007&startDate={start}&endDate={end}"
    text = safe_get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.chinamoney.com.cn/"},
                    timeout=10, retries=3)
    if not text:
        if os.path.exists(fp):
            return json.load(open(fp, encoding="utf-8"))
        return None
    try:
        j = json.loads(text)
        records = j.get("records", [])
        if not records:
            return None
        # 找最新一个交易日
        latest = records[0]  # 按 showDateCN 倒序（最新在前）
        value = float(latest["1W"])
        # 追加/更新 history
        hist_fp = os.path.join(DATA, "dr007_history.json")
        if os.path.exists(hist_fp):
            hist = json.load(open(hist_fp, encoding="utf-8"))
        else:
            hist = {"name": "DR007", "unit": "%", "src": "全国银行间同业拆借中心",
                    "dates": [], "values": []}
        v_map = dict(zip(hist["dates"], hist["values"]))
        for r in records:
            v_map[r["showDateCN"]] = float(r["1W"])
        dates = sorted(v_map)
        hist["dates"] = dates
        hist["values"] = [v_map[d] for d in dates]
        json.dump(hist, open(hist_fp, "w", encoding="utf-8"), ensure_ascii=False)
        # 写当前 dr007.json
        payload = {"value": value, "date": latest["showDateCN"],
                   "src": "全国银行间同业拆借中心/新华财经",
                   "url": "https://www.chinamoney.com.cn/"}
        json.dump(payload, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  DR007: {value:.4f}% @ {latest['showDateCN']} (共{len(records)}条)")
        return value
    except Exception as e:
        print(f"  DR007 解析失败: {e}")
        if os.path.exists(fp):
            return json.load(open(fp, encoding="utf-8"))
        return None


def fetch_margin():
    """两融余额（东财 datacenter-web RPTA_RZRQ_LSHJ）。
    本机 urllib 通常被封；优先读 margin_result.json（自动化 WebFetch 写入），fallback 本地抓
    """
    fp = os.path.join(DATA, "margin_history.json")
    result_fp = os.path.join(DATA, "margin_result.json")
    today = datetime.now().strftime("%Y-%m-%d")
    # 1) 优先读 WebFetch 抓的 margin_result.json（自动化通道）
    if os.path.exists(result_fp):
        try:
            r = json.load(open(result_fp, encoding="utf-8"))
            if r.get("date"):
                v_map = {}
                if os.path.exists(fp):
                    v_map = dict(zip(json.load(open(fp, encoding="utf-8"))["dates"],
                                     json.load(open(fp, encoding="utf-8"))["values"]))
                for row in r.get("records", []):
                    v_map[row["date"]] = row["value"]
                dates = sorted(v_map)
                payload = {"unit": "亿元", "src": "东方财富-融资融券历史（RPTA_RZRQ_LSHJ）",
                           "url": "https://data.eastmoney.com/rzrq/total.html",
                           "dates": dates, "values": [v_map[d] for d in dates]}
                json.dump(payload, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
                last = payload["dates"][-1]
                print(f"  margin_result.json: {len(r.get('records', []))}条最新={last}={payload['values'][-1]}亿")
                return last
        except Exception as e:
            print(f"  margin_result.json 解析失败: {e}")

    # 2) fallback 本机 urllib 抓
    if not os.path.exists(fp):
        return None
    v_map = {}
    try:
        d = json.load(open(fp, encoding="utf-8"))
        v_map = dict(zip(d["dates"], d["values"]))
    except Exception:
        pass
    added = 0
    for pg in range(1, 5):
        try:
            text = safe_get(f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_RZRQ_LSHJ"
                           f"&columns=ALL&sortColumns=dim_date&sortTypes=-1&pageSize=100&pageNumber={pg}"
                           f"&source=WEB&client=WEB",
                           headers={"User-Agent": "Mozilla/5.0",
                                    "Referer": "https://data.eastmoney.com/"}, timeout=20)
            if not text:
                continue
            j = json.loads(text)
            rows = (j.get("result") or {}).get("data") or []
            if not rows:
                break
            for r in rows:
                if r.get("RZYE"):
                    v_map[r["DIM_DATE"][:10]] = round(r["RZYE"] / 1e8, 0)
            added += len(rows)
            time.sleep(0.4)
        except Exception:
            continue
    if added == 0:
        print(f"  两融: 拉取0条，可能接口被封")
        return None
    dates = sorted(v_map)
    payload = {"unit": "亿元", "src": "东方财富-融资融券历史（RPTA_RZRQ_LSHJ）",
               "url": "https://data.eastmoney.com/rzrq/total.html",
               "dates": dates, "values": [v_map[x] for x in dates]}
    json.dump(payload, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
    last = payload["dates"][-1]
    print(f"  两融: 最新{last}={payload['values'][-1]}亿 (共{added}条)")
    return last


def fetch_etf_flow_today():
    """ETF 净申购（追加到 history）。
    数据源优先级：
    1) etf_flow_result.json（自动化 WebFetch/WebSearch 写入，含当日 net3d/7d/30d）
    2) etf_flow_history.json 已有今日数据
    3) 兜底：返回最近一天的数据（不更新）
    """
    fp = os.path.join(DATA, "etf_flow_history.json")
    result_fp = os.path.join(DATA, "etf_flow_result.json")
    today = datetime.now().strftime("%Y-%m-%d")
    # 1) 优先读 etf_flow_result.json
    if os.path.exists(result_fp):
        try:
            r = json.load(open(result_fp, encoding="utf-8"))
            if r.get("date") == today and r.get("net3d") is not None:
                hist = json.load(open(fp, encoding="utf-8")) if os.path.exists(fp) else {
                    "dates": [], "net3d": [], "net7d": [], "net30d": [],
                    "src": "东方财富Choice权益ETF日报", "note": ""}
                v3 = dict(zip(hist.get("dates", []), hist.get("net3d", [])))
                v7 = dict(zip(hist.get("dates", []), hist.get("net7d", [])))
                v30 = dict(zip(hist.get("dates", []), hist.get("net30d", [])))
                v3[today] = r["net3d"]
                if r.get("net7d") is not None:
                    v7[today] = r["net7d"]
                if r.get("net30d") is not None:
                    v30[today] = r["net30d"]
                dates = sorted(set(v3) | set(v7) | set(v30))
                hist["dates"] = dates
                hist["net3d"] = [v3.get(d) for d in dates]
                hist["net7d"] = [v7.get(d) for d in dates]
                hist["net30d"] = [v30.get(d) for d in dates]
                hist["src"] = r.get("src", hist.get("src", ""))
                if r.get("note"):
                    hist["note"] = r["note"]
                json.dump(hist, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                # 同步 etf_flow.json
                payload = {
                    "net3d": r["net3d"], "date": today,
                    "src": r.get("src", "东方财富Choice"),
                    "note": r.get("note", ""),
                    "weekly_new_fund": None,
                }
                if r.get("net7d") is not None:
                    payload["net7d"] = r["net7d"]
                if r.get("net30d") is not None:
                    payload["net30d"] = r["net30d"]
                json.dump(payload, open(os.path.join(DATA, "etf_flow.json"), "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)
                print(f"  ETF净申购: {r['net3d']:+.2f}亿 @ {today} (from etf_flow_result.json)")
                return r["net3d"]
        except Exception as e:
            print(f"  etf_flow_result.json 解析失败: {e}")

    # 2) history 已有今日数据
    if not os.path.exists(fp):
        return None
    try:
        d = json.load(open(fp, encoding="utf-8"))
        if d.get("dates") and d["dates"][-1] == today:
            print(f"  ETF净申购: 已是今日数据 ({d['net3d'][-1]}亿)")
            return d["net3d"][-1]
        # 3) 兜底：返回最近一天
        print(f"  ETF净申购: 今日数据缺失，保留旧值 ({d.get('net3d', [None])[-1]}亿 @ {d.get('dates', ['?'])[-1]})")
        return d.get("net3d", [None])[-1] if d.get("net3d") else None
    except Exception:
        return None


def main():
    print("=" * 60)
    print(f"fetch_daily_data  起始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    today = datetime.now().strftime("%Y-%m-%d")

    # ========== 1) 16家公司涨跌幅+主力净流入 ==========
    print("\n[1] 公司BI实时数据（新浪 hq.sinajs.cn）")
    secids = list(STOCKS.values())
    batches = [secids[i:i + 16] for i in range(0, len(secids), 16)]
    sina_all = {}
    for batch in batches:
        sina_all.update(fetch_sina(batch))
        time.sleep(0.3)

    # 主力净流入优先读已有的 ulistnp_result.json（自动化 WebFetch 抓的）
    flows_em_path = os.path.join(DATA, "ulistnp_result.json")
    flows_em = {}
    if os.path.exists(flows_em_path):
        try:
            r = json.load(open(flows_em_path, encoding="utf-8"))
            # 接受 T-0 / T-1 / T-2（盘后接口可能仍返回上一交易日资金流）
            _rdate = r.get("date", "")
            if _rdate and abs((datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(_rdate, "%Y-%m-%d")).days) <= 2:
                flows_em = r.get("flows", {})
                print(f"  读取 ulistnp_result.json: {len(flows_em)} 家公司主力净流入（数据日 {_rdate}）")
        except Exception:
            pass
    if not flows_em:
        # 备用：本机 urllib 拉一次 ulist.np（多数情况被封）
        em_secids = []
        for code in STOCKS.values():
            mkt = "1" if code.startswith("sh") else "0"
            em_secids.append(f"{mkt}.{code[2:]}")
        em_text = safe_get(f"https://push2.eastmoney.com/api/qt/ulist.np/get?secids={','.join(em_secids)}"
                           f"&fields=f3,f12,f14,f62,f66,f72,f184&invt=2&fltt=2",
                           headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
                           timeout=10, retries=2)
        if em_text:
            try:
                j = json.loads(em_text)
                for it in j.get("data", {}).get("diff", []):
                    name = it.get("f14")
                    flows_em[name] = {
                        "main": round((it.get("f62") or 0) / 1e8, 2),
                        "super": round((it.get("f66") or 0) / 1e8, 2),
                        "big": round((it.get("f72") or 0) / 1e8, 2),
                        "pct_em": it.get("f3"),
                    }
            except Exception:
                pass
        if not flows_em:
            # 生成 todo 文件，提示自动化任务用 WebFetch 抓
            todo_path = os.path.join(DATA, ".todo_ulistnp.json")
            json.dump({"secids": em_secids, "fields": "f3,f12,f14,f62,f66,f72,f184",
                       "date": today, "created": datetime.now().isoformat()},
                      open(todo_path, "w", encoding="utf-8"))
            print(f"  ⚠️ ulist.np 本机抓取失败，已写 .todo_ulistnp.json，需 WebFetch 补")

    # 合并：sina 数据（涨跌幅/价格/开高低）+ ulistnp 数据（主力净流入）
    flows_out = {}
    for name, secid in STOCKS.items():
        s = sina_all.get(secid)
        em = flows_em.get(name)
        if not s and not em:
            continue
        flows_out[name] = {
            "main": em["main"] if em else 0,
            "super": em["super"] if em else 0,
            "big": em["big"] if em else 0,
            "pct": s["pct"] if s and s["pct"] is not None else (em.get("pct_em") if em else None),
            "close": s["price"] if s else None,
            "prev": s["prev"] if s else None,
            "open": s["open"] if s else None,
            "high": s["high"] if s else None,
            "low": s["low"] if s else None,
            "date": today,
            "time": s["time"] if s else "",
            "src": "新浪hq.sinajs+东财ulist.np",
        }
    if flows_out:
        json.dump(flows_out, open(os.path.join(DATA, "stock_flows.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"  已写入 stock_flows.json: {len(flows_out)} 家公司")
        for n, v in list(flows_out.items())[:6]:
            print(f"    {n}: 涨跌幅{v['pct']:+.2f}%, 主力{v['main']:+.2f}亿, 收{v['close']}, 昨收{v['prev']}")
    else:
        print(f"  ⚠️ sina+ulist 都失败，保留旧 stock_flows.json")

    # ========== 2) DR007 ==========
    print("\n[2] DR007 (银行间7天回购利率)")
    dr = fetch_dr007()
    if dr:
        print(f"  当前 DR007 = {dr}%")
    else:
        print(f"  DR007 暂无数据（需要 WebSearch 自动化补充）")

    # ========== 3) 两融余额 ==========
    print("\n[3] 两融余额（东财 datacenter-web RPTA_RZRQ_LSHJ）")
    margin = fetch_margin()
    if not margin:
        print(f"  ⚠️ 两融未更新（东财 datacenter-web 临时被封）")

    # ========== 4) ETF 净申购 ==========
    print("\n[4] ETF 净申购（追加到 history）")
    etf = fetch_etf_flow_today()
    if etf is not None:
        print(f"  最近 ETF 净申购: {etf}亿")
    else:
        # 生成 todo 文件提示自动化任务需要补
        todo_path = os.path.join(DATA, ".todo_etf_flow.json")
        if not os.path.exists(todo_path):
            today = datetime.now().strftime("%Y-%m-%d")
            json.dump({"date": today, "needed": ["net3d", "net7d", "net30d"],
                       "created": datetime.now().isoformat(),
                       "src_hint": "东方财富Choice权益ETF日报/财中ETF日报"},
                      open(todo_path, "w", encoding="utf-8"))
            print(f"  ⚠️ ETF数据缺失，已写 .todo_etf_flow.json，需WebSearch补")

    # ========== 5) 同步 stocks_quote_utf8.txt ==========
    # 这是腾讯财经 qt.gtimg.cn 格式，gen_dashboard_data.py 用它解析"今日涨跌幅"
    # 我们用 sina 数据转成同样格式写出，避免依赖 WebFetch 抓 qt.gtimg.cn（被封）
    print("\n[5] 同步 stocks_quote_utf8.txt (腾讯格式转换)")
    if flows_out:
        # 解析原文件，提取每只股票的原始字段，再覆盖今日数据
        out_lines = []
        for name, secid in STOCKS.items():
            # 找到原文件里对应 secid 的行（v_sh002371 等）
            em_secid = ("sh" if secid.startswith("sh") else "sz") + secid[2:]
            em_id = em_secid.lower()
            # 构造腾讯格式的"v_"行
            f = flows_out.get(name, {})
            if not f:
                continue
            # 格式：v_id="名称~代码~价格~...~涨跌幅~...~时间"
            # 关键字段：p[1]=名称, p[2]=代码, p[3]=收盘价, p[32]=涨跌幅, p[30]=时间
            # 我们填充最小可用的字段，其它用空
            code = secid[2:]  # 002371
            price = f.get("close", 0)
            pct = f.get("pct", 0)
            time_str = datetime.now().strftime("%Y%m%d%H%M%S")
            # 构造与原文件结构相同的字符串
            # 关键字段（按 qt.gtimg.cn 标准格式）：
            # p[0]=1(市场) p[1]=名称 p[2]=代码 p[3]=收盘价
            # p[4..29]=填充 (26个0)
            # **p[30]=时间戳** **p[31]=涨跌额** **p[32]=涨跌幅%**
            # p[33..]=填充
            parts = ["1", name, code, str(price)]
            parts += ["0"] * 26  # 填充 p[4] 到 p[29]（26个）
            parts.append(time_str)  # p[30]=时间戳
            parts.append("%.2f" % (f["close"] - f["prev"]) if f.get("prev") else "0")  # p[31]=涨跌额
            parts.append("%.2f" % pct)  # p[32]=涨跌幅%
            parts += ["0"] * 4  # p[33..36]
            value = "~".join(parts)
            out_lines.append(f'v_{em_id}="{value}";')
        if out_lines:
            with open(os.path.join(DATA, "stocks_quote_utf8.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(out_lines))
            # 同步复制为非 utf8 版本（占位兼容）
            with open(os.path.join(DATA, "stocks_quote.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(out_lines))
            print(f"  已写入 {len(out_lines)} 行")
    else:
        print(f"  跳过（无 flows 数据）")

    print("\n" + "=" * 60)
    print("fetch_daily_data 完成")
    print("=" * 60)


if __name__ == "__main__":
    main()