# -*- coding: utf-8 -*-
"""将 score_result.json 转换为看板 scoreSystem v2 结构（含快照对比），并合并赛道指数K线进 indexes"""
import os, sys
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

sr = json.load(open(os.path.join(DATA, "score_result.json"), encoding="utf-8"))
hand = json.load(open(os.path.join(BASE, "payload_hand.json"), encoding="utf-8"))

tech = sr["tech"]
ov = sr["overseas"]; cap = sr["capital"]; fund = sr["fund"]
others_sum = ov["score"]*0.25 + cap["score"]*0.1 + fund["score"]*0.05 + sr["extras"]["total"]

def idx_composite(track_score, wide_score):
    return round(0.6*(0.6*track_score + 0.4*wide_score) + others_sum, 1)

by_index = []  # 2026-08-13 修订：删除分宽基指数综合得分
for k, s in tech["wideScores"].items():
    pass  # noop，保留占位以避免破坏 score_result 兼容

# 2026-08-13 修订：四赛道综合得分（含创新药 BK1106），用新公式 技术面50% + 基本面35% + 消息面15%
by_track = []
_track_scores_raw = {}
_track_scores_fp = os.path.join(DATA, "track_scores.json")
if os.path.exists(_track_scores_fp):
    _track_scores_raw = json.load(open(_track_scores_fp, encoding="utf-8"))

# 趋势判定（基于 BK 板块的 MA5 vs MA20 + MA20 方向）
def _trend_judge(bk_fp):
    """1:1 对齐科创50 + 位置状态判定（用户指令 v4.2）。

    位置状态 4 档（基于近20日区间分位 + MA20 方向 + 5日反弹）：
      高位横盘：pct ≥ 80%（默认高位区间震荡）
      中位反弹：pct 30-70% + MA20拐头向上 + 5日内反弹
      中位横盘：pct 30-70% + MA20平稳（默认中位区间震荡）
      低位筑底：pct ≤ 20%（低位区间震荡）

    输出趋势名统一为「震荡市·XXXX」（按用户示例）。
    """
    import sys
    _BASE = os.path.dirname(os.path.abspath(__file__))
    if _BASE not in sys.path:
        sys.path.insert(0, _BASE)
    from position_engine import gmma_state, calc_adx

    if not os.path.exists(bk_fp):
        return "震荡市·数据不足", "→", "→", 0.0, 0.0, 0.0, "数据不足", ""
    d = json.load(open(bk_fp, encoding="utf-8"))
    ks = d.get("klines", [])
    if len(ks) < 60:
        return "震荡市·数据不足", "→", "→", 0.0, 0.0, 0.0, "数据不足", ""
    closes = [float(r.split(",")[2]) for r in ks]
    highs = [float(r.split(",")[3]) for r in ks]
    lows = [float(r.split(",")[4]) for r in ks]
    n = len(closes)
    i = n - 1

    # GMMA + ADX + DI（保留作为详情）
    gmma_s, gmma_d = gmma_state(closes, i)
    adx_arr, pdi_arr, mdi_arr = calc_adx(highs, lows, closes, 14)
    adx_val = round(adx_arr[i] or 0, 2)
    pdi_val = round(pdi_arr[i] or 0, 2)
    mdi_val = round(mdi_arr[i] or 0, 2)

    # GMMA 短期/长期组斜率
    shorts = gmma_d.get("shorts", [])
    longs = gmma_d.get("longs", [])
    def _slope(arr):
        if len(arr) < 2: return "→"
        diffs = [arr[k] - arr[k-1] for k in range(1, len(arr))]
        pos = sum(1 for d in diffs if d > 0)
        neg = sum(1 for d in diffs if d < 0)
        if pos == len(diffs): return "↑"
        if neg == len(diffs): return "↓"
        return "→"
    s_slope = _slope(shorts)
    l_slope = _slope(longs)

    gmma_zh = {
        "bullish": "单边多头",
        "bearish": "单边空头",
        "converging_low": "低位收敛",
        "converging_high": "高位收敛",
        "crossed": "缠绕",
    }
    gmma_str = gmma_zh.get(gmma_s, "未知")

    # ---------- 位置状态判定（v4.2） ----------
    last = closes[i]
    h20 = max(highs[-20:])
    l20 = min(lows[-20:])
    pct = (last - l20) / (h20 - l20) if h20 > l20 else 0.5
    # 5 日涨幅
    chg5 = (last / closes[i - 5] - 1) if i >= 5 else 0

    # 优先级判定（v4.2 精细化：高位 85%+ 严格高位，80-85% 视 MA20 方向）
    if pct >= 0.85:
        position = "震荡市·高位横盘"
    elif pct <= 0.2:
        position = "震荡市·低位筑底"
    elif 0.3 <= pct <= 0.7:
        # 中位区间 + MA20 拐头向上 + 5 日反弹 → 中位反弹
        if l_slope == "↑" and chg5 > 0.005:
            position = "震荡市·中位反弹"
        else:
            position = "震荡市·中位横盘"
    elif pct >= 0.8:
        # 80%-85% 边界区：MA20 向上 → 中位反弹（高位但不极端）；否则中位横盘
        if l_slope == "↑" and chg5 > 0.005:
            position = "震荡市·中位反弹"
        else:
            position = "震荡市·中位横盘"
    else:
        # 20%-30% 或 70%-80% 边界区
        if l_slope == "↑" and chg5 > 0.01:
            position = "震荡市·中位反弹"
        else:
            position = "震荡市·中位横盘"

    # MA20 方向（用 l_slope 反映给前端）
    ma20_dir = "向上" if l_slope == "↑" else ("向下" if l_slope == "↓" else "—")

    # 趋势生效起始日：MA5/MA20 关系首次反转
    trend_start = ks[-1].split(",")[0]
    ma5 = sum(closes[-5:]) / 5
    relation = ma5 > sum(closes[-20:]) / 20
    for k in range(i - 1, 19, -1):
        ma5k = sum(closes[k - 4:k + 1]) / 5
        ma20k = sum(closes[k - 19:k + 1]) / 20
        if (ma5k > ma20k) != relation:
            trend_start = ks[k + 1].split(",")[0]
            break

    return position, s_slope, l_slope, adx_val, pdi_val, mdi_val, gmma_str, trend_start

# 4 个赛道（含创新药）按新公式计算综合得分
_BK_FILES = {
    "半导体设备": "bk1326_raw.json",
    "存储芯片": "bk1137_raw.json",
    "光通信模块": "bk1136_raw.json",
    "创新药": "bk1106_raw.json",
}
_track_results = []
for t, bk_fn in _BK_FILES.items():
    bk_fp = os.path.join(DATA, bk_fn)
    (trend, s_slope, l_slope, adx_val, pdi_val, mdi_val,
     gmma_str, trend_start) = _trend_judge(bk_fp)
    if t in _track_scores_raw:
        r = _track_scores_raw[t]
        score = r.get("score", 50)
        tech_v = r.get("tech", 50)
        fund_v = r.get("fundamental", 50)
        news_v = r.get("news", 50)
        proxy_ratio = r.get("fundamental_proxy_ratio", 0.80)
        public_ratio = r.get("fundamental_public_ratio", 0.20)
    else:
        score = tech_v = fund_v = news_v = 50
        proxy_ratio, public_ratio = 0.80, 0.20
    # 涨跌幅备注
    chg_text = ""
    if os.path.exists(bk_fp):
        d = json.load(open(bk_fp, encoding="utf-8"))
        ks = d.get("klines", [])
        if len(ks) >= 2:
            last = ks[-1].split(",")
            prev = ks[-2].split(",")
            chg = (float(last[2]) / float(prev[2]) - 1) * 100
            chg_text = f"{last[0].replace('2026-', '')} {chg:+.2f}%"
    # MA20 方向从 GMMA 长期组斜率推
    ma20_dir = "向上" if l_slope == "↑" else ("向下" if l_slope == "↓" else "—")
    note = f"{chg_text} | 技{tech_v:.1f}/代理基{fund_v:.1f}/消{news_v:.1f} | {trend}·MA20{ma20_dir}"
    by_track.append({
        "name": t,
        "score": round(score, 2),
        "tech": round(tech_v, 1),
        "fundamental": round(fund_v, 1),
        "news": round(news_v, 1),
        "fundamentalProxyRatio": proxy_ratio,
        "fundamentalPublicRatio": public_ratio,
        "trend": trend,
        "trendName": trend,
        "trendStartDate": trend_start,
        "ma20Direction": ma20_dir,
        "gmmaState": gmma_str,
        "gmmaShortSlope": s_slope,
        "gmmaLongSlope": l_slope,
        "adx": adx_val,
        "pdi": pdi_val,
        "mdi": mdi_val,
        "zone": "中性震荡区" if 45 <= score <= 65 else ("强趋势区" if score > 65 else "弱趋势区"),
        "note": note,
        "strengthSort": 0,  # 后面填
    })

# 强度排序（按 score 降序）
sorted_by_score = sorted(by_track, key=lambda x: -x["score"])
for rank, item in enumerate(sorted_by_score, 1):
    item["strengthSort"] = rank

# 总仓位分配：按 score 归一化 + 5% 单位取整 + 合计 100%
# 评分 50 → 5%（最低保底）；每高于 50 累计 +5%
# 评分 70 → 5% + 4*5% = 25%
# 用线性公式：基础 = max(5, (score-40)*1.0)，归一化到 100%，5% 取整
raw_alloc = {}
for item in by_track:
    s = item["score"]
    # 每个赛道基础占比：(score-40)%, 下限 5%
    base = max(5, (s - 40))
    raw_alloc[item["name"]] = base
total_raw = sum(raw_alloc.values())
# 归一化到 100%
norm = {k: v / total_raw * 100 for k, v in raw_alloc.items()}
# 5% 单位取整（标准四舍五入），然后调整使合计 = 100%
alloc = {k: round(v / 5) * 5 for k, v in norm.items()}
# 调整：最后一个补足差额到 100%
total_alloc = sum(alloc.values())
diff_alloc = 100 - total_alloc
if diff_alloc != 0:
    # 找最大 score 的赛道补/减
    biggest = max(alloc, key=alloc.get)
    alloc[biggest] += diff_alloc
# 加到 by_track
for item in by_track:
    item["allocationPct"] = alloc[item["name"]]

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
    # 2026-08-13 修订：暴露技术面子指标原始分（用于前端展示"分指数/分行业综合得分"计算过程）
    "tech": {
        "trackAvg": tech["trackAvg"],
        "wideAvg": tech["wideAvg"],
        "trackScores": tech["trackScores"],
        "wideScores": tech["wideScores"],
    },
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
    "byIndex": [],  # 2026-08-13 修订：删除分宽基指数综合得分（按用户要求）
    "byTrack": by_track,
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
