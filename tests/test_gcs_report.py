"""src/utils/gcs_report.py のテスト"""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.utils.gcs_report import upload_report_to_gcs


@pytest.fixture
def tmp_report(tmp_path):
    """テスト用の一時ファイルを作成する。"""
    f = tmp_path / "test_report.md"
    f.write_text("# test", encoding="utf-8")
    return str(f)


def test_skip_when_no_bucket(tmp_report):
    """GCS_CACHE_BUCKET 未設定時はスキップして False を返す。"""
    env = {k: v for k, v in os.environ.items() if k != "GCS_CACHE_BUCKET"}
    with patch.dict(os.environ, env, clear=True):
        result = upload_report_to_gcs(tmp_report)
    assert result is False


def test_upload_success(tmp_report):
    """GCS_CACHE_BUCKET 設定時に upload_from_filename が呼ばれ True を返す。"""
    mock_blob = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    with patch.dict(os.environ, {"GCS_CACHE_BUCKET": "test-bucket"}):
        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = upload_report_to_gcs(tmp_report)

    assert result is True
    mock_bucket.blob.assert_called_once_with("reports/test_report.md")
    mock_blob.upload_from_filename.assert_called_once_with(tmp_report)


def test_upload_failure_returns_false(tmp_report):
    """アップロード失敗時に False を返す。"""
    mock_blob = MagicMock()
    mock_blob.upload_from_filename.side_effect = Exception("connection error")
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    with patch.dict(os.environ, {"GCS_CACHE_BUCKET": "test-bucket"}):
        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = upload_report_to_gcs(tmp_report)

    assert result is False


def test_upload_logs_success(tmp_report, caplog):
    """アップロード成功時に GCS パスがログに記録される。"""
    mock_blob = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    import logging

    with patch.dict(os.environ, {"GCS_CACHE_BUCKET": "my-bucket"}):
        with patch("google.cloud.storage.Client", return_value=mock_client):
            with caplog.at_level(logging.INFO, logger="src.utils.gcs_report"):
                upload_report_to_gcs(tmp_report)

    assert "gs://my-bucket/reports/test_report.md" in caplog.text


def test_upload_logs_error_on_failure(tmp_report, caplog):
    """アップロード失敗時にエラーがログに記録される。"""
    mock_blob = MagicMock()
    mock_blob.upload_from_filename.side_effect = Exception("timeout")
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    import logging

    with patch.dict(os.environ, {"GCS_CACHE_BUCKET": "my-bucket"}):
        with patch("google.cloud.storage.Client", return_value=mock_client):
            with caplog.at_level(logging.ERROR, logger="src.utils.gcs_report"):
                upload_report_to_gcs(tmp_report)

    assert "GCSアップロード失敗" in caplog.text
