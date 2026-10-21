"""
畫面測試：用 Streamlit 的 AppTest 真的「跑」一次每一頁，確認沒有出錯，並操作幾個主要功能。

AppTest 像一個看不見的瀏覽器：執行 app.py、讀出畫面上的元件、幫你按按鈕和填表單。
這個 app 的頁面是函式（st.Page(page_xxx)），AppTest 的 switch_page 只認得檔案，
所以測試腳本用 runpy 執行 app.py（會畫出側邊欄和總覽），再直接呼叫要測的頁面函式。

每個測試都用暫時的資料庫，不會碰到真正的 finance.db。
"""

import os
from datetime import date

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import db
import quotes
import update_check

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_app(page: str | None = None) -> AppTest:
    """建立 AppTest。page 是頁面函式名稱（例如 'page_debts'），None 表示只跑總覽。"""
    call = f"g['{page}']()" if page else ""
    script = f"""
import os, runpy
os.chdir({APP_DIR!r})
g = runpy.run_path("app.py")
{call}
"""
    return AppTest.from_string(script, default_timeout=60)


FAKE_PRICE = 1234.0


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """畫面測試不連網路：抓股價一律回傳固定的假資料，並清掉上一個測試留下的 5 分鐘快取。"""
    def fake_fetch(symbols):
        return quotes.QuoteResult(prices={s: FAKE_PRICE for s in symbols}, quote_date=date.today(),
                                  source="realtime")
    monkeypatch.setattr(quotes, "fetch_prices", fake_fetch)
    # 版本檢查也不連網路：預設當作「不用更新」
    monkeypatch.setattr(update_check, "check", lambda: None)
    st.cache_data.clear()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """暫時的資料庫。AppTest 在同一個 process 裡跑，db.py 讀的是環境變數，所以兩個都要換。"""
    path = str(tmp_path / "finance.db")
    monkeypatch.setenv("FINANCE_DB", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    return path


@pytest.fixture
def seeded(temp_db):
    """放一些虛構資料，讓每一頁都有東西可以畫。"""
    today = date.today().isoformat()
    db.save_settings({"monthly_income": 40000, "cash_on_hand": 50000,
                      "emergency_fund": 5000, "emergency_target": 17000})
    db.save_budgets({"吃飯": 6000, "約會禮物": 2000, "交通": 1500, "其他": 1500})
    db.add_expense(120, "吃飯", today, "午餐")
    db.add_fixed_expense("電話費", 499)
    db.add_debt("範例學貸", 30000, 3000)
    db.add_holding("台積電", "2330", "A 證券", 10, 900, 1000)
    db.add_trade(today, "2330", "買進", 0, "")
    db.record_networth("2026-01-01", 10000)
    return temp_db


PAGES = ["page_expenses", "page_budgets", "page_fixed", "page_debts", "page_stocks",
         "page_precheck", "page_trades", "page_dca", "page_settings"]


def test_第一次打開_總覽顯示開始使用(temp_db):
    at = make_app().run()
    assert not at.exception
    assert any("開一本自己的存摺" in m.value for m in at.markdown)


def test_有資料時_總覽顯示淨資產(seeded):
    at = make_app().run()
    assert not at.exception
    # 打開總覽會先自動更新股價（測試用的假價格 1234）：
    # 淨資產 = 現金 50000 + 股票 10 股 × 1234 − 負債 30000 = 32340
    assert any("32,340" in m.value and "淨資產" in m.value for m in at.markdown)
    # 打開總覽會記下今天的淨資產
    assert db.get_networth_history()[-1] == {"date": date.today().isoformat(), "value": 32340}


@pytest.mark.parametrize("page", PAGES)
def test_每一頁都打得開(seeded, page):
    at = make_app(page).run()
    assert not at.exception, at.exception


@pytest.mark.parametrize("page", PAGES)
def test_空資料時每一頁也打得開(temp_db, page):
    at = make_app(page).run()
    assert not at.exception, at.exception


def test_側邊欄記一筆(seeded):
    at = make_app().run()
    form_amount = next(n for n in at.sidebar.number_input if n.label == "金額")
    form_amount.set_value(250)
    at.sidebar.radio[0].set_value("交通")
    next(b for b in at.sidebar.button if b.label == "記下來").click()
    at.run()
    assert not at.exception
    month = db.get_expenses_in_month(date.today().year, date.today().month)
    assert any(e["amount"] == 250 and e["category"] == "交通" for e in month)


def test_修改一筆記帳(seeded):
    expense_id = db.get_expenses_in_month(date.today().year, date.today().month)[0]["id"]
    at = make_app("page_expenses").run()
    # 「新增一筆」的金額預設是 0，修改視窗裡的金額是原本的 120，用這個分辨
    next(n for n in at.number_input if n.label == "金額" and n.value == 120).set_value(999)
    next(b for b in at.button if b.label == "儲存").click()
    at.run()
    assert not at.exception
    assert db.get_expenses_in_month(date.today().year, date.today().month)[0]["amount"] == 999


def test_本月已還過_不會直接再出現已還一期按鈕(seeded):
    debt_id = db.get_debts()[0]["id"]
    at = make_app("page_debts").run()
    at.button(key=f"pay_{debt_id}").click()
    at.run()
    assert not at.exception
    assert db.get_debts()[0]["remaining"] == 27000
    # 重跑後，「已還一期」按鈕換成「本月已還」＋需要再確認的「提前再還一期」
    assert not any(b.key == f"pay_{debt_id}" for b in at.button)
    assert any(b.key == f"pay_again_{debt_id}" for b in at.button)


def test_設定頁可以還原備份(seeded):
    db.auto_backup(date(2026, 1, 1))
    db.add_expense(777, "其他", date.today().isoformat(), "備份後才記")
    at = make_app("page_settings").run()
    # 打開程式時會自動備份今天的（裡面已經有「備份後才記」），所以要選 1 月 1 日那一份
    choice = next(s for s in at.selectbox if s.label == "選一份備份")
    choice.set_value(next(o for o in db.list_backups() if "2026-01-01" in o))
    next(b for b in at.button if b.label == "確定還原").click()
    at.run()
    assert not at.exception
    notes = [e["note"] for e in db.get_expenses_in_month(date.today().year, date.today().month)]
    assert "備份後才記" not in notes


def test_用的不是平常的資料庫時_每頁都提醒(seeded):
    # seeded 用的是暫時資料夾裡的資料庫，就是「不是平常那個」
    at = make_app("page_expenses").run()
    assert not at.exception
    assert any("不是平常那一個" in w.value for w in at.warning)


# ---------- 股價自動更新 ----------

def test_打開持股頁會自動更新現價(seeded):
    at = make_app("page_stocks").run()
    assert not at.exception
    assert db.get_holdings()[0]["price"] == FAKE_PRICE
    assert any("盤中即時" in c.value or "收盤價" in c.value for c in at.caption)


def test_關掉自動更新就不連網路(seeded, monkeypatch):
    db.save_settings({"auto_quotes": 0})

    def should_not_call(symbols):
        raise AssertionError("關掉後不應該抓股價")
    monkeypatch.setattr(quotes, "fetch_prices", should_not_call)
    at = make_app("page_stocks").run()
    assert not at.exception
    assert db.get_holdings()[0]["price"] == 1000  # 還是原本手動輸入的
    assert any("自動更新已關閉" in c.value for c in at.caption)


def test_抓不到股價時保留原價並提醒(seeded, monkeypatch):
    monkeypatch.setattr(quotes, "fetch_prices", lambda s: quotes.QuoteResult(error="沒有網路"))
    at = make_app("page_stocks").run()
    assert not at.exception
    assert db.get_holdings()[0]["price"] == 1000
    assert any("抓不到股價" in w.value for w in at.warning)


# ---------- 強制更新 ----------

def test_版本太舊時整個程式被擋住(seeded, monkeypatch):
    monkeypatch.setattr(update_check, "check", lambda: {"required": True, "latest": "9.0.0", "min": "9.0.0"})
    at = make_app().run()
    assert not at.exception
    assert any("需要更新" in m.value for m in at.markdown)
    # 總覽頁、側邊欄都沒有畫出來
    assert not any("淨資產" in m.value for m in at.markdown)
    assert not at.sidebar.button
    assert any(b.label == "用 Onei Hub 更新" for b in at.button)


def test_按用OneiHub更新會叫出Hub(seeded, monkeypatch):
    monkeypatch.setattr(update_check, "check", lambda: {"required": True, "latest": "9.0.0", "min": "9.0.0"})
    opened = []
    monkeypatch.setattr(update_check, "open_hub", lambda: opened.append(True) or True)
    at = make_app().run()
    next(b for b in at.button if b.label == "用 Onei Hub 更新").click()
    at.run()
    assert opened == [True]


def test_版本夠新時照常使用(seeded, monkeypatch):
    monkeypatch.setattr(update_check, "check", lambda: {"required": False, "latest": "1.1.0", "min": "1.1.0"})
    at = make_app().run()
    assert not at.exception
    assert any("淨資產" in m.value for m in at.markdown)
