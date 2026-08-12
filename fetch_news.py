# -*- coding: utf-8 -*-
"""
更新 data/news.json 的"time"时间戳，确保消息面面板的"最新内容"标注每日刷新。

实现思路：
1. 读取现有 news.json（由 gen_news_0810.py 等人工编辑维护的精选内容）；
2. 始终更新顶层 time 字段为当前时间，让看板显示"今日已更新"；
3. 尝试从东方财富快讯 API 拉取最新行业新闻（关键词：半导体/存储/光通信/AI/算力），
   按 impact/horizon 自动归类，追加到对应 category；
4. 抓取失败时仅更新 time，不破坏已有内容；
5. 结果写入 data/news.json。
"""
import json, os, re, time, urllib.request
from datetime import datetime, timedelta

DATA = os.path.join(os.path.dirname(__file__), "data")
OUT = os.path.join(DATA, "news.json")

KEYWORDS = {
    "行业政策": ["工信部", "发改委", "国务院", "商务部", "政策", "法案", "管制", "出口", "关税", "补贴"],
    "重要技术突破": ["HBM", "DRAM", "NAND", "先进制程", "GAA", "3nm", "2nm", "EUV", "光刻", "刻蚀", "薄膜沉积", "CPO", "1.6T", "800G"],
    "美股科技龙头": ["英伟达", "NVIDIA", "AMD", "苹果", "微软", "谷歌", "Meta", "亚马逊", "特斯拉", "亚马逊", "海力士", "三星", "美光", "西部数据", "闪迪", "台积电"],
    "国内龙头企业": ["中微", "北方华创", "拓荆", "华海清科", "长川", "中科飞测", "兆易", "长鑫", "佰维", "普冉", "德明利", "江波龙", "中际旭创", "新易盛", "天孚", "光迅"],
}

IMPACT_KEYWORDS = {
    "利好": ["突破", "增长", "上涨", "利好", "上调", "超预期", "扩产", "中标", "签约", "纳入", "涨幅", "新高", "放量", "回升", "反弹"],
    "利空": ["暴跌", "重挫", "跌停", "下调", "下修", "削减", "利空", "禁令", "管制", "出口管制", "禁运", "腰斩", "亏损", "下滑", "下挫", "回落"],
}

HORIZON_KEYWORDS = {
    "短期": ["今日", "盘中", "早盘", "尾盘", "单日", "隔夜", "盘中", "当日"],
    "中期": ["季度", "Q3", "Q4", "下半年", "本财年", "年报"],
    "长期": ["长期", "2027", "2028", "2030", "战略", "产业", "替代", "政策", "规划"],
}


def _get(url, timeout=12, retries=2):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://wap.eastmoney.com/",
            })
            return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", errors="ignore")
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(1.5)


def _classify(title):
    """根据标题关键词归类到 category、impact、horizon。"""
    cat = "重要技术突破"  # 默认
    for c, kws in KEYWORDS.items():
        if any(kw in title for kw in kws):
            cat = c
            break
    impact = "中性"
    for k, kws in IMPACT_KEYWORDS.items():
        if any(kw in title for kw in kws):
            impact = k
            break
    horizon = "中期"
    for h, kws in HORIZON_KEYWORDS.items():
        if any(kw in title for kw in kws):
            horizon = h
            break
    return cat, impact, horizon


def _fetch_eastmoney_news():
    """从东方财富快讯拉取最新行业新闻。返回 [{date,title,src}] 列表。"""
    items = []
    try:
        # 东方财富快讯 API（财经/科技频道）
        url = "https://np-listapi.eastmoney.com/comm/wap/getListInfo?cb=&client=wap&type=1&mTypeAndCode=&pageSize=30&pageIndex=1&callback=&_=" + str(int(time.time() * 1000))
        body = _get(url)
        # 去除 JSONP 包装
        body = re.sub(r'^[^(]*\(', '', body).rstrip(');')
        d = json.loads(body)
        for art in (d.get("data", {}).get("list") or [])[:30]:
            title = art.get("Art_Title") or art.get("title") or ""
            ts = art.get("Art_ShowTime") or art.get("showTime") or ""
            src = art.get("Art_MediaName") or art.get("mediaName") or "东方财富"
            if not title:
                continue
            date = ts[:10] if len(ts) >= 10 else datetime.now().strftime("%Y-%m-%d")
            items.append({"date": date, "title": title.strip(), "src": src})
    except Exception as e:
        print("  东方财富快讯抓取失败: %s" % str(e)[:80])
    return items


def load_existing():
    if os.path.exists(OUT):
        return json.load(open(OUT, encoding="utf-8"))
    return {"time": "", "categories": []}


def fetch():
    news = load_existing()
    now = datetime.now()
    revision_note = news.get("_revision_note", "")
    time_str = now.strftime("%Y-%m-%d %H:%M")

    # 1) 始终更新顶层 time 字段
    new_time = time_str
    if revision_note:
        new_time = "%s（%s）" % (time_str, revision_note)
    news["time"] = new_time

    # 2) 尝试拉取新快讯，追加到对应分类
    try:
        fresh = _fetch_eastmoney_news()
        added = 0
        for it in fresh:
            title = it["title"]
            # 过滤：必须含科技赛道关键词
            if not any(kw in title for kws in KEYWORDS.values() for kw in kws):
                continue
            # 去重：title 已存在则跳过
            existing_titles = {x.get("title", "") for cat in news.get("categories", []) for x in cat.get("items", [])}
            if title in existing_titles:
                continue
            cat, impact, horizon = _classify(title)
            new_item = {
                "date": it["date"],
                "title": title,
                "impact": impact,
                "horizon": horizon,
                "major": impact != "中性",
                "tag": "",
                "track": "半导体设备/存储芯片/光通信",
                "note": "快讯自动收录-待人工核实",
                "src": it["src"],
            }
            # 找到对应 category 并追加
            for c in news.setdefault("categories", []):
                if c.get("name") == cat:
                    c.setdefault("items", []).insert(0, new_item)
                    added += 1
                    break
            else:
                news["categories"].append({"name": cat, "items": [new_item]})
                added += 1
        # 限制每个 category 最新 12 条
        for c in news["categories"]:
            c["items"] = c.get("items", [])[:12]
        if added:
            print("  新增快讯 %d 条" % added)
        else:
            print("  快讯抓取成功，无新条目")
    except Exception as e:
        print("  快讯抓取失败: %s" % str(e)[:80])

    return news


if __name__ == "__main__":
    data = fetch()
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("news.json updated:", data.get("time", "")[:19])
    print("  categories:", len(data.get("categories", [])), "items:",
          sum(len(c.get("items", [])) for c in data.get("categories", [])))
