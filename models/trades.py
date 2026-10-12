"""
交易紀錄的統計。
"""

from models.budget import filter_month

TRADE_TYPES = ["買進", "賣出", "當沖"]


def count_day_trades(trades: list[dict], year: int, month: int) -> int:
    """算某年某月有幾筆當沖。每筆交易需要 'date'（YYYY-MM-DD）和 'type'。"""
    # filter_month 是第一階段寫給記帳用的，日期格式一樣，可以直接重複使用
    return sum(1 for t in filter_month(trades, year, month) if t["type"] == "當沖")


def total_pnl(trades: list[dict]) -> float:
    """把交易的損益加總（買進通常填 0）。"""
    return sum(t["pnl"] for t in trades)
