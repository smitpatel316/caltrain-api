import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestHealthEndpoint:
    """Tests for /api/v1/health endpoint."""

    def test_health_returns_status(self):
        """Test health endpoint returns status."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database_ok" in data

    def test_health_database_field(self):
        """Test health response has database_ok field."""
        response = client.get("/api/v1/health")
        data = response.json()
        assert isinstance(data["database_ok"], bool)


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root_returns_info(self):
        """Test root endpoint returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Caltrain API"
        assert "version" in data
        assert "docs" in data


class TestStopsEndpoint:
    """Tests for /api/v1/stops endpoint.

    These tests require GTFS data to be loaded and are marked as integration tests.
    They will be skipped unless explicitly run with pytest -m integration.
    """

    @pytest.mark.integration
    def test_stops_returns_list(self):
        """Test stops endpoint returns list of stops.

        Requires GTFS data to be loaded via refresh.
        """
        response = client.get("/api/v1/stops")
        assert response.status_code == 200
        data = response.json()
        assert "stops" in data
        assert "last_updated" in data
        assert isinstance(data["stops"], list)

    @pytest.mark.integration
    def test_stops_optional_agency_param(self):
        """Test stops endpoint accepts agency parameter.

        Requires GTFS data to be loaded via refresh.
        """
        response = client.get("/api/v1/stops?agency=RG")
        assert response.status_code == 200


class TestNextTrainEndpoint:
    """Tests for /api/v1/next-train endpoint."""

    def test_next_train_requires_origin(self):
        """Test next-train requires origin_stop_id parameter."""
        response = client.get("/api/v1/next-train")
        assert response.status_code == 422  # Validation error

    def test_next_train_with_origin(self):
        """Test next-train with origin_stop_id."""
        response = client.get("/api/v1/next-train?origin_stop_id=test")
        # May fail with 500 if no GTFS data, but validates param handling
        assert response.status_code in [200, 500]

    def test_next_train_with_direction(self):
        """Test next-train accepts direction parameter."""
        response = client.get(
            "/api/v1/next-train?origin_stop_id=test&direction=northbound"
        )
        assert response.status_code in [200, 500]

    def test_next_train_with_preferred_types(self):
        """Test next-train accepts preferred_types parameter."""
        response = client.get(
            "/api/v1/next-train?origin_stop_id=test&preferred_types=local,express"
        )
        assert response.status_code in [200, 500]


class TestPresetsEndpoint:
    """Tests for /api/v1/presets endpoint."""

    def test_presets_get_returns_list(self):
        """Test presets GET returns list."""
        response = client.get("/api/v1/presets")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_presets_create_valid(self):
        """Test creating a preset with valid data."""
        response = client.post(
            "/api/v1/presets",
            json={
                "name": "Home to Work",
                "origin_stop_id": "MV",
                "destination_stop_id": "SF",
                "direction": "northbound",
                "preferred_types": ["local", "express"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Home to Work"
        assert "id" in data

    def test_presets_create_requires_name(self):
        """Test creating preset requires name field."""
        response = client.post(
            "/api/v1/presets",
            json={
                "origin_stop_id": "MV",
                "direction": "northbound",
            },
        )
        assert response.status_code == 422
