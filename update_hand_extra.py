# -*- coding: utf-8 -*-
"""合并数据进 payload_hand.json（全部动态生成，禁止硬编码行情值）：
- 外围卡片（纳指/SOX/美债/DXY/WTI/VXN/CDS）从 data/ 数据文件动态计算
- 北向成交额从 northbound_history.json 动态取最新
- 公司BI资金流向合并
- 数据来源库维护"""
import json, os
from datetime import datetime

BASE = r"C:\Users\ASUS\WorkBuddy\2026-08-03-11-17-59"
DATA = os.path.join(BASE, "data")
hand = json.load(open(os.path.join(BASE, "payload_hand.json"), encoding="utf-8"))

def load(fn):
    p = os.path.join(DATA, fn)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None

def md(date_str):
    """2026-08-04 -> 08-04"""
    return date_str[5:] if date_str and len(date_str) >= 10 else date_str

def chg_str(c, p, bp=False):
    d = c - p
    if bp:
        return "%+.1fbp" % (d * 100)
    return "%+.2f%%" % ((c / p - 1) * 100 if p else 0)

def ma_streak(closes, n=5):
    """连续收于MA5上方天数"""
    if len(closes) < 6:
        return 0
    streak = 0
    for i in range(len(closes) - 1, 4, -1):
        ma = sum(closes[i - 4:i + 1]) / 5
        if closes[i] > ma:
            streak += 1
        else:
            break
    return streak

# ---------- 1) 公司BI资金流向 ----------
flows = load("stock_flows.json") or {}
for c in hand.get("companies", []):
    f = flows.get(c["name"])
    if f and "main" in f:
        c["flow"] = f

# ---------- 2) 外围卡片动态生成 ----------
ov_new = {}

# 纳指（东方财富 us.NDX push2his）
ndx = load("ndx100_full.json")
if ndx:
    day = ndx["data"]["us.NDX"]
    day = day.get("day") or day.get("qfqday")
    c, p = float(day[-1][2]), float(day[-2][2])
    closes = [float(r[2]) for r in day]
    streak = ma_streak(closes)
    ov_new["纳斯达克"] = {
        "val": "%.2f" % c, "chg": chg_str(c, p), "date": md(day[-1][0]), "src": "东方财富",
        "note": "最新收%.2f（%s），底背离强确认后连续%d日站稳MA5，反弹趋势延续" % (c, chg_str(c, p), streak)}

# SOX（东方财富 100.SOX push2his via sox_em.json；兼容历史 sox_sina.txt）
p_sox_em = os.path.join(DATA, "sox_em.json")
p_sox_sina = os.path.join(DATA, "sox_sina.txt")
if os.path.exists(p_sox_em):
    try:
        sx = json.load(open(p_sox_em, encoding="utf-8"))
        cs = sx["closes"]; ds = sx["dates"]
        c, p_ = cs[-1], cs[-2]
        streak = ma_streak(cs)
        ov_new["费城半导体SOX"] = {
            "val": "%.2f" % c, "chg": chg_str(c, p_), "date": md(ds[-1]), "src": sx.get("src", "东方财富"),
            "note": "最新收%.2f（%s），连续%d日站稳MA5；SOX与纳指同步性为外围核心信号" % (c, chg_str(c, p_), streak)}
    except Exception:
        pass
elif os.path.exists(p_sox_sina):
    raw = open(p_sox_sina, encoding="utf-8", errors="ignore").read()
    try:
        j = json.loads(raw[raw.find("(") + 1:raw.rfind(")")])
        c, p_ = float(j[-1]["c"]), float(j[-2]["c"])
        closes = [float(r["c"]) for r in j]
        streak = ma_streak(closes)
        ov_new["费城半导体SOX"] = {
            "val": "%.2f" % c, "chg": chg_str(c, p_), "date": md(j[-1]["d"]), "src": "东方财富",
            "note": "最新收%.2f（%s），连续%d日站稳MA5；SOX与纳指同步性为外围核心信号" % (c, chg_str(c, p_), streak)}
    except Exception:
        pass

# 美债10Y（东财us10y_em.json）
us10y = load("us10y_em.json")
if us10y:
    ks = us10y["data"]["klines"]
    last = ks[-1].split(",")
    prev = ks[-2].split(",")
    c, p_ = float(last[2]), float(prev[2])
    ov_new["美债10Y收益率"] = {
        "val": "%.3f%%" % c, "chg": chg_str(c, p_, bp=True), "date": md(last[0]), "src": "东方财富(171.US10Y)",
        "note": "最新%.4f%%（单日%s），流动性风控阈值为3日累计+25bp，当前3日累计%s；折现率压力%s" % (
            c, chg_str(c, p_, bp=True),
            chg_str(c, float(ks[-4].split(",")[2]), bp=True) if len(ks) >= 4 else "待算",
            "缓和" if c < 4.7 else "上行需警惕"),
        "url": "https://quote.eastmoney.com/stock/171.US10Y.html"}

# 美元指数（东方财富 100.UDI push2his via dxy_em.json；兼容 dxy_sina.txt）
p_dxy_em = os.path.join(DATA, "dxy_em.json")
p_dxy_sina = os.path.join(DATA, "dxy_sina.txt")
if os.path.exists(p_dxy_em):
    try:
        dx = json.load(open(p_dxy_em, encoding="utf-8"))
        ds, cs = dx["dates"], dx["closes"]
        c, p_ = cs[-1], cs[-2]
        ov_new["美元指数DXY"] = {
            "val": "%.2f" % c, "chg": chg_str(c, p_), "date": md(ds[-1]), "src": dx.get("src", "东方财富"),
            "note": "最新%.2f（%s），%s" % (c, chg_str(c, p_),
                "跌破100关口后弱势运行，全球美元流动性边际宽松，利好新兴市场与科技成长估值" if c < 100
                else "重回100上方，美元流动性边际收紧，关注对科技板块估值的压制")}
    except Exception:
        pass
elif os.path.exists(p_dxy_sina):
    raw = open(p_dxy_sina, encoding="utf-8", errors="ignore").read()
    try:
        parts = [x for x in raw.split("|") if x.count(",") >= 4]
        last = parts[-1].split(",")
        prev = parts[-2].split(",")
        d_date = last[0].split("=")[-1] if "=" in last[0] else last[0]
        c, p_ = float(last[2]), float(prev[2])
        ov_new["美元指数DXY"] = {
            "val": "%.2f" % c, "chg": chg_str(c, p_), "date": md(d_date), "src": "东方财富",
            "note": "最新%.2f（%s），%s" % (c, chg_str(c, p_),
                "跌破100关口后弱势运行，全球美元流动性边际宽松，利好新兴市场与科技成长估值" if c < 100
                else "重回100上方，美元流动性边际收紧，关注对科技板块估值的压制")}
    except Exception:
        pass

# WTI原油
wti = load("wti.json")
if wti:
    c, p_ = wti["closes"][-1], wti["closes"][-2]
    ov_new["WTI原油"] = {
        "val": "%.2f美元" % c, "chg": chg_str(c, p_), "date": md(wti["dates"][-1]), "src": "东方财富(102.CL00Y)",
        "note": "最新%.2f美元（%s），油价%s——与美债、美元共同构成全球流动性三指标验证" % (
            c, chg_str(c, p_), "回落验证通胀压力缓和" if c < 85 else "上行带来通胀输入压力"),
        "url": "https://quote.eastmoney.com/qihuo/CL00Y.html"}

# 写回（保留VXN/CDS等无法自动获取的卡片原值）
for i, o in enumerate(hand.get("overseas", [])):
    name = o["name"]
    if name in ov_new:
        src_keep = o.get("url")
        hand["overseas"][i].update(ov_new[name])
        if src_keep and "url" not in ov_new[name]:
            hand["overseas"][i]["url"] = src_keep

# ---------- 3) 北向成交额动态（northbound_history.json最新值） ----------
nh = load("northbound_history.json")
if nh and nh.get("dates"):
    i = -1
    # 跳过当日（盘中不完整）若与今天相同且时间在15点前？保守取最新一日
    latest_date = nh["dates"][i]
    total, sh, sz = nh["total"][i], nh["sh"][i], nh["sz"][i]
    # 近20日均值
    recent = nh["total"][-20:]
    avg20 = sum(recent) / len(recent)
    pos = "高于" if total > avg20 else "低于"
    hand["margin"]["northbound"] = {
        "note": "北向资金（陆股通）净流向自2024/8/18起停止日度披露（交易所口径调整），现以成交总额衡量北向活跃度：%s北向成交总额%.2f亿元（沪股通%.2f亿+深股通%.2f亿），%s近20日均值（%.0f亿）" % (
            latest_date, total, sh, sz, pos, avg20),
        "turnover": "%.2f亿元" % total, "turnoverSH": "%.2f亿元" % sh, "turnoverSZ": "%.2f亿元" % sz,
        "date": latest_date,
        "southNet": hand["margin"].get("northbound", {}).get("southNet", ""),
        "southNote": hand["margin"].get("northbound", {}).get("southNote", ""),
        "src": "东方财富-沪深港通",
        "url": "https://data.eastmoney.com/hsgt/hsgtV2.html",
    }

# ---------- 4) 数据来源库补充（只增不覆盖） ----------
new_sources = [
    {"name": "东方财富-沪深港通", "url": "https://data.eastmoney.com/hsgt/hsgtV2.html", "use": "北向资金总成交额（净流向已停日度披露，按成交额口径）与南向净买入", "builtin": True},
    {"name": "东方财富-两融总量", "url": "https://data.eastmoney.com/rzrq/total.html", "use": "融资融券余额逐日历史（图表数据源）", "builtin": True},
    {"name": "东方财富-WTI原油", "url": "https://quote.eastmoney.com/qihuo/CL00Y.html", "use": "WTI原油(NYMEX连续 102.CL00Y)——全球流动性第三观察指标", "builtin": True},
    {"name": "东方财富-美债10Y", "url": "https://quote.eastmoney.com/stock/171.US10Y.html", "use": "美国10年期国债收益率", "builtin": True},
    {"name": "东方财富-板块指数", "url": "https://quote.eastmoney.com/center/boardlist.html", "use": "赛道板块指数BK1326半导体设备/BK1137存储芯片/BK1136光通信模块（风控与评分口径）", "builtin": True},
    {"name": "东方财富-基金净值", "url": "https://api.fund.eastmoney.com/", "use": "赛道ETF净值（159516/159995/515880，周线口径备用）", "builtin": True},
    {"name": "东方财富-个股资金流向", "url": "https://data.eastmoney.com/zjlx/", "use": "16家赛道龙头主力/超大单/大单净流入（公司BI资金动向）", "builtin": True},
    {"name": "东方财富-解禁明细", "url": "https://data.eastmoney.com/dxf/", "use": "未来解禁逐日/逐周明细（解禁图表与扣分项判定）", "builtin": True},
    {"name": "东方财富-融资融券个股明细", "url": "https://data.eastmoney.com/rzrq/detail.html", "use": "16家标的融资买入额（TOP5当日/上周/本月）", "builtin": True},
]
existing = {s["url"] for s in hand.get("sources", [])}
for s in new_sources:
    if s["url"] not in existing:
        hand["sources"].append(s)

json.dump(hand, open(os.path.join(BASE, "payload_hand.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("overseas动态:", [(o["name"], o["val"], o["date"]) for o in hand["overseas"]])
print("northbound:", hand["margin"]["northbound"].get("date"), hand["margin"]["northbound"].get("turnover"))
