# -*- coding: utf-8 -*-
"""将 risk_check.json（v4）整合进 payload_hand.json：
- 当日新触发 → 强制执行结论
- 无新触发但冷却期内有近期触发 → 「风控执行中/冷却观察期」结论（结合执行确认状态）
- 执行确认（risk_ack.json）齐全 → 「已执行·冷却观察」，不再催促减仓
"""
import os, sys
import json, os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
COLLAB = os.path.join(BASE, "dashboard", "collab_data")

risk = json.load(open(os.path.join(DATA, "risk_check.json"), encoding="utf-8"))
hand = json.load(open(os.path.join(BASE, "payload_hand.json"), encoding="utf-8"))
state = json.load(open(os.path.join(DATA, "risk_state.json"), encoding="utf-8")) if os.path.exists(os.path.join(DATA, "risk_state.json")) else {"triggers": []}
acks = json.load(open(os.path.join(COLLAB, "risk_ack.json"), encoding="utf-8")) if os.path.exists(os.path.join(COLLAB, "risk_ack.json")) else []

# 近3个交易日（以风控引擎trading窗口为准：直接用日期差<=4天近似+trigger列表末批）
recent = state["triggers"][-10:]
# 取最近一批触发（最新trigger日期当日的所有触发）
last_date = recent[-1]["date"] if recent else None
last_batch = [t for t in recent if t["date"] == last_date] if last_date else []
today = datetime.now().strftime("%Y-%m-%d")

def acked(t):
    return any(a["scope"] == t["scope"] and a["tier"] == t["tier"] and a.get("triggerDate", t["date"]) == t["date"] for a in acks)

TIER_W = {"T1": 1.0, "T2": 1.0, "T3": 2.0, "M1": 1.0, "M2": 0.5, "B1": 2.0, "B2": 1.0}
track_actions = [a for a in risk["actions"] if a["rule"] == "赛道级风控"]
macro_actions = [a for a in risk["actions"] if a["rule"] == "宏观流动性风控"]
broad_actions = [a for a in risk["actions"] if a["rule"] == "宽基系统性风控"]

integrated = None
mode = None
if risk["actions"]:
    # 当日新触发：强制执行
    assigns = [(a["target"], TIER_W.get(a["tier"], 1.0)) for a in track_actions]
    parts = ["%s %s（%s档）" % (a["target"], a["action"], a["tier"]) for a in track_actions]
    parts += ["%s：%s" % (a["cond"], a["action"]) for a in macro_actions + broad_actions]
    n_t3 = sum(1 for a in track_actions if a["tier"] == "T3")
    headline_items = []
    if n_t3: headline_items.append("%d项赛道周线破位风控(T3)" % n_t3)
    if any(a["tier"] in ("T1", "T2") for a in track_actions): headline_items.append("赛道日线级风控(T1/T2)")
    if macro_actions: headline_items.append("宏观流动性风控")
    if broad_actions: headline_items.append("宽基系统性风控")
    batch = any(TIER_W.get(a["tier"], 0) >= 2 for a in risk["actions"])
    note = "风控指令凌驾打分结论，只减不加。"
    if batch:
        note += "触发2成档位，按公募申赎适配规则分两批执行：当日减1成、次日观察后再减1成；若14:30前条件已满足且大概率维持到收盘，优先15:00前提交赎回锁定当日净值。"
    note += "减仓资金：60%转红利/宽基基金+40%现金。冷却期3个交易日内同档位不重复触发、不发加仓指令。执行后请点击「我已执行减仓」确认。"
    integrated = {"headline": "触发" + " + ".join(headline_items), "main": "；".join(parts), "note": note,
                  "assigns": assigns, "batch": batch}
    mode = "fire"
elif last_batch:
    # 冷却期内：无新触发，展示最近一批触发的执行状态
    pending = [t for t in last_batch if not acked(t)]
    done = [t for t in last_batch if acked(t)]
    assigns = [(t["scope"], TIER_W.get(t["tier"], 1.0)) for t in last_batch]
    if pending:
        headline = "风控冷却期（%s触发）· %d项待执行确认" % (last_date, len(pending))
        main = "；".join("%s %s（%s档，%s触发）" % (t["scope"], "减仓%.0f成" % TIER_W.get(t["tier"], 1), t["tier"], t["date"]) for t in pending)
        if done:
            main += "；已确认执行：" + "、".join(t["scope"] for t in done)
        note = "同档位3个交易日内不重复触发、不发加仓指令；仅更高档位可追加。若已按指令完成减仓，请点击「我已执行减仓」确认，确认后进入冷却观察期，系统不再重复提示。"
        mode = "pending"
    else:
        headline = "风控已执行确认 · 冷却观察期（%s触发，%d个交易日不重复）" % (last_date, 3)
        main = "已确认执行：" + "、".join("%s %s档" % (t["scope"], t["tier"]) for t in done) + "——进入冷却观察期，不重复发同档位指令"
        note = "冷却期内打分体系（%.1f分）恢复为参考层：不追涨、不加仓；反向加仓需「连续3日站稳MA5+MACD底背离」双重确认且首次≤0.5成。" % hand.get("scoreSystem", {}).get("composite", 0)
        mode = "acked"
    integrated = {"headline": headline, "main": main, "note": note, "assigns": assigns, "batch": False}
    # 把最近一批触发补进 actions 供前端展示确认按钮
    if pending:
        risk["actions"] = [{"rule": "赛道级风控", "target": t["scope"], "tier": t["tier"],
                            "cond": "冷却期内待执行（%s触发）" % t["date"],
                            "action": "减仓%.0f成" % TIER_W.get(t["tier"], 1), "detail": "触发日：" + t["date"],
                            "triggerDate": t["date"]} for t in pending]
    risk["ackState"] = {"mode": mode, "pending": [t["scope"] for t in pending], "done": [t["scope"] for t in done], "lastDate": last_date}
risk["integrated"] = integrated
hand["riskControl"] = risk

# 结论覆盖
if integrated:
    cond_map = {a["target"]: a["cond"] for a in risk["actions"]}
    tracks_cfg = []
    for t, w in integrated.get("assigns", []):
        st = "已执行✓" if (mode == "acked" or (risk.get("ackState") and t in risk["ackState"]["done"])) else ("减%.0f成（待执行）" % w)
        tracks_cfg.append({"name": t, "op": st, "note": cond_map.get(t, "风控冷却期")})
    for tname in ("半导体设备", "存储芯片", "光通信模块"):
        if all(t["name"] != tname for t in tracks_cfg):
            tracks_cfg.append({"name": tname, "op": "不操作", "note": "未触发风控"})
    tone = "risk" if mode in ("fire", "pending") else "neutral"
    hand["conclusion"] = {
        "headline": integrated["headline"],
        "action": "强制风控执行（凌驾打分结论%.1f分）" % hand.get("scoreSystem", {}).get("composite", 0) if mode == "fire" else ("风控执行确认中（冷却期）" if mode == "pending" else "冷却观察期 · 打分体系恢复参考"),
        "tone": tone,
        "adjust": integrated["main"],
        "tracks": tracks_cfg,
        "forward": "冷却期管理：3个交易日内同档位不重复触发、不发加仓指令；若跌幅扩大触发更高档位方可追加。反向加仓需「连续3日站稳MA5+MACD底背离」双重确认，首次≤0.5成。",
        "riskNote": integrated["note"],
    }
else:
    # 2026-08-10 v1.1 修复：当 integrated=None（risk_state 已清空，无新触发也无可恢复的冷却期），
    # 主动清除 hand["conclusion"] 中的虚假"风控冷却期"内容，避免残留缓存误导用户
    old = hand.get("conclusion", {})
    if old and ("风控冷却期" in old.get("headline", "") or "风控执行" in old.get("action", "")):
        hand["conclusion"] = {
            "headline": "✓ 本期未触发强制风控",
            "action": "打分体系主导（全维度按档位执行）",
            "tone": "neutral",
            "adjust": "无强制风控指令；打分结果请查看下方评分维度。",
            "tracks": [
                {"name": "半导体设备", "op": "不操作", "note": "未触发风控"},
                {"name": "存储芯片", "op": "不操作", "note": "未触发风控"},
                {"name": "光通信模块", "op": "不操作", "note": "未触发风控"},
            ],
            "forward": "下一阶段关注：请按综合评分结论执行调仓。如需追踪个股动态，详见公司BI模块。",
            "riskNote": "本交易日宏观/赛道/宽基三类风控均未触发。",
        }
        print("已清除残留风控冷却期结论（旧结论已失效，10Y国债数据bug已修复）")

json.dump(hand, open(os.path.join(BASE, "payload_hand.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("mode:", mode, "| integrated:", integrated["headline"] if integrated else None)
print("conclusion:", hand["conclusion"]["headline"])
