"""
測試銀行帳戶、收入／支出記帳和帳戶餘額連動、兩種負債（2026-10-22 新功能），以及舊資料庫升級。

每個測試都用暫時的資料庫，不會碰到真正的 finance.db。
"""

import sqlite3

import pytest

import db
from models.budget import category_options, join_option, split_option


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "finance.db"))
    db.init_db()
    return tmp_path


def balance(name):
    return next(a["balance"] for a in db.get_accounts() if a["name"] == name)


# ---------- 舊資料庫升級 ----------

def test_舊資料庫升級_手上現金變成現金帳戶_舊記帳不動(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    # 照舊版的樣子建表：沒有帳戶表，記帳和負債也沒有新欄位
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE settings (key TEXT PRIMARY KEY, value REAL NOT NULL);
        INSERT INTO settings VALUES ('cash_on_hand', 12345);
        CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL NOT NULL,
                               category TEXT NOT NULL, date TEXT NOT NULL, note TEXT);
        INSERT INTO expenses (amount, category, date, note) VALUES (100, '吃飯', '2026-10-01', '舊的');
        CREATE TABLE debts (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                            remaining REAL NOT NULL, monthly_payment REAL NOT NULL);
        INSERT INTO debts (name, remaining, monthly_payment) VALUES ('學貸', 9000, 3000);
        CREATE TABLE debt_payments (id INTEGER PRIMARY KEY AUTOINCREMENT, debt_id INTEGER NOT NULL,
                                    date TEXT NOT NULL, amount REAL NOT NULL);
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", str(path))

    db.init_db()
    db.init_db()  # 再跑一次也不會重複建帳戶、重複加欄位

    assert db.get_accounts() == [{"id": 1, "name": "現金", "balance": 12345}]
    assert db.get_settings()["cash_on_hand"] == 12345
    old = db.get_records_in_month(2026, 10)[0]
    assert (old["kind"], old["account_id"], old["note"]) == ("expense", None, "舊的")
    assert db.get_debts()[0]["kind"] == "installment"


# ---------- 帳戶 ----------

def test_手上現金是所有帳戶的合計(temp_db):
    db.add_account("台新", 50000)
    db.set_account_balance(db.default_account_id(), 3000)
    assert db.get_settings()["cash_on_hand"] == 53000


def test_設定手上現金時調整現金帳戶_合計等於設定的數字(temp_db):
    db.add_account("台新", 50000)
    db.save_settings({"cash_on_hand": 60000})
    assert balance("現金") == 10000
    assert db.get_settings()["cash_on_hand"] == 60000


def test_轉帳兩邊一起改(temp_db):
    a = db.default_account_id()
    b = db.add_account("郵局", 0)
    db.set_account_balance(a, 1000)
    db.transfer(a, b, 300)
    assert (balance("現金"), balance("郵局")) == (700, 300)
    with pytest.raises(ValueError):
        db.transfer(a, a, 10)


def test_刪除帳戶_記帳留著但不再屬於那個帳戶(temp_db):
    b = db.add_account("郵局", 500)
    db.add_expense(100, "吃飯", "2026-10-01", "", account_id=b)
    db.delete_account(b)
    assert [a["name"] for a in db.get_accounts()] == ["現金"]
    assert db.get_records_in_month(2026, 10)[0]["account_id"] is None
    with pytest.raises(ValueError):
        db.delete_account(db.default_account_id())  # 最後一個帳戶不能刪


# ---------- 記帳和帳戶連動 ----------

def test_支出扣帳戶_收入加帳戶(temp_db):
    a = db.default_account_id()
    db.add_expense(200, "吃飯", "2026-10-01", "", subcategory="午餐", account_id=a)
    db.add_expense(30000, "薪資", "2026-10-05", "", subcategory="月薪", account_id=a, kind="income")
    assert balance("現金") == 29800
    # 支出清單（給預算用）不含收入
    assert [e["amount"] for e in db.get_expenses_in_month(2026, 10)] == [200]
    assert len(db.get_records_in_month(2026, 10)) == 2


def test_修改記帳換帳戶_兩個帳戶都對得上(temp_db):
    a, b = db.default_account_id(), db.add_account("台新", 0)
    db.add_expense(100, "吃飯", "2026-10-01", "", account_id=a)
    rid = db.get_records_in_month(2026, 10)[0]["id"]
    db.update_expense(rid, 150, "交通", "2026-10-01", "", subcategory="捷運公車", account_id=b)
    assert (balance("現金"), balance("台新")) == (0, -150)


def test_刪除記帳還原帳戶餘額(temp_db):
    a = db.default_account_id()
    db.add_expense(5000, "薪資", "2026-10-01", "", account_id=a, kind="income")
    db.delete_expense(db.get_records_in_month(2026, 10)[0]["id"])
    assert balance("現金") == 0


def test_沒有選帳戶的記帳不影響餘額(temp_db):
    db.add_expense(100, "吃飯", "2026-10-01", "")
    assert balance("現金") == 0


# ---------- 類別選單 ----------

def test_類別選單把主類別和細項攤平():
    assert "吃飯 · 午餐" in category_options("expense")
    assert "薪資 · 月薪" in category_options("income")
    assert split_option("吃飯 · 午餐") == ("吃飯", "午餐")
    assert split_option("吃飯") == ("吃飯", None)   # 舊資料沒有細項
    assert join_option("吃飯", None) == "吃飯"


# ---------- 負債 ----------

def test_定期還從選的帳戶扣(temp_db):
    b = db.add_account("台新", 10000)
    db.add_debt("學貸", 9000, 3000)
    db.pay_debt_installment(db.get_debts()[0]["id"], account_id=b)
    assert balance("台新") == 7000
    assert db.get_debts()[0]["remaining"] == 6000
    assert db.get_debt_payments(db.get_debts()[0]["id"])[0]["account_id"] == b


def test_不限期負債_還多少都可以_還超過只還剩下的(temp_db):
    a = db.default_account_id()
    db.set_account_balance(a, 10000)
    db.add_debt("跟朋友借", 5000, 999, kind="open")
    debt = db.get_debts()[0]
    assert (debt["kind"], debt["monthly_payment"]) == ("open", 0)  # 不限期沒有每月還款
    db.pay_debt(debt["id"], 1200)
    assert db.get_debts()[0]["remaining"] == 3800
    assert db.pay_debt(debt["id"], 99999) == 3800   # 只還剩下的
    assert balance("現金") == 10000 - 5000


def test_帳戶不夠時什麼都不改(temp_db):
    db.add_debt("跟朋友借", 5000, 0, kind="open")
    debt_id = db.get_debts()[0]["id"]
    with pytest.raises(ValueError):
        db.pay_debt(debt_id, 100)
    assert db.get_debts()[0]["remaining"] == 5000
    assert db.get_debt_payments(debt_id) == []
