"""
預算計算邏輯。

這裡的函式只吃「普通的 Python 資料」（dict、list），回傳計算結果，
不讀資料庫、不畫畫面。這樣的函式叫做「純函式」，好處是很好測試：
給固定的輸入，一定得到固定的輸出。
"""

from datetime import date

# 生活預算的四個類別（之後要加類別，改這裡就好）
CATEGORIES = ["吃飯", "約會禮物", "交通", "其他"]


def is_in_month(date_str: str, year: int, month: int) -> bool:
    """判斷日期字串（格式 'YYYY-MM-DD'）是否落在指定的年、月。"""
    d = date.fromisoformat(date_str)
    return d.year == year and d.month == month


def filter_month(expenses: list[dict], year: int, month: int) -> list[dict]:
    """從所有支出中，挑出指定年月的那幾筆。

    每筆支出是一個 dict，至少要有 'amount'、'category'、'date' 三個鍵。
    """
    return [e for e in expenses if is_in_month(e["date"], year, month)]


def spent_by_category(expenses: list[dict]) -> dict[str, float]:
    """把支出依類別加總，回傳 {類別: 已花金額}。

    每個類別都會出現在結果裡，沒花錢的類別是 0。
    """
    # 先把每個類別都設成 0（類似 C++ 的 std::map 先初始化）
    totals = {c: 0.0 for c in CATEGORIES}
    for e in expenses:
        # 用 get 是為了防止出現 CATEGORIES 以外的類別時程式出錯
        totals[e["category"]] = totals.get(e["category"], 0.0) + e["amount"]
    return totals


def remaining_this_month(budgets: dict[str, float], month_expenses: list[dict]) -> float:
    """計算「本月還能花多少」。

    公式：所有類別的預算總和 − 本月已花總和
    超支時會得到負數，代表已經超出預算多少。

    budgets：{類別: 預算金額}
    month_expenses：本月的支出清單（請先用 filter_month 篩好）
    """
    total_budget = sum(budgets.values())
    total_spent = sum(e["amount"] for e in month_expenses)
    return total_budget - total_spent


def remaining_by_category(budgets: dict[str, float], month_expenses: list[dict]) -> dict[str, float]:
    """每個類別各自還能花多少：{類別: 預算 − 已花}。"""
    spent = spent_by_category(month_expenses)
    return {c: budgets.get(c, 0.0) - spent.get(c, 0.0) for c in CATEGORIES}
