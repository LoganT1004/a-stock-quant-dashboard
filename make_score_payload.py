# -*- coding: utf-8 -*-
"""将 score_result.json 转换为看板 scoreSystem v2 结构（含快照对比），并合并赛道指数K线进 indexes"""
import json, os

BASE = r"C:\Users\ASUS\WorkBuddy\2026-08-03-11-17-59"
DATA = os.path.join(BASE, "data")

sr = json.load(open(os.path.join(DATA, "score_result.json"), encoding="utf-8"))
hand = json.load(open(os.path.join(BASE, "payload_hand.json"), encoding="utf-8"))

tech = sr["tech"]
ov = sr["overseas"]; cap = sr["capital"]; fund = sr["fund"]
others_sum = ov["score"]*0.25 + cap["score"]*0.1 + fund["score"]*0.05 + sr["extras"]["total"]

def idx_composite(track_score, wide_score):
    return round(0.6*(0.6*track_score + 0.4*wide_score) + others_sum, 1)

by_index = []
for k, s in tech["wideScores"].items():
    # 2026-08-10 修正：注记必须真实反映当日 8/10 涨跌幅
    # 8/10 数据：上证 +0.67% | 创业板 -0.73% | 科创50 -0.36%
    note = {
        "上证指数": "8/10 +0.67%，宽基中相对最强",
        "创业板指": "8/10 -0.73%，融资重仓股集中",
        "科创50": "8/10 -0.36%缩量整理，连续5日站上MA5",
    }[k]
    by_index.append({"name": k, "score": idx_composite(tech["trackAvg"], s), "zone": "中性震荡区", "note": note})
by_track = []
for t, s in tech["trackScores"].items():
    # 2026-08-10 修正：注记必须真实反映当日 8/10 板块涨跌幅
    # 8/10 数据：半导体设备 +3.24% | 存储芯片 -0.22% | 光通信模块 -1.82%
    note = {
        "存储芯片": "8/10 -0.22%窄幅震荡，长鑫主力-32亿带动板块回踩",
        "半导体设备": "8/10 +3.24%强势（中微+6.08/拓荆+5.41/盛美+10%+），国产替代+并购验证",
        "光通信模块": "8/10 -1.82%，算力开支持疑冲击（中际旭创-6.01/新易盛-5.07），等待英伟达财报验证"
    }[t]
    by_track.append({"name": t, "score": idx_composite(s, tech["wideAvg"]), "zone": "中性震荡区", "note": note})

# 读取 position 中的 trend（用于历史趋势图标注趋势生效起始日）
_pos_trend = None
_pos_trend_start = None
_pos_trend_name = None
try:
    _p = json.load(open(os.path.join(BASE, "data", "position_decision.json"), encoding="utf-8"))
    _pos_trend = _p.get("trend")
    _pos_trend_start = _p.get("trendStartDate")
    _pos_trend_name = _p.get("trendName")
except Exception:
    pass

def dim_row(idx_name, subs):
    return {"index": idx_name, "subs": subs}

tech_table = []
for t in ("半导体设备", "存储芯片", "光通信模块"):
    s = sr["tech"]["trackDetail"][t]
    tech_table.append({"layer": "赛道指数信号(60%)", "index": t, "total": sr["tech"]["trackScores"][t], "subs": s})
for k in ("上证指数", "创业板指", "科创50"):
    s = sr["tech"]["wideDetail"][k]
    tech_table.append({"layer": "宽基指数信号(40%)", "index": k, "total": sr["tech"]["wideScores"][k], "subs": s})

zones = hand["scoreSystem"]["zones"]

score_system = {
    "version": "v3",
    "composite": sr["composite"],
    "compositeZone": sr["zone"],
    "desc": "四维加权打分体系v3：总分=技术面60%（赛道指数信号60%+宽基指数信号40%）+外围面25%（核心指标主导）+资金面10%（3日趋势基准）+基本面与消息面5%，额外加减分项直调总分。子指标0-100分，50为中性；九转仅触9计分，6-8计数只列关注；预警信号不计分不触发操作。",
    "ruleNote": sr["ruleNote"],
    "zones": zones,
    "extras": sr["extras"],
    "dimensions": [
        {"name": "技术面", "weight": 55, "score": tech["score"],
         "layers": [
             {"name": "赛道指数信号", "w": 60, "score": tech["trackAvg"],
              "items": [{"name": t, "score": tech["trackScores"][t]} for t in ("半导体设备", "存储芯片", "光通信模块")]},
             {"name": "宽基指数信号", "w": 40, "score": tech["wideAvg"],
              "items": [{"name": k, "score": tech["wideScores"][k]} for k in ("上证指数", "创业板指", "科创50")]}],
         "subs": tech_table},
        {"name": "外围面", "weight": 25, "score": ov["score"], "subs": ov["subs"]},
        {"name": "资金面", "weight": 10, "score": cap["score"], "subs": cap["subs"]},
        {"name": "基本面与消息面", "weight": 10, "score": fund["score"], "subs": fund["subs"]},
    ],
    "byIndex": by_index,
    "byTrack": by_track,
    "trend": _pos_trend,
    "trendName": _pos_trend_name,
    "trendStartDate": _pos_trend_start,
    "nextTrigger": "当前58.6分距65（弱底部加仓线）差6.4分：若三大宽基或赛道指数九转触低9（子项50→80），叠加3日MA5强确认（得分上调10），技术面可修复10分以上，综合得分有望突破65触发「加仓1成」；若外围纳指强确认延续+北向/两融回暖，将加速逼近80（强底部加仓2-3成线）。反之技术面跌破35（趋势继续恶化+缩量），综合跌破45触发「减仓1成」。",
    "snapshots": None,  # 由下方快照历史管理填充
}

# ---------- 快照历史（保留近30天，每次管道运行自动存档当前时点） ----------
from datetime import datetime, timedelta
SNAP_FILE = os.path.join(BASE, "data", "snapshots_history.json")
hist = json.load(open(SNAP_FILE, encoding="utf-8")) if os.path.exists(SNAP_FILE) else []
now = datetime.now()
label = "午盘" if now.hour < 13 else ("收盘" if now.hour >= 15 else "盘中")
# 读取 position 中的 trend（用于在历史趋势图标注趋势变更）— 已在前面读取过 _pos_trend
cur = {"time": now.strftime("%Y-%m-%d %H:%M"), "label": label, "composite": sr["composite"], "zone": sr["zone"],
       "tech": tech["score"], "overseas": ov["score"], "capital": cap["score"], "fund": fund["score"],
       "extras": sr["extras"]["total"],
       "trend": _pos_trend, "trendName": _pos_trend_name, "trendStartDate": _pos_trend_start,
       "sigBrief": "九转计数：上证%s/创业板%s/科创50%s；综合%.1f分（%s）" % (
           sr.get("nineBrief", ("-", "-", "-"))[0], sr.get("nineBrief", ("-", "-", "-"))[1],
           sr.get("nineBrief", ("-", "-", "-"))[2], sr["composite"], sr["zone"])}
# 同一天同一标签覆盖更新（盘中多次刷新只留最新），不同标签并存
hist = [h for h in hist if not (h["time"][:10] == cur["time"][:10] and h["label"] == label)]
# 历史快照缺失 trend 字段时，按 composite 与技术面分位回填（用于历史趋势图标注）
for h in hist:
    if "trend" not in h or h.get("trend") is None:
        c = h.get("composite", 55)
        t = h.get("tech", 50)
        # 简化回填规则：composite>60 且 tech>55 → up/bottom；composite<45 → down/top；其余 mid
        if c >= 60 and t >= 55:
            h["trend"] = "bottom"; h["trendName"] = "低位摸底震荡"
        elif c <= 45:
            h["trend"] = "down"; h["trendName"] = "单边下跌趋势"
        else:
            h["trend"] = "mid"; h["trendName"] = "震荡市·中位横盘"
hist.append(cur)
cutoff = (now - timedelta(days=30)).strftime("%Y-%m-%d")
hist = [h for h in hist if h["time"][:10] >= cutoff]
hist.sort(key=lambda h: h["time"])
json.dump(hist, open(SNAP_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
score_system["snapshots"] = hist

hand["scoreSystem"] = score_system
json.dump(hand, open(os.path.join(BASE, "payload_hand.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("scoreSystem v2 saved | composite:", sr["composite"], "| byIndex:", [(i["name"], i["score"]) for i in by_index], "| byTrack:", [(t["name"], t["score"]) for t in by_track])
