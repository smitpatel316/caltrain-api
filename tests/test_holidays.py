"""
Unit tests for holiday service.
"""

from datetime import date

import pytest

from app.services.holidays_service import HolidayService


class TestHolidayService:
    """Tests for HolidayService."""

    def setup_method(self):
        """Create holiday service instance."""
        self.service = HolidayService()

    def test_is_holiday_christmas(self):
        """Test Christmas is recognized as holiday."""
        christmas = date(2026, 12, 25)
        assert self.service.is_holiday(christmas) is True
        assert self.service.get_holiday_name(christmas) == "christmas"

    def test_is_holiday_independence_day(self):
        """Test Independence Day is recognized."""
        july_4 = date(2026, 7, 4)
        assert self.service.is_holiday(july_4) is True
        assert self.service.get_holiday_name(july_4) == "independence_day"

    def test_is_not_holiday_regular_day(self):
        """Test regular days are not holidays."""
        regular_day = date(2026, 3, 30)
        assert self.service.is_holiday(regular_day) is False
        assert self.service.get_holiday_name(regular_day) is None

    def test_is_not_holiday_monday(self):
        """Test regular Monday is not a holiday."""
        # March 30, 2026 is a Monday but not a holiday
        monday = date(2026, 3, 30)
        assert self.service.is_holiday(monday) is False

    def test_get_service_type_weekday(self):
        """Test weekday service type for regular weekdays."""
        # March 30, 2026 is a Monday - should be weekday service
        monday = date(2026, 3, 30)
        assert self.service.get_service_type(monday) == "weekday"

    def test_get_service_type_weekend(self):
        """Test weekend service type for weekends."""
        saturday = date(2026, 3, 28)
        sunday = date(2026, 3, 29)

        assert self.service.get_service_type(saturday) == "weekend"
        assert self.service.get_service_type(sunday) == "weekend"

    def test_get_service_type_holiday(self):
        """Test holiday service type for holidays."""
        christmas = date(2026, 12, 25)
        # Christmas is on a Friday - should be weekend/holiday service
        assert self.service.get_service_type(christmas) == "weekend"

    def test_get_schedule_info_weekday(self):
        """Test schedule info for weekday."""
        monday = date(2026, 3, 30)
        info = self.service.get_schedule_info(monday)

        assert info["is_weekend"] is False
        assert info["is_holiday"] is False
        assert info["service_type"] == "weekday"

    def test_get_schedule_info_weekend(self):
        """Test schedule info for weekend."""
        saturday = date(2026, 3, 28)
        info = self.service.get_schedule_info(saturday)

        assert info["is_weekend"] is True
        assert info["is_holiday"] is False
        assert info["service_type"] == "weekend"

    def test_get_schedule_info_holiday(self):
        """Test schedule info for holiday."""
        christmas = date(2026, 12, 25)
        info = self.service.get_schedule_info(christmas)

        assert info["is_weekend"] is False
        assert info["is_holiday"] is True
        assert "Christmas" in info["holiday_name"]
        assert info["service_type"] == "weekend"

    def test_get_upcoming_holidays(self):
        """Test getting upcoming holidays."""
        holidays = self.service.get_upcoming_holidays(days=30)

        # March 30 is within 30 days, but there are no holidays
        assert isinstance(holidays, list)

    def test_labor_day_2026(self):
        """Test Labor Day date calculation."""
        # Labor Day 2026 is September 7
        labor_day = date(2026, 9, 7)
        assert self.service.is_holiday(labor_day) is True
        assert self.service.get_holiday_name(labor_day) == "labor_day"

    def test_thanksgiving_2026(self):
        """Test Thanksgiving date calculation."""
        # Thanksgiving 2026 is November 26
        thanksgiving = date(2026, 11, 26)
        assert self.service.is_holiday(thanksgiving) is True
        assert self.service.get_holiday_name(thanksgiving) == "thanksgiving"
        # Thanksgiving has special (reduced) service
        assert self.service.get_service_type(thanksgiving) == "special"

    def test_memorial_day_2026(self):
        """Test Memorial Day date calculation."""
        # Memorial Day 2026 is May 25
        memorial_day = date(2026, 5, 25)
        assert self.service.is_holiday(memorial_day) is True
        assert self.service.get_holiday_name(memorial_day) == "memorial_day"

    def test_juneteenth_2026(self):
        """Test Juneteenth is recognized."""
        juneteenth = date(2026, 6, 19)
        assert self.service.is_holiday(juneteenth) is True
        assert self.service.get_holiday_name(juneteenth) == "juneteenth"

    def test_veterans_day_2026(self):
        """Test Veterans Day is recognized."""
        veterans_day = date(2026, 11, 11)
        assert self.service.is_holiday(veterans_day) is True
        assert self.service.get_holiday_name(veterans_day) == "veterans_day"

    def test_new_years_day_2027(self):
        """Test New Year's Day is recognized."""
        new_year = date(2027, 1, 1)
        assert self.service.is_holiday(new_year) is True
        assert self.service.get_holiday_name(new_year) == "new_year"

    def test_get_schedule_description(self):
        """Test schedule description is human readable."""
        weekday_desc = self.service._get_schedule_description("weekday")
        assert "Weekday" in weekday_desc

        weekend_desc = self.service._get_schedule_description("weekend")
        assert "Weekend" in weekend_desc or "Holiday" in weekend_desc

        special_desc = self.service._get_schedule_description("special")
        assert "Special" in special_desc


class TestHolidayDates:
    """Tests for specific holiday date calculations."""

    def setup_method(self):
        """Create holiday service instance."""
        self.service = HolidayService()

    def test_mlk_day_2026(self):
        """Test MLK Day 2026 falls on January 19."""
        # MLK Day 2026: January 19 (3rd Monday)
        assert self.service.get_holiday_name(date(2026, 1, 19)) == "mlk_day"

    def test_presidents_day_2026(self):
        """Test Presidents Day 2026 falls on February 16."""
        # Presidents Day 2026: February 16 (3rd Monday)
        assert self.service.get_holiday_name(date(2026, 2, 16)) == "presidents_day"

    def test_columbus_day_2026(self):
        """Test Columbus Day 2026 falls on October 12."""
        # Columbus Day 2026: October 12 (2nd Monday)
        assert self.service.get_holiday_name(date(2026, 10, 12)) == "columbus_day"

    def test_labor_day_2026(self):
        """Test Labor Day 2026 falls on September 7."""
        assert self.service.get_holiday_name(date(2026, 9, 7)) == "labor_day"

    def test_memorial_day_2026(self):
        """Test Memorial Day 2026 falls on May 25."""
        assert self.service.get_holiday_name(date(2026, 5, 25)) == "memorial_day"