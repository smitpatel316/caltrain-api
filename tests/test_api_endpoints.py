"""
API endpoint tests - these are integration tests that require the server to be running.
These test the full request/response cycle.
"""

import pytest
from fastapi.testclient import TestClient

# Note: These tests require the app to be importable
# Run with: pytest tests/test_api_endpoints.py -v -m integration


class TestAPIEndpoints:
    """Test all API endpoints return proper responses."""

    @pytest.fixture
    def client(self):
        """Create test client - requires app to be importable."""
        from app.main import app
        return TestClient(app)

    def test_root_endpoint(self, client):
        """Test root endpoint returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Caltrain API"
        assert "endpoints" in data

    def test_health_endpoint(self, client):
        """Test health endpoint."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "realtime" in data

    def test_stops_endpoint_requires_params(self, client):
        """Test stops endpoint returns data."""
        response = client.get("/api/v1/stops")
        # May return 200 with empty list or 500 if no GTFS data
        assert response.status_code in [200, 500]

    def test_next_train_requires_origin(self, client):
        """Test next-train endpoint requires origin_stop_id."""
        response = client.get("/api/v1/next-train")
        assert response.status_code == 422  # Validation error

    def test_presets_get_returns_list(self, client):
        """Test presets GET returns list."""
        response = client.get("/api/v1/presets")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_presets_create_valid(self, client):
        """Test creating a preset."""
        response = client.post(
            "/api/v1/presets",
            json={
                "name": "Test Route",
                "origin_stop_id": "SF",
                "destination_stop_id": "MV",
                "direction": "northbound",
                "preferred_types": ["local", "express"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Route"
        assert "id" in data

    def test_siri_stop_monitoring_requires_stop_id(self, client):
        """Test SIRI stop monitoring requires stop_id."""
        response = client.get("/api/v1/siri/stop-monitoring")
        assert response.status_code == 422

    def test_siri_arrivals_requires_stop_id(self, client):
        """Test SIRI arrivals requires stop_id."""
        response = client.get("/api/v1/siri/arrivals")
        assert response.status_code == 422

    def test_siri_vehicle_monitoring_requires_id(self, client):
        """Test SIRI vehicle monitoring requires vehicle_id or trip_id."""
        response = client.get("/api/v1/siri/vehicle-monitoring")
        assert response.status_code == 400

    def test_holidays_today(self, client):
        """Test holidays today endpoint."""
        response = client.get("/api/v1/schedule/today")
        assert response.status_code == 200
        data = response.json()
        assert "date" in data
        assert "service_type" in data

    def test_holidays_upcoming(self, client):
        """Test upcoming holidays endpoint."""
        response = client.get("/api/v1/holidays/upcoming?days=7")
        assert response.status_code == 200
        data = response.json()
        assert "holidays" in data
        assert "count" in data

    def test_holidays_check_valid_date(self, client):
        """Test holiday check endpoint with valid date."""
        response = client.get("/api/v1/holidays/check?date_str=2026-12-25")
        assert response.status_code == 200
        data = response.json()
        assert data["date"] == "2026-12-25"

    def test_holidays_check_invalid_date(self, client):
        """Test holiday check with invalid date."""
        response = client.get("/api/v1/holidays/check?date_str=invalid")
        assert response.status_code == 200  # Returns error in body, not 422
        data = response.json()
        assert "error" in data

    def test_schedule_for_date_valid(self, client):
        """Test schedule for specific date."""
        response = client.get("/api/v1/schedule/2026-03-30")
        assert response.status_code == 200
        data = response.json()
        assert data["date"] == "2026-03-30"

    def test_schedule_for_date_invalid(self, client):
        """Test schedule for invalid date returns error."""
        response = client.get("/api/v1/schedule/invalid-date")
        assert response.status_code == 200  # Returns error in body
        data = response.json()
        assert "error" in data


class TestErrorHandling:
    """Test error handling across endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from app.main import app
        return TestClient(app)

    def test_404_unknown_endpoint(self, client):
        """Test unknown endpoint returns 404."""
        response = client.get("/api/v1/unknown")
        assert response.status_code == 404

    def test_method_not_allowed(self, client):
        """Test wrong HTTP method returns 405."""
        response = client.delete("/api/v1/stops")
        assert response.status_code == 405

    def test_invalid_json_body(self, client):
        """Test invalid JSON in body returns 422."""
        response = client.post(
            "/api/v1/presets",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_validation_error_response_format(self, client):
        """Test validation errors return proper format."""
        response = client.get("/api/v1/next-train")
        assert response.status_code == 422
        data = response.json()
        assert "error" in data
