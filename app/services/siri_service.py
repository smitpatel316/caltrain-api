"""
SIRI (Service Interface for Real Time Information) service for stop monitoring.

Implements SIRI SM (Stop Monitoring) and VM (Vehicle Monitoring) requests
to get real-time arrival/departure information from 511.org.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.config import get_settings
from app.services.cache import cache
from app.utils.rate_limiter import get_rate_limiter, RateLimitConfig
from app.utils.exceptions import NetworkUnavailableError

settings = get_settings()
logger = logging.getLogger(__name__)


class SIRIService:
    """Service for SIRI Stop Monitoring and Vehicle Monitoring.

    SIRI is a European standard for real-time transit information.
    511.org provides SIRI-SM and SIRI-VM endpoints for stop arrival predictions
    and vehicle location tracking.
    """

    # SIRI Stop Monitoring endpoint
    STOP_MONITORING_URL = "https://api.511.org/Transit/StopMonitoring?api_key={key}&agency=RG"

    # SIRI Vehicle Monitoring endpoint
    VEHICLE_MONITORING_URL = "https://api.511.org/Transit/VehicleMonitoring?api_key={key}&agency=RG"

    # SIRI Service Departures endpoint
    SERVICE_DEPARTURES_URL = "https://api.511.org/Transit/ServicesAtStops?api_key={key}&agency=RG"

    # Cache TTLs in seconds
    STOP_MONITORING_TTL = 60
    VEHICLE_MONITORING_TTL = 30

    def __init__(self):
        """Initialize SIRI service with rate limiting."""
        self.api_key = settings.five_eleven_api_key
        self._last_update: Optional[str] = None
        self._rate_limiter = get_rate_limiter(
            RateLimitConfig(requests_per_hour=settings.rate_limit_requests_per_hour)
        )

    def _fetch_siri(self, url: str, params: dict = None) -> Optional[dict]:
        """Fetch SIRI data from 511.org API.

        Args:
            url: SIRI endpoint URL
            params: Optional query parameters

        Returns:
            Parsed SIRI XML/JSON response or None if fetch fails
        """
        if not self.api_key:
            logger.warning("No API key configured - cannot fetch SIRI data")
            return None

        try:
            full_url = url.format(key=self.api_key)

            def make_request():
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(full_url, params=params)
                    response.raise_for_status()
                    return response

            response = self._rate_limiter.execute(
                make_request,
                headers_callback=lambda h: self._rate_limiter.update_from_response_headers(h)
            )

            # SIRI returns XML by default, but 511.org may support JSON
            content_type = response.headers.get("content-type", "")

            if "xml" in content_type or "text" in content_type:
                # Parse XML response
                return self._parse_siri_xml(response.text)
            else:
                # Try JSON
                try:
                    return response.json()
                except Exception:
                    return self._parse_siri_xml(response.text)

        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching SIRI data: {e}")
            raise NetworkUnavailableError(f"SIRI request timed out: {e}") from e
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching SIRI data: {e}")
            raise NetworkUnavailableError(f"SIRI connection failed: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error fetching SIRI data: {e}")
            return None

    def _parse_siri_xml(self, xml_text: str) -> dict:
        """Parse SIRI XML response into dict.

        Args:
            xml_text: Raw XML response from SIRI endpoint

        Returns:
            Parsed dict representation of SIRI response
        """
        import xml.etree.ElementTree as ET

        try:
            root = ET.fromstring(xml_text)
            return self._siri_xml_to_dict(root)
        except ET.ParseError as e:
            logger.error(f"Failed to parse SIRI XML: {e}")
            return {"error": f"XML parse error: {e}", "raw": xml_text[:500]}

    def _siri_xml_to_dict(self, element) -> dict:
        """Recursively convert SIRI XML element to dict."""
        result = {}

        # Get attributes
        if element.attrib:
            result["@attributes"] = element.attrib

        # Get text content
        if element.text and element.text.strip():
            return element.text.strip()

        # Get child elements
        for child in element:
            child_data = self._siri_xml_to_dict(child)

            if child.tag in result:
                # Multiple children with same tag - make a list
                if not isinstance(result[child.tag], list):
                    result[child.tag] = [result[child.tag]]
                result[child.tag].append(child_data)
            else:
                result[child.tag] = child_data

        return result

    def get_stop_monitoring(
        self,
        stop_id: str,
        maximum_stop_visits: int = 10,
        preview_interval_minutes: int = 60
    ) -> Optional[dict]:
        """Get real-time arrival/departure predictions for a stop.

        Args:
            stop_id: The stop ID to monitor (e.g., "SF" for San Francisco)
            maximum_stop_visits: Maximum number of arrivals to return (default: 10)
            preview_interval_minutes: How far ahead to look (default: 60 minutes)

        Returns:
            Dict containing arrival predictions or None if unavailable
        """
        cache_key = f"siri_stop_{stop_id}_{maximum_stop_visits}"
        cached = cache.get(cache_key, ttl_seconds=self.STOP_MONITORING_TTL)
        if cached:
            return cached

        params = {
            "stopCode": stop_id,
            "maximumStopVisits": maximum_stop_visits,
            "previewInterval": f"PT{preview_interval_minutes}M",
        }

        result = self._fetch_siri(self.STOP_MONITORING_URL, params)

        if result:
            self._last_update = datetime.now(timezone.utc).isoformat()
            cache.set(cache_key, result)

        return result

    def get_vehicle_monitoring(
        self,
        vehicle_id: Optional[str] = None,
        trip_id: Optional[str] = None,
        maximum_vehicles: int = 10
    ) -> Optional[dict]:
        """Get real-time vehicle location information.

        Args:
            vehicle_id: Specific vehicle ID to monitor
            trip_id: Trip ID to monitor (returns the vehicle for that trip)
            maximum_vehicles: Maximum number of vehicles to return (default: 10)

        Returns:
            Dict containing vehicle location data or None if unavailable
        """
        params = {
            "maximumVehicles": maximum_vehicles,
        }

        if vehicle_id:
            params["vehicleRef"] = vehicle_id

        if trip_id:
            params["tripId"] = trip_id

        result = self._fetch_siri(self.VEHICLE_MONITORING_URL, params)

        if result:
            self._last_update = datetime.now(timezone.utc).isoformat()

        return result

    def get_service_at_stops(
        self,
        stop_ids: list[str],
        maximum_stops: int = 20
    ) -> Optional[dict]:
        """Get all services (routes) that serve a list of stops.

        Args:
            stop_ids: List of stop IDs to query
            maximum_stops: Maximum number of stops to return info for

        Returns:
            Dict containing service information for the stops
        """
        cache_key = f"siri_services_{'-'.join(stop_ids[:5])}"
        cached = cache.get(cache_key, ttl_seconds=self.STOP_MONITORING_TTL * 2)
        if cached:
            return cached

        params = {
            "stopCodes": ",".join(stop_ids),
            "maximumStops": maximum_stops,
        }

        result = self._fetch_siri(self.SERVICE_DEPARTURES_URL, params)

        if result:
            cache.set(cache_key, result)

        return result

    def parse_arrivals(self, stop_monitoring_data: dict) -> list[dict]:
        """Parse SIRI StopMonitoring data into a clean arrivals list.

        Extracts key arrival information from raw SIRI response.

        Args:
            stop_monitoring_data: Raw SIRI StopMonitoring response

        Returns:
            List of arrival dicts with key fields normalized
        """
        arrivals = []

        try:
            # Navigate SIRI XML structure
            ns = {
                "siri": "http://www.siri.org.uk/siri",
                "siri2": "http://第二大ity.net/siri",
            }

            # Try to find MonitoredStopVisit elements
            visits = stop_monitoring_data.get("Siri", {})
            if not visits:
                visits = stop_monitoring_data

            # Handle different response structures
            if isinstance(visits, dict):
                service_delivery = visits.get("ServiceDelivery", {})
                if not service_delivery:
                    service_delivery = visits

                stop_monitoring = service_delivery.get("StopMonitoringService", {})
                if not stop_monitoring:
                    stop_monitoring = service_delivery

                monitored_stops = stop_monitoring.get("MonitoredStopVisit", [])
                if not isinstance(monitored_stops, list):
                    monitored_stops = [monitored_stops]

                for visit in monitored_stops:
                    if not isinstance(visit, dict):
                        continue

                    # Extract key fields
                    visit_data = visit.get("MonitoredVehicleVisit", visit)

                    if isinstance(visit_data, dict):
                        monitored_arrival = visit_data.get("MonitoredArrival", {})
                        monitored_call = visit_data.get("MonitoredCall", {})

                        arrival = {
                            "line_ref": self._get_nested(visit_data, "LineRef"),
                            "direction_ref": self._get_nested(visit_data, "DirectionRef"),
                            "published_line_name": self._get_nested(visit_data, "PublishedLineName"),
                            "destination_name": self._get_nested(visit_data, "DestinationName"),
                            "operator_ref": self._get_nested(visit_data, "OperatorRef"),
                            "origin_name": self._get_nested(visit_data, "OriginName"),
                            # Timing info
                            "aimed_arrival_time": self._get_nested(monitored_arrival, "AimedArrivalTime"),
                            "expected_arrival_time": self._get_nested(monitored_arrival, "ExpectedArrivalTime"),
                            "arrival_platform": self._get_nested(monitored_call, "ArrivalPlatformName"),
                            # Stop info
                            "stop_name": self._get_nested(monitored_call, "StopPointName"),
                            "stop_id": self._get_nested(monitored_call, "StopPointRef"),
                            # Vehicle info
                            "vehicle_id": self._get_nested(visit_data, "VehicleRef"),
                            "bearing": self._get_nested(visit_data, "Bearing"),
                        }

                        # Calculate delay if both times present
                        aimed = arrival.get("aimed_arrival_time")
                        expected = arrival.get("expected_arrival_time")
                        if aimed and expected:
                            try:
                                from datetime import datetime
                                a_time = datetime.fromisoformat(aimed.replace("Z", "+00:00"))
                                e_time = datetime.fromisoformat(expected.replace("Z", "+00:00"))
                                delay_seconds = (e_time - a_time).total_seconds()
                                arrival["delay_seconds"] = int(delay_seconds)
                                arrival["delay_minutes"] = int(delay_seconds / 60)
                            except Exception:
                                pass

                        arrivals.append(arrival)

        except Exception as e:
            logger.error(f"Error parsing arrivals: {e}")

        return arrivals

    def _get_nested(self, d: dict, key: str):
        """Safely get nested dict key that might use @attributes or other wrappers."""
        if not isinstance(d, dict):
            return None

        if key in d:
            value = d[key]
            if isinstance(value, dict) and "@attributes" in value:
                return value["@attributes"].get("DataValue", value.get("#text"))
            return value
        return None

    def get_last_update(self) -> Optional[str]:
        """Get timestamp of last SIRI update."""
        return self._last_update


# Singleton instance
siri_service = SIRIService()
