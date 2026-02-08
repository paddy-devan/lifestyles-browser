import datetime as dt
from typing import Any, Dict


def _pick_location_id(date: dt.date, odd_week_location_id: int, even_week_location_id: int) -> int:
    week_number = date.isocalendar().week
    return odd_week_location_id if (week_number % 2) == 1 else even_week_location_id


def badminton_club_booking(
    window_start: str,
    window_end: str,
    days_ahead: int = 7,
    dry_run: bool = False,
) -> Dict[str, Any]:
    from .booking import find_and_book

    target_date = dt.date.today() + dt.timedelta(days=days_ahead)
    location_id = _pick_location_id(target_date, odd_week_location_id=144, even_week_location_id=3)
    return find_and_book(
        activity_id=254,
        days_ahead=days_ahead,
        window_start=window_start,
        window_end=window_end,
        dry_run=dry_run,
        location_id=location_id,
    )