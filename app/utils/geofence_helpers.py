from math import radians, sin, cos, sqrt, atan2
from typing import Tuple


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in miles."""
    R = 3959  # Earth's radius in miles

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


def is_within_geofence(
    user_lat: float,
    user_lon: float,
    stop_lat: float,
    stop_lon: float,
    radius_miles: float = 0.25,
) -> bool:
    """Check if user is within geofence radius of a stop."""
    distance = haversine_distance(user_lat, user_lon, stop_lat, stop_lon)
    return distance <= radius_miles


def find_nearest_stop(
    user_lat: float, user_lon: float, stops: list[dict]
) -> Tuple[str, float]:
    """Find nearest stop to user location. Returns (stop_id, distance_miles).

    Args:
        user_lat: User's latitude
        user_lon: User's longitude
        stops: List of stop dicts with 'stop_id', 'stop_lat', 'stop_lon' keys

    Returns:
        Tuple of (stop_id, distance_miles) for nearest stop, or (None, inf) if no valid stops
    """
    nearest_id = None
    min_distance = float("inf")

    for stop in stops:
        stop_lat = stop.get("stop_lat")
        stop_lon = stop.get("stop_lon")

        # Skip stops with missing or invalid coordinates
        if stop_lat is None or stop_lon is None:
            continue

        distance = haversine_distance(user_lat, user_lon, stop_lat, stop_lon)
        if distance < min_distance:
            min_distance = distance
            nearest_id = stop.get("stop_id")

    return nearest_id, min_distance
