@echo off
REM ============================================================
REM Windows build script: double-click this file in finance-app.
REM Output: dist\FinanceApp\FinanceApp.exe
REM
REM NOTE: keep this file ASCII-only (English). cmd.exe reads .bat
REM files with the system code page (cp950 on Traditional Chinese
REM Windows), so UTF-8 Chinese text here can break the script.
REM ============================================================

REM Go to the folder this .bat file is in, wherever it was opened from.
cd /d "%~dp0"

REM Make Python read and write files as UTF-8 instead of cp950.
set PYTHONUTF8=1

if not exist .venv\Scripts\activate.bat (
    echo [1/3] Creating virtual environment...
    python -m venv .venv || goto :error
)

call .venv\Scripts\activate.bat || goto :error

echo [2/3] Installing packages (slow the first time)...
python -m pip install -r requirements-build.txt || goto :error

echo [3/3] Building the exe, this takes a few minutes...
pyinstaller --noconfirm FinanceApp.spec || goto :error

echo.
echo Done! The program is at dist\FinanceApp\FinanceApp.exe
pause
exit /b 0

:error
echo.
echo Build FAILED. Please copy the error message above and send it to Claude.
pause
exit /b 1
