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


def get_expenses_since(date_str: str) -> list[dict]:
    """讀取某一天（含）以後的所有支出，給「近幾個月趨勢」用。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, amount, category, date, note FROM expenses WHERE date >= ?"
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


def update_expense(expense_id: int, amount: float, category: str, date_str: str, note: str) -> None:
    """修改一筆支出（記錯金額、類別、日期時用，不用刪掉重記）。"""
    with get_connection() as conn:
        conn.execute(
            "UPDATE expenses SET amount = ?, category = ?, date = ?, note = ? WHERE id = ?",
            (amount, category, date_str, note, expense_id),
        )


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
    """刪除一筆負債（連同它的還款紀錄）。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM debts WHERE id = ?", (debt_id,))
        conn.execute("DELETE FROM debt_payments WHERE debt_id = ?", (debt_id,))


def get_debt_payments(debt_id: int) -> list[dict]:
    """某筆負債的還款紀錄，新的在前面。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, date, amount FROM debt_payments WHERE debt_id = ?"
            " ORDER BY date DESC, id DESC",
            (debt_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def pay_debt_installment(debt_id: int, date_str: str | None = None) -> float:
    """「已還一期」：剩餘金額和手上現金同時扣掉這一期的還款，並記一筆還款紀錄，回傳扣了多少。

    三件事放在同一個 with 區塊裡，這叫「交易（transaction）」：
    要嘛全部成功，要嘛中途出錯全部不改，不會只扣了一邊。
    現金不夠時會丟出 ValueError，什麼都不改。
    date_str 是還款日期（'YYYY-MM-DD'），沒給就是今天。
    """
    date_str = date_str or date.today().isoformat()
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
        conn.execute(
            "INSERT INTO debt_payments (debt_id, date, amount) VALUES (?, ?, ?)",
            (debt_id, date_str, pay),
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
EXPORT_TABLES = ["settings", "budgets", "expenses", "fixed_expenses",
                 "debts", "debt_payments", "holdings", "trades", "networth_history"]


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
