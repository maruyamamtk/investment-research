---
name: credential-scanner
description: APIキー・パスワードの平文埋め込みをスキャンし、.gitignoreの不備を報告する。デプロイやgit管理開始前に実行する。
---

以下をすべて実行し、発見したリスクを日本語でまとめて報告してください。

## 1. 平文クレデンシャルのスキャン

```bash
grep -rn \
  -e 'api_key\s*[:=]' \
  -e 'password\s*[:=]' \
  -e 'token\s*[:=]' \
  -e 'secret\s*[:=]' \
  --include="*.py" --include="*.yaml" --include="*.yml" --include="*.json" --include="*.sh" \
  /Users/michika_maruyama/Desktop/investment_research \
  --exclude-dir=".git" --exclude-dir="cache" 2>/dev/null
```

## 2. .gitignore の確認

```bash
cat /Users/michika_maruyama/Desktop/investment_research/.gitignore 2>/dev/null || echo ".gitignore が存在しません"
```

以下が除外されているか確認する:
- `config/settings.yaml`（APIキー直書き）
- `config/settings.local.yaml`
- `cache/`（JSONキャッシュ）
- `logs/`
- `.env`

## 3. Git 追跡状態の確認

```bash
cd /Users/michika_maruyama/Desktop/investment_research && git status 2>/dev/null || echo "Git リポジトリではありません"
```

## 報告形式

リスクを以下の3段階で評価して報告する:

- 🔴 **高**: 平文APIキーがgit追跡対象になっている
- 🟡 **中**: .gitignore の除外漏れがある（まだコミットはされていない）
- 🟢 **低**: 問題なし

各リスクに対して具体的な対処手順（.gitignoreへの追記内容など）を提示する。
