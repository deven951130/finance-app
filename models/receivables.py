"""
別人欠我的錢（應收款）：借給朋友、幫人代墊、還沒收回來的錢。

和「負債」是相反方向：負債是我欠別人（淨資產要減），這裡是別人欠我（淨資產要加）。
"""


def collect_amount(remaining: float, amount: float) -> float:
    """這次實際收回多少：收的比剩下的多時，只算剩下的（不會收成負數）。"""
    return min(amount, remaining)


def outstanding_total(items: list[dict]) -> float:
    """還沒收回來的合計。每筆至少有 'remaining'；已經收完（<= 0）的不算。"""
    return sum(i["remaining"] for i in items if i["remaining"] > 0)


def collected_ratio(amount: float, remaining: float) -> float:
    """收回幾成（0 ~ 1），進度條用。原本借出 0 元時當作 0。"""
    if amount <= 0:
        return 0.0
    return min(max((amount - remaining) / amount, 0.0), 1.0)
