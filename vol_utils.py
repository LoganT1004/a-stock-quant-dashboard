# -*- coding: utf-8 -*-
"""量比盘中投影辅助：在 15:00 收盘前，按已交易时长把当前成交量投影到全日，
使盘中量比与东方财富 APP 保持一致。"""
from cn_time import now_cn


def intraday_vol_factor():
    """
    返回成交量投影系数。
    A股交易时间 09:30-11:30、13:00-15:00，合计 240 分钟。
    收盘后（>=15:00）或周末返回 1.0；非交易时段返回 1.0。
    注意：必须用北京时间判断（GitHub Actions runner 是 UTC，直接用 datetime.now() 会错）。
    """
    now = now_cn()
    if now.weekday() >= 5:
        return 1.0
    hm = now.hour * 60 + now.minute
    if hm >= 15 * 60:
        return 1.0
    if hm < 9 * 60 + 30:
        return 1.0
    if hm <= 11 * 60 + 30:
        elapsed = hm - (9 * 60 + 30)
    elif hm < 13 * 60:
        elapsed = 120
    else:
        elapsed = 120 + (hm - 13 * 60)
    if elapsed <= 0:
        return 1.0
    return 240.0 / elapsed
