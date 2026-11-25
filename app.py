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
import streamlit.components.v1 as components  # 用來執行一小段 JavaScript（切換頁面時的數字動畫）

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
from models.cards import bill_status, card_cashflow, due_date, month_total, unpaid, unpaid_total
from models.cashflow import monthly_savings, total_debt_payment
from models.debt import add_months, months_left, paid_in_month, payment_this_period, payoff_month
from models.dca import monthly_withdrawal, project
from models.precheck import CHECK_ITEMS, check_order
from models.fees import realized_pnl
from models.goals import (goal_done, goal_totals, item_done, monthly_needed, months_until, parse_item_lines,
                          progress_ratio)
from models.quotes import is_trading_time, normalize_symbol
from models.receivables import collected_ratio, outstanding_total
from version import APP_VERSION
from models.stocks import CONCENTRATION_LIMIT, analyze, over_concentrated, profit_totals
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
CARD_COLOR = "#7A8C99"  # 每月現金流裡「信用卡費」那一段：灰藍（紅綠留給漲跌；只用在圖表，不當文字）

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

# 切換頁面時的金額動畫：頁面上每個「○○○ 元」都從 0 數到目標數字，全部用同一個時間（DURATION）。
# 為什麼用 JavaScript 放在 iframe 裡：st.markdown 會把 <script> 去掉，只能用 components.html 執行。
# iframe 和主頁面同源（Streamlit 允許），所以能用 window.parent 找到主頁面上的數字。
# 只找「整格就是一個金額」的元素（例如 st.metric 的數字、明細列的金額），
# 句子中間夾著的金額（例如「剩 1,000 元・已用 50%」）不動，免得把整句文字改掉。
# __PAGE__ 只是讓 iframe 內容每換一頁就不同（見 app.py 底部的 components.html）。
COUNT_UP_JS = """
<!-- page: __PAGE__ -->
<script>
(function () {
  var DURATION = 900;   // 毫秒。所有金額都用這個時間，數字才會一起跑完
  var WATCH = 2500;     // 換頁後只在這段時間內找新出現的金額，之後不再動（避免按按鈕時亂跳）
  var parentWin = window.parent;
  if (parentWin.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  var doc = parentWin.document;
  // 不用 requestAnimationFrame：iframe 高度是 0，有些瀏覽器會暫停它的畫面更新，數字就會卡在 0。
  // 改用 setTimeout 每約 16 毫秒（一秒約 60 次）算一次，時間用主頁面的 performance.now()
  var now = function () { return parentWin.performance.now(); };
  var raf = function (fn) { setTimeout(function () { fn(now()); }, 16); };
  var pattern = /^([+\\-\\u2212]?)(\\d{1,3}(?:,\\d{3})+|\\d+) 元$/;
  var seen = new WeakSet();

  function countUp(el, sign, target) {
    seen.add(el);
    var start = null;
    function frame(ts) {
      if (start === null) start = ts;
      var p = Math.min((ts - start) / DURATION, 1);
      var eased = 1 - Math.pow(1 - p, 3);   // 先快後慢，結束時比較穩
      el.textContent = sign + Math.round(target * eased).toLocaleString('en-US') + ' 元';
      if (p < 1) raf(frame);
    }
    el.textContent = sign + '0 元';
    raf(frame);
  }


  function scan() {
    var all = doc.querySelectorAll('body *');
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (el.children.length || seen.has(el)) continue;   // 只看最裡面、還沒動過的元素
      var m = pattern.exec(el.textContent.trim());
      if (!m) continue;
      var target = parseInt(m[2].replace(/,/g, ''), 10);
      if (target === 0) continue;                          // 0 元不用動
      countUp(el, m[1] === '\\u2212' ? '-' : m[1], target);
    }
  }

  scan();
  var observer = new MutationObserver(scan);
  observer.observe(doc.body, { childList: true, subtree: true });
  setTimeout(function () { observer.disconnect(); }, WATCH);
})();
</script>
"""


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

/* ---------- 動畫 ----------
   只有幾個動作，每個都對應一個意思，不做「每張卡片依序飛入」這種裝飾：
   1. 印章：打開程式時蓋一次，像存摺封面上的印
   2. 進度條：從 0 長到目前的比例，看得出「走到哪裡」
   3. 結餘、結論：頁面打開時由下浮現
   4. 明細列、按鈕：滑過、按下只給顏色和微小位移的回饋
   Streamlit 每次互動都會整頁重跑，但元素位置沒變時 DOM 不會重建，
   所以入場動畫只在第一次出現時播放，不會每按一下就重播一次。 */
@keyframes seal-stamp {{
    0% {{ opacity: 0; transform: scale(1.6) rotate(-10deg); }}
    60% {{ opacity: 1; transform: scale(.93) rotate(-3deg); }}
    100% {{ opacity: 1; transform: scale(1) rotate(-3deg); }}
}}
@keyframes grow {{ from {{ width: 0; }} }}
@keyframes rise {{ from {{ opacity: 0; transform: translateY(8px); }} }}

section[data-testid="stSidebar"] .seal {{
    display: inline-grid; place-items: center; vertical-align: middle;
    width: 1.8rem; height: 1.8rem; margin-right: .6rem;
    border: 2px solid #E3B866; border-radius: 4px; color: #E3B866;
    font-family: {SERIF}; font-size: 1.05rem; font-weight: 900; line-height: 1;
    animation: seal-stamp .6s cubic-bezier(.3, .7, .3, 1) both;
}}

.budget-fill {{ transition: width .6s cubic-bezier(.2, .7, .2, 1);
                animation: grow .9s cubic-bezier(.2, .7, .2, 1) both; }}
.hero-num, .verdict-word {{ animation: rise .6s ease-out both; }}
.hero-num {{ animation-delay: .1s; }}

/* 明細列：滑過時整列淡淡變色，並用負邊界把文字位置留在原來的對齊線上 */
.ledger {{ margin: 0 -.5rem; }}
.ledger-row {{ padding: 7px .5rem; border-radius: 4px;
               transition: background-color .2s ease; }}
.ledger-row:not(.total):hover {{ background: #E6ECE8; }}

/* 按鈕：按下去微縮，像實體按鍵；顏色變化也要慢一點，不要突然跳色 */
button[kind] {{ transition: transform .15s ease, background-color .2s ease,
                border-color .2s ease, color .2s ease; }}
button[kind]:active {{ transform: scale(.97); }}

/* 側邊欄導覽：滑過時底色淡入，目前頁面的底色不動 */
section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {{
    transition: background-color .2s ease, padding-left .2s ease;
}}
section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover {{
    background-color: rgba(255, 255, 255, .08);
}}

/* 頁首下面一條細線，像存摺每一頁的抬頭 */
.page-head {{ border-bottom: 1px solid #CCD6CF; padding-bottom: .9rem; }}

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

/* 有些人會因為動態畫面不舒服（前庭敏感），系統設定「減少動態效果」時全部關掉 */
@media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
        animation-duration: .01ms !important; animation-iteration-count: 1 !important;
        transition-duration: .01ms !important;
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


def done(message: str, close: str | None = None) -> None:
    """存檔成功後呼叫：記下要顯示的通知，然後立刻重跑整頁。

    為什麼一定要重跑：
    - 側邊欄的摘要在頁面內容之前就畫好了，不重跑會顯示存檔前的舊數字。
    - 沒有 key 的輸入框會把「預設值」算進自己的身分；資料庫的值變了卻不重跑，
      下一次輸入的數字會被當成另一個輸入框而丟掉（連按兩次「儲存」，第二次會沒存到）。
    通知先放進 st.session_state（重跑之間會保留的字典），重跑後由主程式用 st.toast 顯示。
    不用 st.success：它是綠色，而綠色在這個 app 代表「賠錢」。
    close 是要順便關掉的小視窗的 key（見 closable_popover）。
    """
    st.session_state["toast"] = message
    if close:
        st.session_state["close_popover"] = close
    st.rerun()


def closable_popover(label: str, key: str, **kwargs):
    """可以用程式關掉的小視窗（st.popover）：done(訊息, close=key) 之後，重跑時這個小視窗會是關的。

    為什麼不能在 done() 裡直接寫 st.session_state[key] = False：
    Streamlit 不准在元件「畫出來之後」改它的狀態（會丟例外），所以先記下要關哪一個，
    重跑時在畫出來「之前」改成關的。on_change="rerun" 加上 key，Streamlit 才會記住開關狀態、讓程式改。
    """
    if st.session_state.get("close_popover") == key:
        del st.session_state["close_popover"]
        st.session_state[key] = False
    return st.popover(label, key=key, on_change="rerun", **kwargs)


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


def card_names() -> dict[int, str]:
    """{信用卡 id: 名稱}，明細列表顯示「用哪張卡刷的」用。"""
    return {c["id"]: c["name"] for c in db.get_cards()}


def account_select(label: str, key: str | None = None, allow_none: bool = False,
                   default: int | None = None, none_label: str = "不屬於任何帳戶") -> int | None:
    """選帳戶的下拉選單，旁邊顯示目前餘額。回傳帳戶 id。

    選項用 id（數字）而不是整個帳戶資料：餘額變了選項也不會變，選到的帳戶不會被重設。
    allow_none=True 時多一個「不屬於任何帳戶」（舊的記帳沒有帳戶，修改時要能保持原狀），
    這個選項的文字可以用 none_label 換掉。
    """
    accounts = {a["id"]: a for a in db.get_accounts()}
    ids = list(accounts) + ([None] if allow_none else [])
    index = ids.index(default) if default in ids else 0
    return st.selectbox(
        label, ids, index=index, key=key,
        format_func=lambda i: none_label if i is None
        else f"{accounts[i]['name']}（{money(accounts[i]['balance'])}）",
    )


def payer_select(label: str, key: str | None = None, allow_none: bool = False,
                 account_id: int | None = None, card_id: int | None = None) -> tuple[int | None, int | None]:
    """支出「從哪裡付」的下拉選單：帳戶（旁邊顯示餘額）和信用卡放在同一個選單。回傳 (帳戶 id, 卡 id)，只有一個不是 None。

    選項是 ("account", id) 或 ("card", id) 這種 tuple：tuple 可以直接當選項，
    跟 C++ 的 std::pair 一樣，比把兩種 id 混成一個字串再拆開清楚。
    刷卡的支出不扣帳戶，加到那張卡下個月的帳單。
    """
    accounts = {a["id"]: a for a in db.get_accounts()}
    cards = {c["id"]: c["name"] for c in db.get_cards()}
    options = [("account", i) for i in accounts] + [("card", i) for i in cards]
    if allow_none:
        options.append(("account", None))
    current = ("card", card_id) if card_id is not None else ("account", account_id)
    index = options.index(current) if current in options else 0

    def label_of(option: tuple[str, int | None]) -> str:
        kind, i = option
        if i is None:
            return "不屬於任何帳戶"
        if kind == "card":
            return f"💳 {cards[i]}（刷卡，算進下個月帳單）"
        return f"{accounts[i]['name']}（{money(accounts[i]['balance'])}）"

    kind, i = st.selectbox(label, options, index=index, key=key, format_func=label_of)
    return (None, i) if kind == "card" else (i, None)


def record_form(key: str, kind: str, with_date: bool = True) -> None:
    """新增一筆記帳的表單（記帳頁和側邊欄「記一筆」共用）。kind 是 "expense" 或 "income"。

    類別是「主類別 · 細項」攤平的一個選單（見 models/budget.py 的 category_options），
    因為表單裡選了主類別不會馬上更新第二個選單。記下來時同時更新選到的帳戶餘額。
    """
    income = kind == "income"
    with st.form(key, clear_on_submit=True, border=False):
        amount = st.number_input("金額", min_value=0.0, step=10.0, format="%.0f")
        option = st.selectbox("類別", category_options(kind))
        if income:
            account_id, card_id = account_select("存入帳戶"), None
        else:
            account_id, card_id = payer_select("從哪裡付（帳戶或信用卡）")
        when = st.date_input("日期", value=date.today()) if with_date else date.today()
        note = st.text_input("備註（可不填）")
        submitted = st.form_submit_button("記下來", type="primary", icon=":material/check:", width="stretch")
    if submitted:
        if amount <= 0:
            st.warning("金額要大於 0")
        else:
            main, sub = split_option(option)
            db.add_expense(amount, main, when.isoformat(), note, subcategory=sub, account_id=account_id, kind=kind,
                           card_id=card_id)
            payer = card_names()[card_id] + " 刷卡" if card_id else account_names()[account_id]
            done(f"已記下{'收入' if income else ''}：{option} {money(amount)}（{plain(payer)}）")


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
    total_profit = profit_totals(analyzed)[0]  # 沒填均價的個股不算進損益
    debts = db.get_debts()
    total_debt = sum(d["remaining"] for d in debts)
    # 別人欠我的錢遲早會回來，算資產；還沒繳的卡費是已經花掉的錢，算負債
    receivable = outstanding_total(db.get_receivables())
    card_bills = db.get_card_bills()
    card_unpaid = unpaid_total(card_bills)
    networth = cash + total_value + receivable - total_debt - card_unpaid

    # --- 結餘：整個 app 的主角。左邊一個大數字，右邊是它怎麼算出來的 ---
    stock_label = "+ 股票市值"
    if total_profit:
        stock_label += f'<span class="sub">損益 {colored_money_html(total_profit)}</span>'
    if analyzed and quote_status():
        stock_label += f'<span class="sub" style="color:{MUTED}">{quote_status()}</span>'
    rows = [("", "帳戶存款", money(cash)), ("", stock_label, money(total_value))]
    # 沒用到的項目不顯示，免得多一排 0 元
    if receivable:
        rows.append(("", "+ 別人欠我", money(receivable)))
    rows.append(("", "− 負債餘額", money(total_debt)))
    if card_unpaid:
        rows.append(("", "− 未繳卡費", money(card_unpaid)))
    hero_rows = ledger_html(rows, total=False)
    st.markdown(
        f'<div class="hero"><div><div class="hero-label">淨資產</div>'
        f'<div class="hero-num">{networth:,.0f}<small>元</small></div>'
        f'<div class="hero-note">{today.year} 年 {today.month} 月 {today.day} 日的結餘</div></div>'
        f'{hero_rows}</div>',
        unsafe_allow_html=True,
    )
    # 每次打開總覽就記下今天的淨資產（同一天會覆蓋），累積起來就是下面的「淨資產變化」
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
    alerts += card_bill_alerts(card_bills, today)
    notices(alerts)

    # --- 每月現金流 + 持股占比 ---
    income = settings["monthly_income"]
    fixed_total = sum(item["amount"] for item in db.get_fixed_expenses())
    debt_payment = total_debt_payment(debts)
    living = sum(db.get_budgets().values())
    # 這個月的卡費，扣掉記帳刷卡的部分（那些已經算在生活預算裡了，見 models/cards.card_cashflow）
    card_month = card_cashflow(card_bills, db.get_card_records(), today.isoformat()[:7])
    savings = monthly_savings(income, fixed_total, debt_payment, living, card_month)

    left, right = st.columns([3, 2])
    with left, st.container(key="card_cashflow"):
        card_title("每月現金流", "收入都花到哪裡去")
        # 一條橫的長條，把收入切成五段；入不敷出時沒有「可存」那一段
        parts = pd.DataFrame({
            "項目": ["固定支出", "負債還款", "信用卡費", "生活預算", "每月可存"],
            "金額": [fixed_total, debt_payment, card_month, living, max(savings, 0)],
            "順序": [1, 2, 3, 4, 5],
        })
        bar = alt.Chart(parts).mark_bar(height=26, cornerRadius=4).encode(
            # 長條的總長度固定是「收入」，四段加起來剛好填滿
            x=alt.X("金額:Q", stack="zero", axis=None,
                    scale=alt.Scale(domain=[0, max(income, parts["金額"].sum(), 1)], nice=False)),
            color=alt.Color("項目:N", sort=list(parts["項目"]), legend=None,
                            scale=alt.Scale(range=["#6C8EBF", "#8A6FB0", CARD_COLOR, "#B7B1A5", GOLD])),
            order="順序:Q",
            tooltip=["項目:N", alt.Tooltip("金額:Q", format=",.0f")],
        ).properties(height=44)
        show_chart(bar)
        ledger([
            ("", "收入", money(income)),
            ("#6C8EBF", "− 固定支出", money(fixed_total)),
            ("#8A6FB0", "− 負債還款", money(debt_payment)),
            (CARD_COLOR, f"− 信用卡費<span class=\"sub\">{today.month} 月帳單裡記帳沒記到的</span>", money(card_month)),
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

    goals_overview(today, savings if income > 0 else None)
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


def goals_overview(today: date, savings: float | None) -> None:
    """總覽的「儲蓄目標」卡片：還沒達成的目標各一條進度條，再跟每月可存比一比。

    savings 是每月可存；還沒填收入時是 None，就不比（收入 0 元時每個目標都會「存不夠」，沒有意義）。
    沒有任何目標時整張卡片不顯示，總覽不多一塊空的。
    """
    goals = db.get_goals()
    if not goals:
        return
    active = [g for g in goals if not goal_done(g["items"])]
    finished = len(goals) - len(active)
    total_need = 0.0
    rows = []
    for g in active:
        totals = goal_totals(g["items"])
        deadline = date.fromisoformat(g["deadline"]) if g["deadline"] else None
        need = monthly_needed(totals["remaining"], months_until(today, deadline))
        total_need += need or 0.0
        rows.append((g, totals, need, deadline))

    with st.container(key="card_goals_overview"):
        note = f"每月共要存 {money(total_need)}" if total_need else ""
        if finished:
            note += ("・" if note else "") + f"已達成 {finished} 個"
        card_title("儲蓄目標", note)
        if not active:
            st.caption("所有目標都達成了！")
        for g, totals, need, deadline in rows:
            label = html.escape(g["name"])
            if deadline:
                # .sub 的間距只在明細列裡有效，這裡在進度條標題裡，所以直接寫樣式
                label += (f'<span style="color:{MUTED};font-weight:400;font-size:.82rem;margin-left:.5rem">'
                          f'{deadline.year}/{deadline.month}/{deadline.day} 截止</span>')
            progress_bar(label, totals["target"] - totals["remaining"], totals["target"], INK,
                         goal_note(totals, False, need), totals["ratio"])
        # 目標每月要存的，比每月可存還多：照現在的收支存不到，提早知道才能調整預算或延後截止日
        if savings is not None and total_need > max(savings, 0):
            notices([("目標", f"儲蓄目標每月共要存 {money(total_need)}，比每月可存 {money(savings)} "
                              f"多 {money(total_need - max(savings, 0))}。可以減少生活預算，或把截止日往後延。", WARN)])
        st.page_link(PAGES["goals"], label="前往儲蓄目標", icon=":material/arrow_forward:")


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
            cards = card_names()
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
                if e["card_id"] is not None:
                    col4.write("💳 " + plain(cards.get(e["card_id"], "信用卡")))
                else:
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
            if e["kind"] == "income":
                account_id, card_id = account_select("帳戶", allow_none=True, default=e["account_id"]), None
            else:
                account_id, card_id = payer_select("從哪裡付", allow_none=True,
                                                   account_id=e["account_id"], card_id=e["card_id"])
            new_date = st.date_input("日期", value=date.fromisoformat(e["date"]))
            note = st.text_input("備註", value=e["note"] or "")
            if st.form_submit_button("儲存", type="primary", icon=":material/save:"):
                if amount <= 0:
                    st.warning("金額要大於 0")
                else:
                    main, sub = split_option(option)
                    db.update_expense(e["id"], amount, main, new_date.isoformat(), note,
                                      subcategory=sub, account_id=account_id, card_id=card_id)
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


# ---------- 頁面：別人欠我 ----------

def page_receivables() -> None:
    """別人欠我的錢：借給朋友、幫人代墊。收回一筆時存進選的帳戶，總覽的淨資產會把還沒收回的加進去。"""
    page_header("別人欠我", "借出去、幫人代墊的錢；收回一筆就記一筆，看還差多少")

    items = db.get_receivables()
    m1, m2, m3 = summary_strip("receivables", 3)
    m1.metric("還沒收回", money(outstanding_total(items)), help="總覽的淨資產會加上這個數字")
    m2.metric("已經收回", money(sum(i["amount"] - i["remaining"] for i in items)))
    m3.metric("還沒收完", f"{sum(1 for i in items if i['remaining'] > 0)} 筆")

    list_col, form_col = st.columns([3, 2])

    with form_col, st.container(key="card_add_receivable"):
        card_title("記一筆別人欠我的")
        with st.form("add_receivable", clear_on_submit=True, border=False):
            name = st.text_input("誰、什麼事（例如 小明 借去繳房租、幫同事代墊午餐）")
            amount = st.number_input("金額", min_value=0.0, step=100.0, format="%.0f")
            when = st.date_input("借出日期", value=date.today())
            # 預設「不動帳戶」：第一次用通常是補記以前借的，那時候帳戶早就扣過了，再扣一次會算錯
            account_id = account_select("錢從哪個帳戶借出", allow_none=True, default=None,
                                        none_label="以前借的，不動帳戶餘額")
            note = st.text_input("備註（可不填）")
            if st.form_submit_button("記下來", type="primary", icon=":material/add:"):
                name = name.strip()
                if not name:
                    st.warning("請輸入是誰、什麼事")
                elif amount <= 0:
                    st.warning("金額要大於 0")
                else:
                    try:
                        db.add_receivable(name, amount, when.isoformat(), note.strip(), account_id)
                    except ValueError as e:  # 帳戶餘額不夠
                        st.warning(str(e))
                    else:
                        done(f"已記下：{plain(name)} 欠 {money(amount)}")

    with list_col:
        if not items:
            st.info("目前沒有人欠你錢")
            return
        # 所有「收回」都存進這個帳戶（跟負債頁的還款帳戶一樣，放在最上面一個就好）
        account_id = account_select("收回的錢存進哪個帳戶", key="receivable_account")
        names = account_names()
        for r in items:
            with st.container(key=f"card_receivable_{r['id']}"):
                receivable_card(r, account_id, names)


def receivable_card(r: dict, account_id: int, names: dict[int, str]) -> None:
    """一筆別人欠我的錢：收回進度、「收回」按鈕、收款紀錄。"""
    payments = db.get_receivable_payments(r["id"])
    collected = r["amount"] - r["remaining"]
    status = chip("已收完", GOLD_TEXT) if r["remaining"] <= 0 else chip(f"{r['date'].replace('-', '/')} 借出", INK)
    st.markdown(f'<div class="card-title">{html.escape(r["name"])}　{status}</div>', unsafe_allow_html=True)
    if r["note"]:
        st.caption(plain(r["note"]))
    progress_bar("收回進度", collected, r["amount"], INK,
                 f"還差 {money(r['remaining'])}・已收回 {collected_ratio(r['amount'], r['remaining']):.0%}",
                 collected_ratio(r["amount"], r["remaining"]))

    b1, b2 = st.columns([3, 1])
    if r["remaining"] > 0:
        with b1, st.popover("收回一筆", icon=":material/savings:"):
            with st.form(f"collect_{r['id']}", border=False):
                # 預設就是全部收回，部分還款再自己改
                amount = st.number_input("這次收回多少", min_value=0.0, max_value=float(r["remaining"]),
                                         value=float(r["remaining"]), step=100.0, format="%.0f")
                if st.form_submit_button("收回", type="primary", icon=":material/check:"):
                    try:
                        got = db.collect_receivable(r["id"], amount, account_id)
                    except ValueError as e:
                        st.warning(str(e))
                    else:
                        done(f"已收回 {money(got)}，存進「{plain(names[account_id])}」")
    with b2:
        if delete_button(f"del_receivable_{r['id']}"):
            db.delete_receivable(r["id"])
            st.rerun()
    if payments:
        with st.expander(f"收款紀錄（{len(payments)} 筆，共 {money(collected)}）"):
            rows = [("", f'{p["date"]}<span class="sub">{html.escape(names.get(p["account_id"], ""))}</span>',
                     money(p["amount"])) for p in payments[:24]]
            st.markdown(ledger_html(rows, total=False), unsafe_allow_html=True)


# ---------- 頁面：儲蓄目標 ----------

def page_goals() -> None:
    """儲蓄目標：像任務清單，每個目標點開後列出細項，各自存、各自看進度。

    存進目標預設只是「把錢記到這個目標名下」，不動帳戶、不影響淨資產（錢還在銀行帳戶裡）。
    目標指定了「旅費放在哪個帳戶」時，存入可以順便從別的帳戶轉過去（只是帳戶之間搬錢，淨資產也不變）。
    """
    page_header("儲蓄目標", "像任務一樣：一個目標拆成幾個細項，存一筆記一筆，各自看進度")

    goals = db.get_goals()
    # 達成的移到後面，進行中的在前面（sorted 是穩定排序：同一組裡維持建立順序）
    goals = sorted(goals, key=lambda g: goal_done(g["items"]))
    earmarked = sum(goal_totals(g["items"])["saved"] for g in goals)
    cash = db.get_settings()["cash_on_hand"]

    m1, m2, m3 = summary_strip("goals", 3)
    m1.metric("已存進目標", money(earmarked))
    m2.metric("還差", money(sum(goal_totals(g["items"])["remaining"] for g in goals)))
    m3.metric("帳戶裡還沒分配", money(cash - earmarked),
              help="帳戶合計減掉已存進目標的錢，看還有多少錢沒有指定用途。順便轉帳只是帳戶之間搬錢，合計不變")
    if earmarked > cash:
        notices([("注意", f"存進目標的錢（{money(earmarked)}）比帳戶合計（{money(cash)}）還多，"
                          "可能有錢已經花掉了，記得到目標裡「取出」。", WARN)])

    list_col, form_col = st.columns([3, 2])

    with form_col, st.container(key="card_add_goal"):
        card_title("新增目標")
        with st.form("add_goal", clear_on_submit=True, border=False):
            name = st.text_input("目標名稱（例如 日本旅遊）")
            deadline = st.date_input("截止日（例如出發日，可不填）", value=None, min_value=date.today())
            lines = st.text_area("細項：一行一個，名稱 空格 金額",
                                 placeholder="來回機票 12000\n住宿 15000\n交通 4000\n吃飯購物 20000")
            # 預設不指定：只是記在目標名下。想把旅費分開放，先到帳戶頁開一個「旅費」帳戶再選它
            account_id = account_select("旅費放在哪個帳戶（可不選）", key="goal_account", allow_none=True,
                                        default=None, none_label="不指定，只記在目標名下")
            note = st.text_input("備註（可不填）")
            if st.form_submit_button("建立目標", type="primary", icon=":material/add:"):
                items, bad = parse_item_lines(lines)
                name = name.strip()
                if not name:
                    st.warning("請輸入目標名稱")
                elif bad:
                    st.warning("這幾行看不懂，請寫成「名稱 金額」：" + "、".join(plain(b) for b in bad))
                else:
                    goal_id = db.add_goal(name, deadline.isoformat() if deadline else None, note.strip(), account_id)
                    for item_name, target in items:
                        db.add_goal_item(goal_id, item_name, target)
                    done(f"已建立目標：{plain(name)}（{len(items)} 個細項）")

    with list_col:
        if not goals:
            st.info("還沒有儲蓄目標。在右邊建立一個，例如「日本旅遊」，再列出機票、住宿這些細項。")
            return
        names = account_names()
        for g in goals:
            goal_card(g, names)


def goal_note(totals: dict, finished: bool, need: float | None) -> str:
    """目標進度條下面的小字（儲蓄目標頁和總覽共用，兩邊說法才一致）。"""
    if finished:
        return f'<span style="color:{GOLD_TEXT};font-weight:600">全部細項都存到了</span>'
    if need is not None:
        return f"還差 {money(totals['remaining'])}・每月存 {money(need)} 就來得及"
    return f"還差 {money(totals['remaining'])}"


def goal_card(g: dict, names: dict[int, str]) -> None:
    """一個目標：可以點開的區塊（st.expander）。標題列就看得到整體進度，點開看細項。"""
    items = g["items"]
    totals = goal_totals(items)
    finished = goal_done(items)
    deadline = date.fromisoformat(g["deadline"]) if g["deadline"] else None
    label = f"{plain(g['name'])}　{money(totals['saved'])} / {money(totals['target'])}・{totals['ratio']:.0%}"
    # key 固定用目標的 id：標題裡的金額每存一筆就會變，沒有 key 的話 Streamlit 會當成新的區塊而自動收起來
    with st.expander(label, key=f"goal_{g['id']}", icon=":material/task_alt:" if finished else ":material/flag:"):
        # 截止日、每月要存多少
        months = months_until(date.today(), deadline)
        need = monthly_needed(totals["remaining"], months)
        if finished:
            tags = chip("已達成", GOLD_TEXT)
        elif deadline and months == 0:
            tags = chip(f"{deadline:%Y/%m/%d} 已過", WARN)
        elif deadline:
            tags = chip(f"{deadline:%Y/%m/%d} 截止・剩 {months} 個月", INK)
        else:
            tags = chip("沒有截止日", MUTED)
        if g["account_id"] in names:
            tags += " " + chip(f"放在 {names[g['account_id']]}", INK)  # chip() 自己會 html.escape
        st.markdown(tags, unsafe_allow_html=True)
        if g["note"]:
            st.caption(plain(g["note"]))

        progress_bar("整體進度", totals["target"] - totals["remaining"], totals["target"],
                     GOLD if finished else INK, goal_note(totals, finished, need), totals["ratio"])

        st.markdown('<div class="card-title" style="margin-top:.8rem">細項</div>', unsafe_allow_html=True)
        if not items:
            st.caption("還沒有細項，在下面加一個。")
        for item in items:
            goal_item_row(item, months, g["account_id"] if g["account_id"] in names else None, names)

        # 加細項：一行排開，名稱、金額、按鈕
        with st.form(f"add_item_{g['id']}", clear_on_submit=True, border=False):
            c1, c2, c3 = st.columns([3, 2, 1.4], vertical_alignment="bottom")
            item_name = c1.text_input("新增細項", placeholder="例如 網卡、保險")
            target = c2.number_input("目標金額", min_value=0.0, step=1000.0, format="%.0f")
            if c3.form_submit_button("加上", icon=":material/add:"):
                if not item_name.strip():
                    st.warning("請輸入細項名稱")
                else:
                    db.add_goal_item(g["id"], item_name.strip(), target)
                    done(f"已加上細項：{plain(item_name.strip())}")

        with st.popover("修改這個目標", icon=":material/edit:"):
            with st.form(f"edit_goal_{g['id']}", border=False):
                new_name = st.text_input("目標名稱", value=g["name"])
                new_deadline = st.date_input("截止日（可不填）", value=deadline)
                new_note = st.text_input("備註", value=g["note"] or "")
                new_account = account_select("旅費放在哪個帳戶", key=f"goal_account_{g['id']}", allow_none=True,
                                             default=g["account_id"], none_label="不指定，只記在目標名下")
                st.caption("換帳戶不會搬動已經存的錢，要搬的話到帳戶頁轉帳。")
                if st.form_submit_button("儲存", type="primary"):
                    if not new_name.strip():
                        st.warning("請輸入目標名稱")
                    else:
                        db.update_goal(g["id"], new_name.strip(),
                                       new_deadline.isoformat() if new_deadline else None, new_note.strip(),
                                       new_account)
                        done("已修改目標")
            st.divider()
            st.caption("刪除會連同所有細項和存入紀錄一起刪掉。帳戶餘額不會變：轉進旅費帳戶的錢還在那個帳戶裡。")
            if st.button("刪除這個目標", key=f"del_goal_{g['id']}", icon=":material/delete:"):
                db.delete_goal(g["id"])
                done(f"已刪除目標：{plain(g['name'])}")


def goal_item_row(item: dict, months: int | None, goal_account: int | None, names: dict[int, str]) -> None:
    """一個細項：進度條，加上「存入／取出」和「紀錄・修改」兩個小視窗（st.popover）。

    一個細項只放兩個按鈕：放五個（存入、取出、修改、刪除、紀錄）在手機上會擠成一團。
    goal_account 是目標的旅費帳戶（沒指定是 None），有的話存入表單多一個「順便轉帳」。
    """
    saved, target = item["saved"], item["target"]
    left = max(target - saved, 0.0)
    if item_done(saved, target):
        color = GOLD
        note = f'<span style="color:{GOLD_TEXT};font-weight:600">已達成</span>'
        if saved > target:
            note += f"・多存了 {money(saved - target)}"
    else:
        color = INK
        need = monthly_needed(left, months)
        note = f"還差 {money(left)}・{progress_ratio(saved, target):.0%}"
        if need is not None:
            note += f"・每月 {money(need)}"
    progress_bar(html.escape(item["name"]), saved, target, color, note, progress_ratio(saved, target))

    b1, b2 = st.columns(2)
    deposit_popover = f"deposit_popover_{item['id']}"
    with b1, closable_popover("存入／取出", deposit_popover, icon=":material/savings:", width="stretch"):
        with st.form(f"deposit_{item['id']}", border=False):
            kind = st.radio("要做什麼", ["存入", "取出"], horizontal=True)
            # 預設金額：存入是「還差多少」，一次存滿；部分存入再自己改
            amount = st.number_input("金額", min_value=0.0, value=float(left), step=100.0, format="%.0f")
            when = st.date_input("日期", value=date.today())
            from_account = None
            if goal_account is not None:
                # 表單裡選了「存入／取出」不會馬上重跑，所以說明文字兩個方向都寫
                others = [i for i in names if i != goal_account]
                balances = {a["id"]: a["balance"] for a in db.get_accounts()}
                from_account = st.selectbox(
                    f"順便轉帳（存入：轉進「{names[goal_account]}」；取出：轉回這個帳戶）",
                    [None] + others,
                    format_func=lambda i: "不轉帳，錢已經在旅費帳戶" if i is None
                    else f"{names[i]}（{money(balances[i])}）",
                )
            dep_note = st.text_input("備註（可不填）")
            if st.form_submit_button("記下來", type="primary", icon=":material/check:"):
                if amount <= 0:
                    st.warning("金額要大於 0")
                else:
                    try:
                        got = db.deposit_goal_item(item["id"], amount if kind == "存入" else -amount,
                                                   when.isoformat(), dep_note.strip(), from_account)
                    except ValueError as e:  # 餘額不夠、沒存過不能取出
                        st.warning(str(e))
                    else:
                        moved = ""
                        if from_account is not None:
                            src, dst = ((from_account, goal_account) if got > 0 else (goal_account, from_account))
                            moved = f"（{plain(names[src])} → {plain(names[dst])}）"
                        # 存完就關掉小視窗：不關的話它還開著、金額變成新的「還差多少」，容易以為沒存到又按一次
                        done(f"{plain(item['name'])}：已{kind} {money(abs(got))}{moved}", close=deposit_popover)
    with b2, st.popover("紀錄・修改", icon=":material/more_horiz:", width="stretch"):
        deposits = db.get_goal_deposits(item["id"])
        if deposits:
            rows = [("", f'{d["date"]}<span class="sub" style="color:{MUTED}">{deposit_detail(d, names)}</span>',
                     signed_money(d["amount"])) for d in deposits[:30]]
            st.markdown(ledger_html(rows, total=False), unsafe_allow_html=True)
        else:
            st.caption("還沒有存入紀錄")
        with st.form(f"edit_item_{item['id']}", border=False):
            new_name = st.text_input("細項名稱", value=item["name"])
            new_target = st.number_input("目標金額", min_value=0.0, value=float(target), step=1000.0, format="%.0f")
            if st.form_submit_button("儲存"):
                if not new_name.strip():
                    st.warning("請輸入細項名稱")
                else:
                    db.update_goal_item(item["id"], new_name.strip(), new_target)
                    done("已修改細項")
        if st.button("刪除這個細項", key=f"del_item_{item['id']}", icon=":material/delete:"):
            db.delete_goal_item(item["id"])
            done(f"已刪除細項：{plain(item['name'])}")


def deposit_detail(d: dict, names: dict[int, str]) -> str:
    """存入紀錄旁邊的灰字：有轉帳時寫「從 現金 轉入」「轉回 現金」，再接備註。回傳 HTML（已 escape）。"""
    parts = []
    if d["from_account_id"] in names:
        account = html.escape(names[d["from_account_id"]])
        parts.append(f"從 {account} 轉入" if d["amount"] > 0 else f"轉回 {account}")
    if d["note"]:
        parts.append(html.escape(d["note"]))
    return "・".join(parts)


# ---------- 頁面：信用卡 ----------

# 帳單狀態 → (文字, 顏色)。過期用橘色、快到期用金色（紅綠留給漲跌）
BILL_STATUS = {
    "paid": ("已繳清", GOLD_TEXT),
    "overdue": ("過了繳款日", WARN),
    "due_soon": ("快到繳款日", GOLD_TEXT),
    "upcoming": ("還沒繳", INK),
}


def month_label(month: str) -> str:
    """'2026-11' → '2026 年 11 月'。"""
    return f"{month[:4]} 年 {int(month[5:])} 月"


def card_bill_alerts(bills: list[dict], today: date) -> list[tuple[str, str, str]]:
    """過了繳款日、或快到繳款日還沒繳清的帳單，給 notices() 用（總覽頁和信用卡頁共用）。"""
    alerts = []
    for b in bills:
        due = due_date(b["month"], b["due_day"])
        status = bill_status(b["amount"], b["paid"], due, today)
        if status in ("overdue", "due_soon"):
            text, color = BILL_STATUS[status]
            alerts.append(("卡費", f"{html.escape(b['card_name'])} {month_label(b['month'])}帳單還有 "
                                   f"{money(unpaid(b['amount'], b['paid']))} 沒繳，{due.month}/{due.day} 截止（{text}）。",
                           color))
    return alerts


def page_cards() -> None:
    """信用卡費：每張卡每月填一次帳單金額，繳的時候從帳戶扣。

    刻意不放進記帳和固定支出：刷卡的花費如果已經記過帳，繳卡費再記成支出就重複算了；
    卡費每個月也不一樣，不是固定支出。
    """
    today = date.today()
    this_month = today.isoformat()[:7]
    page_header("信用卡", "每張卡每月填一次帳單金額，繳費時從帳戶扣；快到繳款日會提醒")

    cards = db.get_cards()
    bills = db.get_card_bills()
    m1, m2, m3 = summary_strip("cards", 3)
    m1.metric("還沒繳的卡費", money(unpaid_total(bills)), help="總覽的淨資產會減掉這個數字")
    m2.metric(f"{today.month} 月帳單合計", money(month_total(bills, this_month)),
              help="記帳刷卡的部分已經算在生活預算裡，每月現金流只扣其他的")
    m3.metric("信用卡", f"{len(cards)} 張")
    alerts = card_bill_alerts(bills, today)
    if alerts:
        notices(alerts)

    list_col, form_col = st.columns([3, 2])

    with form_col:
        if cards:
            with st.container(key="card_set_bill"):
                card_title("填帳單金額", "同一個月再填一次就是修改")
                # 選項是上個月、這個月、下個月（收到帳單通常是在繳款月的前一個月）
                months = []
                for n in (1, 0, -1):
                    y, m = add_months(today, n)
                    months.append(f"{y:04d}-{m:02d}")
                card_names = {c["id"]: c["name"] for c in cards}
                with st.form("set_bill", clear_on_submit=True, border=False):
                    card_id = st.selectbox("哪張卡", list(card_names), format_func=lambda i: card_names[i])
                    month = st.selectbox("哪個月要繳", months, index=1, format_func=month_label)
                    amount = st.number_input("帳單金額", min_value=0.0, step=100.0, format="%.0f")
                    if st.form_submit_button("儲存", type="primary", icon=":material/save:"):
                        if amount <= 0:
                            st.warning("金額要大於 0")
                        else:
                            db.set_card_bill(card_id, month, amount)
                            done(f"已記下：{plain(card_names[card_id])} {month_label(month)} {money(amount)}")

        with st.container(key="card_add_card"):
            card_title("新增信用卡")
            with st.form("add_card", clear_on_submit=True, border=False):
                name = st.text_input("名稱（例如 A 銀行卡）")
                due_day = st.number_input("每月幾號以前要繳", min_value=1, max_value=31, value=15, step=1)
                if st.form_submit_button("新增", type="primary", icon=":material/add:"):
                    name = name.strip()
                    if not name:
                        st.warning("請輸入名稱")
                    else:
                        db.add_card(name, int(due_day))
                        done(f"已新增：{plain(name)}")

    with list_col:
        if not cards:
            st.info("還沒有信用卡")
            return
        account_id = account_select("卡費從哪個帳戶扣", key="card_pay_account")
        names = account_names()
        for c in cards:
            with st.container(key=f"card_cc_{c['id']}"):
                credit_card(c, [b for b in bills if b["card_id"] == c["id"]], account_id, names, today)


def credit_card(c: dict, bills: list[dict], account_id: int, names: dict[int, str], today: date) -> None:
    """一張信用卡：還沒繳清的帳單各一列（可以繳清或繳一部分），繳清的收在「過去的帳單」。"""
    due_chip = chip(f"每月 {c['due_day']} 號繳", MUTED)
    st.markdown(f'<div class="card-title">{html.escape(c["name"])}　{due_chip}</div>', unsafe_allow_html=True)
    open_bills = [b for b in bills if unpaid(b["amount"], b["paid"]) > 0][::-1]  # 舊的先繳
    paid_bills = [b for b in bills if unpaid(b["amount"], b["paid"]) <= 0]
    if not open_bills:
        st.caption("目前沒有要繳的帳單" if bills else "還沒填過帳單，從右邊「填帳單金額」開始")

    for b in open_bills:
        due = due_date(b["month"], b["due_day"])
        text, color = BILL_STATUS[bill_status(b["amount"], b["paid"], due, today)]
        left = unpaid(b["amount"], b["paid"])
        col1, col2 = st.columns(2)
        col1.markdown(big_number(f"{month_label(b['month'])}帳單", money(b["amount"])), unsafe_allow_html=True)
        col2.markdown(big_number("還要繳", money(left)), unsafe_allow_html=True)
        st.markdown(chip(f"{due.month}/{due.day} 截止・{text}", color)
                    + (f'<span class="sub">　已繳 {money(b["paid"])}</span>' if b["paid"] else ""),
                    unsafe_allow_html=True)
        b1, b2, b3 = st.columns([2, 2, 1])
        with b1:
            if st.button(f"繳清（{money(left)}）", key=f"pay_bill_{b['id']}", type="primary",
                         icon=":material/check:"):
                pay_card_bill(b["id"], left, account_id, names)
        with b2, st.popover("繳一部分", icon=":material/payments:"):
            with st.form(f"pay_bill_part_{b['id']}", border=False):
                amount = st.number_input("這次繳多少", min_value=0.0, max_value=float(left),
                                         step=100.0, format="%.0f")
                if st.form_submit_button("繳費", type="primary", icon=":material/check:"):
                    if amount <= 0:
                        st.warning("金額要大於 0")
                    else:
                        pay_card_bill(b["id"], amount, account_id, names)
        with b3:
            if delete_button(f"del_bill_{b['id']}", ""):
                db.delete_card_bill(b["id"])
                st.rerun()

    if paid_bills:
        with st.expander(f"過去的帳單（{len(paid_bills)} 張）"):
            rows = [("", f'{month_label(b["month"])}<span class="sub">{b["paid_date"] or ""}'
                         f' {html.escape(names.get(b["account_id"], ""))}</span>', money(b["amount"]))
                    for b in paid_bills[:24]]
            st.markdown(ledger_html(rows, total=False), unsafe_allow_html=True)
    if delete_button(f"del_card_{c['id']}", "刪除這張卡"):
        db.delete_card(c["id"])
        st.rerun()


def pay_card_bill(bill_id: int, amount: float, account_id: int, names: dict[int, str]) -> None:
    """繳卡費：帳單已繳增加、帳戶扣錢（db 的同一個交易裡）。餘額不夠時提醒，什麼都不扣。"""
    try:
        paid = db.pay_card_bill(bill_id, amount, account_id)
    except ValueError as e:
        st.warning(str(e))
    else:
        done(f"已繳卡費 {money(paid)}，「{plain(names[account_id])}」也扣掉了")


# ---------- 頁面：持股 ----------

def page_stocks() -> None:
    page_header("持股管理", "不同券商的同一檔股票會自動合併計算，現價自動更新")

    refresh_quotes()
    holdings = db.get_holdings()
    analyzed = analyze(holdings)
    if holdings:
        quote_bar()

    if analyzed:
        total_value = sum(m["value"] for m in analyzed)
        total_profit, cost, unknown = profit_totals(analyzed)
        m1, m2, m3 = summary_strip("stocks", 3)
        m1.metric("總市值", money(total_value))
        # delta_color="inverse"：正數紅、負數綠（台股習慣）
        m2.metric("總損益", signed_money(total_profit),
                  delta=f"{total_profit / cost:+.2%}" if cost > 0 else None,
                  delta_color="inverse",
                  help=f"有 {unknown} 檔沒填均價，不知道賺賠多少，沒有算進來" if unknown else None)
        m3.metric("持有檔數", f"{len(analyzed)} 檔")

        with st.container(key="card_holdings"):
            card_title("持股總覽", "同代號已合併")
            table = pd.DataFrame([{
                "名稱": m["name"],
                "代號": m["symbol"],
                "券商": "、".join(m["accounts"]),
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

            # Styler：幫表格上色、設定數字格式。
            # 沒填均價的個股，均價、損益、報酬率是 None（表格裡變成 NaN），na_rep 讓它顯示成「—」
            styled = (
                table.style
                .map(profit_color, subset=["損益", "報酬率%"])
                .format({
                    "股數": "{:,.0f}", "均價": "{:,.2f}", "現價": "{:,.2f}",
                    "市值": "{:,.0f}", "損益": "{:+,.0f}", "報酬率%": "{:+.2f}",
                    "占比%": "{:.1f}",
                }, na_rep="—")
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
        card_title("新增持股", "只要填代號、券商、股數，名稱和現價會自動查")
        add_holding_form()

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
        card_title("各券商明細", "刪除的是單一券商裡的那一筆")
        widths = [3, 2, 3, 1]
        for col, text in zip(st.columns(widths), ["股票", "券商", "股數與均價", ""]):
            col.caption(text)
        for h in holdings:
            col1, col2, col3, col4 = st.columns(widths, vertical_alignment="center")
            col1.write(f"**{plain(h['name'])}**（{plain(h['symbol'])}）")
            col2.write(plain(h["account"]))
            avg = f"@ {h['avg_price']:,.2f}" if h["avg_price"] > 0 else "・均價未填"
            col3.write(f"{h['shares']:,.0f} 股 {avg}")
            with col4:
                if delete_button(f"del_hold_{h['id']}"):
                    db.delete_holding(h["id"])
                    st.rerun()

    with st.container(key="card_brokers"):
        card_title("券商手續費", "買賣時照這裡的折扣自動算")
        broker_fee_form()


NEW_BROKER = "＋ 新的券商"


def broker_options() -> list[str]:
    """券商下拉選單的選項：已經有的券商，最後一個是「新的券商」（選了再輸入名字）。"""
    return [b["name"] for b in db.get_brokers()] + [NEW_BROKER]


def add_holding_form() -> None:
    """新增持股：代號、券商、股數、均價（選填）。名稱和現價用 quotes.lookup 查。

    規則（不同意可以改）：
    - 名稱：自己有填就用自己填的，沒填才用查到的
    - 現價：查得到就用查到的；查不到（基金、海外股票、沒網路）才用自己填的
    - 設定頁關掉「自動更新股價」時完全不連網路，名稱和現價都要自己填
    """
    with st.form("add_holding", clear_on_submit=True, border=False):
        col1, col2, col3 = st.columns(3)
        symbol = col1.text_input("代號（例如 2330）")
        broker = col2.selectbox("券商", broker_options())
        new_broker = col3.text_input("新的券商名稱（選「新的券商」才要填）")
        col4, col5 = st.columns(2)
        shares = col4.number_input("股數", min_value=0.0, step=1.0, format="%.0f")
        avg_price = col5.number_input("均價（選填，不知道就留 0）", min_value=0.0, step=0.1,
                                      help="不填的話這檔不算損益，其他功能照常")
        st.caption("查不到報價時（例如基金、海外股票）才需要填：")
        col6, col7 = st.columns(2)
        manual_name = col6.text_input("名稱")
        manual_price = col7.number_input("現價", min_value=0.0, step=0.1)
        submitted = st.form_submit_button("新增", type="primary", icon=":material/add:")
    if not submitted:
        return

    code = normalize_symbol(symbol)
    broker = new_broker.strip() if broker == NEW_BROKER else broker
    if not code:
        st.warning("請輸入代號")
        return
    if not broker:
        st.warning("請選券商，或輸入新的券商名稱")
        return
    if shares <= 0:
        st.warning("股數要大於 0")
        return
    info = None
    if db.get_settings().get("auto_quotes", 1):
        with st.spinner(f"查詢 {code} 的名稱和現價…"):
            info = quotes.lookup(code)
    name = manual_name.strip() or (info["name"] if info else "")
    price = info["price"] if info else manual_price
    if not name or price <= 0:
        st.warning(f"查不到 {plain(code)} 的報價（可能是基金、海外股票、代號打錯，或網路沒連上），"
                   "請在下面填名稱和現價。")
        return
    db.add_holding(name, code, broker, shares, avg_price, price)
    done(f"已新增：{plain(name)}（{plain(broker)}）{price:,.2f} 元")  # 重跑讓上面的總覽表馬上更新


def broker_fee_form() -> None:
    """每家券商的手續費折扣和最低手續費，一個表單一起改。"""
    brokers = db.get_brokers()
    if not brokers:
        st.caption("新增持股或買進時填的券商會出現在這裡。")
        return
    st.caption("折扣：2.8 折填 0.28、六折填 0.6、不打折填 1。"
               "手續費 = 成交金額 × 0.1425% × 折扣，不到最低手續費時收最低手續費。")
    with st.form("brokers", border=False):
        values = {}
        for b in brokers:
            col1, col2, col3 = st.columns([2, 2, 2], vertical_alignment="bottom")
            col1.write(f"**{plain(b['name'])}**")
            discount = col2.number_input("折扣", min_value=0.01, max_value=1.0, value=float(b["discount"]),
                                         step=0.01, format="%.3f", key=f"discount_{b['id']}")
            min_fee = col3.number_input("最低手續費", min_value=0.0, value=float(b["min_fee"]),
                                        step=1.0, format="%.0f", key=f"min_fee_{b['id']}")
            values[b["name"]] = (discount, min_fee)
        if st.form_submit_button("儲存", type="primary", icon=":material/save:"):
            for name, (discount, min_fee) in values.items():
                db.save_broker(name, discount, min_fee)
            done("已儲存券商手續費")


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
                      for m in analyze(db.get_holdings()) if (m["profit"] or 0) < 0]
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

    with st.container(key="card_trade_exec"):
        card_title("買進／賣出", "持股、帳戶、手續費一起算好")
        trade_form()

    with st.expander("手動記一筆（不會動到持股和帳戶）", icon=":material/edit_note:"):
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
        card_title("全部紀錄", "刪除只刪紀錄，不會把持股和帳戶改回去")
        widths = [1.6, 2.2, 1, 3.2, 1.6, 2.2, 0.8]
        for col, text in zip(st.columns(widths), ["日期", "標的", "類型", "明細", "損益", "備註", ""]):
            col.caption(text)
        # 類型標籤的顏色：當沖用橘色提醒自己，其他用墨藍和灰
        type_colors = {"當沖": WARN, "買進": INK, "賣出": MUTED}
        for t in trades:
            col1, col2, col3, col4, col5, col6, col7 = st.columns(widths, vertical_alignment="center")
            col1.write(t["date"])
            col2.write(plain(t["symbol"]))
            col3.markdown(chip(t["type"], type_colors.get(t["type"], MUTED)),
                          unsafe_allow_html=True)
            col4.write(plain(trade_detail(t)))
            # 買進沒有損益，顯示「—」；手動記的舊紀錄照原本填的
            col5.markdown("—" if t["side"] == "buy" else colored_money(t["pnl"]))
            col6.write(plain(t["note"] or ""))
            with col7:
                if delete_button(f"del_trade_{t['id']}", label=""):
                    db.delete_trade(t["id"])
                    st.rerun()


def trade_detail(t: dict) -> str:
    """交易明細的一行字，例如「1,000 股 @ 60.00・手續費 51・稅 180・A 證券」。手動記的紀錄沒有明細。"""
    if not t["side"]:
        return ""
    text = f"{t['shares']:,.0f} 股 @ {t['price']:,.2f}・手續費 {t['fee']:,.0f}"
    if t["tax"]:
        text += f"・稅 {t['tax']:,.0f}"
    return text + f"・{t['broker']}"


# 買賣表單的元件 key：送出成功後刪掉這些 key，表單就回到空白（這個表單沒用 st.form，不會自動清空）
TRADE_KEYS = ["tr_symbol", "tr_shares", "tr_price", "tr_note", "tr_new_broker", "tr_day_trade"]


def trade_form() -> None:
    """買進／賣出：送出時呼叫 db.execute_trade，持股、帳戶、交易紀錄一起改。

    不用 st.form：表單裡的元件要按送出才會更新，這裡想要一邊填一邊看到手續費、稅和帳戶增減。
    賣出時從現有的持股裡選（哪一家券商的哪一檔），不用再打代號，也不會賣到沒有的股票。
    """
    side = st.radio("買或賣", ["買進", "賣出"], horizontal=True, key="tr_side", label_visibility="collapsed")
    buy = side == "買進"
    holding = None
    if buy:
        col1, col2, col3 = st.columns(3)
        symbol = normalize_symbol(col1.text_input("代號（例如 2330）", key="tr_symbol"))
        broker = col2.selectbox("券商", broker_options(), key="tr_broker")
        if broker == NEW_BROKER:
            broker = col3.text_input("新的券商名稱", key="tr_new_broker").strip()
    else:
        holdings = db.get_holdings()
        if not holdings:
            st.caption("還沒有持股可以賣。")
            return
        by_id = {h["id"]: h for h in holdings}
        hid = st.selectbox("賣哪一筆", list(by_id), key="tr_holding",
                           format_func=lambda i: f"{by_id[i]['symbol']} {by_id[i]['name']}・"
                                                 f"{by_id[i]['account']}（{by_id[i]['shares']:,.0f} 股）")
        holding = by_id[hid]
        symbol, broker = normalize_symbol(holding["symbol"]), holding["account"]

    col4, col5, col6 = st.columns(3)
    shares = col4.number_input("股數", min_value=0, step=1000, key="tr_shares",
                               help="一張 = 1000 股；零股直接打股數")
    price = col5.number_input("成交價", min_value=0.0, step=0.05, format="%.2f", key="tr_price")
    with col6:
        account_id = account_select("從哪個帳戶付" if buy else "錢進哪個帳戶", key="tr_account")
    col7, col8 = st.columns([1, 2])
    when = col7.date_input("日期", value=date.today(), key="tr_date")
    note = col8.text_input("備註（例如 為什麼買、為什麼賣）", key="tr_note")
    day_trade = False if buy else st.checkbox("這是當沖（交易稅減半為 0.15%）", key="tr_day_trade")

    if not (symbol and broker and shares > 0 and price > 0):
        st.caption("填好代號、券商、股數、成交價，這裡會先算出手續費和帳戶增減。")
        return

    p = db.trade_preview("buy" if buy else "sell", symbol, broker, shares, price, day_trade)
    rows = [("", "成交金額", money(p["amount"])), ("", "手續費", money(p["fee"]))]
    if not buy:
        rows.append(("", "交易稅", money(p["tax"])))
    rows.append(("", "= 帳戶要付" if buy else "= 帳戶拿回", money(abs(p["cash"]))))
    ledger(rows)
    balance = next(a["balance"] for a in db.get_accounts() if a["id"] == account_id)
    if buy and -p["cash"] > balance:
        st.warning(f"「{account_names()[account_id]}」只有 {money(balance)}，不夠付這筆。")
    if not buy:
        pnl = realized_pnl(p["cash"], holding["avg_price"], shares)
        st.markdown("這筆的實現損益：" + (colored_money(pnl) if pnl is not None else "沒填均價，算不出來"))

    if st.button("確認買進" if buy else "確認賣出", type="primary", icon=":material/check:", key="tr_submit"):
        name = None
        # 第一次買的股票先查名稱（設定頁關掉自動更新時不連網路，名稱先用代號，之後可以在持股頁看）
        if buy and not any(normalize_symbol(h["symbol"]) == symbol for h in db.get_holdings()):
            if db.get_settings().get("auto_quotes", 1):
                info = quotes.lookup(symbol)
                name = info["name"] if info else None
        else:
            name = next((h["name"] for h in db.get_holdings() if normalize_symbol(h["symbol"]) == symbol), None)
        try:
            db.execute_trade("buy" if buy else "sell", symbol, broker, shares, price, account_id,
                             when.isoformat(), day_trade, name=name, note=note.strip())
        except ValueError as e:
            st.warning(str(e))
            return
        for key in TRADE_KEYS:
            st.session_state.pop(key, None)
        done(f"已{side} {plain(symbol)} {shares:,.0f} 股，「{plain(account_names()[account_id])}」"
             f"{'扣' if buy else '加'} {money(abs(p['cash']))}")


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
        card_cashflow(db.get_card_bills(), db.get_card_records(), today.isoformat()[:7]),
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
        (page_goals, "儲蓄目標", ":material/flag:", "goals"),
        (page_fixed, "固定支出", ":material/event_repeat:", "fixed"),
        (page_debts, "負債", ":material/request_quote:", "debts"),
        (page_receivables, "別人欠我", ":material/handshake:", "receivables"),
        (page_cards, "信用卡", ":material/credit_card:", "cards"),
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
    # 左邊的小方框是「印」：存摺封面上蓋的章，打開時會蓋一次（見 inject_css 的動畫區）
    st.markdown('<div class="brand"><span class="seal">星</span>OniPulsar</div>'
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

# 切換頁面時，金額從 0 跳到目標數字（見 COUNT_UP_JS）。
# 這個 iframe 的內容含有頁面名稱，換頁時內容改變、iframe 會重新載入，腳本才會再跑一次；
# 同一頁裡按按鈕、輸入數字造成的重跑，內容不變，不會重播。
components.html(COUNT_UP_JS.replace("__PAGE__", html.escape(current.title)), height=0)
current.run()  # 執行被選中的頁面函式
