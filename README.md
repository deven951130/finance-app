# 個人理財管理系統

用 Python + Streamlit + SQLite 做的個人理財工具。在自己電腦上執行，資料只存在本機，不會上傳到任何地方。

![總覽](docs/screenshots/overview.png)

> 所有截圖都是用 `seed_example.py` 產生的**虛構範例資料**。

## 下載（Windows）

不想安裝 Python 的話，可以直接下載打包好的 Windows 版（Windows 10 / 11，64 位元）：

1. 到 [Releases](https://github.com/deven951130/finance-app/releases/latest) 下載 `FinanceApp-Windows-v1.0.0.zip`。
2. 解壓縮到任何資料夾（例如桌面）。**整個資料夾要放在一起**，不能只複製 exe，也不要直接在 zip 裡面執行。
3. 點兩下資料夾裡的 `FinanceApp.exe`，會出現一個黑色視窗，瀏覽器會自動打開程式。**關掉黑色視窗就結束程式。**
4. 第一次執行如果跳出「Windows 已保護您的電腦」，按「其他資訊 → 仍要執行」。這是因為程式沒有付費的數位簽章；少數防毒軟體也可能誤判用 PyInstaller 打包的程式。

- 資料存在 `C:\Users\你的名字\FinanceApp\finance.db`，只在你自己的電腦上。備份可以複製這個檔案，或在「設定」頁匯出 CSV。
- 要更新時，下載新版、解壓縮後用新的資料夾取代舊的即可，資料不會遺失。
- macOS 目前沒有提供下載檔，請參考下面的「打包成獨立程式」自己打包。

## 功能介紹

### 日常收支
- **記帳**：輸入金額、類別、日期、備註。顯示本月明細、各類別「已花／預算」進度條，以及本月還能花多少。
- **每月預算**：吃飯、約會禮物、交通、其他，各自設定金額。
- **固定支出**：例如電話費、iCloud，可新增、刪除。

「本月還能花多少」= 四個類別的預算總和 − 本月已記帳的支出總和（超支會變負數）。

### 總覽
- **每月現金流**：收入 − 固定支出 − 負債還款 − 生活預算 = 每月可存
- 單一個股占總市值超過 40% 時提醒
- 本月當沖次數大於 0 時用橘色提醒（紅色、綠色只留給漲跌）
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
- **下單前檢查**：輸入股價和股數，五個項目全部打勾、而且金額不超過手上現金，頁面最上面才會顯示「可以下單」，否則用橘色大字顯示「先不要下單」並列出原因
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
git clone https://github.com/deven951130/finance-app.git
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

## 打包成獨立程式（exe）

不想每次開終端機，可以打包成點兩下就能用的程式，使用的電腦**不需要安裝 Python**。

> 打包只能在「目標系統」上做：Windows 的 exe 要在 Windows 上打包，Mac 版要在 Mac 上打包。

**Windows**：在 finance-app 資料夾裡點兩下 `build_exe.bat`。完成後程式在 `dist\FinanceApp\FinanceApp.exe`。

**macOS**：在終端機執行 `bash build_mac.sh`。完成後程式在 `dist/FinanceApp/FinanceApp`。

使用方式：
- 點兩下 `FinanceApp.exe`，會出現一個黑色視窗，瀏覽器自動打開程式。**關掉黑色視窗就結束程式。**
- 整個 `dist/FinanceApp` 資料夾要一起搬（大約 200 MB），不能只複製 exe。可以對 exe 按右鍵建立桌面捷徑。
- exe 版的資料存在 `家目錄/FinanceApp/finance.db`（例如 `C:\Users\你的名字\FinanceApp\finance.db`），更新程式不會遺失資料。實際位置顯示在「設定」頁最下面。
- 第一次執行時，Windows 可能會跳出「Windows 已保護您的電腦」。這是因為程式沒有付費的數位簽章，按「其他資訊 → 仍要執行」即可；Mac 則是按右鍵選「打開」。

如果點開後視窗馬上關掉：
- 確認點的是 `dist\FinanceApp\FinanceApp.exe`，**不是** `build` 資料夾裡的那個（那個是暫存檔，不能用）。
- 程式出錯時，視窗會停住並顯示錯誤；錯誤也會存到 `家目錄/FinanceApp/error.log`。

相關檔案：

| 檔案 | 用途 |
|---|---|
| `run_app.py` | exe 的啟動入口，代替我們輸入 `streamlit run app.py` |
| `FinanceApp.spec` | PyInstaller 打包設定：要打包哪些檔案 |
| `build_exe.bat` / `build_mac.sh` | 一鍵打包腳本 |
| `requirements-build.txt` | 打包才需要的套件（PyInstaller） |

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
├── run_app.py          # exe 啟動入口
├── FinanceApp.spec     # PyInstaller 打包設定
├── build_exe.bat       # Windows 打包腳本
├── build_mac.sh        # macOS 打包腳本
├── models/
│   ├── budget.py       # 本月還能花多少
│   ├── cashflow.py     # 每月現金流
│   ├── debt.py         # 負債：還一期、預計還清月份
│   ├── stocks.py       # 持股：合併、市值、損益、回本價
│   ├── precheck.py     # 下單前檢查
│   ├── trades.py       # 交易紀錄統計（當沖次數）
│   └── dca.py          # 定期定額試算、4% 法則
├── .streamlit/config.toml  # 外觀主題：配色、字型、圓角
├── tests/              # pytest 測試
├── docs/screenshots/   # README 截圖（虛構資料）
├── data/               # 資料庫檔案（不會進 git）
├── requirements.txt
└── pytest.ini
```

資料表：`settings`、`budgets`、`expenses`、`fixed_expenses`、`debts`、`holdings`、`trades`。
資料庫路徑預設是專案裡的 `data/finance.db`（exe 版是 `家目錄/FinanceApp/finance.db`），可以用環境變數 `FINANCE_DB` 改成別的檔案。

## 給接手開發的人

專案規則、慣例與目前進度在 [`CLAUDE.md`](CLAUDE.md)；各階段的設計決定與待辦清單在 [`docs/開發紀錄.md`](docs/開發紀錄.md)。

## 隱私

- `data/`、`*.db`、`.env`、`*.csv`、`*.xlsx`、`*.zip` 都列在 `.gitignore`，不會被 commit。
- 匯出的備份檔是你的真實資料，請存在專案資料夾以外的地方。
- 上傳 GitHub 前可以用 `git status` 確認沒有資料庫或備份檔。
- 打包產生的 `build/`、`dist/` 也已排除，不會被 commit。
- 不論是 exe 還是 `streamlit run app.py`，都只接受這台電腦自己連線（localhost），區網裡的其他人連不到；也不會傳送使用統計給 Streamlit。設定在 `.streamlit/config.toml` 和 `run_app.py`。
- 畫面上的中文字型會從 Google Fonts 下載，只是字型檔，不會送出任何財務資料；沒有網路時會改用電腦內建的字型。

## 授權

[MIT License](LICENSE)：可以自由使用、修改、再發布，只要保留版權聲明。下載的 Windows 版裡另外附上 `THIRD_PARTY_LICENSES.txt`，列出打包進去的第三方套件（Streamlit、pandas 等）的授權。

## 免責聲明

這是個人學習用的工具，計算結果僅供參考，不構成任何投資建議。
