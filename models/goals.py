"""
儲蓄目標（像「任務」）：一個目標（例如 日本旅遊）底下有好幾個細項（機票、住宿、交通、購物），
每個細項有自己的目標金額，存一筆記一筆，各自看進度。

存進目標的錢只是「記在這個目標名下」，錢其實還在原本的銀行帳戶裡，
所以這裡不動帳戶、也不影響淨資產（動了就重複算）。
"""

from datetime import date


def progress_ratio(saved: float, target: float) -> float:
    """存到幾成（0 ~ 1），進度條用。目標 0 元時當作 0；存超過目標也只算到 1。"""
    if target <= 0:
        return 0.0
    return min(max(saved / target, 0.0), 1.0)


def item_done(saved: float, target: float) -> bool:
    """這個細項達成了沒：目標要大於 0，而且存到的 >= 目標。"""
    return target > 0 and saved >= target


def goal_done(items: list[dict]) -> bool:
    """整個目標達成了沒：至少一個細項，而且每個細項都達成。還沒列細項的目標不算達成。"""
    return bool(items) and all(item_done(i["saved"], i["target"]) for i in items)


def goal_totals(items: list[dict]) -> dict:
    """整個目標的合計。每個細項至少有 'saved'、'target'。

    remaining（還差多少）是「每個細項各自還差多少」加起來：
    機票存超過了，多的不會自動補到住宿（要的話自己取出再存進住宿），
    這樣每個細項的進度才和畫面上看到的一致。
    """
    target = sum(i["target"] for i in items)
    saved = sum(i["saved"] for i in items)
    remaining = sum(max(i["target"] - i["saved"], 0.0) for i in items)
    ratio = (target - remaining) / target if target > 0 else 0.0
    return {"target": target, "saved": saved, "remaining": remaining, "ratio": ratio}


def months_until(today: date, deadline: date | None) -> int | None:
    """從這個月到截止月份還有幾個月可以存（這個月和截止那個月都算）。

    例如今天 11/25、截止 2027/4/10：11、12、1、2、3、4 月，共 6 個月。
    沒有截止日回傳 None；截止日已經過了回傳 0。
    """
    if deadline is None:
        return None
    if deadline < today:
        return 0
    return (deadline.year - today.year) * 12 + (deadline.month - today.month) + 1


def monthly_needed(remaining: float, months: int | None) -> float | None:
    """每個月要存多少才來得及。沒有截止日（months 是 None）或已經過期（0）回傳 None。"""
    if not months:
        return None
    return max(remaining, 0.0) / months


def parse_item_lines(text: str) -> tuple[list[tuple[str, float]], list[str]]:
    """把「一行一個細項」的文字拆成 [(名稱, 目標金額), ...]，新增目標時一次列好細項用。

    每一行最後一段是金額，前面是名稱，例如「來回機票 12,000」→ ("來回機票", 12000)。
    金額可以有千分位逗號或「元」。空白行略過；看不懂的行（沒有金額、沒有名稱、金額是負的）
    放進第二個回傳值，讓畫面告訴使用者哪幾行沒加進去。
    """
    items, bad = [], []
    for line in text.splitlines():
        line = line.replace("　", " ").strip()  # 中文輸入法常打出全形空白，當成一般空白
        if not line:
            continue
        name, _, amount = line.rpartition(" ")  # 從最後一個空白切開：名稱裡可以有空白
        try:
            value = float(amount.replace(",", "").removesuffix("元"))
        except ValueError:
            value = -1.0
        if name.strip() and value >= 0:
            items.append((name.strip(), value))
        else:
            bad.append(line)
    return items, bad


def withdraw_amount(saved: float, amount: float) -> float:
    """這次實際能取出多少：不能取出比存的還多（不會變成負的）。"""
    return min(amount, max(saved, 0.0))
