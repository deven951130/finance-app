# 個人理財管理系統

用 Python + Streamlit + SQLite 做的個人理財工具，在自己電腦上執行，資料只存在本機。

## 功能（第一階段）

- **設定**：每月收入、手上現金、緊急預備金、預備金目標（預設 17000）
- **每月預算**：吃飯、約會禮物、交通、其他，各自設定金額
- **記帳**：輸入金額、類別、日期、備註；顯示本月明細、各類別進度條、本月還能花多少
- **固定支出**：例如電話費、iCloud，可新增、刪除

「本月還能花多少」= 四個類別的預算總和 − 本月已記帳的支出總和（超支會變負數）。
固定支出目前只是清單，不會扣進這個數字。

## 專案結構

```
finance-app/
├── app.py            # Streamlit 畫面（各頁面）
├── db.py             # 資料庫讀寫（所有 SQL 都在這裡）
├── models/
│   └── budget.py     # 純計算邏輯（本月還能花多少等）
├── tests/
│   └── test_budget.py  # pytest 測試
├── data/             # 資料庫檔案放這裡（不會進 git）
├── requirements.txt
└── pytest.ini
```

## 安裝

需要 Python 3.10 以上。

```bash
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

## 測試

```bash
pytest
```

## 隱私

`data/`、`*.db`、`.env`、匯出的 `*.csv`／`*.xlsx` 都已列在 `.gitignore`，不會被 commit。
上傳 GitHub 前可以用 `git status` 確認沒有出現資料庫檔案。
