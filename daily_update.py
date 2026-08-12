# -*- coding: utf-8 -*-
"""
每日看板统一更新入口（供 WorkBuddy 自动化 / 手动调用）。

设计目标：
1. 把所有数据抓取、计算、生成集中到本地 Python 脚本，不再依赖 WorkBuddy 自动化的 WebFetch/WebSearch，避免 429/502 失败和积分浪费。
2. 任一子步骤失败都优雅降级，不影响后续步骤，确保"部分成功优于完全失败"。
3. 输出极简状态报告，由 WorkBuddy 自动化读取后直接部署。

调用示例：
    python daily_update.py --session noon    # 11:35 午盘
    python daily_update.py --session close   # 15:15 收盘
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
PY = sys.executable
STATUS_FILE = os.path.join(DATA, "daily_update_status.json")

# A股交易日历：周六日+已知节假日休市（可扩展）
HOLIDAYS = {
    "2026-01-01", "2026-01-02", "2026-01-03",
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    "2026-02-23", "2026-02-24",
    "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-22",
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",
}


def is_trading_day(dt=None):
    """判断是否为 A股交易日。"""
    if dt is None:
        dt = datetime.now()
    d = dt.strftime("%Y-%m-%d")
    if d in HOLIDAYS:
        return False
    if dt.weekday() >= 5:  # 周六日
        return False
    return True


def run_script(name, script, timeout=300, must_succeed=False):
    """运行本地 Python 脚本，返回 (success:bool, stdout:str, stderr:str, elapsed:float)。"""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 开始: {name}")
    t0 = time.time()
    try:
        r = subprocess.run(
            [PY, os.path.join(BASE, script)],
            capture_output=True, text=True, timeout=timeout,
            cwd=BASE,
        )
        elapsed = time.time() - t0
        if r.returncode == 0:
            print(f"  ✅ {name} 完成 ({elapsed:.1f}s)")
            # 只打印关键行，避免日志过长
            for line in (r.stdout or "").splitlines()[-8:]:
                if line.strip():
                    print(f"      {line[:120]}")
            return True, r.stdout, r.stderr, elapsed
        else:
            print(f"  ⚠️ {name} 返回非零 ({elapsed:.1f}s): {(r.stderr or '')[-200:]}")
            if must_succeed:
                return False, r.stdout, r.stderr, elapsed
            return True, r.stdout, r.stderr, elapsed  # 非致命
    except subprocess.TimeoutExpired as e:
        elapsed = time.time() - t0
        print(f"  ⚠️ {name} 超时 ({elapsed:.1f}s)")
        return (False if must_succeed else True), "", str(e), elapsed
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ⚠️ {name} 异常 ({elapsed:.1f}s): {str(e)[:200]}")
        return (False if must_succeed else True), "", str(e), elapsed


def read_meta_date():
    """读取 deploy_dist/data.js 中的 meta.date。"""
    js_path = os.path.join(BASE, "deploy_dist", "data.js")
    if not os.path.exists(js_path):
        return None
    try:
        import re
        s = open(js_path, encoding="utf-8").read()
        s = re.sub(r"^window\.DASHBOARD_DATA\s*=\s*", "", s).strip().rstrip(";").strip()
        d = json.loads(s)
        return d.get("meta", {}).get("date")
    except Exception:
        return None


def read_dashboard_summary():
    """读取看板核心摘要用于状态报告。"""
    js_path = os.path.join(BASE, "deploy_dist", "data.js")
    if not os.path.exists(js_path):
        return {}
    try:
        import re
        s = open(js_path, encoding="utf-8").read()
        s = re.sub(r"^window\.DASHBOARD_DATA\s*=\s*", "", s).strip().rstrip(";").strip()
        d = json.loads(s)
        out = {
            "meta_date": d.get("meta", {}).get("date"),
            "session": d.get("meta", {}).get("session"),
            "composite": d.get("composite", {}),
        }
        sigs = {}
        for sig in d.get("signals", []):
            sigs[sig.get("name")] = {
                "close": sig.get("close"),
                "chg": sig.get("chg"),
                "volRatio": sig.get("volRatio"),
            }
        out["signals"] = sigs
        lc = d.get("limitCount", {})
        out["limit_count"] = {"up": lc.get("limit_up"), "down": lc.get("limit_down"), "date": lc.get("date")}
        return out
    except Exception as e:
        return {"error": str(e)[:100]}


def main():
    parser = argparse.ArgumentParser(description="A股科技赛道看板每日统一更新")
    parser.add_argument("--session", choices=["noon", "close"], default="close", help="更新时段")
    args = parser.parse_args()

    start = datetime.now()
    today = start.strftime("%Y-%m-%d")
    session_label = "午盘" if args.session == "noon" else "收盘"
    print(f"\n{'='*60}")
    print(f"daily_update.py | 日期 {today} | 时段 {session_label} | PID {os.getpid()}")
    print(f"{'='*60}")

    status = {
        "date": today,
        "session": args.session,
        "started_at": start.isoformat(),
        "trading_day": is_trading_day(),
        "steps": [],
    }

    if not status["trading_day"]:
        status["finished_at"] = datetime.now().isoformat()
        status["success"] = True
        status["message"] = f"{today} 非交易日，跳过更新。"
        json.dump(status, open(STATUS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(status["message"])
        return 0

    steps = [
        ("海外行情刷新", "fetch_overseas.py", False, 180),
        ("A股日数据刷新", "fetch_daily_data.py", False, 240),
        ("看板快速刷新", "quick_refresh.py", True, 600),
    ]

    all_ok = True
    for name, script, must_succeed, timeout in steps:
        ok, stdout, stderr, elapsed = run_script(name, script, timeout=timeout, must_succeed=must_succeed)
        status["steps"].append({
            "name": name,
            "script": script,
            "ok": ok,
            "elapsed": round(elapsed, 2),
        })
        if not ok:
            all_ok = False
            if must_succeed:
                break

    # 读取最终看板摘要
    summary = read_dashboard_summary()
    status["dashboard_summary"] = summary
    status["success"] = all_ok
    status["finished_at"] = datetime.now().isoformat()
    status["deploy_ready"] = os.path.exists(os.path.join(BASE, "deploy_dist", "data.js")) and summary.get("meta_date") == today

    json.dump(status, open(STATUS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    if all_ok and status["deploy_ready"]:
        print(f"✅ {today} {session_label} 更新完成，可部署。")
    elif all_ok:
        print(f"⚠️ {today} {session_label} 管道完成，但 meta.date={summary.get('meta_date')} 不等于今日，请检查数据源。")
    else:
        print(f"❌ {today} {session_label} 更新未完全成功，请查看上方日志。")
    print(f"{'='*60}\n")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
