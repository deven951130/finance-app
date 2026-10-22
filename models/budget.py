"""
預算計算邏輯。

這裡的函式只吃「普通的 Python 資料」（dict、list），回傳計算結果，
不讀資料庫、不畫畫面。這樣的函式叫做「純函式」，好處是很好測試：
給固定的輸入，一定得到固定的輸出。
"""

from datetime import date

# 支出的主類別（預算是照主類別設定）和每個主類別底下的細項。之後要加類別，改這裡就好。
# 原本的四個主類別（吃飯、約會禮物、交通、其他）名字不變，舊的記帳和預算才對得上；
# 2026-10-22 使用者要求「種類再多、要分細項」，加上後面五個主類別和所有細項。
# （dict 會照寫的順序排，像 C++ 的 std::vector<std::pair<...>>，畫面上的順序就是這裡的順序）
SUBCATEGORIES = {
    "吃飯": ["早餐", "午餐", "晚餐", "飲料點心", "聚餐", "買菜"],
    "交通": ["捷運公車", "加油", "停車", "計程車", "火車高鐵", "機車汽車保養"],
    "購物": ["日用品", "衣服鞋子", "3C 電子", "網購"],
    "居家": ["房租", "水電瓦斯", "網路電話", "家具家電"],
    "娛樂": ["電影展覽", "遊戲", "旅遊", "訂閱服務", "運動"],
    "約會禮物": ["約會", "禮物", "紅包"],
    "醫療保健": ["看診", "藥品", "保健食品", "保險"],
    "學習": ["書籍", "課程", "文具"],
    "其他": ["手續費", "捐款", "其他"],
}
CATEGORIES = list(SUBCATEGORIES)

# 收入的類別和細項（收入不設預算）
INCOME_CATEGORIES = {
    "薪資": ["月薪", "加班費", "兼職打工"],
    "獎金": ["年終", "績效", "三節"],
    "投資": ["股利", "利息", "賣股獲利"],
    "家人朋友": ["零用錢", "紅包", "還錢"],
    "其他收入": ["退款", "中獎", "二手拍賣", "其他"],
}


def category_options(kind: str = "expense") -> list[str]:
    """選單用的選項：「主類別 · 細項」攤平成一個清單，例如「吃飯 · 午餐」。

    為什麼攤平：Streamlit 的表單（st.form）裡，選了主類別不會馬上更新細項選單，
    所以把兩層合成一個選單，一次選完。
    """
    table = SUBCATEGORIES if kind == "expense" else INCOME_CATEGORIES
    return [f"{main} · {sub}" for main, subs in table.items() for sub in subs]


def split_option(option: str) -> tuple[str, str | None]:
    """「吃飯 · 午餐」→ ("吃飯", "午餐")；沒有細項的舊資料（只有主類別）→ ("吃飯", None)。"""
    main, _, sub = option.partition(" · ")
    return main, (sub or None)


def join_option(main: str, sub: str | None) -> str:
    """("吃飯", "午餐") → 「吃飯 · 午餐」；沒有細項就只有主類別。"""
    return f"{main} · {sub}" if sub else main


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


def last_n_months(today: date, n: int) -> list[str]:
    """包含本月在內的最近 n 個月，格式 'YYYY-MM'，舊的在前面。

    例如今天 2026-02-10、n=3 → ['2025-12', '2026-01', '2026-02']。
    """
    # 把年月換算成「第幾個月」再往回推，跨年時不用另外判斷
    total = today.year * 12 + (today.month - 1)
    return [f"{m // 12:04d}-{m % 12 + 1:02d}" for m in range(total - n + 1, total + 1)]


def monthly_totals(expenses: list[dict], months: list[str]) -> list[dict]:
    """把支出依「月份 × 類別」加總，給趨勢圖用。

    回傳 [{"月份": 'YYYY-MM', "類別": ..., "金額": ...}, ...]，
    months 裡的每個月、CATEGORIES 的每個類別都會出現（沒花錢就是 0），圖上才不會少一格。
    """
    totals = {(m, c): 0.0 for m in months for c in CATEGORIES}
    for e in expenses:
        key = (e["date"][:7], e["category"])
        if key in totals:
            totals[key] += e["amount"]
    return [{"月份": m, "類別": c, "金額": v} for (m, c), v in totals.items()]
