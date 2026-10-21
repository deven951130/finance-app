"""
負債計算邏輯：還一期、還要幾期、預計哪個月還清。
"""

import math
from datetime import date


def payment_this_period(remaining: float, monthly_payment: float) -> float:
    """這一期實際要還多少。

    通常就是每月還款金額，但最後一期剩的錢可能比較少，
    例如剩 3000、每月還 5000，最後一期只要還 3000。
    """
    return min(remaining, monthly_payment)


def months_left(remaining: float, monthly_payment: float) -> int:
    """還要還幾期（無條件進位）。例如剩 12000、每月 5000 → 3 期。"""
    if remaining <= 0:
        return 0
    if monthly_payment <= 0:
        raise ValueError("每月還款必須大於 0，否則永遠還不完")
    # math.ceil 是無條件進位，跟 C++ 的 std::ceil 一樣
    return math.ceil(remaining / monthly_payment)


def add_months(d: date, n: int) -> tuple[int, int]:
    """從日期 d 往後推 n 個月，回傳 (年, 月)。"""
    # 把「年、月」換算成從西元 0 年開始的第幾個月，加完再換回來
    total = d.year * 12 + (d.month - 1) + n
    return total // 12, total % 12 + 1


def payoff_month(remaining: float, monthly_payment: float, today: date) -> tuple[int, int] | None:
    """預計還清的 (年, 月)。已還清回傳 None。

    假設：下一期在「下個月」繳。所以按了本月的「已還一期」之後，
    剩下的期數從下個月開始算。
    例如今天 2026-10、還剩 5 期 → 2026-11 到 2027-03，預計 2027 年 3 月還清。
    """
    n = months_left(remaining, monthly_payment)
    if n == 0:
        return None
    return add_months(today, n)


def paid_in_month(payments: list[dict], year: int, month: int) -> bool:
    """這個月是不是已經按過「已還一期」。payments 是還款紀錄，每筆至少有 'date'（'YYYY-MM-DD'）。"""
    prefix = f"{year:04d}-{month:02d}"
    return any(p["date"].startswith(prefix) for p in payments)
