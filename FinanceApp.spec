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
    ("models", "models"),
    # 主題配色設定。exe 啟動時 run_app.py 會切換到這個設定所在的資料夾，Streamlit 才讀得到
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
hiddenimports += ["pandas", "sqlite3"] + collect_submodules("models")

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
