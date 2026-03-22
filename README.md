# Claude Code Token Reader

Claude Codeのトークン使用量をリアルタイムで可視化するCLIツール + macOSメニューバー表示。

## 機能

- **リアルタイムモニター** — 5時間ウィンドウと週間使用量を3秒ごと自動更新
- **メニューバー表示** — macOSのメニューバーにトークン使用率を常時表示（SwiftBar）
- **日別/月別/セッション別レポート** — 過去の使用量を集計
- **5時間ウィンドウ時刻表** — 契約開始日に基づく正確なウィンドウ表示
- **プラン対応** — Free / Pro / Max 5x / Max 20x の各プランに対応
- **初期設定ウィザード** — 初回実行時に対話式で設定

## 必要環境

- **macOS**（メニューバー表示を使う場合）
- **Python 3.8+**（macOS標準搭載）
- **Claude Code** がインストール済みで、ログが `~/.claude/projects/` に存在すること

## セットアップ

### 方法1: セットアップスクリプト（推奨）

```bash
# 1. ダウンロード・展開後、フォルダに移動
cd ~/Desktop/dev/Token_Reader   # ← 実際の配置場所に変更

# 2. セットアップ実行（richインストール + 初期設定 + SwiftBar）
bash setup.sh
```

### 方法2: 手動セットアップ

```bash
# 1. rich ライブラリをインストール
pip3 install rich

# 2. 初期設定（対話式ウィザードが起動します）
python3 token_reader.py monitor
```

## 初期設定

初回実行時に以下の情報を入力します。
**claude.ai → 設定** を開いて確認してください。

| ステップ | 入力内容 | 確認場所 |
|---------|---------|---------|
| 1. プラン | Free / Pro / Max 5x / Max 20x | 設定 → 請求 |
| 2. 契約開始日 | 有料プラン開始日（例: 2026-03-05） | 設定 → 請求 → 請求書の日付 |
| 3. 5hリセット時刻 | 次のリセット時刻（例: 17:00） | 設定 → 使用量 → 「○時間○分後にリセット」 |
| 4. 週間リセット | 曜日と時刻（例: 木 17:00） | 設定 → 使用量 → 「○:○○ (曜日)にリセット」 |

ステップ3・4はEnterでスキップ可能（契約日から自動計算）。

設定は `~/.config/token_reader/config.json` に保存され、2回目以降は不要です。

## 使い方

### リアルタイムモニター
```bash
python3 token_reader.py monitor
```
5時間ウィンドウと週間の使用量をリアルタイム表示。3秒ごと自動更新。`Ctrl+C` で終了。

### 日別レポート
```bash
python3 token_reader.py                    # デフォルト
python3 token_reader.py daily              # 同上
python3 token_reader.py daily --breakdown  # モデル別内訳付き
```

### 月別レポート
```bash
python3 token_reader.py monthly
```

### セッション別
```bash
python3 token_reader.py session
```

### 5時間ウィンドウ別
```bash
python3 token_reader.py blocks
```

### プラン比較 & 時刻表
```bash
python3 token_reader.py plans
```

### オプション
```bash
--since 20260301          # 開始日フィルタ
--until 20260331          # 終了日フィルタ
--project OZ              # プロジェクト名フィルタ
--json                    # JSON出力
--plan pro|max5|max20     # プラン指定
```

## メニューバー表示（SwiftBar）

セットアップスクリプトで自動インストールされます。手動の場合：

```bash
# 1. SwiftBar インストール
brew install --cask swiftbar

# 2. プラグイン配置
mkdir -p ~/Library/Application\ Support/SwiftBar/plugins
cp claude-usage.30s.py ~/Library/Application\ Support/SwiftBar/plugins/
chmod +x ~/Library/Application\ Support/SwiftBar/plugins/claude-usage.30s.py

# 3. SwiftBar 起動
open -a SwiftBar
# → 「Choose plugin folder」で以下を指定（Cmd+Shift+G）:
#    ~/Library/Application Support/SwiftBar/plugins
```

### メニューバーの表示

```
☁ 42% | 3%
  ↑        ↑
  5hウィンドウ  週間使用率
```

クリックで詳細表示。色は使用率に応じて変化（緑→白→黄→赤）。

## 設定の変更・リセット

```bash
# 設定をリセットして再設定
rm -f ~/.config/token_reader/config.json
python3 token_reader.py monitor

# 個別に変更
python3 token_reader.py init --plan max5 --start 2026-01-15
```

## ファイル構成

```
Token_Reader/
├── token_reader.py         # メインCLIツール
├── claude-usage.30s.py     # SwiftBar メニューバープラグイン
├── setup.sh                # セットアップスクリプト
├── requirements.txt        # Python依存パッケージ
└── README.md               # このファイル
```

## プラン別トークン上限

| プラン | 月額 | 5hウィンドウ | 週間上限 |
|--------|------|-------------|---------|
| Free | $0 | 制限あり | 制限あり |
| Pro | $20 | 45,000,000 | 1,530,000,000 |
| Max 5x | $100 | 135,000,000 | 4,590,000,000 |
| Max 20x | $200 | 540,000,000 | 18,360,000,000 |
