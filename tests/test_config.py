"""
Unit tests for configuration settings.
"""

import os
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.config import Settings, get_settings


class TestSettings:
    """Tests for Settings validation."""

    def test_defaults(self):
        """Test default configuration values."""
        settings = Settings()

        assert settings.five_eleven_api_key == ""
        assert settings.gtfs_refresh_hours == 24
        assert settings.cache_ttl_minutes == 5
        assert settings.debug is False
        assert settings.data_dir == "data"
        assert settings.rate_limit_requests_per_hour == 60
        assert settings.rate_limit_max_retries == 3

    def test_api_key_validation_rejects_short_key(self):
        """Test that short API keys are rejected."""
        with pytest.raises(PydanticValidationError):
            Settings(five_eleven_api_key="short")

    def test_api_key_validation_accepts_valid_key(self):
        """Test that valid API keys are accepted."""
        settings = Settings(five_eleven_api_key="this_is_a_valid_key_12345")
        assert settings.five_eleven_api_key == "this_is_a_valid_key_12345"

    def test_api_key_allows_empty(self):
        """Test that empty API key is allowed (for fallback mode)."""
        settings = Settings(five_eleven_api_key="")
        assert settings.five_eleven_api_key == ""

    def test_gtfs_refresh_hours_range(self):
        """Test GTFS refresh hours must be between 1 and 168."""
        # Valid range
        settings = Settings(gtfs_refresh_hours=12)
        assert settings.gtfs_refresh_hours == 12

        # Too low
        with pytest.raises(PydanticValidationError):
            Settings(gtfs_refresh_hours=0)

        # Too high
        with pytest.raises(PydanticValidationError):
            Settings(gtfs_refresh_hours=200)

    def test_cache_ttl_range(self):
        """Test cache TTL must be between 1 and 60."""
        # Valid range
        settings = Settings(cache_ttl_minutes=30)
        assert settings.cache_ttl_minutes == 30

        # Too low
        with pytest.raises(PydanticValidationError):
            Settings(cache_ttl_minutes=0)

        # Too high
        with pytest.raises(PydanticValidationError):
            Settings(cache_ttl_minutes=120)

    def test_rate_limit_range(self):
        """Test rate limit requests must be between 1 and 1000."""
        # Valid range
        settings = Settings(rate_limit_requests_per_hour=100)
        assert settings.rate_limit_requests_per_hour == 100

        # Too low
        with pytest.raises(PydanticValidationError):
            Settings(rate_limit_requests_per_hour=0)

        # Too high
        with pytest.raises(PydanticValidationError):
            Settings(rate_limit_requests_per_hour=2000)

    def test_server_port_range(self):
        """Test server port must be between 1 and 65535."""
        # Valid range
        settings = Settings(server_port=8080)
        assert settings.server_port == 8080

        # Too low
        with pytest.raises(PydanticValidationError):
            Settings(server_port=0)

        # Too high
        with pytest.raises(PydanticValidationError):
            Settings(server_port=70000)

    def test_validate_returns_warnings_for_missing_api_key(self):
        """Test that validate returns warning when API key is missing."""
        settings = Settings(five_eleven_api_key="")
        warnings = settings.validate()

        assert any("API key" in w for w in warnings)

    def test_validate_returns_warnings_for_debug_mode(self):
        """Test that validate returns warning when debug mode is on."""
        settings = Settings(debug=True)
        warnings = settings.validate()

        assert any("Debug mode" in w for w in warnings)

    def test_validate_returns_empty_for_good_config(self):
        """Test that validate returns empty list for good config."""
        settings = Settings(
            five_eleven_api_key="valid_key_1234567890",
            debug=False,
        )
        # Manually set data_dir to writable for test
        settings.data_dir = tempfile.mkdtemp()

        warnings = settings.validate()
        # Should not have critical warnings
        assert not any("API key" in w for w in warnings)
        assert not any("Debug mode" in w for w in warnings)

    def test_get_data_dir_creates_directory(self):
        """Test that get_data_dir creates directory if needed."""
        temp_dir = tempfile.mkdtemp()
        test_dir = Path(temp_dir) / "test_data" / "nested"

        settings = Settings(data_dir=str(test_dir))
        result = settings.get_data_dir()

        assert result.exists()
        assert result.is_dir()

        # Clean up
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_env_file_loading(self):
        """Test loading settings from .env file."""
        temp_dir = tempfile.mkdtemp()
        env_file = Path(temp_dir) / ".env"

        env_file.write_text("""
FIVE_ELEVEN_API_KEY=test_key_1234567890
DEBUG=true
GTFS_REFRESH_HOURS=12
""")

        settings = Settings(_env_file=str(env_file))

        assert settings.five_eleven_api_key == "test_key_1234567890"
        assert settings.debug is True
        assert settings.gtfs_refresh_hours == 12

        # Clean up
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


class TestGetSettings:
    """Tests for get_settings singleton."""

    def test_returns_same_instance(self):
        """Test that get_settings returns cached instance."""
        # Clear cache first
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2

    def test_cache_clear_works(self):
        """Test that cache_clear forces new instance."""
        get_settings.cache_clear()

        settings1 = get_settings()
        get_settings.cache_clear()
        settings2 = get_settings()

        assert settings1 is not settings2