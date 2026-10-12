# 個人理財管理系統

用 Python + Streamlit + SQLite 做的個人理財工具。在自己電腦上執行，資料只存在本機，不會上傳到任何地方。

![總覽](docs/screenshots/overview.png)

> 所有截圖都是用 `seed_example.py` 產生的**虛構範例資料**。

## 功能介紹

### 日常收支
- **記帳**：輸入金額、類別、日期、備註。顯示本月明細、各類別「已花／預算」進度條，以及本月還能花多少。
- **每月預算**：吃飯、約會禮物、交通、其他，各自設定金額。
- **固定支出**：例如電話費、iCloud，可新增、刪除。

「本月還能花多少」= 四個類別的預算總和 − 本月已記帳的支出總和（超支會變負數）。

### 總覽
- **每月現金流**：收入 − 固定支出 − 負債還款 − 生活預算 = 每月可存
- 單一個股占總市值超過 40% 時顯示警告
- 本月當沖次數大於 0 時顯示紅色警告
- 手上現金、股票市值、負債餘額

### 負債
- 名稱、剩餘金額、每月還款
- 按「已還一期」會同時扣剩餘金額和手上現金（現金不夠時不會扣）
- 顯示預計還清月份（假設下一期在下個月繳）

### 投資
- **持股**：名稱、代號、帳戶、股數、均價、現價（手動輸入）
  - 同一代號在不同帳戶會合併計算（均價為加權平均）
  - 市值、損益、報酬率、占總市值比例；顏色依台股習慣，紅色是賺、綠色是賠
  - 虧損的個股顯示回本價 = 總成本 ÷ (股數 × (1 − 0.001425 − 0.003))，以及距離現價還要漲幾 %
- **下單前檢查**：輸入股價和股數，五個項目全部打勾、而且金額不超過手上現金，才會顯示綠色「可以下單」，否則顯示紅色「先不要下單」並列出原因
- **交易紀錄**：日期、標的、類型（買進／賣出／當沖）、損益、備註
- **定期定額試算**：輸入現有投資、每月投入、年報酬率、年數，畫出每年資產的折線圖，並用 4% 法則換算每月可領金額

### 設定與備份
- 每月收入、手上現金、緊急預備金、預備金目標（預設 17000）
- **匯出 CSV 備份**：每張資料表一個 CSV，打包成 zip 下載，可用 Excel 開啟

## 截圖

截圖放在 `docs/screenshots/`：

| 持股 | 下單前檢查 |
|---|---|
| ![持股](docs/screenshots/stocks.png) | ![下單前檢查](docs/screenshots/precheck.png) |

| 定期定額試算 | 負債 |
|---|---|
| ![定期定額試算](docs/screenshots/dca.png) | ![負債](docs/screenshots/debts.png) |

| 記帳 | 交易紀錄 |
|---|---|
| ![記帳](docs/screenshots/expenses.png) | ![交易紀錄](docs/screenshots/trades.png) |

## 安裝

需要 Python 3.10 以上。

```bash
git clone <這個 repo 的網址>
cd finance-app

# 建立虛擬環境（讓這個專案的套件跟系統分開）
python -m venv .venv

# 啟用虛擬環境
# Windows：
.venv\Scripts\activate
# macOS / Linux：
source .venv/bin/activate

# 安裝套件
pip install -r requirements.txt
```

## 執行

```bash
streamlit run app.py
```

瀏覽器會自動打開 http://localhost:8501 。第一次執行時會自動建立 `data/finance.db`。

### 用範例資料試玩

```bash
python seed_example.py          # 產生 data/example.db（虛構資料，不會動到 finance.db）

# Windows PowerShell
$env:FINANCE_DB="data/example.db"; streamlit run app.py
# macOS / Linux
FINANCE_DB=data/example.db streamlit run app.py
```

### 測試

```bash
pytest
```

## 技術架構

| 層 | 檔案 | 負責 |
|---|---|---|
| 畫面 | `app.py` | Streamlit 頁面，只負責顯示和接收輸入 |
| 資料 | `db.py` | SQLite 讀寫，所有 SQL 都在這裡 |
| 計算 | `models/` | 純計算函式，不碰資料庫也不碰畫面，方便測試 |
| 測試 | `tests/` | pytest，測 `models/` 的計算和 CSV 匯出 |

```
finance-app/
├── app.py              # Streamlit 主程式
├── db.py               # 資料庫讀寫、CSV 匯出
├── seed_example.py     # 產生虛構範例資料
├── models/
│   ├── budget.py       # 本月還能花多少
│   ├── cashflow.py     # 每月現金流
│   ├── debt.py         # 負債：還一期、預計還清月份
│   ├── stocks.py       # 持股：合併、市值、損益、回本價
│   ├── precheck.py     # 下單前檢查
│   ├── trades.py       # 交易紀錄統計（當沖次數）
│   └── dca.py          # 定期定額試算、4% 法則
├── tests/              # pytest 測試
├── docs/screenshots/   # README 截圖（虛構資料）
├── data/               # 資料庫檔案（不會進 git）
├── requirements.txt
└── pytest.ini
```

資料表：`settings`、`budgets`、`expenses`、`fixed_expenses`、`debts`、`holdings`、`trades`。
資料庫路徑預設是 `data/finance.db`，可以用環境變數 `FINANCE_DB` 改成別的檔案。

## 隱私

- `data/`、`*.db`、`.env`、`*.csv`、`*.xlsx`、`*.zip` 都列在 `.gitignore`，不會被 commit。
- 匯出的備份檔是你的真實資料，請存在專案資料夾以外的地方。
- 上傳 GitHub 前可以用 `git status` 確認沒有資料庫或備份檔。

## 免責聲明

這是個人學習用的工具，計算結果僅供參考，不構成任何投資建議。
