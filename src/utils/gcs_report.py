"""GCS へのレポートファイルアップロードユーティリティ。

GCS_CACHE_BUCKET 環境変数が設定されている場合のみ動作し、
未設定（ローカル実行）の場合はスキップする。
"""
import logging
import os

_logger = logging.getLogger(__name__)


def upload_report_to_gcs(local_path: str, logger=None) -> bool:
    """ローカルのレポートファイルを GCS の reports/ 配下にアップロードする。

    Args:
        local_path: アップロード対象のローカルファイルパス
        logger: ログ出力先（省略時はモジュールロガーを使用）

    Returns:
        アップロード成功時 True、スキップ・失敗時 False
    """
    bucket_name = os.environ.get("GCS_CACHE_BUCKET")
    if not bucket_name:
        return False

    log = logger or _logger
    filename = os.path.basename(local_path)
    blob_name = f"reports/{filename}"

    try:
        from google.cloud import storage  # 遅延インポート（ローカル環境で不要）
        blob = storage.Client().bucket(bucket_name).blob(blob_name)
        blob.upload_from_filename(local_path)
        log.info(f"GCSに出力: gs://{bucket_name}/{blob_name}")
        return True
    except Exception as e:
        log.error(f"GCSアップロード失敗 ({local_path}): {e}")
        return False
