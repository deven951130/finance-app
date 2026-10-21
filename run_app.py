"""
exe 的啟動入口：把理財系統開在「自己的視窗」裡，像一般 Windows 軟體。

平常開發時我們在終端機輸入 streamlit run app.py，再用瀏覽器看畫面。
打包成軟體後，我們希望點兩下就跳出一個視窗，不要黑色視窗、也不要開瀏覽器。

做法分成兩個部分（類比 C++：一個程式啟動兩個 process）：
1. 「伺服器」：在背景執行 Streamlit，負責算資料、產生畫面。
   用同一個 exe 再啟動一次自己，加上 --server 參數，就會走這條路。
2. 「視窗」：用 pywebview 開一個視窗。它內建 Windows 的 Edge 網頁元件（WebView2，
   Windows 10/11 都已經有），把伺服器產生的畫面顯示在視窗裡。
關掉視窗時，程式會順便把背景的伺服器關掉。

開發時也可以直接執行：python run_app.py（需要先 pip install pywebview）
"""

import logging
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request

APP_TITLE = "個人理財管理系統"

# 資料、錯誤紀錄都放在這個資料夾（和 db.py 的資料庫位置相同）
LOG_DIR = os.path.join(os.path.expanduser("~"), "FinanceApp")
SERVER_LOG = os.path.join(LOG_DIR, "server.log")

# 視窗版的資料庫一律放在 ~/FinanceApp/finance.db。
# PyInstaller 版靠 db.py 的 sys.frozen 判斷；安裝版是「官方 Python + 原始碼」（見 installer/build_runtime.py），
# 沒有 sys.frozen，所以在這裡用環境變數告訴 db.py。背景伺服器是這個程式開的，會繼承這個環境變數。
# setdefault：測試時可以先設定 FINANCE_DB 指到別的檔案，不會被蓋掉
os.environ.setdefault("FINANCE_DB", os.path.join(LOG_DIR, "finance.db"))

# 安裝版的圖示放在 app 資料夾的上一層（見 installer/build_runtime.py）
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "icon.ico")
# 工作列用這個名字分辨「是哪個程式」。不設定的話，視窗會被當成 Python，工作列顯示 Python 的圖示。
# 要和安裝程式捷徑的 AppUserModelID 一樣（installer/FinanceApp.iss）
APP_ID = "deven951130.FinanceApp"
# 視窗這一端的紀錄：用了哪個網頁引擎、載入了哪個網址。畫面出問題時看這個檔案
APP_LOG = os.path.join(LOG_DIR, "app.log")


def resource_path(relative: str) -> str:
    """找到打包進 exe 的檔案。

    exe 啟動時，PyInstaller 會把程式檔放在 sys._MEIPASS 這個資料夾。
    沒有打包（直接用 python 執行）時，就用這個檔案所在的資料夾。
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


# ---------------------------------------------------------------------------
# 第 1 部分：伺服器（在背景跑 Streamlit）
# ---------------------------------------------------------------------------

def run_server(port: int, window_pid: int) -> None:
    """代替我們輸入 streamlit run app.py。這個函式在背景的那個 process 裡執行。"""
    # 放在函式裡才 import：視窗那邊用不到 Streamlit，啟動比較快
    from streamlit import config as st_config
    from streamlit.web import cli as stcli

    # Streamlit 會讀「目前資料夾」底下的 .streamlit/config.toml（主題配色），
    # 所以先切換到打包好的檔案所在的資料夾。
    # （資料庫路徑是用絕對路徑算的，見 db.py，不受這行影響）
    os.chdir(resource_path("."))

    sys.argv = [
        "streamlit",
        "run",
        resource_path("app.py"),
        # 以下都是 Streamlit 的設定，等同寫在 .streamlit/config.toml 裡
        "--global.developmentMode=false",       # exe 裡一定要關掉開發模式
        "--server.headless=true",               # 不要自己開瀏覽器，畫面由我們的視窗顯示
        f"--server.port={port}",
        # 只有自己這台電腦連得到，區網其他人連不到。
        # 用 127.0.0.1 而不是 localhost：Windows 上 localhost 可能先被解析成 IPv6（::1），
        # 伺服器和視窗如果一個用 IPv4、一個用 IPv6，就會連不上
        "--server.address=127.0.0.1",
        "--server.fileWatcherType=none",        # exe 裡的程式不會改，不需要監看檔案
        "--browser.gatherUsageStats=false",     # 不傳送使用統計給 Streamlit
        "--client.toolbarMode=minimal",         # 隱藏右上角的 Deploy 等開發者按鈕
    ]

    # 新版 Streamlit 偵測到電腦上有 AI 寫程式工具時，會在畫面右上角跳出
    # 「Help agents write better apps」的開發者提示。這個設定可以關掉它，
    # 但舊版 Streamlit 沒有這個設定（給它不認識的參數會無法啟動），所以先查有沒有。
    if "logger.hideWelcomeMessage" in getattr(st_config, "_config_options_template", {}):
        sys.argv.append("--logger.hideWelcomeMessage=true")

    # 保險：如果視窗那邊意外當掉（沒機會叫我們結束），伺服器也要自己結束，不然會一直留在背景
    threading.Thread(target=exit_when_window_closes, args=(window_pid,), daemon=True).start()

    sys.exit(stcli.main())


def exit_when_window_closes(window_pid: int) -> None:
    """等「視窗那個 process」結束，伺服器就跟著結束。在背景執行緒裡跑。

    注意：以前用「讀 stdin 管線、管線斷了就結束」的寫法，但在 Windows 上，
    一個執行緒卡在讀管線時，Streamlit 送網頁檔案（讀檔）也會跟著卡住，
    視窗就只剩一片空白。所以改成直接問作業系統「那個 process 還在不在」，完全不碰檔案。
    """
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000  # 只要求「可以等它結束」的權限
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, window_pid)
        if handle:
            kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)  # 一直等，直到視窗的 process 結束
    else:
        # macOS / Linux：父 process 結束後，我們的 getppid() 會變成別的數字
        while os.getppid() == window_pid:
            time.sleep(2)
    os._exit(0)


def find_free_port() -> int:
    """找一個目前沒人用的連接埠，避免和其他程式（或另一個開著的理財系統）撞到。

    測試時可以用環境變數 FINANCE_APP_PORT 指定固定的連接埠。
    """
    if os.environ.get("FINANCE_APP_PORT"):
        return int(os.environ["FINANCE_APP_PORT"])
    # 連接埠填 0，作業系統會自動挑一個空的給我們
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int) -> subprocess.Popen:
    """用同一個程式再啟動一次自己，加上 --server，讓它在背景當伺服器。"""
    if getattr(sys, "frozen", False):
        # 打包後：sys.executable 就是 FinanceApp.exe 自己
        command = [sys.executable, "--server", str(port), str(os.getpid())]
    else:
        # 開發時：sys.executable 是 python，要告訴它跑哪個檔案
        command = [sys.executable, os.path.abspath(__file__), "--server", str(port), str(os.getpid())]

    os.makedirs(LOG_DIR, exist_ok=True)
    # 伺服器的訊息寫到 server.log，出問題時可以打開來看
    log_file = open(SERVER_LOG, "w", encoding="utf-8")
    # CREATE_NO_WINDOW：Windows 上不要替背景程式開黑色視窗（其他系統沒有這個設定，用 0）
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # 用同一個程式再開一個 process，把自己的 process 編號傳過去，
    # 伺服器會盯著這個編號，視窗結束它就結束（見 exit_when_window_closes）
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )


def wait_until_ready(port: int, server: subprocess.Popen, timeout: float = 90) -> None:
    """一直問伺服器「好了沒」，直到它回答 ok。

    Streamlit 內建一個健康檢查網址 /_stcore/health，準備好時會回應 ok。
    如果伺服器中途結束（出錯），或等太久，就丟出錯誤。
    """
    url = f"http://127.0.0.1:{port}/_stcore/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"背景伺服器意外結束（代碼 {server.returncode}）")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.read().strip() == b"ok":
                    return
        except OSError:
            pass  # 還沒準備好，等一下再問
        time.sleep(0.3)
    raise RuntimeError(f"等了 {timeout:.0f} 秒，背景伺服器還沒準備好")


# ---------------------------------------------------------------------------
# 第 2 部分：視窗
# ---------------------------------------------------------------------------

# 伺服器還在啟動時，視窗先顯示這個畫面，免得使用者以為沒反應
LOADING_HTML = """
<html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#F6F4EF;color:#1F2633;font-family:'Microsoft JhengHei','PingFang TC',sans-serif;">
<div style="text-align:center">
  <div style="font-size:22px;font-weight:600;margin-bottom:8px">個人理財管理系統</div>
  <div style="font-size:15px;color:#6B7280">正在啟動，請稍候…</div>
</div></body></html>
"""


def current_renderer(webview_module) -> str:
    """查 pywebview 實際用的是哪個網頁引擎。

    Windows 上正常應該是 edgechromium（Edge WebView2）。
    如果是 mshtml，代表電腦上找不到 WebView2，pywebview 退回舊的 IE 引擎，
    而 IE 顯示不了 Streamlit 的畫面，視窗就會一片空白。
    """
    try:
        return webview_module.guilib.guilib.renderer
    except AttributeError:
        return "unknown"


def set_window_icon(window) -> None:
    """把視窗左上角和工作列的圖示換成理財系統的圖示（Windows 安裝版才有 icon.ico）。

    pythonw.exe 開的視窗預設是 Python 的圖示。WM_SETICON 是 Windows 換視窗圖示的訊息，
    用 SendMessage 送給視窗就好，不用管視窗是哪個執行緒建立的。
    """
    if sys.platform != "win32" or not os.path.exists(ICON):
        return
    import ctypes
    user32 = ctypes.windll.user32
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    hwnd = window.native.Handle.ToInt64()  # pywebview 在 Windows 上的視窗是 WinForms 的 Form
    IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x80
    for kind, size in [(0, 16), (1, 32)]:  # 0 = 小圖示（標題列），1 = 大圖示（工作列、Alt+Tab）
        icon = user32.LoadImageW(None, os.path.abspath(ICON), IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if icon:
            user32.SendMessageW(hwnd, WM_SETICON, kind, icon)


def main() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    # 把紀錄寫進 app.log（pywebview 自己的警告也會一起寫進來）
    logging.basicConfig(
        filename=APP_LOG, filemode="w", encoding="utf-8", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("FinanceApp")

    # 放在函式裡才 import：如果 pywebview 載入失敗，也能被下面的 try 抓到並顯示原因
    import webview

    # 允許「設定」頁的「匯出 CSV 備份」按鈕下載檔案（預設是關的）
    webview.settings["ALLOW_DOWNLOADS"] = True
    # 自動測試用：設定這個環境變數，就能從外面連進視窗檢查畫面有沒有正常顯示
    if os.environ.get("FINANCE_APP_DEBUG_PORT"):
        webview.settings["REMOTE_DEBUGGING_PORT"] = int(os.environ["FINANCE_APP_DEBUG_PORT"])

    port = find_free_port()
    server = start_server(port)
    startup_error = []  # 背景執行緒發生的錯誤放這裡，等視窗關掉後再顯示

    window = webview.create_window(
        APP_TITLE,
        html=LOADING_HTML,
        width=1280,
        height=860,
        min_size=(420, 600),
    )

    def load_app() -> None:
        """視窗開好之後，在背景執行緒等伺服器準備好，再把畫面換成理財系統。"""
        try:
            renderer = current_renderer(webview)
            log.info("pywebview %s, renderer=%s", getattr(webview, "__version__", "?"), renderer)
            if renderer == "mshtml":
                raise RuntimeError(
                    "這台電腦找不到 Microsoft Edge WebView2 Runtime，視窗無法顯示畫面。\n"
                    "請到 https://developer.microsoft.com/microsoft-edge/webview2/ "
                    "下載安裝「Evergreen Bootstrapper」，裝好後再打開一次。"
                )
            wait_until_ready(port, server)
            url = f"http://127.0.0.1:{port}"
            log.info("server ready, loading %s", url)
            window.load_url(url)
        except Exception:
            log.exception("startup failed")
            startup_error.append(traceback.format_exc())
            window.destroy()

    def on_shown() -> None:
        """視窗真的出現之後才換圖示（在這之前 window.native 還是 None）。"""
        try:
            set_window_icon(window)
        except Exception:  # 換不了圖示不影響使用，記下來就好
            log.exception("set icon failed")

    window.events.shown += on_shown

    try:
        # start() 會一直停在這裡，直到使用者關掉視窗
        webview.start(load_app)
    finally:
        # 視窗關了：把背景伺服器也關掉，不留在背景佔記憶體
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    if startup_error:
        raise RuntimeError(startup_error[0] + "\n伺服器訊息：\n" + read_server_log())


# ---------------------------------------------------------------------------
# 出錯時的處理
# ---------------------------------------------------------------------------

def read_server_log() -> str:
    """讀背景伺服器的紀錄最後 40 行，附在錯誤訊息裡。"""
    try:
        with open(SERVER_LOG, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-40:])
    except OSError:
        return "(沒有伺服器紀錄)"


def show_error(message: str) -> None:
    """把錯誤存成 error.log，再跳出對話框告訴使用者。

    視窗版沒有黑色視窗可以印訊息，所以 Windows 上用系統內建的對話框（MessageBox）。
    """
    log_path = os.path.join(LOG_DIR, "error.log")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(message)
    except OSError:
        log_path = "(無法寫入紀錄檔)"

    text = (
        "程式發生錯誤，無法開啟。\n\n"
        f"詳細的錯誤訊息存在：\n{log_path}\n\n"
        "可以把這個檔案的內容貼給 Claude 協助排除。\n\n"
        + message[-1500:]  # 對話框放不下太長的內容，只顯示最後一段
    )
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, APP_TITLE, 0x10)  # 0x10 = 紅色叉叉圖示
    else:
        print(text, file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--server":
        # 背景伺服器：錯誤訊息會寫進 server.log，由視窗那邊負責顯示
        run_server(port=int(sys.argv[2]), window_pid=int(sys.argv[3]))
    else:
        try:
            main()
        except Exception:
            show_error(traceback.format_exc())
            sys.exit(1)
