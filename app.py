"""
個人理財管理系統：Streamlit 主程式。

執行方式：streamlit run app.py

Streamlit 的運作方式和一般程式不太一樣：
每次你在網頁上按按鈕或改數字，整個 app.py 會「從頭到尾重新跑一次」。
所以資料都要存在資料庫裡，每次重跑時再讀出來。

外觀分成兩層：
- .streamlit/config.toml：整體配色、字型、圓角（Streamlit 內建的主題設定）
- 這個檔案的 inject_css()：少量 CSS，做卡片陰影、預算進度條、手機版面這些主題設定做不到的部分

檔案由上到下：配色與 CSS → 共用小工具 → 各頁面函式 → 側邊欄 → 主程式
"""

import html
import os
from datetime import date

import altair as alt  # 安裝 streamlit 時會一起裝好，用來畫圖表
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
from models.debt import months_left, payment_this_period, payoff_month
from models.dca import monthly_withdrawal, project
from models.precheck import CHECK_ITEMS, check_order
from models.stocks import CONCENTRATION_LIMIT, analyze, over_concentrated
from models.trades import TRADE_TYPES, count_day_trades, total_pnl

# 頁面基本設定（必須是第一個 st. 指令）
st.set_page_config(page_title="個人理財", page_icon="💰", layout="wide")

# 確保資料表存在
db.init_db()


# ---------- 配色 ----------
# 和 .streamlit/config.toml 用同一組顏色，圖表和自訂 HTML 才會一致

INK = "#2B4C7E"      # 主色：墨藍
GOLD = "#C9973F"     # 強調色：金色（存下來的錢、快用完的預算）
GAIN = "#D64545"     # 賺錢：紅（台股習慣）
LOSS = "#1E9E6A"     # 賠錢：綠（台股習慣）
WARN = "#E07B24"     # 超支：橘（刻意不用紅色，避免和「賺錢紅」搞混）
MUTED = "#6B7280"    # 次要文字：灰（對白底約 4.8:1，符合一般建議的 4.5:1）
CHART_COLORS = ["#2B4C7E", "#C9973F", "#6C8EBF", "#8A6FB0", "#4F9A94", "#B7B1A5"]

# 每個記帳類別配一個小圖示，表格和進度條比較好認
CATEGORY_ICONS = {"吃飯": "🍱", "約會禮物": "🎁", "交通": "🚇", "其他": "🧺"}


def inject_css() -> None:
    """插入少量自訂 CSS。

    st.container(key="card_xxx") 會在 HTML 加上 class「st-key-card_xxx」，
    所以下面用 [class*="st-key-card"] 就能選到所有「卡片」，不用依賴 Streamlit 內部的結構。
    """
    st.markdown("""
<style>
/* 內容區最大寬度，大螢幕上不會拉得太開 */
.block-container { max-width: 1240px; padding-top: 2.2rem; padding-bottom: 3rem; }
header[data-testid="stHeader"] { background: transparent; }

/* 數字卡（st.metric(border=True)）和自訂卡片：白底、柔和陰影 */
div[data-testid="stMetric"], [class*="st-key-card"] {
    background: #FFFFFF;
    box-shadow: 0 1px 2px rgba(31, 38, 51, .04), 0 4px 14px rgba(31, 38, 51, .05);
}
div[data-testid="stMetric"] { padding: 16px 20px; min-height: 160px; }
div[data-testid="stMetricLabel"] p { color: #5F6672; font-size: .9rem; }
[class*="st-key-card"] { padding: 20px 22px; border-radius: 14px; }

/* 頁首：標題 + 一行說明 */
.page-head { margin-bottom: 1.2rem; }
.page-head h1 { font-size: 2rem; margin: 0; padding: 0; letter-spacing: .02em; }
.page-head p { color: #5F6672; margin: .25rem 0 0; }

/* 卡片內的小標題 */
.card-title { font-weight: 700; font-size: 1.05rem; margin: 0 0 .6rem; color: #1F2633; }
.card-title span { color: #6B7280; font-weight: 400; font-size: .85rem; margin-left: .4rem; }

/* 帳本式的明細：左邊項目、右邊金額，最後一列是合計 */
.ledger { width: 100%; }
.ledger-row { display: flex; justify-content: space-between; padding: 7px 0;
              border-bottom: 1px dashed #E2DDD2; font-variant-numeric: tabular-nums; }
.ledger-row.total { border-bottom: none; border-top: 2px solid #1F2633;
                    margin-top: 4px; font-weight: 700; font-size: 1.05rem; }
.ledger-row .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%;
                   margin-right: 8px; vertical-align: 1px; }

/* 預算進度條 */
.budget { margin: 4px 0 14px; }
.budget-top { display: flex; justify-content: space-between; font-size: .92rem;
              font-variant-numeric: tabular-nums; }
.budget-top b { font-weight: 600; }
.budget-track { height: 10px; background: #ECE8DF; border-radius: 99px; margin: 6px 0 3px; overflow: hidden; }
.budget-fill { height: 100%; border-radius: 99px; }
.budget-note { font-size: .8rem; color: #5F6672; }

/* 卡片裡的大數字（例如負債的剩餘金額） */
.big-label { font-size: .85rem; color: #5F6672; }
.big-num { font-size: 1.55rem; font-weight: 600; font-variant-numeric: tabular-nums; margin-bottom: .6rem; }

/* 小標籤（例如「當沖」「已還清」） */
.chip { display: inline-block; white-space: nowrap; padding: 1px 10px; border-radius: 99px; font-size: .8rem;
        font-weight: 600; line-height: 1.6; }

/* 側邊欄 */
section[data-testid="stSidebar"] .brand { font-size: 1.25rem; font-weight: 700; margin: 0 0 2px; }
section[data-testid="stSidebar"] .brand-sub { font-size: .8rem; opacity: .75; margin-bottom: 1rem; }
section[data-testid="stSidebar"] .nav-group { font-size: .72rem; letter-spacing: .12em;
    opacity: .75; margin: 1rem 0 .2rem .2rem; }
section[data-testid="stSidebar"] .side-sum { background: rgba(255,255,255,.06);
    border: 1px solid rgba(255,255,255,.08); border-radius: 12px; padding: 12px 14px; margin-top: 1.2rem; }
section[data-testid="stSidebar"] .side-sum div { display: flex; justify-content: space-between;
    font-size: .85rem; padding: 3px 0; font-variant-numeric: tabular-nums; }
section[data-testid="stSidebar"] .side-sum span { opacity: .8; }

/* 列表裡的刪除按鈕：平常淡淡的，滑過才變紅 */
button[kind="tertiary"] { color: #6B7280; }
button[kind="tertiary"]:hover { color: #D64545; }

/* 表單送出按鈕撐滿一點，比較好按 */
div[data-testid="stFormSubmitButton"] button { min-width: 120px; }

/* ---------- 手機（寬度 640px 以下） ----------
   Streamlit 在窄螢幕會把每個欄位都疊成一行，明細列表就會被拉得很長。
   列表卡片的 key 都以 _list 結尾，這裡讓它們的每一列保持橫排。 */
@media (max-width: 640px) {
    .block-container { padding-left: 1rem; padding-right: 1rem; padding-top: 1.2rem; }
    .page-head h1 { font-size: 1.6rem; }
    div[data-testid="stMetric"] { min-height: 0; padding: 12px 16px; }
    [class*="st-key-card"] { padding: 16px 14px; }
    [class*="st-key-card"][class*="_list"] div[data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap; gap: .35rem;
    }
    [class*="st-key-card"][class*="_list"] div[data-testid="stColumn"] {
        min-width: 0 !important; overflow-wrap: anywhere;
    }
    [class*="st-key-card"][class*="_list"] p { font-size: .82rem; }
    /* 數字卡一列放兩張，不要一張佔滿一整列 */
    div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] div[data-testid="stMetric"]) {
        flex-wrap: wrap; gap: .6rem;
    }
    div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] div[data-testid="stMetric"]) > div[data-testid="stColumn"] {
        min-width: calc(50% - .3rem) !important; width: calc(50% - .3rem) !important;
        flex: 1 1 calc(50% - .3rem) !important;
    }
    div[data-testid="stMetricValue"] div { font-size: 1.25rem; }
    /* 刪除按鈕只留垃圾桶圖示，省空間 */
    [class*="st-key-card"][class*="_list"] button[kind="tertiary"] div[data-testid="stMarkdownContainer"] {
        display: none;
    }
}
</style>
""", unsafe_allow_html=True)


# ---------- 小工具：格式化與共用畫面元件 ----------

def money(x: float) -> str:
    """把數字格式化成金額字串，例如 12345 -> '12,345 元'。

    注意：不要用 $ 符號！Streamlit 的 markdown 會把兩個 $ 中間的文字
    當成數學公式（LaTeX），一行出現兩個金額就會整段變形。
    """
    return f"{x:,.0f} 元"


def signed_money(x: float) -> str:
    """帶正負號的金額，例如 +3,600 元、-1,200 元。"""
    return f"{x:+,.0f} 元"


def profit_color(x: float) -> str:
    """台股習慣：賺錢紅色、賠錢綠色。回傳 CSS 顏色字串（給表格上色用）。"""
    if x > 0:
        return f"color: {GAIN}"
    if x < 0:
        return f"color: {LOSS}"
    return ""


def colored_money(x: float) -> str:
    """用 Streamlit 的 :red[...]、:green[...] 語法幫金額上色（台股習慣）。"""
    if x > 0:
        return f":red[+{money(x)}]"
    if x < 0:
        return f":green[{money(x)}]"
    return money(x)


def colored_money_html(x: float) -> str:
    """同 colored_money，但輸出 HTML（給自訂 HTML 區塊用）。"""
    if x > 0:
        return f'<span style="color:{GAIN}">+{money(x)}</span>'
    if x < 0:
        return f'<span style="color:{LOSS}">{money(x)}</span>'
    return money(x)


def page_header(title: str, subtitle: str) -> None:
    """每一頁最上面的標題和一行說明。"""
    st.markdown(f'<div class="page-head"><h1>{title}</h1><p>{subtitle}</p></div>',
                unsafe_allow_html=True)


def card_title(title: str, note: str = "") -> None:
    """卡片裡的小標題，note 是旁邊的灰色小字。"""
    extra = f"<span>{note}</span>" if note else ""
    st.markdown(f'<div class="card-title">{title}{extra}</div>', unsafe_allow_html=True)


def ledger(rows: list[tuple[str, str, str]]) -> None:
    """畫帳本式明細。rows 是 [(顏色, 項目, 金額), ...]，最後一列當作合計。

    顏色是項目前面的小圓點，空字串就不畫。
    """
    parts = []
    for i, (color, label, amount) in enumerate(rows):
        cls = "ledger-row total" if i == len(rows) - 1 else "ledger-row"
        dot = f'<span class="dot" style="background:{color}"></span>' if color else ""
        parts.append(f'<div class="{cls}"><div>{dot}{label}</div><div>{amount}</div></div>')
    st.markdown(f'<div class="ledger">{"".join(parts)}</div>', unsafe_allow_html=True)


def progress_bar(label: str, value: float, target: float, color: str, note: str,
                 ratio: float | None = None) -> None:
    """通用進度條：label 標題、value / target 決定長度，note 是下面的小字。

    ratio 可以直接指定長度比例（0 ~ 1 以上），沒給就用 value / target 算。
    """
    if ratio is None:
        ratio = value / target if target > 0 else 0.0
    st.markdown(f"""
<div class="budget">
  <div class="budget-top"><b>{label}</b><span>{money(value)} / {money(target)}</span></div>
  <div class="budget-track"><div class="budget-fill" style="width:{min(ratio, 1.0) * 100:.1f}%;background:{color}"></div></div>
  <div class="budget-note">{note}</div>
</div>""", unsafe_allow_html=True)


def budget_bar(label: str, spent: float, budget: float) -> None:
    """一個類別的預算進度條。

    顏色：用不到 8 成是墨藍、8 成到滿是金色（提醒）、超過就是橘色（超支）。
    """
    if budget > 0:
        ratio = spent / budget
    else:
        ratio = 1.0 if spent > 0 else 0.0
    color = INK if ratio < 0.8 else (GOLD if ratio <= 1 else WARN)
    left = budget - spent
    if left >= 0:
        note = f"剩 {money(left)}・已用 {ratio:.0%}"
    else:
        note = f'<span style="color:{WARN};font-weight:600">超支 {money(-left)}</span>'
    progress_bar(label, spent, budget, color, note, ratio)


def big_number(label: str, value: str) -> str:
    """回傳「小標籤 + 大數字」的 HTML，用在卡片裡面。"""
    return f'<div class="big-label">{label}</div><div class="big-num">{value}</div>'


def chip(text: str, color: str) -> str:
    """回傳一個彩色小標籤的 HTML（淡底色 + 深色字）。"""
    return f'<span class="chip" style="background:{color}1F;color:{color}">{html.escape(text)}</span>'


def donut(data: pd.DataFrame, label: str, value: str, center_text: str) -> alt.Chart:
    """甜甜圈圖：看每一塊占多少比例（持股占比、預算分配都用它）。

    center_text 是圓圈中間的字，例如總金額。
    """
    data = data.assign(順序=range(len(data)))  # 甜甜圈一塊一塊照資料順序畫
    base = alt.Chart(data).encode(
        theta=alt.Theta(f"{value}:Q", stack=True),
        # sort：圖例照資料原本的順序排，不要變成依筆畫排序
        color=alt.Color(f"{label}:N", sort=list(data[label]), scale=alt.Scale(range=CHART_COLORS),
                        legend=alt.Legend(title=None, orient="right", labelFontSize=13)),
        order=alt.Order("順序:Q"),
        tooltip=[alt.Tooltip(f"{label}:N"), alt.Tooltip(f"{value}:Q", format=",.0f")],
    )
    ring = base.mark_arc(innerRadius=62, outerRadius=100, stroke="#FFFFFF", strokeWidth=2)
    center = alt.Chart(pd.DataFrame({"t": [center_text]})).mark_text(
        fontSize=15, fontWeight=600, color="#1F2633"
    ).encode(text="t:N")
    return (ring + center).properties(height=230)


def show_chart(chart: alt.Chart) -> None:
    """顯示 Altair 圖表：背景透明、拿掉外框，讓圖表融入白色卡片。"""
    st.altair_chart(chart.properties(background="transparent").configure_view(stroke=None),
                    width="stretch")


def delete_button(key: str) -> bool:
    """列表裡每一列的刪除按鈕（低調的垃圾桶圖示）。"""
    return st.button("刪除", key=key, type="tertiary", icon=":material/delete:")


# ---------- 頁面：總覽 ----------

def page_overview() -> None:
    today = date.today()
    page_header("總覽", f"{today.year} 年 {today.month} 月 {today.day} 日・現金、投資、負債一次看完")

    settings = db.get_settings()
    cash = settings["cash_on_hand"]
    analyzed = analyze(db.get_holdings())
    total_value = sum(m["value"] for m in analyzed)
    total_profit = sum(m["profit"] for m in analyzed)
    debts = db.get_debts()
    total_debt = sum(d["remaining"] for d in debts)

    # --- 上排四張數字卡 ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("淨資產", money(cash + total_value - total_debt),
              help="手上現金 + 股票市值 − 負債餘額", border=True)
    c2.metric("手上現金", money(cash), border=True)
    # delta_color="inverse"：正數紅、負數綠，剛好是台股習慣
    c3.metric("股票市值", money(total_value),
              delta=signed_money(total_profit) if total_profit else None,
              delta_color="inverse", help="下面的小字是總損益", border=True)
    c4.metric("負債餘額", money(total_debt), border=True)

    # --- 提醒：持股集中度、本月當沖 ---
    for m in over_concentrated(analyzed):
        st.warning(
            f"{m['name']}（{m['symbol']}）占總市值 {m['weight']:.1%}，"
            f"超過 {CONCENTRATION_LIMIT:.0%}，風險過度集中", icon="⚠️"
        )
    day_trades = count_day_trades(db.get_trades(), today.year, today.month)
    if day_trades > 0:
        st.error(f"本月已經當沖 {day_trades} 次，請停下來檢討", icon="🚨")
    else:
        st.success("本月當沖 0 次，繼續保持", icon="👍")

    # --- 每月現金流 + 持股占比 ---
    income = settings["monthly_income"]
    fixed_total = sum(item["amount"] for item in db.get_fixed_expenses())
    debt_payment = total_debt_payment(debts)
    living = sum(db.get_budgets().values())
    savings = monthly_savings(income, fixed_total, debt_payment, living)

    left, right = st.columns([3, 2])
    with left, st.container(key="card_cashflow"):
        card_title("每月現金流", "收入都花到哪裡去")
        # 一條橫的長條，把收入切成四段；入不敷出時沒有「可存」那一段
        parts = pd.DataFrame({
            "項目": ["固定支出", "負債還款", "生活預算", "每月可存"],
            "金額": [fixed_total, debt_payment, living, max(savings, 0)],
            "順序": [1, 2, 3, 4],
        })
        bar = alt.Chart(parts).mark_bar(height=26, cornerRadius=4).encode(
            # 長條的總長度固定是「收入」，四段加起來剛好填滿
            x=alt.X("金額:Q", stack="zero", axis=None,
                    scale=alt.Scale(domain=[0, max(income, parts["金額"].sum(), 1)], nice=False)),
            color=alt.Color("項目:N", sort=list(parts["項目"]), legend=None,
                            scale=alt.Scale(range=["#6C8EBF", "#8A6FB0", "#B7B1A5", GOLD])),
            order="順序:Q",
            tooltip=["項目:N", alt.Tooltip("金額:Q", format=",.0f")],
        ).properties(height=44)
        show_chart(bar)
        ledger([
            ("", "收入", money(income)),
            ("#6C8EBF", "− 固定支出", money(fixed_total)),
            ("#8A6FB0", "− 負債還款", money(debt_payment)),
            ("#B7B1A5", "− 生活預算", money(living)),
            (GOLD, "= 每月可存", money(savings)),
        ])
        if savings < 0:
            st.error(f"每月入不敷出 {money(-savings)}")

    with right, st.container(key="card_weights"):
        card_title("持股占比", f"上限 {CONCENTRATION_LIMIT:.0%}")
        if analyzed:
            weights = pd.DataFrame({"股票": [m["name"] for m in analyzed],
                                    "市值": [m["value"] for m in analyzed]})
            show_chart(donut(weights, "股票", "市值", money(total_value)))
        else:
            st.info("還沒有持股")

    # --- 本月預算使用 ---
    month_expenses = db.get_expenses_in_month(today.year, today.month)
    budgets = db.get_budgets()
    spent = spent_by_category(month_expenses)
    with st.container(key="card_budget_overview"):
        card_title("本月預算", f"還能花 {money(remaining_this_month(budgets, month_expenses))}")
        cols = st.columns(2)
        for i, c in enumerate(CATEGORIES):
            with cols[i % 2]:
                budget_bar(f"{CATEGORY_ICONS.get(c, '')} {c}", spent[c], budgets.get(c, 0.0))


# ---------- 頁面：記帳 ----------

def page_expenses() -> None:
    today = date.today()
    page_header("記帳", "隨手記下每一筆花費，月底就知道錢去哪了")

    form_col, stat_col = st.columns([2, 3])

    with form_col, st.container(key="card_add_expense"):
        card_title("新增一筆")
        # st.form：把多個輸入框包在一起，按下送出才一次處理
        # clear_on_submit=True：送出後清空輸入框，方便記下一筆
        with st.form("add_expense", clear_on_submit=True, border=False):
            amount = st.number_input("金額", min_value=0.0, step=10.0, format="%.0f")
            category = st.selectbox("類別", CATEGORIES,
                                    format_func=lambda c: f"{CATEGORY_ICONS.get(c, '')} {c}")
            expense_date = st.date_input("日期", value=today)
            note = st.text_input("備註（可不填）")
            submitted = st.form_submit_button("新增", type="primary", icon=":material/add:")

        if submitted:
            if amount <= 0:
                st.error("金額要大於 0")
            else:
                # date 物件轉成 'YYYY-MM-DD' 字串存進資料庫
                db.add_expense(amount, category, expense_date.isoformat(), note)
                st.success(f"已記下：{category} {money(amount)}")

    # --- 本月統計 ---
    month_expenses = db.get_expenses_in_month(today.year, today.month)
    budgets = db.get_budgets()
    remaining = remaining_this_month(budgets, month_expenses)
    total_spent = sum(e["amount"] for e in month_expenses)

    with stat_col:
        m1, m2 = st.columns(2)
        if remaining >= 0:
            m1.metric("本月還能花", money(remaining), border=True)
        else:
            m1.metric("本月還能花", money(remaining), delta="已超支",
                      delta_color="inverse", border=True)
        m2.metric("本月已花", money(total_spent), border=True)

        with st.container(key="card_budget_bars"):
            card_title(f"{today.year} 年 {today.month} 月各類別")
            spent = spent_by_category(month_expenses)
            for c in CATEGORIES:
                budget_bar(f"{CATEGORY_ICONS.get(c, '')} {c}", spent[c], budgets.get(c, 0.0))

    # --- 本月明細 ---
    with st.container(key="card_expense_list"):
        card_title("本月明細", f"共 {len(month_expenses)} 筆")
        if not month_expenses:
            st.info("本月還沒有記帳")
            return

        widths = [2, 2, 2, 4, 1]  # st.columns 的寬度比例，表頭和每一列共用
        for col, text in zip(st.columns(widths), ["日期", "類別", "金額", "備註", ""]):
            col.caption(text)
        for e in month_expenses:
            col1, col2, col3, col4, col5 = st.columns(widths, vertical_alignment="center")
            col1.write(e["date"])
            col2.write(f"{CATEGORY_ICONS.get(e['category'], '')} {e['category']}")
            col3.write(f"**{money(e['amount'])}**")
            col4.write(e["note"] or "")
            # 每個按鈕需要唯一的 key，所以用支出的 id
            with col5:
                if delete_button(f"del_exp_{e['id']}"):
                    db.delete_expense(e["id"])
                    st.rerun()  # 立刻重跑，讓畫面更新


# ---------- 頁面：每月生活預算 ----------

def page_budgets() -> None:
    page_header("每月生活預算", "先決定每個類別最多花多少，記帳頁會幫你追蹤進度")
    budgets = db.get_budgets()

    form_col, chart_col = st.columns([3, 2])
    with form_col, st.container(key="card_budget_form"):
        card_title("設定預算")
        with st.form("budgets", border=False):
            new_budgets = {}
            cols = st.columns(2)
            for i, c in enumerate(CATEGORIES):
                new_budgets[c] = cols[i % 2].number_input(
                    f"{CATEGORY_ICONS.get(c, '')} {c}", min_value=0.0, step=100.0, format="%.0f",
                    value=float(budgets.get(c, 0.0))
                )
            if st.form_submit_button("儲存", type="primary", icon=":material/save:"):
                db.save_budgets(new_budgets)
                st.success("預算已儲存")

    total = sum(new_budgets.values())
    with chart_col:
        st.metric("每月生活預算合計", money(total), border=True)
        with st.container(key="card_budget_split"):
            card_title("預算分配")
            if total > 0:
                split = pd.DataFrame({"類別": list(new_budgets.keys()),
                                      "金額": list(new_budgets.values())})
                show_chart(donut(split, "類別", "金額", money(total)))
            else:
                st.info("還沒有設定預算")


# ---------- 頁面：固定支出 ----------

def page_fixed() -> None:
    page_header("固定支出", "每個月一定會扣的錢：電話費、訂閱、保險……")

    form_col, list_col = st.columns([2, 3])
    with form_col, st.container(key="card_add_fixed"):
        card_title("新增固定支出")
        with st.form("add_fixed", clear_on_submit=True, border=False):
            name = st.text_input("名稱（例如 電話費、iCloud）")
            amount = st.number_input("每月金額", min_value=0.0, step=10.0, format="%.0f")
            if st.form_submit_button("新增", type="primary", icon=":material/add:"):
                if not name.strip():
                    st.error("請輸入名稱")
                elif amount <= 0:
                    st.error("金額要大於 0")
                else:
                    db.add_fixed_expense(name.strip(), amount)
                    st.success(f"已新增：{name}")

    items = db.get_fixed_expenses()
    with list_col:
        total = sum(item["amount"] for item in items)
        m1, m2 = st.columns(2)
        m1.metric("固定支出合計 / 月", money(total), border=True)
        m2.metric("一年下來", money(total * 12), border=True)

        with st.container(key="card_fixed_list"):
            card_title("項目", f"共 {len(items)} 項")
            if not items:
                st.info("還沒有固定支出")
                return
            for item in items:
                col1, col2, col3 = st.columns([4, 2, 1], vertical_alignment="center")
                col1.write(item["name"])
                col2.write(f"**{money(item['amount'])}**")
                with col3:
                    if delete_button(f"del_fixed_{item['id']}"):
                        db.delete_fixed_expense(item["id"])
                        st.rerun()


# ---------- 頁面：負債 ----------

def page_debts() -> None:
    page_header("負債追蹤", "每還一期按一下，看著餘額慢慢變少")

    debts = db.get_debts()
    cash = db.get_settings()["cash_on_hand"]
    m1, m2, m3 = st.columns(3)
    m1.metric("負債餘額", money(sum(d["remaining"] for d in debts)), border=True)
    m2.metric("每月還款", money(total_debt_payment(debts)), border=True)
    m3.metric("手上現金", money(cash), help="按「已還一期」會從這裡扣", border=True)

    list_col, form_col = st.columns([3, 2])

    with form_col, st.container(key="card_add_debt"):
        card_title("新增負債")
        with st.form("add_debt", clear_on_submit=True, border=False):
            name = st.text_input("名稱（例如 學貸、信用卡分期）")
            remaining = st.number_input("剩餘金額", min_value=0.0, step=1000.0, format="%.0f")
            monthly = st.number_input("每月還款", min_value=0.0, step=100.0, format="%.0f")
            if st.form_submit_button("新增", type="primary", icon=":material/add:"):
                if not name.strip():
                    st.error("請輸入名稱")
                elif remaining <= 0 or monthly <= 0:
                    st.error("剩餘金額和每月還款都要大於 0")
                else:
                    db.add_debt(name.strip(), remaining, monthly)
                    st.success(f"已新增：{name}")
                    st.rerun()  # 讓左邊的清單和上面的數字卡馬上更新

    with list_col:
        if not debts:
            st.info("沒有負債 🎉")
            return

        today = date.today()
        for d in debts:
            with st.container(key=f"card_debt_{d['id']}"):
                ym = payoff_month(d["remaining"], d["monthly_payment"], today)
                if ym is None:
                    status = chip("已還清", GOLD)
                else:
                    n = months_left(d["remaining"], d["monthly_payment"])
                    status = chip(f"還剩 {n} 期・預計 {ym[0]} 年 {ym[1]} 月還清", INK)
                # 名稱是自己輸入的，用 html.escape 把 < > & 換成安全的寫法，避免畫面壞掉
                st.markdown(f'<div class="card-title">{html.escape(d["name"])}　{status}</div>',
                            unsafe_allow_html=True)
                col1, col2 = st.columns(2)
                col1.markdown(big_number("剩餘金額", money(d["remaining"])), unsafe_allow_html=True)
                col2.markdown(big_number("每月還款", money(d["monthly_payment"])), unsafe_allow_html=True)

                b1, b2 = st.columns([3, 1])
                if ym is not None:
                    pay = payment_this_period(d["remaining"], d["monthly_payment"])
                    if b1.button(f"已還一期（{money(pay)}）", key=f"pay_{d['id']}",
                                 type="primary", icon=":material/check:"):
                        try:
                            db.pay_debt_installment(d["id"])
                            st.rerun()
                        except ValueError as e:  # 現金不夠時，db 會丟出 ValueError
                            st.error(str(e))
                with b2:
                    if delete_button(f"del_debt_{d['id']}"):
                        db.delete_debt(d["id"])
                        st.rerun()


# ---------- 頁面：持股 ----------

def page_stocks() -> None:
    page_header("持股管理", "不同帳戶的同一檔股票會自動合併計算")

    holdings = db.get_holdings()
    analyzed = analyze(holdings)

    if analyzed:
        total_value = sum(m["value"] for m in analyzed)
        total_profit = sum(m["profit"] for m in analyzed)
        cost = total_value - total_profit
        m1, m2, m3 = st.columns(3)
        m1.metric("總市值", money(total_value), border=True)
        # delta_color="inverse"：正數紅、負數綠（台股習慣）
        m2.metric("總損益", signed_money(total_profit),
                  delta=f"{total_profit / cost:+.2%}" if cost > 0 else None,
                  delta_color="inverse", border=True)
        m3.metric("持有檔數", f"{len(analyzed)} 檔", border=True)

        with st.container(key="card_holdings"):
            card_title("持股總覽", "同代號已合併")
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
                # 沒虧損時是 None，先轉成字串，空字串在表格裡就是空白
                "回本價": "" if m["breakeven"] is None else f"{m['breakeven']:,.2f}",
                "還要漲%": "" if m["rise_needed"] is None else f"{m['rise_needed']:.2f}",
            } for m in analyzed])

            # Styler：幫表格上色、設定數字格式
            styled = (
                table.style
                .map(profit_color, subset=["損益", "報酬率%"])
                .format({
                    "股數": "{:,.0f}", "均價": "{:,.2f}", "現價": "{:,.2f}",
                    "市值": "{:,.0f}", "損益": "{:+,.0f}", "報酬率%": "{:+.2f}",
                    "占比%": "{:.1f}",
                })
            )
            st.dataframe(styled, hide_index=True)
            for m in over_concentrated(analyzed):
                st.warning(f"{m['name']} 占 {m['weight']:.1%}，超過 {CONCENTRATION_LIMIT:.0%}", icon="⚠️")

    chart_col, side_col = st.columns([3, 2])
    if analyzed:
        with chart_col, st.container(key="card_stock_weights"):
            card_title("持股占比", f"單一個股上限 {CONCENTRATION_LIMIT:.0%}")
            weights = pd.DataFrame({"股票": [m["name"] for m in analyzed],
                                    "市值": [m["value"] for m in analyzed]})
            show_chart(donut(weights, "股票", "市值", money(total_value)))

    with st.container(key="card_add_holding"):
        card_title("新增持股")
        with st.form("add_holding", clear_on_submit=True, border=False):
            col1, col2, col3 = st.columns(3)
            name = col1.text_input("名稱（例如 台積電）")
            symbol = col2.text_input("代號（例如 2330）")
            account = col3.text_input("帳戶（例如 富邦）")
            col4, col5, col6 = st.columns(3)
            shares = col4.number_input("股數", min_value=0.0, step=1.0)
            avg_price = col5.number_input("均價", min_value=0.0, step=0.1)
            price = col6.number_input("現價", min_value=0.0, step=0.1)
            if st.form_submit_button("新增", type="primary", icon=":material/add:"):
                if not (name.strip() and symbol.strip() and account.strip()):
                    st.error("名稱、代號、帳戶都要填")
                elif shares <= 0 or avg_price <= 0 or price <= 0:
                    st.error("股數、均價、現價都要大於 0")
                else:
                    db.add_holding(name.strip(), symbol.strip(), account.strip(),
                                   shares, avg_price, price)
                    st.success(f"已新增：{name} {account}")
                    st.rerun()  # 讓上面的總覽表馬上更新

    if not holdings:
        st.info("還沒有持股")
        return

    # --- 更新現價 ---
    with side_col, st.container(key="card_update_price"):
        card_title("更新現價")
        with st.form("update_price", border=False):
            symbols = [m["symbol"] for m in analyzed]
            sym = st.selectbox("代號", symbols,
                               format_func=lambda s: f"{s} {next(m['name'] for m in analyzed if m['symbol'] == s)}")
            new_price = st.number_input("新的現價", min_value=0.0, step=0.1)
            if st.form_submit_button("更新", type="primary", icon=":material/sync:"):
                if new_price <= 0:
                    st.error("現價要大於 0")
                else:
                    db.update_price(sym, new_price)
                    st.rerun()

    # --- 各帳戶明細（可刪除）---
    with st.container(key="card_holding_list"):
        card_title("各帳戶明細", "刪除的是單一帳戶裡的那一筆")
        widths = [3, 2, 3, 1]
        for col, text in zip(st.columns(widths), ["股票", "帳戶", "股數與均價", ""]):
            col.caption(text)
        for h in holdings:
            col1, col2, col3, col4 = st.columns(widths, vertical_alignment="center")
            col1.write(f"**{h['name']}**（{h['symbol']}）")
            col2.write(h["account"])
            col3.write(f"{h['shares']:,.0f} 股 @ {h['avg_price']:,.2f}")
            with col4:
                if delete_button(f"del_hold_{h['id']}"):
                    db.delete_holding(h["id"])
                    st.rerun()


# ---------- 頁面：下單前檢查 ----------

def page_precheck() -> None:
    page_header("下單前檢查", "按下買進之前，先誠實回答這幾題")
    settings = db.get_settings()
    cash = settings["cash_on_hand"]

    # 先排好上排三張數字卡的位置，等下面算出金額再填進去
    m1, m2, m3 = st.columns(3)
    left, right = st.columns([3, 2])

    with left, st.container(key="card_precheck_form"):
        card_title("這筆交易")
        col1, col2 = st.columns(2)
        price = col1.number_input("股價", min_value=0.0, step=0.5)
        shares = col2.number_input("股數", min_value=0, step=1000)  # 台股一張 = 1000 股
        amount = price * shares

        card_title("每一項都要誠實打勾")
        # 用 dict 推導式一次建立五個勾選框，key 讓 Streamlit 分得出每一個
        checked = {item: st.checkbox(item, key=f"chk_{i}") for i, item in enumerate(CHECK_ITEMS)}

    ok, reasons = check_order(amount, cash, checked)

    m1.metric("這筆要花", money(amount), border=True)
    m2.metric("手上現金", money(cash), border=True)
    m3.metric("買完還剩", money(cash - amount), border=True)

    with right:
        if ok:
            st.success("**可以下單**", icon="✅")
        else:
            # 用 markdown 的清單列出所有原因
            st.error("**先不要下單**\n\n" + "\n".join(f"- {r}" for r in reasons), icon="⛔")

        # 參考資訊：幫你確認打勾的內容是不是真的
        with st.container(key="card_precheck_ref"):
            card_title("參考資訊")
            fund, target = settings["emergency_fund"], settings["emergency_target"]
            status = chip("還沒存滿", WARN) if fund < target else chip("已存滿", INK)
            st.markdown(f"緊急預備金 {money(fund)} / {money(target)}　{status}",
                        unsafe_allow_html=True)
            losing = [f"{m['name']}（{m['symbol']}）"
                      for m in analyze(db.get_holdings()) if m["profit"] < 0]
            st.markdown("虧損中的個股：" + ("、".join(losing) if losing else "沒有"))


# ---------- 頁面：交易紀錄 ----------

def page_trades() -> None:
    page_header("交易紀錄", "記下每一筆買賣，也記下當下的想法")

    trades = db.get_trades()
    today = date.today()
    m1, m2, m3 = st.columns(3)
    pnl_sum = total_pnl(trades)
    m1.metric("累計損益", signed_money(pnl_sum), border=True)
    m2.metric("交易筆數", f"{len(trades)} 筆", border=True)
    m3.metric("本月當沖", f"{count_day_trades(trades, today.year, today.month)} 次",
              help="當沖次數越少越好", border=True)

    with st.expander("新增交易紀錄", icon=":material/add:", expanded=not trades):
        with st.form("add_trade", clear_on_submit=True, border=False):
            col1, col2, col3 = st.columns(3)
            trade_date = col1.date_input("日期", value=today)
            symbol = col2.text_input("標的（例如 2330 台積電）")
            trade_type = col3.selectbox("類型", TRADE_TYPES)
            pnl = st.number_input("損益（賺填正數、賠填負數，買進填 0）", step=100.0)
            note = st.text_input("備註（可不填）")
            if st.form_submit_button("新增", type="primary", icon=":material/add:"):
                if not symbol.strip():
                    st.error("請輸入標的")
                else:
                    db.add_trade(trade_date.isoformat(), symbol.strip(), trade_type, pnl, note)
                    st.success("已新增交易紀錄")
                    st.rerun()

    if not trades:
        st.info("還沒有交易紀錄")
        return

    with st.container(key="card_trade_list"):
        card_title("全部紀錄")
        widths = [2, 2.5, 1.2, 2, 3, 1]
        for col, text in zip(st.columns(widths), ["日期", "標的", "類型", "損益", "備註", ""]):
            col.caption(text)
        # 類型標籤的顏色：當沖用橘色提醒自己，其他用墨藍和灰
        type_colors = {"當沖": WARN, "買進": INK, "賣出": "#6B7280"}
        for t in trades:
            col1, col2, col3, col4, col5, col6 = st.columns(widths, vertical_alignment="center")
            col1.write(t["date"])
            col2.write(t["symbol"])
            col3.markdown(chip(t["type"], type_colors.get(t["type"], MUTED)),
                          unsafe_allow_html=True)
            col4.markdown(colored_money(t["pnl"]))
            col5.write(t["note"] or "")
            with col6:
                if delete_button(f"del_trade_{t['id']}"):
                    db.delete_trade(t["id"])
                    st.rerun()


# ---------- 頁面：定期定額試算 ----------

def page_dca() -> None:
    page_header("定期定額試算", "每個月固定投入，時間拉長後會變多少？")

    # 先排好上排三張數字卡的位置，等算出結果再填進去
    c1, c2, c3 = st.columns(3)
    input_col, result_col = st.columns([1, 2.4])

    with input_col, st.container(key="card_dca_input"):
        card_title("試算條件")
        initial = st.number_input("現有投資", min_value=0.0, step=10000.0, value=100000.0, format="%.0f")
        monthly = st.number_input("每月投入", min_value=0.0, step=1000.0, value=5000.0, format="%.0f")
        rate_pct = st.number_input("年報酬率（%）", min_value=-50.0, max_value=50.0,
                                   step=0.5, value=6.0)
        years = st.number_input("年數", min_value=1, max_value=60, step=1, value=20)

    values = project(initial, monthly, rate_pct / 100, int(years))
    final = values[-1]
    invested = initial + monthly * 12 * years  # 自己總共投入的本金

    c1.metric("最後總額", money(final), border=True)
    c2.metric("投入本金", money(invested),
              delta=f"賺 {money(final - invested)}" if final > invested else None,
              delta_color="inverse", border=True)
    c3.metric("4% 法則每月可領", money(monthly_withdrawal(final)), border=True)

    with result_col:
        with st.container(key="card_dca_chart"):
            card_title("資產成長", "金色是複利多出來的部分")
            # 每一年的「資產」和「本金」放在同一張表，畫成兩層
            chart_data = pd.DataFrame({
                "第幾年": range(len(values)),
                "資產": values,
                "本金": [initial + monthly * 12 * y for y in range(len(values))],
            })
            x = alt.X("第幾年:Q", axis=alt.Axis(tickMinStep=1, title="第幾年", grid=False))
            # 縱軸用「萬」當單位，比 1M、2M 好讀
            y_axis = alt.Axis(title=None, labelExpr="format(datum.value / 10000, ',') + ' 萬'")
            total_area = alt.Chart(chart_data).mark_area(
                color=GOLD, opacity=0.35, line={"color": GOLD, "strokeWidth": 2}
            ).encode(x=x, y=alt.Y("資產:Q", axis=y_axis),
                     tooltip=["第幾年:Q", alt.Tooltip("資產:Q", format=",.0f"),
                              alt.Tooltip("本金:Q", format=",.0f")])
            principal_area = alt.Chart(chart_data).mark_area(
                color=INK, opacity=0.85
            ).encode(x=x, y="本金:Q")
            show_chart((total_area + principal_area).properties(height=320))
            st.caption("假設每月月底投入、年報酬率固定不變。實際報酬每年都會波動，這只是估算。")


# ---------- 頁面：設定 ----------

def page_settings() -> None:
    page_header("設定", "收入、現金和緊急預備金，其他頁面的計算都會用到")
    s = db.get_settings()

    form_col, side_col = st.columns([3, 2])

    with form_col, st.container(key="card_settings_form"):
        card_title("基本資料")
        with st.form("settings", border=False):
            col1, col2 = st.columns(2)
            income = col1.number_input("每月收入", min_value=0.0, step=1000.0, format="%.0f",
                                       value=float(s["monthly_income"]))
            cash = col2.number_input("手上現金", min_value=0.0, step=100.0, format="%.0f",
                                     value=float(s["cash_on_hand"]))
            fund = col1.number_input("緊急預備金（目前存了多少）", min_value=0.0, step=100.0, format="%.0f",
                                     value=float(s["emergency_fund"]))
            target = col2.number_input("預備金目標", min_value=0.0, step=1000.0, format="%.0f",
                                       value=float(s["emergency_target"]))
            if st.form_submit_button("儲存", type="primary", icon=":material/save:"):
                db.save_settings({
                    "monthly_income": income,
                    "cash_on_hand": cash,
                    "emergency_fund": fund,
                    "emergency_target": target,
                })
                st.success("設定已儲存")

    with side_col:
        # 預備金進度
        if target > 0:
            with st.container(key="card_emergency"):
                card_title("緊急預備金進度")
                note = "已存滿 🎉" if fund >= target else f"還差 {money(target - fund)}・已存 {fund / target:.0%}"
                progress_bar("🛟 預備金", fund, target, INK, note)

        # --- 匯出備份 ---
        with st.container(key="card_backup"):
            card_title("匯出 CSV 備份")
            st.write("把所有資料表各存成一個 CSV，打包成 zip 下載。可以用 Excel 打開。")
            # st.download_button：按下去瀏覽器就會下載檔案，檔案內容是 data 參數
            st.download_button(
                "下載備份",
                data=db.export_csv_zip(),
                file_name=f"finance-backup-{date.today().isoformat()}.zip",
                mime="application/zip",
                icon=":material/download:",
            )
            st.caption("備份檔裡是你的真實資料，請不要放進專案資料夾或上傳到 GitHub。")
            st.caption(f"資料庫檔案位置：{os.path.abspath(db.DB_PATH)}")


# ---------- 側邊欄：導覽 ----------

def sidebar_summary() -> None:
    """側邊欄下方的小摘要：本月還能花多少、每月可存多少。"""
    today = date.today()
    budgets = db.get_budgets()
    month_expenses = db.get_expenses_in_month(today.year, today.month)
    remaining = remaining_this_month(budgets, month_expenses)
    settings = db.get_settings()
    savings = monthly_savings(
        settings["monthly_income"],
        sum(item["amount"] for item in db.get_fixed_expenses()),
        total_debt_payment(db.get_debts()),
        sum(budgets.values()),
    )
    st.sidebar.markdown(f"""
<div class="side-sum">
  <div><span>本月還能花</span><b>{money(remaining)}</b></div>
  <div><span>每月可存</span><b>{money(savings)}</b></div>
</div>""", unsafe_allow_html=True)


# ---------- 主程式：組出導覽、畫側邊欄、執行選到的頁面 ----------

# 頁面分組：(群組名稱, [(函式, 標題, 圖示, 網址), ...])
# 圖示用 Google Material Symbols，名稱可以在 https://fonts.google.com/icons 查
NAV = [
    ("日常", [
        (page_overview, "總覽", ":material/space_dashboard:", "overview"),
        (page_expenses, "記帳", ":material/edit_note:", "expenses"),
        (page_budgets, "每月預算", ":material/pie_chart:", "budgets"),
        (page_fixed, "固定支出", ":material/event_repeat:", "fixed"),
        (page_debts, "負債", ":material/credit_card:", "debts"),
    ]),
    ("投資", [
        (page_stocks, "持股", ":material/candlestick_chart:", "stocks"),
        (page_precheck, "下單前檢查", ":material/fact_check:", "precheck"),
        (page_trades, "交易紀錄", ":material/receipt_long:", "trades"),
        (page_dca, "定期定額試算", ":material/trending_up:", "dca"),
    ]),
    ("其他", [
        (page_settings, "設定", ":material/settings:", "settings"),
    ]),
]

inject_css()

# st.navigation 負責「現在在哪一頁」，position="hidden" 表示側邊欄由我們自己畫
pages = {}
for group, items in NAV:
    # 總覽是預設頁，網址固定是「/」，所以不另外設 url_path
    pages[group] = [st.Page(func, title=title, icon=icon,
                            url_path=None if url == "overview" else url,
                            default=(url == "overview"))
                    for func, title, icon, url in items]
current = st.navigation(pages, position="hidden")

with st.sidebar:
    st.markdown('<div class="brand">💰 個人理財</div>'
                '<div class="brand-sub">本機執行・資料只存在你的電腦</div>',
                unsafe_allow_html=True)
    for group, group_pages in pages.items():
        st.markdown(f'<div class="nav-group">{group}</div>', unsafe_allow_html=True)
        for p in group_pages:
            st.page_link(p, width="stretch")
sidebar_summary()

current.run()  # 執行被選中的頁面函式
