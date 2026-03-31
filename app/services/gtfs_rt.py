"""
GTFS-RT (Real-Time) service for fetching and parsing protobuf data from 511.org.

Supports:
- TripUpdates: Real-time arrival/departure delays
- VehiclePositions: Current train locations
- ServiceAlerts: Service disruption notifications
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from google.transit import gtfs_realtime_pb2

from app.config import get_settings
from app.services.cache import cache
from app.utils.rate_limiter import get_rate_limiter, RateLimitConfig
from app.utils.exceptions import GTRTParseError, NetworkUnavailableError

settings = get_settings()
logger = logging.getLogger(__name__)


# Train type classification based on route/headsign patterns
TRAIN_TYPE_PATTERNS = {
    "local": {"headsigns": ["Local"], "prefixes": ["1", "2", "3"]},
    "limited": {"headsigns": ["Limited"], "prefixes": ["4"]},
    "express": {"headsigns": ["Express"], "prefixes": ["5"]},
    "weekend": {"headsigns": ["Weekend"], "prefixes": ["6"]},
    "south_county": {"headsigns": ["Gilroy", "San Jose"], "prefixes": ["8"]},
}

# Colors for each train type (hex format)
TRAIN_COLORS = {
    "local": "#808080",      # Gray - local trains
    "limited": "#FFD700",    # Yellow - limited stops
    "express": "#FF0000",    # Red - express trains
    "weekend": "#00FF00",   # Green - weekend service
    "south_county": "#FFA500",  # Orange - Gilroy extension
}


class GTFSRTService:
    """Service for fetching and parsing GTFS-RT protobuf data from 511.org.

    Handles three main feed types:
    - TripUpdates: Real-time delay and stop time updates
    - VehiclePositions: Current geographic position of trains
    - ServiceAlerts: Service disruptions and notices

    All fetched data is cached with appropriate TTLs to respect rate limits.
    """

    TRIP_UPDATES_URL = "https://api.511.org/Transit/TripUpdates?api_key={key}&agency=RG"
    VEHICLE_POSITIONS_URL = "https://api.511.org/Transit/VehiclePositions?api_key={key}&agency=RG"
    SERVICE_ALERTS_URL = "https://api.511.org/Transit/ServicesAlerts?api_key={key}&agency=RG"

    # Cache TTLs in seconds
    TRIP_UPDATES_TTL = 90
    VEHICLE_POSITIONS_TTL = 60
    SERVICE_ALERTS_TTL = 120

    def __init__(self):
        """Initialize GTFS-RT service with rate limiting."""
        self.api_key = settings.five_eleven_api_key
        self._last_rt_update: Optional[str] = None
        self._rate_limiter = get_rate_limiter(
            RateLimitConfig(requests_per_hour=settings.rate_limit_requests_per_hour)
        )
        self._initialize_caches()

    def _initialize_caches(self) -> None:
        """Initialize empty caches for fallback data."""
        self._cached_trip_updates: dict = {}
        self._cached_vehicle_positions: dict = {}
        self._cached_alerts: dict = {}

    def _fetch_pb(self, url: str) -> Optional[bytes]:
        """Fetch protobuf data from URL with rate limiting and error handling.

        Args:
            url: URL to fetch protobuf from

        Returns:
            Raw protobuf bytes or None if fetch fails

        Raises:
            NetworkUnavailableError: If network is unavailable
        """
        if not self.api_key:
            logger.warning("No API key configured - cannot fetch GTFS-RT data")
            return None

        try:
            def make_request():
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    return response

            response = self._rate_limiter.execute(
                make_request,
                headers_callback=lambda h: self._rate_limiter.update_from_response_headers(h)
            )

            return response.content

        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching GTFS-RT data: {e}")
            raise NetworkUnavailableError(f"Request timed out: {e}") from e
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching GTFS-RT data: {e}")
            raise NetworkUnavailableError(f"Connection failed: {e}") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error("Authentication failed - check API key")
                raise NetworkUnavailableError("Invalid API key") from e
            if e.response.status_code == 403:
                logger.error("Access forbidden - rate limit or subscription issue")
                raise NetworkUnavailableError("Access forbidden - check rate limits") from e
            logger.error(f"HTTP error fetching GTFS-RT: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching GTFS-RT: {e}")
            return None

    def _parse_trip_update(self, entity) -> Optional[dict]:
        """Parse a single TripUpdate entity from GTFS-RT feed.

        Args:
            entity: GTFS-RT FeedEntity containing trip_update

        Returns:
            Dict with parsed trip update data or None if parsing fails
        """
        try:
            tu = entity.trip_update

            if not tu.trip or not tu.trip.trip_id:
                return None

            trip_id = tu.trip.trip_id

            # Parse stop time updates
            stop_time_updates = []
            for stu in tu.stop_time_update:
                stop_update = {
                    "stop_id": stu.stop_id,
                    "stop_sequence": stu.stop_sequence,
                    "arrival_delay": None,
                    "departure_delay": None,
                    "schedule_relationship": str(stu.schedule_relationship),
                }

                # Extract arrival delay if present
                if stu.arrival.HasField("delay"):
                    stop_update["arrival_delay"] = stu.arrival.delay

                # Extract departure delay if present
                if stu.departure.HasField("delay"):
                    stop_update["departure_delay"] = stu.departure.delay

                stop_time_updates.append(stop_update)

            # Build trip update dict
            return {
                "trip_id": trip_id,
                "route_id": tu.trip.route_id if tu.trip.HasField("route_id") else None,
                "direction_id": tu.trip.direction_id if tu.trip.HasField("direction_id") else None,
                "vehicle_id": tu.vehicle.id if tu.vehicle.HasField("id") else None,
                "timestamp": tu.timestamp if tu.HasField("timestamp") else None,
                "stop_time_updates": stop_time_updates,
            }

        except Exception as e:
            logger.warning(f"Failed to parse trip update entity: {e}")
            return None

    def _parse_vehicle_position(self, entity) -> Optional[dict]:
        """Parse a single VehiclePosition entity from GTFS-RT feed.

        Args:
            entity: GTFS-RT FeedEntity containing vehicle

        Returns:
            Dict with parsed vehicle position data or None if parsing fails
        """
        try:
            v = entity.vehicle

            # Get vehicle ID
            vehicle_id = v.vehicle.id if v.vehicle.HasField("id") else entity.id

            # Get position data
            position = {
                "vehicle_id": vehicle_id,
                "trip_id": v.trip.trip_id if v.trip.HasField("trip_id") else None,
                "route_id": v.trip.route_id if v.trip.HasField("route_id") else None,
                "lat": v.position.latitude if v.position.HasField("latitude") else None,
                "lon": v.position.longitude if v.position.HasField("longitude") else None,
                "bearing": v.position.bearing if v.position.HasField("bearing") else None,
                "speed": v.position.speed if v.position.HasField("speed") else None,
                "timestamp": v.timestamp if v.HasField("timestamp") else None,
            }

            return position

        except Exception as e:
            logger.warning(f"Failed to parse vehicle position entity: {e}")
            return None

    def _parse_alert(self, entity) -> Optional[dict]:
        """Parse a single Alert entity from GTFS-RT feed.

        Args:
            entity: GTFS-RT FeedEntity containing alert

        Returns:
            Dict with parsed alert data or None if parsing fails
        """
        try:
            alert = entity.alert
            alert_text = ""

            # Try to get header text
            if alert.header_text.translation:
                alert_text = alert.header_text.translation[0].text
            elif alert.description_text.translation:
                alert_text = alert.description_text.translation[0].text

            # Parse informed entities (affected routes/stops/trips)
            informed_entities = []
            for ie in alert.informed_entity:
                entity_data = {
                    "agency_id": None,
                    "route_id": None,
                    "trip_id": None,
                    "stop_id": None,
                }

                if ie.HasField("agency_id"):
                    entity_data["agency_id"] = ie.agency_id.id
                if ie.HasField("route_id"):
                    entity_data["route_id"] = ie.route_id.id
                if ie.trip.HasField("trip_id"):
                    entity_data["trip_id"] = ie.trip.trip_id
                if ie.HasField("stop_id"):
                    entity_data["stop_id"] = ie.stop_id.id

                informed_entities.append(entity_data)

            # Parse active period
            active_period = {}
            if alert.HasField("active_period"):
                if alert.active_period.HasField("start"):
                    active_period["start"] = alert.active_period.start
                if alert.active_period.HasField("end"):
                    active_period["end"] = alert.active_period.end

            return {
                "alert_id": entity.id,
                "active_period": active_period if active_period else None,
                "effect": str(alert.effect) if alert.HasField("effect") else None,
                "cause": str(alert.cause) if alert.HasField("cause") else None,
                "header_text": alert_text,
                "informed_entities": informed_entities,
            }

        except Exception as e:
            logger.warning(f"Failed to parse alert entity: {e}")
            return None

    def fetch_trip_updates(self) -> dict:
        """Fetch and parse TripUpdates GTFS-RT feed.

        Returns:
            Dict mapping trip_id to trip update data
        """
        cached = cache.get("trip_updates", ttl_seconds=self.TRIP_UPDATES_TTL)
        if cached:
            return cached

        url = self.TRIP_UPDATES_URL.format(key=self.api_key)
        data = self._fetch_pb(url)

        if not data:
            logger.info("Using cached trip updates (fetch failed)")
            return self._cached_trip_updates

        try:
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(data)

            trip_updates = {}
            for entity in feed.entity:
                if entity.HasField("trip_update"):
                    parsed = self._parse_trip_update(entity)
                    if parsed:
                        trip_updates[parsed["trip_id"]] = parsed

            self._cached_trip_updates = trip_updates
            self._last_rt_update = datetime.now(timezone.utc).isoformat()
            cache.set("trip_updates", trip_updates)
            logger.debug(f"Fetched {len(trip_updates)} trip updates")

        except Exception as e:
            logger.error(f"Failed to parse TripUpdates protobuf: {e}")
            raise GTRTParseError(f"Failed to parse TripUpdates: {e}") from e

        return trip_updates

    def fetch_vehicle_positions(self) -> dict:
        """Fetch and parse VehiclePositions GTFS-RT feed.

        Returns:
            Dict mapping vehicle_id to position data
        """
        cached = cache.get("vehicle_positions", ttl_seconds=self.VEHICLE_POSITIONS_TTL)
        if cached:
            return cached

        url = self.VEHICLE_POSITIONS_URL.format(key=self.api_key)
        data = self._fetch_pb(url)

        if not data:
            logger.info("Using cached vehicle positions (fetch failed)")
            return self._cached_vehicle_positions

        try:
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(data)

            vehicle_positions = {}
            for entity in feed.entity:
                if entity.HasField("vehicle"):
                    parsed = self._parse_vehicle_position(entity)
                    if parsed:
                        vehicle_positions[parsed["vehicle_id"]] = parsed

            self._cached_vehicle_positions = vehicle_positions
            cache.set("vehicle_positions", vehicle_positions)
            logger.debug(f"Fetched {len(vehicle_positions)} vehicle positions")

        except Exception as e:
            logger.error(f"Failed to parse VehiclePositions protobuf: {e}")
            raise GTRTParseError(f"Failed to parse VehiclePositions: {e}") from e

        return vehicle_positions

    def fetch_alerts(self) -> dict:
        """Fetch and parse ServiceAlerts GTFS-RT feed.

        Returns:
            Dict mapping alert_id to alert data
        """
        cached = cache.get("alerts", ttl_seconds=self.SERVICE_ALERTS_TTL)
        if cached:
            return cached

        url = self.SERVICE_ALERTS_URL.format(key=self.api_key)
        data = self._fetch_pb(url)

        if not data:
            logger.info("Using cached alerts (fetch failed)")
            return self._cached_alerts

        try:
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(data)

            alerts = {}
            for entity in feed.entity:
                if entity.HasField("alert"):
                    parsed = self._parse_alert(entity)
                    if parsed:
                        alerts[entity.id] = parsed

            self._cached_alerts = alerts
            cache.set("alerts", alerts)
            logger.debug(f"Fetched {len(alerts)} service alerts")

        except Exception as e:
            logger.error(f"Failed to parse ServiceAlerts protobuf: {e}")
            raise GTRTParseError(f"Failed to parse ServiceAlerts: {e}") from e

        return alerts

    def classify_train_type(
        self,
        trip_headsign: str = "",
        route_short_name: str = ""
    ) -> tuple[str, str]:
        """Classify train type based on headsign or route number.

        Classification is based on Caltrain's naming conventions:
        - Local (1xx): Stops at all stations
        - Limited (4xx): Skips some local stops
        - Express (5xx): Only stops at major stations
        - Weekend (6xx): Weekend-specific service
        - South County (8xx): Extended service to Gilroy

        Args:
            trip_headsign: Trip headsign text (e.g., "San Francisco Local")
            route_short_name: Route short name/number (e.g., "401")

        Returns:
            Tuple of (type_name, color_hex)
        """
        headsign_lower = (trip_headsign or "").lower()
        route_prefix = (route_short_name or "")[0] if route_short_name else ""

        # Check headsign patterns first
        for train_type, pattern in TRAIN_TYPE_PATTERNS.items():
            for hs in pattern["headsigns"]:
                if hs.lower() in headsign_lower:
                    return train_type, TRAIN_COLORS[train_type]

        # Then check route number prefix
        for train_type, pattern in TRAIN_TYPE_PATTERNS.items():
            if route_prefix in pattern["prefixes"]:
                return train_type, TRAIN_COLORS[train_type]

        # Default to local
        return "local", TRAIN_COLORS["local"]

    def get_trip_update(self, trip_id: str) -> Optional[dict]:
        """Get trip update for a specific trip.

        Args:
            trip_id: The trip ID to look up

        Returns:
            Trip update dict or None if not found
        """
        trip_updates = self.fetch_trip_updates()
        return trip_updates.get(trip_id)

    def get_vehicle_position(self, trip_id: str) -> Optional[dict]:
        """Get vehicle position for a specific trip.

        Searches through vehicle positions to find one matching the trip.

        Args:
            trip_id: The trip ID to look up

        Returns:
            Vehicle position dict or None if not found
        """
        vehicle_positions = self.fetch_vehicle_positions()

        for vehicle_id, pos in vehicle_positions.items():
            if pos.get("trip_id") == trip_id:
                return pos

        return None

    def get_alerts_for_trip(self, trip_id: str) -> list[str]:
        """Get alert text messages for a specific trip.

        Args:
            trip_id: The trip ID to look up

        Returns:
            List of alert header text strings
        """
        alerts = self.fetch_alerts()
        relevant_alerts = []

        for alert_id, alert in alerts.items():
            for entity in alert.get("informed_entities", []):
                if entity.get("trip_id") == trip_id:
                    if alert.get("header_text"):
                        relevant_alerts.append(alert["header_text"])
                    break

        return relevant_alerts

    def get_alerts_for_route(self, route_id: str) -> list[dict]:
        """Get all alert data for a specific route.

        Args:
            route_id: The route ID to look up

        Returns:
            List of alert dicts affecting this route
        """
        alerts = self.fetch_alerts()
        route_alerts = []

        for alert_id, alert in alerts.items():
            for entity in alert.get("informed_entities", []):
                if entity.get("route_id") == route_id:
                    route_alerts.append(alert)
                    break

        return route_alerts

    def get_alerts_for_stop(self, stop_id: str) -> list[dict]:
        """Get all alert data for a specific stop.

        Args:
            stop_id: The stop ID to look up

        Returns:
            List of alert dicts affecting this stop
        """
        alerts = self.fetch_alerts()
        stop_alerts = []

        for alert_id, alert in alerts.items():
            for entity in alert.get("informed_entities", []):
                if entity.get("stop_id") == stop_id:
                    stop_alerts.append(alert)
                    break

        return stop_alerts

    def get_last_rt_update(self) -> Optional[str]:
        """Get the timestamp of the last successful RT update.

        Returns:
            ISO timestamp string or None if no updates yet
        """
        return self._last_rt_update


# Singleton instance
gtfs_rt = GTFSRTService()