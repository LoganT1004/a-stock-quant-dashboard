# -*- coding: utf-8 -*-
"""
统一 WebFetch 兜底数据合并器（quick_refresh.py 第 4.6 步后自动调用）

本机 push2 / push2his 被封禁时，由 WorkBuddy 自动化任务（或人工会话）通过 WebFetch
把数据写入 `data/.todo_*.json` 对应的 *result.json 文件，本脚本负责：

1. 读取 .result.json 中的最新数据
2. 合并到对应的最终数据文件（如 bk1326_raw.json、limit_count.json）
3. 同时删除 .todo_*.json 占位文件
4. 不存在时 graceful fallback，不报错

支持的 result.json：
- ulistnp_result.json  -> stock_flows.json（公司主力净流入）
- margin_result.json   -> margin_history.json（两融余额）
- etf_flow_result.json -> etf_flow_history.json + etf_flow.json（ETF 净申购）
- bk_raw_result.json   -> bk{1326,1137,1136,1106}_raw.json（BK板块日线）
- cds_result.json      -> cds_history.json + payload_hand.json CDS 卡片
- limit_result.json    -> limit_count.json（涨跌停家数）
- news_result.json     -> news.json（消息面新增条目）
"""
import json, os, time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")


def _load(path):
    fp = os.path.join(DATA, path)
    if not os.path.exists(fp):
        return None
    try:
        return json.load(open(fp, encoding="utf-8"))
    except Exception as e:
        print(f"  [{path}] 解析失败: {e}")
        return None


def _dump(path, obj):
    fp = os.path.join(DATA, path)
    json.dump(obj, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _clear_todo(name):
    """删除 .todo_{name}.json 占位文件"""
    fp = os.path.join(DATA, f".todo_{name}.json")
    if os.path.exists(fp):
        try:
            os.remove(fp)
            print(f"  ✓ 已清理 .todo_{name}.json")
        except Exception:
            pass


def merge_bk_raw():
    """合并 BK 板块 8/14 数据 → bk1326/1137/1136/1106_raw.json
    result.json 结构：{"bk1326": "2026-08-14,open,close,high,low,vol", ...}
    """
    r = _load("bk_raw_result.json")
    if not r or not isinstance(r, dict):
        return False
    count = 0
    for fn, last_bar in r.items():
        fp = os.path.join(DATA, fn)
        if not os.path.exists(fp):
            continue
        try:
            d = json.load(open(fp, encoding="utf-8"))
            ks = d.get("klines", [])
            new_ks = [row for row in ks if row.split(",")[0] != "2026-08-14"]
            new_ks.append(last_bar)
            d["klines"] = new_ks
            d["src"] = (d.get("src", "") + "+web-fetch-result").strip("+")
            json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  ✓ {fn}: 已合并 8/14 ({last_bar.split(',')[2]} close)")
            count += 1
        except Exception as e:
            print(f"  ✗ {fn}: 合并失败 {e}")
    if count:
        _clear_todo("bk")
    return count > 0


def merge_cds():
    """合并 CDS 8/13+ 数据 → cds_history.json + payload_hand.json
    关键安全检查：result.date 必须晚于现有 history 最新日期，否则跳过。
    """
    r = _load("cds_result.json")
    if not r or not isinstance(r, dict):
        return False
    # result 格式：{"date": "2026-08-13", "value": 41.24, "src": "LSEG/LCH CDX.NA.IG 5Y"}
    fp = os.path.join(DATA, "cds_history.json")
    if not os.path.exists(fp):
        return False
    try:
        d = json.load(open(fp, encoding="utf-8"))
        date = r.get("date")
        val = r.get("value")
        if not date or val is None:
            return False
        latest_existing = max(d["dates"]) if d.get("dates") else None
        if latest_existing and date <= latest_existing:
            print(f"  ↷ 跳过 cds: result.date={date} 不晚于 history 最新={latest_existing}")
            _clear_todo("cds")
            return False
        # 去重 + 追加
        paired = sorted([(dt, c) for dt, c in zip(d["dates"], d["closes"])
                         if dt != date] + [(date, val)])
        d["dates"] = [x[0] for x in paired]
        d["closes"] = [x[1] for x in paired]
        d["week52"] = [min(d["closes"]), max(d["closes"])]
        d["src"] = (d.get("src", "") + f"+web-fetch-{date}").strip("+")
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
        # 同步 payload_hand.json CDS 卡片
        ph_fp = os.path.join(BASE, "payload_hand.json")
        if os.path.exists(ph_fp):
            h = json.load(open(ph_fp, encoding="utf-8"))
            n = len(d["closes"])
            last = d["closes"][-1]
            prev = d["closes"][-2]
            chg = (last / prev - 1) * 100 if prev else 0
            for o in h.get("overseas", []):
                if o.get("name") == "美国10Y CDS":
                    o["val"] = f"{last:.2f}bp"
                    o["chg"] = f"{chg:+.2f}%"
                    o["date"] = date[5:]
                    o["src"] = r.get("src", "英为财情")
                    wk_min, wk_max = d["week52"]
                    o["note"] = (f"最新{last:.2f}bp（{chg:+.2f}%），"
                                 f"52周区间{wk_min:.2f}-{wk_max:.2f}bp——"
                                 f"信用环境{'宽松' if last < 45 else '边际收紧'}")
            json.dump(h, open(ph_fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  ✓ cds_history.json + payload_hand.json: {date}={val:.2f}bp")
        _clear_todo("cds")
        return True
    except Exception as e:
        print(f"  ✗ cds 合并失败: {e}")
        return False


def merge_etf_flow():
    """合并 ETF 净申购 8/14 数据 → etf_flow_history.json + etf_flow.json
    result 格式：{"date": "2026-08-14", "net3d": -150.0, "net7d": ..., "net30d": ..., "src": "Choice"}

    关键安全检查：result.json 中 date 必须晚于 history 中最新日期，否则跳过（防止旧数据覆盖）。
    """
    r = _load("etf_flow_result.json")
    if not r or not isinstance(r, dict):
        return False
    date = r.get("date")
    if not date:
        return False
    fp = os.path.join(DATA, "etf_flow_history.json")
    try:
        hist = json.load(open(fp, encoding="utf-8"))
        latest_existing = max(hist.get("dates", [])) if hist.get("dates") else None
        if latest_existing and date <= latest_existing:
            print(f"  ↷ 跳过 etf_flow: result.date={date} 不晚于 history 最新={latest_existing}")
            # 清理 todo 但不合并
            _clear_todo("etf_flow")
            return False
        v3 = dict(zip(hist.get("dates", []), hist.get("net3d", [])))
        v7 = dict(zip(hist.get("dates", []), hist.get("net7d", [])))
        v30 = dict(zip(hist.get("dates", []), hist.get("net30d", [])))
        if r.get("net3d") is not None:
            v3[date] = r["net3d"]
        if r.get("net7d") is not None:
            v7[date] = r["net7d"]
        if r.get("net30d") is not None:
            v30[date] = r["net30d"]
        dates = sorted(v3)
        hist["dates"] = dates
        hist["net3d"] = [v3.get(d) for d in dates]
        hist["net7d"] = [v7.get(d) for d in dates]
        hist["net30d"] = [v30.get(d) for d in dates]
        hist["src"] = r.get("src", hist.get("src", "东方财富Choice"))
        json.dump(hist, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        # 同步 etf_flow.json
        last_net3d = v3.get(date)
        payload = {
            "net3d": last_net3d, "date": date,
            "src": hist["src"],
            "note": f"{date} 全市场股票型ETF净申购 {last_net3d:+.2f} 亿",
            "weekly_new_fund": None,
        }
        if r.get("net7d") is not None:
            payload["net7d"] = r["net7d"]
        if r.get("net30d") is not None:
            payload["net30d"] = r["net30d"]
        json.dump(payload, open(os.path.join(DATA, "etf_flow.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"  ✓ etf_flow_history.json + etf_flow.json: {date} net3d={last_net3d}")
        _clear_todo("etf_flow")
        return True
    except Exception as e:
        print(f"  ✗ etf_flow 合并失败: {e}")
        return False


def merge_limit():
    """合并涨跌停家数 8/14 数据 → limit_count.json
    关键安全检查：result.date 必须 ≥ 现有最新日期。
    """
    r = _load("limit_result.json")
    if not r or not isinstance(r, dict):
        return False
    date = r.get("date")
    if not date:
        return False
    fp = os.path.join(DATA, "limit_count.json")
    try:
        d = json.load(open(fp, encoding="utf-8")) if os.path.exists(fp) else {}
        existing_date = d.get("date", "")
        if existing_date and date < existing_date:
            print(f"  ↷ 跳过 limit: result.date={date} 早于现有={existing_date}")
            _clear_todo("limit")
            return False
        d["date"] = date
        if r.get("limit_up") is not None:
            d["limit_up"] = r["limit_up"]
            d["natural_limit_up"] = r["limit_up"]
        if r.get("limit_down") is not None:
            d["limit_down"] = r["limit_down"]
            d["natural_limit_down"] = r["limit_down"]
        d["ts"] = time.time()
        d["src"] = r.get("src", d.get("src", "WebFetch"))
        if r.get("source_url"):
            d["source_url"] = r["source_url"]
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  ✓ limit_count.json: {date} 涨停{r['limit_up']}/跌停{r['limit_down']}")
        _clear_todo("limit")
        return True
    except Exception as e:
        print(f"  ✗ limit 合并失败: {e}")
        return False


def merge_news():
    """合并 8/14 新闻条目 → news.json
    result 格式：{"items": [{"date": "2026-08-14", "title": "...", "impact": "...", ...}, ...]}
    """
    r = _load("news_result.json")
    if not r or not isinstance(r, dict):
        return False
    items = r.get("items", [])
    if not items:
        return False
    fp = os.path.join(DATA, "news.json")
    try:
        news = json.load(open(fp, encoding="utf-8"))
        cats = {c["name"]: c for c in news.get("categories", [])}
        # 去重
        existing_titles = set()
        for cat in news.get("categories", []):
            for it in cat.get("items", []):
                existing_titles.add(it.get("title", "")[:80])
        added = 0
        for it in items:
            title_prefix = it.get("title", "")[:80]
            if title_prefix in existing_titles:
                continue
            cat_name = it.get("category", "重要技术突破")
            cat_obj = cats.setdefault(cat_name, {"name": cat_name, "items": []})
            cat_obj.setdefault("items", []).insert(0, dict(it))
            existing_titles.add(title_prefix)
            added += 1
        # 限制每个 category 最新 12 条
        for c in news.setdefault("categories", []):
            c["items"] = c.get("items", [])[:12]
        news["time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        json.dump(news, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  ✓ news.json: 新增 {added} 条 8/14 新闻")
        _clear_todo("news")
        return added > 0
    except Exception as e:
        print(f"  ✗ news 合并失败: {e}")
        return False


def merge_ulistnp():
    """合并公司主力净流入 → stock_flows.json
    result 格式：{"date": "2026-08-14", "flows": {"北方华创": {"main": 1.5, ...}, ...}}

    安全策略：result.date 必须 >= stock_flows.json 中最新公司日期，否则跳过。
    （避免用更早日期的旧资金流覆盖当日已抓的最新数据）
    """
    r = _load("ulistnp_result.json")
    if not r or not isinstance(r, dict):
        return False
    flows_em = r.get("flows", {})
    if not flows_em:
        return False
    date = r.get("date")
    if not date:
        return False
    fp = os.path.join(DATA, "stock_flows.json")
    try:
        d = json.load(open(fp, encoding="utf-8")) if os.path.exists(fp) else {}
        # 检查现有最新日期
        existing_dates = [v.get("date", "") for v in d.values() if v.get("date")]
        latest_existing = max(existing_dates) if existing_dates else None
        if latest_existing and date < latest_existing:
            print(f"  ↷ 跳过 ulistnp: result.date={date} 早于 stock_flows 最新={latest_existing}")
            _clear_todo("ulistnp")
            return False
        filled = 0
        for name, fdata in flows_em.items():
            old = d.get(name, {})
            # 把 fdata 中的所有有效字段写入
            for k, v in fdata.items():
                if v is not None:
                    old[k] = v
            # 同步 date 字段保持一致
            old["date"] = date
            d[name] = old
            filled += 1
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  ✓ stock_flows.json: 已合并 {filled} 家公司 {date} 主力净流入")
        _clear_todo("ulistnp")
        return filled > 0
    except Exception as e:
        print(f"  ✗ ulistnp 合并失败: {e}")
        return False


def main():
    print("=" * 60)
    print(f"fetch_via_web_results  起始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    any_done = False
    for name, fn in [
        ("BK板块", merge_bk_raw),
        ("CDS", merge_cds),
        ("ETF净申购", merge_etf_flow),
        ("涨跌停", merge_limit),
        ("消息面", merge_news),
        ("公司主力净流入", merge_ulistnp),
    ]:
        print(f"\n[{name}]")
        try:
            if fn():
                any_done = True
        except Exception as e:
            print(f"  ✗ 异常: {e}")
    if not any_done:
        print("\n（所有 result.json 均无更新，跳过合并）")
    else:
        print("\n✓ 至少一项 result.json 已合并")
    print("=" * 60)


if __name__ == "__main__":
    main()