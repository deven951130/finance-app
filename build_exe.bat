@echo off
chcp 65001 >nul
REM ============================================
REM Windows 打包腳本：在 finance-app 資料夾裡點兩下這個檔案
REM 結果：dist\FinanceApp\FinanceApp.exe
REM ============================================

REM 切換到這個 .bat 所在的資料夾（%~dp0），不管從哪裡點開都一樣
cd /d "%~dp0"

REM 第一次執行時建立虛擬環境
if not exist .venv (
    echo [1/3] 建立虛擬環境...
    python -m venv .venv || goto :error
)

call .venv\Scripts\activate.bat || goto :error

echo [2/3] 安裝套件（第一次會比較久）...
python -m pip install -r requirements-build.txt || goto :error

echo [3/3] 打包中，大約需要 1 到 3 分鐘...
pyinstaller --noconfirm FinanceApp.spec || goto :error

echo.
echo 完成！程式在 dist\FinanceApp\FinanceApp.exe
echo 可以把整個 dist\FinanceApp 資料夾搬到任何地方，再對 FinanceApp.exe 按右鍵「傳送到桌面（建立捷徑）」。
pause
exit /b 0

:error
echo.
echo 打包失敗，請把上面的錯誤訊息複製給我。
pause
exit /b 1
