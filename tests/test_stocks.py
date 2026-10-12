"""
測試持股計算：回本價、還要漲幾 %、同代號合併、占比警告。

pytest.approx(x)：比較浮點數時容許極小的誤差，
因為電腦算小數會有一點點誤差（例如 0.1 + 0.2 = 0.30000000000000004）。
"""

import pytest

from models.stocks import (
    analyze,
    breakeven_price,
    merge_by_symbol,
    over_concentrated,
    rise_needed_pct,
)

# 賣出時要扣的比例：手續費 0.1425% + 交易稅 0.3% = 0.4425%
KEEP = 1 - 0.001425 - 0.003  # 賣出後實際拿到的比例 0.995575


def make_holding(symbol, account, shares, avg_price, price, name=None):
    return {"name": name or symbol, "symbol": symbol, "account": account,
            "shares": shares, "avg_price": avg_price, "price": price}


# ---------- 回本價 ----------

def test_回本價公式():
    # 1000 股、均價 100 → 總成本 100000
    assert breakeven_price(100000, 1000) == pytest.approx(100000 / (1000 * KEEP))


def test_回本價略高於均價():
    # 因為賣出要付手續費和稅，回本價一定比均價高一點
    bp = breakeven_price(100000, 1000)
    assert 100 < bp < 101
    assert bp == pytest.approx(100.4445, abs=1e-4)


def test_用回本價賣出剛好拿回成本():
    # 反過來驗證：以回本價賣出，扣掉費用後剛好等於總成本
    cost, shares = 58000, 200
    bp = breakeven_price(cost, shares)
    assert bp * shares * KEEP == pytest.approx(cost)


def test_股數為零會報錯():
    with pytest.raises(ValueError):
        breakeven_price(1000, 0)


def test_還要漲幾趴():
    assert rise_needed_pct(99, 90) == pytest.approx(10.0)
    assert rise_needed_pct(100, 100) == pytest.approx(0.0)


# ---------- 合併與分析 ----------

def test_同代號不同帳戶合併_均價是加權平均():
    holdings = [
        make_holding("2330", "富邦", 100, 500, 600),
        make_holding("2330", "國泰", 300, 600, 600),
    ]
    merged = merge_by_symbol(holdings)
    assert len(merged) == 1
    m = merged[0]
    assert m["shares"] == 400
    assert m["cost"] == 100 * 500 + 300 * 600       # 230000
    assert m["avg_price"] == pytest.approx(575)     # 不是 (500+600)/2 = 550
    assert m["accounts"] == ["富邦", "國泰"]


def test_虧損個股用合併後的成本算回本價():
    holdings = [
        make_holding("0050", "A", 1000, 150, 120),
        make_holding("0050", "B", 1000, 130, 120),
    ]
    m = analyze(holdings)[0]
    assert m["profit"] == 240000 - 280000           # 虧 40000
    assert m["breakeven"] == pytest.approx(280000 / (2000 * KEEP))
    assert m["rise_needed"] == pytest.approx((m["breakeven"] / 120 - 1) * 100)


def test_賺錢的個股不顯示回本價():
    m = analyze([make_holding("2330", "A", 10, 500, 600)])[0]
    assert m["profit"] == 1000
    assert m["breakeven"] is None
    assert m["rise_needed"] is None


def test_占比與超過四成警告():
    holdings = [
        make_holding("AAA", "A", 10, 100, 100),   # 市值 1000 → 50%
        make_holding("BBB", "A", 6, 100, 100),    # 市值  600 → 30%
        make_holding("CCC", "A", 4, 100, 100),    # 市值  400 → 20%
    ]
    analyzed = analyze(holdings)
    weights = {m["symbol"]: m["weight"] for m in analyzed}
    assert weights == pytest.approx({"AAA": 0.5, "BBB": 0.3, "CCC": 0.2})
    assert [m["symbol"] for m in over_concentrated(analyzed)] == ["AAA"]


def test_剛好四成不警告():
    holdings = [
        make_holding("AAA", "A", 4, 100, 100),
        make_holding("BBB", "A", 3, 100, 100),
        make_holding("CCC", "A", 3, 100, 100),
    ]
    assert over_concentrated(analyze(holdings)) == []
