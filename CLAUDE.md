# CLAUDE.md：接手這個專案前先讀

個人理財管理系統。Python + Streamlit + SQLite，在使用者自己的電腦上執行，資料只存在本機。
功能介紹、截圖、安裝與打包方式寫在 `README.md`；每個階段做了什麼、為什麼這樣做，以及待辦清單寫在 `docs/開發紀錄.md`。

## 🔴 資料安全（最重要，沒有例外）

這個 repo 是**公開的**，使用者會在裡面記錄真實的收入、負債、持股。

- **絕對不能 commit** 任何資料庫檔（`*.db`、`*.sqlite`、`data/`）、匯出的備份（`*.csv`、`*.xlsx`、`*.zip`）、`.env`、`.streamlit/secrets.toml`。這些都已在 `.gitignore`，**不要刪掉或放寬這些規則**。
- 每次 commit 前執行 `git status`，確認沒有上述檔案。新增檔案用 `git add <檔名>`，不要用 `git add -A` / `git add .`。
- 截圖、範例、測試只能用**虛構資料**（`seed_example.py` 產生的 `data/example.db`，名稱像「範例學貸」「A 證券」）。不要把使用者貼給你的真實數字寫進程式碼、測試、文件或 commit 訊息。
- 測試要用暫時的資料庫（`monkeypatch` 換掉 `db.DB_PATH`，見 `tests/test_trading_tools.py`），不能碰 `data/finance.db`。
- **不要拿掉** `.streamlit/config.toml` 的 `server.address = "localhost"` 和 `browser.gatherUsageStats = false`：Streamlit 預設監聽所有網路介面（0.0.0.0），同一個 Wi-Fi 的人就能打開你的財務資料。exe 版的 `run_app.py` 也是同樣設定。
- `FinanceApp.spec` 只打包 `models/*.py`，不要改回整個資料夾：`__pycache__` 裡的 .pyc 記錄了打包電腦上的絕對路徑（可能含使用者名稱）。

## 和使用者合作的方式

使用者會 C++ 和基礎 Python，做這個專案是為了**學習**。使用者的偏好：

1. **先說明再寫程式**：每一步先講「要做什麼、為什麼」，再動手。有自己決定的規則（例如邊界情況怎麼處理），要明白講出來，並說「不同意可以改」。
2. **程式碼註解用繁體中文**，解釋「為什麼」，不只是「做什麼」。適時用 C++ 的概念類比（例如 header／實作分離）。
3. **簡單清楚，不要過度設計**：不加用不到的抽象層、設定檔、class 階層。能用一個函式解決就不要寫一個類別。
4. 回覆和文件都用**繁體中文**。
5. 改完要附上：怎麼執行、`pytest` 應該看到幾個 passed、實際點過哪些畫面。

## 常用指令

```bash
python -m venv .venv && source .venv/bin/activate   # Windows：.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py          # http://localhost:8501，第一次會自動建立 data/finance.db
pytest                        # 目前 107 passed（含 tests/test_app.py 的畫面測試；測試不會連網路）

# 用虛構範例資料啟動（不會動到 finance.db）
python seed_example.py
FINANCE_DB=data/example.db streamlit run app.py
```

打包：Windows 跑 `build_exe.bat`（產生安裝檔），macOS 跑 `bash build_mac.sh`。細節見 README。
一般用 GitHub Actions 打包即可（PR 有改程式或打包檔案時自動跑，會實際安裝、啟動並確認畫面）。

## 架構：三層分開

| 層 | 檔案 | 規則 |
|---|---|---|
| 畫面 | `app.py` | 只負責顯示和接收輸入，**不寫 SQL、不寫計算公式** |
| 資料 | `db.py` | 所有 SQL 都在這裡；建表、讀寫、CSV 匯出 |
| 計算 | `models/*.py` | 純函式，**不碰資料庫、不碰 Streamlit**，給一樣輸入得一樣輸出，方便測試 |
| 測試 | `tests/` | pytest，主要測 `models/`，加上 CSV 匯出和資料庫路徑 |

新功能照這個順序加：`models/` 的計算 → `tests/` 的測試 → `db.py` 的資料表與讀寫 → `app.py` 的畫面。

### 各檔案職責

- `app.py`（約 1100 行）：由上到下是「配色與 CSS（`inject_css`）→ 共用小工具（`money`、`ledger`、`summary_strip`、`notices`、`plain`、`done`、`budget_bar`、`show_donut`、`welcome`…）→ 各頁 `page_*()` 函式 → 側邊欄 → 主程式（`NAV` 清單 + `st.navigation`）」。新增頁面：寫一個 `page_xxx()`，再加進檔尾的 `NAV`。外觀是「存摺」風格：一排數字用 `summary_strip()`、自律提醒用 `notices()`、明細用 `ledger()`。
- `db.py`：`DB_PATH` 預設是 `data/finance.db`；視窗版（`run_app.py` 設定環境變數，或 PyInstaller 的 `sys.frozen`）是 `~/FinanceApp/finance.db`；環境變數 `FINANCE_DB` 可覆蓋。`init_db()` 用 `CREATE TABLE IF NOT EXISTS` 建 9 張表：`settings`（key/value）、`budgets`、`expenses`、`fixed_expenses`、`debts`、`debt_payments`（還款紀錄）、`holdings`、`trades`、`networth_history`（每天的淨資產）。也負責每日自動備份（`auto_backup`，資料庫旁的 `backups/`，留 14 份）和還原（`restore_backup`，還原前先另存）。
- `models/budget.py`：預算類別 `CATEGORIES`（唯一定義處）、篩選某月、本月還能花多少。
- `models/cashflow.py`：每月可存 = 收入 − 固定支出 − 負債還款 − 生活預算。
- `models/debt.py`：這期還多少、剩幾期、預計還清月份（假設下一期在下個月繳）。
- `models/stocks.py`：同代號跨帳戶合併（加權平均均價）、市值、損益、占比、40% 集中警告、回本價。
- `models/precheck.py`：下單前檢查，`CHECK_ITEMS` 五個勾選項，回傳 `(可不可以下單, 原因清單)`。
- `models/trades.py`：交易類型、本月當沖次數、累計損益。
- `models/dca.py`：定期定額複利試算、4% 法則。
- `models/quotes.py`：解析證交所 MIS 即時行情、證交所／櫃買中心每日收盤價，代號正規化、交易時間判斷（純函式）。
- `quotes.py`：**整個程式唯一連網路的地方**：`fetch_prices()` 先問 MIS，MIS 整個失敗才下載官方每日收盤價；不丟例外，失敗時回傳 `error`。只送股票代號。`app.py` 的 `refresh_quotes()` 用 `st.cache_data` 記 5 分鐘，設定 `auto_quotes = 0` 時不連線。
- `seed_example.py`：產生虛構範例資料到 `data/example.db`，路徑不是 `example.db` 就拒絕執行。
- `run_app.py`：視窗版入口（pywebview 開視窗 + 背景 Streamlit）。
- Windows 安裝檔：`installer/build_runtime.py`（官方嵌入式 Python + `requirements-runtime.txt` 的套件 + 程式碼 → `dist/FinanceApp`）→ `installer/FinanceApp.iss`（Inno Setup）。捷徑執行 `python\pythonw.exe app\run_app.py`。
- `FinanceApp.spec` / `build_mac.sh` / `requirements-build.txt`：macOS 用 PyInstaller 打包。
- `.streamlit/config.toml`：主題配色、字型。

## 程式慣例與已知陷阱

- 日期存成 `'YYYY-MM-DD'` 字串（字串排序 = 日期排序，查某月就比對開頭）。
- 會同時改兩個數字的操作要放在**同一個 `with get_connection()`** 裡（例如 `pay_debt_installment()` 同時扣負債和現金）。
- 小數比較用 `pytest.approx()`。
- **金額顯示用 `12,345 元`，不要用 `$12,345`**：Streamlit markdown 會把同一行兩個 `$` 中間當成 LaTeX 公式。用 `app.py` 的 `money()` / `signed_money()`。
- **顏色是台股習慣：紅色 = 賺、綠色 = 賠**。紅綠只留給漲跌；預算快用完用金色、超支用橘色。
- 使用者輸入的文字放進 `unsafe_allow_html=True` 的 HTML 前，一定要 `html.escape()`；放進 `st.write` / `st.markdown` / `st.toast` 前要用 `plain()`（不然兩個 `$` 中間會變成數學公式）。
- 存檔成功一律呼叫 `done("訊息")`：會顯示通知並立刻重跑。不重跑的話，側邊欄會顯示舊數字，而且連按兩次「儲存」第二次會沒存到。
- 不要用 `st.success` / `st.error`（綠、紅色會和漲跌搞混）：輸入錯誤用 `st.warning`，自律提醒用 `notices()`。
- 顏色常數都算過對比（小字至少 4.5:1）。要當小字用的顏色用 `GAIN`、`LOSS`、`WARN`、`GOLD_TEXT`；`GOLD` 只用在進度條和圖表。`config.toml` 的 `redColor` / `greenColor` 要寫比較亮的原色，Streamlit 當文字用時會自己再調深。
- Streamlit 每次互動都會**從頭重跑整個 `app.py`**；資料要存資料庫，改完資料後呼叫 `st.rerun()`。
- `requirements-build.txt` 要保持**純 ASCII**（Windows 的 pip 用 cp950 讀，有中文會失敗）。
- `.streamlit/config.toml` 由 `FinanceApp.spec` 打包到 exe 裡 `app.py` 旁邊的 `.streamlit/`（Streamlit 會讀「主程式旁邊」的設定檔），所以 exe 版也有主題；改完要重新打包才會生效。`run_app.py` 的命令列參數優先權比 config.toml 高，兩邊不要設成不一樣的值。
- 改完畫面跑 `pytest`：`tests/test_app.py` 會用 AppTest 跑每一頁（有資料、空資料各一次）。頁面是函式，AppTest 的 `switch_page` 用不了，所以測試用 `runpy` 執行 app.py 再呼叫頁面函式。新增頁面要加進 `PAGES` 清單。
- **測試不能連網路**：`tests/test_app.py` 有 autouse fixture 把 `quotes.fetch_prices` 換成假資料，並清掉 `st.cache_data`。新增會連網路的功能，也要在測試裡換掉。
- `seed_example.py` 把 `auto_quotes` 設成 0：範例資料的股價保持虛構，截圖不會變成真實股價。
- 頁面裡要連到別頁用 `st.page_link(PAGES["網址名"])`（`PAGES` 在 app.py 檔尾建立）。
- **測試時不要讓使用者在帶著 `FINANCE_DB` 的程式裡記帳**：環境變數會傳給子程式（例如從 Onei Hub 開的理財系統），記下的資料會寫進測試資料庫，正常打開時就「不見了」（2026-10-21 發生過）。現在 `FINANCE_DB` 指到平常以外的檔案時，每頁最上面會顯示警告（`db.is_unusual_db`）。測完要把帶測試環境變數的程式全部關掉，用一般方式重開。

## Windows 打包的坑（不要再犯）

1. **不要改回 PyInstaller 的 exe**：沒有簽章的 FinanceApp.exe 會被 Trend Micro 等防毒軟體刪掉（2026-10-21 在使用者電腦實測：裝完 exe 就不見）。現在用官方有簽章的 `pythonw.exe`。
2. 在有這類防毒的電腦上，PyInstaller 和 Inno Setup 編譯也會失敗（`EndUpdateResource failed`），請用 GitHub Actions 打包。
3. 背景伺服器不能讀 stdin 偵測視窗關閉（Windows 上會卡住 Streamlit 送檔案，畫面全白）；用 `OpenProcess` + `WaitForSingleObject`。
4. 只檢查 `/_stcore/health` 不夠，CI 用 `.github/scripts/check_window.py` 確認畫面真的畫出來。
5. 連線用 `127.0.0.1`，不要用 `localhost`（可能被解析成 IPv6）。
6. 嵌入式 Python 的版本要有官方 embed 檔：3.12 最後一版是 3.12.10（見 `build_runtime.py` 的 `EMBED_VERSIONS`）。
7. `.bat`、`requirements*.txt` 保持純 ASCII；`.iss` 是 UTF-8 含 BOM；`AppId` 不能改。

## Git 與 PR

- 一個功能一個 commit，commit 訊息用繁體中文，第一行簡短描述做了什麼。
- 從分支開 PR 給使用者合併，不要直接推 `main`。

## 目前進度

- ✅ 第一階段：設定、預算、記帳、固定支出
- ✅ 第二階段：負債、每月現金流、持股
- ✅ 第三階段：下單前檢查、交易紀錄、定期定額試算、CSV 匯出、範例資料、README 截圖
- ✅ 打包成 exe（Windows / macOS）
- ✅ 介面美化（主題、數字卡、圖表、側邊欄、手機版面）
- ✅ exe 版套用主題
- ✅ MIT 授權、README 下載說明
- ✅ 介面改版：存摺風格，並修正全面測試找到的問題（2026-10-13）
- ✅ Windows 安裝程式（安裝精靈、獨立視窗、CI 實際安裝測試）
- ✅ v1.0.0 發布（2026-10-21）：GitHub Release 附安裝檔；也上架 Onei Hub（伺服器 `downloads/finance-app-v1.0.0-win-x64.zip`）
- ✅ v1 實用功能（2026-10-21）：首次使用引導、側邊欄記一筆、記帳月份切換與修改、6 個月趨勢、淨資產變化、還款紀錄、每日自動備份與還原；安裝版改用官方嵌入式 Python

下一步建議的待辦（完整清單和理由見 `docs/開發紀錄.md` 的「待辦」）：
1. ETF 賣出交易稅是 0.1%（目前一律用 0.3%），手續費最低 20 元
2. 手上現金不會隨記帳／交易自動更新
3. 記帳類別寫死在 `models/budget.py`，可以考慮讓使用者自訂

開始做任何一項之前，先跟使用者確認要做哪一項。
