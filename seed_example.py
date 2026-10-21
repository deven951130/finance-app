"""
產生「假的範例資料」，給 README 截圖或試玩用。

所有數字都是虛構的，不是任何人的真實財務資料。
資料寫到 data/example.db，不會碰到你真正的 data/finance.db。

使用方式：
    python seed_example.py

然後用範例資料庫啟動：
    Windows PowerShell： $env:FINANCE_DB="data/example.db"; streamlit run app.py
    macOS / Linux：      FINANCE_DB=data/example.db streamlit run app.py
"""

import os
from datetime import date, timedelta

# 用 __file__ 算出絕對路徑，不管從哪個資料夾執行都寫到專案的 data/
EXAMPLE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "example.db")

# 一定要在 import db 之前設定環境變數，db.py 才會讀到範例資料庫的路徑
os.environ["FINANCE_DB"] = EXAMPLE_DB

import db  # noqa: E402  （故意放在設定環境變數之後）


def main() -> None:
    # 安全檢查：確定真的是寫到範例資料庫，避免蓋掉真實資料
    if os.path.basename(db.DB_PATH) != "example.db":
        raise SystemExit(f"停止：目前的資料庫是 {db.DB_PATH}，不是 example.db")

    # 每次都從頭產生，先刪掉舊的範例資料庫
    if os.path.exists(EXAMPLE_DB):
        os.remove(EXAMPLE_DB)
    db.init_db()

    today = date.today()

    def day(n: int) -> str:
        """本月第 n 天的日期字串；超過今天就用今天，避免出現未來的日期。"""
        return min(today.replace(day=n), today).isoformat()

    # 設定
    db.save_settings({
        "monthly_income": 42000,
        "cash_on_hand": 71500,  # 下面學貸還一期會扣 3500，剩 68000
        "emergency_fund": 17000,
        "emergency_target": 17000,
    })

    # 每月生活預算
    db.save_budgets({"吃飯": 7000, "約會禮物": 2500, "交通": 1500, "其他": 2000})

    # 本月記帳
    for amount, category, d, note in [
        (85, "吃飯", 1, "早餐"),
        (160, "吃飯", 1, "午餐便當"),
        (1280, "約會禮物", 2, "電影＋晚餐"),
        (1200, "交通", 3, "捷運月票"),
        (220, "吃飯", 4, "拉麵"),
        (450, "其他", 5, "生活用品"),
        (130, "吃飯", 6, "午餐"),
    ]:
        db.add_expense(amount, category, day(d), note)

    # 前 5 個月的記帳（給記帳頁的「最近 6 個月」趨勢圖用）。每個月金額稍微不同，其中一個月超支
    month_start = today.replace(day=1)
    for back, scale in [(1, 1.0), (2, 1.4), (3, 0.85), (4, 0.95), (5, 0.8)]:
        # 往回推 back 個月的 10 號、20 號
        m = month_start
        for _ in range(back):
            m = (m - timedelta(days=1)).replace(day=1)
        for d, amount, category, note in [
            (3, 2600, "吃飯", "上旬伙食"),
            (13, 3100, "吃飯", "中旬伙食"),
            (20, 1800, "約會禮物", "週末出遊"),
            (2, 1200, "交通", "捷運月票"),
            (22, 1500, "其他", "日用品"),
        ]:
            db.add_expense(round(amount * scale), category, m.replace(day=d).isoformat(), note)

    # 固定支出
    for name, amount in [("電話費", 499), ("iCloud", 90), ("Spotify", 149)]:
        db.add_fixed_expense(name, amount)

    # 負債
    db.add_debt("範例學貸", 89500, 3500)
    db.add_debt("範例手機分期", 9000, 1500)
    # 學貸本月已經還過一期（示範「本月已還」和還款紀錄；會從手上現金扣 3500）
    db.pay_debt_installment(db.get_debts()[0]["id"], day(5))

    # 持股（台積電放在兩個帳戶，示範合併；範例股價都是虛構的）
    db.add_holding("台積電", "2330", "A 證券", 20, 820, 1000)
    db.add_holding("台積電", "2330", "B 證券", 30, 900, 1000)
    db.add_holding("元大台灣50", "0050", "A 證券", 400, 160, 175)  # 占比超過 40%，示範警告
    db.add_holding("範例虧損股", "9999", "B 證券", 1000, 48, 39)

    # 交易紀錄（含一筆當沖，示範總覽頁的警告）
    last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=15).isoformat()
    db.add_trade(last_month, "2330 台積電", "買進", 0, "定期定額")
    db.add_trade(day(2), "0050 元大台灣50", "買進", 0, "")
    db.add_trade(day(4), "9999 範例虧損股", "當沖", -1200, "示範用：衝動當沖")
    db.add_trade(day(5), "2330 台積電", "賣出", 3500, "部分停利")

    # 過去 6 個月的淨資產紀錄（每兩週一筆，慢慢往上，中間有一次股票下跌），示範總覽的「淨資產變化」
    for i, value in enumerate([88000, 93500, 97000, 104000, 101500, 109000, 113500,
                               118000, 115000, 121500, 126000, 129000]):
        db.record_networth((today - timedelta(days=14 * (12 - i))).isoformat(), value)

    print(f"已產生範例資料：{EXAMPLE_DB}")


if __name__ == "__main__":
    main()
