# -*- coding: utf-8 -*-
"""
趋势为王·结构修边 —— 仓位管理引擎 v3.0
顾比GMMA + ADX + 布林带 + 量价组合 · 双向预警版

规则实现（严格无弹性）：
一、趋势定中枢：顾比均线(多/空/靠拢/回落/缠绕) × ADX强度 → 五类趋势 → 仓位映射表五列
二、强度分级：强/弱上涨（布林+量能）、强/弱下跌，中枢±1档
三、双向预警：高位破位预警（4→3成前置减仓）/ 低位企稳预警（2→3成前置加仓）
四、趋势切换：震荡→单边 连续2日+量能确认T+1 / 单边→震荡 连续3日T+1
五、强制风控 > 预警 > 正式趋势 > 打分微调 > 差额调仓
六、打分体系、仓位映射表、差额调仓、T+1执行、冷却期、初始对齐全部沿用
"""
import os, sys
import json, os, time, math
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

# ---------------- 仓位映射表（打分区间 × 趋势状态，单位：成） ----------------
MAP_TABLE = {
    "极致强底部": {"up": 9, "bottom": 8, "mid": 7, "top": 6, "down": 4},
    "弱底部":     {"up": 9, "bottom": 7, "mid": 6, "top": 5, "down": 3},
    "中性":       {"up": 8, "bottom": 6, "mid": 5, "top": 4, "down": 2},
    "弱顶部":     {"up": 7, "bottom": 5, "mid": 4, "top": 3, "down": 1},
    "极致强顶部": {"up": 6, "bottom": 4, "mid": 3, "top": 2, "down": 1},
}
TREND_NAME = {"up": "单边上涨趋势", "down": "单边下跌趋势", "bottom": "震荡市·低位摸底",
              "mid": "震荡市·中位横盘", "top": "震荡市·高位筑顶",
              "alert_hi": "高位破位预警", "alert_lo": "低位企稳预警"}
TREND_CENTER = {"up": 8, "down": 2, "bottom": 6, "mid": 5, "top": 4, "alert_hi": 3, "alert_lo": 3}

# ============== 指标计算 ==============
def ema_arr(vals, n):
    """EMA 序列。"""
    out = [None] * len(vals)
    k = 2.0 / (n + 1)
    out[0] = vals[0]
    for i in range(1, len(vals)):
        out[i] = vals[i] * k + out[i - 1] * (1 - k)
    return out

def sma_arr(vals, n):
    return [None if i < n - 1 else sum(vals[i - n + 1:i + 1]) / n for i in range(len(vals))]

def calc_adx(highs, lows, closes, period=14):
    """ADX 序列（Wilder平滑）。返回 (adx, plus_di, minus_di)。"""
    n = len(closes)
    tr = [0] * n
    plus_dm = [0] * n
    minus_dm = [0] * n
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if up > down and up > 0 else 0
        minus_dm[i] = down if down > up and down > 0 else 0
    # Wilder 平滑
    def wilder(arr):
        out = [0] * n
        out[period - 1] = sum(arr[:period])
        for i in range(period, n):
            out[i] = out[i - 1] - out[i - 1] / period + arr[i]
        return out
    atr = wilder(tr)
    pdi_raw = wilder(plus_dm)
    mdi_raw = wilder(minus_dm)
    adx, plus_di, minus_di = [None] * n, [None] * n, [None] * n
    for i in range(period * 2, n):
        if atr[i] == 0:
            continue
        pdi = (pdi_raw[i] / atr[i]) * 100
        mdi = (mdi_raw[i] / atr[i]) * 100
        plus_di[i] = pdi
        minus_di[i] = mdi
        dx = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0
        # ADX = Wilder 平滑 of DX
        if i == period * 2:
            adx[i] = dx
        elif adx[i - 1] is not None:
            adx[i] = (adx[i - 1] * (period - 1) + dx) / period
    return adx, plus_di, minus_di

def calc_bollinger(closes, period=20, std_mult=2):
    """布林带：返回 (mid, upper, lower, bandwidth, expanding)。"""
    ma20 = sma_arr(closes, period)
    upper, lower, bw = [None] * len(closes), [None] * len(closes), [None] * len(closes)
    for i in range(period - 1, len(closes)):
        win = closes[i - period + 1:i + 1]
        avg = sum(win) / period
        std = math.sqrt(sum((x - avg) ** 2 for x in win) / period)
        upper[i] = avg + std_mult * std
        lower[i] = avg - std_mult * std
        bw[i] = (upper[i] - lower[i]) / avg  # 带宽
    return ma20, upper, lower, bw

def macd_arr(closes, fast=12, slow=26, signal=9):
    ema_f = ema_arr(closes, fast)
    ema_s = ema_arr(closes, slow)
    dif = [None if ema_f[i] is None or ema_s[i] is None else ema_f[i] - ema_s[i] for i in range(len(closes))]
    dea = [None] * len(closes)
    for i in range(len(closes)):
        if dif[i] is None:
            continue
        if dea[i - 1] is None:
            dea[i] = dif[i]
        else:
            dea[i] = dif[i] * (2.0 / (signal + 1)) + dea[i - 1] * (1 - 2.0 / (signal + 1))
    return dif, dea

# ============== 顾比GMMA状态判定 ==============
SHORT_EMA = [3, 5, 8, 10, 12, 15]
LONG_EMA = [30, 35, 40, 45, 50, 60]

def gmma_state(closes, i):
    """第 i 日的 GMMA 状态。
    返回 (state, detail_dict)，state ∈ ["bullish","bearish","converging_low","converging_high","crossed"]。
    """
    if i < 60:
        return "crossed", {}
    # 计算所有EMA最新值
    shorts = [ema_arr(closes, p)[i] for p in SHORT_EMA]
    longs = [ema_arr(closes, p)[i] for p in LONG_EMA]
    # 前一日值（用于斜率判断）
    shorts_prev = [ema_arr(closes, p)[i - 1] for p in SHORT_EMA]
    longs_prev = [ema_arr(closes, p)[i - 1] for p in LONG_EMA]
    min_short, max_short = min(shorts), max(shorts)
    min_long, max_long = min(longs), max(longs)
    # 判定
    all_short_above = min_short > max_long          # 短期组全部在长期组上方
    all_short_below = max_short < min_long          # 短期组全部在长期组下方
    short_slope_up = all(s > sp for s, sp in zip(shorts, shorts_prev))   # 短期组集体上移
    short_slope_dn = all(s < sp for s, sp in zip(shorts, shorts_prev))   # 短期组集体下移
    long_slope_up = all(l > lp for l, lp in zip(longs, longs_prev))
    long_slope_dn = all(l < lp for l, lp in zip(longs, longs_prev))
    gap_ratio = abs(min_short - max_long) / max_long if max_long > 0 else 0

    if all_short_above and short_slope_up and long_slope_up:
        return "bullish", {"shorts": shorts, "longs": longs, "gap": gap_ratio}
    if all_short_below and short_slope_dn and long_slope_dn:
        return "bearish", {"shorts": shorts, "longs": longs, "gap": gap_ratio}
    # 短期组从下方向长期组靠拢
    short_approaching_up = all_short_below and short_slope_up and not long_slope_up
    # 短期组从上方向长期组回落
    short_approaching_dn = all_short_above and short_slope_dn and not long_slope_dn
    if short_approaching_up:
        return "converging_low", {"shorts": shorts, "longs": longs, "gap": gap_ratio}
    if short_approaching_dn:
        return "converging_high", {"shorts": shorts, "longs": longs, "gap": gap_ratio}
    return "crossed", {"shorts": shorts, "longs": longs, "gap": gap_ratio}

# ============== 综合趋势判定 ==============
def classify_trend(closes, highs, lows, vols, i):
    """第 i 日的五类趋势判定（顾比×ADX 为主，辅以布林+量价）。
    返回 (trend_key, detail_dict)。
    detail_dict 含: gmma/adx_val/pdi/mdi/bb_status/vol_ratio/macd_status 等。
    """
    if i < 60:
        return "mid", {"reason": "数据不足60日", "gmma": "crossed"}
    
    gmma_s, gmma_d = gmma_state(closes, i)
    adx, pdi, mdi = calc_adx(highs, lows, closes, 14)
    adx_val = round(adx[i], 2) if adx[i] is not None else 0
    pdi_val = round(pdi[i], 2) if pdi[i] is not None else 0
    mdi_val = round(mdi[i], 2) if mdi[i] is not None else 0
    ma20, bb_upper, bb_lower, bb_bw = calc_bollinger(closes, 20, 2)
    ma5v = sma_arr(closes, 5)
    c = closes[i]
    bb_mid = round(ma20[i], 2) if ma20[i] else 0
    bb_up = round(bb_upper[i], 2) if bb_upper[i] else 0
    bb_lo = round(bb_lower[i], 2) if bb_lower[i] else 0
    bb_pct = (c - bb_lo) / (bb_up - bb_lo) if (bb_up - bb_lo) > 0 else 0.5  # 0=下轨 1=上轨
    # 布林带宽变化（开口/收口）
    bw_now = bb_bw[i] if bb_bw[i] else 0
    bw_prev = bb_bw[i - 1] if i >= 1 and bb_bw[i - 1] else bw_now
    bb_expanding = bw_now > bw_prev * 1.02
    bb_contracting = bw_now < bw_prev * 0.98
    bb_neutral = not bb_expanding and not bb_contracting
    # 量比（5日标准）：今日成交量 / 前5日均量（不含今日）
    # 与东方财富"量比"口径一致
    vol_ma5_past = sum(vols[max(0, i - 5):i]) / min(5, i) if i > 0 else 0
    vol_ratio = vols[i] / vol_ma5_past if vol_ma5_past > 0 else 1.0
    # MACD
    dif, dea = macd_arr(closes)
    macd_dif = round(dif[i], 2) if dif[i] else 0
    macd_dea = round(dea[i], 2) if dea[i] else 0
    macd_below_zero = macd_dif < 0 and macd_dea < 0
    # 底/顶背离扫描（最近30日简化版）
    div_bottom = False; div_top = False
    if i >= 30:
        recent_c = closes[i - 29:i + 1]
        recent_dif = [dif[k] for k in range(i - 29, i + 1) if dif[k] is not None]
        if len(recent_dif) >= 20:
            lo_c = min(recent_c)
            lo_dif = min(recent_dif)
            if c > lo_c * 1.02 and macd_dif > lo_dif and macd_dif < 0:
                div_bottom = True
            hi_c = max(recent_c)
            hi_dif = max(recent_dif)
            if c < hi_c * 0.98 and macd_dif < hi_dif and macd_dif > 0:
                div_top = True

    # 5日均量（用于量能对照）
    vol_ma5 = sum(vols[max(0, i - 4):i + 1]) / min(5, i + 1)
    vol_ratio_5d = vols[i] / vol_ma5 if vol_ma5 > 0 else 1.0
    # MA乖离率（MA5 vs MA20 + 收盘 vs MA5）
    ma5_i, ma20_i = ma5v[i], ma20[i]
    ma_bias_5_20 = round((ma5_i - ma20_i) / ma20_i * 100, 2) if (ma5_i is not None and ma20_i is not None and ma20_i > 0) else 0
    close_vs_ma5 = round((c - ma5_i) / ma5_i * 100, 2) if (ma5_i is not None and ma5_i > 0) else 0
    # MACD柱状（DIF-DEA）
    macd_hist = round(macd_dif - macd_dea, 3)
    macd_hist_prev = round((dif[i - 1] - dea[i - 1]), 3) if i >= 1 and dif[i - 1] is not None and dea[i - 1] is not None else 0
    macd_bar_expanding = abs(macd_hist) > abs(macd_hist_prev)
    # 趋势强度分级判定
    if gmma_s in ("bullish", "bearish"):
        strength_tier = ("强趋势" if adx_val >= 25 else ("弱趋势" if 20 <= adx_val < 25 else "转弱/转强"))
    else:
        strength_tier = ("强震荡" if adx_val >= 20 else ("中性震荡" if 15 <= adx_val < 20 else "弱化震荡"))
    # GMMA组斜率展开文字
    if gmma_d.get("shorts"):
        s_slope = "↑" if all(s > sp for s, sp in zip(gmma_d["shorts"], [gmma_d["shorts"][0]] + gmma_d["shorts"][:-1])) else ("↓" if all(s < sp for s, sp in zip(gmma_d["shorts"], [gmma_d["shorts"][0]] + gmma_d["shorts"][:-1])) else "→")
        l_slope = "↑" if all(s > sp for s, sp in zip(gmma_d["longs"], [gmma_d["longs"][0]] + gmma_d["longs"][:-1])) else ("↓" if all(s < sp for s, sp in zip(gmma_d["longs"], [gmma_d["longs"][0]] + gmma_d["longs"][:-1])) else "→")
    else:
        s_slope = l_slope = "?"
    bb_state = "开口向上" if bb_expanding and bb_pct > 0.5 else ("开口向下" if bb_expanding and bb_pct < 0.5 else ("收口缩窄" if bb_contracting else "横向整理"))
    bb_pos_text = "上轨附近" if bb_pct > 0.8 else ("中上轨" if bb_pct > 0.5 else ("中下轨" if bb_pct > 0.2 else "下轨附近"))
    detail = {
        "gmma": gmma_s, "gmma_short_slope": s_slope, "gmma_long_slope": l_slope,
        "adx": adx_val, "pdi": pdi_val, "mdi": mdi_val, "strength_tier": strength_tier,
        "bb_mid": bb_mid, "bb_lo": bb_lo, "bb_up": bb_up, "bb_pct": round(bb_pct, 3),
        "bb_expanding": bb_expanding, "bb_contracting": bb_contracting,
        "bb_state": bb_state, "bb_pos_text": bb_pos_text,
        "vol_ratio": round(vol_ratio, 2), "vol_ratio_5d": round(vol_ratio_5d, 2),
        "ma5": round(ma5_i, 2) if ma5_i is not None else None,
        "ma20": round(ma20_i, 2) if ma20_i is not None else None,
        "ma_bias_5_20": ma_bias_5_20, "close_vs_ma5": close_vs_ma5,
        "macd_dif": macd_dif, "macd_dea": macd_dea, "macd_hist": macd_hist, "macd_hist_prev": macd_hist_prev,
        "macd_below_zero": macd_below_zero, "macd_bar_expanding": macd_bar_expanding,
        "div_bottom": div_bottom, "div_top": div_top,
        "gmma_detail": gmma_d,
    }

    # 单边上涨：GMMA多头 + ADX≥20
    if gmma_s == "bullish" and adx_val >= 20:
        detail["strength"] = "strong" if (adx_val >= 25 and bb_expanding and bb_pct > 0.8 and vol_ratio > 1.0) else "weak"
        return "up", detail
    # 单边下跌：GMMA空头 + ADX≥20
    if gmma_s == "bearish" and adx_val >= 20:
        detail["strength"] = "strong" if (adx_val >= 25 and bb_expanding and bb_pct < 0.2) else "weak"
        return "down", detail
    # 低位摸底：短期组向长期组靠拢 + ADX<20
    if gmma_s == "converging_low" and adx_val < 20:
        return "bottom", detail
    # 高位筑顶：短期组向长期组回落 + ADX<20
    if gmma_s == "converging_high" and adx_val < 20:
        return "top", detail
    # 其余 → 中位横盘
    return "mid", detail

# ============== 双向预警 ==============
def alert_check_high(closes, highs, lows, vols, i, detail):
    """高位破位预警：当前趋势=top，满足2条及以上→触发。返回 (triggered, reason)。"""
    if i < 20:
        return False, ""
    ma5v = sma_arr(closes, 5)
    ma20v, bb_upper, bb_lower, _ = calc_bollinger(closes, 20, 2)
    dif, dea = macd_arr(closes)
    c = closes[i]
    hits = []
    # ① MA5死叉MA20
    if ma5v[i] and ma20v[i] and ma5v[i] < ma20v[i] and i >= 1 and ma5v[i - 1] >= ma20v[i - 1]:
        hits.append("① MA5死叉MA20")
    # ② 连续2日收盘价低于布林中轨 + 中轨拐头向下
    if ma20v[i] and ma20v[i - 1] and c < ma20v[i] and closes[i - 1] < ma20v[i - 1] and ma20v[i] < ma20v[i - 1]:
        hits.append("② 连续2日收盘低于布林中轨+中轨拐头向下")
    # ③ 单日跌幅≥3% + 量比≥1.05 + 跌破前一轮回调低点
    chg = (c / closes[i - 1] - 1) if i >= 1 else 0
    vol_ma20 = sum(vols[max(0, i - 20):i]) / min(20, i)
    vol_ratio = vols[i] / vol_ma20 if vol_ma20 > 0 else 1
    if chg <= -0.03 and vol_ratio >= 1.05:
        # 找最近回调低点（近30日内局部最小）
        if i >= 30:
            recent = closes[i - 29:i]
            wave_low = min(recent)
            if c < wave_low:
                hits.append("③ 单日跌幅≥3%%+放量跌破前低")
    # ④ MACD下穿0轴
    if dif[i] is not None and dea[i] is not None and dif[i] < 0 and dea[i] < 0:
        if i >= 1 and dif[i - 1] is not None and (dif[i - 1] >= 0 or dea[i - 1] >= 0):
            hits.append("④ MACD下穿0轴进入空头区域")
    if len(hits) >= 2:
        return True, "; ".join(hits[:3])
    return False, ""

def alert_check_low(closes, highs, lows, vols, i, detail):
    """低位企稳预警：当前趋势=down且ADX≥20(强下跌末端)，满足2条且至少1条量能验证→触发。"""
    if i < 20:
        return False, ""
    ma5v = sma_arr(closes, 5)
    ma20v, bb_upper, bb_lower, _ = calc_bollinger(closes, 20, 2)
    dif, dea = macd_arr(closes)
    c = closes[i]
    hits, vol_hits = [], []
    # ① MA5金叉MA20
    if ma5v[i] and ma20v[i] and ma5v[i] > ma20v[i] and i >= 1 and ma5v[i - 1] <= ma20v[i - 1]:
        hits.append("① MA5金叉MA20")
    # ② 连续2日站上布林下轨 + 收口
    if bb_lower[i] and bb_lower[i - 1] and c > bb_lower[i] and closes[i - 1] > bb_lower[i - 1]:
        bw_now = (bb_upper[i] - bb_lower[i]) / ma20v[i] if ma20v[i] else 0
        bw_prev = (bb_upper[i - 1] - bb_lower[i - 1]) / ma20v[i - 1] if ma20v[i - 1] else 0
        if bw_now < bw_prev:
            hits.append("② 连续2日站上下轨上方+布林收口")
    # ③ 连续3日不创新低 + 反弹日量比≥1.1
    if i >= 3:
        recent3 = closes[i - 2:i + 1]
        before = closes[max(0, i - 30):i - 2]
        if min(recent3) >= min(before) and c > closes[i - 1]:
            vol_ma20 = sum(vols[max(0, i - 20):i]) / min(20, i)
            vol_ratio = vols[i] / vol_ma20 if vol_ma20 > 0 else 1
            if vol_ratio >= 1.1:
                hits.append("③ 连续3日不创新低+反弹放量(量比%.2f)" % vol_ratio)
                vol_hits.append("③")
    # ④ MACD底背离+DIFF拐头向上
    if detail.get("div_bottom") and dif[i] is not None and dif[i - 1] is not None and dif[i] > dif[i - 1]:
        hits.append("④ MACD底背离+DIFF拐头向上")
    if len(hits) >= 2 and len(vol_hits) >= 1:
        return True, "; ".join(hits[:3])
    return False, ""

def alert_cancel_high(closes, i):
    """高位预警撤销：连续3日重新站稳MA20+布林中轨。"""
    if i < 3:
        return False
    ma5v = sma_arr(closes, 5)
    ma20v = sma_arr(closes, 20)
    bb_mid = ma20v  # 布林中轨就是MA20
    for k in range(i - 2, i + 1):
        if not (ma5v[k] and ma20v[k] and closes[k] > ma20v[k]):
            return False
    return True

def alert_cancel_low(closes, lows, highs, i):
    """低位预警撤销：放量跌破前期阶段新低。"""
    if i < 30:
        return False
    prev_low = min(lows[max(0, i - 30):i])
    if closes[i] < prev_low:
        vol_ma20 = sum([highs[k] for k in range(max(0, i - 20), i)]) / min(20, i)  # 简化量比
        return True
    return False

# ============== 趋势生效起始日回测 ==============
def find_trend_start_date(closes, highs, lows, vols, current_i, current_trend, current_detail):
    """从当前日向前回测，找到当前趋势**首次确立**的交易日。
    算法：从 current_i 向前遍历，找到"当前 trend 连续成立"的最早一天。
    关键：从 i 向前找，直到出现 trend != current_trend 的那一天；
          当前趋势生效起始日 = (那一天 + 1)。
    返回 (start_date, start_idx)。若数据不足则返回 (None, current_i)。
    """
    if current_i < 60:
        return None, current_i
    bars_obj = json.load(open(os.path.join(DATA, "kc50_full.json"), encoding="utf-8"))["data"]["sh000688"]
    day_arr = bars_obj.get("day") or bars_obj.get("qfqday")
    # 向前找第一个 trend != current_trend 的索引
    search_range = min(current_i + 1, 60)
    for j in range(current_i, current_i - search_range, -1):
        if j < 60:
            break
        try:
            tj, _ = classify_trend(closes, highs, lows, vols, j)
        except Exception:
            continue
        if tj != current_trend:
            # 趋势变更点：j 是最后一天 != current_trend
            # 趋势生效起始日 = j + 1
            start_idx = j + 1
            if start_idx <= current_i and start_idx < len(day_arr):
                return day_arr[start_idx][0], start_idx
            else:
                break
    return None, current_i

# ============== 分赛道调仓建议 ==============
def build_track_recommendations(track_scores, news_items, flow_summary, action, target_diff,
                                 tech_tracks=None, extras_by_track=None):
    """按3个核心赛道输出调仓优先级/方向/比例建议。
    综合：
      - track_scores: 各赛道综合得分（来自 byTrack）
      - tech_tracks: 各赛道当前技术面状态（趋势方向/强弱）
      - extras_by_track: 各赛道归属的额外加减分项（已按 track 分组）
      - action/target_diff: 总体操作指令（差额调整法）
    返回：{primary, secondary, hold} 都是对象数组（含 track, score, amount, action, logic）
    关键：金额与总调仓指令联动 - 总差额 N 成时按 6:4 比例分配到 primary/secondary
    """
    if not track_scores:
        return {"primary": None, "secondary": None, "hold": []}

    def _build_logic(track, score):
        """生成单个赛道的明确 logic（4 个维度都有标签）"""
        # 信号1：技术面趋势
        trend = (tech_tracks or {}).get(track, "neutral")
        trend_desc = {"up": "强势上涨", "down": "弱势下跌",
                       "bottom": "低位摸底", "top": "高位筑顶",
                       "mid": "中性震荡"}.get(trend, "中性震荡")
        # 信号2：综合分位
        if score >= 80:
            score_desc = "极强区"
        elif score >= 65:
            score_desc = "强势区"
        elif score >= 55:
            score_desc = "中性偏强"
        elif score >= 45:
            score_desc = "中性震荡"
        elif score >= 35:
            score_desc = "偏弱区"
        else:
            score_desc = "极弱区"
        # 信号3：消息面加减分项
        track_extras = (extras_by_track or {}).get(track, [])
        ex_plus = sum(x["points"] for x in track_extras if x["points"] > 0)
        ex_minus = sum(x["points"] for x in track_extras if x["points"] < 0)
        if ex_plus > 0 and ex_minus == 0:
            ex_desc = f"+{ex_plus}分催化"
        elif ex_minus < 0 and ex_plus == 0:
            ex_desc = f"{ex_minus}分压制"
        elif ex_plus > 0 and ex_minus < 0:
            ex_desc = f"+{ex_plus}/-{abs(ex_minus)}分双向"
        else:
            ex_desc = "无显著边际"
        return trend_desc, score_desc, ex_desc

    def _recommend_action(track, score):
        """基于三维信号给单个赛道独立建议"""
        trend = (tech_tracks or {}).get(track, "neutral")
        track_extras = (extras_by_track or {}).get(track, [])
        ex_plus = sum(x["points"] for x in track_extras if x["points"] > 0)
        ex_minus = sum(x["points"] for x in track_extras if x["points"] < 0)
        if score >= 65 and (ex_plus > 0 or trend in ("up", "bottom")):
            return "加仓"
        if score <= 40 and (ex_minus < 0 or trend in ("top", "down")):
            return "减仓"
        return "维持"

    # 不管 action 是什么，按 6:4 分配金额到 primary/secondary（按 score 高低）
    # 金额方向跟 target_diff 一致（diff>0 加仓 / diff<0 减仓）；action="不动" 时仍按差额方向输出理想金额
    # 2026-08-12 修订：分数相同时需要确定性 tie-breaker（避免依赖 dict 插入顺序导致优先级任意）
    abs_diff = abs(target_diff)
    trend_strength = {"down": 0, "top": 1, "mid": 2, "bottom": 3, "up": 4}  # 越弱越靠前（减仓优先）
    def _tie_key(track_score, reverse=False):
        """分数相同时的二级排序键：技术面越弱→减仓越先；技术面越强→加仓越先"""
        track_name, score = track_score
        tech_trend = (tech_tracks or {}).get(track_name, "neutral")
        ts = trend_strength.get(tech_trend, 2)
        return (score, ts if not reverse else 4 - ts)
    # 2026-08-12 修订：检测分数完全相等的情况（三赛道同时段都为同一档位）
    score_vals = list(track_scores.values())
    all_tied = len(set(round(s, 2) for s in score_vals)) == 1 and len(track_scores) >= 2
    if target_diff > 0:
        # 加仓场景：分高的优先加；分数相同时技术面强的优先加
        tracks_sorted = sorted(track_scores.items(), key=lambda x: _tie_key(x, reverse=True))
        op_name = "加仓"
    elif target_diff < 0:
        # 减仓场景：分低的优先减；分数相同时技术面弱的优先减
        tracks_sorted = sorted(track_scores.items(), key=lambda x: _tie_key(x, reverse=False))
        op_name = "减仓"
    else:
        # diff=0：所有赛道维持
        tracks_sorted = [(t, 0) for t in track_scores.keys()]
        op_name = "维持"
    # 2026-08-12 修订：分数完全相等时等额分配，避免 primary/secondary/hold 任意分配误导决策
    equal_split = all_tied and abs_diff >= 0.5
    if equal_split:
        per_track = round(abs_diff / len(tracks_sorted), 1)
        tracks_sorted = [(t, per_track) for t, _ in tracks_sorted]
        # 等额场景下，重新指定 primary/secondary/hold：按赛道名字典序标记
        # 逻辑上无可区分，但保留结构让前端展示"等额分配"
        p_track = tracks_sorted[0][0]
        s_track = tracks_sorted[1][0] if len(tracks_sorted) >= 2 else None
        h_tracks = [t[0] for t in tracks_sorted[2:]]
    else:
        p_track = tracks_sorted[0][0] if len(tracks_sorted) >= 1 else None
        s_track = tracks_sorted[1][0] if len(tracks_sorted) >= 2 else None
        h_tracks = [t[0] for t in tracks_sorted[2:]]

    # 金额分配（6:4:0；分数完全相等时三赛道等额）
    if equal_split:
        # 2026-08-12 修订：分数完全相等时，三个赛道各分 1/3（primary/secondary/hold 都参与）
        each = round(abs_diff / 3, 1)
        p_amt = s_amt = h_amt = each
        amount_note = "（三赛道分数完全相等，等额分配各" + str(each) + "成）"
    elif abs_diff < 0.5:
        # 差额过小，所有金额 0；保留为"暂不调整"
        p_amt = s_amt = h_amt = 0
        amount_note = "（总差额<0.5成，按规则不动）"
    else:
        p_amt = round(abs_diff * 0.6, 1)
        s_amt = round(abs_diff * 0.4, 1)
        h_amt = 0
        amount_note = ""

    def _make_obj(track, amt, sub_action, slot_label):
        """生成单个赛道对象（含 logic 4 维度）"""
        trend_desc, score_desc, ex_desc = _build_logic(track, track_scores[track])
        # logic 4 维度明确标签：技术面｜综合分位｜消息面｜建议
        # 2026-08-12 修订：等额分配场景下，等额赛道显示"等额分配"而非"维持"
        if amt > 0:
            if equal_split:
                logic = f"技术面：{trend_desc} ｜ 综合分位：{score_desc} ｜ 消息面：{ex_desc} ｜ {slot_label}{op_name}{amt}成"
            else:
                logic = f"技术面：{trend_desc} ｜ 综合分位：{score_desc} ｜ 消息面：{ex_desc} ｜ {slot_label}{sub_action}{amt}成"
        else:
            logic = f"技术面：{trend_desc} ｜ 综合分位：{score_desc} ｜ 消息面：{ex_desc} ｜ {slot_label}维持当前配置"
        return {
            "track": track, "score": track_scores[track],
            "amount": amt, "action": sub_action,
            "slot": slot_label,
            "logic": logic,
        }

    out = {
        "primary": _make_obj(p_track, p_amt, op_name,
                              ("【等额】" if equal_split else "【优先" + op_name + "】")) if p_track else None,
        "secondary": _make_obj(s_track, s_amt, op_name,
                                ("【等额】" if equal_split else "【次选" + op_name + "】")) if s_track else None,
        "hold": [_make_obj(t, h_amt, "维持" if not equal_split else op_name, "【等额】" if equal_split else "【维持】") for t in h_tracks],
    }
    return out

# ============== 主流程 ==============
def load_kc50():
    d = json.load(open(os.path.join(DATA, "kc50_full.json"), encoding="utf-8"))["data"]["sh000688"]
    day = d.get("day") or d.get("qfqday")
    return [{"date": r[0], "open": float(r[1]), "close": float(r[2]),
             "high": float(r[3]), "low": float(r[4]), "vol": float(r[5])} for r in day]

def main():
    bars = load_kc50()
    closes, highs, lows, vols = [b["close"] for b in bars], [b["high"] for b in bars], [b["low"] for b in bars], [b["vol"] for b in bars]
    n = len(closes)
    i = n - 1
    today = bars[i]["date"]
    ma5v, ma20v = sma_arr(closes, 5), sma_arr(closes, 20)

    score = json.load(open(os.path.join(DATA, "score_result.json"), encoding="utf-8"))
    comp = score["composite"]

    # 趋势判定
    trend_today, detail_today = classify_trend(closes, highs, lows, vols, i)
    trend_prev, detail_prev = classify_trend(closes, highs, lows, vols, i - 1) if i >= 60 else (None, {})
    # 连续确认
    same2d = trend_today == trend_prev
    up_confirmed = trend_today == "up" and trend_prev == "up"
    down_confirmed = trend_today == "down" and trend_prev == "down"
    # 震荡→单边 连续2日 + 量能确认
    osc_to_trend = same2d and trend_today in ("up", "down") and detail_today.get("vol_ratio", 1) > 0.9
    # 单边→震荡 连续3日
    if i >= 62:
        trend3 = [classify_trend(closes, highs, lows, vols, k)[0] for k in range(i - 2, i + 1)]
        trend_to_osc = all(t not in ("up", "down") for t in trend3) and trend_prev in ("up", "down")
    else:
        trend_to_osc = False

    # ---------------- 状态机 ----------------
    # 2026-08-10 修订：增加 user_acked 机制——用户没点"已按指令执行"时，current_position 维持不变
    sf = os.path.join(DATA, "position_state.json")
    state = json.load(open(sf, encoding="utf-8")) if os.path.exists(sf) else {
        "current_position": 8.0, "prev_trend": None, "trend_since": None,
        "last_zone": None, "last_stage": None, "alert_state": None,
        "last_adjust": None, "align_phase": 0, "align_start": None,
        "observe_start_idx": None, "fuse_triggered": None,
        "user_acked": True,  # 默认已确认（向后兼容）
        "pending_action": None,  # 待用户确认的建议 {date, action, amount, target}
        "history": []}
    # 兼容旧 state：补字段
    if "user_acked" not in state:
        state["user_acked"] = True
    if "pending_action" not in state:
        state["pending_action"] = None

    prev_trend_s = state["prev_trend"]  # 上一期最终趋势（含预警）
    prev_alert = state.get("alert_state")  # 上次预警状态

    # --- 预警判定 ---
    alert_active = None
    alert_reason = ""
    # 高位破位预警
    if trend_today in ("top", "mid") and detail_today.get("gmma") in ("converging_high", "crossed"):
        trig, reason = alert_check_high(closes, highs, lows, vols, i, detail_today)
        if trig:
            alert_active = "alert_hi"
            alert_reason = reason
    # 低位企稳预警
    if trend_today == "down" and detail_today.get("adx", 0) >= 20:
        trig, reason = alert_check_low(closes, highs, lows, vols, i, detail_today)
        if trig:
            alert_active = "alert_lo"
            alert_reason = reason
    # 预警撤销
    if prev_alert == "alert_hi" and alert_cancel_high(closes, i):
        alert_active = None; alert_reason = "撤销预警：连续3日站稳MA20+布林中轨"
    if prev_alert == "alert_lo" and alert_cancel_low(closes, lows, highs, i):
        alert_active = None; alert_reason = "撤销预警：放量跌破前期阶段新低，重回单边下跌"

    if prev_alert and not alert_active:
        state["alert_state"] = None

    # --- 正式趋势 ---
    if prev_trend_s is None:  # 启动首日
        if up_confirmed: trend = "up"
        elif down_confirmed: trend = "down"
        else: trend = trend_today if trend_today in ("bottom", "mid", "top") else "mid"
        first_day = True
    elif prev_trend_s in ("up", "down"):  # 单边→
        trend = trend_today if trend_to_osc else prev_trend_s
        first_day = False
    else:  # 震荡→
        if osc_to_trend: trend = trend_today
        else: trend = trend_today if trend_today in ("bottom", "mid", "top") else prev_trend_s
        first_day = False

    # 趋势生效起始日回测
    trend_start_date, trend_start_idx = find_trend_start_date(closes, highs, lows, vols, i, trend, detail_today)
    trend_confirm_date = today

    # 趋势变更高亮标记
    change_markers = []
    if prev_trend_s and prev_trend_s != trend:
        from_prev_map = {"up": "单边上涨", "down": "单边下跌",
                         "bottom": "低位摸底震荡", "mid": "中位横盘震荡",
                         "top": "高位筑顶震荡"}
        change_markers.append({
            "type": "trend",
            "label": "【趋势变更】",
            "text": f"{from_prev_map.get(prev_trend_s, prev_trend_s)} → {TREND_NAME.get(trend, trend)}",
            "color": "#e53935",
            "from": prev_trend_s, "to": trend
        })

    # 趋势持久化标注（初始判定 + 所有变更，跨运行累积，永不删除）
    # 2026-08-12 修订：图上需保留所有出现过的趋势判定/变更标注
    trend_judgments = state.get("trend_judgments", [])
    if not prev_trend_s and not trend_judgments:
        # 首次运行：记录初始趋势判定
        trend_judgments.append({
            "type": "judgment",
            "date": trend_start_date or today,
            "label": "【趋势初始判定】",
            "text": f"初始判定：{TREND_NAME.get(trend, trend)}",
            "color": "#00897b",  # 青色，区别于变更标注
            "to": trend
        })
    if prev_trend_s and prev_trend_s != trend:
        # 新增变更标注（去重：同一日期同类型不重复）
        existing_dates = {m.get("date") for m in trend_judgments if m.get("type") == "trend"}
        if today not in existing_dates:
            trend_judgments.append({
                "type": "trend",
                "date": today,
                "label": "【趋势变更】",
                "text": f"{TREND_NAME.get(prev_trend_s, prev_trend_s)} → {TREND_NAME.get(trend, trend)}",
                "color": "#e53935",
                "from": prev_trend_s,
                "to": trend
            })
    # 同时记录当前趋势生效起始日标注
    if trend_start_date and trend_start_date != today:
        existing = {m.get("date") for m in trend_judgments if m.get("type") == "active"}
        if trend_start_date not in existing:
            trend_judgments.append({
                "type": "active",
                "date": trend_start_date,
                "label": f"【{TREND_NAME.get(trend, trend)}生效】",
                "text": f"{TREND_NAME.get(trend, trend)}生效起始",
                "color": "#ff9800",
                "to": trend
            })
    state["trend_judgments"] = trend_judgments
    # 趋势确认日期与理由（与上次prev_trend对比）
    trend_since = state.get("trend_since") or today
    trend_reason = ""
    if prev_trend_s is None or prev_trend_s != trend:
        trend_since = today
        # 构造判定理由
        if trend == "up":
            trend_reason = "GMMA单边多头+ADX≥20（%.1f）｜%s" % (detail_today["adx"],
                "ADX≥25且布林开口向上，强趋势" if detail_today.get("strength") == "strong" else "趋势延续")
        elif trend == "down":
            trend_reason = "GMMA单边空头+ADX≥20（%.1f）｜%s" % (detail_today["adx"],
                "ADX≥25且布林开口向下，强趋势" if detail_today.get("strength") == "strong" else "趋势延续")
        elif trend == "bottom":
            trend_reason = "GMMA短期组从下方靠拢长期组+ADX＜20（%.1f）｜低位磨底博弈，无明确趋势" % detail_today["adx"]
        elif trend == "top":
            trend_reason = "GMMA短期组从上方回落长期组+ADX＜20（%.1f）｜高位博弈，无明确趋势" % detail_today["adx"]
        else:
            trend_reason = "GMMA交叉缠绕+ADX＜20（%.1f）｜方向不明，震荡格局" % detail_today["adx"]

    # 全量技术指标详情（v2.1 输出规范：GMMA/ADX/BOLL/MA5MA20/MACD/量比分级+位置定性）
    d_today = detail_today
    # 量比分级（结合收盘价与布林轨位分位做位置定性）
    vol_ratio = d_today.get("vol_ratio", 0)
    vol_tier = "放量" if vol_ratio >= 1.2 else ("缩量" if vol_ratio < 0.8 else "正常")
    bb_pct_v = d_today.get("bb_pct", 0.5)
    # v2.1: 位置判定优先级 - 大趋势结构优先于布林分位
    gmma_raw = d_today.get("gmma", "?")
    ma5_v = d_today.get("ma5", 0); ma20_v = d_today.get("ma20", 0)
    ma5_gt_ma20 = (ma5_v > ma20_v) if (ma5_v and ma20_v) else None
    # 低位判定：① MA5<MA20 + GMMA低位收敛 = 下跌后磨底；② 布林分位<33%
    is_low = ((ma5_gt_ma20 is False and gmma_raw == "converging_low") or bb_pct_v < 0.33)
    # 高位判定：① MA5>MA20 + GMMA高位收敛 = 上涨后筑顶；② 布林分位>66%
    is_high = ((ma5_gt_ma20 is True and gmma_raw == "converging_high") or bb_pct_v > 0.66)
    # 中位判定：必须同时满足 MA5/MA20反复交叉+GMMA缠绕 + 布林分位33%-66%
    if is_low: pos_tier = "低位"
    elif is_high: pos_tier = "高位"
    elif bb_pct_v >= 0.33 and bb_pct_v <= 0.66 and gmma_raw == "crossed": pos_tier = "中位"
    else: pos_tier = "中位"  # 默认中位
    # v2.1: 量能+位置 组合定性（6 种，强制三层：位置+量能+多空含义）
    if vol_ratio < 0.8 and pos_tier == "低位":
        vol_pos_desc = "低位缩量整理，抛压逐步衰竭，磨底特征（偏多信号）"
    elif vol_ratio >= 1.2 and pos_tier == "低位":
        vol_pos_desc = "低位放量启动，资金进场（偏多信号）"
    elif vol_ratio < 0.8 and pos_tier == "中位":
        vol_pos_desc = "中位缩量，交投清淡，方向不明（中性）"
    elif vol_ratio >= 1.2 and pos_tier == "中位":
        vol_pos_desc = "中位放量，临近方向选择（中性）"
    elif vol_ratio < 0.8 and pos_tier == "高位":
        vol_pos_desc = "高位缩量，买盘不足，上涨动能衰减（偏空信号）"
    elif vol_ratio >= 1.2 and pos_tier == "高位":
        vol_pos_desc = "高位放量分歧，出货风险（偏空信号）"
    else:
        vol_pos_desc = "量能中性"
    macd_dif_v = d_today.get("macd_dif", 0)
    macd_dea_v = d_today.get("macd_dea", 0)
    macd_zero = "上方" if not d_today.get("macd_below_zero") else "下方"
    macd_cross_state = "金叉" if macd_dif_v > macd_dea_v else ("死叉" if macd_dif_v < macd_dea_v else "粘合")
    macd_div_text = ("底背离" if d_today.get("div_bottom") else "") + ("顶背离" if d_today.get("div_top") else "") or "无"
    # GMMA状态中文映射
    gmma_cn = {"bullish": "单边多头", "bearish": "单边空头",
               "converging_low": "低位收敛", "converging_high": "高位收敛",
               "crossed": "缠绕"}.get(gmma_raw, gmma_raw)
    # v2.1: 趋势强度分级强制校准（GMMA状态+ADX数值 双因子匹配）
    adx_v = d_today.get("adx", 0)
    pdi_v = d_today.get("pdi", 0); mdi_v = d_today.get("mdi", 0)
    side_pref = ("多方占优" if pdi_v > mdi_v else "空方占优")
    if gmma_raw in ("bullish", "bearish"):
        # GMMA单边 + ADX
        if adx_v >= 25:
            strength_tier_v = "强趋势"
        elif adx_v >= 20:
            strength_tier_v = "弱趋势"
        else:
            strength_tier_v = "弱趋势（ADX偏低）"
    else:
        # GMMA 收敛/缠绕 - 不能用"强趋势"
        if adx_v >= 20:
            strength_tier_v = f"弱震荡，{side_pref}"
        elif adx_v >= 15:
            strength_tier_v = f"中性震荡，{side_pref}"
        else:
            strength_tier_v = f"极弱震荡，{side_pref}"
    # MA5/MA20分层
    ma5_gt_ma20_b = ma5_v > ma20_v if (ma5_v and ma20_v) else None
    ma_mid_term = "MA5在MA20上方，中期多头结构" if ma5_gt_ma20_b else ("MA5在MA20下方，中期空头结构" if ma5_gt_ma20_b is False else "未知")
    close_vs_ma5_v = d_today.get("close_vs_ma5", 0)
    ma_short_term = "站上MA5，短期反弹" if close_vs_ma5_v > 0 else ("跌破MA5，短期回落" if close_vs_ma5_v < 0 else "持平MA5")
    # v2.1: 整体趋势结论（先定大方向，再定当前阶段）
    # 中期空头 + 低位收敛 → 下跌趋势中，低位震荡磨底
    # 中期多头 + 高位收敛 → 上涨趋势中，高位震荡筑顶
    # 缠绕+布林走平 → 震荡市，中位横盘
    if ma5_gt_ma20_b is False and gmma_raw == "converging_low":
        overall_phase = "下跌趋势中，低位震荡磨底"
    elif ma5_gt_ma20_b is True and gmma_raw == "converging_high":
        overall_phase = "上涨趋势中，高位震荡筑顶"
    elif gmma_raw == "crossed":
        overall_phase = "震荡市，中位横盘"
    else:
        overall_phase = "中期空头+结构收敛" if ma5_gt_ma20_b is False else "震荡"
    # v2.1: 布林带状态补充含义
    bb_state_v = d_today.get("bb_state", "")
    bb_state_meaning = {
        "收口缩窄": "波动收窄，临近方向选择",
        "开口向上": "趋势加速向上",
        "开口向下": "趋势加速向下",
        "横向整理": "震荡格局，无明确趋势",
    }.get(bb_state_v, "")
    # 5日均量比含义（强制校验清单 #5：连续3日≥1.2=趋势确认）
    vol_5d_v = d_today.get("vol_ratio_5d", 0)
    vol_5d_desc = ("连续3日≥1.2=趋势确认" if vol_5d_v >= 1.2 else
                   "未持续放量，趋势未确认" if vol_5d_v >= 0.8 else
                   "持续缩量，观望气氛浓")
    indicator_detail = {
        "core": [
            {"name":"GMMA短期组斜率","value":d_today.get("gmma_short_slope","?"),
             "showVals":[round(v,2) for v in d_today.get("gmma_detail",{}).get("shorts",[])],
             "rule":"↑=短期资金流入；↓=短期资金流出；→=持平"},
            {"name":"GMMA长期组斜率","value":d_today.get("gmma_long_slope","?"),
             "showVals":[round(v,2) for v in d_today.get("gmma_detail",{}).get("longs",[])],
             "rule":"↑=主线趋势向上；↓=主线趋势向下；→=持平"},
            {"name":"GMMA整体状态","value":gmma_cn+(" ["+gmma_raw+"]" if gmma_raw!="?" else ""),
             "rule":"单边多头=上涨趋势明确｜单边空头=下跌趋势明确｜低位收敛=下跌动能衰竭磨底｜高位收敛=上涨动能衰减博弈｜缠绕=震荡"},
            {"name":"ADX","value":round(d_today.get("adx",0),2),
             "rule":"GMMA单边+ADX≥25=强趋势｜GMMA单边+ADX 20-25=弱趋势｜GMMA收敛/缠绕+ADX 20-25=弱震荡｜GMMA收敛/缠绕+ADX 15-20=中性震荡｜GMMA收敛/缠绕+ADX<15=极弱震荡"},
            {"name":"+DI/-DI方向","value":"%s/%s（%s）"%(round(pdi_v,2), round(mdi_v,2), side_pref),
             "rule":"+DI＞-DI=多方占优；-DI＞+DI=空方占优"},
            {"name":"趋势强度分级","value":strength_tier_v,
             "rule":"GMMA单边+ADX≥25=强趋势；GMMA单边+ADX 20-25=弱趋势；GMMA非单边→统一震荡定级（弱震荡/中性震荡/极弱震荡），严禁「强」字"},
            {"name":"整体趋势结论","value":overall_phase,
             "rule":"中期空头+低位收敛=下跌趋势中低位震荡磨底｜中期多头+高位收敛=上涨趋势中高位震荡筑顶｜缠绕=震荡市中位横盘"},
        ],
        "aux": [
            {"name":"布林上轨/中轨/下轨","value":"%s/%s/%s"%(d_today.get("bb_up",0), d_today.get("bb_mid",0), d_today.get("bb_lo",0)),
             "rule": "轨位%.0f%%（%s）｜%s｜%s" % (bb_pct_v*100, pos_tier, bb_state_v, bb_state_meaning)},
            {"name":"MA5/MA20 中期结构","value":"%s/%s"%(ma5_v, ma20_v),
             "rule": ma_mid_term},
            {"name":"MA5 短期变化","value":"%+.2f%%" % close_vs_ma5_v,
             "rule": ma_short_term},
            {"name":"MACD DIF/DEA","value":"%s/%s"%(macd_dif_v, macd_dea_v),
             "rule":"%s｜零轴%s｜%s%s"%(macd_cross_state, macd_zero,
                "零轴下金叉=弱势反弹" if (macd_cross_state=="金叉" and macd_zero=="下方") else
                "零轴上金叉=强势多头" if (macd_cross_state=="金叉" and macd_zero=="上方") else
                "","，%s" % macd_div_text if macd_div_text!="无" else "")},
            {"name":"当日量比","value":d_today.get("vol_ratio",0),
             "rule": "≥1.2放量｜0.8-1.2正常｜<0.8缩量｜%s｜位置判定（结构优先：%s）" % (vol_tier, vol_pos_desc)},
            {"name":"5日均量比","value":vol_5d_v,
             "rule":"%s｜%s" % (vol_5d_desc, "与当日量比互证")},
        ],
    }

    # 预警优先覆盖正式趋势（执行优先级第二，仅次于强制风控）
    effective_trend = alert_active if alert_active else trend
    if alert_active:
        state["alert_state"] = alert_active

    # ADX强度分级修正中枢
    center = TREND_CENTER[effective_trend]
    if effective_trend == "up":
        if detail_today.get("strength") == "weak":
            center = 7  # 弱上涨→中枢7成
    elif effective_trend == "down":
        if detail_today.get("strength") == "weak":
            center = 3  # 弱下跌→中枢3成

    # ---------------- 打分区间 ----------------
    if comp <= 30: zone = "极致强顶部"
    elif comp <= 45: zone = "弱顶部"
    elif comp <= 65: zone = "中性"
    elif comp <= 80: zone = "弱底部"
    else: zone = "极致强底部"

    if state.get("last_zone") and state.get("last_zone") != zone:
        change_markers.append({
            "type": "zone",
            "label": "【档位变更】",
            "text": f"{state['last_zone']} → {zone}",
            "color": "#f57c00",
            "from": state["last_zone"], "to": zone
        })

    target = MAP_TABLE[zone].get(effective_trend, MAP_TABLE[zone]["mid"])
    target = max(1, min(9, target))
    current = state["current_position"]
    diff = round(target - current, 1)

    trend_changed = (effective_trend != prev_trend_s) if prev_trend_s else True
    stage_changed = (effective_trend in ("bottom", "mid", "top")) and (state.get("last_stage") is not None) and (effective_trend != state["last_stage"])
    zone_changed = (state.get("last_zone") is not None) and (zone != state["last_zone"])

    in_cooldown = False
    if state.get("last_adjust") and not trend_changed:
        last_dt = datetime.strptime(state["last_adjust"]["date"], "%Y-%m-%d")
        direction_same = (diff > 0) == (state["last_adjust"]["amount"] > 0)
        if direction_same and (datetime.strptime(today, "%Y-%m-%d") - last_dt).days < 7:
            in_cooldown = True

    # ---------------- 初始对齐（保留） ----------------
    action, exec_amount, note = "不动", 0.0, ""
    align_phase = state.get("align_phase", 0)
    fuse_hit = None

    if align_phase in (0, 1):
        golden_cross = ma5v[i] is not None and ma20v[i] is not None and ma5v[i] > ma20v[i] and i >= 1 and ma5v[i - 1] <= ma20v[i - 1]
        chg_today = closes[i] / closes[i - 1] - 1 if i >= 1 else 0
        vol_ma20_s = sum(vols[max(0, i - 20):i]) / min(20, i)
        vol_burst = chg_today >= 0.03 and vols[i] > vol_ma20_s * 1.2
        if golden_cross: fuse_hit = "科创50 MA5上穿MA20（金叉）"
        elif vol_burst: fuse_hit = "单日涨幅%.2f%%≥3%%且放量" % (chg_today * 100)
        elif comp > 80: fuse_hit = "综合得分%.1f突破80分" % comp

    if align_phase == 0:
        if abs(diff) < 0.5: action, note, state["align_phase"] = "不动", "差额不足0.5成，直接完成对齐", 2
        elif abs(diff) <= 2: action, exec_amount, note, state["align_phase"] = ("加仓" if diff > 0 else "减仓"), diff, "差额%.1f成≤2成，首日一次性对齐" % abs(diff), 2
        else:
            half = max(-2.0, min(2.0, round(diff / 2, 1)))
            action, exec_amount = ("加仓" if half > 0 else "减仓"), half
            note = "首日半额调仓（差额%.1f成→执行%.1f成），5日观察期" % (diff, half)
            state["align_phase"], state["align_start"], state["observe_start_idx"] = 1, today, i
    elif align_phase == 1:
        obs_days = i - state.get("observe_start_idx", i)
        if fuse_hit and diff < 0:
            action, exec_amount, note, state["align_phase"] = "不动", 0.0, "熔断：%s——停止减仓" % fuse_hit, 2
            state["fuse_triggered"] = fuse_hit
        elif obs_days >= 5:
            if abs(diff) < 0.5: action, note = "不动", "剩余差额不足0.5成，对齐完成"
            else: action, exec_amount, note = ("加仓" if diff > 0 else "减仓"), max(-2.0, min(2.0, diff)), "观察期满，执行剩余%.1f成" % exec_amount
            state["align_phase"] = 2
        else:
            action, note = "不动", "观察期第%d/5日" % obs_days
    else:
        if abs(diff) < 0.5: action, note = "不动", "差额%.1f成＜0.5成不操作" % abs(diff)
        elif not (trend_changed or stage_changed or zone_changed): action, note = "不动", "同区间波动不重复调仓"
        elif in_cooldown: action, note = "不动", "同向冷却期（%s）" % state["last_adjust"]["date"]
        else:
            action = "加仓" if diff > 0 else "减仓"
            exec_amount = diff
            prio = "一级趋势切换" if trend_changed else ("子阶段切换" if stage_changed else "打分档位")
            note = "%s | %s" % (prio, ("预警触发：%s" % alert_reason) if alert_active else "")

    # ---------------- 写回状态 ----------------
    # 重要：始终写回元数据（趋势确认日期/理由/对齐阶段），仅在非盘中观察期内执行仓位变更
    # 2026-08-10 修订：增加 user_acked 机制——仓位变更必须由用户明确确认
    now_hm = time.strftime("%H:%M")
    is_intraday = now_hm < "15:00"
    write_full = not (is_intraday and align_phase != 0)  # 观察期内盘中：只更新元数据，不改仓位

    # 检查是否有用户确认要执行之前pending的动作
    pending = state.get("pending_action")
    if pending and pending.get("date") == today and state.get("user_acked"):
        # 用户确认了pending动作，执行之
        exec_amount = pending["amount"]
        action = pending["action"]
        target = pending.get("target", target)
        state["pending_action"] = None
        state["user_acked"] = False  # 重置回False（下一轮需重新确认）

    if write_full or not is_intraday:
        # 记录本次建议到pending（等待用户确认）
        if exec_amount != 0 and action != "不动" and not (is_intraday and align_phase != 0):
            state["pending_action"] = {"date": today, "action": action, "amount": exec_amount, "target": target}
            # 重要：current_position 仅在用户确认后才更新；用户未确认时保持不变
            if state.get("user_acked"):
                state["current_position"] = round(current + exec_amount, 1)
                state["last_adjust"] = {"date": today, "amount": exec_amount, "target": target}
                state["pending_action"] = None  # 已执行
        state["prev_trend"] = effective_trend
        state["trend_since"] = trend_since
        state["trend_reason"] = trend_reason
        state["last_zone"] = zone
        state["last_stage"] = effective_trend if effective_trend in ("bottom", "mid", "top") else state.get("last_stage")
        state["trend_start_date"] = trend_start_date
        state["trend_confirm_date"] = trend_confirm_date
        state["change_markers"] = change_markers
        state["history"].append({"date": today, "trend": effective_trend, "zone": zone, "score": comp,
                                 "target": target, "action": action, "amount": exec_amount,
                                 "acked": state.get("user_acked", True)})
        state["history"] = state["history"][-120:]
        json.dump(state, open(sf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---------------- 分赛道调仓建议 ----------------
    _track_scores = {}
    _extras_by_track = {}
    _tech_tracks = {}
    try:
        _sr = json.load(open(os.path.join(DATA, "score_result.json"), encoding="utf-8"))
        _track_scores = _sr.get("tech", {}).get("trackScores", {})
        # 按赛道分组 extras
        for ex in _sr.get("extras", {}).get("items", []):
            tk = ex.get("track", "其他")
            _extras_by_track.setdefault(tk, []).append(ex)
        # 读取技术面趋势（来自 tech.trackDetail 的子指标）
        track_detail = _sr.get("tech", {}).get("trackDetail", {})
        for tk in ("半导体设备", "存储芯片", "光通信模块"):
            td = track_detail.get(tk, [])
            # 取第一项的 GMMA 状态作参考
            gmma_state = "neutral"
            for r in td:
                if "GMMA" in r.get("name", ""):
                    gmma_state = r.get("value", "neutral")
                    break
            _tech_tracks[tk] = gmma_state
    except Exception:
        pass
    track_recs = build_track_recommendations(_track_scores, [], {}, action, diff,
                                              tech_tracks=_tech_tracks,
                                              extras_by_track=_extras_by_track)

# ---------------- 输出 ----------------
    try:
        _d = json.load(open(os.path.join(DATA, "szzs_full.json"), encoding="utf-8"))["data"]["sh000001"]
        cal = [r[0] for r in (_d.get("day") or _d.get("qfqday"))]
        future = [d for d in cal if d > today]
        t_plus1 = future[0] if future else None
        if not t_plus1:
            dt = datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)
            while dt.weekday() >= 5: dt += timedelta(days=1)
            t_plus1 = dt.strftime("%Y-%m-%d")
    except Exception:
        t_plus1 = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    decision = {
        "date": today, "execDate": t_plus1,
        "intraday": bool(is_intraday and state.get("align_phase", 0) != 0),
        "trend": effective_trend, "trendName": TREND_NAME.get(effective_trend, effective_trend),
        "trendRaw": trend, "center": center,
        "trendSince": trend_confirm_date, "trendReason": trend_reason,
        "trendStartDate": trend_start_date, "trendStartIdx": trend_start_idx,
        "alertActive": bool(alert_active), "alertReason": alert_reason,
        "changeMarkers": change_markers,
        "trendJudgments": state.get("trend_judgments", []),  # 2026-08-12 修订：所有历史趋势判定/变更标注（永不删除）
        "indicatorDetail": indicator_detail,
        "trackRecs": track_recs,
        "signals": {
            "close": closes[i], "ma5": round(ma5v[i], 2) if ma5v[i] else None,
            "ma20": round(ma20v[i], 2) if ma20v[i] else None,
            "gmma": detail_today.get("gmma"), "adx": detail_today["adx"],
            "pdi": detail_today.get("pdi"), "mdi": detail_today.get("mdi"),
            "bb_mid": detail_today.get("bb_mid"), "bb_lo": detail_today.get("bb_lo"),
            "bb_up": detail_today.get("bb_up"), "bb_pct": detail_today.get("bb_pct"),
            "volRatio": detail_today.get("vol_ratio"),
            "divBottom": detail_today.get("div_bottom"), "divTop": detail_today.get("div_top"),
            "strength": detail_today.get("strength", "neutral"),
            "ruleVersion": "v3.1-顾比GMMA+ADX+布林带+量价·全量显性化",
        },
        "score": comp, "zone": zone,
        "target": target, "current": current, "diff": diff,
        "action": action, "execAmount": exec_amount, "note": note,
        "userAcked": state.get("user_acked", True),  # 2026-08-10 修订：用户是否确认了执行
        "pendingAction": state.get("pending_action"),  # 等待确认的建议
        "alignPhase": state["align_phase"], "fuseHit": fuse_hit,
        "cooldown": in_cooldown, "trendChanged": trend_changed,
        "mapTable": MAP_TABLE, "trendNameMap": TREND_NAME,
    }
    json.dump(decision, open(os.path.join(DATA, "position_decision.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("=" * 60)
    print("日期:", today, "| 趋势:", TREND_NAME.get(effective_trend, effective_trend))
    print("GMMA:", detail_today["gmma"], "| ADX:", detail_today["adx"], "| 强度:", detail_today.get("strength", "neutral"))
    print("目标: %.1f成 | 当前: %.1f成 | 差额: %+.1f成" % (target, current, diff))
    print("指令: %s %s | %s" % (action, exec_amount if exec_amount else "", note))
    if alert_active: print("预警:", alert_reason)
    print("对齐:", state["align_phase"], "| 熔断:", fuse_hit or "无")

if __name__ == "__main__":
    main()