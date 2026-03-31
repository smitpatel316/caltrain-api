"""
Unit tests for geofence helper utilities.
"""

import pytest
from app.utils.geofence_helpers import (
    haversine_distance,
    is_within_geofence,
    find_nearest_stop,
)


class TestHaversineDistance:
    """Tests for haversine_distance function."""

    def test_same_point_returns_zero(self):
        """Test that distance to same point is zero."""
        distance = haversine_distance(37.7749, -122.4194, 37.7749, -122.4194)
        assert distance == pytest.approx(0.0, abs=0.001)

    def test_known_distance_sf_to_la(self):
        """Test distance from SF to LA (approximately 347 miles straight line)."""
        # San Francisco: 37.7749, -122.4194
        # Los Angeles: 34.0522, -118.2437
        distance = haversine_distance(37.7749, -122.4194, 34.0522, -118.2437)
        assert distance == pytest.approx(347, abs=5)  # Within 5 miles (straight line ~347mi)

    def test_known_distance_sf_to_oakland(self):
        """Test distance from SF to Oakland (approximately 8 miles)."""
        # San Francisco: 37.7749, -122.4194
        # Oakland: 37.8044, -122.2712
        distance = haversine_distance(37.7749, -122.4194, 37.8044, -122.2712)
        assert distance == pytest.approx(8.3, abs=1)  # Within 1 mile (actual ~8.3)

    def test_symmetry(self):
        """Test that distance A to B equals B to A."""
        dist1 = haversine_distance(37.7749, -122.4194, 34.0522, -118.2437)
        dist2 = haversine_distance(34.0522, -118.2437, 37.7749, -122.4194)
        assert dist1 == pytest.approx(dist2, abs=0.001)


class TestIsWithinGeofence:
    """Tests for is_within_geofence function."""

    def test_same_location_within_geofence(self):
        """Test same location is within default radius."""
        assert is_within_geofence(37.7749, -122.4194, 37.7749, -122.4194) is True

    def test_close_location_within_geofence(self):
        """Test nearby location within 0.25 mile default."""
        # Points very close together - about 0.1 miles apart
        # 37.7749, -122.4194 (SF downtown)
        # 37.7749, -122.4184 (about 300 feet east - well within 0.25 mi)
        lat1, lon1 = 37.7749, -122.4194
        lat2, lon2 = 37.7759, -122.4184  # Very close - well within 0.25 miles
        assert is_within_geofence(lat1, lon1, lat2, lon2) is True

    def test_far_location_outside_geofence(self):
        """Test distant location outside geofence."""
        # SF to LA is ~370 miles - well outside 0.25 mile radius
        assert is_within_geofence(37.7749, -122.4194, 34.0522, -118.2437) is False

    def test_custom_radius(self):
        """Test custom geofence radius."""
        # These points are about 0.8 miles apart
        lat1, lon1 = 37.7749, -122.4194
        lat2, lon2 = 37.7859, -122.4094

        assert is_within_geofence(lat1, lon1, lat2, lon2, radius_miles=0.5) is False
        assert is_within_geofence(lat1, lon1, lat2, lon2, radius_miles=1.0) is True


class TestFindNearestStop:
    """Tests for find_nearest_stop function."""

    def test_empty_list_returns_none(self):
        """Test with empty stops list."""
        stop_id, distance = find_nearest_stop(37.7749, -122.4194, [])
        assert stop_id is None
        assert distance == float("inf")

    def test_single_stop(self):
        """Test with single stop in list."""
        stops = [
            {"stop_id": "SFO", "stop_lat": 37.6213, "stop_lon": -122.3790}
        ]
        stop_id, distance = find_nearest_stop(37.6213, -122.3790, stops)
        assert stop_id == "SFO"
        assert distance == pytest.approx(0.0, abs=0.001)

    def test_multiple_stops_finds_nearest(self):
        """Test that nearest stop is found correctly."""
        stops = [
            {"stop_id": "SF", "stop_lat": 37.7749, "stop_lon": -122.4194},  # San Francisco
            {"stop_id": "MV", "stop_lat": 37.4419, "stop_lon": -122.1430},   # Mountain View
            {"stop_id": "SJ", "stop_lat": 37.3382, "stop_lon": -121.8863},  # San Jose
        ]
        # User near San Francisco
        stop_id, distance = find_nearest_stop(37.78, -122.42, stops)
        assert stop_id == "SF"

        # User near San Jose
        stop_id, distance = find_nearest_stop(37.34, -121.89, stops)
        assert stop_id == "SJ"

        # User near Mountain View
        stop_id, distance = find_nearest_stop(37.44, -122.14, stops)
        assert stop_id == "MV"

    def test_missing_coordinates(self):
        """Test handling of stops with missing coordinates."""
        stops = [
            {"stop_id": "MISSING", "stop_lat": None, "stop_lon": None},
            {"stop_id": "SFO", "stop_lat": 37.6213, "stop_lon": -122.3790},
        ]
        stop_id, distance = find_nearest_stop(37.7749, -122.4194, stops)
        # Should return the stop with valid coordinates
        assert stop_id == "SFO"
        assert distance != float("inf")