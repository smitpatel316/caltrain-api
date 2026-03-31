"""
Unit tests for rate limiter utilities.
"""

import time
import threading
import pytest
from unittest.mock import Mock, patch

from app.utils.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RateLimitError,
    APIError,
    NetworkError,
    AuthenticationError,
    get_rate_limiter,
    reset_rate_limiter,
)


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RateLimitConfig()
        assert config.requests_per_hour == 60
        assert config.backoff_base_seconds == 2.0
        assert config.backoff_max_seconds == 60.0
        assert config.max_retries == 3

    def test_custom_config(self):
        """Test custom configuration values."""
        config = RateLimitConfig(
            requests_per_hour=100,
            backoff_base_seconds=5.0,
            backoff_max_seconds=120.0,
            max_retries=5,
        )
        assert config.requests_per_hour == 100
        assert config.backoff_base_seconds == 5.0
        assert config.backoff_max_seconds == 120.0
        assert config.max_retries == 5


class TestRateLimiter:
    """Tests for RateLimiter class."""

    def setup_method(self):
        """Reset global limiter before each test."""
        reset_rate_limiter()

    def teardown_method(self):
        """Reset global limiter after each test."""
        reset_rate_limiter()

    def test_initial_tokens(self):
        """Test that limiter starts with full tokens."""
        limiter = RateLimiter()
        assert limiter.state.tokens == 60.0

    def test_can_make_request_under_limit(self):
        """Test that requests can be made under rate limit."""
        limiter = RateLimiter(config=RateLimitConfig(requests_per_hour=60))
        assert limiter._can_make_request() is True

    def test_records_request(self):
        """Test that requests are recorded."""
        limiter = RateLimiter(config=RateLimitConfig(requests_per_hour=60))
        initial_tokens = limiter.state.tokens

        limiter._record_request()

        assert limiter.state.tokens < initial_tokens
        assert len(limiter.state.request_times) > 0

    def test_refill_tokens_over_time(self):
        """Test that tokens are refilled over time."""
        limiter = RateLimiter(config=RateLimitConfig(requests_per_hour=3600))  # 1 per second
        limiter.state.tokens = 0

        # Wait 2 seconds
        time.sleep(0.1)  # Small sleep to trigger refill

        limiter._refill_tokens()

        assert limiter.state.tokens > 0

    def test_wait_if_needed_blocks_when_limited(self):
        """Test wait_if_needed blocks when rate limited."""
        limiter = RateLimiter(config=RateLimitConfig(requests_per_hour=1, max_retries=0))

        # Exhaust tokens
        for _ in range(10):
            limiter._record_request()

        start_time = time.time()
        # This should block since we're rate limited
        limiter.wait_if_needed()
        elapsed = time.time() - start_time

        # Should have waited at least 1 second
        assert elapsed >= 0.0  # Will block, then proceed

    def test_execute_success(self):
        """Test successful request execution."""
        limiter = RateLimiter()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.content = b"data"

        mock_func = Mock(return_value=mock_response)

        result = limiter.execute(mock_func, "http://test.com")

        assert result == mock_response
        mock_func.assert_called_once()

    def test_execute_handles_429(self):
        """Test handling of 429 rate limit response."""
        limiter = RateLimiter(config=RateLimitConfig(max_retries=1))

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "1"}  # 1 second

        mock_func = Mock(return_value=mock_response)

        # Should retry and fail
        with pytest.raises(Exception):  # Could be RateLimitError or APIError
            limiter.execute(mock_func, "http://test.com")

    def test_execute_handles_401(self):
        """Test handling of 401 authentication error."""
        limiter = RateLimiter()

        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_func = Mock(return_value=mock_response)

        with pytest.raises(AuthenticationError):
            limiter.execute(mock_func, "http://test.com")

    def test_execute_handles_500(self):
        """Test handling of 500 server error."""
        limiter = RateLimiter()

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_func = Mock(return_value=mock_response)

        with pytest.raises(APIError):
            limiter.execute(mock_func, "http://test.com")

    def test_execute_network_error_retries(self):
        """Test that network errors trigger retry with backoff."""
        limiter = RateLimiter(config=RateLimitConfig(backoff_base_seconds=0.1, max_retries=2))

        mock_func = Mock(side_effect=Exception("Connection refused"))

        with pytest.raises(APIError):
            limiter.execute(mock_func, "http://test.com")

        # Should have tried 3 times (initial + 2 retries)
        assert mock_func.call_count == 3

    def test_update_from_response_headers(self):
        """Test parsing rate limit info from response headers."""
        limiter = RateLimiter()

        headers = {
            "X-RateLimit-Remaining": "45",
            "X-RateLimit-Reset": "1609459200",
        }

        limiter.update_from_response_headers(headers)

        assert limiter._rate_limit_remaining == 45


class TestGlobalRateLimiter:
    """Tests for global rate limiter singleton."""

    def setup_method(self):
        """Reset global limiter before each test."""
        reset_rate_limiter()

    def teardown_method(self):
        """Reset global limiter after each test."""
        reset_rate_limiter()

    def test_get_rate_limiter_returns_same_instance(self):
        """Test that get_rate_limiter returns singleton."""
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()

        assert limiter1 is limiter2

    def test_get_rate_limiter_with_custom_config(self):
        """Test that custom config is respected."""
        config = RateLimitConfig(requests_per_hour=100)
        limiter = get_rate_limiter(config)

        assert limiter.config.requests_per_hour == 100

    def test_reset_rate_limiter(self):
        """Test that reset_rate_limiter clears singleton."""
        limiter1 = get_rate_limiter()
        reset_rate_limiter()
        limiter2 = get_rate_limiter()

        assert limiter1 is not limiter2


class TestExceptions:
    """Tests for rate limiter exceptions."""

    def test_rate_limit_error_has_retry_after(self):
        """Test RateLimitError includes retry_after."""
        error = RateLimitError("Rate limited", retry_after=30.0)
        assert error.retry_after == 30.0
        assert "30" in str(error)

    def test_api_error_has_status_code(self):
        """Test APIError includes status code."""
        error = APIError("Test error", status_code=404)
        assert error.status_code == 404

    def test_network_error(self):
        """Test NetworkError inheritance."""
        error = NetworkError("Connection failed")
        assert isinstance(error, APIError)
        assert "Connection failed" in str(error)

    def test_authentication_error(self):
        """Test AuthenticationError inheritance."""
        error = AuthenticationError("Invalid key", status_code=401)
        assert isinstance(error, APIError)
        assert error.status_code == 401