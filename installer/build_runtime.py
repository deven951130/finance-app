"""
準備安裝程式要放的檔案：官方的「嵌入式 Python」+ 套件 + 理財系統的程式碼。

為什麼不用 PyInstaller 的 exe：
PyInstaller 產生的 FinanceApp.exe 沒有數位簽章，有些防毒軟體（例如 Trend Micro）
會把它當成可疑程式直接刪掉：安裝完開始選單有捷徑，但 FinanceApp.exe 不見了，點了沒反應。
python.org 官方的 pythonw.exe 有 Python 軟體基金會的數位簽章，防毒軟體信任它，
所以改成「安裝一份官方的 Python + 我們的程式碼」，捷徑執行 pythonw.exe run_app.py。
（pythonw 是沒有黑色視窗的 python，畫面一樣是 run_app.py 用 pywebview 開的視窗。）

使用方式（在 finance-app 資料夾執行，build_exe.bat 會自動呼叫）：
    python installer/build_runtime.py
結果：dist/FinanceApp/
    python/          官方嵌入式 Python 和所有套件
    app/             app.py、db.py、models/、run_app.py、.streamlit/config.toml
    icon.ico
再用 Inno Setup 把 dist/FinanceApp 包成安裝檔（installer/FinanceApp.iss）。

注意：執行這個腳本的 Python 版本（例如 3.12）會決定安裝檔裡放哪個版本的 Python，
因為 pip 會下載「和目前 Python 相同版本」的套件。
"""

import glob
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # finance-app 資料夾
OUT = os.path.join(ROOT, "dist", "FinanceApp")
CACHE = os.path.join(ROOT, "dist", "cache")

# 每個 Python 版本最後一個有提供「嵌入式版本（embed）」下載的小版本。
# 3.12.10 之後的 3.12.x 只有原始碼，沒有 embed 檔，所以不能直接用目前的小版本號。
EMBED_VERSIONS = {
    (3, 11): "3.11.9",
    (3, 12): "3.12.10",
    (3, 13): "3.13.7",
}

# 理財系統要用到的程式檔。只放 .py，不放 __pycache__（.pyc 裡有打包電腦的路徑，可能含使用者名稱）
APP_FILES = ["app.py", "db.py", "run_app.py", ".streamlit/config.toml"] + \
    [os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "models", "*.py"))]


def download_embed_python() -> str:
    """下載官方嵌入式 Python 的 zip（下載過就用快取），回傳 zip 路徑。"""
    key = sys.version_info[:2]
    if key not in EMBED_VERSIONS:
        raise SystemExit(f"不支援 Python {key[0]}.{key[1]}，請用 3.11 ~ 3.13 執行這個腳本")
    version = EMBED_VERSIONS[key]
    name = f"python-{version}-embed-amd64.zip"
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        url = f"https://www.python.org/ftp/python/{version}/{name}"
        print(f"下載 {url}")
        urllib.request.urlretrieve(url, path + ".part")
        os.replace(path + ".part", path)  # 下載完整才改名，避免中斷時留下壞掉的檔案
    return path


def setup_python(zip_path: str) -> str:
    """解壓縮嵌入式 Python，並設定它要從哪裡找套件和程式。回傳 python 資料夾。"""
    py_dir = os.path.join(OUT, "python")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(py_dir)

    # 嵌入式 Python 用 pythonXY._pth 這個檔案決定 import 的搜尋路徑（類似 C++ 的 include path）。
    # 預設只找它自己的標準函式庫，要加上：套件資料夾、我們的程式資料夾，並打開 import site。
    pth = glob.glob(os.path.join(py_dir, "python*._pth"))[0]
    stdlib_zip = os.path.basename(pth).replace("._pth", ".zip")
    with open(pth, "w", encoding="utf-8") as f:
        f.write(f"{stdlib_zip}\n.\nLib\\site-packages\n..\\app\nimport site\n")
    return py_dir


def install_packages(py_dir: str) -> None:
    """把 requirements-runtime.txt 的套件裝進嵌入式 Python 的 Lib/site-packages。"""
    target = os.path.join(py_dir, "Lib", "site-packages")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "--target", target,
        "--no-compile",   # 不先編譯 .pyc：裡面會記錄打包電腦的路徑；第一次執行時 Python 會自己編譯
        "--disable-pip-version-check",
        "-r", os.path.join(ROOT, "requirements-runtime.txt"),
    ])
    # pip --target 會把套件的指令（streamlit.exe 等）放在 bin/，用不到，刪掉
    shutil.rmtree(os.path.join(target, "bin"), ignore_errors=True)


def copy_app() -> None:
    """複製理財系統的程式檔和圖示。"""
    for rel in APP_FILES:
        dst = os.path.join(OUT, "app", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, rel), dst)
    shutil.copy2(os.path.join(ROOT, "installer", "icon.ico"), os.path.join(OUT, "icon.ico"))


def main() -> None:
    # 每次都從乾淨的資料夾開始，避免留下舊版的檔案（例如舊的 PyInstaller 版）
    shutil.rmtree(OUT, ignore_errors=True)
    py_dir = setup_python(download_embed_python())
    install_packages(py_dir)
    copy_app()
    print(f"完成：{OUT}")


if __name__ == "__main__":
    main()
