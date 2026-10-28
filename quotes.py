"""
連網路抓股價。這是整個程式唯一會連到外面的地方。

送出去的只有「股票代號」（例如 2330），不會送股數、金額或任何其他資料。
使用者可以在設定頁關掉「自動更新股價」，關掉後就完全不會連線。

分工（和 db.py、models/ 一樣分開）：
- 這個檔案：發出網路請求、處理逾時與錯誤
- models/quotes.py：把回傳的資料解析成 {代號: 價格}（純函式，方便測試）
"""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date

from models.quotes import normalize_symbol, parse_mis, parse_names, parse_tpex_daily, parse_twse_daily

MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TWSE_DAILY_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_DAILY_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

# 有些網站會擋掉 Python 預設的 User-Agent（直接回 403），所以用一般瀏覽器的寫法
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FinanceApp"}
TIMEOUT = 10  # 秒；網路不通時最多等這麼久，不會讓畫面卡住太久


@dataclass
class QuoteResult:
    """一次抓股價的結果。"""
    prices: dict[str, float] = field(default_factory=dict)  # {代號: 價格}
    quote_date: date | None = None   # 行情是哪一天的
    source: str = ""                 # "realtime"（MIS 即時／當天收盤）或 "daily"（官方每日收盤價）
    missing: list[str] = field(default_factory=list)  # 查不到的代號（例如基金、打錯的代號）
    error: str = ""                  # 完全抓不到時的原因


def _get_json(url: str):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _mis_raw(symbols: list[str]) -> dict:
    """MIS 即時行情的原始資料。不知道每檔是上市（tse）還是上櫃（otc），所以兩種都問，查不到的 MIS 會自動略過。"""
    channels = "|".join(f"{market}_{s}.tw" for s in symbols for market in ("tse", "otc"))
    url = f"{MIS_URL}?ex_ch={urllib.parse.quote(channels, safe='|_.')}&json=1&delay=0"
    return _get_json(url)


def fetch_mis(symbols: list[str]) -> tuple[dict[str, float], date | None]:
    """問 MIS 即時行情，回傳 ({代號: 價格}, 行情日期)。"""
    return parse_mis(_mis_raw(symbols))


def lookup(symbol: str) -> dict | None:
    """新增持股時用：只給代號，查出名稱和現價，回傳 {"symbol", "name", "price"}；查不到或連不上回傳 None。

    先問 MIS；MIS 連不上或查不到，再找官方每日收盤價的清單（上市 + 上櫃，有名稱）。
    """
    code = normalize_symbol(symbol)
    if not code:
        return None
    try:
        data = _mis_raw([code])
        name = parse_names(data).get(code)
        price = parse_mis(data)[0].get(code)
        if name and price:
            return {"symbol": code, "name": name, "price": price}
    except (OSError, ValueError):
        pass
    try:
        for url, parse in ((TWSE_DAILY_URL, parse_twse_daily), (TPEX_DAILY_URL, parse_tpex_daily)):
            rows = _get_json(url)
            name, price = parse_names(rows).get(code), parse(rows)[0].get(code)
            if name and price:
                return {"symbol": code, "name": name, "price": price}
    except (OSError, ValueError):
        pass
    return None


def fetch_daily() -> tuple[dict[str, float], date | None]:
    """問官方開放資料的每日收盤價（上市 + 上櫃）。整份清單一次下載，不會送出任何代號。"""
    prices, quote_date = parse_twse_daily(_get_json(TWSE_DAILY_URL))
    try:
        otc_prices, otc_date = parse_tpex_daily(_get_json(TPEX_DAILY_URL))
        prices.update(otc_prices)
        quote_date = quote_date or otc_date
    except (OSError, ValueError):
        pass  # 櫃買中心抓不到時，至少還有上市的
    return prices, quote_date


def fetch_prices(symbols: list[str]) -> QuoteResult:
    """抓這些代號的最新價格。先問 MIS，MIS 失敗或有查不到的，再用官方每日收盤價補。

    不會丟出例外：網路斷線、網站沒回應時，回傳的 error 會寫原因，畫面照常顯示舊價格。
    """
    wanted = sorted({normalize_symbol(s) for s in symbols if normalize_symbol(s)})
    result = QuoteResult()
    if not wanted:
        return result

    errors = []
    try:
        prices, quote_date = fetch_mis(wanted)
        result.prices = {s: prices[s] for s in wanted if s in prices}
        result.quote_date, result.source = quote_date, "realtime"
    except (OSError, ValueError) as e:  # OSError 包含連不上、逾時；ValueError 是回傳的不是 JSON
        errors.append(f"即時行情：{e}")

    # 只有 MIS 整個失敗才改用每日收盤價。
    # MIS 正常但查不到的代號（基金、海外股票、打錯），每日收盤價的清單裡通常也沒有，
    # 不值得每 5 分鐘下載一次好幾 MB 的清單
    if errors:
        try:
            prices, quote_date = fetch_daily()
            result.prices = {s: prices[s] for s in wanted if s in prices}
            result.quote_date, result.source = quote_date, "daily"
        except (OSError, ValueError) as e:
            errors.append(f"每日收盤價：{e}")

    result.missing = [s for s in wanted if s not in result.prices]
    if not result.prices and errors:
        result.error = "；".join(errors)
    return result
