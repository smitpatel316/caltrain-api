import os
import json
import time
from typing import Optional, Any
from pathlib import Path


class SimpleCache:
    """Simple disk-based cache with TTL support."""

    def __init__(self, cache_dir: str = "data/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str, ttl_seconds: int = 300) -> Optional[Any]:
        """Get cached value if not expired."""
        path = self._get_path(key)
        if not path.exists():
            return None

        try:
            with open(path, "r") as f:
                data = json.load(f)

            cached_time = data.get("_cached_at", 0)
            if time.time() - cached_time > ttl_seconds:
                return None

            return data.get("value")
        except (json.JSONDecodeError, IOError):
            return None

    def set(self, key: str, value: Any) -> None:
        """Set cached value with current timestamp."""
        path = self._get_path(key)
        data = {"value": value, "_cached_at": time.time()}

        with open(path, "w") as f:
            json.dump(data, f)

    def delete(self, key: str) -> None:
        """Delete cached value."""
        path = self._get_path(key)
        if path.exists():
            path.unlink()

    def clear(self) -> None:
        """Clear all cached values."""
        for path in self.cache_dir.glob("*.json"):
            path.unlink()


# Global cache instance
cache = SimpleCache()
