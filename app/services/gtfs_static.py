"""
GTFS Static Data Service for fetching, parsing, and caching Caltrain schedules.

Handles:
- Download of static GTFS data from 511.org API or Caltrans fallback
- Parsing of GTFS zip files (stops, routes, trips, stop_times, calendar)
- SQLite storage for efficient querying
- Automatic refresh on configurable schedule
"""

import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import httpx
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.services.cache import cache
from app.utils.rate_limiter import get_rate_limiter, RateLimitConfig
from app.utils.exceptions import (
    GTFSFetchError,
    GTFSParseError,
    DatabaseError,
    NetworkUnavailableError,
)

settings = get_settings()
logger = logging.getLogger(__name__)


class GTFSStaticService:
    """Service for fetching, parsing, and caching static GTFS data.

    The GTFS static data contains scheduled service information including:
    - Stops: Station locations and names
    - Routes: Train lines and their characteristics
    - Trips: Individual train runs
    - Stop Times: Arrival/departure times at each stop
    - Calendar: Service days (weekday vs weekend schedules)

    Data is cached in SQLite for efficient queries and refreshed periodically.
    """

    # Primary and fallback URLs for GTFS data
    GTFS_URL = "https://api.511.org/transit/datafeeds?api_key={key}&operator_id=RG"
    CALTRANS_GTFS_URL = "https://transit.511.org/open-data/gtfs.zip"

    # Cache TTL for stops and routes (1 hour)
    STOPS_CACHE_TTL = 3600
    ROUTES_CACHE_TTL = 3600

    def __init__(self):
        """Initialize the GTFS static service."""
        self.db_path = settings.sqlite_db_path
        self.gtfs_zip_path = settings.gtfs_zip_path
        self.data_dir = Path(settings.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f"sqlite:///{self.db_path}")
        self.Session = sessionmaker = None  # Not used with raw SQL
        self._last_refresh: Optional[str] = None
        self._refresh_in_progress = False

        # Rate limiter for 511.org API
        self._rate_limiter = get_rate_limiter(
            RateLimitConfig(requests_per_hour=settings.rate_limit_requests_per_hour)
        )

    def _init_database(self) -> None:
        """Initialize SQLite database with GTFS tables.

        Creates all necessary tables and indexes if they don't exist.
        """
        try:
            with self.engine.connect() as conn:
                # Agency table
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS agency (
                        agency_id TEXT PRIMARY KEY,
                        agency_name TEXT,
                        agency_url TEXT,
                        agency_timezone TEXT,
                        agency_lang TEXT
                    )
                """))

                # Stops table
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS stops (
                        stop_id TEXT PRIMARY KEY,
                        stop_name TEXT,
                        stop_lat REAL,
                        stop_lon REAL,
                        zone_id TEXT,
                        location_type INTEGER,
                        parent_station TEXT
                    )
                """))

                # Routes table
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS routes (
                        route_id TEXT PRIMARY KEY,
                        route_short_name TEXT,
                        route_long_name TEXT,
                        route_type INTEGER,
                        route_color TEXT,
                        route_text_color TEXT,
                        agency_id TEXT
                    )
                """))

                # Trips table
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS trips (
                        trip_id TEXT PRIMARY KEY,
                        route_id TEXT,
                        service_id TEXT,
                        trip_headsign TEXT,
                        direction_id INTEGER,
                        block_id TEXT
                    )
                """))

                # Stop times table
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS stop_times (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trip_id TEXT,
                        stop_id TEXT,
                        arrival_time TEXT,
                        departure_time TEXT,
                        stop_sequence INTEGER,
                        pickup_type TEXT,
                        drop_off_type TEXT
                    )
                """))

                # Calendar table
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS calendar (
                        service_id TEXT PRIMARY KEY,
                        monday INTEGER,
                        tuesday INTEGER,
                        wednesday INTEGER,
                        thursday INTEGER,
                        friday INTEGER,
                        saturday INTEGER,
                        sunday INTEGER,
                        start_date TEXT,
                        end_date TEXT
                    )
                """))

                # Create indexes for performance
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_stop_times_trip ON stop_times(trip_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_stop_times_stop ON stop_times(stop_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_trips_route ON trips(route_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_trips_service ON trips(service_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_stops_name ON stops(stop_name)"))

                conn.commit()
                logger.info("Database initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise DatabaseError(f"Database initialization failed: {e}") from e

    def _download_gtfs(self) -> bool:
        """Download GTFS zip file from 511.org API with rate limiting.

        Returns:
            True if download successful, False otherwise

        Raises:
            GTFSFetchError: If download fails after all retries
            NetworkUnavailableError: If network is unavailable
        """
        api_key = settings.five_eleven_api_key

        if not api_key:
            logger.warning("No API key provided - attempting Caltrans fallback")
            return self._download_caltrans_gtfs()

        try:
            url = self.GTFS_URL.format(key=api_key)

            def make_request():
                with httpx.Client(timeout=120.0) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    return response

            response = self._rate_limiter.execute(
                make_request,
                headers_callback=lambda h: self._rate_limiter.update_from_response_headers(h)
            )

            with open(self.gtfs_zip_path, "wb") as f:
                f.write(response.content)

            logger.info(f"Downloaded GTFS data from 511.org API ({response.headers.get('content-length', 'unknown')} bytes)")
            return True

        except NetworkUnavailableError:
            logger.warning("511.org API unavailable, trying Caltrans fallback")
            return self._download_caltrans_gtfs()
        except Exception as e:
            logger.error(f"Failed to download from 511 API: {e}")
            return self._download_caltrans_gtfs()

    def _download_caltrans_gtfs(self) -> bool:
        """Fallback download from Caltrans public GTFS feed.

        Returns:
            True if download successful, False otherwise
        """
        try:
            with httpx.Client(timeout=180.0) as client:
                response = client.get(self.CALTRANS_GTFS_URL)
                response.raise_for_status()

            with open(self.gtfs_zip_path, "wb") as f:
                f.write(response.content)

            logger.info("Downloaded GTFS data from Caltrans fallback")
            return True

        except Exception as e:
            logger.error(f"Failed to download Caltrans GTFS: {e}")
            raise GTFSFetchError(
                f"Failed to download GTFS from any source: {e}"
            )

    def _parse_gtfs(self) -> bool:
        """Parse GTFS zip and store in SQLite.

        Returns:
            True if parsing successful, False otherwise

        Raises:
            GTFSParseError: If GTFS file is invalid or parsing fails
        """
        if not zipfile.is_zipfile(self.gtfs_zip_path):
            raise GTFSParseError(
                f"Downloaded file is not a valid ZIP archive: {self.gtfs_zip_path}"
            )

        try:
            # Extract zip contents
            extract_dir = self.data_dir / "gtfs_extracted"

            # Clean up old extraction
            if extract_dir.exists():
                import shutil
                shutil.rmtree(extract_dir)

            with zipfile.ZipFile(self.gtfs_zip_path, "r") as z:
                z.extractall(extract_dir)

            # Parse each GTFS file
            self._parse_agency(extract_dir)
            self._parse_stops(extract_dir)
            self._parse_routes(extract_dir)
            self._parse_trips(extract_dir)
            self._parse_stop_times(extract_dir)
            self._parse_calendar(extract_dir)

            self._last_refresh = datetime.now(timezone.utc).isoformat()
            logger.info("GTFS data parsed and stored successfully")
            return True

        except GTFSParseError:
            raise
        except Exception as e:
            logger.error(f"Failed to parse GTFS: {e}")
            raise GTFSParseError(f"Failed to parse GTFS data: {e}") from e

    def _parse_agency(self, extracted_dir: Path) -> None:
        """Parse agency.txt file.

        Args:
            extracted_dir: Path to extracted GTFS files
        """
        agency_file = extracted_dir / "agency.txt"
        if not agency_file.exists():
            logger.warning("agency.txt not found in GTFS feed")
            return

        try:
            df = pd.read_csv(agency_file)
            with self.engine.connect() as conn:
                for _, row in df.iterrows():
                    conn.execute(
                        text("""
                            INSERT OR REPLACE INTO agency VALUES (:agency_id, :agency_name,
                                :agency_url, :agency_timezone, :agency_lang)
                        """),
                        {
                            "agency_id": row.get("agency_id"),
                            "agency_name": row.get("agency_name"),
                            "agency_url": row.get("agency_url"),
                            "agency_timezone": row.get("agency_timezone"),
                            "agency_lang": row.get("agency_lang"),
                        },
                    )
                conn.commit()
            logger.debug(f"Parsed {len(df)} agency records")
        except Exception as e:
            logger.warning(f"Failed to parse agency.txt: {e}")

    def _parse_stops(self, extracted_dir: Path) -> None:
        """Parse stops.txt file.

        Args:
            extracted_dir: Path to extracted GTFS files
        """
        stops_file = extracted_dir / "stops.txt"
        if not stops_file.exists():
            raise GTFSParseError("stops.txt not found in GTFS feed", file_name="stops.txt")

        try:
            df = pd.read_csv(stops_file)
            with self.engine.connect() as conn:
                # Clear existing data
                conn.execute(text("DELETE FROM stops"))

                for _, row in df.iterrows():
                    conn.execute(
                        text("""
                            INSERT OR REPLACE INTO stops VALUES (:stop_id, :stop_name,
                                :stop_lat, :stop_lon, :zone_id, :location_type, :parent_station)
                        """),
                        {
                            "stop_id": row["stop_id"],
                            "stop_name": row["stop_name"],
                            "stop_lat": row["stop_lat"],
                            "stop_lon": row["stop_lon"],
                            "zone_id": row.get("zone_id"),
                            "location_type": row.get("location_type", 0),
                            "parent_station": row.get("parent_station"),
                        },
                    )
                conn.commit()
            logger.info(f"Parsed {len(df)} stops")
        except Exception as e:
            raise GTFSParseError(f"Failed to parse stops.txt: {e}", file_name="stops.txt") from e

    def _parse_routes(self, extracted_dir: Path) -> None:
        """Parse routes.txt file.

        Args:
            extracted_dir: Path to extracted GTFS files
        """
        routes_file = extracted_dir / "routes.txt"
        if not routes_file.exists():
            raise GTFSParseError("routes.txt not found in GTFS feed", file_name="routes.txt")

        try:
            df = pd.read_csv(routes_file)
            with self.engine.connect() as conn:
                conn.execute(text("DELETE FROM routes"))

                for _, row in df.iterrows():
                    conn.execute(
                        text("""
                            INSERT OR REPLACE INTO routes VALUES (:route_id, :route_short_name,
                                :route_long_name, :route_type, :route_color, :route_text_color, :agency_id)
                        """),
                        {
                            "route_id": row["route_id"],
                            "route_short_name": row.get("route_short_name"),
                            "route_long_name": row.get("route_long_name"),
                            "route_type": row.get("route_type"),
                            "route_color": row.get("route_color"),
                            "route_text_color": row.get("route_text_color"),
                            "agency_id": row.get("agency_id"),
                        },
                    )
                conn.commit()
            logger.info(f"Parsed {len(df)} routes")
        except Exception as e:
            raise GTFSParseError(f"Failed to parse routes.txt: {e}", file_name="routes.txt") from e

    def _parse_trips(self, extracted_dir: Path) -> None:
        """Parse trips.txt file.

        Args:
            extracted_dir: Path to extracted GTFS files
        """
        trips_file = extracted_dir / "trips.txt"
        if not trips_file.exists():
            raise GTFSParseError("trips.txt not found in GTFS feed", file_name="trips.txt")

        try:
            df = pd.read_csv(trips_file)
            with self.engine.connect() as conn:
                conn.execute(text("DELETE FROM trips"))

                for _, row in df.iterrows():
                    conn.execute(
                        text("""
                            INSERT OR REPLACE INTO trips VALUES (:trip_id, :route_id,
                                :service_id, :trip_headsign, :direction_id, :block_id)
                        """),
                        {
                            "trip_id": row["trip_id"],
                            "route_id": row["route_id"],
                            "service_id": row["service_id"],
                            "trip_headsign": row.get("trip_headsign"),
                            "direction_id": int(row.get("direction_id", 0)),
                            "block_id": row.get("block_id"),
                        },
                    )
                conn.commit()
            logger.info(f"Parsed {len(df)} trips")
        except Exception as e:
            raise GTFSParseError(f"Failed to parse trips.txt: {e}", file_name="trips.txt") from e

    def _parse_stop_times(self, extracted_dir: Path) -> None:
        """Parse stop_times.txt file.

        Args:
            extracted_dir: Path to extracted GTFS files
        """
        stop_times_file = extracted_dir / "stop_times.txt"
        if not stop_times_file.exists():
            raise GTFSParseError("stop_times.txt not found in GTFS feed", file_name="stop_times.txt")

        try:
            df = pd.read_csv(stop_times_file)
            with self.engine.connect() as conn:
                conn.execute(text("DELETE FROM stop_times"))

                for _, row in df.iterrows():
                    conn.execute(
                        text("""
                            INSERT INTO stop_times (trip_id, stop_id, arrival_time, departure_time,
                                stop_sequence, pickup_type, drop_off_type)
                            VALUES (:trip_id, :stop_id, :arrival_time, :departure_time,
                                :stop_sequence, :pickup_type, :drop_off_type)
                        """),
                        {
                            "trip_id": row["trip_id"],
                            "stop_id": row["stop_id"],
                            "arrival_time": row.get("arrival_time"),
                            "departure_time": row.get("departure_time"),
                            "stop_sequence": row["stop_sequence"],
                            "pickup_type": row.get("pickup_type"),
                            "drop_off_type": row.get("drop_off_type"),
                        },
                    )
                conn.commit()
            logger.info(f"Parsed {len(df)} stop times")
        except Exception as e:
            raise GTFSParseError(f"Failed to parse stop_times.txt: {e}", file_name="stop_times.txt") from e

    def _parse_calendar(self, extracted_dir: Path) -> None:
        """Parse calendar.txt and calendar_dates.txt files.

        Args:
            extracted_dir: Path to extracted GTFS files
        """
        calendar_file = extracted_dir / "calendar.txt"

        if calendar_file.exists():
            self._parse_calendar_file(calendar_file)
        else:
            # Try calendar_dates.txt for exception-based service
            calendar_dates_file = extracted_dir / "calendar_dates.txt"
            if calendar_dates_file.exists():
                self._parse_calendar_dates(calendar_dates_file)
            else:
                logger.warning("No calendar.txt or calendar_dates.txt found")

    def _parse_calendar_file(self, calendar_file: Path) -> None:
        """Parse calendar.txt file.

        Args:
            calendar_file: Path to calendar.txt
        """
        try:
            df = pd.read_csv(calendar_file)
            with self.engine.connect() as conn:
                conn.execute(text("DELETE FROM calendar"))

                for _, row in df.iterrows():
                    conn.execute(
                        text("""
                            INSERT OR REPLACE INTO calendar VALUES (:service_id, :monday,
                                :tuesday, :wednesday, :thursday, :friday, :saturday, :sunday,
                                :start_date, :end_date)
                        """),
                        {
                            "service_id": row["service_id"],
                            "monday": int(row["monday"]),
                            "tuesday": int(row["tuesday"]),
                            "wednesday": int(row["wednesday"]),
                            "thursday": int(row["thursday"]),
                            "friday": int(row["friday"]),
                            "saturday": int(row["saturday"]),
                            "sunday": int(row["sunday"]),
                            "start_date": row["start_date"],
                            "end_date": row["end_date"],
                        },
                    )
                conn.commit()
            logger.info(f"Parsed {len(df)} calendar entries")
        except Exception as e:
            logger.warning(f"Failed to parse calendar.txt: {e}")

    def _parse_calendar_dates(self, calendar_dates_file: Path) -> None:
        """Parse calendar_dates.txt for exception-based service.

        Args:
            calendar_dates_file: Path to calendar_dates.txt
        """
        try:
            df = pd.read_csv(calendar_dates_file)
            with self.engine.connect() as conn:
                for _, row in df.iterrows():
                    conn.execute(
                        text("""
                            INSERT OR REPLACE INTO calendar VALUES (:service_id, 0, 0, 0, 0, 0, 0, 0, :date, :date)
                        """),
                        {
                            "service_id": row["service_id"],
                            "date": str(row["date"]),
                        },
                    )
                conn.commit()
            logger.info(f"Parsed {len(df)} calendar date exceptions")
        except Exception as e:
            logger.warning(f"Failed to parse calendar_dates.txt: {e}")

    def refresh(self) -> bool:
        """Refresh static GTFS data from 511.org API.

        Downloads new GTFS data if available and parses it into the database.

        Returns:
            True if refresh successful, False otherwise
        """
        if self._refresh_in_progress:
            logger.warning("Refresh already in progress, skipping")
            return False

        self._refresh_in_progress = True

        try:
            self._init_database()

            if not self._download_gtfs():
                return False

            return self._parse_gtfs()

        except Exception as e:
            logger.error(f"GTFS refresh failed: {e}")
            return False
        finally:
            self._refresh_in_progress = False

    def get_stops(self, agency: str = "RG") -> list[dict]:
        """Get all Caltrain stops from database.

        Args:
            agency: Agency ID filter (default: RG for Caltrain)

        Returns:
            List of stop dicts with id, name, lat, lon
        """
        cached = cache.get(f"stops_{agency}", ttl_seconds=self.STOPS_CACHE_TTL)
        if cached:
            return cached

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT * FROM stops ORDER BY stop_name"))
                rows = result.fetchall()

            stops = [
                {
                    "stop_id": row.stop_id,
                    "stop_name": row.stop_name,
                    "stop_lat": row.stop_lat,
                    "stop_lon": row.stop_lon,
                    "zone_id": row.zone_id,
                    "location_type": row.location_type,
                }
                for row in rows
            ]

            cache.set(f"stops_{agency}", stops)
            return stops

        except Exception as e:
            logger.error(f"Failed to get stops from database: {e}")
            raise DatabaseError(f"Failed to query stops: {e}") from e

    def get_stop_by_id(self, stop_id: str) -> Optional[dict]:
        """Get a specific stop by ID.

        Args:
            stop_id: The stop ID to look up

        Returns:
            Stop dict or None if not found
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT * FROM stops WHERE stop_id = :stop_id"),
                    {"stop_id": stop_id}
                )
                row = result.fetchone()

            if not row:
                return None

            return {
                "stop_id": row.stop_id,
                "stop_name": row.stop_name,
                "stop_lat": row.stop_lat,
                "stop_lon": row.stop_lon,
                "zone_id": row.zone_id,
                "location_type": row.location_type,
            }

        except Exception as e:
            logger.error(f"Failed to get stop {stop_id}: {e}")
            return None

    def get_routes(self) -> list[dict]:
        """Get all Caltrain routes from database.

        Returns:
            List of route dicts
        """
        cached = cache.get("routes", ttl_seconds=self.ROUTES_CACHE_TTL)
        if cached:
            return cached

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT * FROM routes"))
                rows = result.fetchall()

            routes = [
                {
                    "route_id": row.route_id,
                    "route_short_name": row.route_short_name,
                    "route_long_name": row.route_long_name,
                    "route_type": row.route_type,
                    "route_color": row.route_color or "FFFFFF",
                    "route_text_color": row.route_text_color or "000000",
                }
                for row in rows
            ]

            cache.set("routes", routes)
            return routes

        except Exception as e:
            logger.error(f"Failed to get routes from database: {e}")
            raise DatabaseError(f"Failed to query routes: {e}") from e

    def get_trips_for_route(self, route_id: str) -> list[dict]:
        """Get all trips for a specific route.

        Args:
            route_id: The route ID to look up

        Returns:
            List of trip dicts
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT * FROM trips WHERE route_id = :route_id"),
                    {"route_id": route_id}
                )
                rows = result.fetchall()

            return [
                {
                    "trip_id": row.trip_id,
                    "route_id": row.route_id,
                    "service_id": row.service_id,
                    "trip_headsign": row.trip_headsign,
                    "direction_id": row.direction_id,
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"Failed to get trips for route {route_id}: {e}")
            return []

    def get_stop_times_for_trip(self, trip_id: str) -> list[dict]:
        """Get all stop times for a specific trip, ordered by sequence.

        Args:
            trip_id: The trip ID to look up

        Returns:
            List of stop time dicts
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT * FROM stop_times
                        WHERE trip_id = :trip_id
                        ORDER BY stop_sequence
                    """),
                    {"trip_id": trip_id}
                )
                rows = result.fetchall()

            return [
                {
                    "trip_id": row.trip_id,
                    "stop_id": row.stop_id,
                    "arrival_time": row.arrival_time,
                    "departure_time": row.departure_time,
                    "stop_sequence": row.stop_sequence,
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"Failed to get stop times for trip {trip_id}: {e}")
            return []

    def get_service_ids_for_date(self, date_str: str) -> list[str]:
        """Get service IDs active on a given date.

        Args:
            date_str: Date in YYYYMMDD format

        Returns:
            List of active service IDs
        """
        try:
            from datetime import date

            year = int(date_str[:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])

            check_date = date(year, month, day)
            weekday = check_date.weekday()  # 0=Monday, 6=Sunday

            day_columns = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            day_column = day_columns[weekday]

            with self.engine.connect() as conn:
                result = conn.execute(
                    text(f"""
                        SELECT service_id FROM calendar
                        WHERE {day_column} = 1
                        AND start_date <= :date_str
                        AND end_date >= :date_str
                    """),
                    {"date_str": date_str}
                )
                rows = result.fetchall()

            return [row.service_id for row in rows]

        except Exception as e:
            logger.error(f"Failed to get service IDs for date {date_str}: {e}")
            return []

    def get_trips_with_stops(
        self,
        origin_stop_id: str,
        direction_id: Optional[int] = None,
        service_ids: Optional[list[str]] = None,
    ) -> list[dict]:
        """Get all trips at a specific stop with full stop times.

        Args:
            origin_stop_id: Stop ID to query
            direction_id: Optional direction filter (0=northbound, 1=southbound)
            service_ids: Optional list of service IDs to filter by

        Returns:
            List of trip dicts with stop times
        """
        try:
            with self.engine.connect() as conn:
                query = """
                    SELECT DISTINCT st.trip_id, st.arrival_time, st.departure_time, st.stop_sequence,
                           t.route_id, t.service_id, t.trip_headsign, t.direction_id
                    FROM stop_times st
                    JOIN trips t ON st.trip_id = t.trip_id
                    WHERE st.stop_id = :stop_id
                """
                params = {"stop_id": origin_stop_id}

                if direction_id is not None:
                    query += " AND t.direction_id = :direction_id"
                    params["direction_id"] = direction_id

                if service_ids:
                    placeholders = ",".join([f":service_{i}" for i in range(len(service_ids))])
                    query += f" AND t.service_id IN ({placeholders})"
                    for i, sid in enumerate(service_ids):
                        params[f"service_{i}"] = sid

                query += " ORDER BY st.departure_time"

                result = conn.execute(text(query), params)
                rows = result.fetchall()

            return [
                {
                    "trip_id": row.trip_id,
                    "arrival_time": row.arrival_time,
                    "departure_time": row.departure_time,
                    "stop_sequence": row.stop_sequence,
                    "route_id": row.route_id,
                    "service_id": row.service_id,
                    "trip_headsign": row.trip_headsign,
                    "direction_id": row.direction_id,
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"Failed to get trips for stop {origin_stop_id}: {e}")
            return []

    def get_last_refresh_time(self) -> Optional[str]:
        """Get the last GTFS refresh timestamp.

        Returns:
            ISO timestamp or None if never refreshed
        """
        return self._last_refresh

    def is_data_loaded(self) -> bool:
        """Check if GTFS data is loaded in the database.

        Returns:
            True if stops table has data
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM stops"))
                count = result.scalar()
            return count > 0
        except Exception:
            return False


# Singleton instance
gtfs_static = GTFSStaticService()