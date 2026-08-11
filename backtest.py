# -*- coding: utf-8 -*-
"""九转信号回测：验证科创50(3/23低9,6/25高9)与纳指100(3/20低9,6/3高9)的信号有效性"""
import json, os

DATA = r"C:\Users\ASUS\WorkBuddy\2026-08-03-11-17-59\data"

def load_tx(name, key):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        d = json.load(f)["data"][key]["day"]
    rows = []
    for r in d:
        rows.append({"date": r[0], "open": float(r[1]), "close": float(r[2]),
                     "high": float(r[3]), "low": float(r[4]), "vol": float(r[5])})
    return rows

def ema(vals, n):
    k = 2 / (n + 1); out = []; e = vals[0]
    for i, v in enumerate(vals):
        e = v if i == 0 else v * k + e * (1 - k)
        out.append(e)
    return out

def analyze(rows, targets, label):
    n = len(rows)
    closes = [r["close"] for r in rows]
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = ema(dif, 9)
    ma5 = [sum(closes[max(0, i - 4):i + 1]) / min(5, i + 1) for i in range(n)]
    up = [0] * n; down = [0] * n
    for i in range(4, n):
        if rows[i]["close"] > rows[i - 4]["close"]: up[i] = up[i - 1] + 1
        if rows[i]["close"] < rows[i - 4]["close"]: down[i] = down[i - 1] + 1
    all_nine = {"up9": [rows[i]["date"] for i in range(n) if up[i] == 9],
                "down9": [rows[i]["date"] for i in range(n) if down[i] == 9]}
    out = {"label": label, "allNineTurns": all_nine, "cases": []}
    for tdate, ttype in targets:
        # 找目标日或±2日内最近的9
        idx = None
        for off in (0, 1, -1, 2, -2):
            j = None
            for i, r in enumerate(rows):
                if r["date"] == tdate:
                    j = i; break
            if j is None: break
            jj = j + off
            if 0 <= jj < n:
                if ttype == "低9" and down[jj] >= 9: idx = jj; break
                if ttype == "高9" and up[jj] >= 9: idx = jj; break
        case = {"expectDate": tdate, "type": ttype}
        if idx is None:
            case.update({"found": False, "note": "目标日附近未检出" + ttype})
        else:
            r0 = rows[idx]
            actual = "低9" if down[idx] >= 9 else "高9"
            cnt = max(up[idx], down[idx])
            # 3日确认
            confirm_days = []
            for k in range(idx + 1, min(idx + 4, n)):
                confirm_days.append("上" if rows[k]["close"] > ma5[k] else "下")
            above2 = confirm_days.count("上") >= 2
            below2 = confirm_days.count("下") >= 2
            if actual == "低9":
                sig_state = "强确认" if above2 else ("弱确认" if "上" in confirm_days else "未确认/鱼尾")
                action = "加仓2-3成" if above2 else ("加仓1成" if "上" in confirm_days else "不操作")
            else:
                sig_state = "强确认" if below2 else ("弱确认" if "下" in confirm_days else "未确认/鱼尾")
                action = "减仓2-3成" if below2 else ("减仓1成" if "下" in confirm_days else "不操作")
            # 后续收益
            rets = {}
            for h in (3, 5, 10, 20):
                if idx + h < n:
                    rets[str(h) + "日"] = round((rows[idx + h]["close"] / r0["close"] - 1) * 100, 2)
            # 之后20日最大反向/顺向
            fwd = rows[idx:min(idx + 21, n)]
            if actual == "低9":
                best = round((max(x["close"] for x in fwd) / r0["close"] - 1) * 100, 2) if fwd else None
                worst = round((min(x["close"] for x in fwd) / r0["close"] - 1) * 100, 2) if fwd else None
            else:
                best = round((min(x["close"] for x in fwd) / r0["close"] - 1) * 100, 2) if fwd else None
                worst = round((max(x["close"] for x in fwd) / r0["close"] - 1) * 100, 2) if fwd else None
            # MACD背离（与前一同向摆动点粗判）
            case.update({"found": True, "date": r0["date"], "count": cnt, "close": r0["close"],
                         "dif": round(dif[idx], 2), "dea": round(dea[idx], 2), "ma5": round(ma5[idx], 2),
                         "confirm3d": confirm_days, "sigState": sig_state, "action": action,
                         "rets": rets, "fwd20 favorable%": best, "fwd20 adverse%": worst})
        out["cases"].append(case)
    return out

result = {
    "kc50": analyze(load_tx("kc50_full.json", "sh000688"),
                    [("2026-03-23", "低9"), ("2026-06-25", "高9")], "科创50"),
    "ndx100": analyze(load_tx("ndx100_full.json", "us.NDX"),
                      [("2026-03-20", "低9"), ("2026-06-03", "高9")], "纳斯达克100"),
}
with open(os.path.join(DATA, "backtest_result.json"), "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=1)
print(json.dumps(result, ensure_ascii=False, indent=1))
