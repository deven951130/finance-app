"""
啟動時檢查版本：太舊就要求用 Onei Hub 更新。

做法：讀 Onei Hub 伺服器上公開的軟體清單（catalog.json），找到「OniPulsar 星脈流轉」（id 還是 finance-app）的 min_version（最低可用版本），
目前版本（version.py）比它舊，畫面就整個擋住，只顯示「需要更新」。

規則（2026-10-21 使用者決定）：
- 每次發新版都強制更新（發布時把 min_version 設成新版本號）。
- 確定版本太舊才擋；沒網路、伺服器沒回應、資料格式不對，一律放行，
  不然伺服器停機時所有人都打不開，連自己的理財資料都看不到。

只是下載一份公開的清單，不會送出任何資料。
"""

import json
import os
import subprocess
import sys
import urllib.request
import webbrowser

from models.version import update_status
from version import APP_VERSION

APP_ID = "finance-app"
CATALOG_URL = "https://oneihub.absoluteaxis.dpdns.org/catalog.json"
HUB_LINK = f"oneihub://app/{APP_ID}"   # Onei Hub 會被叫出來並跳到「OniPulsar 星脈流轉」頁
HUB_DOWNLOAD = "https://oneihub.absoluteaxis.dpdns.org/#download"
TIMEOUT = 5  # 秒：沒網路時最多讓啟動慢這麼久

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FinanceApp"}


def check() -> dict | None:
    """回傳 update_status() 的結果；任何錯誤（沒網路、逾時、格式不對）都回傳 None，代表放行。"""
    try:
        request = urllib.request.Request(CATALOG_URL, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            catalog = json.loads(response.read().decode("utf-8"))
        return update_status(catalog, APP_ID, APP_VERSION)
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def open_hub() -> bool:
    """叫出 Onei Hub 並跳到「OniPulsar 星脈流轉」。成功送出回傳 True。

    用作業系統打開 oneihub:// 連結（和在檔案總管點連結一樣），不從網頁裡開：
    視窗版的網頁元件不一定允許打開自訂協定。
    """
    try:
        if sys.platform == "win32":
            os.startfile(HUB_LINK)  # 沒裝 Onei Hub 時會丟出 OSError
        elif sys.platform == "darwin":
            subprocess.run(["open", HUB_LINK], check=True)
        else:
            subprocess.run(["xdg-open", HUB_LINK], check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def open_download_page() -> None:
    """用預設瀏覽器打開 Onei Hub 下載頁。"""
    webbrowser.open(HUB_DOWNLOAD)
