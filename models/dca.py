"""
定期定額試算。

假設：
- 每個月「月底」投入一次
- 年報酬率換算成「每月報酬率」時用複利換算：(1 + 年報酬率)^(1/12) − 1
  這樣一整年 12 個月滾下來，剛好等於輸入的年報酬率。
  （如果直接用 年報酬率 ÷ 12，一年下來會比輸入的年報酬率高一點）
"""

# 4% 法則：每年從資產中提領 4%，資產大致可以撐很久
WITHDRAW_RATE = 0.04


def monthly_rate(annual_rate: float) -> float:
    """把年報酬率（例如 0.06 代表 6%）換算成每月報酬率。"""
    return (1 + annual_rate) ** (1 / 12) - 1


def project(initial: float, monthly: float, annual_rate: float, years: int) -> list[float]:
    """計算每年年底的資產，回傳長度為 years + 1 的清單。

    第 0 個是一開始的資產（= 現有投資），第 i 個是第 i 年年底的資產。
    """
    r = monthly_rate(annual_rate)
    balance = initial
    result = [balance]
    for _year in range(years):          # 變數名稱用 _ 開頭，表示「用不到它」
        for _month in range(12):
            balance = balance * (1 + r) + monthly  # 先長利息，月底再投入
        result.append(balance)
    return result


def monthly_withdrawal(total: float) -> float:
    """用 4% 法則換算每月可以領多少：總資產 × 4% ÷ 12。"""
    return total * WITHDRAW_RATE / 12
