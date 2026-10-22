"""
測試買賣交易：買進、賣出、券商手續費折扣、帳戶餘額和持股要一起改，而且要全部成功或全部不改。

每個測試都用暫時的資料庫（tmp_path），不會碰到真正的 finance.db。
數字都是手算過的（台股手續費 0.1425%、賣出交易稅 0.3%，無條件捨去）。
"""

import pytest

import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "finance.db"))
    db.init_db()
    db.save_settings({"cash_on_hand": 1_000_000})
    return tmp_path


def cash():
    return db.get_accounts()[0]["balance"]


def holding(symbol="2330", broker="永豐"):
    rows = [h for h in db.get_holdings() if h["symbol"] == symbol and h["account"] == broker]
    return rows[0] if rows else None


# ---------- 買進 ----------

def test_買進_帳戶扣金額加手續費_持股和均價照算(temp_db):
    # 1000 股 × 100 = 100000，手續費 floor(100000 × 0.001425) = 142
    result = db.execute_trade("buy", "2330", "永豐", 1000, 100, date_str="2026-10-22", name="台積電")

    assert result["amount"] == 100000
    assert result["fee"] == 142
    assert result["tax"] == 0
    assert cash() == pytest.approx(1_000_000 - 100142)
    h = holding()
    assert h["name"] == "台積電"
    assert h["shares"] == 1000
    assert h["avg_price"] == pytest.approx(100.142)  # 均價含手續費
    assert result["pnl"] == 0.0


def test_再買一次_均價是加權平均(temp_db):
    db.execute_trade("buy", "2330", "永豐", 1000, 100)   # 成本 100142
    db.execute_trade("buy", "2330", "永豐", 1000, 120)   # 成本 120000 + 手續費 171 = 120171

    h = holding()
    assert h["shares"] == 2000
    assert h["avg_price"] == pytest.approx((100142 + 120171) / 2000)


def test_買進的均價不知道_加碼後還是不知道(temp_db):
    # 先手動加一筆沒填均價的持股（均價存 0 = 不知道）
    db.add_holding("台積電", "2330", "永豐", 1000, 0, 100)
    db.execute_trade("buy", "2330", "永豐", 1000, 120)

    h = holding()
    assert h["shares"] == 2000
    assert h["avg_price"] == 0


def test_餘額不夠_什麼都不改(temp_db):
    db.save_settings({"cash_on_hand": 50000})

    with pytest.raises(ValueError, match="不夠買"):
        db.execute_trade("buy", "2330", "永豐", 1000, 100)

    assert cash() == 50000
    assert holding() is None
    assert db.get_trades() == []


def test_新券商自動建立_用預設折扣(temp_db):
    db.execute_trade("buy", "2330", "新券商", 10, 100)

    brokers = {b["name"]: b for b in db.get_brokers()}
    assert brokers["新券商"]["discount"] == 1.0
    assert brokers["新券商"]["min_fee"] == 20


def test_手續費折扣_2點8折(temp_db):
    # 1000 × 100 = 100000，× 0.001425 × 0.28 = 39.9，捨去成 39
    db.save_broker("元大", 0.28, 20)

    result = db.execute_trade("buy", "2330", "元大", 1000, 100)

    assert result["fee"] == 39


def test_手續費不足最低額_收最低手續費(temp_db):
    # 10 元的交易，手續費 0.01 元，不足 20 元就收 20
    result = db.execute_trade("buy", "2330", "永豐", 1, 10)

    assert result["fee"] == 20
    assert cash() == pytest.approx(1_000_000 - 30)


# ---------- 賣出 ----------

def test_賣出_帳戶加成交金額減手續費和稅_持股扣股數(temp_db):
    db.execute_trade("buy", "2330", "永豐", 1000, 100)  # 成本 100142，均價 100.142
    before = cash()

    # 500 × 120 = 60000，手續費 floor(60000 × 0.001425) = 85，稅 floor(60000 × 0.003) = 180
    result = db.execute_trade("sell", "2330", "永豐", 500, 120)

    assert result["amount"] == 60000
    assert result["fee"] == 85
    assert result["tax"] == 180
    assert cash() == pytest.approx(before + 59735)
    assert holding()["shares"] == 500
    # 實現損益 = 拿回來的錢 − 這 500 股的成本 = 59735 − 100.142 × 500
    assert result["pnl"] == pytest.approx(59735 - 100.142 * 500)


def test_賣光_持股那列刪掉(temp_db):
    db.execute_trade("buy", "2330", "永豐", 1000, 100)
    db.execute_trade("sell", "2330", "永豐", 1000, 100)

    assert holding() is None


def test_賣超過持有的股數_什麼都不改(temp_db):
    db.execute_trade("buy", "2330", "永豐", 1000, 100)
    before = cash()

    with pytest.raises(ValueError, match="不夠賣"):
        db.execute_trade("sell", "2330", "永豐", 1001, 100)

    assert cash() == before
    assert holding()["shares"] == 1000
    assert len(db.get_trades()) == 1  # 只有買進那一筆


def test_只能賣自己券商的持股(temp_db):
    db.execute_trade("buy", "2330", "永豐", 1000, 100)

    with pytest.raises(ValueError, match="不夠賣"):
        db.execute_trade("sell", "2330", "元大", 100, 100)


def test_均價不知道_賣出的實現損益是None(temp_db):
    db.add_holding("台積電", "2330", "永豐", 1000, 0, 100)

    result = db.execute_trade("sell", "2330", "永豐", 100, 120)

    assert result["pnl"] is None
    assert db.get_trades()[0]["pnl"] == 0  # 資料庫欄位不能是 NULL，存 0


def test_當沖賣出_稅率是千五(temp_db):
    db.execute_trade("buy", "2330", "永豐", 1000, 100)

    # 60000 × 0.0015 = 90，不是 0.3% 的 180
    result = db.execute_trade("sell", "2330", "永豐", 500, 120, day_trade=True)

    assert result["tax"] == 90
    assert db.get_trades()[0]["type"] == "當沖"


def test_ETF賣出_稅率是千一(temp_db):
    db.execute_trade("buy", "0050", "永豐", 1000, 100)

    # 60000 × 0.001 = 60
    result = db.execute_trade("sell", "0050", "永豐", 500, 120)

    assert result["tax"] == 60


# ---------- 交易紀錄 ----------

def test_買賣紀錄會寫進交易紀錄(temp_db):
    db.execute_trade("buy", "2330", "永豐", 1000, 100, date_str="2026-10-22")

    trade = db.get_trades()[0]
    assert trade["side"] == "buy"
    assert trade["type"] == "買進"
    assert trade["shares"] == 1000
    assert trade["price"] == 100
    assert trade["fee"] == 142
    assert trade["broker"] == "永豐"
    assert trade["date"] == "2026-10-22"


def test_買賣紀錄不能直接刪除(temp_db):
    db.execute_trade("buy", "2330", "永豐", 1000, 100)
    trade_id = db.get_trades()[0]["id"]

    with pytest.raises(ValueError, match="不能直接刪除"):
        db.delete_trade(trade_id)

    assert len(db.get_trades()) == 1


def test_手動記的交易還是可以刪除(temp_db):
    db.add_trade("2026-10-22", "2330", "當沖", -500, "")
    trade_id = db.get_trades()[0]["id"]

    db.delete_trade(trade_id)

    assert db.get_trades() == []


def test_沒指定帳戶_就用第一個帳戶(temp_db):
    db.add_account("台新銀行", 0)

    db.execute_trade("buy", "2330", "永豐", 1000, 100)

    assert cash() == pytest.approx(1_000_000 - 100142)
