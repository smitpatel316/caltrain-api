"""
Rate limiting utilities for 511.org API calls.

Implements a token bucket algorithm with exponential backoff for handling
rate limits and transient errors from the 511.org API.
"""

import time
import threading
import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when rate limit is exceeded and all retries are exhausted."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class APIError(Exception):
    """Base exception for API-related errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class NetworkError(APIError):
    """Raised when network communication fails."""
    pass


class AuthenticationError(APIError):
    """Raised when API key is invalid or missing."""
    pass


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting.

    Attributes:
        requests_per_hour: Maximum requests allowed per hour (default: 60 for 511.org free tier)
        backoff_base_seconds: Base delay for exponential backoff (default: 2 seconds)
        backoff_max_seconds: Maximum delay between retries (default: 60 seconds)
        max_retries: Maximum number of retries after rate limiting (default: 3)
    """

    requests_per_hour: int = 60
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 60.0
    max_retries: int = 3


@dataclass
class RateLimitState:
    """Internal state for rate limit tracking."""

    tokens: float = field(default=60.0)
    last_update: float = field(default_factory=time.time)
    request_times: list[float] = field(default_factory=list)
    consecutive_errors: int = 0


class RateLimiter:
    """Token bucket rate limiter with exponential backoff for 511.org API.

    Thread-safe implementation that tracks request timestamps and enforces
    rate limits using a sliding window algorithm.

    Example:
        limiter = RateLimiter(config=RateLimitConfig(requests_per_hour=60))
        try:
            response = limiter.execute(http_client.get, url)
        except RateLimitError:
            logger.error("Rate limit exceeded after all retries")
    """

    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()
        self.state = RateLimitState(tokens=float(self.config.requests_per_hour))
        self._lock = threading.Lock()
        self._last_rate_limit_time: Optional[float] = None
        self._rate_limit_remaining: Optional[int] = None

    def _refill_tokens(self) -> None:
        """Refill tokens based on elapsed time using token bucket algorithm."""
        now = time.time()
        elapsed = now - self.state.last_update

        # Refill tokens based on requests_per_hour rate
        tokens_to_add = (elapsed / 3600.0) * self.config.requests_per_hour
        self.state.tokens = min(
            self.config.requests_per_hour,
            self.state.tokens + tokens_to_add
        )
        self.state.last_update = now

    def _can_make_request(self) -> bool:
        """Check if a request can be made within rate limits."""
        self._refill_tokens()

        # Check sliding window for recent requests
        now = time.time()
        cutoff = now - 3600  # 1 hour ago

        self.state.request_times = [
            t for t in self.state.request_times if t > cutoff
        ]

        return len(self.state.request_times) < self.config.requests_per_hour

    def _record_request(self) -> None:
        """Record that a request was made."""
        self.state.request_times.append(time.time())
        self.state.tokens = max(0, self.state.tokens - 1)

    def update_from_response_headers(self, headers: dict) -> None:
        """Update rate limit state from API response headers.

        Many APIs return rate limit info in headers like:
        - X-RateLimit-Remaining
        - X-RateLimit-Reset
        - Retry-After
        """
        if "X-RateLimit-Remaining" in headers:
            try:
                self._rate_limit_remaining = int(headers["X-RateLimit-Remaining"])
            except ValueError:
                pass

    def wait_if_needed(self) -> None:
        """Block if rate limit would be exceeded by making a request."""
        while not self._can_make_request():
            sleep_time = 1.0  # Check every second
            logger.debug(f"Rate limit: waiting {sleep_time}s")
            time.sleep(sleep_time)
            self._refill_tokens()

    def execute(
        self,
        func,
        *args,
        headers_callback=None,
        **kwargs
    ):
        """Execute a function with rate limiting and exponential backoff.

        Args:
            func: Callable to execute (e.g., httpx.Client.get)
            *args: Positional arguments to pass to func
            headers_callback: Optional callback to process response headers
            **kwargs: Keyword arguments to pass to func

        Returns:
            Result from func call

        Raises:
            RateLimitError: If rate limit exceeded after all retries
            NetworkError: If network communication fails
            AuthenticationError: If API key is invalid
            APIError: For other API-related errors
        """
        last_exception = None

        for attempt in range(self.config.max_retries + 1):
            try:
                # Wait if needed before making request
                self.wait_if_needed()

                # Make the request
                response = func(*args, **kwargs)

                # Process headers for rate limit info
                if headers_callback and hasattr(response, 'headers'):
                    headers_callback(dict(response.headers))

                # Record successful request
                self._record_request()
                self.state.consecutive_errors = 0

                # Check for HTTP errors
                if response.status_code == 429:
                    # Rate limited - extract retry-after if available
                    retry_after = response.headers.get("Retry-After")
                    wait_time = float(retry_after) if retry_after else 60.0
                    logger.warning(f"Rate limited by API, waiting {wait_time}s")
                    time.sleep(wait_time)
                    self._last_rate_limit_time = time.time()
                    continue

                if response.status_code == 401:
                    raise AuthenticationError(
                        "Invalid or missing API key",
                        status_code=401
                    )

                if response.status_code >= 400:
                    raise APIError(
                        f"API error: {response.status_code} - {response.text[:200]}",
                        status_code=response.status_code
                    )

                return response

            except RateLimitError:
                raise
            except AuthenticationError:
                raise
            except APIError:
                raise
            except Exception as e:
                last_exception = e
                self.state.consecutive_errors += 1

                # Check if it's a network error
                if "connection" in str(e).lower() or "timeout" in str(e).lower():
                    raise NetworkError(f"Network error: {str(e)}") from e

                # Exponential backoff for retries
                if attempt < self.config.max_retries:
                    delay = min(
                        self.config.backoff_base_seconds * (2 ** attempt),
                        self.config.backoff_max_seconds
                    )
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{self.config.max_retries + 1}), "
                        f"retrying in {delay:.1f}s: {str(e)}"
                    )
                    time.sleep(delay)
                else:
                    raise APIError(f"Request failed after {self.config.max_retries + 1} attempts: {str(e)}")

        # If we get here, all retries exhausted
        raise RateLimitError(
            f"Rate limit exceeded after {self.config.max_retries + 1} attempts"
        )


# Global rate limiter instance
_global_limiter: Optional[RateLimiter] = None
_limiter_lock = threading.Lock()


def get_rate_limiter(config: Optional[RateLimitConfig] = None) -> RateLimiter:
    """Get or create the global RateLimiter instance.

    Thread-safe singleton pattern for the rate limiter.
    """
    global _global_limiter

    if _global_limiter is None:
        with _limiter_lock:
            if _global_limiter is None:
                _global_limiter = RateLimiter(config)

    return _global_limiter


def reset_rate_limiter() -> None:
    """Reset the global rate limiter (primarily for testing)."""
    global _global_limiter
    with _limiter_lock:
        _global_limiter = None