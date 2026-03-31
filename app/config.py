from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import field_validator, Field
from functools import lru_cache
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings can be overridden via .env file or environment variables.
    """

    # 511.org API configuration
    five_eleven_api_key: str = Field(
        default="",
        description="511.org API key for transit data access"
    )

    # GTFS refresh interval
    gtfs_refresh_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Hours between automatic GTFS static data refreshes (1-168)"
    )

    # Cache TTL in minutes
    cache_ttl_minutes: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Default cache TTL in minutes (1-60)"
    )

    # Debug mode
    debug: bool = Field(
        default=False,
        description="Enable debug mode with verbose logging"
    )

    # Data directory paths
    data_dir: str = Field(
        default="data",
        description="Directory for cached GTFS files and SQLite database"
    )

    sqlite_db_path: str = Field(
        default="data/caltrain.db",
        description="Path to SQLite database file"
    )

    gtfs_zip_path: str = Field(
        default="data/gtfs.zip",
        description="Path to cached GTFS zip file"
    )

    # Rate limiting configuration
    rate_limit_requests_per_hour: int = Field(
        default=60,
        ge=1,
        le=1000,
        description="Maximum requests per hour to 511.org API"
    )

    rate_limit_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retries after rate limiting"
    )

    # Server configuration
    server_host: str = Field(
        default="0.0.0.0",
        description="Server bind host"
    )

    server_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Server bind port"
    )

    class Config:
        env_file = ".env"
        extra = "allow"

    @field_validator("data_dir", "sqlite_db_path", "gtfs_zip_path")
    @classmethod
    def ensure_directory_exists(cls, v: str) -> str:
        """Ensure the parent directory for path exists."""
        path = Path(v)
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)
        return v

    @field_validator("five_eleven_api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Validate API key format."""
        if v and len(v) < 10:
            raise ValueError("API key appears to be too short (minimum 10 characters)")
        return v

    def get_data_dir(self) -> Path:
        """Get data directory as Path object, creating if needed."""
        path = Path(self.data_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def validate(self) -> list[str]:
        """Validate settings and return list of warnings.

        Returns list of warning messages for configuration issues.
        """
        warnings = []

        if not self.five_eleven_api_key:
            warnings.append(
                "No 511.org API key configured. Set FIVE_ELEVEN_API_KEY in environment. "
                "The server will fall back to Caltrans public GTFS but real-time data will be unavailable."
            )

        if self.debug:
            warnings.append("Debug mode is enabled - do not use in production")

        # Validate paths are writable
        data_dir = self.get_data_dir()
        if not os.access(str(data_dir), os.W_OK):
            warnings.append(f"Data directory {data_dir} is not writable")

        return warnings


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()