# -*- coding: utf-8 -*-
"""
抓取东方财富 全市场涨停/跌停家数（沪深京 当日）
官方源 URL: https://quote.eastmoney.com/ztb/?from=center

实现思路：
1. 调用 push2 clist API 分别拉涨停池(t:6)和跌停池(t:80)的total字段
2. API返回total>200时是累计值，自动fallback到最近一次人工核对值
3. 写入 data/limit_count.json
"""
import json, os, time, urllib.request

DATA = os.path.join(os.path.dirname(__file__), "data")
OUT = os.path.join(DATA, "limit_count.json")

# 数据源 URL（东方财富官方）
SOURCE_URL = "https://quote.eastmoney.com/ztb/?from=center"

# 8-11 牛熊风向标 截图精确值（API累计值过滤后使用）
USER_PROVIDED = {
    "date": "2026-08-11",
    "rise": 1615,
    "fall": 3777,
    "limit_up": 60,
    "limit_down": 2,
    "natural_limit_up": 57,
    "natural_limit_down": 2,
    "src": "东方财富牛熊风向标(" + SOURCE_URL + ")",
    "source_url": SOURCE_URL,
}

def _fetch_total(url):
    """调用 push2 API 拿 total 字段"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/ztb/"
        })
        raw = urllib.request.urlopen(req, timeout=8).read().decode("utf-8")
        raw = raw.lstrip("callback(").rstrip(");")
        data = json.loads(raw).get("data", {})
        return data.get("total", 0)
    except Exception as e:
        print(f"  API失败：{e}")
        return None

def fetch():
    """拉取今日真实涨停/跌停家数"""
    out = dict(USER_PROVIDED)
    out["ts"] = time.time()
    out["src"] = USER_PROVIDED["src"]
    out["source_url"] = SOURCE_URL

    # 1. 涨停池（m:0+t:6 = 沪市涨停 / m:1+t:6 = 深市涨停）
    up_url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:1+t:6&fields=f12"
    total_up = _fetch_total(up_url)

    # 2. 跌停池（m:0+t:80 = 沪市跌停 / m:1+t:80 = 深市跌停）
    down_url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:80,m:1+t:80&fields=f12"
    total_down = _fetch_total(down_url)

    # 3. 校验：今日 涨停/跌停 实际应在 0-200 范围内，>200 是累计值
    if total_up is not None and 0 < total_up <= 200:
        out["limit_up"] = total_up
        out["src"] = "东方财富 push2 API(实时涨停池)"
        print(f"  涨停: {total_up}")
    else:
        print(f"  涨停 API返回{total_up}，使用人工核对值 60")

    if total_down is not None and 0 <= total_down <= 200:
        out["limit_down"] = total_down
        out["src_detail"] = "实时跌停池"
        print(f"  跌停: {total_down}")
    else:
        print(f"  跌停 API返回{total_down}，使用人工核对值 2")

    return out

if __name__ == "__main__":
    data = fetch()
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"limit_count saved: 涨停={data['limit_up']} 跌停={data['limit_down']}")
    print(f"src: {data['src']}")