import logging
from datetime import date, timedelta

import httpx

from bot.db import save_oura_data

logger = logging.getLogger(__name__)

OURA_BASE = "https://api.ouraring.com/v2/usercollection"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _fetch_endpoint(token: str, endpoint: str, day: str) -> list[dict]:
    url = f"{OURA_BASE}/{endpoint}"
    resp = httpx.get(url, headers=_headers(token), params={"start_date": day, "end_date": day})
    resp.raise_for_status()
    return resp.json().get("data", [])


def fetch_oura_day(token: str, day: str) -> dict:
    """Fetch sleep, readiness, and activity for a single day. Returns raw API objects."""
    sleep_list = _fetch_endpoint(token, "sleep", day)
    # Filter for 'long_sleep' type (the main sleep period, not naps)
    sleep = next((s for s in sleep_list if s.get("type") == "long_sleep"), sleep_list[0] if sleep_list else None)

    readiness_list = _fetch_endpoint(token, "daily_readiness", day)
    readiness = readiness_list[0] if readiness_list else None

    activity_list = _fetch_endpoint(token, "daily_activity", day)
    activity = activity_list[0] if activity_list else None

    return {"sleep": sleep, "readiness": readiness, "activity": activity}


def fetch_and_store(token: str, db_path: str, day: str) -> dict:
    """Fetch a single day from Oura and save to DB. Returns the raw data."""
    data = fetch_oura_day(token, day)
    save_oura_data(db_path, day, data["sleep"], data["readiness"], data["activity"])
    logger.info(f"Stored Oura data for {day}")
    return data


def backfill(token: str, db_path: str, start: str, end: str) -> int:
    """Fetch and store Oura data for a date range. Returns count of days stored."""
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    count = 0
    current = start_date
    while current <= end_date:
        day_str = current.isoformat()
        try:
            fetch_and_store(token, db_path, day_str)
            count += 1
        except httpx.HTTPStatusError as e:
            logger.warning(f"Failed to fetch {day_str}: {e}")
        except Exception as e:
            logger.warning(f"Error for {day_str}: {e}")
        current += timedelta(days=1)
    return count
