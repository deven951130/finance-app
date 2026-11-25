"""
儲蓄目標：models/goals.py 的計算（純函式），和 db.py 的讀寫（用暫時的資料庫）。
數字都是虛構的。
"""

from datetime import date

import pytest

import db
from models.goals import (goal_done, goal_totals, item_done, monthly_needed, months_until, parse_item_lines,
                          progress_ratio, withdraw_amount)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()


# ---------- models/goals.py ----------

def test_進度比例_超過目標只算到一():
    assert progress_ratio(3000, 12000) == pytest.approx(0.25)
    assert progress_ratio(15000, 12000) == 1.0
    assert progress_ratio(500, 0) == 0.0


def test_細項和目標是否達成():
    assert item_done(12000, 12000)
    assert not item_done(11999, 12000)
    assert not item_done(0, 0)  # 目標 0 元不算達成
    assert goal_done([{"saved": 5000, "target": 5000}, {"saved": 9000, "target": 8000}])
    assert not goal_done([{"saved": 5000, "target": 5000}, {"saved": 100, "target": 8000}])
    assert not goal_done([])  # 還沒列細項


def test_目標合計_一個細項存超過不會補到別的細項():
    items = [{"saved": 15000, "target": 12000},   # 機票多存 3000
             {"saved": 2000, "target": 10000}]    # 住宿還差 8000
    t = goal_totals(items)
    assert t["target"] == 22000
    assert t["saved"] == 17000
    assert t["remaining"] == 8000
    assert t["ratio"] == pytest.approx(14000 / 22000)
    assert goal_totals([])["ratio"] == 0.0


def test_剩幾個月_這個月和截止月都算():
    today = date(2026, 11, 25)
    assert months_until(today, date(2027, 4, 10)) == 6
    assert months_until(today, date(2026, 11, 30)) == 1
    assert months_until(today, date(2026, 11, 1)) == 0  # 已經過了
    assert months_until(today, None) is None


def test_每月要存多少():
    assert monthly_needed(30000, 6) == pytest.approx(5000)
    assert monthly_needed(0, 6) == 0
    assert monthly_needed(30000, 0) is None
    assert monthly_needed(30000, None) is None


def test_一行一個細項():
    items, bad = parse_item_lines("來回機票 12,000\n\n住宿　8000元\n日本 交通 3000\n伴手禮\n怪 -5")
    assert items == [("來回機票", 12000), ("住宿", 8000), ("日本 交通", 3000)]  # 住宿那行是全形空白
    assert bad == ["伴手禮", "怪 -5"]


def test_取出不能比存的多():
    assert withdraw_amount(3000, 1000) == 1000
    assert withdraw_amount(3000, 5000) == 3000
    assert withdraw_amount(0, 500) == 0


# ---------- db.py ----------

def test_目標細項存入取出(temp_db):
    goal = db.add_goal("範例旅行", "2027-04-10", "")
    ticket = db.add_goal_item(goal, "機票", 12000)
    hotel = db.add_goal_item(goal, "住宿", 10000)
    db.deposit_goal_item(ticket, 5000, "2026-11-01")
    db.deposit_goal_item(ticket, 3000, "2026-12-01")
    assert db.deposit_goal_item(ticket, -10000) == -8000  # 只取出存的 8000

    g = db.get_goals()[0]
    assert g["name"] == "範例旅行" and g["deadline"] == "2027-04-10"
    saved = {i["name"]: i["saved"] for i in g["items"]}
    assert saved == {"機票": 0, "住宿": 0}  # 住宿沒存過也要出現
    assert len(db.get_goal_deposits(ticket)) == 3
    with pytest.raises(ValueError):
        db.deposit_goal_item(hotel, -100)  # 沒存過不能取出
    with pytest.raises(ValueError):
        db.deposit_goal_item(hotel, 0)


def test_存進目標不動帳戶(temp_db):
    db.save_settings({"cash_on_hand": 10000})
    item = db.add_goal_item(db.add_goal("範例旅行"), "機票", 12000)
    db.deposit_goal_item(item, 5000)
    assert db.get_settings()["cash_on_hand"] == 10000


def _balances() -> dict:
    return {a["name"]: a["balance"] for a in db.get_accounts()}


def test_存入時順便轉到旅費帳戶_取出時轉回(temp_db):
    cash = db.get_accounts()[0]["id"]  # 預設的「現金」帳戶
    db.set_account_balance(cash, 10000)
    trip_account = db.add_account("範例旅費", 0)
    item = db.add_goal_item(db.add_goal("範例旅行", account_id=trip_account), "機票", 12000)

    db.deposit_goal_item(item, 4000, from_account_id=cash)
    assert _balances() == {"現金": 6000, "範例旅費": 4000}
    db.deposit_goal_item(item, -1500, from_account_id=cash)  # 取出：轉回現金
    assert _balances() == {"現金": 7500, "範例旅費": 2500}
    db.deposit_goal_item(item, 500)  # 沒選來源帳戶：只記在目標名下，不轉帳
    assert _balances() == {"現金": 7500, "範例旅費": 2500}

    assert db.get_goals()[0]["items"][0]["saved"] == 3000
    assert [d["from_account_id"] for d in db.get_goal_deposits(item)] == [None, cash, cash]


def test_順便轉帳_餘額不夠或沒指定帳戶_什麼都不改(temp_db):
    cash = db.get_accounts()[0]["id"]
    db.set_account_balance(cash, 1000)
    trip_account = db.add_account("範例旅費", 0)
    item = db.add_goal_item(db.add_goal("範例旅行", account_id=trip_account), "機票", 12000)
    with pytest.raises(ValueError, match="不夠"):
        db.deposit_goal_item(item, 5000, from_account_id=cash)
    with pytest.raises(ValueError, match="同一個帳戶"):
        db.deposit_goal_item(item, 100, from_account_id=trip_account)
    no_account = db.add_goal_item(db.add_goal("範例新手機"), "手機", 8000)
    with pytest.raises(ValueError, match="指定"):
        db.deposit_goal_item(no_account, 100, from_account_id=cash)
    assert _balances() == {"現金": 1000, "範例旅費": 0}
    assert db.get_goal_deposits(item) == [] and db.get_goal_deposits(no_account) == []


def test_刪除旅費帳戶_目標變成沒指定帳戶(temp_db):
    cash = db.get_accounts()[0]["id"]
    trip_account = db.add_account("範例旅費", 0)
    db.set_account_balance(cash, 1000)
    item = db.add_goal_item(db.add_goal("範例旅行", account_id=trip_account), "機票", 12000)
    db.deposit_goal_item(item, 300, from_account_id=cash)
    db.delete_account(trip_account)
    assert db.get_goals()[0]["account_id"] is None
    assert db.get_goal_deposits(item)[0]["from_account_id"] == cash  # 現金還在，紀錄保留


def test_修改與刪除_連同細項和紀錄(temp_db):
    goal = db.add_goal("範例旅行")
    item = db.add_goal_item(goal, "機票", 12000)
    db.deposit_goal_item(item, 5000)
    db.update_goal(goal, "範例旅行 改名", "2027-01-31", "備註")
    db.update_goal_item(item, "來回機票", 15000)
    g = db.get_goals()[0]
    assert (g["name"], g["deadline"], g["note"]) == ("範例旅行 改名", "2027-01-31", "備註")
    assert (g["items"][0]["name"], g["items"][0]["target"], g["items"][0]["saved"]) == ("來回機票", 15000, 5000)

    db.delete_goal(goal)
    assert db.get_goals() == []
    assert db.get_goal_deposits(item) == []


def test_有目標就不算空的資料庫(temp_db):
    assert db.is_empty()
    db.add_goal("範例旅行")
    assert not db.is_empty()
