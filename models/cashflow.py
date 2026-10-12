"""
每月現金流計算。

每月可存 = 收入 − 固定支出 − 負債還款 − 生活預算
"""


def total_debt_payment(debts: list[dict]) -> float:
    """把還沒還清的負債，每月要還的錢加總。

    每筆負債是 dict，需要 'remaining'（剩餘金額）和 'monthly_payment'（每月還款）。
    已經還清（剩餘 <= 0）的不算；最後一期剩不到每月還款金額時，只算剩下的。
    """
    total = 0.0
    for d in debts:
        if d["remaining"] > 0:
            total += min(d["remaining"], d["monthly_payment"])
    return total


def monthly_savings(income: float, fixed_total: float, debt_payment: float, living_budget: float) -> float:
    """每月可存多少。結果是負數代表每個月入不敷出。"""
    return income - fixed_total - debt_payment - living_budget
