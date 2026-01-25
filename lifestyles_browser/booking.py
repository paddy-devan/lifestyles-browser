import os
import json
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

import requests
import bs4
from dotenv import load_dotenv

load_dotenv()

EMAIL = os.environ.get("lifestyles_email")
PASSWORD = os.environ.get("lifestyles_password")

BASE_URL = "https://liverpoollifestyles.legendonlineservices.co.uk"
LOGIN_URL = f"{BASE_URL}/enterprise/account/login"


def _ordinal(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _human_date(d: dt.date) -> str:
    return f"{d.strftime('%A')}, {d.strftime('%B')} {_ordinal(d.day)} {d.year}"


def _parse_dt(value: str) -> dt.datetime:
    # Schedule data is like "2025-07-09T20:00:00"
    return dt.datetime.fromisoformat(value)


def login_session() -> requests.Session:
    if not EMAIL or not PASSWORD:
        raise RuntimeError("Missing lifestyles_email or lifestyles_password in environment.")

    s = requests.Session()
    html = s.get(LOGIN_URL).text
    token = (
        bs4.BeautifulSoup(html, "html.parser")
        .find("input", attrs={"name": "__RequestVerificationToken"})["value"]
    )

    payload = {
        "Email": EMAIL,
        "Password": PASSWORD,
        "__RequestVerificationToken": token,
    }
    s.post(LOGIN_URL, data=payload, allow_redirects=True)
    return s


def list_activities(s: requests.Session) -> List[Dict[str, Any]]:
    locations = s.get(f"{BASE_URL}/enterprise/filteredlocationhierarchy").json()
    activities: List[Dict[str, Any]] = []

    for loc in locations[0]["Children"]:
        loc_id = loc["Id"]
        categories = s.get(
            f"{BASE_URL}/enterprise/Bookings/ActivitySubTypeCategories?LocationIds={loc_id}"
        ).json()
        for cat in categories:
            acts = s.get(
                f"{BASE_URL}/enterprise/Bookings/ActivitySubTypes"
                f"?ResourceSubTypeCategoryId={cat['ResourceSubTypeCategoryId']}"
                f"&LocationIds={loc_id}"
            ).json()
            for a in acts:
                activities.append(
                    {
                        "ActivityId": a.get("ResourceSubTypeId"),
                        "ActivityName": a.get("Name"),
                        "LocationId": loc_id,
                        "LocationName": loc.get("Name"),
                        "CategoryId": cat.get("ResourceSubTypeCategoryId"),
                        "CategoryName": cat.get("Name"),
                    }
                )

    activities.sort(key=lambda x: (x["ActivityName"] or "", x["ActivityId"] or 0))
    return activities


def fetch_slots(
    s: requests.Session,
    start_date: dt.date,
    days: int = 1,
    activity_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    start_dt = start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_dt = (start_date + dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    schedules_all: List[Dict[str, Any]] = []
    locations = s.get(f"{BASE_URL}/enterprise/filteredlocationhierarchy").json()

    for loc in locations[0]["Children"]:
        loc_id = loc["Id"]
        booking_facility_id = s.get(
            f"{BASE_URL}/enterprise/FacilityLocation?request={loc_id}"
        ).json()[0]
        categories = s.get(
            f"{BASE_URL}/enterprise/Bookings/ActivitySubTypeCategories?LocationIds={loc_id}"
        ).json()
        for cat in categories:
            activities = s.get(
                f"{BASE_URL}/enterprise/Bookings/ActivitySubTypes"
                f"?ResourceSubTypeCategoryId={cat['ResourceSubTypeCategoryId']}"
                f"&LocationIds={loc_id}"
            ).json()
            for a in activities:
                if activity_id and a.get("ResourceSubTypeId") != activity_id:
                    continue
                schedules = s.get(
                    f"{BASE_URL}/enterprise/BookingsCentre/SportsHallTimeTable"
                    f"?Activities={a['ResourceSubTypeId']}"
                    f"&BookingFacilities={booking_facility_id}"
                    f"&Start={start_dt}"
                    f"&End={end_dt}"
                ).json()
                rows = schedules["SportsHallActivitySnapshots"][0]["SportsHallTimetableRows"]
                schedules_all.extend(rows)

    return schedules_all


def _select_resource_location(resp_json: Any) -> Tuple[Optional[int], Optional[str]]:
    """
    Attempt to pick the first available resource (court/sector) from response.
    Returns (resource_id, resource_name). If not found, returns (None, None).
    """
    # Common shapes seen in similar APIs: list of objects or dict with list.
    candidates: List[Dict[str, Any]] = []

    if isinstance(resp_json, list):
        candidates = resp_json
    elif isinstance(resp_json, dict):
        for key in ("ResourceLocations", "Resources", "Locations", "Data"):
            if isinstance(resp_json.get(key), list):
                candidates = resp_json[key]
                break

    for c in candidates:
        # Prefer available resources if an availability flag exists.
        if "AvailableSlots" in c and c["AvailableSlots"] <= 0:
            continue
        rid = c.get("Id") or c.get("ResourceLocationId") or c.get("LocationId")
        name = c.get("Name") or c.get("ResourceLocationName") or c.get("LocationName")
        if rid or name:
            return rid, name

    return None, None


def get_resource_location(
    s: requests.Session,
    slot: Dict[str, Any],
) -> Tuple[Optional[int], Optional[str], Any]:
    payload = {
        "models": [
            {
                "SlotId": slot["SlotId"],
                "FacilityId": slot["FacilityId"],
                "ActivityId": slot["ActivityId"],
                "StartTime": slot["StartTime"].replace("T", " ").replace("Z", ""),
                "Duration": slot["Duration"],
            }
        ]
    }
    resp = s.post(
        f"{BASE_URL}/enterprise/BookingsCentre/GetResourceLocation",
        json=payload,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    resp.raise_for_status()
    data = resp.json()
    resource_id, resource_name = _select_resource_location(data)
    return resource_id, resource_name, data


def book_slot(
    s: requests.Session,
    slot: Dict[str, Any],
    resource_id: Optional[int],
    resource_name: Optional[str],
    dry_run: bool = True,
) -> Dict[str, Any]:
    start_dt = _parse_dt(slot["StartTime"])
    params = {
        "ActivityId": slot["ActivityId"],
        "ActivityName": slot.get("ActivityName"),
        "ProductId": slot["ProductId"],
        "Date": _human_date(start_dt.date()),
        "StartTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "Time": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "MultiLocation": "false",
        "Duration": slot["Duration"],
        "FacilityId": slot["FacilityId"],
        "FacilityName": slot.get("FacilityName"),
        "AvailableSlots": slot.get("AvailableSlots", 1),
        "ResourceLocationSelectionEnabled": str(
            slot.get("ResourceLocationSelectionEnabled", False)
        ).lower(),
        "Locations[0][SlotId]": slot["SlotId"],
        "Locations[0][FacilityId]": slot["FacilityId"],
        "Locations[0][FacilityName]": slot.get("FacilityName"),
        "Locations[0][ActivityId]": slot["ActivityId"],
        "Locations[0][AvailableSlots]": slot.get("AvailableSlots", 1),
        "Locations[0][StartTime]": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "Locations[0][ActivityName]": slot.get("ActivityName"),
        "Locations[0][ProductId]": slot["ProductId"],
        "Locations[0][Duration]": slot["Duration"],
        "Locations[0][ResourceLocationSelectionEnabled]": str(
            slot.get("ResourceLocationSelectionEnabled", False)
        ).lower(),
        "AddedToBasket": "false",
        "Text": "1 Slots",
        "SlotId": slot["SlotId"],
    }

    if resource_id is not None:
        params["SelectedCourts"] = resource_id
    if resource_name is not None:
        params["ResourceLocation"] = resource_name

    if dry_run:
        return {
            "dry_run": True,
            "book_url": f"{BASE_URL}/enterprise/BookingsCentre/BookSportsHallSlot",
            "params": params,
        }

    book_resp = s.get(
        f"{BASE_URL}/enterprise/BookingsCentre/BookSportsHallSlot",
        params=params,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    book_resp.raise_for_status()

    # Keep basket alive (optional, but matches observed flow)
    s.put(
        f"{BASE_URL}/enterprise/universalbasket/updatebasketexpiry",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    # Confirm booking in basket
    confirm = s.post(
        f"{BASE_URL}/enterprise/cart/confirmbasket",
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json",
        },
        data=json.dumps({}),
    )
    confirm.raise_for_status()

    return {"dry_run": False, "book_response": book_resp.text, "confirm_status": confirm.status_code}


def find_and_book(
    activity_id: int,
    days_ahead: int,
    window_start: str,
    window_end: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    s = login_session()

    date = dt.date.today() + dt.timedelta(days=days_ahead)
    start_time = dt.time.fromisoformat(window_start)
    end_time = dt.time.fromisoformat(window_end)

    # If window crosses midnight, fetch two days and adjust end date.
    window_start_dt = dt.datetime.combine(date, start_time)
    if end_time <= start_time:
        window_end_dt = dt.datetime.combine(date + dt.timedelta(days=1), end_time)
        days = 2
    else:
        window_end_dt = dt.datetime.combine(date, end_time)
        days = 1

    slots = fetch_slots(s, date, days=days, activity_id=activity_id)
    candidates = []
    for slot in slots:
        if slot.get("ActivityId") != activity_id:
            continue
        if slot.get("AvailableSlots", 0) <= 0:
            continue
        slot_dt = _parse_dt(slot["StartTime"])
        if window_start_dt <= slot_dt <= window_end_dt:
            candidates.append(slot)

    if not candidates:
        return {"booked": False, "reason": "No available slots in window"}

    candidates.sort(key=lambda x: _parse_dt(x["StartTime"]))
    chosen = candidates[0]

    resource_id, resource_name, resource_raw = (None, None, None)
    if chosen.get("ResourceLocationSelectionEnabled"):
        resource_id, resource_name, resource_raw = get_resource_location(s, chosen)

    booking_result = book_slot(
        s,
        chosen,
        resource_id=resource_id,
        resource_name=resource_name,
        dry_run=dry_run,
    )

    return {
        "booked": not dry_run,
        "dry_run": dry_run,
        "slot": chosen,
        "resource": {"id": resource_id, "name": resource_name},
        "resource_raw": resource_raw,
        "booking": booking_result,
        "target_date": date.isoformat(),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Find and book the earliest slot in a time window.")
    parser.add_argument("--list-activities", action="store_true")
    parser.add_argument("--activity-id", type=int)
    parser.add_argument("--days-ahead", type=int, help="Days ahead from today")
    parser.add_argument("--window-start", type=str, help="HH:MM (24h)")
    parser.add_argument("--window-end", type=str, help="HH:MM (24h)")
    parser.add_argument("--dry-run", action="store_true", default=False)

    args = parser.parse_args()

    s = login_session()
    if args.list_activities:
        acts = list_activities(s)
        print(json.dumps(acts, indent=2))
    else:
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
        )
        print(json.dumps(result, indent=2))
