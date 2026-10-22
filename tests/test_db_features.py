"""
測試 v1 新增的功能：還款紀錄、修改記帳、趨勢加總、自動備份與還原、第一次使用判斷。

每個測試都用暫時的資料庫（tmp_path），不會碰到真正的 finance.db。
"""

import os
import sqlite3
from datetime import date

import pytest

import db
from models.budget import last_n_months, monthly_totals
from models.debt import paid_in_month


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """把 db.DB_PATH 換成暫時資料夾裡的檔案，測完自動刪掉。"""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "finance.db"))
    db.init_db()
    return tmp_path


# ---------- 還款紀錄 ----------

def test_還一期_會記一筆還款紀錄(temp_db):
    db.save_settings({"cash_on_hand": 10000})
    db.add_debt("學貸", 9000, 3000)
    debt_id = db.get_debts()[0]["id"]

    db.pay_debt_installment(debt_id, "2026-10-05")

    payments = db.get_debt_payments(debt_id)
    assert len(payments) == 1
    assert payments[0]["date"] == "2026-10-05"
    assert payments[0]["amount"] == pytest.approx(3000)
    assert db.get_debts()[0]["remaining"] == pytest.approx(6000)
    assert db.get_settings()["cash_on_hand"] == pytest.approx(7000)


def test_現金不夠_負債現金和紀錄都不變(temp_db):
    db.save_settings({"cash_on_hand": 1000})
    db.add_debt("學貸", 9000, 3000)
    debt_id = db.get_debts()[0]["id"]

    with pytest.raises(ValueError):
        db.pay_debt_installment(debt_id)

    assert db.get_debts()[0]["remaining"] == pytest.approx(9000)
    assert db.get_settings()["cash_on_hand"] == pytest.approx(1000)
    assert db.get_debt_payments(debt_id) == []


def test_刪除負債_還款紀錄也一起刪(temp_db):
    db.save_settings({"cash_on_hand": 10000})
    db.add_debt("學貸", 9000, 3000)
    debt_id = db.get_debts()[0]["id"]
    db.pay_debt_installment(debt_id)

    db.delete_debt(debt_id)
    assert db.get_debt_payments(debt_id) == []


def test_本月是否已還():
    payments = [{"date": "2026-09-30"}, {"date": "2026-10-01"}]
    assert paid_in_month(payments, 2026, 10)
    assert paid_in_month(payments, 2026, 9)
    assert not paid_in_month(payments, 2026, 11)
    assert not paid_in_month([], 2026, 10)


# ---------- 修改記帳 ----------

def test_修改一筆支出(temp_db):
    db.add_expense(100, "吃飯", "2026-10-01", "午餐")
    expense_id = db.get_expenses_in_month(2026, 10)[0]["id"]

    db.update_expense(expense_id, 250, "交通", "2026-09-30", "計程車")

    assert db.get_expenses_in_month(2026, 10) == []
    moved = db.get_expenses_in_month(2026, 9)[0]
    assert (moved["amount"], moved["category"], moved["note"]) == (250, "交通", "計程車")


def test_有記帳的月份_新的在前面(temp_db):
    db.add_expense(100, "吃飯", "2026-08-01", "")
    db.add_expense(100, "吃飯", "2026-10-01", "")
    db.add_expense(100, "吃飯", "2026-10-15", "")
    assert db.get_expense_months() == ["2026-10", "2026-08"]


# ---------- 趨勢 ----------

def test_最近幾個月_跨年():
    assert last_n_months(date(2026, 2, 10), 3) == ["2025-12", "2026-01", "2026-02"]
    assert last_n_months(date(2026, 10, 1), 1) == ["2026-10"]


def test_每月各類別加總_沒花錢的月份是0():
    expenses = [
        {"date": "2026-10-01", "category": "吃飯", "amount": 100},
        {"date": "2026-10-20", "category": "吃飯", "amount": 50},
        {"date": "2026-08-01", "category": "交通", "amount": 999},  # 不在範圍內，不算
    ]
    rows = monthly_totals(expenses, ["2026-09", "2026-10"])
    table = {(r["月份"], r["類別"]): r["金額"] for r in rows}
    assert table[("2026-10", "吃飯")] == pytest.approx(150)
    assert table[("2026-09", "吃飯")] == 0
    assert ("2026-08", "交通") not in table


# ---------- 自動備份與還原 ----------

def test_每天只備份一次(temp_db):
    first = db.auto_backup(date(2026, 10, 1))
    assert first and os.path.exists(first)
    assert db.auto_backup(date(2026, 10, 1)) is None  # 同一天第二次不備份
    assert db.auto_backup(date(2026, 10, 2)) is not None
    assert len(db.list_backups()) == 2


def test_只留最近幾份備份(temp_db, monkeypatch):
    monkeypatch.setattr(db, "BACKUP_KEEP", 3)
    for d in range(1, 7):
        db.auto_backup(date(2026, 10, d))
    names = [os.path.basename(p) for p in db.list_backups()]
    assert names == ["finance-2026-10-06.db", "finance-2026-10-05.db", "finance-2026-10-04.db"]


def test_還原備份_並先另存目前的資料(temp_db):
    db.add_expense(100, "吃飯", "2026-10-01", "備份前就有")
    backup = db.auto_backup(date(2026, 10, 1))
    db.add_expense(999, "其他", "2026-10-02", "備份後才記")

    safety = db.restore_backup(backup)

    notes = [e["note"] for e in db.get_expenses_in_month(2026, 10)]
    assert notes == ["備份前就有"]
    # 還原前的資料另存了一份，裡面有「備份後才記」那一筆
    with sqlite3.connect(safety) as conn:
        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    conn.close()
    assert count == 2


def test_還原不是資料庫的檔案_會拒絕而且資料不變(temp_db):
    db.add_expense(100, "吃飯", "2026-10-01", "")
    bad = temp_db / "not-a-db.db"
    bad.write_bytes(b"hello")
    with pytest.raises(ValueError):
        db.restore_backup(str(bad))
    assert len(db.get_expenses_in_month(2026, 10)) == 1


# ---------- 第一次使用 ----------

def test_剛建立的資料庫是空的(temp_db):
    assert db.is_empty()
    db.save_settings({"monthly_income": 30000})
    assert not db.is_empty()


def test_有記帳就不是空的(temp_db):
    db.add_expense(100, "吃飯", "2026-10-01", "")
    assert not db.is_empty()


# ---------- 淨資產紀錄 ----------

def test_淨資產同一天只留最後一筆(temp_db):
    db.record_networth("2026-10-01", 100)
    db.record_networth("2026-10-01", 150)
    db.record_networth("2026-10-02", 200)
    assert db.get_networth_history() == [{"date": "2026-10-01", "value": 150},
                                         {"date": "2026-10-02", "value": 200}]


# ---------- 歡迎畫面判斷：填過任何東西就不是空的 ----------

def test_只填了現金_不算空的(temp_db):
    db.save_settings({"cash_on_hand": 5000})
    assert not db.is_empty()


def test_只設了預算_不算空的(temp_db):
    db.save_budgets({"吃飯": 3000})
    assert not db.is_empty()


def test_設定都是預設值_算空的(temp_db):
    db.save_settings(dict(db.DEFAULT_SETTINGS))
    assert db.is_empty()


# ---------- 是不是平常那個資料庫 ----------

def test_平常的資料庫位置_不提醒():
    for path in db.standard_db_paths():
        assert not db.is_unusual_db(path)


def test_被指到其他檔案_要提醒(tmp_path):
    assert db.is_unusual_db(str(tmp_path / "hubtest.db"))


def test_範例資料庫_不提醒(tmp_path):
    assert not db.is_unusual_db(str(tmp_path / "example.db"))


# ---------- 自動更新股價寫回持股 ----------

def test_股價寫回持股_代號大小寫空白都對得上(temp_db):
    db.add_holding("台積電", "2330 ", "A", 10, 900, 900)
    db.add_holding("台積電", "2330", "B", 10, 900, 900)
    db.add_holding("槓桿", "00631l", "A", 10, 20, 20)
    db.add_holding("某基金", "FUND1", "A", 10, 10, 10)

    updated = db.update_prices({"2330": 1000.0, "00631L": 30.0})

    assert updated == 3
    prices = {(h["symbol"], h["account"]): h["price"] for h in db.get_holdings()}
    assert prices[("2330 ", "A")] == 1000.0
    assert prices[("2330", "B")] == 1000.0
    assert prices[("00631l", "A")] == 30.0
    assert prices[("FUND1", "A")] == 10  # 沒有報價的保持原價
