# Lessons

## 2026-06-22 J-Quants V1認証廃止（410 Gone）の対応

### 事象
- 週次パイプラインが `410 Client Error: Gone for url: .../v1/token/auth_user` で異常終了。
- ウォッチリストが更新されず、日次パイプラインがデモ用デフォルト銘柄にフォールバック。
  シグナル（例: 6/15 の 8306.T BUY）がスクリーニングを経ない偶発的なものになっていた。

### 根本原因
- J-Quants が V2 API へ移行し、**V1のトークン認証（email/password→refresh_token→id_token）を廃止**。
- 認証は **APIキー方式（`x-api-key` ヘッダー）** に変更。エンドポイントとフィールド名も変更:
  - `/v1/listed/info`(key:`info`,`MarketCode`) → `/v2/equities/master`(key:`data`,`Mkt`)
  - `/v1/fins/statements`(key:`statements`) → `/v2/fins/summary`(key:`data`)
  - 財務フィールド: `EarningsPerShare/NetSales/Profit/Equity/TypeOfDocument/CurrentPeriodEndDate`
    → `EPS/Sales/NP/Eq/DocType/CurPerEn`

### 対応
- `JQuantsClient` をAPIキー方式へ刷新。V2短縮フィールド名→V1正規名の `_normalize_statement()` を挟み、
  下流ロジック（`get_eps_series` 等）を不変に保った。
- `JQUANTS_API_KEY` 環境変数・`settings.yaml(.example)`・`DEPLOY_GUIDE.md`・`deploy_cloud_run.sh` を更新。
- モック単体検証 + 既存390テストの全PASSで回帰なしを確認。

### 教訓（ルール）
1. **外部API起因の障害は「パイプラインが落ちる」だけでなく「フォールバックで静かに劣化」する**。
   フォールバック発動時は警告だけでなく、シグナルの信頼度を区別できるようにする（将来改善候補）。
2. 外部APIのバージョン移行は「認証・エンドポイント・レスポンスフィールド名」の3点セットで変わり得る。
   1つ直して終わりにせず、レスポンスのパース層まで追う。
3. ベンダーのフィールド名変更は**正規化レイヤー1か所**に閉じ込めると下流改修が最小で済む。

### 残課題（ライブAPIで要確認）
- `DocType` のプレフィックス（年次/四半期判定の `FY/1Q/2Q/3Q`）がV2で同形式か。
- `/v2/fins/summary` の `code` パラメータ仕様（5桁コードのままか）。
