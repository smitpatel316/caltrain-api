import pytest
from datetime import datetime, timezone
from app.services.next_train import NextTrainService
from app.services.gtfs_rt import gtfs_rt


class TestNextTrainService:
    """Tests for NextTrainService."""

    def test_parse_gtfs_time_standard(self):
        """Test parsing standard GTFS time format."""
        service = NextTrainService()
        result = service._parse_gtfs_time("08:15:00", "20260330")
        assert result.hour == 8
        assert result.minute == 15
        assert result.second == 0

    def test_parse_gtfs_time_past_midnight(self):
        """Test parsing GTFS time past midnight (e.g., 25:30:00)."""
        service = NextTrainService()
        result = service._parse_gtfs_time("25:30:00", "20260330")
        assert result.day == 31  # Next day
        assert result.hour == 1
        assert result.minute == 30

    def test_classify_train_type_local(self):
        """Test local train classification."""
        train_type, color = gtfs_rt.classify_train_type(
            trip_headsign="San Francisco Local",
            route_short_name="101",
        )
        assert train_type == "local"
        assert color == "#808080"

    def test_classify_train_type_limited(self):
        """Test limited train classification."""
        train_type, color = gtfs_rt.classify_train_type(
            trip_headsign="Limited",
            route_short_name="401",
        )
        assert train_type == "limited"
        assert color == "#FFD700"

    def test_classify_train_type_express(self):
        """Test express train classification."""
        train_type, color = gtfs_rt.classify_train_type(
            trip_headsign="Express",
            route_short_name="501",
        )
        assert train_type == "express"
        assert color == "#FF0000"


class TestGTFSRTService:
    """Tests for GTFSRTService."""

    def test_classify_train_type_weekend(self):
        """Test weekend train classification."""
        train_type, color = gtfs_rt.classify_train_type(
            trip_headsign="Weekend Service",
            route_short_name="601",
        )
        assert train_type == "weekend"
        assert color == "#00FF00"

    def test_classify_train_type_south_county(self):
        """Test south county (Gilroy) train classification."""
        train_type, color = gtfs_rt.classify_train_type(
            trip_headsign="Gilroy",
            route_short_name="8",
        )
        assert train_type == "south_county"
        assert color == "#FFA500"

    def test_classify_train_type_unknown_defaults_local(self):
        """Test unknown train type defaults to local."""
        train_type, color = gtfs_rt.classify_train_type(
            trip_headsign="Special",
            route_short_name="999",
        )
        assert train_type == "local"
        assert color == "#808080"
