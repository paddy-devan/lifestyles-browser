import argparse
import json

from .booking import find_and_book, list_activities, login_session
from .booking_workflows import badminton_club_booking


def main() -> None:
    parser = argparse.ArgumentParser(description="Find and book the earliest slot in a time window.")
    parser.add_argument("--badminton-club-booking", action="store_true")
    parser.add_argument("--list-activities", action="store_true")
    parser.add_argument("--activity-id", type=int)
    parser.add_argument("--days-ahead", type=int, help="Days ahead from today")
    parser.add_argument("--window-start", type=str, help="HH:MM (24h)")
    parser.add_argument("--window-end", type=str, help="HH:MM (24h)")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--location-id", type=int)

    args = parser.parse_args()

    s = login_session()
    if args.list_activities:
        acts = list_activities(s)
        print(json.dumps(acts, indent=2))
        return

    if args.badminton_club_booking:
        if not (args.window_start and args.window_end):
            raise SystemExit("Missing required arguments for badminton club booking.")
        result = badminton_club_booking(
            window_start=args.window_start,
            window_end=args.window_end,
            days_ahead=args.days_ahead or 7,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return

    if not (
        args.activity_id
        and args.days_ahead is not None
        and args.window_start
        and args.window_end
    ):
        raise SystemExit("Missing required arguments for booking flow.")

    result = find_and_book(
        activity_id=args.activity_id,
        days_ahead=args.days_ahead,
        window_start=args.window_start,
        window_end=args.window_end,
        dry_run=args.dry_run,
        location_id=args.location_id,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
