#!/bin/bash
# ============================================
# macOS / Linux 打包腳本
# 使用方式：在終端機輸入  bash build_mac.sh
# 結果：dist/FinanceApp/FinanceApp
# ============================================

# 任何一步失敗就停下來
set -e

# 切換到這個腳本所在的資料夾
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "[1/3] 建立虛擬環境..."
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "[2/3] 安裝套件（第一次會比較久）..."
python -m pip install -r requirements-build.txt

echo "[3/3] 打包中，大約需要 1 到 3 分鐘..."
pyinstaller --noconfirm FinanceApp.spec

# build/ 只是暫存檔，裡面的 FinanceApp 不能用，刪掉避免點錯
rm -rf build

echo
echo "完成！程式在 dist/FinanceApp/FinanceApp ，在 Finder 裡點兩下就能啟動。"
