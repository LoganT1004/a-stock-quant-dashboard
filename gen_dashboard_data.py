# -*- coding: utf-8 -*-
"""看板数据管道 v2：东方财富统一数据源，一年K线窗口，多均线，自动信号，个股行情，回测嵌入"""
import os, sys
import json, re
from datetime import datetime
from vol_utils import intraday_vol_factor

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(BASE, "dashboard")
WINDOW = 250

def load_tx(fname, key):
    with open(os.path.join(DATA, fname), encoding="utf-8") as f:
        d = json.load(f)["data"][key]["day"]
    return [{"date": r[0], "open": float(r[1]), "close": float(r[2]),
             "high": float(r[3]), "low": float(r[4]), "vol": float(r[5])} for r in d]

def load_em_json(fname):
    """加载东方财富 JSON 日K：{dates:[], closes:[]} → [{date,open,close,high,low}]"""
    d = json.load(open(os.path.join(DATA, fname), encoding="utf-8"))
    rows = []
    for i, dt in enumerate(d["dates"]):
        c = d["closes"][i]
        rows.append({"date": dt, "open": c, "close": c, "high": c, "low": c, "vol": 0.0})
    return rows

def ema(vals, n):
    k = 2 / (n + 1); out = []; e = vals[0]
    for i, v in enumerate(vals):
        e = v if i == 0 else v * k + e * (1 - k)
        out.append(e)
    return out

def sma(vals, n):
    return [round(sum(vals[max(0, i - n + 1):i + 1]) / min(n, i + 1), 2) for i in range(len(vals))]

def nine_turn(rows):
    n = len(rows); up = [0] * n; down = [0] * n
    for i in range(4, n):
        if rows[i]["close"] > rows[i - 4]["close"]: up[i] = up[i - 1] + 1
        if rows[i]["close"] < rows[i - 4]["close"]: down[i] = down[i - 1] + 1
    return up, down

def build(key, rows, name):
    closes = [r["close"] for r in rows]
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = ema(dif, 9)
    bar = [2 * (d - s) for d, s in zip(dif, dea)]
    up, down = nine_turn(rows)
    w = rows[-WINDOW:]; off = len(rows) - len(w)
    mas = {n: sma(closes, n)[off:] for n in (5, 10, 20, 60, 120, 250)}
    return key, {
        "name": name,
        "dates": [r["date"] for r in w],
        "kline": [[r["open"], r["close"], r["low"], r["high"]] for r in w],
        "vol": [r["vol"] for r in w],
        "ma": mas,
        "dif": [round(x, 2) for x in dif[off:]],
        "dea": [round(x, 2) for x in dea[off:]],
        "bar": [round(x, 2) for x in bar[off:]],
        "up": up[off:], "down": down[off:],
        "lastClose": w[-1]["close"],
        "chgPct": round((w[-1]["close"] / w[-2]["close"] - 1) * 100, 2),
        "lastDate": w[-1]["date"],
    }

def auto_signal(rows, name):
    """收盘口径自动信号：九转/背离/MA5/量能"""
    n = len(rows); closes = [r["close"] for r in rows]
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]; dea = ema(dif, 9)
    ma5 = sma(closes, 5)
    up, down = nine_turn(rows)
    cu, cd = up[-1], down[-1]
    recent30 = rows[-30:] if n >= 30 else rows
    u9 = [r["date"] for i, r in enumerate(rows[-30:], start=n - 30) if up[i] == 9]
    d9 = [r["date"] for i, r in enumerate(rows[-30:], start=n - 30) if down[i] == 9]
    if cu >= 9: nine = "高9（顶部预警）"
    elif cd >= 9: nine = "低9（底部预警）"
    elif cd > 0: nine = "无（下跌计数%d/9）" % cd
    elif cu > 0: nine = "无（上涨计数%d/9）" % cu
    else: nine = "无"
    # 连续MA5上/下天数
    streak = 0; side = ""
    for i in range(n - 1, max(n - 10, -1), -1):
        s = "上" if closes[i] > ma5[i] else "下"
        if not side: side = s
        if s == side: streak += 1
        else: break
    chg = round((closes[-1] / closes[-2] - 1) * 100, 2)
    # 量比：今日成交量 / 前5日均量（不含今日）= 东方财富"量比"标准公式
    # 之前错误：vol5(含今日)/vol20(含今日) → 得到0.98/1.05/0.89（与东方财富不符）
    # 修正后：today_vol / past5day_avg → 0.94/0.90/1.00（与东方财富一致）
    past5_vols = [r["vol"] for r in rows[-6:-1]]  # 前5个交易日（不含今日）
    vol_ma5 = sum(past5_vols) / 5 if len(past5_vols) == 5 else (sum(past5_vols) / len(past5_vols) if past5_vols else 0)
    # 盘中按已交易时长投影到全日，使盘中量比与东方财富 APP 一致
    today_vol = rows[-1]["vol"] * intraday_vol_factor()
    vr = round(today_vol / vol_ma5, 2) if vol_ma5 > 0 else None
    dif_s = round(dif[-1], 2); dea_s = round(dea[-1], 2)
    macd_state = "DIF在DEA上方" if dif[-1] > dea[-1] else "DIF在DEA下方"
    detail = ("DIF=%s/DEA=%s（%s）；收盘%sMA5（%s）已连续%s日；量比%s%s" %
              (dif_s, dea_s, macd_state, side, ma5[-1], streak, vr,
               "缩量" if vr and vr < 0.9 else ("放量" if vr and vr > 1.1 else "量能平稳")))
    if u9: detail += "；近30日高9：%s" % "、".join(u9)
    if d9: detail += "；近30日低9：%s" % "、".join(d9)
    status = "无信号"
    if cu >= 9: status = "顶部预警（待确认）"
    elif cd >= 9: status = "底部预警（待确认）"
    elif chg <= -2: status = "异动大跌"
    return {"name": name, "close": closes[-1], "chg": chg, "nine": nine,
            "div": "无背离", "strength": "无", "status": status if chg > -2 else status + "（%s%%）" % chg,
            "detail": detail, "curDown": cd, "curUp": cu, "streakSide": side, "streak": streak, "volRatio": vr}

def parse_stock_quotes(fname):
    raw = open(os.path.join(DATA, fname), encoding="utf-8").read()
    out = {}
    for m in re.finditer(r'v_\w+="([^"]+)"', raw):
        p = m.group(1).split("~")
        if len(p) > 33 and p[1]:
            out[p[1]] = {"code": p[2], "close": float(p[3] or 0), "chgPct": float(p[32] or 0),
                         "time": p[30] if len(p) > 30 else ""}
    return out

# ---------- 指数数据 ----------
idx = {}
builders = [
    ("szzs", load_tx("szzs_full.json", "sh000001"), "上证指数"),
    ("cybz", load_tx("cybz_full.json", "sz399006"), "创业板指"),
    ("kc50", load_tx("kc50_full.json", "sh000688"), "科创50"),
    ("ndx", load_tx("ndx100_full.json", "us.NDX"), "纳斯达克100"),
    ("sox", load_em_json("sox_em.json")[-WINDOW:], "费城半导体SOX"),
    ("dxy", load_em_json("dxy_em.json")[-WINDOW:], "美元指数DXY"),
]
for key, rows, name in builders:
    k, v = build(key, rows, name)
    idx[k] = v

# 赛道等权指数（score_engine 合成）
track_idx_file = os.path.join(DATA, "track_indexes.json")
if os.path.exists(track_idx_file):
    tidx = json.load(open(track_idx_file, encoding="utf-8"))
    for key, tname in [("bksb", "半导体设备指数"), ("bkcc", "存储芯片指数"), ("bkcm", "光通信模块指数")]:
        if tname.replace("指数", "") in tidx:
            rows = tidx[tname.replace("指数", "")]
            k, v = build(key, rows[-WINDOW:], name=tname)
            idx[k] = v

sig_rows = {
    "上证指数": load_tx("szzs_full.json", "sh000001"),
    "创业板指": load_tx("cybz_full.json", "sz399006"),
    "科创50": load_tx("kc50_full.json", "sh000688"),
}
signals = [auto_signal(rows, name) for name, rows in sig_rows.items()]

backtest = json.load(open(os.path.join(DATA, "backtest_result.json"), encoding="utf-8"))

# ---------- 动态报告生成（每次管道运行按最新数据组装，不再使用静态md） ----------
def build_report():
    R = payload_hand.get("riskControl", {}) if payload_hand else {}
    S = payload_hand.get("scoreSystem", {}) if payload_hand else {}
    C = payload_hand.get("conclusion", {}) if payload_hand else {}
    integ = R.get("integrated") or {}
    sig_tbl = "\n".join("| %s | %s | %+.2f%% | %s | %s |" % (
        s["name"], s["close"], s["chg"], s["nine"], s.get("status", "")) for s in signals)
    track_lines = "\n".join("- **%s**：%s（%s）" % (t["name"], t["op"], t["note"]) for t in C.get("tracks", []))
    ov_lines = "\n".join("- **%s**：%s（%s，%s）——%s" % (o["name"], o["val"], o["chg"], o["date"], o["note"]) for o in payload_hand.get("overseas", []))
    extras = S.get("extras", {})
    ex_lines = "\n".join("- [%s%s分｜%s影响｜%s] %s——%s" % (e["type"], e["points"], e.get("horizon", ""), e.get("time", ""), e.get("title", e.get("note", "")), e.get("reason", "")) for e in extras.get("items", []))
    return """【更新时点】
%s（%s）

【三大指数核心技术信号汇总】
| 指数 | 收盘点位 | 涨跌幅 | 神奇九转 | 状态 |
| --- | --- | --- | --- | --- |
%s

【强制风控（最高优先级）】
%s
%s

【仓位操作指引（场外公募专属）】
**%s**
%s
%s

【综合评分】
%s / 100（%s）｜技术面%.1f（60%%）｜外围面%.1f（25%%）｜资金面%.1f（10%%）｜基本面%.1f（5%%）｜加减分%+.0f

【外围市场先行指标】
%s

【额外加减分明细（消息面实时判定）】
%s
合计：%+.0f 分

【核心风险提示】
1. 风控冷却期内不加仓：反向加仓需「连续3日站稳MA5+MACD底背离」双重确认，首次≤0.5成
2. 外围传导：关注今夜美股对亚洲盘的二次传导
3. 融资盘结构：核心赛道融资盘集中，急跌易放大波动

【下一阶段重点关注】
1. 三大指数九转计数进度（当前见信号表）
2. 风控冷却期执行状态与更高档位触发条件
3. 消息面tab的行业政策/巨头财报/龙头动态更新

*本报告由数据管道于 %s 自动生成，所有结论为技术分析参考，不构成法定投资建议。*
""" % (
        meta_str(), session_str(),
        sig_tbl,
        ("⚠️ " + integ.get("headline", "")) if R.get("triggered") or R.get("ackState") else "✓ 本期未触发强制风控",
        integ.get("main", "") + ("——" + integ.get("note", "") if integ.get("note") else "") if integ else "",
        C.get("headline", ""), track_lines, C.get("forward", ""),
        S.get("composite", ""), S.get("compositeZone", ""),
        S.get("dimensions", [{}])[0].get("score", 0), S.get("dimensions", [{}, {}])[1].get("score", 0),
        S.get("dimensions", [{}, {}, {}])[2].get("score", 0), S.get("dimensions", [{}, {}, {}, {}])[3].get("score", 0),
        extras.get("total", 0),
        ov_lines, ex_lines, extras.get("total", 0),
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
def meta_str():
    return payload["meta"]["date"]
def session_str():
    return payload["meta"]["session"]

# ---------- 公司库（已删除：节省算力 + 减少出错几率） ----------
# 2026-08-12 用户要求删除"公司BI·三大赛道持仓标的"板块
companies = []

# ---------- 手工研判内容（保留此前结论框架） ----------
payload_hand = json.load(open(os.path.join(BASE, "payload_hand.json"), encoding="utf-8")) if os.path.exists(os.path.join(BASE, "payload_hand.json")) else None

payload = {
    "meta": {
        "date": idx["szzs"]["dates"][-1],
        "session": ("盘中实时" if idx["szzs"]["dates"][-1] == datetime.now().strftime("%Y-%m-%d") and datetime.now().hour < 15 else "收盘更新（15:00）"),
        "aShareTime": idx["szzs"]["dates"][-1] + (" 盘中" if idx["szzs"]["dates"][-1] == datetime.now().strftime("%Y-%m-%d") and datetime.now().hour < 15 else " 15:00"),
        "overseasTime": (idx["ndx"]["dates"][-1] + " 收盘（美股）") if "ndx" in idx else "—",
        "note": "全线采用东方财富行情数据（push2his日K + datacenter-web报告 + push2实时快照）；VXN：CBOE官方；美国10Y CDS：英为财情（自动化推送）"
    },
    "backtest": backtest,
    "signals": signals,
    "companies": companies,
    "indexes": idx,
}

if payload_hand:
    for k in ("conclusion", "argument", "scoreSystem", "overseas", "margin", "unlockIpo", "sources", "riskControl"):
        payload[k] = payload_hand[k]
else:
    raise SystemExit("payload_hand.json missing")

# WTI原油序列 + 两融/北向历史序列 + 消息面 + 解禁未来明细 + 融资TOP5（图表用）
for key, fn in (("wti", "wti.json"), ("marginHist", "margin_history.json"), ("northHist", "northbound_history.json"), ("news", "news.json"), ("unlockFuture", "unlock_future.json"), ("rzrqTop", "rzrq_top.json"), ("insights", "insights.json"), ("vxnHist", "vxn_history.json"), ("cdsHist", "cds_history.json"), ("etfFlowHist", "etf_flow_history.json"), ("position", "position_decision.json")):
    fp = os.path.join(DATA, fn)
    if os.path.exists(fp):
        payload[key] = json.load(open(fp, encoding="utf-8"))

# 今日涨/跌停家数（来自 fetch_limit_count.py）
limit_fp = os.path.join(DATA, "limit_count.json")
if os.path.exists(limit_fp):
    payload["limitCount"] = json.load(open(limit_fp, encoding="utf-8"))

payload["report"] = build_report()

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "data.js"), "w", encoding="utf-8") as f:
    f.write("window.DASHBOARD_DATA = ")
    json.dump(payload, f, ensure_ascii=False)
    f.write(";")
print("data.js written:", os.path.getsize(os.path.join(OUT, "data.js")))
for k in idx:
    print(k, idx[k]["name"], "bars:", len(idx[k]["dates"]), idx[k]["dates"][0], "→", idx[k]["dates"][-1], "close:", idx[k]["lastClose"], idx[k]["chgPct"])
print("signals:", [(s["name"], s["close"], s["chg"], s["nine"]) for s in signals])

# ---------- 云部署目录同步（deploy_dist 保持最新静态版，带 cache-busting 时间戳）----------
import shutil, datetime as _dt
DEPLOY = os.path.join(BASE, "deploy_dist")
os.makedirs(DEPLOY, exist_ok=True)
_ts = _dt.datetime.now().strftime("%Y%m%d%H%M")
for f in ("data.js", "collab.js", "echarts.min.js"):
    src = os.path.join(OUT, f)
    if os.path.exists(src):
        # 主文件（同名）
        shutil.copy2(src, os.path.join(DEPLOY, f))
        # 同时复制带版本号的副本（供 index.html 引用破缓存）
        name, ext = os.path.splitext(f)
        shutil.copy2(src, os.path.join(DEPLOY, f"{name}.{_ts}{ext}"))
# 处理 index.html：更新 data.js 的版本号引用（同时更新 dashboard 和 deploy_dist）
idx_src = os.path.join(OUT, "index.html")
if os.path.exists(idx_src):
    with open(idx_src, "r", encoding="utf-8") as f:
        idx_content = f.read()
    import re as _re
    new_idx_content = _re.sub(r'(data\.js\?v=)\d+', f'\\g<1>{_ts}', idx_content)
    # 同时写 dashboard 和 deploy_dist
    with open(idx_src, "w", encoding="utf-8") as f:
        f.write(new_idx_content)
    with open(os.path.join(DEPLOY, "index.html"), "w", encoding="utf-8") as f:
        f.write(new_idx_content)
    print(f"cache-busted: data.js?v={_ts} → dashboard/index.html + deploy_dist/index.html")
    print(f"deploy_dist synced (data.js?v={_ts})")
