"""
資料庫存取（SQLite）。

所有「讀寫資料庫」的程式都集中在這個檔案，app.py 只呼叫這裡的函式，
不直接寫 SQL。這樣以後要改資料表時，只需要改這一個地方。

資料庫檔案放在哪裡：
- 用 python / streamlit 執行時：專案裡的 data/finance.db（已被 .gitignore 排除）
- 打包成 exe 執行時：使用者家目錄的 FinanceApp/finance.db
  （例如 C:\\Users\\你的名字\\FinanceApp\\finance.db）
"""

import csv
import io
import os
import sqlite3
import sys
import zipfile
from datetime import date, datetime

from models.budget import CATEGORIES
from models.debt import payment_this_period
from models.fees import DEFAULT_MIN_FEE, avg_after_buy, realized_pnl, trade_summary



def default_db_path() -> str:
    """決定資料庫的預設位置。"""
    # PyInstaller 打包的 exe 執行時，sys.frozen 會是 True。
    # exe 的程式檔每次啟動會解壓到暫存資料夾，關掉就刪除，資料不能放在那裡，
    # 所以改放到使用者的家目錄，更新或重新安裝 exe 也不會遺失資料。
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.expanduser("~"), "FinanceApp", "finance.db")

    # 一般執行：放在 db.py 所在資料夾底下的 data/。
    # 用 __file__ 算出絕對路徑，不管從哪個資料夾啟動，都會找到同一個檔案。
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "data", "finance.db")


# 資料庫檔案位置。可以用環境變數 FINANCE_DB 改成別的路徑（例如測試或範例資料）。
DB_PATH = os.environ.get("FINANCE_DB", default_db_path())

# 第一個帳戶的名字：舊版的「手上現金」會變成這個帳戶
DEFAULT_ACCOUNT = "現金"

# 設定頁的預設值：預備金目標預設 17000，其他預設 0
DEFAULT_SETTINGS = {
    "monthly_income": 0.0,     # 每月收入
    "cash_on_hand": 0.0,       # 手上現金
    "emergency_fund": 0.0,     # 緊急預備金（目前存了多少）
    "emergency_target": 17000.0,  # 預備金目標
    # 股價自動更新（見 quotes.py）。1 = 開、0 = 關
    "auto_quotes": 1.0,
    # 上一次成功抓到股價的資訊（給畫面顯示「股價：10/21 11:46 盤中」）
    "quotes_fetched_at": 0.0,  # 抓的時間（Unix 時間戳記，秒）
    "quotes_date": 0.0,        # 行情是哪一天的，寫成 20261021 這種數字
    "quotes_realtime": 0.0,    # 1 = 即時行情（MIS），0 = 官方每日收盤價
}


def get_connection() -> sqlite3.Connection:
    """開啟資料庫連線。資料夾不存在時會自動建立。"""
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    # 讓查詢結果可以用欄位名稱取值，例如 row["amount"]
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """建立資料表（已經存在就略過），並放入預設值。程式啟動時呼叫一次。"""
    with get_connection() as conn:
        # 設定：一個名稱對應一個數字
        conn.execute(
            "CREATE TABLE IF NOT EXISTS settings ("
            " key TEXT PRIMARY KEY,"
            " value REAL NOT NULL)"
        )
        # 每月生活預算：一個類別一個金額
        conn.execute(
            "CREATE TABLE IF NOT EXISTS budgets ("
            " category TEXT PRIMARY KEY,"
            " amount REAL NOT NULL)"
        )
        # 記帳：每筆支出
        conn.execute(
            "CREATE TABLE IF NOT EXISTS expenses ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " amount REAL NOT NULL,"
            " category TEXT NOT NULL,"
            " date TEXT NOT NULL,"   # 存成 'YYYY-MM-DD' 字串
            " note TEXT)"
        )
        # 固定支出：例如電話費、iCloud
        conn.execute(
            "CREATE TABLE IF NOT EXISTS fixed_expenses ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name TEXT NOT NULL,"
            " amount REAL NOT NULL)"
        )

        # 負債：剩餘金額、每月還款
        conn.execute(
            "CREATE TABLE IF NOT EXISTS debts ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name TEXT NOT NULL,"
            " remaining REAL NOT NULL,"
            " monthly_payment REAL NOT NULL)"
        )
        # 持股：同一代號可以在不同帳戶各有一列，計算時再合併
        conn.execute(
            "CREATE TABLE IF NOT EXISTS holdings ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name TEXT NOT NULL,"
            " symbol TEXT NOT NULL,"
            " account TEXT NOT NULL,"
            " shares REAL NOT NULL,"
            " avg_price REAL NOT NULL,"
            " price REAL NOT NULL)"   # 現價，手動輸入
        )

        # 交易紀錄：日期、標的、類型（買進／賣出／當沖）、損益、備註
        conn.execute(
            "CREATE TABLE IF NOT EXISTS trades ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " date TEXT NOT NULL,"
            " symbol TEXT NOT NULL,"
            " type TEXT NOT NULL,"
            " pnl REAL NOT NULL DEFAULT 0,"
            " note TEXT)"
        )

        # 還款紀錄：每按一次「已還一期」記一筆，才知道這個月是不是已經還過了。
        # 舊資料庫沒有這張表，CREATE TABLE IF NOT EXISTS 會自動補上，不用另外寫升級程式
        conn.execute(
            "CREATE TABLE IF NOT EXISTS debt_payments ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " debt_id INTEGER NOT NULL,"
            " date TEXT NOT NULL,"
            " amount REAL NOT NULL)"
        )

        # 淨資產紀錄：每天一筆（打開總覽時記下當天的淨資產），用來畫「淨資產變化」折線圖
        conn.execute(
            "CREATE TABLE IF NOT EXISTS networth_history ("
            " date TEXT PRIMARY KEY,"
            " value REAL NOT NULL)"
        )

        # 銀行帳戶：每個帳戶一個餘額（2026-10-22 使用者要求「區分銀行帳戶、各自紀錄」）。
        # 「手上現金」改成所有帳戶餘額的合計（見 get_settings）
        conn.execute(
            "CREATE TABLE IF NOT EXISTS accounts ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name TEXT NOT NULL,"
            " balance REAL NOT NULL DEFAULT 0)"
        )

        # 券商：每家的手續費折扣不同（例如 2.8 折 = 0.28），最低手續費一般 20 元。
        # 持股的 account 欄位就是券商名稱，所以用 name 對應，不另外存 id
        conn.execute(
            "CREATE TABLE IF NOT EXISTS brokers ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name TEXT NOT NULL UNIQUE,"
            " discount REAL NOT NULL DEFAULT 1.0,"
            f" min_fee REAL NOT NULL DEFAULT {DEFAULT_MIN_FEE})"
        )

        # 舊資料庫升級：CREATE TABLE IF NOT EXISTS 不會幫已經存在的表加欄位，要自己用 ALTER TABLE 補
        # 記帳：kind 是支出 expense 或收入 income；subcategory 是細項；account_id 是從哪個帳戶進出
        #   舊的記帳沒有帳戶（NULL），不影響任何帳戶的餘額
        add_column(conn, "expenses", "kind", "TEXT NOT NULL DEFAULT 'expense'")
        add_column(conn, "expenses", "subcategory", "TEXT")
        add_column(conn, "expenses", "account_id", "INTEGER")
        # 負債：kind 是定期還 installment（每月固定還款）或不限期 open（沒有固定還款，有錢就還）
        add_column(conn, "debts", "kind", "TEXT NOT NULL DEFAULT 'installment'")
        # 還款紀錄：從哪個帳戶還的
        add_column(conn, "debt_payments", "account_id", "INTEGER")
        # 交易紀錄：用「買進／賣出」表單記的交易，會多記這些明細（手動記的舊紀錄都是 NULL）
        #   side 是 buy / sell；amount 成交金額；fee 手續費；tax 交易稅；broker 券商；account_id 扣款／入帳的帳戶
        for column, decl in [("side", "TEXT"), ("shares", "REAL"), ("price", "REAL"), ("amount", "REAL"),
                             ("fee", "REAL"), ("tax", "REAL"), ("broker", "TEXT"), ("account_id", "INTEGER")]:
            add_column(conn, "trades", column, decl)

        # 舊資料的持股已經寫了券商（account 欄），幫每家券商建一列，手續費先用不打折
        conn.execute("INSERT OR IGNORE INTO brokers (name) SELECT DISTINCT account FROM holdings")

        # INSERT OR IGNORE：如果這個 key 已經有值就不覆蓋，只補上缺少的
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        for category in CATEGORIES:
            conn.execute(
                "INSERT OR IGNORE INTO budgets (category, amount) VALUES (?, 0)",
                (category,),
            )

        # 第一次有帳戶功能時：把原本的「手上現金」變成一個叫「現金」的帳戶，金額不變
        if not conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone():
            cash = conn.execute("SELECT value FROM settings WHERE key = 'cash_on_hand'").fetchone()
            conn.execute("INSERT INTO accounts (name, balance) VALUES (?, ?)",
                         (DEFAULT_ACCOUNT, cash["value"] if cash else 0.0))


def add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """表裡沒有這個欄位才加（舊資料庫升級用）。PRAGMA table_info 會列出表的所有欄位。"""
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


# ---------- 設定 ----------

def get_settings() -> dict[str, float]:
    """讀取所有設定，回傳 {名稱: 數值}。

    cash_on_hand（手上現金）不再是自己存的數字，而是所有帳戶餘額的合計，
    這樣總覽、下單前檢查這些用到「手上現金」的地方都不用改。
    """
    with get_connection() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        total = conn.execute("SELECT COALESCE(SUM(balance), 0) AS t FROM accounts").fetchone()["t"]
    settings = {row["key"]: row["value"] for row in rows}
    settings["cash_on_hand"] = total
    return settings


def save_settings(settings: dict[str, float]) -> None:
    """儲存設定（有就更新，沒有就新增）。

    給了 cash_on_hand 時，調整第一個帳戶（現金）的餘額，讓所有帳戶合計等於這個數字
    （範例資料、測試和舊的寫法還是可以直接設定「手上現金」）。
    """
    settings = dict(settings)
    cash = settings.pop("cash_on_hand", None)
    with get_connection() as conn:
        for key, value in settings.items():
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        if cash is not None:
            first = _default_account_id(conn)
            others = conn.execute(
                "SELECT COALESCE(SUM(balance), 0) AS t FROM accounts WHERE id != ?", (first,)
            ).fetchone()["t"]
            conn.execute("UPDATE accounts SET balance = ? WHERE id = ?", (cash - others, first))


# ---------- 銀行帳戶 ----------

def _default_account_id(conn: sqlite3.Connection) -> int:
    """第一個帳戶（通常是「現金」）的 id；一個帳戶都沒有時先建一個。"""
    row = conn.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO accounts (name, balance) VALUES (?, 0)", (DEFAULT_ACCOUNT,)).lastrowid


def default_account_id() -> int:
    with get_connection() as conn:
        return _default_account_id(conn)


def get_accounts() -> list[dict]:
    """所有帳戶，照建立順序（第一個是「現金」）。"""
    with get_connection() as conn:
        rows = conn.execute("SELECT id, name, balance FROM accounts ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def add_account(name: str, balance: float) -> int:
    """開一個新帳戶（例如「台新銀行」），balance 是現在的餘額。回傳新帳戶的 id。"""
    with get_connection() as conn:
        return conn.execute("INSERT INTO accounts (name, balance) VALUES (?, ?)", (name, balance)).lastrowid


def rename_account(account_id: int, name: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE accounts SET name = ? WHERE id = ?", (name, account_id))


def set_account_balance(account_id: int, balance: float) -> None:
    """直接把餘額改成某個數字（對帳用：和銀行 App 上的數字不一樣時校正）。"""
    with get_connection() as conn:
        conn.execute("UPDATE accounts SET balance = ? WHERE id = ?", (balance, account_id))


def transfer(from_id: int, to_id: int, amount: float) -> None:
    """轉帳：一個帳戶扣、另一個帳戶加，在同一個交易裡（不會只扣一邊）。"""
    if from_id == to_id:
        raise ValueError("轉出和轉入是同一個帳戶")
    if amount <= 0:
        raise ValueError("金額要大於 0")
    with get_connection() as conn:
        conn.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (amount, from_id))
        conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, to_id))


def delete_account(account_id: int) -> None:
    """刪除帳戶。記帳、還款紀錄還在，只是不再屬於這個帳戶。至少要留一個帳戶。"""
    with get_connection() as conn:
        if conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"] <= 1:
            raise ValueError("至少要留一個帳戶")
        conn.execute("UPDATE expenses SET account_id = NULL WHERE account_id = ?", (account_id,))
        conn.execute("UPDATE debt_payments SET account_id = NULL WHERE account_id = ?", (account_id,))
        conn.execute("UPDATE trades SET account_id = NULL WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


def _apply(conn: sqlite3.Connection, account_id: int | None, kind: str, amount: float, sign: int = 1) -> None:
    """記帳對帳戶餘額的影響：支出扣、收入加。sign = -1 是把這個影響還原（修改、刪除時用）。"""
    if account_id is None:
        return
    delta = amount if kind == "income" else -amount
    conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (sign * delta, account_id))


# ---------- 每月生活預算 ----------

def get_budgets() -> dict[str, float]:
    """讀取各類別預算，回傳 {類別: 金額}。"""
    with get_connection() as conn:
        rows = conn.execute("SELECT category, amount FROM budgets").fetchall()
    return {row["category"]: row["amount"] for row in rows}


def save_budgets(budgets: dict[str, float]) -> None:
    """儲存各類別預算。"""
    with get_connection() as conn:
        for category, amount in budgets.items():
            conn.execute(
                "INSERT OR REPLACE INTO budgets (category, amount) VALUES (?, ?)",
                (category, amount),
            )


# ---------- 記帳 ----------

RECORD_COLUMNS = "id, kind, amount, category, subcategory, date, note, account_id"


def add_expense(amount: float, category: str, date_str: str, note: str,
                subcategory: str | None = None, account_id: int | None = None, kind: str = "expense") -> None:
    """新增一筆記帳。kind 是 "expense"（支出）或 "income"（收入），date_str 格式為 'YYYY-MM-DD'。

    有選帳戶時，在同一個交易裡更新那個帳戶的餘額（支出扣、收入加）。
    """
    with get_connection() as conn:
        # 用 ? 當佔位符號，不要自己拼字串，可以避免 SQL injection
        conn.execute(
            "INSERT INTO expenses (kind, amount, category, subcategory, date, note, account_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, amount, category, subcategory, date_str, note, account_id),
        )
        _apply(conn, account_id, kind, amount)


def get_records_in_month(year: int, month: int) -> list[dict]:
    """某年某月的所有記帳（支出和收入都有），新的在前面。"""
    # 日期存成 'YYYY-MM-DD'，所以用開頭 'YYYY-MM' 比對就能篩出整個月
    prefix = f"{year:04d}-{month:02d}-%"
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT {RECORD_COLUMNS} FROM expenses WHERE date LIKE ? ORDER BY date DESC, id DESC",
            (prefix,),
        ).fetchall()
    # 把 sqlite3.Row 轉成一般的 dict，給 models 和畫面使用
    return [dict(row) for row in rows]


def get_expenses_in_month(year: int, month: int) -> list[dict]:
    """某年某月的支出（不含收入），新的在前面。預算、「還能花多少」都只看支出。"""
    return [r for r in get_records_in_month(year, month) if r["kind"] == "expense"]


def get_expenses_since(date_str: str) -> list[dict]:
    """某一天（含）以後的所有支出（不含收入），給「近幾個月趨勢」用。"""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT {RECORD_COLUMNS} FROM expenses WHERE date >= ? AND kind = 'expense'"
            " ORDER BY date, id",
            (date_str,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_expense_months() -> list[str]:
    """有記帳的月份（'YYYY-MM'），新的在前面。給記帳頁的月份選單用。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT substr(date, 1, 7) AS ym FROM expenses ORDER BY ym DESC"
        ).fetchall()
    return [row["ym"] for row in rows]


def update_expense(expense_id: int, amount: float, category: str, date_str: str, note: str,
                   subcategory: str | None = None, account_id: int | None = None, kind: str | None = None) -> None:
    """修改一筆記帳（記錯金額、類別、日期、帳戶時用，不用刪掉重記）。

    帳戶餘額：先把舊的那筆對帳戶的影響還原，再套用新的（換了帳戶也對得上）。
    kind 沒給就維持原本的支出／收入。
    """
    with get_connection() as conn:
        old = conn.execute("SELECT kind, amount, account_id FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        kind = kind or old["kind"]
        _apply(conn, old["account_id"], old["kind"], old["amount"], sign=-1)
        conn.execute(
            "UPDATE expenses SET kind = ?, amount = ?, category = ?, subcategory = ?, date = ?, note = ?,"
            " account_id = ? WHERE id = ?",
            (kind, amount, category, subcategory, date_str, note, account_id, expense_id),
        )
        _apply(conn, account_id, kind, amount)


def delete_expense(expense_id: int) -> None:
    """刪除一筆記帳（記錯時用），並把它對帳戶餘額的影響還原。"""
    with get_connection() as conn:
        old = conn.execute("SELECT kind, amount, account_id FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        if old:
            _apply(conn, old["account_id"], old["kind"], old["amount"], sign=-1)
        conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))


# ---------- 固定支出 ----------

def get_fixed_expenses() -> list[dict]:
    """讀取所有固定支出。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, amount FROM fixed_expenses ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def add_fixed_expense(name: str, amount: float) -> None:
    """新增一項固定支出。"""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO fixed_expenses (name, amount) VALUES (?, ?)",
            (name, amount),
        )


def delete_fixed_expense(fixed_id: int) -> None:
    """刪除一項固定支出。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM fixed_expenses WHERE id = ?", (fixed_id,))


# ---------- 負債 ----------

def get_debts() -> list[dict]:
    """讀取所有負債。kind 是 "installment"（定期還）或 "open"（不限期）。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, remaining, monthly_payment, kind FROM debts ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def add_debt(name: str, remaining: float, monthly_payment: float, kind: str = "installment") -> None:
    """新增一筆負債。不限期（open）的負債沒有每月還款，monthly_payment 存 0。"""
    if kind == "open":
        monthly_payment = 0.0
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO debts (name, remaining, monthly_payment, kind) VALUES (?, ?, ?, ?)",
            (name, remaining, monthly_payment, kind),
        )


def delete_debt(debt_id: int) -> None:
    """刪除一筆負債（連同它的還款紀錄）。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM debts WHERE id = ?", (debt_id,))
        conn.execute("DELETE FROM debt_payments WHERE debt_id = ?", (debt_id,))


def get_debt_payments(debt_id: int) -> list[dict]:
    """某筆負債的還款紀錄，新的在前面。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, date, amount, account_id FROM debt_payments WHERE debt_id = ?"
            " ORDER BY date DESC, id DESC",
            (debt_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def pay_debt(debt_id: int, amount: float, account_id: int | None = None, date_str: str | None = None) -> float:
    """還一筆錢：負債剩餘金額和帳戶餘額同時扣掉，並記一筆還款紀錄，回傳實際還了多少。

    三件事放在同一個 with 區塊裡，這叫「交易（transaction）」：
    要嘛全部成功，要嘛中途出錯全部不改，不會只扣了一邊。
    - 還的錢比剩下的多時，只還剩下的（不會還成負數）
    - 帳戶餘額不夠時丟出 ValueError，什麼都不改
    account_id 沒給就用第一個帳戶（現金）；date_str 沒給就是今天。
    """
    date_str = date_str or date.today().isoformat()
    with get_connection() as conn:
        if account_id is None:
            account_id = _default_account_id(conn)
        debt = conn.execute("SELECT remaining FROM debts WHERE id = ?", (debt_id,)).fetchone()
        account = conn.execute("SELECT name, balance FROM accounts WHERE id = ?", (account_id,)).fetchone()
        pay = min(amount, debt["remaining"])
        if pay <= 0:
            raise ValueError("這筆負債已經還清了" if debt["remaining"] <= 0 else "金額要大於 0")
        if pay > account["balance"]:
            raise ValueError(f"「{account['name']}」餘額 {account['balance']:,.0f} 不夠還 {pay:,.0f}")

        conn.execute("UPDATE debts SET remaining = remaining - ? WHERE id = ?", (pay, debt_id))
        conn.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (pay, account_id))
        conn.execute(
            "INSERT INTO debt_payments (debt_id, date, amount, account_id) VALUES (?, ?, ?, ?)",
            (debt_id, date_str, pay, account_id),
        )
    return pay


def pay_debt_installment(debt_id: int, date_str: str | None = None, account_id: int | None = None) -> float:
    """「已還一期」（定期還的負債）：還這一期的金額（最後一期只還剩下的）。"""
    with get_connection() as conn:
        debt = conn.execute("SELECT remaining, monthly_payment FROM debts WHERE id = ?", (debt_id,)).fetchone()
    pay = payment_this_period(debt["remaining"], debt["monthly_payment"])
    if pay <= 0:
        raise ValueError("這筆負債已經還清了")
    return pay_debt(debt_id, pay, account_id, date_str)


# ---------- 持股 ----------

def get_holdings() -> list[dict]:
    """讀取所有持股（每個帳戶一列，還沒合併）。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, symbol, account, shares, avg_price, price"
            " FROM holdings ORDER BY symbol, account"
        ).fetchall()
    return [dict(row) for row in rows]


def add_holding(name: str, symbol: str, account: str, shares: float,
                avg_price: float, price: float) -> None:
    """新增一筆持股。同代號的其他帳戶現價也一起更新，確保合併計算時一致。

    account 是券商名稱；avg_price 可以是 0，代表不知道均價（損益就不算）。
    """
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO holdings (name, symbol, account, shares, avg_price, price)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (name, symbol, account, shares, avg_price, price),
        )
        conn.execute("UPDATE holdings SET price = ? WHERE symbol = ?", (price, symbol))
        # 第一次出現的券商自動建一列（手續費先用不打折，到持股頁的「券商手續費」改）
        conn.execute("INSERT OR IGNORE INTO brokers (name) VALUES (?)", (account,))


def update_prices(prices: dict[str, float]) -> int:
    """自動抓到的股價寫回持股（所有帳戶一起改），回傳更新了幾列。

    prices 的代號已經整理過（去空白、大寫），持股裡的代號也用同樣方式整理後比對，
    所以使用者輸入「2330 」或「00631l」也對得上。
    """
    from models.quotes import normalize_symbol  # 只有這裡用到，放在函式裡避免 db 一載入就依賴股價模組

    updated = 0
    with get_connection() as conn:
        rows = conn.execute("SELECT id, symbol FROM holdings").fetchall()
        for row in rows:
            price = prices.get(normalize_symbol(row["symbol"]))
            if price is not None:
                conn.execute("UPDATE holdings SET price = ? WHERE id = ?", (price, row["id"]))
                updated += 1
    return updated


def update_price(symbol: str, price: float) -> None:
    """更新某個代號的現價（所有帳戶一起改）。"""
    with get_connection() as conn:
        conn.execute("UPDATE holdings SET price = ? WHERE symbol = ?", (price, symbol))


def delete_holding(holding_id: int) -> None:
    """刪除一筆持股。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))


# ---------- 券商 ----------

def get_brokers() -> list[dict]:
    """所有券商和它的手續費折扣、最低手續費，照建立順序。"""
    with get_connection() as conn:
        rows = conn.execute("SELECT id, name, discount, min_fee FROM brokers ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def save_broker(name: str, discount: float, min_fee: float) -> None:
    """新增或修改一家券商的手續費（name 一樣就是修改）。"""
    if not 0 < discount <= 1:
        raise ValueError("折扣要在 0 到 1 之間（例如 2.8 折填 0.28）")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO brokers (name, discount, min_fee) VALUES (?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET discount = excluded.discount, min_fee = excluded.min_fee",
            (name, discount, min_fee),
        )


def _broker_fee_rule(conn: sqlite3.Connection, broker: str) -> tuple[float, float]:
    """某家券商的 (折扣, 最低手續費)；還沒有這家就先建一列（不打折、最低 20 元）。"""
    conn.execute("INSERT OR IGNORE INTO brokers (name) VALUES (?)", (broker,))
    row = conn.execute("SELECT discount, min_fee FROM brokers WHERE name = ?", (broker,)).fetchone()
    return row["discount"], row["min_fee"]


def trade_preview(side: str, symbol: str, broker: str, shares: float, price: float,
                  day_trade: bool = False) -> dict:
    """還沒送出前，先算這筆交易的手續費、稅和帳戶增減（交易頁的即時預覽用，不改資料庫）。"""
    with get_connection() as conn:
        row = conn.execute("SELECT discount, min_fee FROM brokers WHERE name = ?", (broker,)).fetchone()
    discount, min_fee = (row["discount"], row["min_fee"]) if row else (1.0, DEFAULT_MIN_FEE)
    return trade_summary(side, symbol, shares, price, discount, min_fee, day_trade)


# ---------- 交易紀錄 ----------

TRADE_COLUMNS = "id, date, symbol, type, pnl, note, side, shares, price, amount, fee, tax, broker, account_id"


def get_trades() -> list[dict]:
    """讀取所有交易紀錄，新的在前面。手動記的舊紀錄 side、shares 這些明細是 None。"""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT {TRADE_COLUMNS} FROM trades ORDER BY date DESC, id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def add_trade(date_str: str, symbol: str, trade_type: str, pnl: float, note: str) -> None:
    """手動記一筆交易紀錄（只記下來，不會動到持股和帳戶）。"""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO trades (date, symbol, type, pnl, note) VALUES (?, ?, ?, ?, ?)",
            (date_str, symbol, trade_type, pnl, note),
        )


def execute_trade(side: str, symbol: str, broker: str, shares: float, price: float, account_id: int,
                  date_str: str | None = None, day_trade: bool = False, name: str | None = None,
                  note: str = "") -> dict:
    """真的買進（side="buy"）或賣出（side="sell"）一筆股票：帳戶、持股、交易紀錄三個一起改。

    和 pay_debt() 一樣放在同一個 with 區塊（同一個交易）裡，中途出錯就全部不改。
    - 手續費照這家券商的折扣和最低手續費算（見 models/fees.py）
    - 買進：帳戶扣「成交金額 + 手續費」；這家券商已經有這檔就加股數、重算均價（含手續費），
      沒有就新增一列（名稱用 name，沒給就先用代號）。帳戶餘額不夠時丟 ValueError
    - 賣出：這家券商的股數不夠時丟 ValueError；帳戶加「成交金額 − 手續費 − 稅」，
      持股扣股數（賣光就刪掉那一列），實現損益記在交易紀錄的 pnl
    - 均價不知道（0）時：買進後均價還是不知道；賣出的損益記 0，備註寫「沒有均價，損益沒算」
    回傳 trade_summary 的明細，再加上 pnl（實現損益，買進或算不出來是 None）。
    """
    from models.quotes import normalize_symbol

    if side not in ("buy", "sell"):
        raise ValueError("side 要是 buy 或 sell")
    if shares <= 0 or price <= 0:
        raise ValueError("股數和成交價都要大於 0")
    symbol = normalize_symbol(symbol)
    date_str = date_str or date.today().isoformat()
    with get_connection() as conn:
        discount, min_fee = _broker_fee_rule(conn, broker)
        summary = trade_summary(side, symbol, shares, price, discount, min_fee, day_trade)
        account = conn.execute("SELECT name, balance FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if account is None:
            raise ValueError("找不到這個帳戶")
        # 同一家券商、同一個代號的那一列（代號用整理過的比對，舊資料的「2330 」也找得到）
        holding = next((dict(h) for h in conn.execute(
            "SELECT id, name, symbol, shares, avg_price FROM holdings WHERE account = ?", (broker,))
            if normalize_symbol(h["symbol"]) == symbol), None)

        pnl = None
        if side == "buy":
            if -summary["cash"] > account["balance"]:
                raise ValueError(f"「{account['name']}」餘額 {account['balance']:,.0f} 不夠付 {-summary['cash']:,.0f}")
            if holding:
                avg = avg_after_buy(holding["shares"], holding["avg_price"], shares, -summary["cash"])
                conn.execute("UPDATE holdings SET shares = shares + ?, avg_price = ? WHERE id = ?",
                             (shares, avg or 0.0, holding["id"]))
                name = holding["name"]
            else:
                name = name or symbol
                conn.execute(
                    "INSERT INTO holdings (name, symbol, account, shares, avg_price, price) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, symbol, broker, shares, -summary["cash"] / shares, price),
                )
        else:
            if holding is None or holding["shares"] < shares:
                have = holding["shares"] if holding else 0
                raise ValueError(f"「{broker}」只有 {have:,.0f} 股 {symbol}，不夠賣 {shares:,.0f} 股")
            name = holding["name"]
            pnl = realized_pnl(summary["cash"], holding["avg_price"], shares)
            if holding["shares"] == shares:
                conn.execute("DELETE FROM holdings WHERE id = ?", (holding["id"],))
            else:
                conn.execute("UPDATE holdings SET shares = shares - ? WHERE id = ?", (shares, holding["id"]))
            if pnl is None:
                note = (note + "；" if note else "") + "沒有均價，損益沒算"

        # 成交價就是現在的市價，同代號的其他券商也一起更新
        conn.execute("UPDATE holdings SET price = ? WHERE symbol = ?", (price, symbol))
        conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (summary["cash"], account_id))
        trade_type = "當沖" if day_trade else ("買進" if side == "buy" else "賣出")
        conn.execute(
            "INSERT INTO trades (date, symbol, type, pnl, note, side, shares, price, amount, fee, tax, broker, account_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date_str, f"{symbol} {name}" if name != symbol else symbol, trade_type, round(pnl or 0), note,
             side, shares, price, summary["amount"], summary["fee"], summary["tax"], broker, account_id),
        )
    return {**summary, "pnl": pnl}


def delete_trade(trade_id: int) -> None:
    """刪除一筆交易紀錄。只刪紀錄，不會把持股和帳戶改回去（記錯時到持股頁、帳戶頁校正）。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))


# ---------- 淨資產紀錄 ----------

def record_networth(date_str: str, value: float) -> None:
    """記下某一天的淨資產。同一天再記一次會覆蓋（一天只留最後的數字）。"""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO networth_history (date, value) VALUES (?, ?)",
            (date_str, value),
        )


def get_networth_history() -> list[dict]:
    """所有淨資產紀錄，舊的在前面。"""
    with get_connection() as conn:
        rows = conn.execute("SELECT date, value FROM networth_history ORDER BY date").fetchall()
    return [dict(row) for row in rows]


# ---------- 匯出 CSV 備份 ----------

# 要備份的資料表
EXPORT_TABLES = ["settings", "accounts", "budgets", "expenses", "fixed_expenses",
                 "debts", "debt_payments", "holdings", "brokers", "trades", "networth_history"]


def export_csv_zip() -> bytes:
    """把每張資料表各存成一個 CSV，打包成一個 zip，回傳 zip 檔的內容（bytes）。

    整個過程都在記憶體裡完成（io.BytesIO 就像一個「假的檔案」），
    不會在專案資料夾留下任何檔案，所以不用擔心備份檔被 commit。
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf, get_connection() as conn:
        for table in EXPORT_TABLES:
            # 表名不是使用者輸入的，是上面寫死的清單，所以可以放進 f-string
            cursor = conn.execute(f"SELECT * FROM {table}")
            headers = [col[0] for col in cursor.description]

            text = io.StringIO()
            writer = csv.writer(text)
            writer.writerow(headers)
            writer.writerows(cursor.fetchall())

            # utf-8-sig：在檔案開頭加 BOM，Excel 打開中文才不會變亂碼
            zf.writestr(f"{table}.csv", text.getvalue().encode("utf-8-sig"))
    return buffer.getvalue()


# ---------- 自動備份與還原 ----------
#
# 為什麼要自動備份：所有資料只存在一個 finance.db 檔，硬碟壞掉、誤刪、不小心按錯「刪除」就救不回來。
# 做法很簡單：每天第一次打開程式時，把資料庫複製一份到旁邊的 backups 資料夾，只留最近幾份。
# 備份檔和資料庫在同一個資料夾底下（exe 版是 ~/FinanceApp/backups，原始碼版是 data/backups，
# data/ 已經被 .gitignore 排除），所以不會被 commit。

BACKUP_KEEP = 14  # 只留最近 14 份，避免越積越多


def backup_dir() -> str:
    """備份資料夾：資料庫旁邊的 backups/。"""
    return os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")


def _db_stem() -> str:
    """資料庫檔名去掉副檔名，例如 finance。備份檔名用它開頭，範例資料庫的備份才不會混在一起。"""
    return os.path.splitext(os.path.basename(DB_PATH))[0]


def _copy_db(src: str, dst: str) -> None:
    """用 SQLite 內建的備份功能複製資料庫。

    不直接用 shutil.copy：如果複製的瞬間程式剛好在寫入，複製出來的檔案可能是壞的；
    SQLite 的 backup() 會確保複製出來的是一份完整的資料庫。
    """
    with sqlite3.connect(src) as source, sqlite3.connect(dst) as target:
        source.backup(target)
    # with 只會 commit，不會關閉連線；Windows 上沒關閉的檔案不能刪除或覆蓋，所以要自己關
    source.close()
    target.close()


def list_backups() -> list[str]:
    """所有備份檔的完整路徑，新的在前面。"""
    folder = backup_dir()
    if not os.path.isdir(folder):
        return []
    prefix = _db_stem() + "-"
    names = [n for n in os.listdir(folder) if n.startswith(prefix) and n.endswith(".db")]
    # 檔名裡有日期時間（YYYY-MM-DD...），字串排序就是時間排序
    return [os.path.join(folder, n) for n in sorted(names, reverse=True)]


def auto_backup(today: date | None = None) -> str | None:
    """今天還沒備份過就備份一次，回傳備份檔路徑；今天已經備份過或資料庫還不存在就回傳 None。"""
    if not os.path.exists(DB_PATH):
        return None
    today = today or date.today()
    folder = backup_dir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{_db_stem()}-{today.isoformat()}.db")
    if os.path.exists(path):
        return None
    _copy_db(DB_PATH, path)

    # 只留最近 BACKUP_KEEP 份「每日備份」；還原前另存的那份（檔名有 before-restore）不自動刪
    daily = [p for p in list_backups() if "before-restore" not in p]
    for old in daily[BACKUP_KEEP:]:
        os.remove(old)
    return path


def restore_backup(path: str) -> str:
    """用備份檔蓋掉目前的資料庫，回傳「還原前另存的那一份」的路徑。

    還原前先把目前的資料另存一份，萬一選錯備份還可以再還原回來。
    """
    # 先確認選的檔案真的是這個程式的資料庫，避免把別的檔案蓋上來
    try:
        with sqlite3.connect(path) as conn:
            conn.execute("SELECT key, value FROM settings").fetchall()
        conn.close()
    except sqlite3.Error as e:
        raise ValueError("這個檔案不是理財系統的備份") from e

    folder = backup_dir()
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    safety = os.path.join(folder, f"{_db_stem()}-{stamp}-before-restore.db")
    _copy_db(DB_PATH, safety)
    _copy_db(path, DB_PATH)
    init_db()  # 舊的備份可能少了新版才有的資料表，補上
    return safety


# ---------- 是不是剛開始使用 ----------

def is_empty() -> bool:
    """還沒輸入任何資料（第一次打開程式）時回傳 True，總覽頁會改成顯示「開始使用」的步驟。

    只要「任何一個地方」填過東西就不算空的：設定改過任何一項（例如只填了手上現金）、
    設過任何一個預算，或任何一張表有資料。以前只看「每月收入」，只填了現金或預算的人
    下次打開又看到歡迎畫面，會以為資料不見了。
    """
    with get_connection() as conn:
        for table in ["expenses", "fixed_expenses", "debts", "holdings", "trades"]:
            if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                return False
        # 開了第二個帳戶，或帳戶裡有錢，也算開始使用了
        if conn.execute("SELECT 1 FROM accounts WHERE balance != 0 OR id != (SELECT MIN(id) FROM accounts) LIMIT 1").fetchone():
            return False
        for row in conn.execute("SELECT key, value FROM settings"):
            if row["value"] != DEFAULT_SETTINGS.get(row["key"], 0.0):
                return False
        if conn.execute("SELECT 1 FROM budgets WHERE amount > 0 LIMIT 1").fetchone():
            return False
    return True


# ---------- 現在用的是不是平常那個資料庫 ----------

def standard_db_paths() -> list[str]:
    """平常會用到的資料庫位置：視窗版的 ~/FinanceApp/finance.db、原始碼版的 data/finance.db。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(os.path.expanduser("~"), "FinanceApp", "finance.db"),
        os.path.join(here, "data", "finance.db"),
    ]


def is_unusual_db(path: str | None = None) -> bool:
    """資料庫是不是「平常那個」以外的檔案（被環境變數 FINANCE_DB 指到別的地方）。

    為什麼要檢查：曾經有測試把 FINANCE_DB 指到暫存資料庫，從那裡開的程式記下的資料都寫進暫存檔，
    下次正常打開就「不見了」。畫面上明白顯示用的是哪個檔案，這種情況一眼就看得出來。
    範例資料庫（example.db）是故意用的，不算。
    """
    path = os.path.normcase(os.path.abspath(path or DB_PATH))
    if os.path.basename(path) == "example.db":
        return False
    return path not in [os.path.normcase(os.path.abspath(p)) for p in standard_db_paths()]
