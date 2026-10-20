@echo off
REM ============================================================
REM Windows build script: double-click this file in finance-app.
REM Output: dist\FinanceApp\                         (the program files)
REM         dist\installer\FinanceApp-Setup-x.y.z.exe  (the installer,
REM         only if Inno Setup 6.5 or newer is installed)
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
    echo [1/4] Creating virtual environment...
    python -m venv .venv || goto :error
)

call .venv\Scripts\activate.bat || goto :error

echo [2/4] Installing packages (slow the first time)...
python -m pip install -r requirements.txt || goto :error

REM We do NOT use PyInstaller on Windows: its unsigned FinanceApp.exe gets
REM deleted by some antivirus software (e.g. Trend Micro). Instead we ship the
REM official, signed embeddable Python plus our source code.
REM See installer\build_runtime.py for details.
echo [3/4] Preparing dist\FinanceApp (official Python + packages + app)...
python installer\build_runtime.py || goto :error

echo [4/4] Building the installer...
REM Look for the Inno Setup compiler (ISCC.exe) in the usual install folders.
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if not defined ISCC goto :no_inno

"%ISCC%" installer\FinanceApp.iss || goto :error

echo.
echo Done! The installer is in dist\installer
echo Double-click FinanceApp-Setup-*.exe to install. Your data is NOT inside it.
echo Opening that folder for you now...
explorer "dist\installer"
pause
exit /b 0

:no_inno
REM Inno Setup is optional: without it we still have a working exe.
echo.
echo Inno Setup was not found, so only dist\FinanceApp was prepared (no installer).
echo To also build the installer, install Inno Setup 6.5 or newer:
echo     winget install JRSoftware.InnoSetup
echo   or download it from https://jrsoftware.org/isdl.php
echo Then run this file again.
echo.
echo To run it without installing: dist\FinanceApp\python\pythonw.exe dist\FinanceApp\app\run_app.py
explorer "dist\FinanceApp"
pause
exit /b 0

:error
echo.
echo Build FAILED. Please copy the error message above and send it to Claude.
pause
exit /b 1
