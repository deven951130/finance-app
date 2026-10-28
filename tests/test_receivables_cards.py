"""
別人欠我的錢、信用卡費：models/ 的計算（純函式），和 db.py 的讀寫（用暫時的資料庫）。
數字都是虛構的。
"""

from datetime import date

import pytest

import db
from models.cards import (bill_from_records, bill_month, bill_status, card_cashflow, due_date, month_total,
                          unpaid, unpaid_total)
from models.receivables import collect_amount, collected_ratio, outstanding_total


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    db.save_settings({"cash_on_hand": 10000})


# ---------- models/receivables.py ----------

def test_收回比剩下多_只算剩下的():
    assert collect_amount(3000, 5000) == 3000
    assert collect_amount(3000, 1000) == 1000


def test_還沒收回的合計_不算已經收完的():
    items = [{"remaining": 2000}, {"remaining": 0}, {"remaining": 500}]
    assert outstanding_total(items) == 2500


def test_收回幾成():
    assert collected_ratio(4000, 1000) == pytest.approx(0.75)
    assert collected_ratio(0, 0) == 0.0


# ---------- models/cards.py ----------

def test_截止日超過月底_用月底():
    assert due_date("2027-02", 31) == date(2027, 2, 28)
    assert due_date("2026-11", 15) == date(2026, 11, 15)


def test_帳單狀態():
    due = date(2026, 11, 15)
    assert bill_status(3000, 3000, due, date(2026, 11, 20)) == "paid"
    assert bill_status(0, 0, due, date(2026, 11, 20)) == "paid"
    assert bill_status(3000, 1000, due, date(2026, 11, 16)) == "overdue"
    assert bill_status(3000, 0, due, date(2026, 11, 10)) == "due_soon"   # 剛好 5 天
    assert bill_status(3000, 0, due, date(2026, 11, 1)) == "upcoming"


def test_未繳合計和當月帳單合計():
    bills = [{"month": "2026-11", "amount": 3000, "paid": 1000},
             {"month": "2026-11", "amount": 2000, "paid": 2500},  # 多繳不算負的
             {"month": "2026-10", "amount": 4000, "paid": 4000}]
    assert unpaid(2000, 2500) == 0
    assert unpaid_total(bills) == 2000
    assert month_total(bills, "2026-11") == 5000


# ---------- db.py：別人欠我的錢 ----------

def test_借出去_從帳戶扣錢(temp_db):
    cash = db.default_account_id()
    db.add_receivable("範例朋友", 3000, "2026-10-01", "", account_id=cash)
    r = db.get_receivables()[0]
    assert (r["amount"], r["remaining"]) == (3000, 3000)
    assert db.get_settings()["cash_on_hand"] == 7000


def test_以前借的_不扣帳戶(temp_db):
    db.add_receivable("範例朋友", 3000, "2026-10-01", "")
    assert db.get_settings()["cash_on_hand"] == 10000


def test_借出去_帳戶不夠時什麼都不改(temp_db):
    with pytest.raises(ValueError):
        db.add_receivable("範例朋友", 20000, "2026-10-01", "", account_id=db.default_account_id())
    assert db.get_receivables() == []
    assert db.get_settings()["cash_on_hand"] == 10000


def test_收回一筆_欠款減少帳戶增加(temp_db):
    db.add_receivable("範例朋友", 3000, "2026-10-01", "")
    rid = db.get_receivables()[0]["id"]
    bank = db.add_account("範例銀行", 0)
    assert db.collect_receivable(rid, 1000, bank, "2026-10-10") == 1000
    assert db.collect_receivable(rid, 5000, bank, "2026-10-20") == 2000  # 只剩 2000
    assert db.get_receivables()[0]["remaining"] == 0
    assert {a["name"]: a["balance"] for a in db.get_accounts()}["範例銀行"] == 3000
    assert [p["amount"] for p in db.get_receivable_payments(rid)] == [2000, 1000]
    with pytest.raises(ValueError):
        db.collect_receivable(rid, 100, bank)  # 收完了


def test_刪除欠款_連同收款紀錄(temp_db):
    db.add_receivable("範例朋友", 3000, "2026-10-01", "")
    rid = db.get_receivables()[0]["id"]
    db.collect_receivable(rid, 1000, db.default_account_id())
    db.delete_receivable(rid)
    assert db.get_receivables() == []
    assert db.get_receivable_payments(rid) == []


# ---------- db.py：信用卡 ----------

def test_填帳單_同一個月再填是修改(temp_db):
    card = db.add_card("範例卡", 15)
    db.set_card_bill(card, "2026-11", 3000)
    db.set_card_bill(card, "2026-11", 3200)
    bills = db.get_card_bills()
    assert len(bills) == 1
    assert (bills[0]["amount"], bills[0]["paid"], bills[0]["card_name"]) == (3200, 0, "範例卡")


def test_繳卡費_從帳戶扣_不會多繳(temp_db):
    card = db.add_card("範例卡", 15)
    db.set_card_bill(card, "2026-11", 3000)
    bill = db.get_card_bills()[0]["id"]
    cash = db.default_account_id()
    assert db.pay_card_bill(bill, 1000, cash, "2026-11-05") == 1000
    assert db.pay_card_bill(bill, 9999, cash, "2026-11-10") == 2000
    b = db.get_card_bills()[0]
    assert (b["paid"], b["paid_date"]) == (3000, "2026-11-10")
    assert db.get_settings()["cash_on_hand"] == 7000
    with pytest.raises(ValueError):
        db.pay_card_bill(bill, 100, cash)  # 已經繳清


def test_繳卡費_帳戶不夠時什麼都不改(temp_db):
    card = db.add_card("範例卡", 15)
    db.set_card_bill(card, "2026-11", 30000)
    with pytest.raises(ValueError):
        db.pay_card_bill(db.get_card_bills()[0]["id"], 30000, db.default_account_id())
    assert db.get_card_bills()[0]["paid"] == 0
    assert db.get_settings()["cash_on_hand"] == 10000


def test_刪除信用卡_連同帳單(temp_db):
    card = db.add_card("範例卡", 15)
    db.set_card_bill(card, "2026-11", 3000)
    db.delete_card(card)
    assert db.get_cards() == []
    assert db.get_card_bills() == []


def test_新的表也會匯出和算進有沒有資料(temp_db):
    import io, zipfile
    names = zipfile.ZipFile(io.BytesIO(db.export_csv_zip())).namelist()
    for table in ["receivables", "receivable_payments", "credit_cards", "card_bills"]:
        assert f"{table}.csv" in names
    db.save_settings({"cash_on_hand": 0})
    assert db.is_empty()
    db.add_card("範例卡", 15)
    assert not db.is_empty()


# ---------- 記帳刷卡 ----------

def test_刷卡算進下個月的帳單():
    assert bill_month("2026-10-28") == "2026-11"
    assert bill_month("2026-12-01") == "2027-01"


def test_每月現金流的卡費_扣掉記帳刷卡的部分():
    bills = [{"month": "2026-11", "amount": 5000, "paid": 0}]
    records = [{"date": "2026-10-03", "amount": 1200}, {"date": "2026-10-20", "amount": 800},
               {"date": "2026-11-02", "amount": 999}]  # 這筆算 12 月
    assert bill_from_records(records, "2026-11") == 2000
    assert card_cashflow(bills, records, "2026-11") == 3000
    assert card_cashflow([], records, "2026-11") == 0  # 帳單被改得比記帳少，不會變負的


def test_記帳選信用卡_累加到帳單_不扣帳戶(temp_db):
    card = db.add_card("範例卡", 15)
    db.add_expense(300, "吃飯", "2026-10-05", "", card_id=card)
    db.add_expense(200, "交通", "2026-10-06", "", card_id=card)
    bill = db.get_card_bills()[0]
    assert (bill["month"], bill["amount"]) == ("2026-11", 500)
    assert db.get_settings()["cash_on_hand"] == 10000
    assert [r["amount"] for r in db.get_card_records()] == [300, 200]


def test_修改刷卡的記帳_帳單跟著改(temp_db):
    card = db.add_card("範例卡", 15)
    db.add_expense(300, "吃飯", "2026-10-05", "", card_id=card)
    eid = db.get_card_records()[0]["id"]
    # 金額改成 450、日期改到 11 月：11 月帳單變回 0，12 月帳單 450
    db.update_expense(eid, 450, "吃飯", "2026-11-02", "", card_id=card)
    assert {b["month"]: b["amount"] for b in db.get_card_bills()} == {"2026-11": 0, "2026-12": 450}
    # 改成用現金付：帳單扣掉、現金扣錢
    db.update_expense(eid, 450, "吃飯", "2026-11-02", "", account_id=db.default_account_id())
    assert {b["month"]: b["amount"] for b in db.get_card_bills()} == {"2026-11": 0, "2026-12": 0}
    assert db.get_settings()["cash_on_hand"] == 9550


def test_刪除刷卡的記帳_帳單扣回來(temp_db):
    card = db.add_card("範例卡", 15)
    db.add_expense(300, "吃飯", "2026-10-05", "", card_id=card)
    db.delete_expense(db.get_card_records()[0]["id"])
    assert db.get_card_bills()[0]["amount"] == 0


def test_刪除信用卡_記帳還在(temp_db):
    card = db.add_card("範例卡", 15)
    db.add_expense(300, "吃飯", "2026-10-05", "", card_id=card)
    db.delete_card(card)
    assert db.get_card_records() == []
    assert len(db.get_records_in_month(2026, 10)) == 1
