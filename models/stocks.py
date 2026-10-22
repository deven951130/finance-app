"""
持股計算：合併同一代號、市值、損益、占比、回本價。
"""

# 台股交易成本
FEE_RATE = 0.001425   # 手續費 0.1425%（賣出時也要付）
TAX_RATE = 0.003      # 證券交易稅 0.3%（只有賣出時付）

# 單一個股占總市值超過這個比例就警告
CONCENTRATION_LIMIT = 0.40


def merge_by_symbol(holdings: list[dict]) -> list[dict]:
    """把同一個代號、不同帳戶的持股合併成一筆。

    每筆持股是 dict，需要 'name'、'symbol'、'account'、'shares'、'avg_price'、'price'。
    合併後：
      股數 = 各帳戶股數相加
      總成本 = 各帳戶（股數 × 均價）相加
      均價 = 總成本 ÷ 總股數（加權平均，不是直接把均價平均）
    現價：同一代號的現價應該一樣，取第一筆。
    均價可以不填（存 0）：只要有一個帳戶沒填，這檔的成本就是「不知道」（cost、avg_price 為 None），
    不能把沒填當成 0 元成本，不然損益會等於整個市值。
    """
    merged = {}  # {代號: 合併後的 dict}，Python 的 dict 會記得加入順序
    for h in holdings:
        sym = h["symbol"]
        if sym not in merged:
            merged[sym] = {
                "name": h["name"],
                "symbol": sym,
                "accounts": [],
                "shares": 0.0,
                "cost": 0.0,
                "cost_known": True,
                "price": h["price"],
            }
        m = merged[sym]
        m["accounts"].append(h["account"])
        m["shares"] += h["shares"]
        if (h["avg_price"] or 0) > 0:
            m["cost"] += h["shares"] * h["avg_price"]
        else:
            m["cost_known"] = False

    result = list(merged.values())
    for m in result:
        if not m.pop("cost_known"):
            m["cost"] = m["avg_price"] = None
        else:
            m["avg_price"] = m["cost"] / m["shares"] if m["shares"] > 0 else 0.0
    return result


def breakeven_price(total_cost: float, shares: float) -> float:
    """回本價：賣出後扣掉手續費和交易稅，剛好拿回總成本的股價。

    賣出拿到的錢 = 股價 × 股數 × (1 − 手續費 − 交易稅)
    讓它等於總成本，移項就得到：
    回本價 = 總成本 ÷ (股數 × (1 − 0.001425 − 0.003))
    """
    if shares <= 0:
        raise ValueError("股數必須大於 0")
    return total_cost / (shares * (1 - FEE_RATE - TAX_RATE))


def rise_needed_pct(breakeven: float, price: float) -> float:
    """現價還要漲幾 % 才到回本價。例如現價 90、回本價 99 → 10.0。"""
    if price <= 0:
        raise ValueError("現價必須大於 0")
    return (breakeven / price - 1) * 100


def analyze(holdings: list[dict]) -> list[dict]:
    """合併持股後，計算每檔的市值、損益、占比，虧損的再加上回本價。

    損益 = 市值 − 總成本（還沒扣賣出的手續費和稅，是帳面損益）。
    沒填均價的個股：損益、報酬率、回本價都是 None（不知道），畫面顯示「—」、也不算進總損益。
    """
    merged = merge_by_symbol(holdings)

    for m in merged:
        m["value"] = m["shares"] * m["price"]
        if m["cost"] is None:
            m["profit"] = m["profit_pct"] = None
        else:
            m["profit"] = m["value"] - m["cost"]
            m["profit_pct"] = m["profit"] / m["cost"] * 100 if m["cost"] > 0 else 0.0

    total_value = sum(m["value"] for m in merged)
    for m in merged:
        m["weight"] = m["value"] / total_value if total_value > 0 else 0.0
        # 只有虧損的個股才算回本價（None 代表不需要顯示）
        if m["profit"] is not None and m["profit"] < 0 and m["shares"] > 0 and m["price"] > 0:
            m["breakeven"] = breakeven_price(m["cost"], m["shares"])
            m["rise_needed"] = rise_needed_pct(m["breakeven"], m["price"])
        else:
            m["breakeven"] = None
            m["rise_needed"] = None
    return merged


def over_concentrated(analyzed: list[dict]) -> list[dict]:
    """找出占總市值超過 40% 的個股。"""
    return [m for m in analyzed if m["weight"] > CONCENTRATION_LIMIT]
