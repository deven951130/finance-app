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

from models.budget import CATEGORIES
from models.debt import payment_this_period



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

# 設定頁的預設值：預備金目標預設 17000，其他預設 0
DEFAULT_SETTINGS = {
    "monthly_income": 0.0,     # 每月收入
    "cash_on_hand": 0.0,       # 手上現金
    "emergency_fund": 0.0,     # 緊急預備金（目前存了多少）
    "emergency_target": 17000.0,  # 預備金目標
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


# ---------- 設定 ----------

def get_settings() -> dict[str, float]:
    """讀取所有設定，回傳 {名稱: 數值}。"""
    with get_connection() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def save_settings(settings: dict[str, float]) -> None:
    """儲存設定（有就更新，沒有就新增）。"""
    with get_connection() as conn:
        for key, value in settings.items():
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )


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

def add_expense(amount: float, category: str, date_str: str, note: str) -> None:
    """新增一筆支出。date_str 格式為 'YYYY-MM-DD'。"""
    with get_connection() as conn:
        # 用 ? 當佔位符號，不要自己拼字串，可以避免 SQL injection
        conn.execute(
            "INSERT INTO expenses (amount, category, date, note) VALUES (?, ?, ?, ?)",
            (amount, category, date_str, note),
        )


def get_expenses_in_month(year: int, month: int) -> list[dict]:
    """讀取某年某月的所有支出，依日期由新到舊排序。"""
    # 日期存成 'YYYY-MM-DD'，所以用開頭 'YYYY-MM' 比對就能篩出整個月
    prefix = f"{year:04d}-{month:02d}-%"
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, amount, category, date, note FROM expenses"
            " WHERE date LIKE ? ORDER BY date DESC, id DESC",
            (prefix,),
        ).fetchall()
    # 把 sqlite3.Row 轉成一般的 dict，給 models 和畫面使用
    return [dict(row) for row in rows]


def delete_expense(expense_id: int) -> None:
    """刪除一筆支出（記錯時用）。"""
    with get_connection() as conn:
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
    """讀取所有負債。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, remaining, monthly_payment FROM debts ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def add_debt(name: str, remaining: float, monthly_payment: float) -> None:
    """新增一筆負債。"""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO debts (name, remaining, monthly_payment) VALUES (?, ?, ?)",
            (name, remaining, monthly_payment),
        )


def delete_debt(debt_id: int) -> None:
    """刪除一筆負債。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM debts WHERE id = ?", (debt_id,))


def pay_debt_installment(debt_id: int) -> float:
    """「已還一期」：剩餘金額和手上現金同時扣掉這一期的還款，回傳扣了多少。

    兩個數字放在同一個 with 區塊裡更新，這叫「交易（transaction）」：
    要嘛兩個都改成功，要嘛中途出錯兩個都不改，不會只扣了一邊。
    現金不夠時會丟出 ValueError，什麼都不改。
    """
    with get_connection() as conn:
        debt = conn.execute(
            "SELECT remaining, monthly_payment FROM debts WHERE id = ?", (debt_id,)
        ).fetchone()
        cash = conn.execute(
            "SELECT value FROM settings WHERE key = 'cash_on_hand'"
        ).fetchone()["value"]

        pay = payment_this_period(debt["remaining"], debt["monthly_payment"])
        if pay <= 0:
            raise ValueError("這筆負債已經還清了")
        if pay > cash:
            raise ValueError(f"手上現金 {cash:,.0f} 不夠還這一期 {pay:,.0f}")

        conn.execute(
            "UPDATE debts SET remaining = remaining - ? WHERE id = ?", (pay, debt_id)
        )
        conn.execute(
            "UPDATE settings SET value = value - ? WHERE key = 'cash_on_hand'", (pay,)
        )
    return pay


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
    """新增一筆持股。同代號的其他帳戶現價也一起更新，確保合併計算時一致。"""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO holdings (name, symbol, account, shares, avg_price, price)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (name, symbol, account, shares, avg_price, price),
        )
        conn.execute("UPDATE holdings SET price = ? WHERE symbol = ?", (price, symbol))


def update_price(symbol: str, price: float) -> None:
    """更新某個代號的現價（所有帳戶一起改）。"""
    with get_connection() as conn:
        conn.execute("UPDATE holdings SET price = ? WHERE symbol = ?", (price, symbol))


def delete_holding(holding_id: int) -> None:
    """刪除一筆持股。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))


# ---------- 交易紀錄 ----------

def get_trades() -> list[dict]:
    """讀取所有交易紀錄，新的在前面。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, date, symbol, type, pnl, note FROM trades"
            " ORDER BY date DESC, id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def add_trade(date_str: str, symbol: str, trade_type: str, pnl: float, note: str) -> None:
    """新增一筆交易紀錄。"""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO trades (date, symbol, type, pnl, note) VALUES (?, ?, ?, ?, ?)",
            (date_str, symbol, trade_type, pnl, note),
        )


def delete_trade(trade_id: int) -> None:
    """刪除一筆交易紀錄。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))


# ---------- 匯出 CSV 備份 ----------

# 要備份的資料表
EXPORT_TABLES = ["settings", "budgets", "expenses", "fixed_expenses",
                 "debts", "holdings", "trades"]


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
