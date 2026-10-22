"""
測試「本月還能花多少」的計算。

執行方式：在專案根目錄輸入 pytest
pytest 會自動找 tests/ 裡 test_ 開頭的檔案和函式來執行。
每個 test_ 函式就是一個測試案例，assert 後面的條件不成立就算失敗。
"""

from models.budget import (
    filter_month,
    remaining_by_category,
    remaining_this_month,
)

# 測試用的預算：總共 10000
BUDGETS = {"吃飯": 6000, "約會禮物": 2000, "交通": 1500, "其他": 500}


def make_expense(amount, category, date_str):
    """產生一筆測試用支出，少打一些字。"""
    return {"amount": amount, "category": category, "date": date_str, "note": ""}


def test_沒有支出時等於預算總和():
    assert remaining_this_month(BUDGETS, []) == 10000


def test_扣掉本月支出():
    expenses = [
        make_expense(120, "吃飯", "2026-10-01"),
        make_expense(80, "交通", "2026-10-03"),
    ]
    assert remaining_this_month(BUDGETS, expenses) == 10000 - 200


def test_超支時變成負數():
    expenses = [make_expense(12000, "其他", "2026-10-05")]
    assert remaining_this_month(BUDGETS, expenses) == -2000


def test_只算本月_其他月份不影響():
    all_expenses = [
        make_expense(500, "吃飯", "2026-09-30"),   # 上個月，不算
        make_expense(300, "吃飯", "2026-10-01"),   # 本月第一天
        make_expense(200, "交通", "2026-10-31"),   # 本月最後一天
        make_expense(999, "吃飯", "2025-10-15"),   # 去年同月，不算
    ]
    month_expenses = filter_month(all_expenses, 2026, 10)
    assert remaining_this_month(BUDGETS, month_expenses) == 10000 - 500


def test_預算全部是零():
    zero = {"吃飯": 0, "約會禮物": 0, "交通": 0, "其他": 0}
    expenses = [make_expense(50, "吃飯", "2026-10-02")]
    assert remaining_this_month(zero, expenses) == -50


def test_小數金額():
    expenses = [make_expense(0.1, "吃飯", "2026-10-01"), make_expense(0.2, "吃飯", "2026-10-01")]
    # 浮點數有誤差（0.1 + 0.2 != 0.3），比較時要容許一點點差距
    assert abs(remaining_this_month(BUDGETS, expenses) - 9999.7) < 1e-9


def test_各類別剩餘():
    expenses = [
        make_expense(1000, "吃飯", "2026-10-01"),
        make_expense(2500, "約會禮物", "2026-10-02"),  # 這個類別超支 500
    ]
    left = remaining_by_category(BUDGETS, expenses)
    assert left["吃飯"] == 5000
    assert left["約會禮物"] == -500   # 超支是負數
    assert left["交通"] == 1500 and left["其他"] == 500
    assert left["購物"] == 0          # 沒設預算、也沒花錢的類別是 0
