"""
Custom exceptions for the Caltrain API server.
"""


class CaltrainAPIError(Exception):
    """Base exception for all Caltrain API errors."""

    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class GTFSFetchError(CaltrainAPIError):
    """Raised when GTFS data fetch fails."""
    pass


class GTFSParseError(CaltrainAPIError):
    """Raised when GTFS data parsing fails."""

    def __init__(self, message: str, file_name: str = None, line_number: int = None):
        super().__init__(message, {"file_name": file_name, "line_number": line_number})
        self.file_name = file_name
        self.line_number = line_number


class GTRTParseError(CaltrainAPIError):
    """Raised when GTFS-RT protobuf parsing fails."""

    def __init__(self, message: str, entity_id: str = None):
        super().__init__(message, {"entity_id": entity_id})
        self.entity_id = entity_id


class DatabaseError(CaltrainAPIError):
    """Raised when database operations fail."""
    pass


class CacheError(CaltrainAPIError):
    """Raised when cache operations fail."""
    pass


class ValidationError(CaltrainAPIError):
    """Raised when input validation fails."""

    def __init__(self, message: str, field: str = None, value = None):
        super().__init__(message, {"field": field, "value": str(value) if value else None})
        self.field = field
        self.value = value


class RateLimitExceededError(CaltrainAPIError):
    """Raised when 511.org API rate limit is exceeded."""

    def __init__(self, retry_after: float = None):
        super().__init__(
            "511.org API rate limit exceeded",
            {"retry_after": retry_after} if retry_after else {}
        )
        self.retry_after = retry_after


class NetworkUnavailableError(CaltrainAPIError):
    """Raised when network is unavailable for API calls."""
    pass