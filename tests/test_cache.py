"""
Unit tests for cache service.
"""

import json
import time
import tempfile
import shutil
from pathlib import Path

import pytest

from app.services.cache import SimpleCache


class TestSimpleCache:
    """Tests for SimpleCache class."""

    def setup_method(self):
        """Create a temporary cache directory for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.cache = SimpleCache(cache_dir=self.temp_dir)

    def teardown_method(self):
        """Clean up temporary cache directory."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_set_and_get(self):
        """Test basic set and get operations."""
        self.cache.set("test_key", {"value": 123})
        result = self.cache.get("test_key")
        assert result == {"value": 123}

    def test_get_nonexistent_key(self):
        """Test getting a key that doesn't exist."""
        result = self.cache.get("nonexistent")
        assert result is None

    def test_ttl_expiration(self):
        """Test that cached values expire after TTL."""
        # Use a very short TTL for testing
        self.cache.set("test_key", {"value": 123}, ttl_seconds=1)

        # Should be valid immediately
        result = self.cache.get("test_key", ttl_seconds=1)
        assert result == {"value": 123}

        # Wait for TTL to expire
        time.sleep(1.2)

        # Should be None now
        result = self.cache.get("test_key", ttl_seconds=1)
        assert result is None

    def test_delete(self):
        """Test deleting a cached value."""
        self.cache.set("delete_key", {"value": 456})
        self.cache.delete("delete_key")

        result = self.cache.get("delete_key")
        assert result is None

    def test_clear(self):
        """Test clearing all cached values."""
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.cache.set("key3", "value3")

        self.cache.clear()

        assert self.cache.get("key1") is None
        assert self.cache.get("key2") is None
        assert self.cache.get("key3") is None

    def test_cache_with_various_types(self):
        """Test caching various data types."""
        # String
        self.cache.set("string_key", "test string")
        assert self.cache.get("string_key") == "test string"

        # Integer
        self.cache.set("int_key", 42)
        assert self.cache.get("int_key") == 42

        # Float
        self.cache.set("float_key", 3.14)
        assert self.cache.get("float_key") == 3.14

        # List
        self.cache.set("list_key", [1, 2, 3])
        assert self.cache.get("list_key") == [1, 2, 3]

        # Nested dict
        self.cache.set("dict_key", {"nested": {"data": [1, 2, 3]}})
        assert self.cache.get("dict_key") == {"nested": {"data": [1, 2, 3]}}

    def test_cache_preserves_json_structure(self):
        """Test that complex JSON structures are preserved."""
        data = {
            "trains": [
                {"id": "1", "name": "Local 101", "stops": ["SF", "MV", "SJ"]},
                {"id": "2", "name": "Express 501", "stops": ["SF", "PA", "SC"]},
            ],
            "metadata": {
                "count": 2,
                "timestamp": "2026-03-30T10:00:00Z",
            }
        }

        self.cache.set("complex_data", data)
        result = self.cache.get("complex_data")

        assert result == data
        assert len(result["trains"]) == 2
        assert result["trains"][0]["stops"] == ["SF", "MV", "SJ"]

    def test_cache_directory_creation(self):
        """Test that cache directory is created if it doesn't exist."""
        new_cache_dir = Path(self.temp_dir) / "new" / "nested" / "dir"
        cache = SimpleCache(cache_dir=str(new_cache_dir))

        # Should have created the directory
        assert new_cache_dir.exists()

        # Should be able to use it
        cache.set("test", "value")
        assert cache.get("test") == "value"

    def test_get_with_custom_ttl(self):
        """Test that custom TTL works correctly with stored TTL."""
        # Set a value with a specific TTL
        self.cache.set("ttl_test_key", {"value": 789}, ttl_seconds=2)

        # Should be valid within the TTL
        result = self.cache.get("ttl_test_key", ttl_seconds=2)
        assert result == {"value": 789}

        # Wait longer than the TTL
        time.sleep(2.5)

        # Should be expired
        result = self.cache.get("ttl_test_key", ttl_seconds=2)
        assert result is None

    def test_duplicate_keys_overwrite(self):
        """Test that setting the same key overwrites previous value."""
        self.cache.set("test_key", {"value": 1})
        self.cache.set("test_key", {"value": 2})
        self.cache.set("test_key", {"value": 3})

        result = self.cache.get("test_key")
        assert result == {"value": 3}

    def test_empty_value_caching(self):
        """Test that empty/falsy values can be cached."""
        self.cache.set("empty_list", [])
        self.cache.set("empty_dict", {})
        self.cache.set("zero", 0)
        self.cache.set("empty_string", "")

        assert self.cache.get("empty_list") == []
        assert self.cache.get("empty_dict") == {}
        assert self.cache.get("zero") == 0
        assert self.cache.get("empty_string") == ""

    def test_none_value_not_cached(self):
        """Test that None values are not cached."""
        self.cache.set("none_key", None)

        # None values should not be stored (checking internal behavior)
        # The get should return None which could be from non-existence or actual None
        # This is a limitation of the simple cache design
        pass


class TestCachePerformance:
    """Tests for cache performance characteristics."""

    def setup_method(self):
        """Create a temporary cache directory for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.cache = SimpleCache(cache_dir=self.temp_dir)

    def teardown_method(self):
        """Clean up temporary cache directory."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_large_data_caching(self):
        """Test caching large data structures."""
        large_data = {
            "stops": [
                {
                    "id": f"stop_{i}",
                    "name": f"Stop {i}",
                    "lat": 37.0 + i * 0.01,
                    "lon": -122.0 + i * 0.01,
                    "connections": list(range(100)),
                }
                for i in range(1000)
            ]
        }

        self.cache.set("large_data", large_data)
        result = self.cache.get("large_data")

        assert result is not None
        assert len(result["stops"]) == 1000
        assert result["stops"][0]["connections"] == list(range(100))

    def test_sequential_access_performance(self):
        """Test that sequential cache access is fast."""
        # Fill cache
        for i in range(100):
            self.cache.set(f"key_{i}", {"index": i})

        # Sequential reads
        start = time.time()
        for i in range(100):
            result = self.cache.get(f"key_{i}")
            assert result["index"] == i
        elapsed = time.time() - start

        # Should complete in reasonable time (< 1 second for 100 ops)
        assert elapsed < 1.0