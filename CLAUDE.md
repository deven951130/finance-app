# CLAUDE.md：接手這個專案前先讀

個人理財管理系統。Python + Streamlit + SQLite，在使用者自己的電腦上執行，資料只存在本機。
功能介紹、截圖、安裝與打包方式寫在 `README.md`；每個階段做了什麼、為什麼這樣做，以及待辦清單寫在 `docs/開發紀錄.md`。

## 🔴 資料安全（最重要，沒有例外）

這個 repo 是**公開的**，使用者會在裡面記錄真實的收入、負債、持股。

- **絕對不能 commit** 任何資料庫檔（`*.db`、`*.sqlite`、`data/`）、匯出的備份（`*.csv`、`*.xlsx`、`*.zip`）、`.env`、`.streamlit/secrets.toml`。這些都已在 `.gitignore`，**不要刪掉或放寬這些規則**。
- 每次 commit 前執行 `git status`，確認沒有上述檔案。新增檔案用 `git add <檔名>`，不要用 `git add -A` / `git add .`。
- 截圖、範例、測試只能用**虛構資料**（`seed_example.py` 產生的 `data/example.db`，名稱像「範例學貸」「A 證券」）。不要把使用者貼給你的真實數字寫進程式碼、測試、文件或 commit 訊息。
- 測試要用暫時的資料庫（`monkeypatch` 換掉 `db.DB_PATH`，見 `tests/test_trading_tools.py`），不能碰 `data/finance.db`。

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
pytest                        # 目前 44 passed

# 用虛構範例資料啟動（不會動到 finance.db）
python seed_example.py
FINANCE_DB=data/example.db streamlit run app.py
```

打包 exe：Windows 跑 `build_exe.bat`，macOS 跑 `bash build_mac.sh`（只能在目標系統上打包）。細節見 README。

## 架構：三層分開

| 層 | 檔案 | 規則 |
|---|---|---|
| 畫面 | `app.py` | 只負責顯示和接收輸入，**不寫 SQL、不寫計算公式** |
| 資料 | `db.py` | 所有 SQL 都在這裡；建表、讀寫、CSV 匯出 |
| 計算 | `models/*.py` | 純函式，**不碰資料庫、不碰 Streamlit**，給一樣輸入得一樣輸出，方便測試 |
| 測試 | `tests/` | pytest，主要測 `models/`，加上 CSV 匯出和資料庫路徑 |

新功能照這個順序加：`models/` 的計算 → `tests/` 的測試 → `db.py` 的資料表與讀寫 → `app.py` 的畫面。

### 各檔案職責

- `app.py`（約 1000 行）：由上到下是「配色與 CSS（`inject_css`）→ 共用小工具（`money`、`ledger`、`budget_bar`、`donut`…）→ 各頁 `page_*()` 函式 → 側邊欄 → 主程式（`NAV` 清單 + `st.navigation`）」。新增頁面：寫一個 `page_xxx()`，再加進檔尾的 `NAV`。
- `db.py`：`DB_PATH` 預設是 `data/finance.db`；exe 版（`sys.frozen`）是 `~/FinanceApp/finance.db`；環境變數 `FINANCE_DB` 可覆蓋。`init_db()` 用 `CREATE TABLE IF NOT EXISTS` 建 7 張表：`settings`（key/value）、`budgets`、`expenses`、`fixed_expenses`、`debts`、`holdings`、`trades`。
- `models/budget.py`：預算類別 `CATEGORIES`（唯一定義處）、篩選某月、本月還能花多少。
- `models/cashflow.py`：每月可存 = 收入 − 固定支出 − 負債還款 − 生活預算。
- `models/debt.py`：這期還多少、剩幾期、預計還清月份（假設下一期在下個月繳）。
- `models/stocks.py`：同代號跨帳戶合併（加權平均均價）、市值、損益、占比、40% 集中警告、回本價。
- `models/precheck.py`：下單前檢查，`CHECK_ITEMS` 五個勾選項，回傳 `(可不可以下單, 原因清單)`。
- `models/trades.py`：交易類型、本月當沖次數、累計損益。
- `models/dca.py`：定期定額複利試算、4% 法則。
- `seed_example.py`：產生虛構範例資料到 `data/example.db`，路徑不是 `example.db` 就拒絕執行。
- `run_app.py` / `FinanceApp.spec` / `build_*.{bat,sh}` / `requirements-build.txt`：PyInstaller 打包用。
- `.streamlit/config.toml`：主題配色、字型。

## 程式慣例與已知陷阱

- 日期存成 `'YYYY-MM-DD'` 字串（字串排序 = 日期排序，查某月就比對開頭）。
- 會同時改兩個數字的操作要放在**同一個 `with get_connection()`** 裡（例如 `pay_debt_installment()` 同時扣負債和現金）。
- 小數比較用 `pytest.approx()`。
- **金額顯示用 `12,345 元`，不要用 `$12,345`**：Streamlit markdown 會把同一行兩個 `$` 中間當成 LaTeX 公式。用 `app.py` 的 `money()` / `signed_money()`。
- **顏色是台股習慣：紅色 = 賺、綠色 = 賠**。紅綠只留給漲跌；預算快用完用金色、超支用橘色。
- 使用者輸入的文字放進 `unsafe_allow_html=True` 的 HTML 前，一定要 `html.escape()`。
- Streamlit 每次互動都會**從頭重跑整個 `app.py`**；資料要存資料庫，改完資料後呼叫 `st.rerun()`。
- `requirements-build.txt` 要保持**純 ASCII**（Windows 的 pip 用 cp950 讀，有中文會失敗）。
- `.streamlit/config.toml` 由 `FinanceApp.spec` 打包到 exe 裡 `app.py` 旁邊的 `.streamlit/`（Streamlit 會讀「主程式旁邊」的設定檔），所以 exe 版也有主題；改完要重新打包才會生效。`run_app.py` 的命令列參數優先權比 config.toml 高，兩邊不要設成不一樣的值。
- 改完畫面，除了 `pytest`，也用 `streamlit.testing.v1.AppTest` 或實際啟動，確認每一頁都打得開。

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

下一步建議的待辦（完整清單和理由見 `docs/開發紀錄.md` 的「待辦」）：
1. ETF 賣出交易稅是 0.1%（目前一律用 0.3%），手續費最低 20 元
2. 加 LICENSE（公開 repo）
3. 「已還一期」可重複按，需要還款紀錄
4. 手上現金不會隨記帳／交易自動更新
5. `db.py` 補測試（例如現金不夠時負債和現金都不變）

開始做任何一項之前，先跟使用者確認要做哪一項。
