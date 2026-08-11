# -*- coding: utf-8 -*-
"""按东方财富官方规则计算神奇九转 + MACD背离 + MA5确认状态"""
import json, os

DATA_DIR = r"C:\Users\ASUS\WorkBuddy\2026-08-03-11-17-59\data"

def load(name):
    path = os.path.join(DATA_DIR, name + ".json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if not d.get("data"):
        return name, []
    rows = []
    for line in d["data"]["klines"]:
        p = line.split(",")
        rows.append({
            "date": p[0], "open": float(p[1]), "close": float(p[2]),
            "high": float(p[3]), "low": float(p[4]),
            "vol": float(p[5]), "amt": float(p[6])
        })
    return d["data"]["name"], rows

def nine_turn(rows):
    n = len(rows)
    up = [0]*n; down = [0]*n
    for i in range(4, n):
        c = rows[i]["close"]; c4 = rows[i-4]["close"]
        if c > c4:
            up[i] = up[i-1] + 1
        elif c < c4:
            down[i] = down[i-1] + 1
    return up, down

def ema(vals, period):
    k = 2.0/(period+1)
    out = []
    e = vals[0]
    for i, v in enumerate(vals):
        e = v if i == 0 else v*k + e*(1-k)
        out.append(e)
    return out

def macd(closes):
    e12 = ema(closes, 12); e26 = ema(closes, 26)
    dif = [a-b for a, b in zip(e12, e26)]
    dea = ema(dif, 9)
    return dif, dea

def swing_idx(rows, w, mode):
    idx = []
    for i in range(w, len(rows)-w):
        if mode == "high":
            if all(rows[i]["high"] >= rows[j]["high"] for j in range(i-w, i+w+1) if j != i):
                idx.append(i)
        else:
            if all(rows[i]["low"] <= rows[j]["low"] for j in range(i-w, i+w+1) if j != i):
                idx.append(i)
    return idx

def ma(vals, period, i):
    if i < period - 1:
        return None
    return sum(vals[i-period+1:i+1]) / period

def analyze(fname, label):
    name, rows = load(fname)
    if len(rows) < 10:
        return {"label": label, "error": "数据不足", "n": len(rows)}
    closes = [r["close"] for r in rows]
    vols = [r["vol"] for r in rows]
    up, down = nine_turn(rows)
    dif, dea = macd(closes)
    n = len(rows)
    i = n - 1

    # 最近30个交易日内九转最大计数
    lookback = min(30, n-4)
    recent_up_max = max(up[n-lookback:]) if lookback > 0 else up[i]
    recent_down_max = max(down[n-lookback:]) if lookback > 0 else down[i]
    up9_dates = [rows[j]["date"] for j in range(max(4, n-lookback), n) if up[j] >= 9]
    down9_dates = [rows[j]["date"] for j in range(max(4, n-lookback), n) if down[j] >= 9]

    # MA5
    ma5 = ma(closes, 5, i)
    last5_vs_ma5 = []
    for j in range(max(4, n-5), n):
        m5 = ma(closes, 5, j)
        last5_vs_ma5.append({"date": rows[j]["date"], "close": closes[j],
                             "ma5": round(m5, 2) if m5 else None,
                             "pos": "上" if m5 and closes[j] >= m5 else "下"})

    # 摆动高低点（窗口3）
    sh = swing_idx(rows, 3, "high")
    sl = swing_idx(rows, 3, "low")
    def pk(idxs, k=3):
        out = []
        for j in idxs[-k:]:
            out.append({"date": rows[j]["date"], "close": round(closes[j],2),
                        "high": round(rows[j]["high"],2), "low": round(rows[j]["low"],2),
                        "dif": round(dif[j],2)})
        return out

    # 顶背离：最近两个swing high，价格创新高且DIF更低
    top_div = None
    if len(sh) >= 2:
        a, b = sh[-2], sh[-1]
        price_chg = (rows[b]["high"] - rows[a]["high"]) / rows[a]["high"] * 100
        dif_chg_pct = (dif[b] - dif[a]) / abs(dif[a]) * 100 if dif[a] != 0 else 0
        top_div = {
            "prev": {"date": rows[a]["date"], "high": round(rows[a]["high"],2), "dif": round(dif[a],2)},
            "curr": {"date": rows[b]["date"], "high": round(rows[b]["high"],2), "dif": round(dif[b],2)},
            "price_higher": rows[b]["high"] > rows[a]["high"],
            "dif_lower": dif[b] < dif[a],
            "dif_deviation_pct": round(dif_chg_pct,1),
            "is_divergence": rows[b]["high"] > rows[a]["high"] and dif[b] < dif[a]
        }
    bot_div = None
    if len(sl) >= 2:
        a, b = sl[-2], sl[-1]
        dif_chg_pct = (dif[b] - dif[a]) / abs(dif[a]) * 100 if dif[a] != 0 else 0
        bot_div = {
            "prev": {"date": rows[a]["date"], "low": round(rows[a]["low"],2), "dif": round(dif[a],2)},
            "curr": {"date": rows[b]["date"], "low": round(rows[b]["low"],2), "dif": round(dif[b],2)},
            "price_lower": rows[b]["low"] < rows[a]["low"],
            "dif_higher": dif[b] > dif[a],
            "dif_deviation_pct": round(dif_chg_pct,1),
            "is_divergence": rows[b]["low"] < rows[a]["low"] and dif[b] > dif[a]
        }

    # 量能
    vol5 = sum(vols[n-5:]) / min(5, n)
    vol20 = sum(vols[max(0,n-25):n-5]) / max(1, min(20, n-5)) if n > 5 else vol5

    prev_close = rows[n-2]["close"] if n >= 2 else closes[i]
    return {
        "label": label, "em_name": name, "n_bars": n,
        "last_date": rows[i]["date"],
        "close": closes[i],
        "chg_pct": round((closes[i]-prev_close)/prev_close*100, 2),
        "nine_turn": {
            "cur_up": up[i], "cur_down": down[i],
            "recent30_up_max": recent_up_max, "recent30_down_max": recent_down_max,
            "up9_dates_last30": up9_dates, "down9_dates_last30": down9_dates
        },
        "macd": {"dif": round(dif[i],2), "dea": round(dea[i],2),
                 "dif_prev": round(dif[i-1],2)},
        "top_divergence": top_div,
        "bottom_divergence": bot_div,
        "ma5_now": round(ma5,2) if ma5 else None,
        "close_vs_ma5": "上" if ma5 and closes[i] >= ma5 else "下",
        "last5_vs_ma5": last5_vs_ma5,
        "vol_ratio_5vs20": round(vol5/vol20, 2) if vol20 else None,
        "recent_swings_high": pk(sh), "recent_swings_low": pk(sl),
        "last10_closes": [{"date": rows[j]["date"], "close": closes[j]} for j in range(max(0,n-10), n)]
    }

targets = [
    ("szzs", "上证指数"), ("cybz", "创业板指"), ("kc50", "科创50"),
    ("ndx", "纳斯达克(东财NDX)"), ("sox", "费城半导体SOX"), ("ndi", "美元指数DXY")
]
result = {}
for fname, label in targets:
    try:
        result[label] = analyze(fname, label)
    except Exception as e:
        result[label] = {"label": label, "error": str(e)}

out = json.dumps(result, ensure_ascii=False, indent=1)
with open(os.path.join(DATA_DIR, "signals_result.json"), "w", encoding="utf-8") as f:
    f.write(out)
print(out[:6000])
