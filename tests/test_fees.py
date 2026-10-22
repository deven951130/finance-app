"""
測試手續費、交易稅、買賣後的均價（models/fees.py），以及沒填均價時的持股計算（models/stocks.py）。
數字都是手算對照的。
"""

import pytest

from models.fees import avg_after_buy, broker_fee, is_etf, realized_pnl, sell_tax, trade_summary
from models.stocks import analyze


def test_手續費_打折_無條件捨去():
    # 1,000,000 × 0.1425% = 1425；2.8 折 = 399 → 無條件捨去
    assert broker_fee(1_000_000) == 1425
    assert broker_fee(1_000_000, discount=0.28) == 399
    assert broker_fee(1_000_000, discount=0.6) == 855


def test_手續費_不足最低手續費():
    # 10,000 × 0.1425% = 14.25 → 不到 20 元收 20 元；券商最低 1 元時收 14 元
    assert broker_fee(10_000) == 20
    assert broker_fee(10_000, min_fee=1) == 14
    assert broker_fee(0) == 0


def test_交易稅_股票_ETF_當沖():
    assert sell_tax(1_000_000, "2330") == 3000
    assert sell_tax(1_000_000, "0050") == 1000           # ETF 0.1%
    assert sell_tax(1_000_000, "00631L") == 1000
    assert sell_tax(1_000_000, "2330", day_trade=True) == 1500
    assert is_etf("00878") and not is_etf("2330")


def test_買進一張_帳戶付出成交金額加手續費():
    r = trade_summary("buy", "2330", 1000, 1000, discount=0.28)
    assert r == {"amount": 1_000_000, "fee": 399, "tax": 0, "cash": -1_000_399}


def test_賣出一張_帳戶拿回成交金額減手續費和稅():
    r = trade_summary("sell", "2330", 1000, 1000, discount=0.28)
    assert r == {"amount": 1_000_000, "fee": 399, "tax": 3000, "cash": 996_601}


def test_零股_成交金額小_收最低手續費():
    r = trade_summary("buy", "0050", 10, 150)
    assert r == {"amount": 1500, "fee": 20, "tax": 0, "cash": -1520}


def test_加碼後的均價含手續費():
    # 原本 1000 股均價 100，再買 1000 股付了 110,000（含手續費）→ 210,000 ÷ 2000 = 105
    assert avg_after_buy(1000, 100, 1000, 110_000) == pytest.approx(105)
    assert avg_after_buy(0, None, 1000, 100_399) == pytest.approx(100.399)
    assert avg_after_buy(1000, None, 1000, 100_000) is None   # 原本的成本不知道，加碼後也不知道


def test_實現損益():
    assert realized_pnl(996_601, 900, 1000) == pytest.approx(96_601)
    assert realized_pnl(996_601, None, 1000) is None


def test_沒填均價的持股_損益是不知道_不是賺整個市值():
    holdings = [
        {"name": "台積電", "symbol": "2330", "account": "A", "shares": 10, "avg_price": 0, "price": 1000},
        {"name": "元大台灣50", "symbol": "0050", "account": "A", "shares": 100, "avg_price": 100, "price": 150},
    ]
    result = {m["symbol"]: m for m in analyze(holdings)}
    assert result["2330"]["profit"] is None and result["2330"]["breakeven"] is None
    assert result["2330"]["value"] == 10_000            # 市值照算
    assert result["0050"]["profit"] == pytest.approx(5000)
    # 同一檔在兩個帳戶，只要有一個沒填均價，合併後的成本就是不知道
    two = analyze([dict(holdings[1]), dict(holdings[1], account="B", avg_price=0)])
    assert two[0]["profit"] is None and two[0]["shares"] == 200
