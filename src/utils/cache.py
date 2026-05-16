import json
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class Cache:
    def __init__(self, cache_dir: str = "cache"):
        os.makedirs(cache_dir, exist_ok=True)
        self.cache_dir = cache_dir

    def _path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.json")

    def get(self, key: str, ttl_hours: float = 168) -> Optional[Any]:
        path = self._path(key)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        saved_at = datetime.fromisoformat(entry["saved_at"])
        if datetime.now() - saved_at > timedelta(hours=ttl_hours):
            return None
        return entry["data"]

    def set(self, key: str, data: Any) -> None:
        path = self._path(key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"saved_at": datetime.now().isoformat(), "data": data}, f, ensure_ascii=False, indent=2)

    def invalidate(self, key: str) -> None:
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)
