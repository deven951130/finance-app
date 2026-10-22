"""
測試券商手續費、真的買進／賣出（db.execute_trade）：帳戶、持股、交易紀錄三個一起改。

數字都是虛構的；每個測試都用暫時的資料庫，不會碰到真正的 finance.db。
"""

import sqlite3

import pytest

import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "finance.db"))
    db.init_db()
    db.save_settings({"cash_on_hand": 100000})  # 第一個帳戶「現金」有 10 萬
    return tmp_path


def cash():
    return db.get_settings()["cash_on_hand"]


def holding(symbol, broker):
    return next((h for h in db.get_holdings() if h["symbol"] == symbol and h["account"] == broker), None)


# ---------- 券商 ----------

def test_新增持股遇到新券商自動建立_預設不打折最低20元(temp_db):
    db.add_holding("範例股", "1111", "A 證券", 1000, 50, 55)
    assert db.get_brokers() == [{"id": 1, "name": "A 證券", "discount": 1.0, "min_fee": 20.0}]


def test_修改券商折扣(temp_db):
    db.save_broker("A 證券", 0.28, 1)
    db.save_broker("A 證券", 0.6, 20)  # 同名是修改，不會多一列
    assert [(b["name"], b["discount"], b["min_fee"]) for b in db.get_brokers()] == [("A 證券", 0.6, 20)]
    with pytest.raises(ValueError):
        db.save_broker("A 證券", 2.8, 20)  # 2.8 折要填 0.28，不是 2.8


def test_舊資料庫升級_持股的帳戶變成券商(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE holdings (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, symbol TEXT NOT NULL,
                               account TEXT NOT NULL, shares REAL NOT NULL, avg_price REAL NOT NULL,
                               price REAL NOT NULL);
        INSERT INTO holdings (name, symbol, account, shares, avg_price, price) VALUES ('甲', '1111', 'B 證券', 1, 1, 1);
        CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, symbol TEXT NOT NULL,
                             type TEXT NOT NULL, pnl REAL NOT NULL DEFAULT 0, note TEXT);
        INSERT INTO trades (date, symbol, type, pnl, note) VALUES ('2026-10-01', '1111', '賣出', 500, '舊的');
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    assert [b["name"] for b in db.get_brokers()] == ["B 證券"]
    old = db.get_trades()[0]
    assert (old["pnl"], old["side"], old["fee"]) == (500, None, None)  # 舊紀錄不變，新欄位是空的


# ---------- 買進 ----------

def test_買進新股票_帳戶扣金額加手續費_新增持股(temp_db):
    # 100 股 × 50 元 = 5000，手續費 5000 × 0.1425% = 7.1 → 不到 20 元收 20
    result = db.execute_trade("buy", "1111", "A 證券", 100, 50, db.default_account_id(), name="範例股")
    assert (result["amount"], result["fee"], result["tax"], result["cash"]) == (5000, 20, 0, -5020)
    assert cash() == 100000 - 5020
    h = holding("1111", "A 證券")
    assert (h["name"], h["shares"], h["price"]) == ("範例股", 100, 50)
    assert h["avg_price"] == pytest.approx(50.2)  # 均價含手續費
    t = db.get_trades()[0]
    assert (t["type"], t["side"], t["fee"], t["broker"]) == ("買進", "buy", 20, "A 證券")


def test_加碼_均價用加權平均含手續費(temp_db):
    db.add_holding("範例股", "1111", "A 證券", 1000, 50, 50)
    db.save_broker("A 證券", 0.6, 20)
    # 1000 股 × 60 = 60000，手續費 60000 × 0.1425% × 0.6 = 51.3 → 51
    db.execute_trade("buy", "1111", "A 證券", 1000, 60, db.default_account_id())
    h = holding("1111", "A 證券")
    assert h["shares"] == 2000
    assert h["avg_price"] == pytest.approx((50000 + 60051) / 2000)
    assert cash() == 100000 - 60051


def test_沒有均價的持股加碼後均價還是不知道(temp_db):
    db.add_holding("範例股", "1111", "A 證券", 1000, 0, 50)
    db.execute_trade("buy", "1111", "A 證券", 100, 50, db.default_account_id())
    assert holding("1111", "A 證券")["avg_price"] == 0


def test_帳戶餘額不夠就不買_什麼都不改(temp_db):
    with pytest.raises(ValueError, match="不夠"):
        db.execute_trade("buy", "1111", "A 證券", 1000, 500, db.default_account_id())
    assert cash() == 100000
    assert db.get_holdings() == [] and db.get_trades() == []


# ---------- 賣出 ----------

def test_賣出_帳戶加回扣掉手續費和稅_記實現損益(temp_db):
    db.add_holding("範例股", "1111", "A 證券", 1000, 50, 50)
    # 400 股 × 60 = 24000；手續費 24000 × 0.1425% = 34.2 → 34；一般股票稅 0.3% = 72
    result = db.execute_trade("sell", "1111", "A 證券", 400, 60, db.default_account_id())
    assert (result["fee"], result["tax"], result["cash"]) == (34, 72, 24000 - 34 - 72)
    assert result["pnl"] == pytest.approx(23894 - 50 * 400)
    assert cash() == 100000 + 23894
    assert holding("1111", "A 證券")["shares"] == 600
    t = db.get_trades()[0]
    assert (t["type"], t["pnl"], t["tax"]) == ("賣出", 3894, 72)


def test_ETF賣出稅是千分之一_當沖是千分之一點五(temp_db):
    db.add_holding("範例ETF", "0099", "A 證券", 1000, 20, 20)
    assert db.execute_trade("sell", "0099", "A 證券", 500, 20, db.default_account_id())["tax"] == 10
    db.add_holding("範例股", "1111", "A 證券", 1000, 20, 20)
    r = db.execute_trade("sell", "1111", "A 證券", 500, 20, db.default_account_id(), day_trade=True)
    assert r["tax"] == 15
    assert db.get_trades()[0]["type"] == "當沖"


def test_全部賣光_持股那一列刪掉(temp_db):
    db.add_holding("範例股", "1111", "A 證券", 100, 50, 50)
    db.execute_trade("sell", "1111", "A 證券", 100, 50, db.default_account_id())
    assert holding("1111", "A 證券") is None


def test_股數不夠或券商不對就不能賣(temp_db):
    db.add_holding("範例股", "1111", "A 證券", 100, 50, 50)
    with pytest.raises(ValueError, match="只有 100 股"):
        db.execute_trade("sell", "1111", "A 證券", 200, 50, db.default_account_id())
    with pytest.raises(ValueError, match="只有 0 股"):
        db.execute_trade("sell", "1111", "B 證券", 10, 50, db.default_account_id())
    assert cash() == 100000 and holding("1111", "A 證券")["shares"] == 100


def test_沒有均價時賣出_損益記0並註明(temp_db):
    db.add_holding("範例股", "1111", "A 證券", 100, 0, 50)
    result = db.execute_trade("sell", "1111", "A 證券", 100, 50, db.default_account_id(), note="停損")
    assert result["pnl"] is None
    t = db.get_trades()[0]
    assert t["pnl"] == 0 and t["note"] == "停損；沒有均價，損益沒算"


def test_代號大小寫空白都對得上(temp_db):
    db.add_holding("範例槓桿", "00631l ", "A 證券", 100, 100, 100)
    db.execute_trade("sell", "00631L", "A 證券", 50, 100, db.default_account_id())
    assert db.get_holdings()[0]["shares"] == 50


def test_預覽不改資料庫(temp_db):
    p = db.trade_preview("buy", "1111", "A 證券", 1000, 100)
    assert (p["fee"], p["cash"]) == (142, -100142)
    assert cash() == 100000 and db.get_trades() == [] and db.get_brokers() == []
