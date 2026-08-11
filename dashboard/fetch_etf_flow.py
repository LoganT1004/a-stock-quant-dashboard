# -*- coding: utf-8 -*-
"""抓取当日权益ETF累计净申购并追加到历史序列。
数据源：东财Choice权益ETF日报（通过WebSearch获取）
由消息面自动化（11:40/15:20）每日执行。
"""
import json, os
from datetime import datetime

DATA = r"C:\Users\ASUS\WorkBuddy\2026-08-03-11-17-59\data"
HIST = os.path.join(DATA, "etf_flow_history.json")

def append_today(date_str, net3d, net7d=None, net30d=None):
    """追加当日数据到历史文件"""
    old = json.load(open(HIST, encoding="utf-8")) if os.path.exists(HIST) else {
        "dates": [], "net3d": [], "net7d": [], "net30d": [],
        "src": "东财Choice权益ETF日报", "note": ""}
    # 去重（若同日已有数据则更新）
    if date_str in old["dates"]:
        idx = old["dates"].index(date_str)
        old["net3d"][idx] = net3d
        if net7d is not None and "net7d" in old: old["net7d"][idx] = net7d
        if net30d is not None and "net30d" in old: old["net30d"][idx] = net30d
    else:
        old["dates"].append(date_str)
        old["net3d"].append(net3d)
        if net7d is not None:
            if "net7d" not in old or len(old.get("net7d", [])) < len(old["dates"]):
                old.setdefault("net7d", [None] * (len(old["dates"]) - 1 - len(old.get("net7d", []))))
                old["net7d"].append(net7d)
            else:
                old["net7d"].append(net7d)
        if net30d is not None:
            old.setdefault("net30d", [])
            while len(old["net30d"]) < len(old["dates"]) - 1:
                old["net30d"].append(None)
            old["net30d"].append(net30d)
    # 填充null为今日值（历史7d/30d留空时不处理）
    json.dump(old, open(HIST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[etf_flow] appended {date_str}: 3d={net3d} 7d={net7d} 30d={net30d}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        # 命令行参数: 日期 3d [7d] [30d]
        append_today(sys.argv[1], float(sys.argv[2]),
                    float(sys.argv[3]) if len(sys.argv) > 3 else None,
                    float(sys.argv[4]) if len(sys.argv) > 4 else None)