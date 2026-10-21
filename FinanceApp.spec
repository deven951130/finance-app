# PyInstaller 打包設定檔（這個檔案本身就是 Python 程式）
#
# 使用方式：pyinstaller FinanceApp.spec
# 打包結果：dist/FinanceApp/ 資料夾，裡面的 FinanceApp.exe（Mac 是 FinanceApp）就是主程式
#
# 為什麼需要這個設定檔：
# PyInstaller 會從 run_app.py 開始，順著 import 找出要打包哪些東西。
# 但是 app.py 不是被 import 的，而是被 Streamlit 在執行時「讀檔案再執行」，
# 所以 PyInstaller 看不到 app.py、db.py、models/，要在這裡手動告訴它。

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    # (來源, 放到 exe 裡的哪個資料夾)
    ("app.py", "."),
    ("db.py", "."),
    ("quotes.py", "."),  # 股價自動更新（新增最上層的 .py 檔都要加在這裡）
    # 只打包 .py：整個資料夾會連 __pycache__ 一起帶進去，
    # 裡面的 .pyc 記錄了打包電腦上的絕對路徑（可能含使用者名稱），不該出現在公開的下載檔
    ("models/*.py", "models"),
    # 主題設定：Streamlit 會讀「app.py 旁邊的 .streamlit/config.toml」，
    # 所以放到和 app.py 同一層的 .streamlit 資料夾，exe 版就會套用一樣的配色和字型
    (".streamlit/config.toml", ".streamlit"),
]
binaries = []
hiddenimports = []

# Streamlit 有很多網頁前端檔案（HTML、JS）和套件資訊，collect_all 會全部收進來。
# （pyarrow 也是必要的，但 PyInstaller 內建的設定就會處理，用 collect_all 會多出 100 多 MB）
for package in ["streamlit", "altair"]:
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# app.py 用到、但 PyInstaller 從 run_app.py 找不到的模組
hiddenimports += ["pandas", "sqlite3", "urllib.request"] + collect_submodules("models")

a = Analysis(
    ["run_app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # 測試工具不用打包進去，可以讓檔案小一點
    excludes=["pytest", "tkinter", "pydeck"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FinanceApp",
    # console=False：不要黑色視窗。畫面由 run_app.py 用 pywebview 開的視窗顯示，
    # 關掉那個視窗，程式（包括背景的伺服器）就會結束。
    console=False,
    icon="installer/icon.ico",  # exe 和捷徑上顯示的圖示（安裝程式也用同一個）
)

# onedir 模式：輸出一個資料夾，啟動比單一 exe 快很多（不用每次解壓 100 多 MB）
coll = COLLECT(exe, a.binaries, a.datas, name="FinanceApp")
