"""
測試第三階段：下單前檢查、當沖次數、定期定額試算、CSV 匯出。
"""

import csv
import io
import zipfile

import pytest

import db
from models.dca import monthly_rate, monthly_withdrawal, project
from models.precheck import CHECK_ITEMS, check_order
from models.trades import count_day_trades

ALL_CHECKED = {item: True for item in CHECK_ITEMS}


# ---------- 下單前檢查 ----------

def test_全部打勾且現金足夠_可以下單():
    ok, reasons = check_order(50000, 60000, ALL_CHECKED)
    assert ok
    assert reasons == []


def test_金額剛好等於現金_可以下單():
    ok, _ = check_order(60000, 60000, ALL_CHECKED)
    assert ok


def test_少勾一項_不能下單並說明是哪一項():
    checked = dict(ALL_CHECKED)
    checked["這個想法已經等了 7 天"] = False
    ok, reasons = check_order(1000, 60000, checked)
    assert not ok
    assert reasons == ["還沒打勾：這個想法已經等了 7 天"]


def test_現金不夠_不能下單():
    ok, reasons = check_order(70000, 60000, ALL_CHECKED)
    assert not ok
    assert len(reasons) == 1
    assert "超過手上現金" in reasons[0]


def test_同時有多個原因時全部列出():
    ok, reasons = check_order(70000, 60000, {})   # 一個都沒勾
    assert not ok
    assert len(reasons) == len(CHECK_ITEMS) + 1


def test_金額為零_不能下單():
    ok, reasons = check_order(0, 60000, ALL_CHECKED)
    assert not ok
    assert reasons == ["請輸入這筆要花的金額"]


# ---------- 本月當沖次數 ----------

def test_只算本月的當沖():
    trades = [
        {"date": "2026-10-01", "type": "當沖"},
        {"date": "2026-10-20", "type": "當沖"},
        {"date": "2026-10-05", "type": "買進"},
        {"date": "2026-09-30", "type": "當沖"},   # 上個月，不算
    ]
    assert count_day_trades(trades, 2026, 10) == 2
    assert count_day_trades([], 2026, 10) == 0


# ---------- 定期定額 ----------

def test_每月報酬率滾一年等於年報酬率():
    assert (1 + monthly_rate(0.06)) ** 12 == pytest.approx(1.06)


def test_報酬率為零_就是本金相加():
    values = project(100000, 5000, 0, 3)
    assert values == pytest.approx([100000, 160000, 220000, 280000])


def test_只有現有投資_每年乘上年報酬率():
    values = project(100000, 0, 0.10, 2)
    assert values == pytest.approx([100000, 110000, 121000])


def test_有報酬時總額大於本金():
    values = project(0, 5000, 0.06, 10)
    assert len(values) == 11
    assert values[-1] > 5000 * 12 * 10


def test_4趴法則每月可領():
    assert monthly_withdrawal(3_000_000) == pytest.approx(10000)


# ---------- CSV 匯出 ----------

def test_匯出的zip包含每張資料表(tmp_path, monkeypatch):
    # monkeypatch：測試期間暫時把資料庫換成暫存資料夾裡的檔案，不碰真實資料
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    db.add_expense(120, "吃飯", "2026-10-01", "午餐")

    with zipfile.ZipFile(io.BytesIO(db.export_csv_zip())) as zf:
        assert sorted(zf.namelist()) == sorted(f"{t}.csv" for t in db.EXPORT_TABLES)
        text = zf.read("expenses.csv").decode("utf-8-sig")

    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["id", "amount", "category", "date", "note"]
    assert rows[1][1:] == ["120.0", "吃飯", "2026-10-01", "午餐"]
