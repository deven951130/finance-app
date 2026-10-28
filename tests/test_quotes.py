"""
測試股價解析（models/quotes.py）與抓股價的備援流程（quotes.py）。

不連網路：解析用固定的範例資料（格式照證交所、櫃買中心實際回傳的樣子，數字是虛構的）；
抓股價的流程用 monkeypatch 換掉真正連網路的函式。
"""

from datetime import date, datetime

import pytest

import quotes
from models.quotes import (
    is_trading_time,
    normalize_symbol,
    parse_mis,
    parse_tpex_daily,
    parse_twse_daily,
    roc_to_date,
)

MIS_SAMPLE = {"msgArray": [
    {"c": "2330", "z": "1000.0000", "b": "999.0000_998.0000_", "y": "990.0000", "d": "20261021"},
    # 這幾秒剛好沒有成交：z 是「-」，改用最好的買價
    {"c": "0050", "z": "-", "b": "150.5000_150.4500_", "y": "149.0000", "d": "20261021"},
    # 連買價都沒有（例如開盤前）：用昨收
    {"c": "6488", "z": "-", "b": "-", "y": "800.0000", "d": "20261021"},
    # 完全沒有價格：不放進結果
    {"c": "9999", "z": "-", "b": "", "y": "-", "d": "20261021"},
]}


def test_MIS_依序用成交價_買價_昨收():
    prices, quote_date = parse_mis(MIS_SAMPLE)
    assert prices == {"2330": 1000.0, "0050": 150.5, "6488": 800.0}
    assert quote_date == date(2026, 10, 21)


def test_MIS_沒有資料():
    assert parse_mis({}) == ({}, None)


def test_民國年轉西元():
    assert roc_to_date("1151020") == date(2026, 10, 20)
    assert roc_to_date("") is None


def test_證交所每日收盤價():
    rows = [
        {"Date": "1151020", "Code": "2330", "ClosingPrice": "1000.00"},
        {"Date": "1151020", "Code": "1234", "ClosingPrice": ""},  # 當天沒成交
    ]
    assert parse_twse_daily(rows) == ({"2330": 1000.0}, date(2026, 10, 20))


def test_櫃買中心每日收盤價():
    rows = [{"Date": "1151020", "SecuritiesCompanyCode": "6488", "Close": "800.00"}]
    assert parse_tpex_daily(rows) == ({"6488": 800.0}, date(2026, 10, 20))


def test_代號統一格式():
    assert normalize_symbol(" 2330 台積電 ") == "2330"
    assert normalize_symbol("00631l") == "00631L"
    assert normalize_symbol("   ") == ""


def test_交易時間():
    assert is_trading_time(datetime(2026, 10, 21, 10, 0))       # 週三 10:00
    assert is_trading_time(datetime(2026, 10, 21, 13, 30))      # 收盤那一分鐘
    assert not is_trading_time(datetime(2026, 10, 21, 13, 31))
    assert not is_trading_time(datetime(2026, 10, 21, 8, 59))
    assert not is_trading_time(datetime(2026, 10, 24, 10, 0))   # 週六


# ---------- 抓股價的備援流程（不連網路） ----------

def test_MIS正常時用即時行情_查不到的列出來(monkeypatch):
    monkeypatch.setattr(quotes, "fetch_mis", lambda s: ({"2330": 1000.0}, date(2026, 10, 21)))

    def should_not_download():
        raise AssertionError("MIS 正常時不應該下載每日收盤價清單")
    monkeypatch.setattr(quotes, "fetch_daily", should_not_download)
    r = quotes.fetch_prices(["2330", "某基金"])
    assert r.prices == {"2330": 1000.0}
    assert r.source == "realtime"
    assert r.missing == ["某基金"]
    assert r.error == ""


def test_MIS失敗時改用每日收盤價(monkeypatch):
    def down(symbols):
        raise OSError("連不上")
    monkeypatch.setattr(quotes, "fetch_mis", down)
    monkeypatch.setattr(quotes, "fetch_daily", lambda: ({"2330": 990.0, "6488": 800.0}, date(2026, 10, 20)))
    r = quotes.fetch_prices(["2330", "6488"])
    assert r.prices == {"2330": 990.0, "6488": 800.0}
    assert r.source == "daily"
    assert r.quote_date == date(2026, 10, 20)


def test_全部都連不上_回傳原因_不丟例外(monkeypatch):
    def down(*args):
        raise OSError("沒有網路")
    monkeypatch.setattr(quotes, "fetch_mis", down)
    monkeypatch.setattr(quotes, "fetch_daily", down)
    r = quotes.fetch_prices(["2330"])
    assert r.prices == {}
    assert "沒有網路" in r.error


def test_沒有持股就不連網路(monkeypatch):
    def should_not_call(*args):
        raise AssertionError("不應該連網路")
    monkeypatch.setattr(quotes, "fetch_mis", should_not_call)
    assert quotes.fetch_prices([]).prices == {}
