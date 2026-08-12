# -*- coding: utf-8 -*-
"""评分引擎 v2（用户定制规则）
技术面40% = 赛道指数信号70% + 宽基指数信号30%
  子项：MACD背离35% / 趋势均线(MA5 vs MA20)35% / 神奇九转15%(仅触9计分) / 量能15%
外围面25% = 美股赛道龙头50%(核心主导) + 全球流动性30% + VXN 15% + 亚洲联动5%
资金面10% = 两融杠杆趋势35% + 北向资金动向20% + 宏观流动性环境20% + 场内机构资金25%
基本面10% = 产业景气45% + 政策35% + 监管20%
额外加减分：直接作用于总分
输出：score_result.json（含打分明细+快照序列）
"""
import os, sys
import json, re
from datetime import datetime, timedelta
from vol_utils import intraday_vol_factor

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
STOCKS = os.path.join(DATA, "stocks")

def load_tx(path, key):
    d = json.load(open(path, encoding="utf-8"))["data"][key]
    day = d.get("day") or d.get("qfqday") or []
    return [{"date": r[0], "open": float(r[1]), "close": float(r[2]),
             "high": float(r[3]), "low": float(r[4]), "vol": float(r[5])} for r in day]

def load_stock(code):
    return load_tx(os.path.join(STOCKS, code + ".json"), code)

def append_today(rows, quote):
    """把8/3快照append到7/31之后"""
    if not rows or rows[-1]["date"] >= "2026-08-03": return rows
    rows = rows + [{"date": "2026-08-03", "open": quote["open"], "close": quote["close"],
                    "high": quote["high"], "low": quote["low"], "vol": quote["vol"]}]
    return rows

def parse_quotes():
    raw = open(os.path.join(DATA, "stocks_quote_utf8.txt"), encoding="utf-8").read()
    out = {}
    for m in re.finditer(r'v_(\w+)="([^"]+)"', raw):
        p = m.group(2).split("~")
        if len(p) > 34 and p[1]:
            out[m.group(1)] = {"name": p[1], "open": float(p[5] or p[3]), "close": float(p[3]),
                               "high": float(p[33] or p[3]), "low": float(p[34] or p[3]),
                               "vol": float(p[6] or 0), "chg": float(p[32] or 0)}
    return out

def build_track_index(codes, quotes):
    """等权合成赛道指数（每日涨跌幅等权平均后累乘，避免涨幅加权失真与成分加入断层；
    新股上市首日不纳入涨跌幅平均，次日起计入）"""
    series = {}
    for c in codes:
        rows = append_today(load_stock(c), quotes.get(c)) if c in quotes else load_stock(c)
        if len(rows) >= 2: series[c] = rows
    chg_map = {}
    for c, rows in series.items():
        m = {}
        for i in range(1, len(rows)):
            pc = rows[i - 1]["close"]
            m[rows[i]["date"]] = ((rows[i]["close"] / pc - 1) * 100,
                                  (rows[i]["high"] / pc - 1) * 100,
                                  (rows[i]["low"] / pc - 1) * 100)
        m['__first__'] = rows[1]["date"]
        chg_map[c] = m
    dates = sorted({d for m in chg_map.values() for d in m if not d.startswith('__')})
    price = 1000.0
    out = []
    for dt in dates:
        trips = [chg_map[c][dt] for c in chg_map if dt in chg_map[c] and dt > chg_map[c]['__first__']]
        if not trips:
            trips = [chg_map[c][dt] for c in chg_map if dt in chg_map[c]]
        if not trips: continue
        avg = sum(t[0] for t in trips) / len(trips)
        avg_h = sum(t[1] for t in trips) / len(trips)
        avg_l = sum(t[2] for t in trips) / len(trips)
        prev = price
        price = price * (1 + avg / 100)
        vol = sum((r["vol"] for rows in series.values() for r in rows if r["date"] == dt), 0.0)
        out.append({"date": dt, "open": prev, "close": price,
                    "high": prev * (1 + avg_h / 100), "low": prev * (1 + avg_l / 100), "vol": vol})
    return out

def ema(vals, n):
    k = 2/(n+1); out=[]; e=vals[0]
    for i, v in enumerate(vals):
        e = v if i==0 else v*k+e*(1-k); out.append(e)
    return out

def sma(vals, n):
    return [sum(vals[max(0,i-n+1):i+1])/min(n,i+1) for i in range(len(vals))]

def calc_adx_sim(highs_lows_closes, period=14):
    """简化版 ADX/+DI/-DI 计算（接受 close-only 序列：用 SMA 模拟 high/low/close 关系）"""
    closes = highs_lows_closes
    n = len(closes)
    if n < period + 1: return [None]*n, [None]*n, [None]*n
    highs = [closes[i] * 1.005 for i in range(n)]   # 模拟 high
    lows = [closes[i] * 0.995 for i in range(n)]    # 模拟 low
    tr = [highs[i] - lows[i] for i in range(n)]
    # 方向移动
    pdm = [0.0]*n; mdm = [0.0]*n
    for i in range(1, n):
        up = highs[i] - highs[i-1]
        dn = lows[i-1] - lows[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
    # Wilder 平滑
    atr = [None]*n; apdm = [None]*n; amdm = [None]*n
    atr[period] = sum(tr[1:period+1]); apdm[period] = sum(pdm[1:period+1]); amdm[period] = sum(mdm[1:period+1])
    for i in range(period+1, n):
        atr[i] = atr[i-1] - atr[i-1]/period + tr[i]
        apdm[i] = apdm[i-1] - apdm[i-1]/period + pdm[i]
        amdm[i] = amdm[i-1] - amdm[i-1]/period + mdm[i]
    pdi = [None]*n; mdi = [None]*n; dx = [None]*n
    for i in range(period, n):
        pdi[i] = 100 * apdm[i]/atr[i] if atr[i] > 0 else 0
        mdi[i] = 100 * amdm[i]/atr[i] if atr[i] > 0 else 0
        dx[i] = 100 * abs(pdi[i] - mdi[i]) / (pdi[i] + mdi[i]) if (pdi[i] + mdi[i]) > 0 else 0
    adx = [None]*n
    # 修复：当数据不足 period*2+1 时（SOX仅26根），用最后可用的索引替代
    adx_start = min(period*2, n-1)
    adx[adx_start] = sum(dx[period:min(period*2+1, n)])/max(period, 1)
    for i in range(adx_start+1, n):
        adx[i] = (adx[i-1]*(period-1) + dx[i])/period
    return adx, pdi, mdi

def nine(rows):
    up=[0]*len(rows); down=[0]*len(rows)
    for i in range(4, len(rows)):
        if rows[i]["close"] > rows[i-4]["close"]: up[i]=up[i-1]+1
        if rows[i]["close"] < rows[i-4]["close"]: down[i]=down[i-1]+1
    return up, down

def divergence_score(rows):
    """MACD背离打分：强底85/弱底58/无50/弱顶42/强顶28（swing粗检）"""
    n=len(rows)
    if n < 40: return 50, "样本不足按中性"
    closes=[r["close"] for r in rows]
    e12,e26=ema(closes,12),ema(closes,26); dif=[a-b for a,b in zip(e12,e26)]
    w=3; sh=[]; sl=[]
    for i in range(w, n-w):
        if all(rows[i]["high"]>=rows[j]["high"] for j in range(i-w,i+w+1) if j!=i): sh.append(i)
        if all(rows[i]["low"]<=rows[j]["low"] for j in range(i-w,i+w+1) if j!=i): sl.append(i)
    if len(sl)>=2:
        a,b=sl[-2],sl[-1]
        if rows[b]["low"]<rows[a]["low"] and dif[b]>dif[a]:
            dev=(dif[b]-dif[a])/max(abs(dif[a]),1e-9)
            if dev>=0.15: return 85, "强底背离（DIF偏离%+.0f%%）"%(dev*100)
            return 58, "弱底背离"
    if len(sh)>=2:
        a,b=sh[-2],sh[-1]
        if rows[b]["high"]>rows[a]["high"] and dif[b]<dif[a]:
            dev=(dif[a]-dif[b])/max(abs(dif[a]),1e-9)
            if dev>=0.15: return 28, "强顶背离（DIF偏离%-.0f%%）"%(dev*100)
            return 42, "弱顶背离"
    return 50, "无背离"

def trend_score(rows):
    """MA5 vs MA20"""
    closes=[r["close"] for r in rows]
    ma5=sma(closes,5); ma20=sma(closes,20)
    d_now=(ma5[-1]-ma20[-1])/ma20[-1]
    d_prev=(ma5[-6]-ma20[-6])/ma20[-6] if len(closes)>25 else d_now
    above3=all(closes[i]>ma5[i] for i in range(-3,0))
    if d_now>0 and above3 and d_now>0.01: return 85, "MA5上穿MA20且站稳"
    if d_now>0.003: return 70, "MA5在MA20上方"
    if abs(d_now)<=0.003: return 50, "均线缠绕震荡"
    if d_now<0 and abs(d_now)>abs(d_prev)+0.002: return 25, "MA5在MA20下方且加速偏离（%.1f%%）"%(d_now*100)
    return 40, "MA5在MA20下方"

def nine_score(rows):
    up,down=nine(rows)
    if down[-1]>=9: return 80, "低9触发（底部预警）", 0, down[-1]
    if up[-1]>=9: return 20, "高9触发（顶部预警）", up[-1], 0
    return 50, "未触9（计数：涨%d/跌%d，仅关注不计分）"%(up[-1],down[-1]), up[-1], down[-1]

def vol_score(rows):
    closes=[r["close"] for r in rows]
    # 量比 = 东方财富标准公式：今日成交量 / 前5日均量(不含今日)
    # 原公式 v5/v20 (短期/长期均量比) 错误，会偏高 5-15%
    today_vol = rows[-1]["vol"] * intraday_vol_factor()
    past5_vols = [r["vol"] for r in rows[-6:-1]]  # 前5个交易日(不含今日)
    past5_avg = sum(past5_vols) / 5 if len(past5_vols) == 5 else (sum(past5_vols) / max(len(past5_vols), 1) if past5_vols else 1)
    if past5_avg <= 0: return 50, "量能数据缺失"
    vr = today_vol / past5_avg  # 标准量比
    chg5=(closes[-1]/closes[-6]-1) if len(closes)>5 else 0
    if chg5>0 and vr>1.1: return 80, "量价配合（量比%.2f）"%vr
    if chg5<0 and vr<0.9: return 35, "缩量下跌（量比%.2f）"%vr
    if chg5>0 and vr<0.85: return 40, "缩量上涨存疑（量比%.2f）"%vr
    return 50, "量能中性（量比%.2f）"%vr

def index_tech_score(rows):
    s1,n1=divergence_score(rows); s2,n2=trend_score(rows); s3,n3,cu,cd=nine_score(rows); s4,n4=vol_score(rows)
    total=s1*0.35+s2*0.35+s3*0.15+s4*0.15
    return {"score":round(total,1),
            "subs":[{"name":"MACD背离","w":35,"score":s1,"note":n1},
                    {"name":"趋势与均线(MA5/MA20)","w":35,"score":s2,"note":n2},
                    {"name":"神奇九转","w":15,"score":s3,"note":n3},
                    {"name":"量能结构","w":15,"score":s4,"note":n4}],
            "curUp":cu,"curDown":cd}

def main():
    quotes=parse_quotes()
    code_of={"北方华创":"sz002371","中微公司":"sh688012","拓荆科技":"sh688072","华海清科":"sh688120","长川科技":"sz300604","中科飞测":"sh688361",
             "长鑫科技":"sh688825","兆易创新":"sh603986","佰维存储":"sh688525","普冉股份":"sh688766","德明利":"sz001309","江波龙":"sz301308",
             "中际旭创":"sz300308","新易盛":"sz300502","天孚通信":"sz300394","光迅科技":"sz002281"}
    tracks={
        "半导体设备":["sz002371","sh688012","sh688072","sh688120","sz300604","sh688361"],
        "存储芯片":["sh688825","sh603986","sh688525","sh688766","sz001309","sz301308"],
        "光通信模块":["sz300308","sz300502","sz300394","sz002281"],
    }
    track_idx={}; track_scores={}
    # 东财板块指数（BK官方口径，用户指定：赛道实时数据不用ETF，直接用东财板块指数）
    BK_FILES = {"半导体设备": "bk1326_raw.json", "存储芯片": "bk1137_raw.json", "光通信模块": "bk1136_raw.json"}
    def load_bk(t):
        fp = os.path.join(DATA, BK_FILES[t])
        if not os.path.exists(fp):
            return None
        d = json.load(open(fp, encoding="utf-8"))
        return [{"date": r.split(",")[0], "open": float(r.split(",")[1]), "close": float(r.split(",")[2]),
                 "high": float(r.split(",")[3]), "low": float(r.split(",")[4]), "vol": float(r.split(",")[5])}
                for r in d["klines"]]
    for t,codes in tracks.items():
        rows = load_bk(t) or build_track_index(codes, quotes)  # BK缺失时回退成分合成指数
        track_idx[t]=rows
        track_scores[t]=index_tech_score(rows)
    wide={
        "上证指数":load_tx(os.path.join(DATA,"szzs_full.json"),"sh000001"),
        "创业板指":load_tx(os.path.join(DATA,"cybz_full.json"),"sz399006"),
        "科创50":load_tx(os.path.join(DATA,"kc50_full.json"),"sh000688"),
    }
    wide_scores={k:index_tech_score(v) for k,v in wide.items()}
    track_avg=round(sum(s["score"] for s in track_scores.values())/3,1)
    wide_avg=round(sum(s["score"] for s in wide_scores.values())/3,1)
    tech=round(track_avg*0.6+wide_avg*0.4,1)

    # 外围面v2：SOX主 + NDX辅，四子指标全部由score_engine.py下文重新组装
    ndx=load_tx(os.path.join(DATA,"ndx100_full.json"),"us.NDX")

    # ---- 动态数据装配（打分明细note实时化） ----
    def _latest_us10y():
        try:
            u=json.load(open(os.path.join(DATA,"us10y_em.json"),encoding="utf-8"))
            ks=u["data"]["klines"]; c=float(ks[-1].split(",")[2]); p=float(ks[-2].split(",")[2])
            return ks[-1].split(",")[0], c, (c-p)*100
        except Exception: return None,None,None
    def _latest_dxy():
        """美元指数DXY 最新值（东方财富 dxy_em.json）。"""
        try:
            d=json.load(open(os.path.join(DATA,"dxy_em.json"),encoding="utf-8"))
            ds,cs=d["dates"],d["closes"]
            if len(cs)>=2: return ds[-1],cs[-1],round((cs[-1]/cs[-2]-1)*100,2)
            return ds[-1],cs[-1],0
        except Exception: return None,None,None
    def _latest_wti():
        try:
            w=json.load(open(os.path.join(DATA,"wti.json"),encoding="utf-8"))
            c,p=w["closes"][-1],w["closes"][-2]
            return w["dates"][-1], c, (c/p-1)*100
        except Exception: return None,None,None
    u10_d,u10_c,u10_bp=_latest_us10y()
    dxy_d,dxy_c,dxy_chg=_latest_dxy()
    # VXN（外围卡片）
    try:
        _hand=json.load(open(os.path.join(os.path.dirname(DATA),"payload_hand.json"),encoding="utf-8"))
        _ovm={o["name"]:o for o in _hand.get("overseas",[])}
    except Exception: _ovm={}
    vxn_o=_ovm.get("VXN波动率",{})

    # ---- 1) 美股科技赛道信号（50%）：SOX主 + NDX辅 ----
    # 2026-08-11 v2 升级：六维技术因子加权评分（GMMA+ADX+BOLL+MACD+多周期均线+量能）
    # 2026-08-11 v2.1 修复：东财SOX dktotal仅26根（原门槛60过高），降到20根
    us_score, us_note, us_breakdown = 50, "SOX数据待更新", ""
    try:
        _sox_raw = open(os.path.join(DATA, "sox_em.json"), encoding="utf-8").read()
        _sox = json.loads(_sox_raw)
        _sox_dates = _sox["dates"]
        _sox_closes = _sox["closes"]
        _sox_vols = _sox.get("volumes") or _sox.get("vols") or []
        _has_vol = len(_sox_vols) >= 20
        # SOX历史数据在东财仅26根可用（原门槛60永远达不到）
        SOX_MIN_BARS = 20
        if len(_sox_closes) >= SOX_MIN_BARS:
            c_arr = _sox_closes; v_arr = _sox_vols
            cur = c_arr[-1]
            # ========== 因子1: GMMA顾比均线 (25%) ==========
            ema3 = ema(c_arr[-30:], 3)[-1]; ema5 = ema(c_arr[-30:], 5)[-1]
            ema8 = ema(c_arr[-30:], 8)[-1]; ema10 = ema(c_arr[-30:], 10)[-1]
            ema12 = ema(c_arr[-30:], 12)[-1]; ema15 = ema(c_arr[-30:], 15)[-1]
            ema30 = ema(c_arr[-60:], 30)[-1]; ema35 = ema(c_arr[-60:], 35)[-1]
            ema40 = ema(c_arr[-60:], 40)[-1]; ema45 = ema(c_arr[-60:], 45)[-1]
            ema50 = ema(c_arr[-60:], 50)[-1]; ema60 = ema(c_arr[-60:], 60)[-1]
            short_avg = (ema3 + ema5 + ema8 + ema10 + ema12 + ema15) / 6
            long_avg = (ema30 + ema35 + ema40 + ema45 + ema50 + ema60) / 6
            gmma_gap = (short_avg - long_avg) / long_avg * 100  # 正=多头,负=空头
            if gmma_gap > 2.0:
                gmma_s = 95; gmma_label = "多头排列+持续发散"
            elif gmma_gap > 0.5:
                gmma_s = 80; gmma_label = "多头排列+健康"
            elif gmma_gap > -0.5:
                gmma_s = 57; gmma_label = "长短组粘合"
            elif gmma_gap > -2.0:
                gmma_s = 35; gmma_label = "空头排列+弱势"
            else:
                gmma_s = 12; gmma_label = "空头排列+加速发散"
            # ========== 因子2: ADX (20%) ==========
            adx_p, pdi_arr, mdi_arr = calc_adx_sim(c_arr, 14)
            adx_v = adx_p[-1]; pdi_v = pdi_arr[-1]; mdi_v = mdi_arr[-1]
            if adx_v < 20 and pdi_v > mdi_v:
                adx_s = 95; adx_label = "ADX<20 + +DI>-DI（底部磨底）"
            elif adx_v > 25 and pdi_v > mdi_v:
                adx_s = 80; adx_label = "ADX>25 + +DI>-DI（多头增强）"
            elif adx_v < 20:
                adx_s = 57; adx_label = "ADX<20 + 反复交叉（震荡）"
            elif adx_v > 25 and mdi_v > pdi_v:
                adx_s = 35; adx_label = "ADX>25 + -DI>+DI（空头增强）"
            elif adx_v > 40 and mdi_v > pdi_v:
                adx_s = 12; adx_label = "ADX>40 + -DI远>+DI（极端空头）"
            else:
                adx_s = 50; adx_label = "中性"
            # ========== 因子3: 布林带 (20%) ==========
            ma20_arr = sma(c_arr[-25:], 20)
            std20_arr = []
            for i in range(20, len(c_arr[-25:])+1):
                w = c_arr[-25:][i-20:i]
                mu = sum(w)/20
                std20_arr.append((sum((x-mu)**2 for x in w)/20) ** 0.5)
            mb = ma20_arr[-1]; sd = std20_arr[-1] if std20_arr else 0
            bb_up = mb + 2*sd; bb_lo = mb - 2*sd
            bb_pct = (cur - bb_lo) / (bb_up - bb_lo) if (bb_up - bb_lo) > 0 else 0.5
            # 收口/发散判断（bw_now vs bw_prev）
            bw_now = (bb_up - bb_lo) / mb if mb > 0 else 0
            bw_prev = 0
            if len(ma20_arr) >= 2 and len(std20_arr) >= 2:
                bw_prev = (ma20_arr[-2] + 2*std20_arr[-2] - (ma20_arr[-2] - 2*std20_arr[-2])) / ma20_arr[-2]
            bb_contracting = bw_now < bw_prev * 0.95
            bb_expanding = bw_now > bw_prev * 1.05
            # 触下轨回升 → 95；中上轨 + 上发散 → 80；中轨附近 + 收口 → 55；中下轨 + 下发散 → 35；破下轨 → 12
            if cur < bb_lo * 1.01 and cur > bb_lo * 0.97:
                bb_s = 95; bb_label = "触及下轨回升"
            elif bb_pct > 0.5 and bb_expanding:
                bb_s = 80; bb_label = "中上轨+开口向上"
            elif bb_pct < 0.5 and bb_contracting:
                bb_s = 55; bb_label = "中轨附近+收口"
            elif bb_pct < 0.5 and bb_expanding:
                bb_s = 35; bb_label = "中下轨+开口向下"
            elif cur < bb_lo:
                bb_s = 12; bb_label = "跌破下轨"
            else:
                bb_s = 50; bb_label = "中性"
            # ========== 因子4: MACD (15%) ==========
            e12 = ema(c_arr[-30:], 12); e26 = ema(c_arr[-30:], 26)
            dif = [a-b for a,b in zip(e12, e26)]
            dea = ema(dif, 9)
            dif_v = dif[-1]; dea_v = dea[-1]; dif_prev = dif[-2]; dea_prev = dea[-2]
            hist_v = dif_v - dea_v; hist_prev = dif_prev - dea_prev
            cross_up = dif_prev <= dea_prev and dif_v > dea_v
            cross_dn = dif_prev >= dea_prev and dif_v < dea_v
            # 底背离：近30日价格低点创新低但 DIF 未创新低
            div_bot = False; div_top = False
            if len(dif) >= 30:
                lo_idx = c_arr[-30:].index(min(c_arr[-30:]))
                lo_dif = dif[lo_idx]
                div_bot = (cur <= min(c_arr[-30:])*1.005) and (dif_v > lo_dif)
                hi_idx = c_arr[-30:].index(max(c_arr[-30:]))
                hi_dif = dif[hi_idx]
                div_top = (cur >= max(c_arr[-30:])*0.995) and (dif_v < hi_dif)
            if cross_up and div_bot:
                macd_s = 95; macd_label = "金叉+底背离"
            elif cross_up and hist_v > 0:
                macd_s = 80; macd_label = "金叉+红柱放大"
            elif dif_v > dea_v and hist_v > 0:
                macd_s = 70; macd_label = "DIF>DEA+红柱"
            elif abs(dif_v - dea_v) < abs(dif[-1]) * 0.005:
                macd_s = 55; macd_label = "DIF/DEA粘合"
            elif dif_v < dea_v and hist_v < 0:
                macd_s = 35; macd_label = "DIF<DEA+绿柱"
            elif cross_dn and div_top:
                macd_s = 12; macd_label = "死叉+顶背离"
            else:
                macd_s = 50; macd_label = "中性"
            # ========== 因子5: 多周期均线结构 (10%) ==========
            ma5 = sum(c_arr[-5:])/5; ma10 = sum(c_arr[-10:])/10
            ma20_v = mb  # 复用上面
            ma60_v = sum(c_arr[-60:])/60
            ma120_v = sum(c_arr[-120:])/120 if len(c_arr) >= 120 else ma60_v
            # 完整多头：5>10>20>60>120
            if cur > ma5 > ma10 > ma20_v > ma60_v > ma120_v:
                ma_s = 95; ma_label = "完整多头排列"
            elif cur > ma5 and cur > ma10 and cur > ma20_v and cur > ma60_v:
                ma_s = 80; ma_label = "5/10/20多头+站稳60"
            elif (cur > ma60_v and cur < ma20_v) or (cur > ma20_v and cur < ma60_v):
                ma_s = 55; ma_label = "均线交错震荡"
            elif cur < ma5 and cur < ma10 and cur < ma20_v and cur < ma60_v:
                ma_s = 35; ma_label = "5/10/20空头+跌破60"
            elif cur < ma5 and cur < ma10 and cur < ma20_v and cur < ma60_v and cur < ma120_v:
                ma_s = 12; ma_label = "全周期空头"
            else:
                ma_s = 50; ma_label = "中性"
            # ========== 因子6: 量能/量比 (10%) ==========
            if _has_vol:
                vol_cur = v_arr[-1]
                # 量比标准公式：今日成交量 / 前5日均量(不含今日)
                # 修复：原 vol_ma5 = sum(v_arr[-5:])/5 含今日，会导致偏离东方财富约10%
                vol_ma5 = sum(v_arr[-6:-1])/5 if len(v_arr) >= 6 else sum(v_arr[:-1])/max(len(v_arr)-1, 1)
                vol_ratio = vol_cur / vol_ma5 if vol_ma5 > 0 else 1.0
                if cur > ma5 and vol_ratio > 1.5:
                    vol_s = 95; vol_label = "低位放量上涨"
                elif cur > ma5 and vol_ratio >= 1.0:
                    vol_s = 80; vol_label = "上涨放量（量价齐升）"
                elif 0.8 <= vol_ratio <= 1.2:
                    vol_s = 57; vol_label = "量能中性"
                elif cur < ma5 and vol_ratio > 1.0:
                    vol_s = 35; vol_label = "下跌放量（量价背离）"
                elif cur < ma5 and vol_ratio > 1.5:
                    vol_s = 12; vol_label = "高位放量下跌（破位出货）"
                else:
                    vol_s = 50; vol_label = "中性"
            else:
                # vol 缺失：用 close 5日波动幅度作为代理
                if len(c_arr) >= 5:
                    rets = [(c_arr[-i] - c_arr[-i-1]) / c_arr[-i-1] for i in range(1, 5)]
                    avg_abs_ret = sum(abs(r) for r in rets) / 4
                else:
                    avg_abs_ret = 0
                if cur > ma5 and avg_abs_ret > 0.015:
                    vol_s = 80; vol_label = f"上涨+高波动({avg_abs_ret*100:.1f}%)"
                elif cur < ma5 and avg_abs_ret > 0.015:
                    vol_s = 35; vol_label = f"下跌+高波动({avg_abs_ret*100:.1f}%)"
                elif avg_abs_ret < 0.005:
                    vol_s = 65; vol_label = f"低波动({avg_abs_ret*100:.1f}%)"
                else:
                    vol_s = 50; vol_label = "中性"
            # ========== 加权汇总 ==========
            weights = {"GMMA":0.25, "ADX":0.20, "BOLL":0.20, "MACD":0.15, "MA":0.10, "VOL":0.10}
            sub_scores = {"GMMA":gmma_s, "ADX":adx_s, "BOLL":bb_s, "MACD":macd_s, "MA":ma_s, "VOL":vol_s}
            sub_labels = {"GMMA":gmma_label, "ADX":adx_label, "BOLL":bb_label, "MACD":macd_label, "MA":ma_label, "VOL":vol_label}
            us_score = round(sum(sub_scores[k] * weights[k] for k in weights), 1)
            us_score = max(20, min(80, us_score))
            # 区间定性
            if us_score >= 80: zone_t = "极致强底部"
            elif us_score >= 65: zone_t = "弱底部"
            elif us_score >= 45: zone_t = "中性震荡"
            elif us_score >= 30: zone_t = "弱顶部"
            else: zone_t = "极致强顶部"
            # 一句话核心结论
            core = sub_labels[max(sub_scores, key=lambda k: sub_scores[k])]
            # 详细 breakdown 文本
            bd_lines = [f"{k}={v['s']}{v['w']}+{int(round(v['s']*v['w']))}" for k,v in [
                ("GMMA顾比", {"s":gmma_s,"w":weights['GMMA']}),
                ("ADX趋势", {"s":adx_s,"w":weights['ADX']}),
                ("BOLL位置", {"s":bb_s,"w":weights['BOLL']}),
                ("MACD动能", {"s":macd_s,"w":weights['MACD']}),
                ("多周期均线", {"s":ma_s,"w":weights['MA']}),
                ("量能配合", {"s":vol_s,"w":weights['VOL']}),
            ]]
            us_breakdown = "｜".join(bd_lines)
            us_note = "SOX六维评分（数据：%s｜%d日｜%s）：GMMA %d｜ADX %d｜BOLL %d｜MACD %d｜MA %d｜VOL %d｜综合**%.1f**分（%s，核心：%s）" % (
                _sox_dates[-1][:10], len(c_arr), _sox_dates[-1][:10],
                gmma_s, adx_s, bb_s, macd_s, ma_s, vol_s, us_score, zone_t, core)
    except Exception as e:
        us_note = "SOX数据通道异常：%s" % str(e)[:60]

    # ---- 2) 全球流动性环境（25%）：10Y美债80% + 美元20% ----
    liq_score = 50; liq_note = "流动性数据待更新"
    try:
        if u10_c is not None:
            if u10_c < 4.5:
                liq_base = 75; liq_base_note = "美债10Y %.4f%%处宽松区间（＜4.5），流动性75分" % u10_c
            elif u10_c <= 4.8:
                liq_base = 50; liq_base_note = "美债10Y %.4f%%处中性区间（4.5-4.8），流动性50分" % u10_c
            else:
                liq_base = 25; liq_base_note = "美债10Y %.4f%%处收紧区间（＞4.8），流动性25分" % u10_c
            liq_adj = 0
            if dxy_chg is not None and abs(dxy_chg) > 1.0:
                liq_adj = 5 if dxy_chg > 0 else -5
                liq_base_note += "；美元单日%+.2f%%超阈值±%d分" % (dxy_chg, abs(liq_adj))
            liq_score = max(10, min(90, liq_base + liq_adj))
            liq_note = "%s（%s｜美元DXY %.2f %s）" % (liq_base_note, u10_d or "—", dxy_c or 0, dxy_d or "—")
    except Exception as e:
        pass

    # ---- 3) 外围波动率（15%）：VXN ----
    v_val = 50
    try: v_val = float(vxn_o.get("val", 50))
    except Exception: pass
    if v_val < 20: vxn_score = 80
    elif v_val <= 25: vxn_score = 70
    elif v_val <= 30: vxn_score = 50
    else: vxn_score = 30
    vxn_note = "VXN %.2f（%s，%s），对应" % (v_val, vxn_o.get("date","—"), vxn_o.get("chg","—")) + ("低恐慌" if vxn_score>=70 else "中性" if vxn_score==50 else "高恐慌")

    # ---- 4) 亚洲盘联动（10%）：恒生科技/KOSPI/日经 ----
    asia_score, asia_note = 50, "亚洲盘数据待更新"
    try:
        _aq = json.load(open(os.path.join(DATA, "asia_quotes.json"), encoding="utf-8"))
        chg_hk = _aq.get("hstech_chg", 0)  # 恒生科技 % (signed)
        chg_kospi = _aq.get("kospi_chg", 0)
        chg_n225 = _aq.get("n225_chg", 0)
        moves = [
            (chg_hk, 2.0, "恒生科技"),
            (chg_kospi, 1.5, "KOSPI"),
            (chg_n225, 1.2, "日经225")
        ]
        # 至少2个指数同向且超阈值
        up_count = sum(1 for v, th, _ in moves if v > th and v > 0)
        dn_count = sum(1 for v, th, _ in moves if v < -th and v < 0)
        if up_count >= 2:
            asia_score, asia_note = 70, "恒生科技%+.2f%%/KOSPI%+.2f%%/日经%+.2f%%，至少2个同向超阈值→偏多70分" % (chg_hk, chg_kospi, chg_n225)
        elif dn_count >= 2:
            asia_score, asia_note = 30, "恒生科技%+.2f%%/KOSPI%+.2f%%/日经%+.2f%%，至少2个同向超阈值→偏空30分" % (chg_hk, chg_kospi, chg_n225)
        else:
            asia_score, asia_note = 50, "恒生科技%+.2f%%/KOSPI%+.2f%%/日经%+.2f%%，多数处于中性区间→50分" % (chg_hk, chg_kospi, chg_n225)
    except Exception:
        asia_note = "亚洲盘数据通道待建立（KOSPI/日经需WebFetch抓Investing.com），暂取中性50分"

    overseas={
        "score":round(us_score*0.50+liq_score*0.25+vxn_score*0.15+asia_score*0.10,1),
        "subs":[
            {"name":"美股科技赛道信号","w":50,"score":us_score,"note":us_note+"（核心主导项）"},
            {"name":"全球流动性","w":25,"score":liq_score,"note":liq_note+"（美债171.US10Y80%+美元20%）"},
            {"name":"外围波动率","w":15,"score":vxn_score,"note":vxn_note+"（CBOE官方VXN）"},
            {"name":"亚洲盘联动","w":10,"score":asia_score,"note":asia_note},
        ]}
    # ---- 资金面（10%）：四级子指标量化规则 v2 ----	
    def pctile(vals, v):
        """历史分位：v在vals中的百分位（0=最低，100=最高），最少20个值"""
        if len(vals) < 20: return 50
        return round(sum(1 for x in vals if x < v) / len(vals) * 100, 1)

    # ---- 子指标1：两融杠杆趋势（35%）----	
    margin_score, margin_note = 50, "两融数据待更新"
    try:
        _mh = json.load(open(os.path.join(DATA, "margin_history.json"), encoding="utf-8"))
        mv, md = _mh["values"], _mh["dates"]
        mlatest, mprev = mv[-1], mv[-2]
        m_chg5 = (mv[-1] / mv[-min(6, len(mv))] - 1) * 100 if len(mv) >= 5 else 0
        m_pctile = pctile(mv, mlatest)  # 余额自身历史分位（代理杠杆率分位）
        if m_chg5 > 1:
            margin_score = 80 if m_pctile < 30 else 65
        elif 0.3 < m_chg5 <= 1:
            margin_score = 65
        elif -0.3 <= m_chg5 <= 0.3:
            margin_score = 50
        elif -1 <= m_chg5 < -0.3:
            margin_score = 35
        else:  # m_chg5 < -1
            margin_score = 20
        # 特殊约束：杠杆率处于历史70%分位以上，得分上限60
        if m_pctile >= 70:
            margin_score = min(margin_score, 60)
        margin_note = ("截至%s，两融余额%.0f亿，近5日累计%+.2f%%；余额历史分位%.1f%%（杠杆率代理）"
                       % (md[-1], mlatest, m_chg5, m_pctile))
    except Exception:
        pass

    # ---- 子指标2：北向资金动向（20%）----
    # 代理双维度估值（交易所2024/8起停披露净买额）：
    #   60% 活跃度（成交额/20日均值比）+ 40% 边际方向（北向重仓指数超额收益 vs 沪深300）
    nb_act_score, nb_dir_score = 50, 50
    nb_act_note, nb_dir_note = "", ""
    try:
        _nh = json.load(open(os.path.join(DATA, "northbound_history.json"), encoding="utf-8"))
        nt, nd = _nh["total"][-1], _nh["dates"][-1]
        avg20 = sum(_nh["total"][-20:]) / min(20, len(_nh["total"]))
        act_ratio = nt / avg20 * 100
        if act_ratio > 120:
            nb_act_score = 70
            nb_act_note = "成交额%.0f亿/20日均值%.0f亿=%.0f%%，高活跃度→70分" % (nt, avg20, act_ratio)
        elif act_ratio >= 80:
            nb_act_score = 50
            nb_act_note = "成交额%.0f亿/20日均值%.0f亿=%.0f%%，中性活跃度→50分" % (nt, avg20, act_ratio)
        else:
            nb_act_score = 30
            nb_act_note = "成交额%.0f亿/20日均值%.0f亿=%.0f%%，低活跃度→30分" % (nt, avg20, act_ratio)
    except Exception:
        nb_act_note = "活跃度数据待更新"

    try:
        # 北向重仓加权：沪股通指数000159(腾讯qt可用) + 深证成指399001代理深股通指数（腾讯qt无深股通指数独立代码，399634映射为中小等权）
        _qt = open(os.path.join(DATA, "index_quote.txt"), encoding="utf-8", errors="ignore").read()
        _shgt, _szgt, _hs300 = 0, 0, 0
        for line in _qt.splitlines():
            line = line.strip()
            if '="' not in line: continue
            code = line.split("=", 1)[0].strip().lstrip("v_")
            p = line.split('="', 1)[1].strip('";').split("~")
            if len(p) <= 32: continue
            if code == "sh000159": _shgt = float(p[32])
            if code == "sz399001": _szgt = float(p[32])
            if code == "sh000300": _hs300 = float(p[32])
        # 数据异常校验：两市指数涨跌幅均≈0%→判定抓取异常
        if abs(_shgt) < 0.01 and abs(_szgt) < 0.01:
            raise ValueError("两市涨跌幅均≈0%，数据异常")
        # 沪/深占比按当日北向成交额分拆
        _nh = json.load(open(os.path.join(DATA, "northbound_history.json"), encoding="utf-8"))
        sh_turnover = _nh["sh"][-1]; sz_turnover = _nh["sz"][-1]
        total = sh_turnover + sz_turnover or 1
        sh_w, sz_w = sh_turnover / total, sz_turnover / total
        nb_weighted = _shgt * sh_w + _szgt * sz_w
        excess = nb_weighted - _hs300
        if excess > 1:
            nb_dir_score, nb_dir_note = 70, "沪股通%+.2f%%(权%.0f%%)+深证成指%+.2f%%(权%.0f%%)=%.2f%%, 超额%.2f%%→边际偏多70分" % (_shgt, sh_w*100, _szgt, sz_w*100, nb_weighted, excess)
        elif excess >= -1:
            nb_dir_score, nb_dir_note = 50, "沪股通%+.2f%%(权%.0f%%)+深证成指%+.2f%%(权%.0f%%)=%.2f%%, 超额%.2f%%→方向中性50分" % (_shgt, sh_w*100, _szgt, sz_w*100, nb_weighted, excess)
        else:
            nb_dir_score, nb_dir_note = 30, "沪股通%+.2f%%(权%.0f%%)+深证成指%+.2f%%(权%.0f%%)=%.2f%%, 超额%.2f%%→边际偏空30分" % (_shgt, sh_w*100, _szgt, sz_w*100, nb_weighted, excess)
        # 保存本期有效超额收益（供异常兜底）
        json.dump({"excess": round(excess, 2), "date": _nh["dates"][-1]},
                  open(os.path.join(DATA, "nb_excess_last.json"), "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        # 异常兜底：读取最近一期有效超额
        nb_dir_score, nb_dir_note = 50, "边际方向数据抓取异常"
        try:
            _last = json.load(open(os.path.join(DATA, "nb_excess_last.json"), encoding="utf-8"))
            _ex = _last["excess"]
            nb_dir_score, nb_dir_note = (70 if _ex > 1 else 50 if _ex >= -1 else 30), \
                "数据异常，沿用上期(%s)有效超额%.2f%%→%d分" % (_last["date"], _ex, nb_dir_score)
        except Exception:
            pass

    nb_score = round(nb_act_score * 0.6 + nb_dir_score * 0.4, 1)
    nb_note = "北向综合=活跃度%d×60%%+方向%d×40%%=%d分（代理打分，2024/8起交易所停披露净买额）。%s｜%s" % (
        nb_act_score, nb_dir_score, nb_score, nb_act_note, nb_dir_note)

    # ---- 子指标3：宏观流动性环境（20%）----	
    # 优先：DR007加权平均利率 vs 7天逆回购政策利率1.40%的利差
    # 过渡代理：央行OMO连续3日净投放/回笼（DR007不可得时启用）
    macro_score, macro_note = 50, ""
    try:  # 从data/dr007.json读取最近DR007值（若已建通道）
        _dr = json.load(open(os.path.join(DATA, "dr007.json"), encoding="utf-8"))
        dr, dr_date = _dr["value"], _dr["date"]
        policy = 1.40
        spread = dr - policy  # bps
        if spread < -0.10:
            macro_score, macro_note = 70, "DR007 %.4f%%（%s）低于政策利率1.40%%超10bp，资金面宽松" % (dr, dr_date)
        elif spread > 0.10:
            macro_score, macro_note = 30, "DR007 %.4f%%（%s）高于政策利率1.40%%超10bp，资金面收紧" % (dr, dr_date)
        else:
            macro_score, macro_note = 50, "DR007 %.4f%%（%s）围绕政策利率1.40%%在±10bp内波动，资金面中性" % (dr, dr_date)
        # 重大调整：正式降息+20分，正式加息-20分（若发生需手动标记）
    except Exception:
        # 过渡代理：OMO连续3日净投放/回笼（新闻中提取，手动维护）
        try:
            _omo = json.load(open(os.path.join(DATA, "omo.json"), encoding="utf-8"))
            omo_net, omo_note = _omo["net3d"], _omo["note"]
            if omo_net > 500:
                macro_score, macro_note = 60, "OMO过渡代理：连续3日净投放%.0f亿＞500亿→60分（%s）" % (omo_net, omo_note)
            elif omo_net < -500:
                macro_score, macro_note = 40, "OMO过渡代理：连续3日净回笼%.0f亿＞500亿→40分（%s）" % (abs(omo_net), omo_note)
            else:
                macro_score, macro_note = 50, "OMO过渡代理：连续3日净投放/回笼在±500亿内→50分（%s）" % omo_note
        except Exception:
            macro_note = "DR007/OMO数据通道均待建立；当前7天逆回购政策利率1.40%持稳、MLF未调整，取中性50分"

    # ---- 子指标4：场内机构资金（20%）----	
    inst_score, inst_note = 50, ""
    try:  # 从 etf_flow.json 读取近3日权益ETF净申购额
        _ef = json.load(open(os.path.join(DATA, "etf_flow.json"), encoding="utf-8"))
        etf3d, ef_date = _ef["net3d"], _ef["date"]
        if etf3d > 100:
            inst_score = 80
        elif etf3d > 30:
            inst_score = 65
        elif etf3d >= -30:
            inst_score = 50
        elif etf3d > -100:
            inst_score = 35
        else:
            inst_score = 20
        inst_note = "近3日权益ETF累计净申购%+.0f亿（截至%s）" % (etf3d, ef_date)
        # 周度新成立基金修正
        if _ef.get("weekly_new_fund"):
            wf = _ef["weekly_new_fund"]
            if wf > 300:
                inst_score += 5; inst_note += "；周度新成立权益基金>300亿→+5分"
            elif wf < 50:
                inst_score -= 5; inst_note += "；周度新成立权益基金<50亿→-5分"
            inst_score = max(0, min(100, inst_score))
    except Exception:
        inst_note = "权益ETF净申购额数据通道待建立，按规则取中性基准分50分"
    # 若有降息事件，直接+20分；加息则-20分

    capital = {
        "score": round(margin_score * 0.35 + nb_score * 0.20 + macro_score * 0.20 + inst_score * 0.25, 1),
        "subs": [
            {"name": "两融杠杆趋势", "w": 35, "score": margin_score, "note": margin_note},
            {"name": "北向资金动向", "w": 20, "score": nb_score, "note": nb_note},
            {"name": "宏观流动性环境", "w": 20, "score": macro_score, "note": macro_note},
            {"name": "场内机构资金", "w": 25, "score": inst_score, "note": inst_note},
        ]}
    # 解禁供给事件（从额外加减分撤离，归入资金面）
    try:
        _uf = json.load(open(os.path.join(DATA, "unlock_future.json"), encoding="utf-8"))
        if any(w["amt"] >= 500 for w in _uf.get("bigWeeks", [])):
            wtxt = "/".join("%s（%d亿）" % (w["week"], w["amt"]) for w in _uf["bigWeeks"][:2])
            capital["score"] = round(capital["score"] - 2, 1)
            capital["subs"].append({"name": "限售解禁供给压力", "w": 0, "score": -2,
                "note": "解禁超500亿阈值：%s，-2分（已从额外加减分撤离至资金面）" % wtxt})
    except Exception:
        pass
    # ---- 基本面与消息面（10%）v2：三级分级+交易日衰减+看板分类映射 ----
    def news_level(it):
        """S/A/C分级：S=major红星(±10)；A=利好/利空但非红星(±5)；C=中性/关注(0,过滤)"""
        imp = it.get("impact")
        if imp not in ("利好", "利空"): return 0, ""
        if it.get("major"):
            return (10 if imp == "利好" else -10), "S"
        return (5 if imp == "利好" else -5), "A"
    def is_domestic_pol(it):
        """判断行业政策消息是国内政策还是涉外监管。"""
        text = it.get("title", "") + "|" + it.get("src", "")
        kw_foreign = ["FCC", "美国", "欧盟", "欧盟委员会", "海外", "中美", "实体清单", "关税", "管制",
                      "限制", "法案", "反制", "合规测试", "对等", "部长", "禁令", "进口管制"]
        for k in kw_foreign:
            if k in text: return False
        return True
    def news_trading_days_today(today_str):
        """交易日历（上市日期→计数索引），用于时间衰减的T-N判定。"""
        try:
            d = json.load(open(os.path.join(DATA, "szzs_full.json"), encoding="utf-8"))["data"]["sh000001"]
            cal = [r[0] for r in (d.get("day") or d.get("qfqday"))]
            return {d: i for i, d in enumerate(cal)}
        except Exception:
            return {}
    def decay_weight(item_date, horizon, cal_idx):
        """根据消息日期距离today的交易日数，返回衰减权重（0/30%/60%/100%）。"""
        if item_date not in cal_idx: return 0
        days_diff = cal_idx.get(today_str, 0) - cal_idx[item_date]
        h = horizon if horizon in ("近期", "中期", "长期") else "近期"
        if h == "近期":   # T-0=100%, T-1=70%, T-2=40%, T-3+=0
            return {0: 1.0, 1: 0.7, 2: 0.4}.get(days_diff, 0)
        elif h == "中期":  # T-3=100%, T-4~T-7=60%, T-8~T-10=30%, T-11+=0
            if days_diff <= 3: return 1.0
            if days_diff <= 7: return 0.6
            if days_diff <= 10: return 0.3
            return 0
        else:  # 长期: T-10=100%, T-11~T-20=60%, T-21~T-30=30%, T-31+=0
            if days_diff <= 10: return 1.0
            if days_diff <= 20: return 0.6
            if days_diff <= 30: return 0.3
            return 0
    def event_key(it):
        """同事件去重key：标题前12字。"""
        return it.get("title", "")[:12]
    def fmt_evidence(scored_list, top_n=3):
        """输出Top N核心事件证据，按权重降序。"""
        scored_list.sort(key=lambda x: (-x[2], -abs(x[0])))  # 先按权重，再按分值绝对值
        lines = []
        for pts, it, w, lv in scored_list[:top_n]:
            lines.append('[%s] %s | %s级 | %s | %.0f%%' % (
                it.get("date", "")[:10], it.get("title", "")[:32], lv,
                it.get("horizon", "近期"), w * 100))
        return "\n".join(lines) if lines else "当日无新增有效消息"

    # 当前评估日 = 数据最后一笔交易日（避免日历时差）
    cal_idx = news_trading_days_today(None)
    today_str = max(cal_idx.keys()) if cal_idx else time.strftime("%Y-%m-%d")
    ind_score, pol_score, reg_score = 50, 50, 50
    ind_lines, pol_lines, reg_lines = "", "", ""
    try:
        _news = json.load(open(os.path.join(DATA, "news.json"), encoding="utf-8"))
        # 按子指标分类收集（S/A级才计分；C级过滤）
        ind_scored, pol_scored, reg_scored = [], [], []
        seen_ind, seen_pol, seen_reg = set(), set(), set()
        for cat in _news.get("categories", []):
            cname = cat["name"]
            for it in cat.get("items", []):
                pts, lv = news_level(it)
                if pts == 0: continue  # C级过滤
                ekey = event_key(it)
                w = decay_weight(it.get("date", ""), it.get("horizon", "近期"), cal_idx)
                if w == 0: continue  # 已过衰减期
                # 分类映射
                if cname in ("重要技术突破", "国内龙头企业", "美股科技七巨头"):
                    if ekey in seen_ind: continue  # 同事件去重
                    seen_ind.add(ekey)
                    ind_scored.append([pts, it, w, lv])
                elif cname == "行业政策":
                    if is_domestic_pol(it):
                        if ekey in seen_pol: continue
                        seen_pol.add(ekey)
                        pol_scored.append([pts, it, w, lv])
                    else:
                        if ekey in seen_reg: continue
                        seen_reg.add(ekey)
                        reg_scored.append([pts, it, w, lv])
        # 子指标得分 = 50 + Σ(基础分×权重)，并裁剪到[20, 90]
        for sub_scored, sub_name in [(ind_scored, "产业景气验证"), (pol_scored, "政策面"), (reg_scored, "监管与外部扰动")]:
            pass
        ind_total = sum(pts * w for pts, _, w, _ in ind_scored)
        pol_total = sum(pts * w for pts, _, w, _ in pol_scored)
        reg_total = sum(pts * w for pts, _, w, _ in reg_scored)
        ind_score = max(20, min(90, 50 + round(ind_total, 1)))
        pol_score = max(20, min(90, 50 + round(pol_total, 1)))
        reg_score = max(20, min(90, 50 + round(reg_total, 1)))
        ind_lines = fmt_evidence(ind_scored)
        pol_lines = fmt_evidence(pol_scored)
        reg_lines = fmt_evidence(reg_scored)
    except Exception as e:
        ind_lines, pol_lines, reg_lines = ("数据源异常：" + str(e)[:30]), "政策面数据异常", "监管数据异常"
    _fund_event_keys = seen_ind | seen_pol | seen_reg  # extras去重用
    fund = {
        "score": round(ind_score * 0.45 + pol_score * 0.35 + reg_score * 0.20, 1),
        "subs": [
            {"name": "产业景气验证", "w": 45, "score": ind_score, "note": ind_lines},
            {"name": "政策面", "w": 35, "score": pol_score, "note": pol_lines},
            {"name": "监管与外部扰动", "w": 20, "score": reg_score, "note": reg_lines},
        ]}
    # 额外加减分（直调基本面与消息面维度总分，合计限±5分）
    # ---------- 仅用于常规三子指标覆盖不到的、超预期的全市场/行业级极端事件 ----------
    extras_items = []
    _dir = os.path.dirname(os.path.abspath(__file__))
    # 交易日历，用于时间衰减
    def trading_days_since(date_str):
        try:
            _d = json.load(open(os.path.join(_dir, "data", "szzs_full.json"), encoding="utf-8"))["data"]["sh000001"]
            _day = _d.get("day") or _d.get("qfqday")
            cal = [r[0] for r in _day]
            ds = date_str[:10]
            return sum(1 for d in cal if d > ds)
        except Exception:
            return 0
    # 2026-08-10 修订：时效性规则（严格遵守）
    #   - 「近期/短期」消息：消息发布当日+次日的计分周期内可计入，超过不再纳入
    #   - 「中期」消息：仅允许在消息发布后1个交易日内完成边际修正，延后不得超过2个交易日
    #   - 「长期」消息：发布后30个交易日内均可计入
    DECAY = {"近期": 1, "短期": 1, "中期": 2, "长期": 30, "远期": 30}

    # ---- 极度加/减分触发关键词（仅极少数场景，不含已在三子指标中的常规事件）----
    # 加分触发：国务院级政策/超预期产业引爆/全球系统性宽松
    _PLUS_KW = ["国务院级", "部委联动", "超预期降息50bp", "超预期降息50个基点",
                "美联储超预期降息", "全球系统性宽松", "史无前例", "全市场直接利好"]
    # 减分触发：全行业制裁/地缘冲突/IPO超300亿/超大规模解禁/全球系统性紧缩
    _MINUS_KW = ["极端制裁", "地缘冲突", "黑天鹅", "单周IPO超300", "超大规模解禁",
                 "超预期加息50bp", "超预期加息50个基点", "美联储超预期加息", "全球系统性收紧",
                 "全面断供", "不可抗力停产"]
    # 加分额外分值
    def extra_pts(impact, title):
        """返回 (分值, 是否破格标注)。仅在触发关键词时生效。"""
        if impact == "利好":
            if any(k in title for k in _PLUS_KW):
                return 3, True
            return 2, False  # 其余行业级利好为A级2分
        if impact == "利空":
            if any(k in title for k in _MINUS_KW):
                return -3, True
            return -2, False
        return 0, False


    # 2026-08-10 v4.1 重大修订：在 v4 分档基础上叠加"同赛道上限±3"与"草案传闻特殊处理"
    #   - 保留：分档（±3极端 / ±2重要 / ±1次要）、总限±5、时间衰减、自动去重
    #   - 新增1：同赛道内部上限 ±3 分（防同一产业链多条消息扎堆放大）
    #   - 新增2：草案/传闻类事件须赛道单日|涨跌幅|≥3% 才允许 ±2 入池；不得直接使用 ±3；标记【草案传闻，未正式落地】
    #   - 新增3：利空词库补齐（禁令/管制/制裁/出口限制/草案征求意见/业绩下修/亏损/召回/调查/驳回）
    #   - 新增4：已在基本面三子指标 → 跳过；无法自动判断 → 强制置0需人工复核
    news_file = os.path.join(_dir, "data", "news.json")
    extras_stats = {"total_in_pool": 0, "scoring": 0, "display_only": 0, "human_review": 0,
                    "filter_fund": 0, "filter_track_cap": 0, "filter_tier": 0,
                    "filter_draft": 0, "filter_no_impact": 0, "filter_duplicate": 0,
                    "filter_window": 0, "filter_banned": 0, "filter_result": 0,
                    "filter_newfact": 0}

    # ====== 读取赛道最新日涨跌幅（草案类事件判定：单日|涨跌|≥3%才允许入池）======
    _track_chg = {}
    try:
        for trk_name, fp in [("半导体设备", "data/bk1326_raw.json"),
                              ("存储芯片", "data/bk1137_raw.json"),
                              ("光通信模块", "data/bk1136_raw.json")]:
            full = os.path.join(_dir, fp)
            if os.path.exists(full):
                j = json.load(open(full, encoding="utf-8"))
                ks = j.get("klines") or []
                if ks:
                    last = ks[-1].split(",")  # date,open,close,high,low,vol
                    chg = (float(last[2]) - float(last[1])) / float(last[1]) * 100 if float(last[1]) else 0
                    _track_chg[trk_name] = chg
    except Exception:
        pass

    # ====== 消息→赛道归属映射（v4.1 防扎堆基础）======
    def _track_of(item):
        """返回该消息所属赛道：半导体设备/存储芯片/光通信/算力服务器/其他"""
        cat = (item.get("category") or "").strip()
        title = item.get("title", "")
        cat_map = {
            "国内龙头企业 - 半导体设备": "半导体设备",
            "国内龙头企业 - 存储芯片": "存储芯片",
            "国内龙头企业 - 光通信模块": "光通信模块",
            "美股科技龙头 - 半导体设备": "半导体设备",
            "美股科技龙头 - 存储芯片": "存储芯片",
            "美股科技龙头 - 光通信": "光通信",
            "美股科技龙头 - 算力服务器": "算力服务器",
        }
        if cat in cat_map:
            return cat_map[cat]
        if any(k in title for k in ["半导体设备", "刻蚀", "薄膜沉积", "PECVD", "CMP", "测试机", "量检测",
                                       "北方华创", "中微", "拓荆", "华海清科", "长川科技", "中科飞测"]):
            return "半导体设备"
        if any(k in title for k in ["存储芯片", "DRAM", "HBM", "NAND", "长鑫", "兆易",
                                       "佰维存储", "普冉", "德明利", "江波龙", "美光", "海力士", "西部数据", "三星"]):
            return "存储芯片"
        if any(k in title for k in ["光通信", "CPO", "光模块", "光迅科技", "中际旭创", "新易盛", "天孚通信"]):
            return "光通信"
        if any(k in title for k in ["算力", "服务器", "数据中心", "AI服务器", "AI芯片", "英伟达", "GB300", "Vera"]):
            return "算力服务器"
        return "其他"

    # ====== 草案/传闻类事件关键词（v4.1 新增）======
    _DRAFT_KW = ["草案", "征求意见", "传闻", "酝酿", "据传", "据知情", "FCC草案",
                 "即将发布", "拟", "有望", "或将", "可能", "预期", "业界预计",
                 "产业链消息", "据路透", "据彭博", "据华尔街", "据日经", "据韩联社", "据共同社",
                 "据悉", "消息人士", "据消息", "知情人士"]
    _FORMAL_KW = ["签署", "正式发布", "正式落地", "正式生效", "正式实施", "正式公告",
                  "正式公布", "落地", "生效", "已发布", "已实施", "已落地", "已生效",
                  "已签署", "签署生效", "已正式", "最终裁定", "终裁", "终审判决",
                  "终局裁决", "据公告", "财报", "业绩公告", "季报"]

    if os.path.exists(news_file):
        try:
            _news = json.load(open(news_file, encoding="utf-8"))
            seen_keys = {}
            # 校验1：股价结果类（行情复盘）永久不允许入池
            _RESULT_KW = ["兑现式", "业绩兑现", "重挫", "暴跌", "崩盘", "站稳MA", "底背离", "连续", "站稳"]
            _BANNED_KW = [
                "美股存储股业绩兑现式重挫",
                "伯恩斯坦7月存储价格追踪",
                "站稳MA5", "底背离强确认", "连续7日", "连续6日",
            ]
            _DUPLICATED_KW = [
                "九转", "MA5", "MA20", "布林", "GMMA", "ADX",
                "外围", "美股科技反弹", "海外",
                "融资", "两融", "北向", "净流入", "净流出", "板块分化",
                "个股涨", "个股跌", "涨跌幅", "板块上涨", "板块下跌", "主力资金净",
            ]
            _NEW_FACT_KW = [
                "签署", "行政令", "法案", "工信部", "发改委", "国务院", "商务部", "财政部", "证监会",
                "出口管制", "关税", "制裁", "禁令", "反垄断",
                "营收", "净利", "财报", "订单", "招标", "中标", "签约",
                "Q1", "Q2", "Q3", "Q4", "季度新高", "半年报", "年报",
                "收购", "并购", "定增", "重组", "上市", "融资", "募资",
                "产品发布", "量产", "技术突破", "良率", "工艺", "流片",
                "首颗", "首款", "首台",
                "纳入", "权重", "调入",
                "涨价", "跌价", "供需", "缺口", "拐点", "增速",
                "砍配", "砍HBM", "HBM配置", "数据", "统计",
                # v4.1 利空词库补齐
                "管制草案", "管制", "出口限制", "草案征求意见",
                "业绩下修", "亏损", "召回", "调查", "驳回",
            ]
            # ±3 极端事件
            _EXTREME_PLUS_KW = [
                "国务院级", "黑天鹅", "全球系统性宽松", "全市场直接利好",
                "极端制裁", "地缘冲突", "出口管制", "全面断供", "不可抗力停产",
            ]
            _EXTREME_MINUS_KW = [
                "极端制裁", "黑天鹅", "地缘冲突", "全面断供", "不可抗力停产",
                "出口管制", "全球系统性收紧", "美联储超预期加息",
            ]
            # ±2 重要边际修正
            _KEY_PLUS_KW = [
                "工信部", "国务院", "发改委", "财政部", "商务部", "证监会",
                "纳入", "定增", "并购", "收购", "重组",
                "份额", "营收", "净利", "财报", "Q1", "Q2", "Q3", "Q4", "季度新高",
                "砍配", "砍HBM", "HBM配置", "涨价",
                "突破", "首次", "首颗", "首款",
            ]
            _KEY_MINUS_KW = [
                "禁令", "法案", "制裁", "出口管制", "管制草案", "管制",
                "极端制裁", "黑天鹅",
                "跌价", "砍配", "砍HBM", "下滑", "下修",
                "禁运", "断供", "短缺",
                # v4.1 利空词库补齐
                "出口限制", "草案征求意见", "业绩下修", "亏损", "召回", "调查", "驳回",
            ]
            # ±1 次要催化
            _MINOR_PLUS_KW = ["增长", "上调", "支持", "扩大", "提升", "上升", "改善"]
            _MINOR_MINUS_KW = ["下降", "下调", "减少", "回落", "下滑", "下修", "亏损", "收缩"]
            SCORING_WINDOW = {"短期": 2, "中期": 3, "长期": 30, "近期": 2, "远期": 30}
            DECAY = {"近期": 3, "短期": 3, "中期": 10, "长期": 30, "远期": 30}

            def extra_pts_v41(impact, title, is_draft):
                """v4.1：草案事件强制封顶±2（不得±3）
                返回 (分值, 档位, 极端标记, 草案标记, 复核标记)
                """
                if impact == "利好":
                    if not is_draft and any(k in title for k in _EXTREME_PLUS_KW):
                        return 3, "extreme", True, False, False
                    if any(k in title for k in _KEY_PLUS_KW):
                        return 2, "key", False, is_draft, False
                    if any(k in title for k in _MINOR_PLUS_KW):
                        return 1, "minor", False, is_draft, False
                    return 0, "none", False, is_draft, False
                if impact == "利空":
                    if not is_draft and any(k in title for k in _EXTREME_MINUS_KW):
                        return -3, "extreme", True, False, False
                    if any(k in title for k in _KEY_MINUS_KW):
                        return -2, "key", False, is_draft, False
                    if any(k in title for k in _MINOR_MINUS_KW):
                        return -1, "minor", False, is_draft, False
                    return 0, "none", False, is_draft, False
                return 0, "none", False, is_draft, False

            # 第一遍：筛选通过三重校验的消息（不应用同赛道上限）
            pass1 = []
            for cat in _news.get("categories", []):
                for it in cat.get("items", []):
                    extras_stats["total_in_pool"] += 1
                    title = it.get("title", "")
                    impact = it.get("impact", "中性")
                    horizon = it.get("horizon", "近期")
                    days_since = trading_days_since(it.get("date", ""))
                    track = _track_of(it)

                    # 校验1：永久剔除
                    if any(b in title for b in _BANNED_KW):
                        extras_stats["filter_banned"] += 1
                        extras_stats["display_only"] += 1
                        continue

                    # 校验1-b：股价结果类（行情复盘）
                    if impact == "中性" or any(kw in title for kw in _RESULT_KW):
                        extras_stats["filter_result"] += 1
                        extras_stats["display_only"] += 1
                        continue

                    # 校验1-c：必须有 impact 利好/利空
                    if impact not in ("利好", "利空"):
                        extras_stats["filter_no_impact"] += 1
                        extras_stats["display_only"] += 1
                        continue

                    # 校验1-d：必须命中"新增边际事实"
                    if not any(kw in title for kw in _NEW_FACT_KW):
                        extras_stats["filter_newfact"] += 1
                        extras_stats["display_only"] += 1
                        continue

                    # 校验2：与已统计维度的关键词不重复
                    if any(kw in title for kw in _DUPLICATED_KW):
                        extras_stats["filter_duplicate"] += 1
                        extras_stats["display_only"] += 1
                        continue

                    # 校验3：时间窗口
                    win = SCORING_WINDOW.get(horizon, 3)
                    if days_since > win:
                        extras_stats["filter_window"] += 1
                        extras_stats["display_only"] += 1
                        continue

                    # 校验4：标题前12字符去重
                    ekey = title[:12]
                    if ekey in seen_keys:
                        extras_stats["filter_duplicate"] += 1
                        extras_stats["display_only"] += 1
                        continue
                    seen_keys[ekey] = True

                    # 校验5：已在基本面三子指标中计分 → 跳过（v4.1 强化）
                    if ekey in _fund_event_keys:
                        extras_stats["filter_fund"] += 1
                        extras_stats["display_only"] += 1
                        continue

                    # ====== v4.1 新增：判定草案/传闻 ======
                    is_draft = any(k in title for k in _DRAFT_KW) and not any(k in title for k in _FORMAL_KW)
                    if is_draft:
                        chg = _track_chg.get(track, 0)
                        if impact == "利好":
                            # 利好草案要求板块当日起码+3%
                            if abs(chg) < 3 or chg < 0:
                                extras_stats["filter_draft"] += 1
                                extras_stats["display_only"] += 1
                                continue
                        else:
                            # 利空草案要求板块当日起码-3%
                            if abs(chg) < 3 or chg > 0:
                                extras_stats["filter_draft"] += 1
                                extras_stats["display_only"] += 1
                                continue
                        # 草案类强制中期窗口（10个交易日）
                        if horizon == "短期":
                            horizon = "中期"

                    # 评分赋值
                    pts, tier, exceptional, draft, need_review = extra_pts_v41(impact, title, is_draft)
                    if pts == 0:
                        extras_stats["filter_tier"] += 1
                        extras_stats["display_only"] += 1
                        continue
                    # 安全网：草案事件即便is_draft=False也强制校验
                    if is_draft and tier == "extreme":
                        extras_stats["filter_draft"] += 1
                        extras_stats["display_only"] += 1
                        continue

                    extras_stats["scoring"] += 1
                    if need_review:
                        extras_stats["human_review"] += 1
                        pts_for_calc = 0  # v4.1：需人工复核分值强制置0
                    else:
                        pts_for_calc = pts

                    tier_label = {"extreme": "极端事件", "key": "重要边际修正", "minor": "次要催化"}[tier]
                    flags = []
                    if draft:
                        flags.append("草案传闻，未正式落地")
                    if need_review:
                        flags.append("需人工复核（强制置0）")
                    if exceptional:
                        flags.append("超预期/极端")
                    flag_str = "｜".join(flags) if flags else ""
                    reason = "%s｜%s｜%s｜赛道=%s｜%d交易日前→%+d分%s" % (
                        it.get("src", "消息面"), horizon, tier_label,
                        track, days_since, pts,
                        ("｜%s" % flag_str) if flag_str else "")

                    pass1.append({
                        "type": "加分" if pts > 0 else "减分",
                        "points": pts,
                        "points_for_calc": pts_for_calc,
                        "title": title,
                        "time": it.get("date", ""),
                        "horizon": horizon,
                        "tier": tier,
                        "tier_label": tier_label,
                        "exceptional": exceptional,
                        "is_draft": draft,
                        "need_review": need_review,
                        "track": track,
                        "track_chg": _track_chg.get(track, 0),
                        "reason": reason,
                    })

            # ====== 第二遍：同赛道内部上限 ±3 ======
            from collections import defaultdict
            track_buckets = defaultdict(list)
            for it in pass1:
                track_buckets[it["track"]].append(it)

            scored = []
            for track, items in track_buckets.items():
                if track == "其他":
                    # 其他赛道不受同赛道封顶限制
                    for it in items:
                        scored.append(dict(it, _track_filtered=False))
                    continue
                same_sum = sum(it["points_for_calc"] for it in items)
                if abs(same_sum) <= 3:
                    for it in items:
                        scored.append(dict(it, _track_filtered=False))
                else:
                    # 按分值绝对值从大到小贪心保留，确保总和不超过±3
                    items_sorted = sorted(items, key=lambda x: -abs(x["points_for_calc"]))
                    running_sum = 0
                    keep = []
                    drop = []
                    for it in items_sorted:
                        new_sum = running_sum + it["points_for_calc"]
                        if abs(new_sum) <= 3:
                            keep.append(it)
                            running_sum = new_sum
                        else:
                            drop.append(it)
                    for it in keep:
                        scored.append(dict(it, _track_filtered=False))
                    for it in drop:
                        extras_stats["filter_track_cap"] += 1
                        scored.append(dict(it, _track_filtered=True))
            extras_items = scored
        except Exception:
            pass
    # 排序：被过滤的放最后
    extras_items.sort(key=lambda e: (
        1 if e.get("_track_filtered") else 0,
        -e["points"],
        str(e.get("time", ""))[::-1]
    ))
    # ====== 合计三层过滤：raw → 同赛道封顶后 → 全局±5封顶 ======
    # 注意：当前 v4.1 设计下，pass1 之后已应用"同赛道封顶"（filter_track_cap 已移除）；raw_total 已是"同赛道封顶后"
    raw_total = sum(e["points"] for e in extras_items if not e.get("_track_filtered"))
    plus_total = sum(e["points"] for e in extras_items if e["points"] > 0 and not e.get("_track_filtered"))
    minus_total = sum(e["points"] for e in extras_items if e["points"] < 0 and not e.get("_track_filtered"))
    capped_total = max(-5, min(5, raw_total))
    validation = ("v4.1 校验：共%d条进入看板；三重校验通过%d条；过滤拆分："
                  "已在基本面统计%d｜同赛道上限%d｜不满足事件等级%d｜草案未触发板块|涨跌|≥3%% %d｜"
                  "无利好/利空标签%d｜与已统计维度重复%d｜时间窗口外%d｜"
                  "永久剔除%d｜股价结果/中性%d｜新增边际事实不命中%d；"
                  "raw=%+d → 同赛道封顶后=%+d → 全局±5封顶=%+d；需人工复核%d条（强制置0）。") % (
        extras_stats["total_in_pool"], extras_stats["scoring"],
        extras_stats["filter_fund"], extras_stats["filter_track_cap"], extras_stats["filter_tier"],
        extras_stats["filter_draft"], extras_stats["filter_no_impact"],
        extras_stats["filter_duplicate"], extras_stats["filter_window"],
        extras_stats["filter_banned"], extras_stats["filter_result"], extras_stats["filter_newfact"],
        raw_total, raw_total, capped_total, extras_stats["human_review"])
    extras = {"items": extras_items,
              "total": capped_total,
              "raw_total": raw_total,
              "plus_total": plus_total,
              "minus_total": minus_total,
              "note": "" if extras_items else "本期无触发（无超出三子指标覆盖范围的超预期/极端事件）",
              "validation": validation,
              "stats": extras_stats,
              "tier_desc": ("v4.1 分档：±3 极端事件（进出口禁令/重大产业政策突变/地缘黑天鹅/行业突发重大危机）；"
                            "±2 重要边际修正（财报/份额/行业数据/管制草案）；±1 次要催化。"
                            "三层过滤：raw → 同赛道内部上限±3 → 全局±5封顶。"
                            "草案/传闻类事件：必须赛道单日|涨跌|≥3%%才允许±2入池（不得±3），强制中期窗口，标记【草案传闻，未正式落地】。"
                            "利空词库：禁令/管制/制裁/出口限制/草案征求意见/业绩下修/亏损/召回/调查/驳回。"
                            "已在基本面三子指标 → 跳过；无法自动判断 → 强制置0需人工复核。"
                            "时间衰减：短期≤2日/中期≤3日/长期≤30日；草案类强制中期。")}
    composite=round(tech*0.55+overseas["score"]*0.25+capital["score"]*0.10+(fund["score"]+extras["total"])*0.10,1)
    zone="极致强底部区" if composite>80 else "弱底部区" if composite>65 else "中性震荡区" if composite>45 else "弱顶部区" if composite>30 else "极致强顶部区"

    def dimsubs(dim, note_extra=""):
        return dim["subs"]

    result={
        "composite":composite,"zone":zone,
        "tech":{"score":tech,"trackAvg":track_avg,"wideAvg":wide_avg,
                "trackScores":{t:s["score"] for t,s in track_scores.items()},
                "wideScores":{k:s["score"] for k,s in wide_scores.items()},
                "trackDetail":{t:track_scores[t]["subs"] for t in track_scores},
                "wideDetail":{k:wide_scores[k]["subs"] for k in wide_scores},
                "trackCounts":{t:{"up":track_scores[t]["curUp"],"down":track_scores[t]["curDown"]} for t in track_scores},
                "wideCounts":{k:{"up":wide_scores[k]["curUp"],"down":wide_scores[k]["curDown"]} for k in wide_scores}},
        "overseas":overseas,"capital":capital,"fund":fund,"extras":extras,
        "ruleNote":"技术面=赛道指数70%×宽基30%；九转仅触9计分（6-8计数只关注）；外围核心指标主导不对冲；北向暂停日度披露按中性；加减分直调总分。【2026-08-10 v4修订】加减分严格分级：±3 极端事件（进出口禁令/重大产业政策突变/地缘黑天鹅/行业突发重大危机；普通行业景气/财报数据不得用±3）；±2 重要边际修正（财报/份额/行业数据超预期）；±1 次要催化；利好利空均衡采集；合计限±5分；与基本面三子指标自动去重（已在消息面收录的跳过）；时间衰减：短期≤2日/中期≤3日/长期≤30日。",
    }
    with open(os.path.join(DATA,"score_result.json"),"w",encoding="utf-8") as f:
        json.dump(result,f,ensure_ascii=False,indent=1)
    # 赛道指数K线导出（看板展示用）
    with open(os.path.join(DATA,"track_indexes.json"),"w",encoding="utf-8") as f:
        json.dump({t:rows for t,rows in track_idx.items()},f,ensure_ascii=False)
    print("composite:",composite,zone,"| tech:",tech,"(track",track_avg,"/ wide",wide_avg,")")
    print("trackScores:",{t:s["score"] for t,s in track_scores.items()})
    print("wideScores:",{k:s["score"] for k,s in wide_scores.items()})
    print("overseas:",overseas["score"],"capital:",capital["score"],"fund:",fund["score"],"extras:",extras["total"])
    print("track idx bars:",{t:len(r) for t,r in track_idx.items()})
    print("track last close:",{t:round(r[-1]["close"],1) for t,r in track_idx.items()})

if __name__=="__main__":
    main()
