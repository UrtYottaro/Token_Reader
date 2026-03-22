#!/bin/bash
# Claude Code Token Reader - Uninstall Script

echo ""
echo "======================================"
echo "  Claude Code Token Reader - 削除"
echo "======================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. SwiftBar plugin
PLUGIN="$HOME/Library/Application Support/SwiftBar/plugins/claude-usage.30s.py"
if [ -f "$PLUGIN" ]; then
    rm -f "$PLUGIN"
    echo "[OK] SwiftBar プラグインを削除しました"
else
    echo "[--] SwiftBar プラグインは見つかりませんでした"
fi

# 2. Config
CONFIG_DIR="$HOME/.config/token_reader"
if [ -d "$CONFIG_DIR" ]; then
    rm -rf "$CONFIG_DIR"
    echo "[OK] 設定ファイルを削除しました ($CONFIG_DIR)"
else
    echo "[--] 設定ファイルは見つかりませんでした"
fi

# 3. SwiftBar (optional)
echo ""
read -p "SwiftBar 本体もアンインストールしますか? (y/N): " remove_swiftbar
if [[ "$remove_swiftbar" =~ ^[Yy]$ ]]; then
    osascript -e 'quit app "SwiftBar"' 2>/dev/null
    brew uninstall --cask swiftbar 2>/dev/null && echo "[OK] SwiftBar をアンインストールしました" || echo "[--] SwiftBar は Homebrew で管理されていません"
fi

# 4. Token Reader itself
echo ""
read -p "Token Reader 本体 ($SCRIPT_DIR) も削除しますか? (y/N): " remove_self
if [[ "$remove_self" =~ ^[Yy]$ ]]; then
    rm -rf "$SCRIPT_DIR"
    echo "[OK] Token Reader を削除しました"
fi

echo ""
echo "======================================"
echo "  削除完了"
echo "======================================"
echo ""
