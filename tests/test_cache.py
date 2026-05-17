"""
テスト: src/utils/cache.py
- ローカルバックエンド（デフォルト）
- GCS バックエンド（モック使用）
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.cache import Cache, _LocalBackend, _GCSBackend, _check_ttl, _make_payload


# ============================================================
# ヘルパー関数テスト
# ============================================================

def test_make_payload_has_saved_at_and_data():
    payload = json.loads(_make_payload({"x": 1}))
    assert "saved_at" in payload
    assert payload["data"] == {"x": 1}


def test_check_ttl_within_expiry_returns_data():
    entry = {"saved_at": datetime.now().isoformat(), "data": [1, 2, 3]}
    result = _check_ttl(entry, ttl_hours=1)
    assert result == [1, 2, 3]


def test_check_ttl_expired_returns_none():
    old = (datetime.now() - timedelta(hours=2)).isoformat()
    entry = {"saved_at": old, "data": "stale"}
    assert _check_ttl(entry, ttl_hours=1) is None


# ============================================================
# ローカルバックエンドテスト
# ============================================================

class TestLocalBackend:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.backend = _LocalBackend(self.tmpdir)

    def test_get_missing_key_returns_none(self):
        assert self.backend.get("no_such_key", ttl_hours=1) is None

    def test_set_and_get_roundtrip(self):
        self.backend.set("foo", {"a": 1})
        result = self.backend.get("foo", ttl_hours=1)
        assert result == {"a": 1}

    def test_get_expired_returns_none(self):
        # 保存後に TTL 0 で取得 → None
        self.backend.set("bar", "value")
        assert self.backend.get("bar", ttl_hours=0) is None

    def test_invalidate_removes_file(self):
        self.backend.set("baz", 42)
        self.backend.invalidate("baz")
        assert self.backend.get("baz", ttl_hours=1) is None

    def test_invalidate_nonexistent_key_no_error(self):
        self.backend.invalidate("ghost")  # エラーなし


# ============================================================
# Cache クラス（ローカルモード）
# ============================================================

class TestCacheLocal:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # GCS_CACHE_BUCKET 未設定でローカルバックエンド使用
        os.environ.pop("GCS_CACHE_BUCKET", None)
        self.cache = Cache(cache_dir=self.tmpdir)

    def test_uses_local_backend(self):
        from src.utils.cache import _LocalBackend
        assert isinstance(self.cache._backend, _LocalBackend)

    def test_set_get_invalidate(self):
        self.cache.set("key1", [1, 2, 3])
        assert self.cache.get("key1", ttl_hours=1) == [1, 2, 3]
        self.cache.invalidate("key1")
        assert self.cache.get("key1", ttl_hours=1) is None


# ============================================================
# GCS バックエンドテスト（モック）
# ============================================================

class TestGCSBackend:
    def _make_backend(self, stored: dict):
        """stored: {key: json_string} のモックバケットを持つ _GCSBackend を返す"""
        mock_bucket = MagicMock()

        def make_blob(path):
            blob = MagicMock()
            key = path.split("/")[-1].replace(".json", "")

            # download_as_text
            if key in stored:
                blob.download_as_text.return_value = stored[key]
            else:
                from google.cloud.exceptions import NotFound
                blob.download_as_text.side_effect = NotFound("blob not found")

            # upload_from_string: ストアに保存
            def upload(payload, content_type=None):
                stored[key] = payload
            blob.upload_from_string.side_effect = upload

            # delete
            def delete():
                stored.pop(key, None)
            blob.delete.side_effect = delete

            return blob

        mock_bucket.blob.side_effect = make_blob

        with patch("google.cloud.storage.Client") as mock_client:
            mock_client.return_value.bucket.return_value = mock_bucket
            backend = _GCSBackend("test-bucket", "cache")
        return backend, stored

    def test_get_missing_key_returns_none(self):
        backend, _ = self._make_backend({})
        assert backend.get("missing", ttl_hours=1) is None

    def test_set_and_get_roundtrip(self):
        backend, stored = self._make_backend({})
        backend.set("mykey", {"val": 99})
        result = backend.get("mykey", ttl_hours=1)
        assert result == {"val": 99}

    def test_get_expired_returns_none(self):
        old_payload = json.dumps({
            "saved_at": (datetime.now() - timedelta(hours=2)).isoformat(),
            "data": "stale",
        })
        backend, _ = self._make_backend({"expiredkey": old_payload})
        assert backend.get("expiredkey", ttl_hours=1) is None

    def test_invalidate_removes_blob(self):
        payload = json.dumps({"saved_at": datetime.now().isoformat(), "data": "x"})
        backend, stored = self._make_backend({"delkey": payload})
        backend.invalidate("delkey")
        assert "delkey" not in stored

    def test_invalidate_nonexistent_no_error(self):
        backend, _ = self._make_backend({})
        backend.invalidate("ghost")  # エラーなし


# ============================================================
# Cache クラス（GCS モード）
# ============================================================

class TestCacheGCS:
    def setup_method(self):
        os.environ["GCS_CACHE_BUCKET"] = "test-bucket"

    def teardown_method(self):
        os.environ.pop("GCS_CACHE_BUCKET", None)

    def test_uses_gcs_backend_when_env_set(self):
        with patch("google.cloud.storage.Client") as mock_client:
            mock_client.return_value.bucket.return_value = MagicMock()
            cache = Cache(cache_dir="cache")
        assert isinstance(cache._backend, _GCSBackend)

    def test_set_get_via_gcs(self):
        stored = {}
        mock_bucket = MagicMock()

        def make_blob(path):
            blob = MagicMock()
            key = path.split("/")[-1].replace(".json", "")

            def download():
                if key not in stored:
                    raise Exception("not found")
                return stored[key]
            blob.download_as_text.side_effect = download

            def upload(payload, content_type=None):
                stored[key] = payload
            blob.upload_from_string.side_effect = upload
            return blob

        mock_bucket.blob.side_effect = make_blob

        with patch("google.cloud.storage.Client") as mock_client:
            mock_client.return_value.bucket.return_value = mock_bucket
            cache = Cache(cache_dir="cache")

        cache.set("k", {"hello": "world"})
        assert cache.get("k", ttl_hours=1) == {"hello": "world"}
