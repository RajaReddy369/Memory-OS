"""
MemoryOS Time-Aware Temporal Query Parser.
Parses natural language temporal expressions into Unix timestamp intervals
and cleans the search query so keywords aren't diluted by temporal words.
"""

from datetime import datetime, timedelta, time as dt_time
import re
from typing import Optional, Tuple


WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def parse_temporal_query(query: str, reference_time: Optional[datetime] = None) -> Tuple[str, Optional[float], Optional[float]]:
    """
    Parse a query string for natural language time constraints.
    Returns:
        (clean_query, start_timestamp, end_timestamp)
    """
    if not query:
        return "", None, None

    now = reference_time or datetime.now()
    today_start = datetime.combine(now.date(), dt_time.min)
    today_end = datetime.combine(now.date(), dt_time.max)
    yesterday_date = now.date() - timedelta(days=1)
    yesterday_start = datetime.combine(yesterday_date, dt_time.min)
    yesterday_end = datetime.combine(yesterday_date, dt_time.max)

    start_ts: Optional[float] = None
    end_ts: Optional[float] = None
    clean_query = query

    # Patterns mapped to (regex, handler)
    # 1. "yesterday afternoon" (12:00 to 18:00)
    if re.search(r"\byesterday\s+afternoon\b", clean_query, re.IGNORECASE):
        start_ts = datetime.combine(yesterday_date, dt_time(12, 0)).timestamp()
        end_ts = datetime.combine(yesterday_date, dt_time(18, 0)).timestamp()
        clean_query = re.sub(r"\byesterday\s+afternoon\b", "", clean_query, flags=re.IGNORECASE)

    # 2. "yesterday morning" (06:00 to 12:00)
    elif re.search(r"\byesterday\s+morning\b", clean_query, re.IGNORECASE):
        start_ts = datetime.combine(yesterday_date, dt_time(6, 0)).timestamp()
        end_ts = datetime.combine(yesterday_date, dt_time(12, 0)).timestamp()
        clean_query = re.sub(r"\byesterday\s+morning\b", "", clean_query, flags=re.IGNORECASE)

    # 3. "yesterday evening" or "yesterday night" (18:00 to 23:59:59)
    elif re.search(r"\byesterday\s+(evening|night)\b", clean_query, re.IGNORECASE):
        start_ts = datetime.combine(yesterday_date, dt_time(18, 0)).timestamp()
        end_ts = yesterday_end.timestamp()
        clean_query = re.sub(r"\byesterday\s+(evening|night)\b", "", clean_query, flags=re.IGNORECASE)

    # 4. "yesterday"
    elif re.search(r"\byesterday\b", clean_query, re.IGNORECASE):
        start_ts = yesterday_start.timestamp()
        end_ts = yesterday_end.timestamp()
        clean_query = re.sub(r"\byesterday\b", "", clean_query, flags=re.IGNORECASE)

    # 5. "this morning" (06:00 to 12:00 today)
    elif re.search(r"\bthis\s+morning\b", clean_query, re.IGNORECASE):
        start_ts = datetime.combine(now.date(), dt_time(6, 0)).timestamp()
        end_ts = datetime.combine(now.date(), dt_time(12, 0)).timestamp()
        clean_query = re.sub(r"\bthis\s+morning\b", "", clean_query, flags=re.IGNORECASE)

    # 6. "this afternoon" (12:00 to 18:00 today)
    elif re.search(r"\bthis\s+afternoon\b", clean_query, re.IGNORECASE):
        start_ts = datetime.combine(now.date(), dt_time(12, 0)).timestamp()
        end_ts = datetime.combine(now.date(), dt_time(18, 0)).timestamp()
        clean_query = re.sub(r"\bthis\s+afternoon\b", "", clean_query, flags=re.IGNORECASE)

    # 7. "today"
    elif re.search(r"\btoday\b", clean_query, re.IGNORECASE):
        start_ts = today_start.timestamp()
        end_ts = now.timestamp()
        clean_query = re.sub(r"\btoday\b", "", clean_query, flags=re.IGNORECASE)

    # 8. "last [weekday]" (e.g., "last tuesday", "last friday")
    weekday_match = re.search(r"\blast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", clean_query, re.IGNORECASE)
    if weekday_match:
        target_name = weekday_match.group(1).lower()
        target_wd = WEEKDAYS[target_name]
        current_wd = now.weekday()
        # Days back to that weekday
        days_back = (current_wd - target_wd) % 7
        if days_back == 0:
            days_back = 7  # If today is Tuesday, "last Tuesday" means 7 days ago
        target_date = now.date() - timedelta(days=days_back)
        start_ts = datetime.combine(target_date, dt_time.min).timestamp()
        end_ts = datetime.combine(target_date, dt_time.max).timestamp()
        clean_query = re.sub(r"\blast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", "", clean_query, flags=re.IGNORECASE)

    # 9. "two weeks ago"
    elif re.search(r"\btwo\s+weeks\s+ago\b|\b2\s+weeks\s+ago\b", clean_query, re.IGNORECASE):
        start_ts = (now - timedelta(days=14)).timestamp()
        end_ts = (now - timedelta(days=7)).timestamp()
        clean_query = re.sub(r"\b(two|2)\s+weeks\s+ago\b", "", clean_query, flags=re.IGNORECASE)

    # 10. "last week"
    elif re.search(r"\blast\s+week\b", clean_query, re.IGNORECASE):
        start_ts = (now - timedelta(days=7)).timestamp()
        end_ts = now.timestamp()
        clean_query = re.sub(r"\blast\s+week\b", "", clean_query, flags=re.IGNORECASE)

    # 11. "N days ago"
    days_ago_match = re.search(r"\b(\d+)\s+days?\s+ago\b", clean_query, re.IGNORECASE)
    if days_ago_match and not start_ts:
        n = int(days_ago_match.group(1))
        target_date = now.date() - timedelta(days=n)
        start_ts = datetime.combine(target_date, dt_time.min).timestamp()
        end_ts = datetime.combine(target_date, dt_time.max).timestamp()
        clean_query = re.sub(r"\b\d+\s+days?\s+ago\b", "", clean_query, flags=re.IGNORECASE)

    # Clean residual filler words like "what was that article about", "what did I work on", etc.
    clean_query = re.sub(r"\b(what\s+was\s+that|what\s+did\s+i\s+work\s+on|tell\s+me\s+about|find\s+me|show\s+me)\b", "", clean_query, flags=re.IGNORECASE)
    # Normalize whitespaces
    clean_query = " ".join(clean_query.strip().split())

    return clean_query, start_ts, end_ts

