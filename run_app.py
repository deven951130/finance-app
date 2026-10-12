"""
exe 的啟動入口。

平常開發時我們在終端機輸入 streamlit run app.py。
打包成 exe 之後沒有終端機可以打指令，所以用這個檔案「代替我們輸入那行指令」：
它把參數塞進 sys.argv，再呼叫 Streamlit 自己的命令列程式。

開發時也可以直接執行：python run_app.py
"""

import os
import sys
import traceback


def resource_path(relative: str) -> str:
    """找到打包進 exe 的檔案。

    exe 啟動時，PyInstaller 會把程式檔解壓到一個暫存資料夾，路徑放在 sys._MEIPASS。
    沒有打包（直接用 python 執行）時，就用這個檔案所在的資料夾。
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def main() -> None:
    # 放在函式裡才 import：如果連 Streamlit 都載入失敗，也能被下面的 try 抓到並顯示原因
    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        resource_path("app.py"),
        # 以下都是 Streamlit 的設定，等同寫在 .streamlit/config.toml 裡
        "--global.developmentMode=false",       # exe 裡一定要關掉開發模式
        "--server.headless=false",              # 啟動後自動打開瀏覽器
        "--server.showEmailPrompt=false",       # 不要在黑色視窗問你的 email
        "--server.address=localhost",           # 只有自己這台電腦連得到，區網其他人連不到
        "--server.fileWatcherType=none",        # exe 裡的程式不會改，不需要監看檔案
        "--browser.gatherUsageStats=false",     # 不傳送使用統計給 Streamlit
        "--client.toolbarMode=minimal",         # 隱藏右上角的 Deploy 等開發者按鈕
    ]
    sys.exit(stcli.main())


def show_error_and_wait(message: str) -> None:
    """程式出錯時，把錯誤印出來並存成檔案，然後停住，不讓黑色視窗直接關掉。"""
    log_dir = os.path.join(os.path.expanduser("~"), "FinanceApp")
    log_path = os.path.join(log_dir, "error.log")
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(message)
    except OSError:
        log_path = "(could not write log file)"

    # 用英文，避免 Windows 黑色視窗的編碼問題
    print()
    print("=" * 60)
    print("FinanceApp crashed. Error details:")
    print("=" * 60)
    print(message)
    print(f"This error was also saved to: {log_path}")
    input("Press Enter to close this window...")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        # 正常結束是 0（或 None）；其他代碼代表 Streamlit 啟動失敗
        if e.code not in (0, None):
            show_error_and_wait(f"Streamlit exited with code {e.code}")
        raise
    except Exception:
        # 任何其他錯誤（按 Ctrl+C 結束不算錯誤，所以不用 BaseException）：顯示完整的錯誤訊息（traceback）
        show_error_and_wait(traceback.format_exc())
        raise
