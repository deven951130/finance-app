"""
exe 的啟動入口。

平常開發時我們在終端機輸入 streamlit run app.py。
打包成 exe 之後沒有終端機可以打指令，所以用這個檔案「代替我們輸入那行指令」：
它把參數塞進 sys.argv，再呼叫 Streamlit 自己的命令列程式。

開發時也可以直接執行：python run_app.py
"""

import os
import sys

from streamlit.web import cli as stcli


def resource_path(relative: str) -> str:
    """找到打包進 exe 的檔案。

    exe 啟動時，PyInstaller 會把程式檔解壓到一個暫存資料夾，路徑放在 sys._MEIPASS。
    沒有打包（直接用 python 執行）時，就用這個檔案所在的資料夾。
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def main() -> None:
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


if __name__ == "__main__":
    main()
