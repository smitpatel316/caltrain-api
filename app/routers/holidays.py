"""
Holidays router for schedule information.

Provides holiday service schedule information.
"""

from datetime import date
from typing import Optional
import re

from fastapi import APIRouter, Query, Path

from app.services.holidays_service import holiday_service

router = APIRouter(prefix="/api/v1", tags=["holidays"])


# NOTE: /schedule/today must be defined BEFORE /schedule/{date_str}
# to prevent "today" from being matched as a date parameter

@router.get("/schedule/today")
async def get_todays_schedule():
    """Get today's schedule information."""
    schedule_info = holiday_service.get_schedule_info()
    return schedule_info


@router.get("/schedule/{date_str}")
async def get_schedule_for_date(
    date_str: str = Path(
        ...,
        description="Date in YYYY-MM-DD format",
        # Regex to match only date-like patterns, not "today" or other words
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
):
    """Get schedule information for a specific date.

    Returns the service type (weekday/weekend/holiday) and
    description of the schedule.
    """
    try:
        check_date = date.fromisoformat(date_str)
        schedule_info = holiday_service.get_schedule_info(check_date)
        return schedule_info

    except ValueError:
        return {
            "error": "Invalid date format",
            "message": "Use YYYY-MM-DD format (e.g., 2026-03-30)",
        }


@router.get("/holidays/upcoming")
async def get_upcoming_holidays(
    days: int = Query(30, ge=1, le=365, description="Number of days to look ahead"),
):
    """Get list of upcoming holidays.

    Returns holidays that fall within the specified number of days.
    """
    holidays = holiday_service.get_upcoming_holidays(days)
    return {
        "days_ahead": days,
        "holidays": holidays,
        "count": len(holidays),
    }


@router.get("/holidays/check")
async def check_if_holiday(
    date_str: str = Query(..., description="Date in YYYY-MM-DD format"),
):
    """Check if a specific date is a holiday.

    Returns holiday name if it's a holiday, null otherwise.
    """
    try:
        check_date = date.fromisoformat(date_str)
        holiday_name = holiday_service.get_holiday_name(check_date)

        return {
            "date": date_str,
            "is_holiday": holiday_name is not None,
            "holiday_name": holiday_name.replace("_", " ").title() if holiday_name else None,
            "service_type": holiday_service.get_service_type(check_date),
        }

    except ValueError:
        return {
            "error": "Invalid date format",
            "message": "Use YYYY-MM-DD format (e.g., 2026-03-30)",
        }
