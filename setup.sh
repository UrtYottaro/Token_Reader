#!/bin/bash
# Claude Code Token Reader - Setup Script
# macOS用セットアップスクリプト

set -e

echo ""
echo "======================================"
echo "  Claude Code Token Reader - Setup"
echo "======================================"
echo ""

# 1. Check Python3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 が見つかりません。"
    echo "  Xcode Command Line Tools をインストールしてください:"
    echo "  xcode-select --install"
    exit 1
fi
echo "[OK] python3 found: $(python3 --version)"

# 2. Install rich
echo ""
echo ">>> pip3 install rich ..."
pip3 install rich --quiet 2>/dev/null || python3 -m pip install rich --quiet
echo "[OK] rich installed"

# 3. Run initial setup wizard
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo ""
echo ">>> 初期設定を開始します..."
echo "  claude.ai → 設定 → 請求/使用量 を参照してください。"
echo ""
python3 "$SCRIPT_DIR/token_reader.py" init

# 4. SwiftBar (optional)
echo ""
echo "======================================"
echo "  メニューバー表示 (オプション)"
echo "======================================"
echo ""
echo "メニューバーにトークン使用率を表示しますか？"
echo "  SwiftBar (無料) をインストールします。"
echo ""
read -p "  インストールする? (y/N): " install_swiftbar

if [[ "$install_swiftbar" =~ ^[Yy]$ ]]; then
    # Check Homebrew
    if ! command -v brew &> /dev/null; then
        echo ""
        echo "[ERROR] Homebrew が見つかりません。"
        echo "  先に Homebrew をインストールしてください:"
        echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        echo ""
        echo "  インストール後、再度このスクリプトを実行してください。"
    else
        echo ""
        echo ">>> SwiftBar をインストール中..."
        brew install --cask swiftbar 2>/dev/null || echo "[INFO] SwiftBar は既にインストール済みです"

        # Setup plugin directory
        PLUGIN_DIR="$HOME/Library/Application Support/SwiftBar/plugins"
        mkdir -p "$PLUGIN_DIR"

        # Copy plugin
        cp "$SCRIPT_DIR/claude-usage.30s.py" "$PLUGIN_DIR/claude-usage.30s.py"
        chmod +x "$PLUGIN_DIR/claude-usage.30s.py"

        echo "[OK] SwiftBar プラグインを配置しました"
        echo ""
        echo ">>> SwiftBar を起動します..."
        open -a SwiftBar

        echo ""
        echo "[INFO] SwiftBar が「Choose plugin folder」を表示した場合:"
        echo "  Cmd+Shift+G を押して以下を入力してください:"
        echo "  ~/Library/Application Support/SwiftBar/plugins"
        echo ""
    fi
fi

# 5. Done
echo ""
echo "======================================"
echo "  セットアップ完了!"
echo "======================================"
echo ""
echo "使い方:"
echo "  cd $SCRIPT_DIR"
echo ""
echo "  python3 token_reader.py                # 日別レポート"
echo "  python3 token_reader.py monitor        # リアルタイムモニター"
echo "  python3 token_reader.py plans          # プラン比較＆時刻表"
echo "  python3 token_reader.py blocks         # 5時間ウィンドウ別"
echo "  python3 token_reader.py session        # セッション別"
echo "  python3 token_reader.py monthly        # 月別"
echo ""
echo "設定のリセット:"
echo "  rm -f ~/.config/token_reader/config.json"
echo "  python3 token_reader.py monitor"
echo ""
