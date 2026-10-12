"""
測試每月現金流與負債計算。

每月可存 = 收入 − 固定支出 − 負債還款 − 生活預算
"""

from datetime import date

from models.cashflow import monthly_savings, total_debt_payment
from models.debt import months_left, payment_this_period, payoff_month


# ---------- 每月可存 ----------

def test_每月可存基本計算():
    assert monthly_savings(50000, 1500, 8000, 15000) == 25500


def test_入不敷出是負數():
    assert monthly_savings(30000, 2000, 10000, 20000) == -2000


def test_全部是零():
    assert monthly_savings(0, 0, 0, 0) == 0


# ---------- 負債還款合計 ----------

def test_負債還款合計():
    debts = [
        {"remaining": 100000, "monthly_payment": 5000},
        {"remaining": 30000, "monthly_payment": 3000},
    ]
    assert total_debt_payment(debts) == 8000


def test_已還清的負債不算():
    debts = [
        {"remaining": 0, "monthly_payment": 5000},
        {"remaining": 30000, "monthly_payment": 3000},
    ]
    assert total_debt_payment(debts) == 3000


def test_最後一期只算剩下的錢():
    debts = [{"remaining": 1200, "monthly_payment": 5000}]
    assert total_debt_payment(debts) == 1200


def test_現金流串起來():
    # 模擬總覽頁的計算流程
    debts = [{"remaining": 60000, "monthly_payment": 5000}]
    fixed = [399, 90]           # 電話費、iCloud
    budgets = [6000, 2000, 1500, 500]
    result = monthly_savings(40000, sum(fixed), total_debt_payment(debts), sum(budgets))
    assert result == 40000 - 489 - 5000 - 10000


# ---------- 還一期、預計還清月份 ----------

def test_還一期的金額():
    assert payment_this_period(30000, 5000) == 5000
    assert payment_this_period(3000, 5000) == 3000


def test_剩幾期無條件進位():
    assert months_left(12000, 5000) == 3
    assert months_left(10000, 5000) == 2
    assert months_left(0, 5000) == 0


def test_預計還清月份():
    # 2026 年 10 月，剩 5 期 → 2026/11 ~ 2027/03
    assert payoff_month(25000, 5000, date(2026, 10, 12)) == (2027, 3)


def test_預計還清月份跨到十二月():
    # 2026 年 10 月，剩 2 期 → 11 月、12 月
    assert payoff_month(10000, 5000, date(2026, 10, 1)) == (2026, 12)


def test_已還清沒有還清月份():
    assert payoff_month(0, 5000, date(2026, 10, 1)) is None
