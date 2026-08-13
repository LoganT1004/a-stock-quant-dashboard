# -*- coding: utf-8 -*-
"""
抓取全市场涨停/跌停家数（沪深京A股）。

实现思路：
1. 调用东方财富 push2 clist 全A实时列表（m:0+m:1+m:3），按页拉取；
2. 对每只股票按 f3（涨跌幅）计数：f3 >= 9.9 计为涨停，f3 <= -9.9 计为跌停；
3. 支持重试 + 超时保护。若扫描 0 只或 API 失败，保留最近一次有效值，
   避免退回到硬编码旧值；
4. 结果写入 data/limit_count.json。

注：本机直连 push2 间歇被封（RemoteDisconnected），GitHub Actions 云端通常可通。
"""
import json, os, time, urllib.request
from datetime import datetime

DATA = os.path.join(os.path.dirname(__file__), "data")
OUT = os.path.join(DATA, "limit_count.json")
SOURCE_URL = "https://quote.eastmoney.com/ztb/?from=center"


def _get(url, timeout=25, retries=5):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://quote.eastmoney.com/ztb/",
            })
            return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)


def _page_url(pn, pz=100):
    fs = "m:0+m:1+m:3"
    return (
        "https://push2.eastmoney.com/api/qt/clist/get?"
        "pn=%d&pz=%d&po=1&np=1&fltt=2&invt=2&fid=f3&fs=%s&fields=f12,f14,f3"
        % (pn, pz, fs)
    )


def _count_all():
    limit_up = 0
    limit_down = 0
    total_seen = 0
    pn = 1
    pz = 100
    while pn <= 60:
        body = _get(_page_url(pn, pz))
        d = json.loads(body) if body else {}
        if not isinstance(d, dict):
            raise ValueError("invalid response: %r" % (body[:120] if body else None,))
        data = d.get("data") or {}
        diff = data.get("diff") or []
        if not diff:
            break
        for item in diff:
            f3 = float(item.get("f3", 0))
            if f3 >= 9.9:
                limit_up += 1
            if f3 <= -9.9:
                limit_down += 1
        total_seen += len(diff)
        api_total = data.get("total", 0)
        if api_total and total_seen >= int(api_total):
            break
        pn += 1
        time.sleep(0.08)
    return limit_up, limit_down, total_seen


def load_existing():
    if os.path.exists(OUT):
        return json.load(open(OUT, encoding="utf-8"))
    return {}


def fetch():
    out = load_existing()
    out["ts"] = time.time()
    out["source_url"] = SOURCE_URL
    try:
        up, down, seen = _count_all()
        # 扫描 0 只通常是网络被截断/空返回，保留旧值避免显示 0/0
        if seen == 0:
            raise ValueError("API 返回空列表，视为失败")
        out.update({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "limit_up": up,
            "limit_down": down,
            "seen": seen,
            "src": "东方财富 push2 clist（全A实时 f3≥9.9% / f3≤-9.9% 计数）",
        })
        print("涨停=%d 跌停=%d（扫描 %d 只）" % (up, down, seen))
    except Exception as e:
        # 2026-08-13 修订：API 失败时不再追加 "[API失败，保留旧值]" 到 src 字段
        # 避免多次失败后 src 字段堆叠一长串；用户明确要求只显示数量
        print("涨跌停 API 失败: %s，保留旧值（涨停=%d 跌停=%d）" % (
            str(e)[:80], out.get("limit_up", 0), out.get("limit_down", 0)))
        # 仅在第一次失败时设置简洁的失败提示
        if not out.get("src") or "保留旧值" in out.get("src", ""):
            out["src"] = "东方财富 push2 clist（API失败·保留旧值）"
        else:
            out["src"] = out.get("src", "东方财富 push2 clist")
        if "date" not in out:
            out["date"] = datetime.now().strftime("%Y-%m-%d")
    return out


if __name__ == "__main__":
    data = fetch()
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("limit_count saved: 涨停=%d 跌停=%d" % (data.get("limit_up", 0), data.get("limit_down", 0)))
