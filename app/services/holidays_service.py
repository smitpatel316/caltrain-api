"""
Holiday service information for Caltrain.

Provides information about holiday service schedules and special service days.
"""

import logging
from datetime import date, datetime
from typing import Optional

from app.config import get_settings
from app.services.cache import cache

settings = get_settings()
logger = logging.getLogger(__name__)


# Known US federal holidays that affect Caltrain service
# Format: (month, day) - holidays that fall on weekends are typically observed on Monday
FEDERAL_HOLIDAYS = [
    (1, 1),    # New Year's Day
    (1, 15),   # MLK Day (3rd Monday of January)
    (2, 15),   # Presidents Day (3rd Monday of February)
    (5, 25),   # Memorial Day (last Monday of May)
    (6, 19),   # Juneteenth
    (7, 4),    # Independence Day
    (9, 7),    # Labor Day (1st Monday of September)
    (10, 12),  # Columbus Day (2nd Monday of October)
    (11, 11),  # Veterans Day
    (11, 26),  # Thanksgiving (4th Thursday of November)
    (12, 25),  # Christmas Day
]


class HolidayService:
    """Service for determining holiday service schedules.

    Caltrain operates reduced service on some holidays and
    may have special schedules for others.
    """

    # Holidays when Caltrain operates weekend/holiday schedule
    HOLIDAY_SERVICE_TYPES = {
        "new_year": "weekend",
        "mlk_day": "weekend",
        "presidents_day": "weekend",
        "memorial_day": "weekend",
        "juneteenth": "weekend",
        "independence_day": "weekend",
        "labor_day": "weekend",
        "columbus_day": "weekend",
        "veterans_day": "weekend",
        "thanksgiving": "special",  # Reduced service
        "christmas": "weekend",
    }

    def __init__(self):
        self._cache_ttl = 86400  # 24 hours

    def get_holiday_name(self, check_date: date) -> Optional[str]:
        """Get the holiday name for a given date if it's a holiday.

        Args:
            check_date: Date to check

        Returns:
            Holiday name or None if not a holiday
        """
        # Check against known holidays
        for name, (month, day) in self._holiday_dates(check_date.year).items():
            if check_date.month == month and check_date.day == day:
                return name

        return None

    def is_holiday(self, check_date: date) -> bool:
        """Check if a date is a recognized holiday.

        Args:
            check_date: Date to check

        Returns:
            True if it's a holiday
        """
        return self.get_holiday_name(check_date) is not None

    def get_service_type(self, check_date: date) -> str:
        """Get the service type for a date.

        Args:
            check_date: Date to check

        Returns:
            Service type: "weekday", "weekend", or "holiday"
        """
        if check_date.weekday() in [5, 6]:  # Saturday or Sunday
            return "weekend"

        holiday_name = self.get_holiday_name(check_date)
        if holiday_name:
            return self.HOLIDAY_SERVICE_TYPES.get(holiday_name, "weekend")

        return "weekday"

    def _holiday_dates(self, year: int) -> dict:
        """Calculate actual holiday dates for a given year.

        Some holidays fall on specific days of the week,
        so we compute the actual date.

        Args:
            year: Year to calculate for

        Returns:
            Dict mapping holiday names to (month, day) tuples
        """
        holidays = {}

        # New Year's Day
        holidays["new_year"] = (1, 1)

        # MLK Day - 3rd Monday of January
        mlk = self._nth_weekday_of_month(year, 1, 0, 3)  # January, Monday, 3rd
        holidays["mlk_day"] = (mlk.month, mlk.day)

        # Presidents Day - 3rd Monday of February
        presidents = self._nth_weekday_of_month(year, 2, 0, 3)
        holidays["presidents_day"] = (presidents.month, presidents.day)

        # Memorial Day - Last Monday of May
        memorial = self._last_weekday_of_month(year, 5, 0)
        holidays["memorial_day"] = (memorial.month, memorial.day)

        # Juneteenth
        holidays["juneteenth"] = (6, 19)

        # Independence Day
        holidays["independence_day"] = (7, 4)

        # Labor Day - 1st Monday of September
        labor = self._nth_weekday_of_month(year, 9, 0, 1)
        holidays["labor_day"] = (labor.month, labor.day)

        # Columbus Day - 2nd Monday of October
        columbus = self._nth_weekday_of_month(year, 10, 0, 2)
        holidays["columbus_day"] = (columbus.month, columbus.day)

        # Veterans Day
        holidays["veterans_day"] = (11, 11)

        # Thanksgiving - 4th Thursday of November
        thanksgiving = self._nth_weekday_of_month(year, 11, 3, 4)
        holidays["thanksgiving"] = (thanksgiving.month, thanksgiving.day)

        # Christmas
        holidays["christmas"] = (12, 25)

        return holidays

    def _nth_weekday_of_month(self, year: int, month: int, weekday: int, n: int) -> date:
        """Find the nth occurrence of a weekday in a month.

        Args:
            year: Year
            month: Month (1-12)
            weekday: Day of week (0=Monday, 6=Sunday)
            n: Which occurrence (1=first, 2=second, etc.)

        Returns:
            Date of the nth weekday
        """
        from datetime import timedelta

        # First day of month
        first_day = date(year, month, 1)

        # Find first occurrence of weekday
        days_ahead = (weekday - first_day.weekday()) % 7
        first_occurrence = first_day + timedelta(days=days_ahead)

        # Nth occurrence
        return first_occurrence + timedelta(weeks=n - 1)

    def _last_weekday_of_month(self, year: int, month: int, weekday: int) -> date:
        """Find the last occurrence of a weekday in a month.

        Args:
            year: Year
            month: Month (1-12)
            weekday: Day of week (0=Monday, 6=Sunday)

        Returns:
            Date of the last occurrence
        """
        from datetime import timedelta

        # First day of next month
        if month == 12:
            first_next_month = date(year + 1, 1, 1)
        else:
            first_next_month = date(year, month + 1, 1)

        # Go back one day
        last_day = first_next_month - timedelta(days=1)

        # Find last occurrence of weekday
        days_back = (last_day.weekday() - weekday) % 7
        return last_day - timedelta(days=days_back)

    def get_upcoming_holidays(self, days: int = 30) -> list[dict]:
        """Get upcoming holidays within the specified number of days.

        Args:
            days: Number of days to look ahead

        Returns:
            List of dicts with holiday information
        """
        from datetime import timedelta

        cache_key = f"holidays_upcoming_{days}"
        cached = cache.get(cache_key, ttl_seconds=self._cache_ttl)
        if cached:
            return cached

        today = date.today()
        holidays = []

        for i in range(days):
            check_date = today + timedelta(days=i)
            holiday_name = self.get_holiday_name(check_date)

            if holiday_name:
                holidays.append({
                    "date": check_date.isoformat(),
                    "name": holiday_name.replace("_", " ").title(),
                    "service_type": self.get_service_type(check_date),
                    "days_until": i,
                })

        cache.set(cache_key, holidays)
        return holidays

    def get_schedule_info(self, check_date: date = None) -> dict:
        """Get complete schedule information for a date.

        Args:
            check_date: Date to check (defaults to today)

        Returns:
            Dict with schedule info
        """
        if check_date is None:
            check_date = date.today()

        holiday_name = self.get_holiday_name(check_date)
        service_type = self.get_service_type(check_date)

        return {
            "date": check_date.isoformat(),
            "day_of_week": check_date.strftime("%A"),
            "is_weekend": check_date.weekday() in [5, 6],
            "is_holiday": holiday_name is not None,
            "holiday_name": holiday_name.replace("_", " ").title() if holiday_name else None,
            "service_type": service_type,
            "schedule": self._get_schedule_description(service_type),
        }

    def _get_schedule_description(self, service_type: str) -> str:
        """Get human-readable schedule description."""
        descriptions = {
            "weekday": "Weekday schedule - full Caltrain service",
            "weekend": "Weekend/Holiday schedule - reduced stops",
            "special": "Special schedule - check specific train times",
        }
        return descriptions.get(service_type, "Unknown schedule")


# Singleton instance
holiday_service = HolidayService()
