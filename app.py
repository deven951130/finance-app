"""
個人理財管理系統：Streamlit 主程式。

執行方式：streamlit run app.py

Streamlit 的運作方式和一般程式不太一樣：
每次你在網頁上按按鈕或改數字，整個 app.py 會「從頭到尾重新跑一次」。
所以資料都要存在資料庫裡，每次重跑時再讀出來。
"""

from datetime import date

import pandas as pd  # 安裝 streamlit 時會一起裝好，用來顯示表格
import streamlit as st

import db
from models.budget import (
    CATEGORIES,
    remaining_by_category,
    remaining_this_month,
    spent_by_category,
)
from models.cashflow import monthly_savings, total_debt_payment
from models.debt import payment_this_period, payoff_month
from models.stocks import CONCENTRATION_LIMIT, analyze, over_concentrated

# 頁面基本設定（必須是第一個 st. 指令）
st.set_page_config(page_title="個人理財", page_icon="💰")

# 確保資料表存在
db.init_db()


def money(x: float) -> str:
    """把數字格式化成金額字串，例如 12345 -> '$12,345'。"""
    return f"${x:,.0f}"


def profit_color(x: float) -> str:
    """台股習慣：賺錢紅色、賠錢綠色。回傳 CSS 顏色字串。"""
    if x > 0:
        return "color: red"
    if x < 0:
        return "color: green"
    return ""


def colored_money(x: float) -> str:
    """用 Streamlit 的 :red[...]、:green[...] 語法幫金額上色（台股習慣）。"""
    if x > 0:
        return f":red[+{money(x)}]"
    if x < 0:
        return f":green[{money(x)}]"
    return money(x)


# ---------- 頁面：總覽 ----------

def page_overview() -> None:
    st.header("總覽")

    # --- 每月現金流 ---
    settings = db.get_settings()
    income = settings["monthly_income"]
    fixed_total = sum(item["amount"] for item in db.get_fixed_expenses())
    debt_payment = total_debt_payment(db.get_debts())
    living = sum(db.get_budgets().values())
    savings = monthly_savings(income, fixed_total, debt_payment, living)

    st.subheader("每月現金流")
    # 用表格把算式一項一項列出來，比較好對帳
    st.table(pd.DataFrame({
        "項目": ["收入", "− 固定支出", "− 負債還款", "− 生活預算", "= 每月可存"],
        "金額": [money(income), money(fixed_total), money(debt_payment),
                 money(living), money(savings)],
    }).set_index("項目"))
    if savings < 0:
        st.error(f"每月入不敷出 {money(-savings)}")

    # --- 持股集中度警告 ---
    analyzed = analyze(db.get_holdings())
    for m in over_concentrated(analyzed):
        st.warning(
            f"⚠️ {m['name']}（{m['symbol']}）占總市值 {m['weight']:.1%}，"
            f"超過 {CONCENTRATION_LIMIT:.0%}，風險過度集中"
        )

    # --- 簡單資產概況 ---
    total_value = sum(m["value"] for m in analyzed)
    total_debt = sum(d["remaining"] for d in db.get_debts())
    col1, col2, col3 = st.columns(3)
    col1.metric("手上現金", money(settings["cash_on_hand"]))
    col2.metric("股票市值", money(total_value))
    col3.metric("負債餘額", money(total_debt))


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


# ---------- 頁面：負債 ----------

def page_debts() -> None:
    st.header("負債追蹤")

    with st.form("add_debt", clear_on_submit=True):
        name = st.text_input("名稱（例如 學貸、信用卡分期）")
        remaining = st.number_input("剩餘金額", min_value=0.0, step=1000.0)
        monthly = st.number_input("每月還款", min_value=0.0, step=100.0)
        if st.form_submit_button("新增"):
            if not name.strip():
                st.error("請輸入名稱")
            elif remaining <= 0 or monthly <= 0:
                st.error("剩餘金額和每月還款都要大於 0")
            else:
                db.add_debt(name.strip(), remaining, monthly)
                st.success(f"已新增：{name}")

    st.write(f"手上現金：**{money(db.get_settings()['cash_on_hand'])}**")

    debts = db.get_debts()
    if not debts:
        st.info("沒有負債 🎉")
        return

    today = date.today()
    for d in debts:
        # st.container(border=True)：畫一個有框線的區塊，讓每筆負債分開
        with st.container(border=True):
            st.write(f"**{d['name']}**")
            col1, col2, col3 = st.columns(3)
            col1.write(f"剩餘 {money(d['remaining'])}")
            col2.write(f"每月 {money(d['monthly_payment'])}")
            ym = payoff_month(d["remaining"], d["monthly_payment"], today)
            col3.write("已還清 ✅" if ym is None else f"預計 {ym[0]} 年 {ym[1]} 月還清")

            b1, b2 = st.columns(2)
            if ym is not None:
                pay = payment_this_period(d["remaining"], d["monthly_payment"])
                if b1.button(f"已還一期（{money(pay)}）", key=f"pay_{d['id']}"):
                    try:
                        db.pay_debt_installment(d["id"])
                        st.rerun()
                    except ValueError as e:  # 現金不夠時，db 會丟出 ValueError
                        st.error(str(e))
            if b2.button("刪除", key=f"del_debt_{d['id']}"):
                db.delete_debt(d["id"])
                st.rerun()


# ---------- 頁面：持股 ----------

def page_stocks() -> None:
    st.header("持股管理")

    with st.form("add_holding", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        name = col1.text_input("名稱（例如 台積電）")
        symbol = col2.text_input("代號（例如 2330）")
        account = col3.text_input("帳戶（例如 富邦）")
        col4, col5, col6 = st.columns(3)
        shares = col4.number_input("股數", min_value=0.0, step=1.0)
        avg_price = col5.number_input("均價", min_value=0.0, step=0.1)
        price = col6.number_input("現價", min_value=0.0, step=0.1)
        if st.form_submit_button("新增"):
            if not (name.strip() and symbol.strip() and account.strip()):
                st.error("名稱、代號、帳戶都要填")
            elif shares <= 0 or avg_price <= 0 or price <= 0:
                st.error("股數、均價、現價都要大於 0")
            else:
                db.add_holding(name.strip(), symbol.strip(), account.strip(),
                               shares, avg_price, price)
                st.success(f"已新增：{name} {account}")

    holdings = db.get_holdings()
    if not holdings:
        st.info("還沒有持股")
        return

    # --- 合併後的計算結果 ---
    analyzed = analyze(holdings)
    total_value = sum(m["value"] for m in analyzed)
    total_profit = sum(m["profit"] for m in analyzed)
    st.subheader("持股總覽（同代號已合併）")
    st.markdown(f"總市值 **{money(total_value)}**　總損益 **{colored_money(total_profit)}**")

    table = pd.DataFrame([{
        "名稱": m["name"],
        "代號": m["symbol"],
        "帳戶": "、".join(m["accounts"]),
        "股數": m["shares"],
        "均價": m["avg_price"],
        "現價": m["price"],
        "市值": m["value"],
        "損益": m["profit"],
        "報酬率%": m["profit_pct"],
        "占比%": m["weight"] * 100,
        "回本價": m["breakeven"],          # 沒虧損時是 None，表格顯示空白
        "還要漲%": m["rise_needed"],
    } for m in analyzed])

    # Styler：幫表格上色、設定數字格式
    styled = (
        table.style
        .map(profit_color, subset=["損益", "報酬率%"])
        .format({
            "股數": "{:,.0f}", "均價": "{:,.2f}", "現價": "{:,.2f}",
            "市值": "{:,.0f}", "損益": "{:+,.0f}", "報酬率%": "{:+.2f}",
            "占比%": "{:.1f}", "回本價": "{:,.2f}", "還要漲%": "{:.2f}",
        }, na_rep="")
    )
    st.dataframe(styled, hide_index=True)

    # --- 更新現價 ---
    st.subheader("更新現價")
    with st.form("update_price"):
        symbols = [m["symbol"] for m in analyzed]
        sym = st.selectbox("代號", symbols,
                           format_func=lambda s: f"{s} {next(m['name'] for m in analyzed if m['symbol'] == s)}")
        new_price = st.number_input("新的現價", min_value=0.0, step=0.1)
        if st.form_submit_button("更新"):
            if new_price <= 0:
                st.error("現價要大於 0")
            else:
                db.update_price(sym, new_price)
                st.rerun()

    # --- 各帳戶明細（可刪除）---
    st.subheader("各帳戶明細")
    for h in holdings:
        col1, col2, col3, col4 = st.columns([3, 2, 3, 1])
        col1.write(f"{h['name']}（{h['symbol']}）")
        col2.write(h["account"])
        col3.write(f"{h['shares']:,.0f} 股 @ {h['avg_price']:,.2f}")
        if col4.button("刪除", key=f"del_hold_{h['id']}"):
            db.delete_holding(h["id"])
            st.rerun()


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
    "總覽": page_overview,
    "記帳": page_expenses,
    "每月預算": page_budgets,
    "固定支出": page_fixed,
    "負債": page_debts,
    "持股": page_stocks,
    "設定": page_settings,
}

choice = st.sidebar.radio("功能", list(PAGES.keys()))
PAGES[choice]()  # 呼叫被選中的頁面函式
