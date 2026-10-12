"""
下單前檢查：五個項目全部打勾，而且金額不超過手上現金，才可以下單。
"""

# 五個必須打勾的項目（畫面和判斷都讀這份清單）
CHECK_ITEMS = [
    "這不是當沖",
    "不是加碼虧損中的個股",
    "這個想法已經等了 7 天",
    "不是朋友或群組報的明牌",
    "緊急預備金已經存滿",
]


def check_order(amount: float, cash: float, checked: dict[str, bool]) -> tuple[bool, list[str]]:
    """判斷這筆單能不能下。

    amount：這筆要花的金額（股價 × 股數）
    cash：手上現金
    checked：{項目: 有沒有打勾}

    回傳 (可不可以下單, 不行的原因清單)。
    Python 可以一次回傳兩個值（其實是回傳一個 tuple），呼叫時用 ok, reasons = ... 接。
    """
    reasons = []

    if amount <= 0:
        reasons.append("請輸入這筆要花的金額")

    for item in CHECK_ITEMS:
        if not checked.get(item, False):
            reasons.append(f"還沒打勾：{item}")

    if amount > cash:
        reasons.append(f"金額 {amount:,.0f} 超過手上現金 {cash:,.0f}")

    # 沒有任何原因 = 可以下單
    return len(reasons) == 0, reasons
