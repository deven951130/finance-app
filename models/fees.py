"""
台股交易的手續費、證券交易稅，以及買賣後的持股均價（純函式，不碰資料庫）。

規則（2026-10 的台股制度；每家券商的折扣和最低手續費不同，所以都當參數傳進來）：
- 手續費 = 成交金額 × 0.1425% × 折扣，無條件捨去到整數元；不足最低手續費時收最低手續費（一般 20 元）。
  買進、賣出都要付。
- 證券交易稅（只有賣出時付，無條件捨去到整數元）：
    一般股票 0.3%；ETF 0.1%（代號 00 開頭）；當沖賣出 0.15%。
"""

import math

FEE_RATE = 0.001425
TAX_STOCK = 0.003
TAX_ETF = 0.001
TAX_DAY_TRADE = 0.0015
DEFAULT_MIN_FEE = 20.0


def is_etf(symbol: str) -> bool:
    """台股 ETF 的代號都是 00 開頭（例如 0050、00878、00631L）。"""
    return symbol.strip().startswith("00")


def broker_fee(amount: float, discount: float = 1.0, min_fee: float = DEFAULT_MIN_FEE) -> int:
    """手續費。discount 是折扣：1 = 不打折、0.6 = 六折、0.28 = 2.8 折。"""
    if amount <= 0:
        return 0
    return max(math.floor(amount * FEE_RATE * discount), int(min_fee))


def sell_tax(amount: float, symbol: str, day_trade: bool = False) -> int:
    """賣出的證券交易稅。"""
    if amount <= 0:
        return 0
    rate = TAX_DAY_TRADE if day_trade else (TAX_ETF if is_etf(symbol) else TAX_STOCK)
    return math.floor(amount * rate)


def trade_summary(side: str, symbol: str, shares: float, price: float,
                  discount: float = 1.0, min_fee: float = DEFAULT_MIN_FEE, day_trade: bool = False) -> dict:
    """一筆買進（side="buy"）或賣出（side="sell"）的金額明細。

    回傳 amount（成交金額）、fee（手續費）、tax（交易稅，買進是 0），
    以及 cash（帳戶的變化：買進是負數 = 付出去的錢，賣出是正數 = 拿回來的錢）。
    """
    amount = round(shares * price)
    fee = broker_fee(amount, discount, min_fee)
    tax = sell_tax(amount, symbol, day_trade) if side == "sell" else 0
    cash = -(amount + fee) if side == "buy" else amount - fee - tax
    return {"amount": amount, "fee": fee, "tax": tax, "cash": cash}


def avg_after_buy(old_shares: float, old_avg: float | None, buy_shares: float, buy_cost: float) -> float | None:
    """加碼後的均價（含手續費）：(原本的總成本 + 這次付的錢) ÷ 總股數。

    原本的均價不知道（None 或 0）而且原本有股票時，加碼後也算不出來，回傳 None；
    原本沒有股票時，均價就是這次的成本 ÷ 股數。
    """
    if old_shares <= 0:
        return buy_cost / buy_shares
    if not old_avg:
        return None
    return (old_shares * old_avg + buy_cost) / (old_shares + buy_shares)


def realized_pnl(proceeds: float, avg: float | None, shares: float) -> float | None:
    """賣出的實現損益 = 拿回來的錢（已扣手續費、稅）− 這些股票的成本。均價不知道時回傳 None。"""
    if not avg:
        return None
    return proceeds - avg * shares
