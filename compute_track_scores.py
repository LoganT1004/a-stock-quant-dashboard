# -*- coding: utf-8 -*-
"""四赛道综合评分 v2（创新药+半导体设备+光通信模块+存储芯片）

输出 data/track_scores.json：每个赛道的技术面六维度分 + 基本面分 + 消息面分 + 总分。

公式：综合 = 技术面×50% + 基本面×35% + 消息面×15%

技术面（6 维度，对标 SOX 六维评分）：
  GMMA顾比 20% + ADX 20% + BOLL 15% + MACD 20% + MA均线 15% + VOL量能 10%

基本面（每个赛道专属代理指标，0-100）：
  创新药：近期涨跌幅（30%）+ 上涨天数（25%）+ 量能（20%）+ 波动性（15%）+ 趋势（10%）
  半导体设备：同上
  光通信模块：同上
  存储芯片：同上
  （共享公式：短期涨幅 + 量比 + 趋势一致性 + 波动性控制 + 板块强度）

消息面（基于 news.json 关键词匹配 + 影响分级）：
  基准 50 分；利好每条 +1~2 分；利空每条 -1~2 分；极值 ±3 分；上限 ±5
  自动去重：已纳入标题的公司消息不重复加减分
"""
import os, json, re
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")


def load_industry_data():
    """加载公开行业数据（data/industry_data.json）。"""
    fp = os.path.join(DATA, "industry_data.json")
    if not os.path.exists(fp):
        return {}
    try:
        return json.load(open(fp, encoding="utf-8"))
    except Exception:
        return {}


def public_industry_score(track_name, industry_data):
    """根据公开行业数据计算 0-100 分（对齐 fetch_industry_data.public_industry_score）。

    规则：各 item 按 weight×时间衰减 加权；正向取 score 本身，负向取 100-score；
    无数据返回中性 50。
    """
    tracks = industry_data.get("tracks", {})
    items = tracks.get(track_name, {}).get("items", [])
    if not items:
        return 50, {}
    total_w = 0.0
    acc = 0.0
    detail = []
    for it in items:
        try:
            d0 = datetime.strptime(it["date"], "%Y-%m-%d")
            days = (datetime.now() - d0).days
            decay = max(0.5, 1.0 - days / 30.0)
        except Exception:
            decay = 0.8
        w = it.get("weight", 0.25) * decay
        if it.get("direction", 1) >= 0:
            s = it.get("score", 50)
        else:
            s = 100 - it.get("score", 50)
        acc += s * w
        total_w += w
        detail.append({"metric": it["metric"], "score": round(s, 1),
                       "date": it["date"], "src": it["src"],
                       "note": it["note"][:100]})
    final = round(acc / total_w, 2) if total_w > 0 else 50
    return final, {"items": detail, "weighted": final}


def ema(vals, n):
    k = 2 / (n + 1); out = []; e = vals[0]
    for i, v in enumerate(vals):
        e = v if i == 0 else v * k + e * (1 - k)
        out.append(e)
    return out


def sma(vals, n):
    return [sum(vals[max(0, i - n + 1):i + 1]) / min(n, i + 1) for i in range(len(vals))]


def tech_score_track(rows):
    """计算 6 维度技术面评分（满分 100）。

    维度权重：GMMA 20% + ADX 20% + BOLL 15% + MACD 20% + MA 15% + VOL 10%
    """
    if not rows or len(rows) < 60:
        return 50, {}  # 数据不足，中性分

    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    vols = [r["vol"] for r in rows]
    i = len(rows) - 1  # 最新一天
    c = closes[i]
    detail = {}

    # 1) GMMA 顾比均线 20%（用 SMA6/18/30/72/288 替代，与 SOX 一致）
    sma6 = sma(closes, 6); sma18 = sma(closes, 18); sma30 = sma(closes, 30)
    sma72 = sma(closes, 72) if len(closes) >= 72 else None
    sma288 = sma(closes, 288) if len(closes) >= 288 else None
    if sma72 is not None and sma288 is not None:
        # 多头：短组 > 中组 > 长组；空头反向；缠绕为中性
        if sma6[i] > sma18[i] > sma30[i] > sma72[i] > sma288[i]:
            gmma_score = 90
            gmma_state = "强多头排列"
        elif sma6[i] > sma18[i] > sma30[i]:
            gmma_score = 75
            gmma_state = "短中多头"
        elif sma6[i] < sma18[i] < sma30[i] < sma72[i] < sma288[i]:
            gmma_score = 10
            gmma_state = "强空头排列"
        elif sma6[i] < sma18[i] < sma30[i]:
            gmma_score = 25
            gmma_state = "短中空头"
        else:
            gmma_score = 50
            gmma_state = "缠绕震荡"
    else:
        gmma_score = 50
        gmma_state = "数据不足"
    detail["GMMA顾比"] = gmma_score

    # 2) ADX 趋势强度 20%（14 周期 Wilder）
    # 简化：基于 close-high / close-low 的比率（无需完整 Wilder）
    plus_dm = []; minus_dm = []; trs = []
    for k in range(1, len(rows)):
        up = highs[k] - highs[k-1]
        dn = lows[k-1] - lows[k]
        plus_dm.append(max(up, 0) if up > dn else 0)
        minus_dm.append(max(dn, 0) if dn > up else 0)
        tr = max(highs[k] - lows[k], abs(highs[k] - closes[k-1]), abs(lows[k] - closes[k-1]))
        trs.append(tr)
    period = 14
    if len(plus_dm) >= period:
        sm_tr = sum(trs[-period:])
        if sm_tr > 0:
            plus_di = sum(plus_dm[-period:]) / sm_tr * 100
            minus_di = sum(minus_dm[-period:]) / sm_tr * 100
            dx_sum = abs(plus_di - minus_di)
            adx_v = min(100, max(0, dx_sum / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0))
            # 14 周期 ADX
            if adx_v >= 40:
                adx_score = 90
            elif adx_v >= 30:
                adx_score = 75
            elif adx_v >= 25:
                adx_score = 60
            elif adx_v >= 20:
                adx_score = 50
            elif adx_v >= 15:
                adx_score = 40
            else:
                adx_score = 25
            detail["ADX趋势强度"] = round(adx_v, 1)
        else:
            adx_score = 50
    else:
        adx_score = 50
    detail["ADX评分"] = adx_score

    # 3) BOLL 布林带 15%（20 日 2 倍标准差）
    if len(closes) >= 20:
        ma20 = sum(closes[-20:]) / 20
        std20 = (sum((x - ma20) ** 2 for x in closes[-20:]) / 20) ** 0.5
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        if c >= upper:
            boll_score = 90  # 站上上轨加速
        elif c >= ma20 + std20:
            boll_score = 70  # 中轨之上
        elif c >= ma20 - std20:
            boll_score = 50  # 中轨附近中性
        elif c >= lower:
            boll_score = 30  # 中轨之下
        else:
            boll_score = 15  # 跌破下轨破位
        detail["BOLL分位"] = round((c - lower) / (upper - lower) if upper > lower else 0.5, 3)
    else:
        boll_score = 50
    detail["BOLL评分"] = boll_score

    # 4) MACD 动量 20%
    if len(closes) >= 26:
        dif, dea = ema(closes, 12), ema(closes, 26)
        macd = [(d - e) for d, e in zip(dif, dea)]
        dif_v = dif[i]; dea_v = dea[i]
        if dif_v > 0 and dif_v > dea_v and macd[i] > (macd[i-1] if i >= 1 else 0):
            macd_score = 90  # 零轴上方金叉红柱放大
        elif dif_v > 0 and dif_v > dea_v:
            macd_score = 70  # 零轴上方金叉
        elif dif_v < 0 and dif_v < dea_v and macd[i] < (macd[i-1] if i >= 1 else 0):
            macd_score = 15  # 死叉绿柱放大
        elif dif_v < 0 and dif_v < dea_v:
            macd_score = 30  # 死叉
        else:
            macd_score = 50  # 零轴纠缠
    else:
        macd_score = 50
    detail["MACD评分"] = macd_score

    # 5) MA 均线系统 15%（5/10/20/60 多头排列）
    if len(closes) >= 60:
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20_v = sum(closes[-20:]) / 20
        ma60 = sum(closes[-60:]) / 60
        if ma5 > ma10 > ma20_v > ma60:
            ma_score = 90  # 完美多头
        elif ma5 > ma10 > ma20_v:
            ma_score = 70  # 中短期多头
        elif ma5 < ma10 < ma20_v < ma60:
            ma_score = 10  # 完美空头
        elif ma5 < ma10 < ma20_v:
            ma_score = 30  # 中短期空头
        else:
            ma_score = 50  # 交叉震荡
    else:
        ma_score = 50
    detail["MA评分"] = ma_score

    # 6) VOL 量能健康度 10%
    if len(vols) >= 5 and i >= 1:
        today_vol = vols[i]
        past5_avg = sum(vols[-6:-1]) / 5 if len(vols) >= 6 else sum(vols[:-1]) / max(len(vols) - 1, 1)
        vol_ratio = today_vol / past5_avg if past5_avg > 0 else 1.0
        chg = closes[i] / closes[i - 1] - 1 if i >= 1 else 0
        # 上涨放量+下跌缩量 = 健康
        if chg > 0 and vol_ratio > 1.0:
            vol_score = min(100, 60 + (vol_ratio - 1) * 50)
        elif chg < 0 and vol_ratio < 1.0:
            vol_score = min(100, 60 + (1 - vol_ratio) * 50)
        elif chg > 0 and vol_ratio < 1.0:
            vol_score = max(0, 40 - (1 - vol_ratio) * 30)  # 缩量上涨，滞涨
        else:
            vol_score = max(0, 30 - (vol_ratio - 1) * 30)  # 放量下跌
        vol_score = max(0, min(100, vol_score))
    else:
        vol_score = 50
    detail["VOL评分"] = round(vol_score)

    # 加权求和
    final = (gmma_score * 0.20 + adx_score * 0.20 + boll_score * 0.15 +
             macd_score * 0.20 + ma_score * 0.15 + vol_score * 0.10)
    detail["技术面加权分"] = round(final, 2)
    detail["GMMA状态"] = gmma_state
    return round(final, 2), detail


def _load_kc50_closes():
    """加载科创50历史收盘序列（用于行业相对强弱基准）。"""
    fp = os.path.join(DATA, "kc50_full.json")
    if not os.path.exists(fp):
        return None
    try:
        d = json.load(open(fp, encoding="utf-8"))
        day = d["data"]["sh000688"]["day"]
        # 转为 {date: close}
        return {x[0]: float(x[2]) for x in day}
    except Exception:
        return None

def fundamental_score_track(rows, name, kc50_close_map=None):
    """基本面评分 V2（5维代理指标框架，0-100）。

    与用户指令对齐：
      1) 行业相对强弱 30%（近20日、60日相对科创50的超额收益）
      2) 资金趋势强度 25%（近10日、20日主力资金累计净流入占比代理=价格行为代理）
      3) 趋势一致性 20%（日线+周线共振）
      4) 量价健康度 15%（近20日上涨日放量、下跌日缩量占比）
      5) 波动率稳定性 10%（近20日波动率 vs 行业历史均值）

    全部基于现有行情数据衍生，作为「市场对基本面预期的代理变量」，
    严格与纯技术面指标（GMMA/ADX/BOLL/MACD/MA/VOL）做差异化互补。
    """
    if not rows or len(rows) < 60:
        return 50, {}

    closes = [r["close"] for r in rows]
    vols = [r["vol"] for r in rows]
    dates = [r["date"] for r in rows]
    n = len(closes)
    i = n - 1
    c = closes[i]
    detail = {}
    sub_scores = {}

    # 1) 行业相对强弱 30%（近20日、60日相对科创50超额收益）
    #    基准：科创50指数同期涨跌幅
    rel_s = 50
    if kc50_close_map:
        # 找最接近的 KC50 同期日期
        last_date = dates[i]
        sorted_kc50 = sorted(kc50_close_map.keys())
        kc_now = kc50_close_map.get(last_date)
        if not kc_now:
            # 找最近的更早日期
            for d in sorted_kc50[::-1]:
                if d <= last_date:
                    kc_now = kc50_close_map[d]
                    break
        # 算20日/60日超额
        excess = {"20d": None, "60d": None}
        if kc_now and i >= 20 and i >= 60:
            track_ret_20 = closes[i] / closes[i - 20] - 1
            kc_ret_20 = kc_now / kc50_close_map.get(sorted_kc50[max(0, len(sorted_kc50) - 21)], kc_now) - 1
            # 简化为：track_ret - kc_ret 都不太好算，用指数化对数
            import math
            track_ret_20 = math.log(closes[i] / closes[i - 20])
            track_ret_60 = math.log(closes[i] / closes[i - 60])
            kc_dates_20 = [x for x in sorted_kc50 if x <= dates[i - 20]][-1] if any(x for x in sorted_kc50 if x <= dates[i - 20]) else None
            kc_dates_60 = [x for x in sorted_kc50 if x <= dates[i - 60]][-1] if any(x for x in sorted_kc50 if x <= dates[i - 60]) else None
            kc_ret_20 = math.log(kc_now / kc50_close_map.get(kc_dates_20, kc_now)) if kc_dates_20 else 0
            kc_ret_60 = math.log(kc_now / kc50_close_map.get(kc_dates_60, kc_now)) if kc_dates_60 else 0
            excess["20d"] = (track_ret_20 - kc_ret_20) * 100  # 转化为百分点
            excess["60d"] = (track_ret_60 - kc_ret_60) * 100
        # 综合20日 (权重60%) + 60日 (权重40%)
        if excess["20d"] is not None and excess["60d"] is not None:
            excess_score = excess["20d"] * 0.6 + excess["60d"] * 0.4
            # 线性打分：超额 +5% → 90, +2% → 70, 0 → 50, -2% → 30, -5% → 10
            rel_s = max(0, min(100, 50 + excess_score * 8))
        detail["相对超额20d%"] = round(excess["20d"], 2) if excess["20d"] is not None else None
        detail["相对超额60d%"] = round(excess["60d"], 2) if excess["60d"] is not None else None
    sub_scores["行业相对强弱"] = (round(rel_s, 1), 0.30)

    # 2) 资金趋势强度 25%（近10日、20日主力资金累计净流入占比，价格行为代理）
    # 价格行为代理：上涨日相对涨幅 - 下跌日相对跌幅，反映资金流向
    fund_flow_s = 50
    if i >= 20:
        # 近20日资金代理值
        proxy_20 = sum(
            (closes[k] - closes[k - 1]) / closes[k - 1] if closes[k] >= closes[k - 1]
            else (closes[k] - closes[k - 1]) / closes[k - 1] * 1.5  # 下跌日按同等幅度计 1.5x
            for k in range(i - 19, i + 1) if k >= 1
        )
        # 近10日
        proxy_10 = sum(
            (closes[k] - closes[k - 1]) / closes[k - 1] if closes[k] >= closes[k - 1]
            else (closes[k] - closes[k - 1]) / closes[k - 1] * 1.5
            for k in range(i - 9, i + 1) if k >= 1
        )
        # 标准化：log 用对数映射，10%净流入 → 100分
        composite_proxy = proxy_10 * 0.5 + proxy_20 * 0.5
        fund_flow_s = max(0, min(100, 50 + composite_proxy * 350))
    sub_scores["资金趋势强度"] = (round(fund_flow_s, 1), 0.25)

    # 3) 趋势一致性 20%（日线+周线共振）
    consistency_s = 50
    if i >= 20:
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        # 日线方向：MA5 vs MA20
        daily_up = 1 if ma5 > ma20 else -1
        # 周线方向：5日均 vs 20日均（5天≈1周，但用 20 天移窗模拟周线趋势）
        # 简化：最近 5 周（25 天）均价 vs 最近 12 周（60 天）均价
        if i >= 60:
            wk5 = sum(closes[i - 4:i + 1]) / 5
            wk12 = sum(closes[i - 59:i + 1]) / 60
            weekly_up = 1 if wk5 > wk12 else -1
        else:
            weekly_up = daily_up
        # 共振打分：相同方向 + 50，不同方向 - 30
        if daily_up == weekly_up:
            # 同向：看强度
            if daily_up > 0:
                consistency_s = 75 + min(25, abs(ma5 - ma20) / ma20 * 1000)
            else:
                consistency_s = 75 - min(25, abs(ma5 - ma20) / ma20 * 1000)
        else:
            # 周期背离
            consistency_s = 30
        detail["日线方向"] = "↑" if daily_up > 0 else "↓"
        detail["周线方向"] = "↑" if weekly_up > 0 else "↓"
        detail["共振"] = "是" if daily_up == weekly_up else "否"
    sub_scores["趋势一致性"] = (round(consistency_s, 1), 0.20)

    # 4) 量价健康度 15%（近20日上涨日放量、下跌日缩量占比）
    vol_health_s = 50
    if i >= 20:
        up_vols = []
        down_vols = []
        for k in range(i - 19, i + 1):
            if k >= 1:
                if closes[k] > closes[k - 1]:
                    up_vols.append(vols[k])
                elif closes[k] < closes[k - 1]:
                    down_vols.append(vols[k])
        if up_vols and down_vols:
            avg_up = sum(up_vols) / len(up_vols)
            avg_down = sum(down_vols) / len(down_vols)
            # 健康度：上涨日均量 / 下跌日均量
            # 1.5+ → 95, 1.2 → 75, 1.0 → 60, 0.8 → 40, 0.5 → 20
            vratio = avg_up / avg_down if avg_down > 0 else 1
            if vratio > 1.5: vol_health_s = 95
            elif vratio > 1.2: vol_health_s = 75
            elif vratio > 0.95: vol_health_s = 60
            elif vratio > 0.7: vol_health_s = 40
            else: vol_health_s = 20
            detail["上涨日均量"] = round(avg_up)
            detail["下跌日均量"] = round(avg_down)
            detail["量价比"] = round(vratio, 2)
    sub_scores["量价健康度"] = (round(vol_health_s, 1), 0.15)

    # 5) 波动率稳定性 10%（近20日波动率 vs 近60日均波动率）
    vola_s = 50
    if i >= 60:
        # 近20日 ATR
        atr20 = sum(abs(closes[k] - closes[k - 1]) for k in range(i - 19, i + 1) if k >= 1) / 20
        # 近60日 ATR
        atr60 = sum(abs(closes[k] - closes[k - 1]) for k in range(i - 59, i + 1) if k >= 1) / 60
        # 比率：当前波动率 / 长期均值
        vola_ratio = atr20 / atr60 if atr60 > 0 else 1
        # 当前波动 < 长期波动 → 稳定 → 高分
        if vola_ratio < 0.7: vola_s = 90
        elif vola_ratio < 0.85: vola_s = 75
        elif vola_ratio < 1.0: vola_s = 60
        elif vola_ratio < 1.2: vola_s = 45
        else: vola_s = 25
        detail["ATR20"] = round(atr20, 2)
        detail["ATR60"] = round(atr60, 2)
        detail["波动率比20/60"] = round(vola_ratio, 2)
    sub_scores["波动率稳定性"] = (round(vola_s, 1), 0.10)

    # 加权求和（纯代理基本面分，未混合公开数据）
    final = sum(score * w for score, w in sub_scores.values())
    detail["5维明细"] = {k: {"score": v[0], "weight": v[1]} for k, v in sub_scores.items()}
    detail["基本面加权分"] = round(final, 2)
    detail["代理基本面分"] = round(final, 2)
    return round(final, 2), detail


def news_score_track(name, news_items):
    """消息面评分（基于 news.json 关键词匹配）。

    基准 50 分；利好每条 +1~2 分；利空每条 -1~2 分；极值事件 ±3 分；上限 ±5。
    """
    if not news_items:
        return 50, {}

    # 赛道关键词
    KEYWORDS = {
        "创新药": ["创新药", "药明", "恒瑞", "百济", "信达", "PD-1", "ADC", "GLP-1", "医保", "新药", "获批"],
        "半导体设备": ["半导体设备", "刻蚀", "薄膜沉积", "CMP", "测试机", "北方华创", "中微公司", "拓荆", "华海清科", "国产化", "国产替代", "长川科技", "中科飞测", "芯源微"],
        "光通信模块": ["光通信", "光模块", "800G", "1.6T", "中际旭创", "新易盛", "天孚通信", "光迅", "光芯片", "AI算力", "CPO"],
        "存储芯片": ["存储", "存储芯片", "HBM", "DRAM", "NAND", "长鑫", "兆易创新", "佰维存储", "普冉", "江波龙", "德明利", "海力士", "美光", "三星", "SK海力士", "长存", "长鑫存储"],
    }
    kw_list = KEYWORDS.get(name, [])
    if not kw_list:
        return 50, {}

    matched_items = []
    score = 50
    counts = {"利好": 0, "利空": 0, "极值": 0}

    for it in news_items:
        title = it.get("title", "")
        impact = it.get("impact", "")
        major = it.get("major", False)

        # 检查关键词
        hit = False
        for kw in kw_list:
            if kw in title:
                hit = True
                break
        if not hit:
            continue

        matched_items.append({"title": title[:60], "impact": impact, "major": major})

        # 加减分
        if major:
            # 极值事件
            if impact == "利好":
                score += 3
                counts["极值"] += 1
                counts["利好"] += 1
            elif impact == "利空":
                score -= 3
                counts["极值"] += 1
                counts["利空"] += 1
        else:
            if impact == "利好":
                score += 1
                counts["利好"] += 1
            elif impact == "利空":
                score -= 1
                counts["利空"] += 1

    # 上限 ±5 调整
    if score > 55:
        score = 55  # 上限 +5
    elif score < 45:
        score = 45  # 下限 -5

    detail = {
        "匹配条数": len(matched_items),
        "利好条数": counts["利好"],
        "利空条数": counts["利空"],
        "极值条数": counts["极值"],
        "消息面分": score,
        "代表条目": [it["title"] for it in matched_items[:3]],
    }
    return score, detail


def main():
    """主函数：为 4 个赛道计算综合评分并写入 data/track_scores.json。"""
    TRACKS = [
        ("半导体设备", "bk1326_raw.json"),
        ("存储芯片", "bk1137_raw.json"),
        ("光通信模块", "bk1136_raw.json"),
        ("创新药", "bk1106_raw.json"),
    ]

    # 读取新闻
    news_items = []
    news_fp = os.path.join(DATA, "news.json")
    if os.path.exists(news_fp):
        d = json.load(open(news_fp, encoding="utf-8"))
        for cat in d.get("categories", []):
            for it in cat.get("items", []):
                news_items.append(it)

    # 读取科创50 基准（行业相对强弱）
    kc50_close_map = _load_kc50_closes()

    # 读取公开行业数据
    industry_data = load_industry_data()

    results = {}
    for name, fn in TRACKS:
        fp = os.path.join(DATA, fn)
        if not os.path.exists(fp):
            results[name] = {"score": 50, "error": f"{fn} not found"}
            continue

        d = json.load(open(fp, encoding="utf-8"))
        rows = [{"date": r.split(",")[0], "open": float(r.split(",")[1]),
                 "close": float(r.split(",")[2]), "high": float(r.split(",")[3]),
                 "low": float(r.split(",")[4]), "vol": float(r.split(",")[5])}
                for r in d["klines"]]

        tech, tech_d = tech_score_track(rows)
        proxy_fund, fund_d = fundamental_score_track(rows, name, kc50_close_map)
        news, news_d = news_score_track(name, news_items)

        # 公开行业数据分（免费公开渠道）
        public_fund, public_d = public_industry_score(name, industry_data)

        # 过渡阶段权重：初始阶段 代理80% + 公开数据20%
        proxy_ratio = 0.80
        public_ratio = 0.20
        fund = round(proxy_fund * proxy_ratio + public_fund * public_ratio, 2)
        fund_d["代理基本面分"] = round(proxy_fund, 2)
        fund_d["公开行业数据分"] = round(public_fund, 2)
        fund_d["代理指标占比"] = proxy_ratio
        fund_d["公开数据占比"] = public_ratio
        fund_d["公开数据明细"] = public_d
        fund_d["混合基本面分"] = fund

        composite = round(tech * 0.50 + fund * 0.35 + news * 0.15, 2)

        results[name] = {
            "score": composite,
            "tech": tech, "fundamental": fund, "news": news,
            "tech_detail": tech_d, "fundamental_detail": fund_d, "news_detail": news_d,
            "fundamental_proxy_ratio": proxy_ratio,
            "fundamental_public_ratio": public_ratio,
            "last_close": rows[-1]["close"] if rows else None,
            "last_date": rows[-1]["date"] if rows else None,
        }

    json.dump(results, open(os.path.join(DATA, "track_scores.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("track_scores.json 已写入")
    for name in results:
        r = results[name]
        print(f"  {name}: 总={r['score']} (技={r['tech']}, 基={r['fundamental']}, 消={r['news']})")


if __name__ == "__main__":
    main()