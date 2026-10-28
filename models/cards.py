"""
信用卡費：每張卡每個月一張帳單，幾號以前要繳清。

為什麼不放進記帳或固定支出：
- 刷卡當下錢還沒離開帳戶，真正扣錢的是「繳卡費」那天；
- 每個月金額都不一樣，不是固定支出。
所以獨立一項：每月填帳單金額，繳的時候從帳戶扣。

帳單用「繳款的月份」表示，例如 '2026-11' 是 11 月要繳的那一張。
"""

import calendar
from datetime import date

DUE_SOON_DAYS = 5  # 離截止日 5 天以內還沒繳清，就提醒


def due_date(month: str, due_day: int) -> date:
    """某個月帳單的繳款截止日。month 是 'YYYY-MM'。

    due_day 超過那個月的天數時用月底（例如每月 31 號繳，2 月就是 28 或 29 號）。
    calendar.monthrange 回傳 (那個月第一天是星期幾, 那個月有幾天)。
    """
    year, mon = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(year, mon)[1]
    return date(year, mon, min(due_day, last))


def unpaid(amount: float, paid: float) -> float:
    """這張帳單還要繳多少（繳超過不會變負數）。"""
    return max(amount - paid, 0.0)


def bill_status(amount: float, paid: float, due: date, today: date) -> str:
    """帳單狀態：
    - "paid"：繳清了（包含帳單 0 元）
    - "overdue"：過了截止日還沒繳清
    - "due_soon"：DUE_SOON_DAYS 天以內要繳
    - "upcoming"：還早
    """
    if unpaid(amount, paid) <= 0:
        return "paid"
    days = (due - today).days
    if days < 0:
        return "overdue"
    if days <= DUE_SOON_DAYS:
        return "due_soon"
    return "upcoming"


def unpaid_total(bills: list[dict]) -> float:
    """所有帳單還沒繳的合計（總覽的淨資產要減掉：這筆錢已經花了，只是還沒從帳戶扣）。"""
    return sum(unpaid(b["amount"], b["paid"]) for b in bills)


def month_total(bills: list[dict], month: str) -> float:
    """某個月所有卡的帳單金額合計（每月現金流用：不管繳了沒，這個月都要付這麼多）。"""
    return sum(b["amount"] for b in bills if b["month"] == month)


def bill_month(date_str: str) -> str:
    """刷卡的花費算進哪個月的帳單：刷卡日期的「下一個月」。

    例如 10 月任何一天刷的，算 11 月要繳的帳單。
    真實的信用卡有「結帳日」（例如每月 20 號結帳，21 號以後刷的要再晚一個月），
    這裡先用最簡單的規則；跟銀行帳單對不上時，在信用卡頁直接改帳單金額就好。
    """
    total = int(date_str[:4]) * 12 + (int(date_str[5:7]) - 1) + 1  # 換算成「第幾個月」再加 1，跟 debt.add_months 一樣
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def bill_from_records(card_records: list[dict], month: str) -> float:
    """某個月的帳單裡，有多少是從記帳刷卡來的。card_records 是有選信用卡的支出（每筆有 'date'、'amount'）。"""
    return sum(r["amount"] for r in card_records if bill_month(r["date"]) == month)


def card_cashflow(bills: list[dict], card_records: list[dict], month: str) -> float:
    """每月現金流要扣的「信用卡費」：這個月的帳單，扣掉從記帳刷卡來的部分。

    為什麼要扣掉：每月現金流已經扣了「生活預算」，記帳刷卡的花費屬於生活預算，
    帳單再整筆扣一次就重複算了。剩下的是記帳沒記到的（例如直接扣卡的訂閱）。
    """
    return max(month_total(bills, month) - bill_from_records(card_records, month), 0.0)
