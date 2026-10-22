"""
OniPulsar 星脈流轉（原名「個人理財」）：Streamlit 主程式。

執行方式：streamlit run app.py

Streamlit 的運作方式和一般程式不太一樣：
每次你在網頁上按按鈕或改數字，整個 app.py 會「從頭到尾重新跑一次」。
所以資料都要存在資料庫裡，每次重跑時再讀出來。

外觀的設計概念是「存摺」：淡青灰的紙、墨色的字、金額用宋體，明細一列一列用橫線隔開。
外觀分成兩層：
- .streamlit/config.toml：整體配色、字型、圓角（Streamlit 內建的主題設定）
- 這個檔案的 inject_css()：少量 CSS，做存摺式明細、摘要列、總覽的結餘、手機版面這些主題設定做不到的部分

檔案由上到下：配色與 CSS → 共用小工具 → 各頁面函式 → 側邊欄 → 主程式
"""

import html
import os
import re
import time
from datetime import date, datetime

import altair as alt  # 安裝 streamlit 時會一起裝好，用來畫圖表
import pandas as pd  # 安裝 streamlit 時會一起裝好，用來顯示表格
import streamlit as st

import db
import quotes
import update_check
from models.budget import (
    CATEGORIES,
    category_options,
    join_option,
    split_option,
    last_n_months,
    monthly_totals,
    remaining_this_month,
    spent_by_category,
)
from models.cashflow import monthly_savings, total_debt_payment
from models.debt import months_left, paid_in_month, payment_this_period, payoff_month
from models.dca import monthly_withdrawal, project
from models.precheck import CHECK_ITEMS, check_order
from models.quotes import is_trading_time
from version import APP_VERSION
from models.stocks import CONCENTRATION_LIMIT, analyze, over_concentrated
from models.trades import TRADE_TYPES, count_day_trades, total_pnl

# 頁面基本設定（必須是第一個 st. 指令）
st.set_page_config(page_title="OniPulsar 星脈流轉", page_icon="💰", layout="wide")

# 確保資料表存在
db.init_db()

# 每天第一次打開時自動備份一份（見 db.auto_backup）。
# 只在這個瀏覽器分頁第一次執行時做：Streamlit 每次互動都會重跑整個檔案，不用每次都檢查。
# 備份失敗（例如硬碟滿了）不應該讓整個程式打不開，所以出錯就記下來、在設定頁顯示
if "backup_checked" not in st.session_state:
    st.session_state["backup_checked"] = True
    try:
        db.auto_backup()
    except OSError as e:
        st.session_state["backup_error"] = str(e)


# ---------- 配色 ----------
# 和 .streamlit/config.toml 用同一組顏色，圖表和自訂 HTML 才會一致

TEXT = "#1C2833"     # 文字：墨色
PAPER = "#FAFBF9"    # 卡片底色：比頁面的存摺紙（#EDF1EE）亮一點
INK = "#2B4C7E"      # 主色：墨藍
GOLD = "#C9973F"     # 強調色：金色（存下來的錢、快用完的預算），用在進度條和圖表
GOLD_TEXT = "#7E5B1C"  # 金色當「小字」用時的深色版（原本的金色在淡底上對比只有約 2.3:1，看不清楚）
# 賺錢紅、賠錢綠（台股習慣）。這兩個顏色主要用在小字上，所以調得比較深：
# 在存摺紙底色上對比分別約 4.9:1、4.7:1（一般建議小字至少 4.5:1）
GAIN = "#B83B3B"
LOSS = "#147A53"
# 超支、先不要下單：橘。刻意不用紅色，避免和「賺錢紅」搞混。
# 這個橘色也用在小字上，所以調得比較深：對存摺紙底色約 5.1:1、對卡片底色約 5.6:1
WARN = "#A04E17"
MUTED = "#5F6672"    # 次要文字：灰（對存摺紙底色約 5:1）
CHART_COLORS = ["#2B4C7E", "#C9973F", "#6C8EBF", "#8A6FB0", "#4F9A94", "#B7B1A5"]

# 每個記帳類別一個顏色，和「預算分配」圓餅圖用同一組，看圖就知道哪一塊是哪個類別。
# 刻意不用墨藍和金色：這兩個顏色在預算進度條上代表「正常」和「快用完」，避免同一個顏色有兩種意思；
# 也不用紅、綠：這兩個顏色留給漲跌。原本四個類別的顏色不變，新加的五個用柔和的顏色
CATEGORY_COLORS = {
    "吃飯": "#6C8EBF", "交通": "#4F9A94", "購物": "#B07AA1", "居家": "#7D8A9E", "娛樂": "#5FA8C9",
    "約會禮物": "#8A6FB0", "醫療保健": "#9C8F6E", "學習": "#7E8FC4", "其他": "#B7B1A5",
}

# 金額用的字型：宋體。思源宋體由 config.toml 的 headingFont 載入；
# 沒網路時依序改用 Windows 的新細明體、Mac 的宋體
SERIF = '"Noto Serif TC", PMingLiU, "Songti TC", serif'


def inject_css() -> None:
    """插入少量自訂 CSS。

    st.container(key="card_xxx") 會在 HTML 加上 class「st-key-card_xxx」，
    所以下面用 [class*="st-key-card"] 就能選到所有「卡片」，不用依賴 Streamlit 內部的結構。
    """
    # 用 f-string 是為了把上面的顏色常數放進 CSS；CSS 本身的大括號要寫兩個 {{ }} 才不會被當成變數
    st.markdown(f"""
<style>
/* 內容區最大寬度，大螢幕上不會拉得太開 */
.block-container {{ max-width: 1240px; padding-top: 2.2rem; padding-bottom: 3rem; }}
header[data-testid="stHeader"] {{ background: transparent; }}

/* 金額一律用宋體，像印在存摺上的數字；tabular-nums 讓每個數字一樣寬，上下才對得齊 */
div[data-testid="stMetricValue"], .hero-num, .big-num,
.ledger-row > div:last-child, section[data-testid="stSidebar"] .side-sum b {{
    font-family: {SERIF}; font-variant-numeric: tabular-nums;
}}

/* 自訂卡片：平的，不加陰影，只用一條細框線，像存摺裡的一頁 */
[class*="st-key-card"] {{ background: {PAPER}; border: 1px solid #CCD6CF; border-radius: 8px;
                          padding: 20px 22px; }}

/* 摘要列（一排數字）：上面一條墨色粗線、下面一條細線，格子之間用直線隔開，
   取代一張一張分開的數字卡。summary_strip() 建出來的容器 key 都以 strip_ 開頭 */
[class*="st-key-strip"] {{ border-top: 2px solid {TEXT}; border-bottom: 1px solid #CCD6CF;
                           margin-bottom: .4rem; }}
[class*="st-key-strip"] div[data-testid="stHorizontalBlock"] {{ gap: 0; }}
[class*="st-key-strip"] div[data-testid="stMetric"] {{ padding: 12px 20px 14px; }}
[class*="st-key-strip"] div[data-testid="stColumn"]:first-child div[data-testid="stMetric"] {{ padding-left: 0; }}
/* 格子之間的直線畫在「欄」上而不是數字上：同一排的欄一樣高，
   某一格多一行小字（例如報酬率）時，直線也不會一長一短 */
[class*="st-key-strip"] div[data-testid="stColumn"] + div[data-testid="stColumn"] {{
    border-left: 1px solid #CCD6CF;
}}
div[data-testid="stMetricLabel"] p {{ color: {MUTED}; font-size: .9rem; }}

/* 頁首：宋體大標題 + 一行說明 */
.page-head {{ margin-bottom: 1.2rem; }}
/* 字型在這裡再寫一次：config.toml 的 headingFont 只能寫一個字型，沒網路時要靠這裡的新細明體等備援 */
.page-head h1 {{ font-family: {SERIF}; font-size: 2.1rem; margin: 0; padding: 0; letter-spacing: .04em; }}
.page-head p {{ color: {MUTED}; margin: .3rem 0 0; }}

/* 卡片內的小標題 */
.card-title {{ font-weight: 700; font-size: 1.05rem; margin: 0 0 .6rem; color: {TEXT}; }}
.card-title span {{ color: {MUTED}; font-weight: 400; font-size: .85rem; margin-left: .4rem; }}

/* 類別、項目前面的小圓點 */
.dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%;
        margin-right: 8px; vertical-align: 1px; }}

/* 存摺式明細：左邊項目、右邊金額，每列一條細橫線。
   合計那一列上面畫「雙線」：這是會計帳本上表示「以下是合計」的寫法 */
.ledger {{ width: 100%; }}
.ledger-row {{ display: flex; justify-content: space-between; gap: 1rem; padding: 7px 0;
               border-bottom: 1px solid #DCE3DE; }}
.ledger-row.total {{ border-bottom: none; border-top: 3px double {TEXT};
                     margin-top: 2px; font-weight: 700; font-size: 1.05rem; }}
.ledger-row .sub {{ font-size: .82rem; margin-left: .5rem; }}
/* 金額不要斷行（「100,000 元」被拆成兩行很難讀）；窄的時候讓左邊的項目名稱去縮 */
.ledger-row > div:first-child {{ min-width: 0; }}
.ledger-row > div:last-child {{ white-space: nowrap; }}

/* 總覽的結餘：整個 app 唯一的「主角」。不放在卡片裡，直接印在存摺紙上 */
/* 左欄寬度跟著數字走（auto），數字一定不斷行：「1,234,56 / 7 元」這種斷法會讓人讀錯金額。
   字級用 clamp()：視窗窄時自動縮小，最小 2.4rem、最大 3.6rem */
.hero {{ display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 3rem;
         align-items: end; border-top: 2px solid {TEXT}; padding: 1rem 0 .4rem; }}
.hero-label {{ color: {MUTED}; }}
.hero-num {{ font-size: clamp(2.4rem, 4.2vw, 3.6rem); font-weight: 700; line-height: 1.1; color: {TEXT};
             white-space: nowrap; }}
.hero-num small {{ font-size: 1.2rem; font-weight: 600; margin-left: .4rem; color: {MUTED}; }}
.hero-note {{ font-size: .85rem; color: {MUTED}; margin-top: .3rem; }}

/* 第一次使用的歡迎畫面 */
.welcome-why {{ color: {MUTED}; line-height: 1.8; padding-bottom: .4rem; }}
.step-num {{ font-family: {SERIF}; font-size: 2rem; font-weight: 900; color: {GOLD}; line-height: 1; margin-bottom: .5rem; }}
.step-text {{ color: {MUTED}; font-size: .92rem; min-height: 2.8em; }}

/* 記帳趨勢下面的小字說明 */
.trend-note {{ font-size: .85rem; color: {MUTED}; }}

/* 自律提醒：存摺的「摘要」欄，左邊兩個字的標籤、右邊一句說明 */
.notices {{ margin: .2rem 0 1.2rem; }}
.notice {{ display: flex; gap: 1rem; padding: 8px 0; border-bottom: 1px solid #CCD6CF; }}
.notice b {{ flex: 0 0 auto; min-width: 2.5em; }}

/* 下單前檢查的結論：大大的一句判斷，旁邊列原因 */
.verdict {{ display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2.5rem; align-items: start;
            border-top: 2px solid {TEXT}; border-bottom: 1px solid #CCD6CF; padding: 1rem 0 1.1rem;
            margin-bottom: 1.2rem; }}
.verdict-word {{ font-family: {SERIF}; font-size: 2.6rem; font-weight: 900; line-height: 1.15;
                 white-space: nowrap; color: var(--tone); }}
.verdict ul {{ margin: .3rem 0 0; padding-left: 1.1rem; }}
.verdict li {{ margin: .1rem 0; }}
.verdict p {{ margin: .6rem 0 0; }}

/* 預算進度條 */
.budget {{ margin: 4px 0 14px; }}
.budget-top {{ display: flex; justify-content: space-between; font-size: .92rem;
               font-variant-numeric: tabular-nums; }}
.budget-top b {{ font-weight: 600; }}
.budget-track {{ height: 10px; background: #E1E8E3; border-radius: 99px; margin: 6px 0 3px; overflow: hidden; }}
.budget-fill {{ height: 100%; border-radius: 99px; }}
.budget-note {{ font-size: .8rem; color: {MUTED}; }}

/* 卡片裡的大數字（例如負債的剩餘金額） */
.big-label {{ font-size: .85rem; color: {MUTED}; }}
.big-num {{ font-size: 1.55rem; font-weight: 600; margin-bottom: .6rem; }}

/* 小標籤（例如「當沖」「已還清」） */
.chip {{ display: inline-block; white-space: nowrap; padding: 1px 10px; border-radius: 99px; font-size: .8rem;
         font-weight: 600; line-height: 1.6; }}

/* 側邊欄：深色的存摺封面 */
section[data-testid="stSidebar"] .brand {{ font-family: {SERIF}; font-size: 1.4rem; font-weight: 900;
    letter-spacing: .08em; margin: 0 0 2px; }}
section[data-testid="stSidebar"] .brand-sub {{ font-size: .8rem; opacity: .75; margin-bottom: 1rem; }}
section[data-testid="stSidebar"] .nav-group {{ font-size: .75rem; letter-spacing: .12em;
    opacity: .75; margin: 1rem 0 .2rem .2rem; }}
section[data-testid="stSidebar"] .side-sum {{ border-top: 1px solid rgba(255,255,255,.25);
    padding: 10px 2px 0; margin-top: 1.2rem; }}
section[data-testid="stSidebar"] .side-sum div {{ display: flex; justify-content: space-between;
    font-size: .85rem; padding: 3px 0; }}
section[data-testid="stSidebar"] .side-sum span {{ opacity: .8; }}

/* 列表裡的刪除按鈕：平常淡淡的，滑過才變橘色（紅色留給漲跌） */
button[kind="tertiary"] {{ color: {MUTED}; }}
button[kind="tertiary"]:hover {{ color: {WARN}; }}

/* 側邊欄的「記一筆」：金色底配墨色字。Streamlit 預設是白字，在金色上對比太低看不清楚 */
section[data-testid="stSidebar"] div[data-testid="stPopover"] button {{ color: {TEXT}; font-weight: 700; }}
section[data-testid="stSidebar"] div[data-testid="stPopover"] button * {{ color: {TEXT}; }}

/* 表單送出按鈕撐滿一點，比較好按 */
div[data-testid="stFormSubmitButton"] button {{ min-width: 120px; }}

/* ---------- 手機（寬度 640px 以下） ----------
   Streamlit 在窄螢幕會把每個欄位都疊成一行，明細列表就會被拉得很長。
   列表卡片的 key 都以 _list 結尾，這裡讓它們的每一列保持橫排。 */
@media (max-width: 640px) {{
    .block-container {{ padding-left: 1rem; padding-right: 1rem; padding-top: 1.2rem; }}
    .page-head h1 {{ font-size: 1.7rem; }}
    [class*="st-key-card"] {{ padding: 16px 14px; }}
    [class*="st-key-card"][class*="_list"] div[data-testid="stHorizontalBlock"] {{
        flex-wrap: nowrap; gap: .35rem;
    }}
    [class*="st-key-card"][class*="_list"] div[data-testid="stColumn"] {{
        min-width: 0 !important; overflow-wrap: anywhere;
    }}
    [class*="st-key-card"][class*="_list"] p {{ font-size: .82rem; }}
    /* 摘要列一列放兩格，不要一格佔滿一整列；格子之間改用底線分開 */
    [class*="st-key-strip"] {{ border-bottom: none; }}
    [class*="st-key-strip"] div[data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
    [class*="st-key-strip"] div[data-testid="stColumn"] {{
        min-width: 50% !important; width: 50% !important; flex: 1 1 50% !important;
        border-left: none !important; border-bottom: 1px solid #CCD6CF;
    }}
    [class*="st-key-strip"] div[data-testid="stMetric"],
    [class*="st-key-strip"] div[data-testid="stColumn"]:first-child div[data-testid="stMetric"] {{
        padding: 10px 8px 10px 0;
    }}
    div[data-testid="stMetricValue"] div {{ font-size: 1.25rem; }}
    /* 結餘和下單結論改成上下排 */
    .hero, .verdict {{ grid-template-columns: minmax(0, 1fr); gap: .8rem; }}
    .hero-num {{ font-size: 2.6rem; }}
    .verdict-word {{ font-size: 2rem; }}
    /* 刪除按鈕只留垃圾桶圖示，省空間 */
    [class*="st-key-card"][class*="_list"] button[kind="tertiary"] div[data-testid="stMarkdownContainer"] {{
        display: none;
    }}
}}
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


def ledger_html(rows: list[tuple[str, str, str]], total: bool = True) -> str:
    """存摺式明細的 HTML。rows 是 [(顏色, 項目, 金額), ...]。

    顏色是項目前面的小圓點，空字串就不畫。
    total=True 時最後一列當作合計（上面畫雙線）；總覽的結餘用 total=False，因為合計就是旁邊的大數字。
    """
    parts = []
    for i, (color, label, amount) in enumerate(rows):
        cls = "ledger-row total" if total and i == len(rows) - 1 else "ledger-row"
        dot = f'<span class="dot" style="background:{color}"></span>' if color else ""
        parts.append(f'<div class="{cls}"><div>{dot}{label}</div><div>{amount}</div></div>')
    return f'<div class="ledger">{"".join(parts)}</div>'


def ledger(rows: list[tuple[str, str, str]]) -> None:
    """畫存摺式明細，最後一列是合計（格式見 ledger_html）。"""
    st.markdown(ledger_html(rows), unsafe_allow_html=True)


def plain(text: str) -> str:
    """使用者自己輸入的文字，放進 st.write / st.markdown / st.toast 之前先用這個處理。

    Markdown 會把一些符號當成格式：兩個 $ 中間變成數學公式、** 變成粗體……
    在每個標點符號前面加一個反斜線，Markdown 就會照原樣顯示（像 C++ 字串裡用 \\" 表示引號）。
    """
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|$~<>])", r"\\\1", text)


def done(message: str) -> None:
    """存檔成功後呼叫：記下要顯示的通知，然後立刻重跑整頁。

    為什麼一定要重跑：
    - 側邊欄的摘要在頁面內容之前就畫好了，不重跑會顯示存檔前的舊數字。
    - 沒有 key 的輸入框會把「預設值」算進自己的身分；資料庫的值變了卻不重跑，
      下一次輸入的數字會被當成另一個輸入框而丟掉（連按兩次「儲存」，第二次會沒存到）。
    通知先放進 st.session_state（重跑之間會保留的字典），重跑後由主程式用 st.toast 顯示。
    不用 st.success：它是綠色，而綠色在這個 app 代表「賠錢」。
    """
    st.session_state["toast"] = message
    st.rerun()


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
    標題旁邊刻意不放類別圓點：進度條的顏色已經代表「狀態」，旁邊再放一個代表「類別」的顏色，
    同一列就有兩種顏色意思，容易看錯。
    """
    if budget > 0:
        ratio = spent / budget
    else:
        # 預算是 0 卻有花錢，一定是超支；用無限大讓它走「超支」的橘色（長度另外限制在 100%）
        ratio = float("inf") if spent > 0 else 0.0
    color = INK if ratio < 0.8 else (GOLD if ratio <= 1 else WARN)
    left = budget - spent
    if left >= 0:
        note = f"剩 {money(left)}・已用 {ratio:.0%}"
    else:
        note = f'<span style="color:{WARN};font-weight:600">超支 {money(-left)}</span>'
    progress_bar(label, spent, budget, color, note, ratio)


def category_label(category: str, sub: str | None = None, income: bool = False) -> str:
    """類別名稱前面加上它的顏色圓點（HTML），有細項時接在後面的灰色小字。

    顏色和「預算分配」圓餅圖一致；收入一律用金色圓點（收入沒有預算、也不參加支出的圓餅圖）。
    """
    color = GOLD if income else CATEGORY_COLORS.get(category, MUTED)
    extra = f'<span style="color:{MUTED}"> · {html.escape(sub)}</span>' if sub else ""
    return f'<span class="dot" style="background:{color}"></span>{html.escape(category)}{extra}'


def account_names() -> dict[int, str]:
    """{帳戶 id: 名稱}，明細列表顯示「從哪個帳戶」用。"""
    return {a["id"]: a["name"] for a in db.get_accounts()}


def account_select(label: str, key: str | None = None, allow_none: bool = False,
                   default: int | None = None) -> int | None:
    """選帳戶的下拉選單，旁邊顯示目前餘額。回傳帳戶 id。

    選項用 id（數字）而不是整個帳戶資料：餘額變了選項也不會變，選到的帳戶不會被重設。
    allow_none=True 時多一個「不屬於任何帳戶」（舊的記帳沒有帳戶，修改時要能保持原狀）。
    """
    accounts = {a["id"]: a for a in db.get_accounts()}
    ids = list(accounts) + ([None] if allow_none else [])
    index = ids.index(default) if default in ids else 0
    return st.selectbox(
        label, ids, index=index, key=key,
        format_func=lambda i: "不屬於任何帳戶" if i is None
        else f"{accounts[i]['name']}（{money(accounts[i]['balance'])}）",
    )


def record_form(key: str, kind: str, with_date: bool = True) -> None:
    """新增一筆記帳的表單（記帳頁和側邊欄「記一筆」共用）。kind 是 "expense" 或 "income"。

    類別是「主類別 · 細項」攤平的一個選單（見 models/budget.py 的 category_options），
    因為表單裡選了主類別不會馬上更新第二個選單。記下來時同時更新選到的帳戶餘額。
    """
    income = kind == "income"
    with st.form(key, clear_on_submit=True, border=False):
        amount = st.number_input("金額", min_value=0.0, step=10.0, format="%.0f")
        option = st.selectbox("類別", category_options(kind))
        account_id = account_select("存入帳戶" if income else "從哪個帳戶付")
        when = st.date_input("日期", value=date.today()) if with_date else date.today()
        note = st.text_input("備註（可不填）")
        submitted = st.form_submit_button("記下來", type="primary", icon=":material/check:", width="stretch")
    if submitted:
        if amount <= 0:
            st.warning("金額要大於 0")
        else:
            main, sub = split_option(option)
            db.add_expense(amount, main, when.isoformat(), note, subcategory=sub, account_id=account_id, kind=kind)
            done(f"已記下{'收入' if income else ''}：{option} {money(amount)}（{account_names()[account_id]}）")


def summary_strip(key: str, n: int) -> list:
    """一排摘要數字（存摺式）：回傳 n 個欄位，每個欄位放一個 st.metric。

    外面包一個 key 以 strip_ 開頭的容器，inject_css() 才選得到它、畫出上下的橫線。
    """
    return st.container(key=f"strip_{key}").columns(n)


def notices(rows: list[tuple[str, str, str]]) -> None:
    """自律提醒（例如當沖、持股太集中），畫成存摺的「摘要」欄。

    rows 是 [(標籤, 說明, 顏色), ...]，標籤是兩個字，例如「當沖」。
    說明會直接放進 HTML，裡面如果有使用者輸入的文字，呼叫前要先 html.escape()。

    為什麼不用 st.error / st.warning：st.error 是紅色塊，而紅色在這個 app 代表「賺錢」；
    st.warning 的黃色塊像系統訊息。自律提醒是這個 app 自己的判斷，用存摺的樣式。
    （st.warning 只留給「輸入錯誤」這類系統訊息。）
    """
    parts = [f'<div class="notice"><b style="color:{color}">{tag}</b><span>{text}</span></div>'
             for tag, text, color in rows]
    st.markdown(f'<div class="notices">{"".join(parts)}</div>', unsafe_allow_html=True)


def big_number(label: str, value: str) -> str:
    """回傳「小標籤 + 大數字」的 HTML，用在卡片裡面。"""
    return f'<div class="big-label">{label}</div><div class="big-num">{value}</div>'


def chip(text: str, color: str) -> str:
    """回傳一個彩色小標籤的 HTML（淡底色 + 深色字）。"""
    return f'<span class="chip" style="background:{color}1F;color:{color}">{html.escape(text)}</span>'


def show_donut(data: pd.DataFrame, label: str, value: str, center_text: str,
               colors: list[str] | None = None) -> None:
    """甜甜圈圖：看每一塊占多少比例（持股占比、預算分配都用它），下面附圖例和百分比。

    center_text 是圓圈中間的字，例如總金額。
    colors 是每一塊的顏色（照資料順序）；沒給就用 CHART_COLORS。
    圖例自己用 HTML 畫在圖下面，不用 Altair 內建的：內建圖例在窄的卡片裡會蓋到圓圈或被裁掉，
    自己畫還可以順便顯示每一塊的百分比。
    """
    colors = (colors or CHART_COLORS)[:len(data)]
    data = data.assign(順序=range(len(data)))  # 甜甜圈一塊一塊照資料順序畫
    base = alt.Chart(data).encode(
        theta=alt.Theta(f"{value}:Q", stack=True),
        color=alt.Color(f"{label}:N", sort=list(data[label]), scale=alt.Scale(range=colors), legend=None),
        order=alt.Order("順序:Q"),
        tooltip=[alt.Tooltip(f"{label}:N"), alt.Tooltip(f"{value}:Q", format=",.0f")],
    )
    # 每一塊之間的縫用卡片底色，看起來像切開的
    # 半徑不要太大：總覽右邊那張卡片在 1024px 寬的視窗只有約 230px 寬（扣掉內距約 170px），圓圈要放得下
    ring = base.mark_arc(innerRadius=50, outerRadius=80, stroke=PAPER, strokeWidth=2)
    center = alt.Chart(pd.DataFrame({"t": [center_text]})).mark_text(
        fontSize=16, fontWeight=700, color=TEXT, font=SERIF.replace('"', "")
    ).encode(text="t:N")
    show_chart((ring + center).properties(height=200))

    total = data[value].sum()
    rows = [(color, html.escape(str(name)), f"{v / total:.0%}" if total else "—")
            for color, name, v in zip(colors * len(data), data[label], data[value])]
    st.markdown(ledger_html(rows, total=False), unsafe_allow_html=True)


def show_chart(chart: alt.Chart) -> None:
    """顯示 Altair 圖表：背景透明、拿掉外框，讓圖表融入卡片。"""
    st.altair_chart(chart.properties(background="transparent").configure_view(stroke=None),
                    width="stretch")


def delete_button(key: str, label: str = "刪除") -> bool:
    """列表裡每一列的刪除按鈕（低調的垃圾桶圖示）。欄位窄的時候 label 給空字串，只留圖示。"""
    return st.button(label, key=key, type="tertiary", icon=":material/delete:", help="刪除這一筆")


# ---------- 股價自動更新 ----------

QUOTE_TTL = 300  # 秒：5 分鐘內重複打開頁面不再連網路，用上一次抓到的


@st.cache_data(ttl=QUOTE_TTL, show_spinner=False)
def cached_quotes(symbols: tuple[str, ...]) -> tuple[quotes.QuoteResult, float]:
    """抓股價並記住 5 分鐘（st.cache_data：同樣的參數在期限內直接回傳上次的結果，不重抓）。

    回傳 (結果, 抓的時間)。抓的時間要一起記住：5 分鐘內重跑頁面時，顯示的仍是真正抓的那一刻。
    """
    return quotes.fetch_prices(list(symbols)), time.time()


def refresh_quotes(force: bool = False) -> None:
    """打開總覽或持股頁時呼叫：自動更新所有持股的現價。

    - 設定頁關掉「自動更新股價」時什麼都不做（force=True 是按了「立即更新」，照樣抓）
    - 沒有持股就不連網路
    - 抓不到時保留原本的價格，原因放進 session_state，持股頁會顯示
    """
    settings = db.get_settings()
    if not settings.get("auto_quotes", 1) and not force:
        return
    symbols = tuple(sorted({h["symbol"] for h in db.get_holdings()}))
    if not symbols:
        return
    if force:
        cached_quotes.clear()
    with st.spinner("更新股價中…"):
        result, fetched_at = cached_quotes(symbols)
    st.session_state["quote_result"] = result
    if result.prices:
        db.update_prices(result.prices)
        d = result.quote_date
        db.save_settings({
            "quotes_fetched_at": fetched_at,
            "quotes_date": d.year * 10000 + d.month * 100 + d.day if d else 0.0,
            "quotes_realtime": 1.0 if result.source == "realtime" else 0.0,
        })


def quote_status() -> str:
    """現價是什麼時候的，例如「10/21 11:46 盤中即時」「10/20 收盤價」。還沒抓過回傳空字串。"""
    s = db.get_settings()
    if not s.get("quotes_fetched_at"):
        return ""
    fetched = datetime.fromtimestamp(s["quotes_fetched_at"])
    n = int(s.get("quotes_date") or 0)
    quote_day = date(n // 10000, n // 100 % 100, n % 100) if n else fetched.date()
    if s.get("quotes_realtime") and quote_day == fetched.date():
        if is_trading_time(fetched):
            return f"{fetched.month}/{fetched.day} {fetched:%H:%M} 盤中即時（約延遲幾秒）"
        return f"{quote_day.month}/{quote_day.day} 收盤價"
    return f"{quote_day.month}/{quote_day.day} 收盤價"


# ---------- 頁面：總覽 ----------

def welcome() -> None:
    """第一次打開（還沒有任何資料）時，總覽頁改成顯示「開始使用」的三個步驟。

    為什麼需要：空的資料庫打開總覽，只會看到一排 0 元，不知道要從哪裡開始。
    """
    st.markdown(
        '<div class="hero" style="margin-bottom:1.2rem"><div><div class="hero-label">歡迎使用</div>'
        '<div class="hero-num" style="font-size:2.6rem">開一本自己的存摺</div>'
        '<div class="hero-note">資料只存在這台電腦，不會上傳到任何地方</div></div>'
        '<div class="welcome-why">花 3 分鐘填好基本資料，之後每天只要記帳，'
        '這裡就會告訴你：淨資產多少、每月能存多少、這個月還能花多少。</div></div>',
        unsafe_allow_html=True,
    )
    steps = [
        ("1", "開帳戶、填收入", "現金、銀行戶頭各開一個帳戶，填上現在的餘額；每月收入在設定頁。", "accounts", "前往帳戶"),
        ("2", "設定每月預算", "吃飯、交通……每個類別最多花多少。", "budgets", "設定預算"),
        ("3", "開始記帳", "每花一筆就記一筆，也可以用左邊的「記一筆」。", "expenses", "去記帳"),
    ]
    cols = st.columns(3)
    for col, (num, title, text, url, label) in zip(cols, steps):
        with col, st.container(key=f"card_step_{num}"):
            st.markdown(f'<div class="step-num">{num}</div><div class="card-title">{title}</div>'
                        f'<p class="step-text">{text}</p>', unsafe_allow_html=True)
            st.page_link(PAGES[url], label=label, icon=":material/arrow_forward:")
    st.caption("有負債、股票的話，也可以到「負債」「持股」頁加進來，總覽會一起算進淨資產。")


def page_overview() -> None:
    today = date.today()
    page_header("總覽", "現金、投資、負債一次看完")
    if db.is_empty():
        welcome()
        return

    refresh_quotes()  # 淨資產裡的股票市值要用最新的價格算
    settings = db.get_settings()
    cash = settings["cash_on_hand"]
    analyzed = analyze(db.get_holdings())
    total_value = sum(m["value"] for m in analyzed)
    total_profit = sum(m["profit"] for m in analyzed)
    debts = db.get_debts()
    total_debt = sum(d["remaining"] for d in debts)

    # --- 結餘：整個 app 的主角。左邊一個大數字，右邊是它怎麼算出來的 ---
    stock_label = "+ 股票市值"
    if total_profit:
        stock_label += f'<span class="sub">損益 {colored_money_html(total_profit)}</span>'
    if analyzed and quote_status():
        stock_label += f'<span class="sub" style="color:{MUTED}">{quote_status()}</span>'
    hero_rows = ledger_html([("", "帳戶存款", money(cash)),
                             ("", stock_label, money(total_value)),
                             ("", "− 負債餘額", money(total_debt))], total=False)
    st.markdown(
        f'<div class="hero"><div><div class="hero-label">淨資產</div>'
        f'<div class="hero-num">{cash + total_value - total_debt:,.0f}<small>元</small></div>'
        f'<div class="hero-note">{today.year} 年 {today.month} 月 {today.day} 日的結餘</div></div>'
        f'{hero_rows}</div>',
        unsafe_allow_html=True,
    )
    # 每次打開總覽就記下今天的淨資產（同一天會覆蓋），累積起來就是下面的「淨資產變化」
    networth = cash + total_value - total_debt
    db.record_networth(today.isoformat(), networth)

    # --- 提醒：持股集中度、本月當沖 ---
    # 股票名稱和代號是自己輸入的，放進 HTML 前先 html.escape，避免畫面壞掉
    alerts = [("集中", f"{html.escape(m['name'])}（{html.escape(m['symbol'])}）"
                       f"占總市值 {m['weight']:.1%}，超過 {CONCENTRATION_LIMIT:.0%}，風險過度集中。", WARN)
              for m in over_concentrated(analyzed)]
    day_trades = count_day_trades(db.get_trades(), today.year, today.month)
    if day_trades > 0:
        alerts.append(("當沖", f"本月已經當沖 {day_trades} 次，請停下來檢討。", WARN))
    else:
        alerts.append(("當沖", "本月 0 次，繼續保持。", INK))
    notices(alerts)

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
            notices([("超支", f"每月入不敷出 {money(-savings)}。", WARN)])

    with right, st.container(key="card_weights"):
        card_title("持股占比", f"上限 {CONCENTRATION_LIMIT:.0%}")
        if analyzed:
            weights = pd.DataFrame({"股票": [m["name"] for m in analyzed],
                                    "市值": [m["value"] for m in analyzed]})
            show_donut(weights, "股票", "市值", money(total_value))
        else:
            st.info("還沒有持股")

    networth_trend()

    # --- 本月預算使用 ---
    month_expenses = db.get_expenses_in_month(today.year, today.month)
    budgets = db.get_budgets()
    spent = spent_by_category(month_expenses)
    with st.container(key="card_budget_overview"):
        card_title("本月預算", f"還能花 {money(remaining_this_month(budgets, month_expenses))}")
        cols = st.columns(2)
        for i, c in enumerate(CATEGORIES):
            with cols[i % 2]:
                budget_bar(c, spent[c], budgets.get(c, 0.0))


def networth_trend() -> None:
    """淨資產變化的折線圖。至少要有兩天的紀錄才畫（一個點畫不出變化）。

    看到數字一天天往上，是持續記帳最好的動力。
    """
    history = db.get_networth_history()
    if len(history) < 2:
        return
    data = pd.DataFrame(history)
    data["日期"] = pd.to_datetime(data["date"])
    change = history[-1]["value"] - history[0]["value"]
    first = history[0]["date"]
    with st.container(key="card_networth"):
        card_title("淨資產變化", f"從 {first[:4]} 年 {int(first[5:7])} 月 {int(first[8:])} 日到今天 "
                   + ("增加" if change >= 0 else "減少") + f" {money(abs(change))}")
        x = alt.X("日期:T", title=None, axis=alt.Axis(format="%Y/%m", grid=False, labelFontSize=12,
                                                     tickCount="month"))
        y = alt.Y("value:Q", title=None,
                  axis=alt.Axis(labelExpr="format(datum.value / 10000, ',') + ' 萬'", gridColor="#E1E8E3"))
        area = alt.Chart(data).mark_area(
            color=alt.Gradient(gradient="linear", x1=1, x2=1, y1=1, y2=0,
                               stops=[alt.GradientStop(color=PAPER, offset=0),
                                      alt.GradientStop(color="#C9D5E6", offset=1)]),
            line={"color": INK, "strokeWidth": 2.5},
        ).encode(x=x, y=y, tooltip=[alt.Tooltip("date:N", title="日期"),
                                     alt.Tooltip("value:Q", title="淨資產", format=",.0f")])
        last = alt.Chart(data.tail(1)).mark_circle(size=70, color=INK).encode(x=x, y=y)
        show_chart((area + last).properties(height=220))


# ---------- 頁面：記帳 ----------

def page_expenses() -> None:
    today = date.today()
    page_header("記帳", "花出去的、收進來的都記下，帳戶餘額會跟著變")

    form_col, stat_col = st.columns([2, 3])

    with form_col, st.container(key="card_add_expense"):
        card_title("新增一筆")
        # 支出和收入分兩個分頁，類別選單不一樣（收入沒有預算）
        tab_out, tab_in = st.tabs(["支出", "收入"])
        with tab_out:
            record_form("add_expense", "expense")
        with tab_in:
            record_form("add_income", "income")

    # --- 選月份：預設本月，也可以回頭看以前的月份 ---
    this_month = f"{today.year:04d}-{today.month:02d}"
    # 本月一定在選單裡（就算還沒記帳）；sorted(set(...)) 去掉重複再排序，新的在前面
    months = sorted(set([this_month] + db.get_expense_months()), reverse=True)

    with stat_col:
        ym = st.selectbox("月份", months, key="expense_month", label_visibility="collapsed",
                          format_func=lambda m: f"{m[:4]} 年 {int(m[5:])} 月" + ("（本月）" if m == this_month else ""))
        year, month = int(ym[:4]), int(ym[5:])
        is_this_month = ym == this_month
        word = "本月" if is_this_month else "當月"

        records = db.get_records_in_month(year, month)
        month_expenses = [r for r in records if r["kind"] == "expense"]  # 預算、還能花多少只看支出
        budgets = db.get_budgets()
        remaining = remaining_this_month(budgets, month_expenses)
        total_spent = sum(e["amount"] for e in month_expenses)
        total_income = sum(r["amount"] for r in records if r["kind"] == "income")

        m1, m2, m3 = summary_strip("expenses", 3)
        label = f"{word}還能花" if is_this_month else "比預算剩下"
        if remaining >= 0:
            m1.metric(label, money(remaining))
        else:
            # 超支用橘色（config.toml 的 orangeColor），紅色留給漲跌
            m1.metric(label, money(remaining), delta="已超支",
                      delta_color="orange", delta_arrow="off")
        m2.metric(f"{word}已花", money(total_spent))
        # 收入減支出 = 這個月存下（或花掉）多少。不用紅綠（紅綠留給漲跌），只用文字說明
        net = total_income - total_spent
        m3.metric(f"{word}收入", money(total_income),
                  delta=f"收支{'結餘' if net >= 0 else '不足'} {money(abs(net))}", delta_color="off", delta_arrow="off")

        with st.container(key="card_budget_bars"):
            card_title(f"{year} 年 {month} 月各類別")
            spent = spent_by_category(month_expenses)
            for c in CATEGORIES:
                budget_bar(c, spent[c], budgets.get(c, 0.0))

    # --- 當月明細 ---
    with st.container(key="card_expense_list"):
        card_title(f"{word}明細", f"共 {len(records)} 筆")
        if not records:
            st.info(f"{word}還沒有記帳")
        else:
            names = account_names()
            widths = [1.8, 2.6, 1.8, 1.6, 2.6, 1.4]  # st.columns 的寬度比例，表頭和每一列共用
            for col, text in zip(st.columns(widths), ["日期", "類別", "金額", "帳戶", "備註", ""]):
                col.caption(text)
            for e in records:
                income = e["kind"] == "income"
                col1, col2, col3, col4, col5, col6 = st.columns(widths, vertical_alignment="center")
                col1.write(e["date"])
                col2.markdown(category_label(e["category"], e["subcategory"], income), unsafe_allow_html=True)
                # 收入前面加「+」、用金色；支出照舊。不用紅綠（紅綠留給漲跌）
                if income:
                    col3.markdown(f'<b style="color:{GOLD_TEXT}">+{money(e["amount"])}</b>', unsafe_allow_html=True)
                else:
                    col3.write(f"**{money(e['amount'])}**")
                col4.write(plain(names.get(e["account_id"], "—")))
                col5.write(plain(e["note"] or ""))
                # 每個按鈕需要唯一的 key，所以用記帳的 id
                with col6:
                    edit_col, del_col = st.columns(2, gap="small")
                    with edit_col:
                        edit_expense(e)
                    with del_col:
                        if delete_button(f"del_exp_{e['id']}", label=""):
                            db.delete_expense(e["id"])
                            st.rerun()  # 立刻重跑，讓畫面更新

    expense_trend(budgets)


def edit_expense(e: dict) -> None:
    """明細裡每一列的「修改」：點了跳出一個小視窗，改完按儲存。記錯不用再刪掉重記。"""
    with st.popover("", icon=":material/edit:", help="修改這一筆", type="tertiary"):
        with st.form(f"edit_exp_{e['id']}", border=False):
            amount = st.number_input("金額", min_value=0.0, step=10.0, format="%.0f",
                                     value=float(e["amount"]))
            # 舊的記帳只有主類別（沒有細項），把它放在選單最前面，修改時才不會被改掉
            options = category_options(e["kind"])
            current = join_option(e["category"], e["subcategory"])
            if current not in options:
                options = [current] + options
            option = st.selectbox("類別", options, index=options.index(current))
            account_id = account_select("帳戶", allow_none=True, default=e["account_id"])
            new_date = st.date_input("日期", value=date.fromisoformat(e["date"]))
            note = st.text_input("備註", value=e["note"] or "")
            if st.form_submit_button("儲存", type="primary", icon=":material/save:"):
                if amount <= 0:
                    st.warning("金額要大於 0")
                else:
                    main, sub = split_option(option)
                    db.update_expense(e["id"], amount, main, new_date.isoformat(), note,
                                      subcategory=sub, account_id=account_id)
                    done("已修改")


def expense_trend(budgets: dict[str, float]) -> None:
    """最近 6 個月每月花了多少（依類別疊起來），旁邊一條虛線是每月預算，一眼看出哪個月花太多。"""
    months = last_n_months(date.today(), 6)
    data = pd.DataFrame(monthly_totals(db.get_expenses_since(f"{months[0]}-01"), months))
    if data["金額"].sum() == 0:
        return  # 還沒有任何記帳，不畫空的圖

    budget_total = sum(budgets.values())
    # 月份顯示成「10 月」比「2026-10」好讀；跨年時一月顯示年份
    # （標籤要「每個月」算一次，不是每一列算一次，不然同一個月會變成兩根長條）
    labels = {m: (f"{m[:4]}/{int(m[5:])}月" if i == 0 or m.endswith("-01") else f"{int(m[5:])}月")
              for i, m in enumerate(months)}
    data["月"] = data["月份"].map(labels)
    order = [labels[m] for m in months]
    data["順序"] = [CATEGORIES.index(c) for c in data["類別"]]  # 疊的順序和圖例一樣

    with st.container(key="card_expense_trend"):
        totals = data.groupby("月份")["金額"].sum()
        avg = totals[totals > 0].mean()
        card_title("最近 6 個月", f"有記帳的月份平均每月 {money(avg)}")
        bars = alt.Chart(data).mark_bar(size=34, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("月:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, labelFontSize=12)),
            y=alt.Y("金額:Q", title=None, axis=alt.Axis(format=",.0f", gridColor="#E1E8E3")),
            color=alt.Color("類別:N", sort=CATEGORIES,
                            scale=alt.Scale(domain=CATEGORIES, range=[CATEGORY_COLORS[c] for c in CATEGORIES]),
                            legend=alt.Legend(title=None, orient="top", labelFontSize=12)),
            order=alt.Order("順序:Q"),
            tooltip=["月份:N", "類別:N", alt.Tooltip("金額:Q", format=",.0f")],
        )
        chart = bars
        if budget_total > 0:
            # 預算線：金色虛線。超過這條線的月份就是超支
            rule = alt.Chart(pd.DataFrame({"預算": [budget_total]})).mark_rule(
                color=GOLD, strokeDash=[6, 4], strokeWidth=2
            ).encode(y="預算:Q", tooltip=[alt.Tooltip("預算:Q", format=",.0f", title="每月預算")])
            chart = bars + rule
        show_chart(chart.properties(height=260))
        if budget_total > 0:
            over = [m for m, v in totals.items() if v > budget_total]
            note = (f"金色虛線是每月預算 {money(budget_total)}。"
                    + (f"超過預算的月份：{'、'.join(f'{int(m[5:])} 月' for m in over)}。" if over else "每個月都在預算內。"))
            st.markdown(f'<div class="trend-note">{note}</div>', unsafe_allow_html=True)


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
                    c, min_value=0.0, step=100.0, format="%.0f",
                    value=float(budgets.get(c, 0.0))
                )
            if st.form_submit_button("儲存", type="primary", icon=":material/save:"):
                db.save_budgets(new_budgets)
                done("預算已儲存")

    total = sum(new_budgets.values())
    with chart_col, st.container(key="card_budget_split"):
        # 合計寫在標題旁邊，圓餅圖中間也會再寫一次，不另外放一張數字卡
        card_title("預算分配", f"每月合計 {money(total)}")
        if total > 0:
            split = pd.DataFrame({"類別": list(new_budgets.keys()),
                                  "金額": list(new_budgets.values())})
            show_donut(split, "類別", "金額", money(total),
                       colors=[CATEGORY_COLORS[c] for c in new_budgets])
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
                name = name.strip()  # 前後的空白不要存進去，通知訊息也用同一個值
                if not name:
                    st.warning("請輸入名稱")
                elif amount <= 0:
                    st.warning("金額要大於 0")
                else:
                    db.add_fixed_expense(name, amount)
                    done(f"已新增：{plain(name)}")

    items = db.get_fixed_expenses()
    with list_col:
        total = sum(item["amount"] for item in items)
        m1, m2 = summary_strip("fixed", 2)
        m1.metric("固定支出合計 / 月", money(total))
        m2.metric("一年下來", money(total * 12))

        with st.container(key="card_fixed_list"):
            card_title("項目", f"共 {len(items)} 項")
            if not items:
                st.info("還沒有固定支出")
                return
            for item in items:
                col1, col2, col3 = st.columns([4, 2, 1], vertical_alignment="center")
                col1.write(plain(item["name"]))
                col2.write(f"**{money(item['amount'])}**")
                with col3:
                    if delete_button(f"del_fixed_{item['id']}"):
                        db.delete_fixed_expense(item["id"])
                        st.rerun()


# ---------- 頁面：帳戶 ----------

def page_accounts() -> None:
    """銀行帳戶：每個帳戶各自的餘額。記帳、還債時選帳戶，餘額會自動增減。"""
    page_header("帳戶", "現金、銀行戶頭各自記；記帳和還債時選帳戶，餘額會跟著變")
    accounts = db.get_accounts()
    total = sum(a["balance"] for a in accounts)

    m1, m2 = summary_strip("accounts", 2)
    m1.metric("全部帳戶合計", money(total), help="總覽的淨資產用這個數字")
    m2.metric("帳戶數", f"{len(accounts)} 個")

    list_col, form_col = st.columns([3, 2])
    with list_col, st.container(key="card_account_list"):
        card_title("各帳戶餘額")
        for a in accounts:
            col1, col2, col3 = st.columns([3, 3, 1.4], vertical_alignment="center")
            col1.markdown(f"**{plain(a['name'])}**")
            # 負數（例如信用卡、透支）用橘色提醒；紅綠留給漲跌
            text = money(a["balance"])
            col2.markdown(f'<div style="text-align:right;font-family:{SERIF};font-size:1.15rem'
                          f'{";color:" + WARN if a["balance"] < 0 else ""}">{text}</div>', unsafe_allow_html=True)
            with col3:
                with st.popover("", icon=":material/edit:", help="改名、校正餘額、刪除", type="tertiary"):
                    with st.form(f"acc_edit_{a['id']}", border=False):
                        name = st.text_input("名稱", value=a["name"])
                        balance = st.number_input("餘額（和銀行 App 上的數字不一樣時校正）", step=100.0,
                                                  format="%.0f", value=float(a["balance"]))
                        if st.form_submit_button("儲存", type="primary", icon=":material/save:"):
                            if not name.strip():
                                st.warning("請輸入名稱")
                            else:
                                db.rename_account(a["id"], name.strip())
                                db.set_account_balance(a["id"], balance)
                                done(f"已更新：{plain(name.strip())}")
                    if len(accounts) > 1 and st.button("刪除這個帳戶", key=f"acc_del_{a['id']}",
                                                       icon=":material/delete:"):
                        db.delete_account(a["id"])
                        done(f"已刪除：{plain(a['name'])}（記帳紀錄還在）")

    with form_col:
        with st.container(key="card_add_account"):
            card_title("開一個帳戶")
            with st.form("add_account", clear_on_submit=True, border=False):
                name = st.text_input("名稱（例如 台新銀行、郵局、悠遊卡）")
                balance = st.number_input("現在的餘額", step=1000.0, format="%.0f")
                if st.form_submit_button("開戶", type="primary", icon=":material/add:"):
                    name = name.strip()
                    if not name:
                        st.warning("請輸入名稱")
                    elif name in [a["name"] for a in accounts]:
                        st.warning("已經有同名的帳戶")
                    else:
                        db.add_account(name, balance)
                        done(f"已開戶：{plain(name)}")

        if len(accounts) > 1:
            with st.container(key="card_transfer"):
                card_title("轉帳", "例如從銀行領錢出來")
                with st.form("transfer", clear_on_submit=True, border=False):
                    src = account_select("從")
                    dst = account_select("轉到", default=accounts[1]["id"])
                    amount = st.number_input("金額", min_value=0.0, step=100.0, format="%.0f")
                    if st.form_submit_button("轉帳", type="primary", icon=":material/swap_horiz:"):
                        try:
                            db.transfer(src, dst, amount)
                        except ValueError as e:
                            st.warning(str(e))
                        else:
                            done(f"已轉帳 {money(amount)}")


# ---------- 頁面：負債 ----------

def page_debts() -> None:
    page_header("負債追蹤", "定期還的每期按一下；不限期的有錢就還一筆，看著餘額慢慢變少")

    debts = db.get_debts()
    installment = [d for d in debts if d["kind"] != "open"]
    m1, m2, m3 = summary_strip("debts", 3)
    m1.metric("負債餘額", money(sum(d["remaining"] for d in debts)))
    m2.metric("每月固定還款", money(total_debt_payment(installment)), help="只算「定期還」的負債")
    m3.metric("帳戶存款合計", money(db.get_settings()["cash_on_hand"]))

    list_col, form_col = st.columns([3, 2])

    with form_col, st.container(key="card_add_debt"):
        card_title("新增負債")
        with st.form("add_debt", clear_on_submit=True, border=False):
            name = st.text_input("名稱（例如 學貸、信用卡分期、跟朋友借）")
            kind = st.radio("類型", ["定期還", "不限期"], horizontal=True,
                            captions=["每月固定還一筆", "沒有固定還款，有錢就還"])
            remaining = st.number_input("剩餘金額", min_value=0.0, step=1000.0, format="%.0f")
            monthly = st.number_input("每月還款（定期還才要填）", min_value=0.0, step=100.0, format="%.0f")
            if st.form_submit_button("新增", type="primary", icon=":material/add:"):
                name = name.strip()
                if not name:
                    st.warning("請輸入名稱")
                elif remaining <= 0:
                    st.warning("剩餘金額要大於 0")
                elif kind == "定期還" and monthly <= 0:
                    st.warning("定期還的負債要填每月還款")
                else:
                    db.add_debt(name, remaining, monthly, "open" if kind == "不限期" else "installment")
                    done(f"已新增：{plain(name)}")  # 重跑讓左邊的清單和上面的數字馬上更新

    with list_col:
        if not debts:
            st.info("沒有負債")
            return
        # 所有還款按鈕都從這個帳戶扣（每張卡片各放一個選單太佔位置）
        account_id = account_select("還款從哪個帳戶扣", key="debt_pay_account")

        today = date.today()
        for d in debts:
            with st.container(key=f"card_debt_{d['id']}"):
                payments = db.get_debt_payments(d["id"])
                paid_total = sum(p["amount"] for p in payments)
                if d["kind"] == "open":
                    open_debt_card(d, payments, paid_total, account_id)
                else:
                    installment_card(d, payments, account_id, today)
                if payments:
                    names = account_names()
                    with st.expander(f"還款紀錄（{len(payments)} 筆，共 {money(paid_total)}）"):
                        ledger_rows = [("", f'{p["date"]}<span class="sub">{html.escape(names.get(p["account_id"], ""))}</span>',
                                        money(p["amount"])) for p in payments[:24]]
                        st.markdown(ledger_html(ledger_rows, total=False), unsafe_allow_html=True)


def installment_card(d: dict, payments: list[dict], account_id: int, today: date) -> None:
    """定期還的負債：還剩幾期、預計哪個月還清、「已還一期」按鈕。"""
    ym = payoff_month(d["remaining"], d["monthly_payment"], today)
    if ym is None:
        status = chip("已還清", GOLD_TEXT)
    else:
        n = months_left(d["remaining"], d["monthly_payment"])
        status = chip(f"定期還・還剩 {n} 期・預計 {ym[0]} 年 {ym[1]} 月還清", INK)
    # 名稱是自己輸入的，用 html.escape 把 < > & 換成安全的寫法，避免畫面壞掉
    st.markdown(f'<div class="card-title">{html.escape(d["name"])}　{status}</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    col1.markdown(big_number("剩餘金額", money(d["remaining"])), unsafe_allow_html=True)
    col2.markdown(big_number("每月還款", money(d["monthly_payment"])), unsafe_allow_html=True)

    b1, b2 = st.columns([3, 1])
    if ym is not None:
        pay = payment_this_period(d["remaining"], d["monthly_payment"])
        with b1:
            if paid_in_month(payments, today.year, today.month):
                # 這個月已經按過了：不直接給「已還一期」按鈕，避免手滑按兩次、多扣一期。
                # 真的要提前多還一期（例如一次繳兩期），點開再確認一次
                st.markdown(chip(f"本月已還 {payments[0]['date'][5:].replace('-', '/')}", INK),
                            unsafe_allow_html=True)
                with st.popover("提前再還一期", icon=":material/more_time:"):
                    st.write(f"這個月已經還過了。確定要再還一期 {money(pay)} 嗎？")
                    if st.button("確定再還一期", key=f"pay_again_{d['id']}", type="primary"):
                        pay_debt(d["id"], pay, account_id)
            elif st.button(f"已還一期（{money(pay)}）", key=f"pay_{d['id']}",
                           type="primary", icon=":material/check:"):
                pay_debt(d["id"], pay, account_id)
    with b2:
        if delete_button(f"del_debt_{d['id']}"):
            db.delete_debt(d["id"])
            st.rerun()


def open_debt_card(d: dict, payments: list[dict], paid_total: float, account_id: int) -> None:
    """不限期的負債：沒有每月還款，有錢就「還一筆」，金額自己填。"""
    status = chip("已還清", GOLD_TEXT) if d["remaining"] <= 0 else chip("不限期", MUTED)
    st.markdown(f'<div class="card-title">{html.escape(d["name"])}　{status}</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    col1.markdown(big_number("剩餘金額", money(d["remaining"])), unsafe_allow_html=True)
    col2.markdown(big_number("已經還了", money(paid_total)), unsafe_allow_html=True)

    b1, b2 = st.columns([3, 1])
    if d["remaining"] > 0:
        with b1, st.popover("還一筆", icon=":material/payments:"):
            with st.form(f"pay_open_{d['id']}", border=False):
                amount = st.number_input("這次還多少", min_value=0.0, max_value=float(d["remaining"]),
                                         step=100.0, format="%.0f")
                if st.form_submit_button("還款", type="primary", icon=":material/check:"):
                    if amount <= 0:
                        st.warning("金額要大於 0")
                    else:
                        pay_debt(d["id"], amount, account_id)
    with b2:
        if delete_button(f"del_debt_{d['id']}"):
            db.delete_debt(d["id"])
            st.rerun()


def pay_debt(debt_id: int, amount: float, account_id: int) -> None:
    """還款：扣負債、扣選到的帳戶、記一筆還款紀錄（在 db 的同一個交易裡）。"""
    try:
        paid = db.pay_debt(debt_id, amount, account_id)
    except ValueError as e:  # 帳戶餘額不夠時，db 會丟出 ValueError，什麼都不扣
        st.warning(str(e))
    else:  # 沒有出錯才會走到這裡（try 的 else）
        done(f"已還 {money(paid)}，「{plain(account_names()[account_id])}」也扣掉了")


# ---------- 頁面：持股 ----------

def page_stocks() -> None:
    page_header("持股管理", "不同帳戶的同一檔股票會自動合併計算，現價自動更新")

    refresh_quotes()
    holdings = db.get_holdings()
    analyzed = analyze(holdings)
    if holdings:
        quote_bar()

    if analyzed:
        total_value = sum(m["value"] for m in analyzed)
        total_profit = sum(m["profit"] for m in analyzed)
        cost = total_value - total_profit
        m1, m2, m3 = summary_strip("stocks", 3)
        m1.metric("總市值", money(total_value))
        # delta_color="inverse"：正數紅、負數綠（台股習慣）
        m2.metric("總損益", signed_money(total_profit),
                  delta=f"{total_profit / cost:+.2%}" if cost > 0 else None,
                  delta_color="inverse")
        m3.metric("持有檔數", f"{len(analyzed)} 檔")

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
            over = over_concentrated(analyzed)
            if over:
                notices([("集中", f"{html.escape(m['name'])} 占 {m['weight']:.1%}，"
                                  f"超過 {CONCENTRATION_LIMIT:.0%}。", WARN) for m in over])

    chart_col, side_col = st.columns([3, 2])
    if analyzed:
        with chart_col, st.container(key="card_stock_weights"):
            card_title("持股占比", f"單一個股上限 {CONCENTRATION_LIMIT:.0%}")
            weights = pd.DataFrame({"股票": [m["name"] for m in analyzed],
                                    "市值": [m["value"] for m in analyzed]})
            show_donut(weights, "股票", "市值", money(total_value))

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
                name, symbol, account = name.strip(), symbol.strip(), account.strip()
                if not (name and symbol and account):
                    st.warning("名稱、代號、帳戶都要填")
                elif shares <= 0 or avg_price <= 0 or price <= 0:
                    st.warning("股數、均價、現價都要大於 0")
                else:
                    db.add_holding(name, symbol, account, shares, avg_price, price)
                    done(f"已新增：{plain(name)}（{plain(account)}）")  # 重跑讓上面的總覽表馬上更新

    if not holdings:
        st.info("還沒有持股")
        return

    # --- 手動修改現價：自動抓不到的（例如基金、海外股票）才需要 ---
    with side_col, st.container(key="card_update_price"):
        card_title("手動修改現價", "自動抓不到的才需要")
        st.caption("有開自動更新的話，抓得到報價的股票下次更新時會被換成最新價格。")
        with st.form("update_price", border=False):
            symbols = [m["symbol"] for m in analyzed]
            sym = st.selectbox("代號", symbols,
                               format_func=lambda s: f"{s} {next(m['name'] for m in analyzed if m['symbol'] == s)}")
            new_price = st.number_input("新的現價", min_value=0.0, step=0.1)
            if st.form_submit_button("更新", type="primary", icon=":material/sync:"):
                if new_price <= 0:
                    st.warning("現價要大於 0")
                else:
                    db.update_price(sym, new_price)
                    done(f"已更新 {plain(sym)} 的現價")

    # --- 各帳戶明細（可刪除）---
    with st.container(key="card_holding_list"):
        card_title("各帳戶明細", "刪除的是單一帳戶裡的那一筆")
        widths = [3, 2, 3, 1]
        for col, text in zip(st.columns(widths), ["股票", "帳戶", "股數與均價", ""]):
            col.caption(text)
        for h in holdings:
            col1, col2, col3, col4 = st.columns(widths, vertical_alignment="center")
            col1.write(f"**{plain(h['name'])}**（{plain(h['symbol'])}）")
            col2.write(plain(h["account"]))
            col3.write(f"{h['shares']:,.0f} 股 @ {h['avg_price']:,.2f}")
            with col4:
                if delete_button(f"del_hold_{h['id']}"):
                    db.delete_holding(h["id"])
                    st.rerun()


def quote_bar() -> None:
    """持股頁最上面一行：現價是什麼時候的、立即更新按鈕、抓不到的原因。"""
    settings = db.get_settings()
    left, right = st.columns([4, 1], vertical_alignment="center")
    status = quote_status()
    if not settings.get("auto_quotes", 1):
        left.caption("股價自動更新已關閉（可以在設定頁打開），現價是手動輸入的。")
    elif status:
        left.caption(f"現價：{status}・每 5 分鐘自動更新，資料來源：證交所、櫃買中心")
    else:
        left.caption("現價還沒自動更新過")
    if right.button("立即更新", icon=":material/refresh:", key="refresh_quotes", width="stretch"):
        refresh_quotes(force=True)
        done("股價已更新")

    result = st.session_state.get("quote_result")
    if result and result.error:
        when = f"（顯示的是 {status} 的價格）" if status else ""
        st.warning(f"現在抓不到股價，可能是網路沒有連線{when}。可以稍後按「立即更新」，或手動修改現價。")
    elif result and result.missing:
        names = "、".join(result.missing)
        st.caption(f"查不到報價：{plain(names)}（例如基金、海外股票或代號打錯），這些請手動修改現價。")


# ---------- 頁面：下單前檢查 ----------

def page_precheck() -> None:
    page_header("下單前檢查", "按下買進之前，先誠實回答這幾題")
    settings = db.get_settings()
    cash = settings["cash_on_hand"]

    # 結論要放在最上面，但得等下面的股價、股數、勾選都讀到才算得出來。
    # st.empty() 先佔一個位置，算完再把內容填進去（有點像 C++ 先宣告變數、晚一點才賦值）
    verdict_slot = st.empty()
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

    # 結論：可以下單用墨藍、先不要下單用橘色（紅綠留給漲跌）
    if ok:
        word, tone = "可以下單", INK
        body = "<p>五項都誠實打勾了，金額也沒有超過帳戶存款合計。</p>"
    else:
        word, tone = "先不要下單", WARN
        body = "<ul>" + "".join(f"<li>{html.escape(r)}</li>" for r in reasons) + "</ul>"
    verdict_slot.markdown(
        f'<div class="verdict"><div class="verdict-word" style="--tone:{tone}">{word}</div>'
        f'<div>{body}</div></div>',
        unsafe_allow_html=True,
    )

    with right:
        with st.container(key="card_precheck_sum"):
            card_title("買完還剩多少")
            after = cash - amount
            # 現金不夠時，剩下的錢用橘色標出來
            after_text = money(after) if after >= 0 else f'<span style="color:{WARN}">{money(after)}</span>'
            ledger([("", "帳戶存款合計", money(cash)),
                    ("", "− 這筆要花", money(amount)),
                    ("", "= 買完還剩", after_text)])

        # 參考資訊：幫你確認打勾的內容是不是真的
        with st.container(key="card_precheck_ref"):
            card_title("參考資訊")
            fund, target = settings["emergency_fund"], settings["emergency_target"]
            status = chip("還沒存滿", WARN) if fund < target else chip("已存滿", INK)
            st.markdown(f"緊急預備金 {money(fund)} / {money(target)}　{status}",
                        unsafe_allow_html=True)
            losing = [f"{plain(m['name'])}（{plain(m['symbol'])}）"
                      for m in analyze(db.get_holdings()) if m["profit"] < 0]
            st.markdown("虧損中的個股：" + ("、".join(losing) if losing else "沒有"))


# ---------- 頁面：交易紀錄 ----------

def page_trades() -> None:
    page_header("交易紀錄", "記下每一筆買賣，也記下當下的想法")

    trades = db.get_trades()
    today = date.today()
    m1, m2, m3 = summary_strip("trades", 3)
    pnl_sum = total_pnl(trades)
    m1.metric("累計損益", signed_money(pnl_sum))
    m2.metric("交易筆數", f"{len(trades)} 筆")
    m3.metric("本月當沖", f"{count_day_trades(trades, today.year, today.month)} 次",
              help="當沖次數越少越好")

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
                    st.warning("請輸入標的")
                else:
                    db.add_trade(trade_date.isoformat(), symbol.strip(), trade_type, pnl, note)
                    done("已新增交易紀錄")

    if not trades:
        st.info("還沒有交易紀錄")
        return

    with st.container(key="card_trade_list"):
        card_title("全部紀錄")
        widths = [2, 2.5, 1.2, 2, 3, 1]
        for col, text in zip(st.columns(widths), ["日期", "標的", "類型", "損益", "備註", ""]):
            col.caption(text)
        # 類型標籤的顏色：當沖用橘色提醒自己，其他用墨藍和灰
        type_colors = {"當沖": WARN, "買進": INK, "賣出": MUTED}
        for t in trades:
            col1, col2, col3, col4, col5, col6 = st.columns(widths, vertical_alignment="center")
            col1.write(t["date"])
            col2.write(plain(t["symbol"]))
            col3.markdown(chip(t["type"], type_colors.get(t["type"], MUTED)),
                          unsafe_allow_html=True)
            col4.markdown(colored_money(t["pnl"]))
            col5.write(plain(t["note"] or ""))
            with col6:
                if delete_button(f"del_trade_{t['id']}"):
                    db.delete_trade(t["id"])
                    st.rerun()


# ---------- 頁面：定期定額試算 ----------

def page_dca() -> None:
    page_header("定期定額試算", "每個月固定投入，時間拉長後會變多少？")

    # 先排好上面摘要列的三個格子，等算出結果再填進去
    c1, c2, c3 = summary_strip("dca", 3)
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

    c1.metric("最後總額", money(final))
    c2.metric("投入本金", money(invested),
              delta=f"賺 {money(final - invested)}" if final > invested else None,
              delta_color="inverse")
    c3.metric("4% 法則每月可領", money(monthly_withdrawal(final)))

    with result_col:
        with st.container(key="card_dca_chart"):
            # 年報酬率是負的時候，資產會比本金少，副標題要跟著改
            card_title("資產成長", "金色是複利多出來的部分" if final >= invested
                       else "金色線是資產，比藍色的本金低代表虧損")
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
            # 資產的線再畫一次、放在最上層：虧損時資產比本金低，不然會被本金的面積蓋住
            asset_line = alt.Chart(chart_data).mark_line(color=GOLD, strokeWidth=2.5).encode(x=x, y="資產:Q")
            show_chart((total_area + principal_area + asset_line).properties(height=320))
            st.caption("假設每月月底投入、年報酬率固定不變。實際報酬每年都會波動，這只是估算。")


# ---------- 頁面：設定 ----------

def page_settings() -> None:
    page_header("設定", "收入和緊急預備金，其他頁面的計算都會用到；現金和銀行存款在「帳戶」頁")
    s = db.get_settings()

    form_col, side_col = st.columns([3, 2])

    with form_col, st.container(key="card_settings_form"):
        card_title("基本資料")
        with st.form("settings", border=False):
            col1, col2 = st.columns(2)
            income = col1.number_input("每月收入", min_value=0.0, step=1000.0, format="%.0f",
                                       value=float(s["monthly_income"]))
            # 手上現金改在「帳戶」頁管理（每個帳戶各自的餘額），這裡不再填
            col2.markdown(f'<div class="big-label">帳戶存款合計</div>'
                          f'<div class="big-num">{money(s["cash_on_hand"])}</div>', unsafe_allow_html=True)
            fund = col1.number_input("緊急預備金（目前存了多少）", min_value=0.0, step=100.0, format="%.0f",
                                     value=float(s["emergency_fund"]))
            target = col2.number_input("預備金目標", min_value=0.0, step=1000.0, format="%.0f",
                                       value=float(s["emergency_target"]))
            if st.form_submit_button("儲存", type="primary", icon=":material/save:"):
                db.save_settings({
                    "monthly_income": income,
                    "emergency_fund": fund,
                    "emergency_target": target,
                })
                done("設定已儲存")

    with side_col:
        # 預備金進度
        if target > 0:
            with st.container(key="card_emergency"):
                card_title("緊急預備金進度")
                note = "已存滿" if fund >= target else f"還差 {money(target - fund)}・已存 {fund / target:.0%}"
                progress_bar("預備金", fund, target, INK, note)

        # --- 股價自動更新 ---
        with st.container(key="card_quotes"):
            card_title("股價自動更新")
            on = st.toggle("打開總覽、持股頁時自動更新現價", value=bool(s.get("auto_quotes", 1)))
            st.caption("會連到證交所查詢報價，只送出股票代號（例如 2330），不會送出股數、金額或其他資料。"
                       "關掉的話不會查股價，現價要自己輸入。")
            st.caption(f"版本 v{APP_VERSION}・每次打開時會到 Onei Hub 伺服器確認是不是最新版"
                       "（只下載公開的軟體清單，不送出任何資料）。")
            if on != bool(s.get("auto_quotes", 1)):
                db.save_settings({"auto_quotes": 1.0 if on else 0.0})
                done("已打開股價自動更新" if on else "已關閉股價自動更新")

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

        # --- 自動備份與還原 ---
        with st.container(key="card_restore"):
            backups = db.list_backups()
            card_title("自動備份", f"每天第一次打開時備份，保留最近 {db.BACKUP_KEEP} 份")
            if "backup_error" in st.session_state:
                st.warning(f"今天的自動備份失敗：{st.session_state['backup_error']}")
            if not backups:
                st.write("還沒有備份。明天打開程式時會自動備份第一份。")
            else:
                choice = st.selectbox("選一份備份", backups, format_func=backup_label)
                with st.popover("還原這份備份", icon=":material/settings_backup_restore:"):
                    st.write(f"目前的資料會被換成「{backup_label(choice)}」那時候的樣子。"
                             "還原前會先把目前的資料另存一份，選錯了還可以再還原回來。")
                    if st.button("確定還原", type="primary"):
                        try:
                            db.restore_backup(choice)
                        except ValueError as e:
                            st.warning(str(e))
                        else:
                            done("已還原備份")
            st.caption(f"資料庫：{short_path(db.DB_PATH)}")
            st.caption(f"備份資料夾：{short_path(db.backup_dir())}")


def short_path(path: str) -> str:
    """把家目錄換成 ~ 顯示，例如 ~\\FinanceApp\\finance.db。

    完整路徑裡有 Windows 的使用者名稱，截圖分享時容易不小心洩漏，所以顯示時縮短。
    """
    path = os.path.abspath(path)
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path


def backup_label(path: str) -> str:
    """備份檔在選單裡的顯示名稱，例如「2026-10-21」「2026-10-21 14:03 還原前」。"""
    name = os.path.splitext(os.path.basename(path))[0]
    stamp = name.split("-", 1)[1]  # 去掉開頭的「finance-」
    if stamp.endswith("-before-restore"):
        d = stamp[:10]
        t = stamp[11:15]
        return f"{d} {t[:2]}:{t[2:]} 還原前的資料"
    return stamp


# ---------- 側邊欄：導覽 ----------

def quick_add() -> None:
    """側邊欄的「記一筆」：不管在哪一頁都能馬上記帳，不用先切到記帳頁。

    記帳是每天最常做的事，步驟越少越容易持續。
    """
    with st.sidebar.popover("記一筆", icon=":material/add:", width="stretch", type="primary"):
        # 和記帳頁同一個表單（record_form），日期固定今天；要補記以前的到記帳頁
        tab_out, tab_in = st.tabs(["支出", "收入"])
        with tab_out:
            record_form("quick_expense", "expense", with_date=False)
        with tab_in:
            record_form("quick_income", "income", with_date=False)


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
        (page_accounts, "帳戶", ":material/account_balance:", "accounts"),
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


def update_gate() -> None:
    """版本太舊時擋住整個程式，只顯示「需要更新」（見 update_check.py）。

    每個視窗只問伺服器一次（結果存在 session_state），之後換頁不會再連線。
    沒網路、問不到時 check() 回傳 None，直接放行。
    放在畫導覽和側邊欄之前，擋住時 st.stop() 讓後面所有東西都不畫，任何一頁都進不去。
    """
    if "update_status" not in st.session_state:
        st.session_state["update_status"] = update_check.check()
    status = st.session_state["update_status"]
    if not status or not status["required"]:
        return

    latest = status["latest"] or status["min"]
    st.markdown(
        '<div class="hero" style="margin-top:2rem"><div><div class="hero-label">OniPulsar 星脈流轉</div>'
        '<div class="hero-num" style="font-size:2.6rem">需要更新</div>'
        f'<div class="hero-note">目前版本 v{html.escape(APP_VERSION)} 已停止使用</div></div>'
        f'<div class="welcome-why">請用 Onei Hub 更新到 v{html.escape(latest)} 才能繼續使用。'
        '你的資料存在 C:\\Users\\你的名字\\FinanceApp，更新不會影響。</div></div>',
        unsafe_allow_html=True,
    )
    col1, col2, _ = st.columns([1, 1, 2])
    if col1.button("用 Onei Hub 更新", type="primary", icon=":material/system_update:", width="stretch"):
        if update_check.open_hub():
            st.toast("已經打開 Onei Hub，請在「OniPulsar 星脈流轉」頁按「需要更新」", icon=":material/check_circle:")
        else:
            st.warning("找不到 Onei Hub，請先按右邊的「下載 Onei Hub」安裝。")
    if col2.button("下載 Onei Hub", icon=":material/download:", width="stretch"):
        update_check.open_download_page()
    st.stop()


update_gate()

# st.navigation 負責「現在在哪一頁」，position="hidden" 表示側邊欄由我們自己畫
pages = {}
PAGES = {}  # 網址名稱 → 頁面，給頁面裡的 st.page_link 用（例如歡迎畫面的「前往設定」）
for group, items in NAV:
    # 總覽是預設頁，網址固定是「/」，所以不另外設 url_path
    pages[group] = [st.Page(func, title=title, icon=icon,
                            url_path=None if url == "overview" else url,
                            default=(url == "overview"))
                    for func, title, icon, url in items]
    for (_, _, _, url), page in zip(items, pages[group]):
        PAGES[url] = page
current = st.navigation(pages, position="hidden")

with st.sidebar:
    # 名稱：OniPulsar 星脈流轉（2026-10-22 使用者取的新名字，原名「個人理財」）
    st.markdown('<div class="brand">OniPulsar</div>'
                '<div class="brand-sub">星脈流轉・資料只存在你的電腦</div>',
                unsafe_allow_html=True)
    for group, group_pages in pages.items():
        st.markdown(f'<div class="nav-group">{group}</div>', unsafe_allow_html=True)
        for p in group_pages:
            st.page_link(p, width="stretch")
    st.markdown('<div style="height:.8rem"></div>', unsafe_allow_html=True)
quick_add()
sidebar_summary()

# 用的不是平常那個資料庫時，每一頁最上面都提醒（見 db.is_unusual_db）：
# 這裡記的資料不會出現在平常打開的程式裡，不提醒的話使用者會以為資料不見了
if db.is_unusual_db():
    st.warning(f"目前使用的資料庫是 {short_path(db.DB_PATH)}，不是平常那一個。"
               "在這裡記的資料，平常打開程式時看不到。", icon=":material/database:")

# 上一次存檔留下的通知（見 done()），顯示一次就拿掉
if "toast" in st.session_state:
    st.toast(st.session_state.pop("toast"), icon=":material/check_circle:")

current.run()  # 執行被選中的頁面函式
