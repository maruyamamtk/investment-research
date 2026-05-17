import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

_logger = logging.getLogger(__name__)


class Cache:
    """JSONキャッシュ。GCS_CACHE_BUCKET 環境変数が設定されていれば GCS を使用し、
    未設定の場合はローカルファイルにフォールバックする。"""

    def __init__(self, cache_dir: str = "cache"):
        bucket = os.environ.get("GCS_CACHE_BUCKET")
        if bucket:
            self._backend: _Backend = _GCSBackend(bucket, cache_dir)
        else:
            os.makedirs(cache_dir, exist_ok=True)
            self._backend = _LocalBackend(cache_dir)

    def get(self, key: str, ttl_hours: float = 168) -> Optional[Any]:
        return self._backend.get(key, ttl_hours)

    def set(self, key: str, data: Any) -> None:
        self._backend.set(key, data)

    def invalidate(self, key: str) -> None:
        self._backend.invalidate(key)


# ── バックエンド基底 ───────────────────────────────────────

class _Backend:
    def get(self, key: str, ttl_hours: float) -> Optional[Any]:
        raise NotImplementedError

    def set(self, key: str, data: Any) -> None:
        raise NotImplementedError

    def invalidate(self, key: str) -> None:
        raise NotImplementedError


def _check_ttl(entry: dict, ttl_hours: float) -> Optional[Any]:
    saved_at = datetime.fromisoformat(entry["saved_at"])
    if datetime.now() - saved_at > timedelta(hours=ttl_hours):
        return None
    return entry["data"]


def _make_payload(data: Any) -> str:
    return json.dumps(
        {"saved_at": datetime.now().isoformat(), "data": data},
        ensure_ascii=False,
        indent=2,
    )


# ── ローカルファイルバックエンド ──────────────────────────

class _LocalBackend(_Backend):
    def __init__(self, cache_dir: str):
        self._dir = cache_dir

    def _path(self, key: str) -> str:
        return os.path.join(self._dir, f"{key}.json")

    def get(self, key: str, ttl_hours: float) -> Optional[Any]:
        path = self._path(key)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        return _check_ttl(entry, ttl_hours)

    def set(self, key: str, data: Any) -> None:
        with open(self._path(key), "w", encoding="utf-8") as f:
            f.write(_make_payload(data))

    def invalidate(self, key: str) -> None:
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)


# ── GCS バックエンド ──────────────────────────────────────

class _GCSBackend(_Backend):
    """Cloud Run など GCS_CACHE_BUCKET が設定された環境で使用する GCS バックエンド。
    インポートは遅延させ、google-cloud-storage が未インストールのローカル環境で
    GCS_CACHE_BUCKET が設定されていない限りエラーにならないようにする。"""

    def __init__(self, bucket_name: str, prefix: str):
        from google.cloud import storage  # 遅延インポート
        self._bucket = storage.Client().bucket(bucket_name)
        self._prefix = prefix

    def _blob(self, key: str):
        return self._bucket.blob(f"{self._prefix}/{key}.json")

    def get(self, key: str, ttl_hours: float) -> Optional[Any]:
        blob = self._blob(key)
        try:
            entry = json.loads(blob.download_as_text())
        except Exception as e:
            from google.cloud.exceptions import NotFound
            if not isinstance(e, NotFound):
                _logger.warning("GCS cache get failed for key=%s: %s", key, e)
            return None
        return _check_ttl(entry, ttl_hours)

    def set(self, key: str, data: Any) -> None:
        self._blob(key).upload_from_string(
            _make_payload(data), content_type="application/json"
        )

    def invalidate(self, key: str) -> None:
        blob = self._blob(key)
        try:
            blob.delete()
        except Exception:
            pass
