"""
Unit tests for custom exceptions.
"""

import pytest

from app.utils.exceptions import (
    CaltrainAPIError,
    GTFSFetchError,
    GTFSParseError,
    GTRTParseError,
    DatabaseError,
    CacheError,
    ValidationError,
    RateLimitExceededError,
    NetworkUnavailableError,
)


class TestCaltrainAPIError:
    """Tests for base CaltrainAPIError."""

    def test_basic_error(self):
        """Test basic error creation."""
        error = CaltrainAPIError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"
        assert error.details == {}

    def test_error_with_details(self):
        """Test error with details dict."""
        error = CaltrainAPIError("Failed", details={"key": "value"})
        assert error.details == {"key": "value"}


class TestGTFSFetchError:
    """Tests for GTFSFetchError."""

    def test_fetch_error(self):
        """Test GTFS fetch error."""
        error = GTFSFetchError("Failed to download GTFS")
        assert "Failed to download GTFS" in str(error)
        assert isinstance(error, CaltrainAPIError)


class TestGTFSParseError:
    """Tests for GTFSParseError."""

    def test_parse_error(self):
        """Test basic parse error."""
        error = GTFSParseError("Invalid format")
        assert "Invalid format" in str(error)
        assert error.file_name is None
        assert error.line_number is None

    def test_parse_error_with_file(self):
        """Test parse error with file name."""
        error = GTFSParseError("Missing column", file_name="stops.txt")
        assert error.file_name == "stops.txt"

    def test_parse_error_with_line(self):
        """Test parse error with line number."""
        error = GTFSParseError("Invalid value", file_name="stops.txt", line_number=42)
        assert error.file_name == "stops.txt"
        assert error.line_number == 42


class TestGTRTParseError:
    """Tests for GTRTParseError."""

    def test_grt_parse_error(self):
        """Test GTFS-RT parse error."""
        error = GTRTParseError("Invalid protobuf")
        assert "Invalid protobuf" in str(error)
        assert error.entity_id is None

    def test_grt_parse_error_with_entity(self):
        """Test GTFS-RT parse error with entity ID."""
        error = GTRTParseError("Missing trip ID", entity_id="trip-123")
        assert error.entity_id == "trip-123"


class TestDatabaseError:
    """Tests for DatabaseError."""

    def test_database_error(self):
        """Test database error."""
        error = DatabaseError("Connection failed")
        assert "Connection failed" in str(error)
        assert isinstance(error, CaltrainAPIError)


class TestCacheError:
    """Tests for CacheError."""

    def test_cache_error(self):
        """Test cache error."""
        error = CacheError("Cache miss")
        assert "Cache miss" in str(error)
        assert isinstance(error, CaltrainAPIError)


class TestValidationError:
    """Tests for ValidationError."""

    def test_validation_error(self):
        """Test basic validation error."""
        error = ValidationError("Invalid stop ID")
        assert "Invalid stop ID" in str(error)
        assert error.field is None

    def test_validation_error_with_field(self):
        """Test validation error with field name."""
        error = ValidationError("Invalid value", field="origin_stop_id")
        assert error.field == "origin_stop_id"

    def test_validation_error_with_value(self):
        """Test validation error with value."""
        error = ValidationError("Invalid value", field="stop_id", value="unknown")
        assert error.field == "stop_id"
        assert error.value == "unknown"


class TestRateLimitExceededError:
    """Tests for RateLimitExceededError."""

    def test_rate_limit_error_without_retry(self):
        """Test rate limit error without retry info."""
        error = RateLimitExceededError()
        assert error.retry_after is None

    def test_rate_limit_error_with_retry(self):
        """Test rate limit error with retry info."""
        error = RateLimitExceededError(retry_after=60.0)
        assert error.retry_after == 60.0
        # Check the details dict contains the retry_after
        assert error.details.get("retry_after") == 60.0


class TestNetworkUnavailableError:
    """Tests for NetworkUnavailableError."""

    def test_network_error(self):
        """Test network unavailable error."""
        error = NetworkUnavailableError("No internet connection")
        assert "No internet connection" in str(error)
        assert isinstance(error, CaltrainAPIError)