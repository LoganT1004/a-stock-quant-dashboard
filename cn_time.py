# -*- coding: utf-8 -*-
"""统一北京时间工具：解决 GitHub Actions（UTC）与本地（UTC+8）时区不一致问题。

问题背景：gen_dashboard_data.py / vol_utils.py / fetch_daily_data.py 等多处使用
datetime.now() 判断「当前是否盘中 / 今日日期」。在 GitHub Actions runner（UTC 时区）上，
datetime.now() 返回 UTC 时间，导致：
- 收盘后（北京时间 15:00 后）仍被判断为「盘中实时」（UTC 07:00 < 15:00）
- 盘中量比投影系数 intraday_vol_factor() 用 UTC 判断交易时段，永远返回 1.0
- 「今日日期」在 UTC 跨零点时会差一天

用法：
    from cn_time import now_cn, today_cn
    now = now_cn()          # 北京时间 now（tz-aware datetime）
    today = today_cn()      # 北京时间今天 "YYYY-MM-DD"
"""
from datetime import datetime, timezone, timedelta

CN_TZ = timezone(timedelta(hours=8))


def now_cn():
    """返回北京时间当前时刻（tz-aware datetime）"""
    return datetime.now(CN_TZ)


def today_cn():
    """返回北京时间今天日期字符串 YYYY-MM-DD"""
    return datetime.now(CN_TZ).strftime("%Y-%m-%d")


def now_cn_str(fmt="%Y-%m-%d %H:%M"):
    """返回北京时间当前时刻的格式化字符串"""
    return datetime.now(CN_TZ).strftime(fmt)
