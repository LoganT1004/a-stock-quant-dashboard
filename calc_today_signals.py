# -*- coding: utf-8 -*-
"""计算最新技术信号：九转/MACD/MA5（上证、创业板、科创50 + 三大赛道板块）"""
import json

def load(fn):
    d = json.load(open(fn, encoding="utf-8"))
    if "klines" in d:
        kl = d["klines"]
    elif "data" in d and "klines" in d["data"]:
        kl = d["data"]["klines"]
    else:
        # 腾讯格式 {"data": {"sh000001": {"day": [[date,o,c,h,l,vol],...]}}}
        key = list(d["data"].keys())[0]
        kl = [",".join(map(str, r[:5])) for r in d["data"][key]["day"]]
    rows = []
    for s in kl:
        p = s.split(",")
        rows.append({"date": p[0], "open": float(p[1]), "close": float(p[2]), "high": float(p[3]), "low": float(p[4])})
    return rows

def ema(vals, n):
    k = 2 / (n + 1)
    e = vals[0]
    out = [e]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out

def nine_turn(rows):
    """TD九转：收盘高于/低于4日前收盘则计数+1，否则清零"""
    up = dn = 0
    ups, dns = [], []
    for i in range(len(rows)):
        if i < 4:
            ups.append(0); dns.append(0); continue
        c = rows[i]["close"]; c4 = rows[i - 4]["close"]
        if c > c4: up += 1
        else: up = 0
        if c < c4: dn += 1
        else: dn = 0
        ups.append(up); dns.append(dn)
    return ups, dns

def analyze(name, fn):
    rows = load(fn)[-200:]
    closes = [r["close"] for r in rows]
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = ema(dif, 9)
    ma5 = sum(closes[-5:]) / 5
    ups, dns = nine_turn(rows)
    # 近30日最大计数与触9日期
    u30 = ups[-30:]; d30 = dns[-30:]
    up9 = [rows[len(ups)-30+i]["date"] for i, v in enumerate(u30) if v >= 9]
    dn9 = [rows[len(dns)-30+i]["date"] for i, v in enumerate(d30) if v >= 9]
    above5 = sum(1 for r in rows[-6:-1] if r["close"] > sum(x["close"] for x in rows[:rows.index(r)][-5:] or [0]) )
    # 连续站上MA5天数
    streak = 0
    for i in range(len(rows) - 1, 4, -1):
        m = sum(closes[i-4:i+1]) / 5
        if closes[i] > m: streak += 1
        else: break
    last = rows[-1]; prev = rows[-2]
    chg = (last["close"] / prev["close"] - 1) * 100
    print(f"== {name} == {last['date']} 收{last['close']:.2f} ({chg:+.2f}%)")
    print(f"   九转: 上涨计数{ups[-1]} / 下跌计数{dns[-1]}；近30日最大涨{max(u30)}跌{max(d30)}；高9日{up9} 低9日{dn9}")
    print(f"   MACD: DIF {dif[-1]:.2f} (前{ dif[-2]:.2f}) DEA {dea[-1]:.2f} 差{dif[-1]-dea[-1]:+.2f}")
    print(f"   MA5={ma5:.2f} 收盘在MA5{'上' if last['close']>ma5 else '下'} 连续站上{streak}日")
    # 近20日摆动高低点用于背离判断
    return rows, dif, dea

for name, fn in [("上证指数","data/szzs_full.json"),("创业板指","data/cybz_full.json"),("科创50","data/kc50_full.json"),
                 ("半导体设备","data/bk1326_raw.json"),("存储芯片","data/bk1137_raw.json"),("光通信模块","data/bk1136_raw.json")]:
    try:
        analyze(name, fn)
    except Exception as e:
        print(name, "ERR", e)
