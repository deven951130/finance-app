"""
個人理財管理系統：Streamlit 主程式。

執行方式：streamlit run app.py

Streamlit 的運作方式和一般程式不太一樣：
每次你在網頁上按按鈕或改數字，整個 app.py 會「從頭到尾重新跑一次」。
所以資料都要存在資料庫裡，每次重跑時再讀出來。
"""

from datetime import date

import streamlit as st

import db
from models.budget import (
    CATEGORIES,
    remaining_by_category,
    remaining_this_month,
    spent_by_category,
)

# 頁面基本設定（必須是第一個 st. 指令）
st.set_page_config(page_title="個人理財", page_icon="💰")

# 確保資料表存在
db.init_db()


def money(x: float) -> str:
    """把數字格式化成金額字串，例如 12345 -> '$12,345'。"""
    return f"${x:,.0f}"


# ---------- 頁面：記帳 ----------

def page_expenses() -> None:
    st.header("記帳")

    # st.form：把多個輸入框包在一起，按下送出才一次處理
    # clear_on_submit=True：送出後清空輸入框，方便記下一筆
    with st.form("add_expense", clear_on_submit=True):
        amount = st.number_input("金額", min_value=0.0, step=10.0)
        category = st.selectbox("類別", CATEGORIES)
        expense_date = st.date_input("日期", value=date.today())
        note = st.text_input("備註（可不填）")
        submitted = st.form_submit_button("新增")

    if submitted:
        if amount <= 0:
            st.error("金額要大於 0")
        else:
            # date 物件轉成 'YYYY-MM-DD' 字串存進資料庫
            db.add_expense(amount, category, expense_date.isoformat(), note)
            st.success(f"已記下：{category} {money(amount)}")

    # --- 本月統計 ---
    today = date.today()
    month_expenses = db.get_expenses_in_month(today.year, today.month)
    budgets = db.get_budgets()

    st.subheader(f"{today.year} 年 {today.month} 月")

    remaining = remaining_this_month(budgets, month_expenses)
    if remaining >= 0:
        st.metric("本月還能花", money(remaining))
    else:
        st.metric("本月還能花", money(remaining), delta="已超支", delta_color="inverse")

    # 各類別進度條：已花 / 預算
    spent = spent_by_category(month_expenses)
    left = remaining_by_category(budgets, month_expenses)
    for c in CATEGORIES:
        budget = budgets.get(c, 0.0)
        st.write(f"**{c}**：{money(spent[c])} / {money(budget)}（剩 {money(left[c])}）")
        # 進度條只接受 0.0 ~ 1.0，所以超過 1 就當作 1（滿格）
        if budget > 0:
            st.progress(min(spent[c] / budget, 1.0))
        else:
            st.progress(1.0 if spent[c] > 0 else 0.0)

    # --- 本月明細 ---
    st.subheader("本月明細")
    if not month_expenses:
        st.info("本月還沒有記帳")
        return

    for e in month_expenses:
        # st.columns：把一列切成幾欄，數字是寬度比例
        col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 4, 1])
        col1.write(e["date"])
        col2.write(e["category"])
        col3.write(money(e["amount"]))
        col4.write(e["note"] or "")
        # 每個按鈕需要唯一的 key，所以用支出的 id
        if col5.button("刪除", key=f"del_exp_{e['id']}"):
            db.delete_expense(e["id"])
            st.rerun()  # 立刻重跑，讓畫面更新


# ---------- 頁面：每月生活預算 ----------

def page_budgets() -> None:
    st.header("每月生活預算")
    budgets = db.get_budgets()

    with st.form("budgets"):
        new_budgets = {}
        for c in CATEGORIES:
            new_budgets[c] = st.number_input(
                c, min_value=0.0, step=100.0, value=float(budgets.get(c, 0.0))
            )
        if st.form_submit_button("儲存"):
            db.save_budgets(new_budgets)
            st.success("預算已儲存")

    st.write(f"每月生活預算合計：**{money(sum(new_budgets.values()))}**")


# ---------- 頁面：固定支出 ----------

def page_fixed() -> None:
    st.header("固定支出")

    with st.form("add_fixed", clear_on_submit=True):
        name = st.text_input("名稱（例如 電話費、iCloud）")
        amount = st.number_input("每月金額", min_value=0.0, step=10.0)
        if st.form_submit_button("新增"):
            if not name.strip():
                st.error("請輸入名稱")
            elif amount <= 0:
                st.error("金額要大於 0")
            else:
                db.add_fixed_expense(name.strip(), amount)
                st.success(f"已新增：{name}")

    items = db.get_fixed_expenses()
    if not items:
        st.info("還沒有固定支出")
        return

    for item in items:
        col1, col2, col3 = st.columns([4, 2, 1])
        col1.write(item["name"])
        col2.write(money(item["amount"]))
        if col3.button("刪除", key=f"del_fixed_{item['id']}"):
            db.delete_fixed_expense(item["id"])
            st.rerun()

    total = sum(item["amount"] for item in items)
    st.write(f"固定支出合計：**{money(total)}** / 月")


# ---------- 頁面：設定 ----------

def page_settings() -> None:
    st.header("設定")
    s = db.get_settings()

    with st.form("settings"):
        income = st.number_input("每月收入", min_value=0.0, step=1000.0,
                                 value=float(s["monthly_income"]))
        cash = st.number_input("手上現金", min_value=0.0, step=100.0,
                               value=float(s["cash_on_hand"]))
        fund = st.number_input("緊急預備金（目前存了多少）", min_value=0.0, step=100.0,
                               value=float(s["emergency_fund"]))
        target = st.number_input("預備金目標", min_value=0.0, step=1000.0,
                                 value=float(s["emergency_target"]))
        if st.form_submit_button("儲存"):
            db.save_settings({
                "monthly_income": income,
                "cash_on_hand": cash,
                "emergency_fund": fund,
                "emergency_target": target,
            })
            st.success("設定已儲存")

    # 預備金進度
    if target > 0:
        st.write(f"緊急預備金進度：{money(fund)} / {money(target)}")
        st.progress(min(fund / target, 1.0))


# ---------- 側邊欄：選擇頁面 ----------

# 用 dict 把「頁面名稱」對應到「要呼叫的函式」
PAGES = {
    "記帳": page_expenses,
    "每月預算": page_budgets,
    "固定支出": page_fixed,
    "設定": page_settings,
}

choice = st.sidebar.radio("功能", list(PAGES.keys()))
PAGES[choice]()  # 呼叫被選中的頁面函式
