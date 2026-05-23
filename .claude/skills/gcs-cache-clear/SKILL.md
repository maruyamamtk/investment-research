---
name: gcs-cache-clear
description: GCSキャッシュの特定キーまたは全件を削除してフレッシュ再取得を強制する。引数例: stage1 / stage2 / watchlist / prime_stock_list / all
disable-model-invocation: true
---

プロジェクト: keiba-prediction-1768734113
バケット: gs://keiba-prediction-1768734113-investment-cache/cache/

## 引数が "all" の場合
```bash
gsutil -m rm -r gs://keiba-prediction-1768734113-investment-cache/cache/
echo "✅ GCSキャッシュ全件削除完了"
```

## 引数が特定キー（例: stage1, stage2, watchlist, prime_stock_list）の場合
```bash
gsutil rm gs://keiba-prediction-1768734113-investment-cache/cache/{引数}.json 2>/dev/null && \
  echo "✅ 削除完了: {引数}.json" || echo "⚠️ 対象なし（既に存在しないか、キー名が違う可能性があります）"
```

## キャッシュ一覧確認（引数が "list" の場合）
```bash
gsutil ls gs://keiba-prediction-1768734113-investment-cache/cache/
```

削除後は次回パイプライン実行時にGCSへ新規保存されます。
ローカルキャッシュ（cache/*.json）は別途削除が必要な場合は教えてください。
