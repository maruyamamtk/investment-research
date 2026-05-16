#!/bin/bash
# 初回セットアップスクリプト

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "==================================="
echo " 投資調査自動化システム セットアップ"
echo "==================================="
echo "プロジェクトディレクトリ: $PROJECT_DIR"

cd "$PROJECT_DIR"

# Pythonバージョン確認
echo ""
echo "[1/4] Python環境確認..."
python3 --version || { echo "ERROR: Python3が見つかりません"; exit 1; }

# パッケージインストール
echo ""
echo "[2/4] 依存パッケージのインストール..."
pip3 install -r requirements.txt

# ディレクトリ作成
echo ""
echo "[3/4] ディレクトリ確認..."
mkdir -p cache logs output

# 設定ファイル確認
echo ""
echo "[4/4] 設定ファイル確認..."
if grep -q 'email: ""' config/settings.yaml; then
    echo ""
    echo "======================================================"
    echo " ⚠️  セットアップが必要な項目があります"
    echo "======================================================"
    echo ""
    echo "【必須】config/settings.yaml を編集してAPIキーを設定してください:"
    echo ""
    echo "  J-Quants API（日本株銘柄マスター取得に必要）:"
    echo "    → https://jpx-jquants.com/ でアカウント作成"
    echo "    → api.jquants.email / api.jquants.password を設定"
    echo ""
    echo "  Claude API（AI分析メモ生成に必要・任意）:"
    echo "    → https://console.anthropic.com/ でAPIキー取得"
    echo "    → api.anthropic.api_key を設定"
    echo ""
    echo "  ※ APIキーなしでも --dry-run フラグで動作確認できます"
    echo ""
else
    echo "設定ファイル OK"
fi

echo ""
echo "======================================================"
echo " セットアップ完了！以下のコマンドで動作確認できます:"
echo "======================================================"
echo ""
echo "  # 動作テスト（APIキー不要）"
echo "  python3 pipelines/daily_pipeline.py --ticker 7203.T --dry-run"
echo ""
echo "  # 週次スクリーニング（30銘柄でテスト）"
echo "  python3 pipelines/weekly_pipeline.py --dry-run"
echo ""
echo "  # Cron設定（自動実行）"
echo "  bash scripts/setup_cron.sh"
echo ""
