"""
股價解析：把證交所、櫃買中心回傳的資料，整理成 {代號: 價格}。

這裡只「解析」，不連網路（連網路在 quotes.py），所以可以用固定的範例資料測試。

資料來源（都是公開、免費、不用帳號）：
- 證交所 MIS 即時行情：盤中是最新成交價（約有幾秒延遲），收盤後是當天收盤價。上市、上櫃都查得到。
- 證交所 OpenAPI STOCK_DAY_ALL：上市股票、ETF 的每日收盤價（官方開放資料）。
- 櫃買中心 OpenAPI：上櫃股票的每日收盤價。
MIS 查不到時才用後兩個（只有收盤價）。
"""

from datetime import date


def normalize_symbol(symbol: str) -> str:
    """代號統一格式：去掉空白、英文轉大寫（例如 00631l → 00631L）。

    使用者有時會輸入「2330 台積電」，只取第一段。
    """
    parts = symbol.strip().split()
    return parts[0].upper() if parts else ""


def _to_price(text) -> float | None:
    """把行情裡的價格文字轉成數字；「-」、空白、0 都代表沒有價格。"""
    try:
        value = float(str(text).replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def parse_mis(data: dict) -> tuple[dict[str, float], date | None]:
    """解析 MIS 即時行情，回傳 ({代號: 價格}, 行情日期)。

    MIS 每一檔的欄位（只列用到的）：
      c 代號、z 最新成交價、b 買價（多個用 _ 分開，第一個是最好的買價）、y 昨天收盤價、d 日期 YYYYMMDD
    盤中有時候 z 是「-」（剛好這幾秒沒有成交），這時依序改用：最好的買價 → 昨收。
    """
    prices: dict[str, float] = {}
    quote_date = None
    for item in data.get("msgArray", []):
        code = normalize_symbol(item.get("c", ""))
        if not code:
            continue
        price = _to_price(item.get("z"))
        if price is None:
            best_bid = str(item.get("b", "")).split("_")[0]
            price = _to_price(best_bid)
        if price is None:
            price = _to_price(item.get("y"))
        if price is not None:
            prices[code] = price
        if item.get("d") and quote_date is None:
            d = str(item["d"])
            quote_date = date(int(d[:4]), int(d[4:6]), int(d[6:8]))
    return prices, quote_date


def roc_to_date(text: str) -> date | None:
    """民國年日期轉成 date，例如 '1151020' → 2026-10-20（民國 115 年 = 西元 2026 年）。"""
    text = str(text).strip()
    if len(text) != 7 or not text.isdigit():
        return None
    return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))


def parse_twse_daily(rows: list[dict]) -> tuple[dict[str, float], date | None]:
    """解析證交所 OpenAPI 的每日收盤價（欄位 Code、ClosingPrice、Date）。"""
    prices: dict[str, float] = {}
    quote_date = None
    for row in rows:
        price = _to_price(row.get("ClosingPrice"))
        if price is not None:
            prices[normalize_symbol(row.get("Code", ""))] = price
        quote_date = quote_date or roc_to_date(row.get("Date", ""))
    return prices, quote_date


def parse_tpex_daily(rows: list[dict]) -> tuple[dict[str, float], date | None]:
    """解析櫃買中心 OpenAPI 的每日收盤價（欄位 SecuritiesCompanyCode、Close、Date）。"""
    prices: dict[str, float] = {}
    quote_date = None
    for row in rows:
        price = _to_price(row.get("Close"))
        if price is not None:
            prices[normalize_symbol(row.get("SecuritiesCompanyCode", ""))] = price
        quote_date = quote_date or roc_to_date(row.get("Date", ""))
    return prices, quote_date


def is_trading_time(now) -> bool:
    """台股交易時間：週一到週五 9:00～13:30（國定假日不管，假日 MIS 只會給前一天的收盤價）。"""
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 <= minutes <= 13 * 60 + 30
