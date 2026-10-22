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
    # 新增持股、第一次買進時查名稱：一律回傳假的名稱和價格
    monkeypatch.setattr(quotes, "lookup", lambda s: {"symbol": s, "name": f"測試股{s}", "price": FAKE_PRICE})
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


PAGES = ["page_expenses", "page_accounts", "page_budgets", "page_fixed", "page_debts", "page_stocks",
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
    cash_before = db.get_settings()["cash_on_hand"]
    # 「支出」分頁是第一個表單：金額、類別（主類別 · 細項）、帳戶
    next(n for n in at.sidebar.number_input if n.label == "金額").set_value(250)
    next(s for s in at.sidebar.selectbox if s.label == "類別").set_value("交通 · 捷運公車")
    next(b for b in at.sidebar.button if b.label == "記下來").click()
    at.run()
    assert not at.exception
    month = db.get_expenses_in_month(date.today().year, date.today().month)
    assert any(e["amount"] == 250 and (e["category"], e["subcategory"]) == ("交通", "捷運公車") for e in month)
    assert db.get_settings()["cash_on_hand"] == cash_before - 250  # 從現金帳戶扣掉了


def test_記帳頁記一筆收入_帳戶增加(seeded):
    at = make_app("page_expenses").run()
    cash_before = db.get_settings()["cash_on_hand"]
    # 主畫面的第二個表單是「收入」分頁（第一個是支出）；側邊欄的不算
    incomes = [n for n in at.main.number_input if n.label == "金額"]
    incomes[1].set_value(30000)
    next(s for s in at.main.selectbox if s.label == "類別" and "薪資 · 月薪" in s.options).set_value("薪資 · 月薪")
    [b for b in at.main.button if b.label == "記下來"][1].click()
    at.run()
    assert not at.exception
    records = db.get_records_in_month(date.today().year, date.today().month)
    assert any(r["kind"] == "income" and r["amount"] == 30000 for r in records)
    assert db.get_settings()["cash_on_hand"] == cash_before + 30000


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


def test_不限期負債還一筆_負債和帳戶都扣(seeded):
    db.add_debt("跟朋友借", 8000, 0, kind="open")
    debt = next(d for d in db.get_debts() if d["kind"] == "open")
    cash_before = db.get_settings()["cash_on_hand"]
    at = make_app("page_debts").run()
    assert not at.exception
    next(n for n in at.number_input if n.label == "這次還多少").set_value(1500)
    next(b for b in at.button if b.label == "還款").click()
    at.run()
    assert not at.exception
    assert next(d for d in db.get_debts() if d["id"] == debt["id"])["remaining"] == 6500
    assert db.get_settings()["cash_on_hand"] == cash_before - 1500


def test_帳戶頁開戶與轉帳(seeded):
    at = make_app("page_accounts").run()
    assert not at.exception
    next(t for t in at.text_input if t.label.startswith("名稱（例如 台新")).set_value("台新")
    next(n for n in at.number_input if n.label == "現在的餘額").set_value(20000)
    next(b for b in at.button if b.label == "開戶").click()
    at.run()
    assert not at.exception
    assert [a["name"] for a in db.get_accounts()] == ["現金", "台新"]
    # 開了第二個帳戶才有轉帳表單：預設從現金轉到台新
    at = make_app("page_accounts").run()
    next(n for n in at.number_input if n.label == "金額").set_value(5000)
    next(b for b in at.button if b.label == "轉帳").click()
    at.run()
    assert not at.exception
    balances = {a["name"]: a["balance"] for a in db.get_accounts()}
    assert balances["台新"] == 25000


# ---------- 持股只填代號、買賣連動帳戶 ----------

def test_新增持股只填代號券商股數_名稱現價自動查(seeded):
    at = make_app("page_stocks").run()
    next(t for t in at.text_input if t.label.startswith("代號")).set_value("1111")
    next(s for s in at.selectbox if s.label == "券商").set_value("＋ 新的券商")
    next(t for t in at.text_input if t.label.startswith("新的券商名稱")).set_value("B 證券")
    next(n for n in at.number_input if n.label == "股數").set_value(100)
    next(b for b in at.button if b.label == "新增").click()
    at.run()
    assert not at.exception
    h = next(h for h in db.get_holdings() if h["symbol"] == "1111")
    assert (h["name"], h["account"], h["shares"], h["avg_price"], h["price"]) == ("測試股1111", "B 證券", 100, 0, FAKE_PRICE)
    assert "B 證券" in [b["name"] for b in db.get_brokers()]
    # 沒填均價的那檔損益顯示「—」，頁面照常
    at = make_app("page_stocks").run()
    assert not at.exception


def test_新增持股查不到報價時要自己填(seeded, monkeypatch):
    monkeypatch.setattr(quotes, "lookup", lambda s: None)
    at = make_app("page_stocks").run()
    next(t for t in at.text_input if t.label.startswith("代號")).set_value("ABCD")
    next(n for n in at.number_input if n.label == "股數").set_value(10)
    next(b for b in at.button if b.label == "新增").click()
    at.run()
    assert not at.exception
    assert any("查不到 ABCD" in w.value for w in at.warning)
    assert not any(h["symbol"] == "ABCD" for h in db.get_holdings())


def test_交易頁買進_帳戶扣錢持股增加(seeded):
    cash_before = db.get_settings()["cash_on_hand"]
    at = make_app("page_trades").run()
    next(t for t in at.text_input if t.label.startswith("代號")).set_value("2330")
    next(n for n in at.number_input if n.label == "股數").set_value(10)
    next(n for n in at.number_input if n.label == "成交價").set_value(1000)
    at.run()
    # 送出前先看到預覽：10 股 × 1000 = 10000，手續費 14.25 → 最低 20
    assert any("10,020 元" in m.value for m in at.markdown)
    next(b for b in at.button if b.label == "確認買進").click()
    at.run()
    assert not at.exception
    assert db.get_settings()["cash_on_hand"] == cash_before - 10020
    assert db.get_holdings()[0]["shares"] == 20  # seeded 原本就有 10 股（A 證券）
    assert db.get_trades()[0]["fee"] == 20


def test_交易頁賣出_帳戶加錢記損益(seeded):
    cash_before = db.get_settings()["cash_on_hand"]
    at = make_app("page_trades").run()
    at.radio(key="tr_side").set_value("賣出")
    at.run()
    next(n for n in at.number_input if n.label == "股數").set_value(10)
    next(n for n in at.number_input if n.label == "成交價").set_value(1000)
    at.run()
    next(b for b in at.button if b.label == "確認賣出").click()
    at.run()
    assert not at.exception
    # 10000 − 手續費 20 − 稅 30 = 9950；成本 10 股 × 900 = 9000 → 賺 950
    assert db.get_settings()["cash_on_hand"] == cash_before + 9950
    assert db.get_holdings() == []
    assert db.get_trades()[0]["pnl"] == 950
