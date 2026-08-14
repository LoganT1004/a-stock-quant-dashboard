# -*- coding: utf-8 -*-
"""强制风控引擎 v4（2026-08-04 新规则）
优先级最高，凌驾打分结论；仅触发减仓不触发加仓。
规则：
(1) 赛道级（半导体设备/存储芯片/光通信）
    T1 单日跌幅>=9% 且 量比>=1.5            -> 该赛道减1成
    T2 连续2日累计跌幅>=12% 且 收盘破MA20   -> 该赛道减1成
    T3 单周跌幅>=15% 且 周线跌破10周均线    -> 该赛道减2成
(2) 宏观流动性
    M1 美债10Y 3日累计上行>=25bp 且突破近1个月关键阻力位 -> 整体减1成
    M2 DXY 3日累计上涨>=2.5% 且突破近3个月新高           -> 整体减0.5成
(3) 宽基系统性
    B1 科创50 跌破近3个月平台下沿 且连续3日收于平台下方 且放量 -> 整体减2成
    B2 上证/创业板/科创50 同步单日>=3% 且全市场跌停>50家       -> 整体减1成
配套：冷却期3个交易日（同档位不重复触发/禁加仓指令）、反向加仓门槛、申赎适配（14:30窗口/收盘后约束/>=2成分两批）。
口径：赛道日涨跌幅=东财ETF净值增长率（159516/159995/515880）；均线/周线=ETF净值序列；
     量比=成分股合计成交量（track_indexes.json）；宽基=腾讯K线。
"""
import os, sys
import json
from datetime import datetime
from vol_utils import intraday_vol_factor

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

def load(fn):
    p = os.path.join(DATA, fn)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None

def sma(vals, n):
    return [sum(vals[max(0, i - n + 1):i + 1]) / min(n, i + 1) for i in range(len(vals))]

def pct(a, b):
    return (a / b - 1) * 100 if b else 0.0

# ---------- 数据装载 ----------
etf_nav = load("etf_nav.json")            # {赛道: [{date,nav,chg}]} 东财净值口径
tidx = load("track_indexes.json")         # 成分等权合成（量比用成交量）
kc50 = load("kc50_full.json")
us10y = load("us10y_em.json")
dxy_raw = None
# 优先读 dxy_em.json（东财格式），兼容旧 dxy_sina.txt
p_em = os.path.join(DATA, "dxy_em.json")
p_sina = os.path.join(DATA, "dxy_sina.txt")
if os.path.exists(p_em):
    try:
        dx = json.load(open(p_em, encoding="utf-8"))
        dxy_raw = [{"day": dx["dates"][i], "close": dx["closes"][i]} for i in range(len(dx["dates"]))]
    except Exception:
        pass
if not dxy_raw and os.path.exists(p_sina):
    raw = open(p_sina, encoding="utf-8", errors="ignore").read()
    try:
        body = raw[raw.find('("') + 2:raw.rfind('")')]
        dxy_raw = [{"day": r.split(",")[0], "close": float(r.split(",")[2])}
                   for r in body.split("|") if r.count(",") >= 4]
    except Exception:
        dxy_raw = None
state = load("risk_state.json") or {"triggers": []}   # 冷却期状态机

rules, actions, alerts = [], [], []
new_triggers = []

# ---------- (1) 赛道级风控（东财BK板块指数口径，用户指定替代ETF净值） ----------
TRACK_BK = {
    "半导体设备": {"file": "bk1326_raw.json", "code": "BK1326"},
    "存储芯片":   {"file": "bk1137_raw.json", "code": "BK1137"},
    "光通信模块": {"file": "bk1136_raw.json", "code": "BK1136"},
    "创新药":     {"file": "bk1106_raw.json", "code": "BK1106"},
}
def load_bk(fn):
    d = load(fn)
    if not d:
        return []
    return [{"date": r.split(",")[0], "open": float(r.split(",")[1]), "close": float(r.split(",")[2]),
             "high": float(r.split(",")[3]), "low": float(r.split(",")[4]), "vol": float(r.split(",")[5])}
            for r in d["klines"]]

for t, meta in TRACK_BK.items():
    rows = load_bk(meta["file"])
    if len(rows) < 60:
        continue
    closes = [r["close"] for r in rows]
    vols = [r["vol"] for r in rows]
    last = rows[-1]
    day_chg = pct(closes[-1], closes[-2])                     # 单日（BK官方收盘/盘中）
    cum2 = pct(closes[-1], closes[-3])                        # 连续2日累计
    # 本周（周一7/28起；每周一为起点动态计算）
    monday = None
    for i in range(len(rows) - 1, -1, -1):
        if datetime.strptime(rows[i]["date"], "%Y-%m-%d").weekday() == 0:
            monday = i
            break
    cumw = pct(closes[-1], closes[monday - 1]) if monday else 0  # 单周（自上周收盘起）
    ma20 = sma(closes, 20)
    below_ma20 = closes[-1] < ma20[-1]
    # 周线：按ISO周聚合取每周末收盘，算10周均线
    weekly = {}
    for r in rows:
        yw = datetime.strptime(r["date"], "%Y-%m-%d").isocalendar()[:2]
        weekly[yw] = r["close"]
    wvals = list(weekly.values())
    ma10w = sma(wvals, 10)
    below_ma10w = wvals[-1] < ma10w[-1] if len(wvals) >= 10 else None
    # 量比：东方财富标准公式 = 今日成交量 / 前5日均量(不含今日)
    # 原 v5/v20 (5日均/20日均) 错误，平均偏高 5-15%
    today_vol = vols[-1] * intraday_vol_factor()
    past5_avg = sum(vols[-6:-1]) / 5 if len(vols) >= 6 else (sum(vols[:-1]) / max(len(vols)-1, 1) if len(vols) > 1 else 0)
    vol_ratio = today_vol / past5_avg if past5_avg > 0 else 1
    src_tag = "东财板块指数%s（%s）" % (meta["code"], last["date"])

    cur = ("单日%+.2f%%（%s）｜2日累计%+.2f%%｜单周%+.2f%%｜%sMA20（%.0f）｜周线%s10周均线｜量比%.2f" % (
        day_chg, src_tag, cum2, cumw,
        "跌破" if below_ma20 else "站上", ma20[-1],
        ("跌破" if below_ma10w else "未跌破") if below_ma10w is not None else "样本不足", vol_ratio))
    fired = []
    if day_chg <= -9 and vol_ratio and vol_ratio >= 1.5:
        fired.append(("T1", "单日跌幅≥9%且量比≥1.5", "减仓1成"))
    if cum2 <= -12 and below_ma20:
        fired.append(("T2", "连续2日累计跌幅≥12%且跌破MA20", "减仓1成"))
    if cumw <= -15 and below_ma10w:
        fired.append(("T3", "单周跌幅≥15%且周线跌破10周均线", "减仓2成"))
    if fired:
        top = fired[-1]  # 取最高档
        rules.append({"rule": "赛道级风控", "target": t, "status": "触发",
                      "current": cur + "｜命中档位：" + "、".join(f[0] for f in fired)})
        actions.append({"rule": "赛道级风控", "target": t, "tier": top[0],
                        "cond": top[1], "action": top[2], "detail": cur})
        new_triggers.append({"date": rows[-1]["date"], "scope": t, "tier": top[0]})
    else:
        rules.append({"rule": "赛道级风控", "target": t, "status": "未触发", "current": cur})

# ---------- (2) 宏观流动性风控 ----------
if us10y and us10y.get("data", {}).get("klines"):
    ks = [k.split(",") for k in us10y["data"]["klines"]]
    yc = [float(k[2]) for k in ks]
    if len(yc) >= 4:
        d3 = (yc[-1] - yc[-4]) * 100                        # 3日累计bp
        resist = max(yc[-22:-1])                            # 近1个月阻力位（前期高点）
        breakout = yc[-1] > resist
        cur = "最新%.4f%%（%s）｜3日累计%+.1fbp｜近1月阻力%.4f%%：%s" % (
            yc[-1], ks[-1][0], d3, resist, "突破" if breakout else "未突破")
        if d3 >= 25 and breakout:
            rules.append({"rule": "宏观流动性风控", "target": "美债10Y", "status": "触发", "current": cur})
            actions.append({"rule": "宏观流动性风控", "target": "美债10Y", "tier": "M1",
                            "cond": "3日累计上行≥25bp且突破近1月阻力", "action": "整体减仓1成", "detail": cur})
            new_triggers.append({"date": ks[-1][0], "scope": "整体", "tier": "M1"})
        else:
            rules.append({"rule": "宏观流动性风控", "target": "美债10Y", "status": "未触发", "current": cur})
if dxy_raw:
    dc = [float(r["close"]) for r in dxy_raw]
    if len(dc) >= 65:
        d3 = pct(dc[-1], dc[-4])
        high3m = max(dc[-65:-1])
        breakout = dc[-1] > high3m
        cur = "最新%.2f（%s）｜3日累计%+.2f%%｜近3月新高%.2f：%s" % (
            dc[-1], dxy_raw[-1]["day"], d3, high3m, "突破" if breakout else "未突破")
        if d3 >= 2.5 and breakout:
            rules.append({"rule": "宏观流动性风控", "target": "美元指数DXY", "status": "触发", "current": cur})
            actions.append({"rule": "宏观流动性风控", "target": "美元指数DXY", "tier": "M2",
                            "cond": "3日累计上涨≥2.5%且突破近3个月新高", "action": "整体减仓0.5成", "detail": cur})
            new_triggers.append({"date": dxy_raw[-1]["day"], "scope": "整体", "tier": "M2"})
        else:
            rules.append({"rule": "宏观流动性风控", "target": "美元指数DXY", "status": "未触发", "current": cur})

# ---------- (3) 宽基系统性风控 ----------
if kc50:
    kd = kc50["data"]["sh000688"]
    day = kd.get("day") or kd.get("qfqday")
    rows = [{"date": r[0], "close": float(r[2]), "vol": float(r[5])} for r in day]
    closes = [r["close"] for r in rows]
    vols = [r["vol"] for r in rows]
    # 近3个月震荡平台下沿：排除近5日后的近60日最低点
    platform = min(closes[-65:-5]) if len(closes) >= 65 else min(closes[:-5])
    below_streak = 0
    for c in reversed(closes):
        if c < platform: below_streak += 1
        else: break
    # 量比：东方财富标准公式 = 今日成交量 / 前5日均量(不含今日)
    # 短期/长期均量比用于判断放量趋势
    v5 = sum(vols[-6:-1]) / 5 if len(vols) >= 6 else (sum(vols[:-1]) / max(len(vols)-1, 1) if len(vols) > 1 else 0)
    v20 = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else (sum(vols[:-1]) / max(len(vols)-1, 1) if len(vols) > 1 else 0)
    today_vol = vols[-1] * intraday_vol_factor()
    vol_ratio = today_vol / v5 if v5 > 0 else 1  # 标准量比
    vol_expand = vol_ratio > 1.2  # 用标准量比判断放量
    cur = ("收盘%.2f（%s）｜平台下沿%.2f｜连续%d日收于平台下方｜量比%.2f（%s）" % (
        closes[-1], rows[-1]["date"], platform, below_streak,
        vol_ratio, "放大" if vol_expand else "未放大"))
    if below_streak >= 3 and vol_expand:
        rules.append({"rule": "宽基系统性风控", "target": "科创50", "status": "触发", "current": cur})
        actions.append({"rule": "宽基系统性风控", "target": "科创50", "tier": "B1",
                        "cond": "跌破近3月平台+连续3日收于下方+放量", "action": "整体减仓2成", "detail": cur})
        new_triggers.append({"date": rows[-1]["date"], "scope": "整体", "tier": "B1"})
    else:
        rules.append({"rule": "宽基系统性风控", "target": "科创50", "status": "未触发", "current": cur})

    # B2：三指数同步单日≥3% + 跌停>50家（从 data/limit_count.json 读今日真实家数）
    sync = {}
    for fn, sec, nm in [("szzs_full.json", "sh000001", "上证指数"), ("cybz_full.json", "sz399006", "创业板指")]:
        d = load(fn)
        if d:
            dd = d["data"][sec]; dy = dd.get("day") or dd.get("qfqday")
            sync[nm] = pct(float(dy[-1][2]), float(dy[-2][2]))
    sync["科创50"] = pct(closes[-1], closes[-2])
    # 读取今日真实跌停/涨停家数（fetch_limit_count.py 写入）
    limit_info = {}
    try:
        limit_info = json.load(open(os.path.join(os.path.dirname(__file__), "data", "limit_count.json"), encoding="utf-8"))
    except Exception:
        pass
    real_limit_down = limit_info.get("limit_down")
    real_limit_up = limit_info.get("limit_up")
    limit_text = ""
    if real_limit_down is not None and real_limit_up is not None:
        # 2026-08-13 修订：只显示数量，不拼接 src 长串（用户要求）
        limit_text = "｜今日涨停%d家 / 跌停%d家" % (real_limit_up, real_limit_down)
    else:
        limit_text = "｜跌停家数待补（请运行 fetch_limit_count.py）"
    all3 = all(v <= -3 for v in sync.values())
    cur = "单日涨跌幅：" + " / ".join("%s%+.2f%%" % (k, v) for k, v in sync.items()) + limit_text
    st = "触发" if (all3 and real_limit_down is not None and real_limit_down > 50) else "未触发"
    rules.append({"rule": "宽基系统性风控", "target": "三指数同步", "status": st if not all3 else "待核实",
                  "current": cur + ("｜三指数同步≥3%已满足，跌停>50家已确认" if (all3 and real_limit_down and real_limit_down > 50) else "")})
    if all3 and real_limit_down is not None and real_limit_down > 50:
        actions.append({"rule": "宽基系统性风控", "target": "三指数同步", "tier": "B2",
                        "cond": "三指数同步单日≥3%且跌停>50家", "action": "整体减仓1成", "detail": cur})

# ---------- 冷却期与档位状态机 ----------
# 记录新触发；近3个交易日内的同scope同tier触发被抑制（冷却期）
trading_days = sorted({r["date"] for r in (tidx.get("半导体设备") or [])})
def recent_days(n):
    return trading_days[-n:] if trading_days else []
cool_window = recent_days(3)
active_cd = [t for t in state["triggers"] if t["date"] in cool_window]
for nt in new_triggers:
    dup = any(t["scope"] == nt["scope"] and t["tier"] == nt["tier"] for t in state["triggers"])
    if not dup:
        state["triggers"].append(nt)
state["triggers"] = state["triggers"][-60:]
json.dump(state, open(os.path.join(DATA, "risk_state.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

cooldown = {
    "active": bool(active_cd),
    "items": ["%s %s档（%s触发，冷却期内同档位不重复）" % (t["scope"], t["tier"], t["date"]) for t in active_cd],
    "window": "冷却窗口=近3个交易日：" + "、".join(cool_window),
    "rule": "强制减仓后3个交易日内不触发同档位风控、不发加仓指令；仅更高档位可追加。反向加仓需「连续3日站稳MA5+MACD底背离确认」，首次≤0.5成。",
}

# ---------- 申赎适配执行指引 ----------
execution = [
    "最优操作窗口：14:30前若已满足触发条件且大概率维持到收盘，优先15:00前提交赎回，按当日净值确认，锁定当日价格。",
    "收盘后触发：仅「单日9%放量暴跌」「连续2日累计跌12%且破MA20」强确认条件可执行减仓；普通下跌未破关键均线的改为次日观察。",
    "大额减仓分批：触发2成及以上整体减仓时，默认分2个交易日执行（当日1成+次日观察后再1成），平滑冲击成本。",
]

result = {
    "time": datetime.now().strftime("%Y-%m-%d %H:%M") + "（行情截至%s）" % (trading_days[-1] if trading_days else "最新交易日"),
    "version": "v4",
    "triggered": len(actions) > 0,
    "rules": rules, "actions": actions, "alerts": alerts,
    "cooldown": cooldown, "execution": execution,
    "principle": "仅针对极端系统性风险、趋势性破位触发，过滤单日情绪脉冲；风控只减不加，凌驾于所有打分结论。",
}
json.dump(result, open(os.path.join(DATA, "risk_check.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("=== 风控 v4 检测（截至8/3收盘）===")
for r in rules:
    print("[%s] %s-%s: %s" % (r["status"], r["rule"], r["target"], r["current"][:90]))
print("actions:", [(a["target"], a["tier"], a["action"]) for a in actions])
print("cooldown active:", cooldown["active"], cooldown["items"])
