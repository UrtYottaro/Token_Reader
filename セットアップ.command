#!/bin/bash
cd "$(dirname "$0")"
# Gatekeeperのquarantine属性を自動削除（次回以降の警告を防止）
xattr -cr "$(dirname "$0")" 2>/dev/null
bash setup.sh
echo ""
echo "ウィンドウを閉じるには何かキーを押してください..."
read -n 1
