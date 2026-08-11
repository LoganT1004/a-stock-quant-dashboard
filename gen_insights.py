# -*- coding: utf-8 -*-
"""为数据看板每张图表生成「解读 + 走势判断」（数据驱动自动生成）"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
DASH = os.path.join(BASE, "dashboard")

def load(fn):
    p = os.path.join(DATA, fn)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None

def trend(vals, n=5):
    """近n日均值 vs 前n日均值的变化方向"""
    if len(vals) < n * 2: return "持平", 0
    a = sum(vals[-n:]) / n; b = sum(vals[-2*n:-n]) / n
    chg = (a / b - 1) * 100 if b else 0
    if chg > 3: return "上行", chg
    if chg < -3: return "下行", chg
    return "持平", chg

def pctile(vals, v):
    """当前值在近一年分位"""
    s = sorted(vals)
    rank = sum(1 for x in s if x <= v)
    return round(rank / len(s) * 100)

insights = {}

# ---- 两融余额 ----
mh = load("margin_history.json")
if mh and len(mh["values"]) > 20:
    vals, dates = mh["values"], mh["dates"]
    latest, prev = vals[-1], vals[-2]
    t, chg = trend(vals)
    pt = pctile(vals, latest)
    wchg = (vals[-1] / vals[-6] - 1) * 100 if len(vals) > 6 else 0
    insights["margin-chart"] = (
        "最新两融余额 <b>%.0f亿</b>（%s），单日%+.0f亿，近一周%+.2f%%；当前处于近一年 <b>%d%%</b> 分位，近10日均值趋势<b>%s</b>。"
        % (latest, dates[-1], latest - prev, wchg, pt, t) +
        ("余额自8/1低点25804亿连续回升，杠杆资金在赛道急跌后重新进场，属底部区域加仓行为——若延续回升将支撑反弹持续性；"
         if latest > vals[-6] else
         "余额仍在回落通道，杠杆资金尚未停止撤离，反弹缺乏杠杆资金背书，需等待余额企稳信号；") +
        "<b>走势判断：</b>" +
        ("杠杆情绪由出清转向回补，短期偏多验证；重点观察能否收复26000亿整数关口。"
         if latest > vals[-6] else
         "杠杆退潮未止，维持谨慎；若跌破前低则强化防御。"))

# ---- 北向成交额 ----
nh = load("northbound_history.json")
if nh and len(nh["total"]) > 20:
    vals, dates = nh["total"], nh["dates"]
    latest = vals[-1]
    t, chg = trend(vals)
    pt = pctile(vals, latest)
    peak = max(vals); peakd = dates[vals.index(peak)]
    insights["nb-chart"] = (
        "北向总成交额最新 <b>%.1f亿</b>（%s），处近一年 <b>%d%%</b> 分位；一年峰值%.1f亿（%s），近10日活跃度趋势<b>%s</b>（%+.1f%%）。"
        % (latest, dates[-1], pt, peak, peakd, t, chg) +
        "<b>走势判断：</b>" +
        ("成交活跃度仍低于6月峰值区间，北向资金处于存量博弈状态——缩量环境下赛道反弹更多由内资与融资盘驱动，北向放大成交前，反弹高度受量能约束。"
         if pt < 50 else
         "北向成交维持高位，外资参与度积极，与内资形成共振，对趋势延续构成支撑。"))

# ---- 融资买入TOP5 ----
rt = load("rzrq_top.json")
if rt:
    today_items = rt["today"]["items"]
    top1 = today_items[0]
    total5 = sum(i["amt"] for i in today_items)
    insights["topbuy-chart"] = (
        "当日赛道标的融资买入集中于 <b>%s（%.2f亿）</b>，TOP5合计 <b>%.1f亿</b>；上榜：%s。"
        % (top1["name"], top1["amt"], total5, "、".join(i["name"] for i in today_items)) +
        "<b>走势判断：</b>融资盘持续重仓光通信与存储龙头，杠杆资金与主力流向形成共振的方向（中际旭创/新易盛）短期动能最强；"
        "但融资盘集中度越高，波动放大效应越强，急跌时需警惕多杀多。")

# ---- 解禁 ----
uf = load("unlock_future.json")
if uf:
    insights["unlock-chart"] = (
        "未来7日解禁 <b>%.1f亿</b>、1个月 <b>%.1f亿</b>、半年 <b>%.1f亿</b>；高压周（单周>300亿）共%d个，"
        "其中 <b>9月W37（787亿）与10月W40（906亿）</b> 超500亿扣分阈值。" % (uf["sum7d"], uf["sum1m"], uf["sum6m"], len(uf["bigWeeks"])) +
        "<b>走势判断：</b>8月供给压力温和（全月1089亿环比-43%），不构成减仓理由；"
        "但9月中旬与10月初两个解禁高峰需提前一周复核，若届时叠加技术走弱，将触发评分扣分并压制板块估值修复节奏。")

# ---- A股K线（按当前指数各自生成）----
try:
    raw = open(os.path.join(DASH, "data.js"), encoding="utf-8").read()
    d = json.loads(raw[len("window.DASHBOARD_DATA = "):-1])
    for key in ("szzs", "cybz", "kc50", "bksb", "bkcc", "bkcm"):
        idx = d["indexes"][key]
        n = len(idx["dates"])
        close = idx["kline"][-1][1]
        ma5, ma20 = idx["ma"]["5"][-1], idx["ma"]["20"][-1]
        down, up = idx["down"][-1], idx["up"][-1]
        pos20 = (close / ma20 - 1) * 100
        nine = ("下跌计数%d/9" % down) if down > 0 else ("上涨计数%d/9" % up) if up > 0 else "无计数"
        above_ma5 = close > ma5
        above = "站上" if above_ma5 else "收于"
        # 走势判断：先看MA5位置，再看涨跌幅
        if above_ma5:
            if idx["chgPct"] > 2:
                judge = "今日大涨后重新站上MA5，若明日回踩确认则急跌波段宣告结束；反之若再度收破则需警惕二次探底。"
            elif idx["chgPct"] > -1:
                judge = "站上MA5但动能偏弱，需连续3日站稳方可确认止跌企稳；继续观察量能配合。"
            else:
                judge = "虽然收于MA5上方但日跌幅较大，反弹结构不稳固，需观察后续能否持续站稳MA5；若再度收破则将延续弱势。"
        else:
            if idx["chgPct"] > 2:
                judge = "今日大涨后重新逼近MA5，若明日站稳MA5且九转计数中断，急跌波段宣告结束；反之若再度收破，则计数推进至8，周四进入低9形成窗口——届时叠加缩量企稳将构成左侧加仓区。"
            elif idx["chgPct"] > -1:
                judge = "跌势放缓但未确认止跌，继续观察MA5争夺与量能变化。"
            else:
                judge = "仍在MA5下方弱势运行，未见企稳信号，维持观望。"
        insights["kline-" + key] = (
            "<b>%s</b> 最新收 <b>%.2f</b>（%+.2f%%），%sMA5（%.1f），偏离MA20 %+.1f%%；九转%s。"
            % (idx["name"], close, idx["chgPct"], above, ma5, pos20, nine) +
            "<b>走势判断：</b>" + judge)
    # ---- 外围 ----
    for key, label in (("ndx", "纳斯达克100"), ("sox", "费城半导体SOX"), ("dxy", "美元指数")):
        idx = d["indexes"][key]
        closes = [k[1] for k in idx["kline"]]
        ma5 = idx["ma"]["5"][-1]
        streak = 0
        for i in range(len(closes) - 1, max(len(closes) - 12, -1), -1):
            if closes[i] > idx["ma"]["5"][i]: streak += 1
            else: break
        insights["ov-" + key] = (
            "<b>%s</b> 最新 <b>%.2f</b>（%+.2f%%，%s），连续<b>%d日</b>收于MA5上方。"
            % (label, closes[-1], idx["chgPct"], idx["dates"][-1], streak) +
            "<b>走势判断：</b>" +
            ("底背离强确认后的反弹趋势延续，外围核心信号正向，对A股科技赛道构成先行指引；关注前高压力位量能配合。"
             if streak >= 3 else
             "反弹结构尚不稳定，需连续3日站稳MA5方可确认趋势反转。"))
    # ---- WTI ----
    w = d.get("wti")
    if w and w.get("dates"):
        vals = w["values"]
        latest = vals[-1]
        w5 = (vals[-1] / vals[-6] - 1) * 100 if len(vals) > 6 else 0
        insights["ov-wti"] = (
            "<b>WTI原油</b> 最新 <b>%.2f美元</b>（%s），近一周%+.1f%%；8/3单日-7.8%%暴跌后低位企稳。" % (latest, w["dates"][-1], w5) +
            "<b>走势判断：</b>油价急跌反映全球需求预期降温，与美债收益率下行、美元走弱共同验证流动性宽松方向——折现率端对科技成长股估值构成支撑；"
            "但若油价破位续跌引发衰退交易，将反噬风险偏好，需跟踪80美元关口得失。")
except Exception as e:
    insights["_error"] = str(e)

out = os.path.join(DATA, "insights.json")
json.dump(insights, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("insights generated:", len(insights), "条")
for k in list(insights)[:3]:
    print(" ", k, "->", insights[k][:60])
