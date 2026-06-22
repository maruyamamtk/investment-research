# TODO: J-Quants V2移行（410 Gone 修正）

## 背景
J-Quants V1トークン認証廃止（410 Gone）で週次パイプラインが停止していた問題の修正。

## 実装タスク
- [x] 根本原因の特定（V1認証廃止 → V2 APIキー方式へ移行）
- [x] `JQuantsClient` をAPIキー方式（`x-api-key`）へ刷新
- [x] エンドポイントをV2へ（`/v2/equities/master`, `/v2/fins/summary`）
- [x] V2短縮フィールド名→V1正規名の正規化レイヤー追加
- [x] `credentials.py` に `JQUANTS_API_KEY` マッピング追加
- [x] `settings.yaml` / `settings.yaml.example` に `api_key` 欄追加
- [x] パイプライン2本（weekly / agent_weekly）をAPIキー優先に変更
- [x] `DEPLOY_GUIDE.md` / `deploy_cloud_run.sh` のシークレットをapi-keyへ更新

## 検証
- [x] V2レスポンスをモックした単体検証（ヘッダー/マスター/財務正規化/ROE）全PASS
- [x] 既存テスト 390件 全PASS（回帰なし）

## レビューセクション
- 変更は認証・エンドポイント・パース層に限定。下流ロジック（スコアリング等）は正規化レイヤーで不変に維持。
- `config/settings.yaml` はgitignore対象のためコミットされない（テンプレート側 `.example` を更新）。

## 残課題（運用側 / ライブAPI確認）
- [ ] J-QuantsダッシュボードでAPIキーを発行し `JQUANTS_API_KEY` を設定
- [ ] 実データ1銘柄で `DocType` プレフィックス（FY/1Q/2Q/3Q）と `code` 仕様を確認
- [ ] Cloud Run: `jquants-api-key` シークレットを登録（旧 jquants-email/password は削除可）
