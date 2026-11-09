"""
Unit tests for Time-Aware Temporal Query Parser.
"""

from datetime import datetime, timedelta, time as dt_time
from backend.temporal import parse_temporal_query


def test_parse_yesterday_afternoon():
    ref = datetime(2026, 11, 10, 20, 0, 0)
    query = "What was that article about vector databases I read yesterday afternoon?"
    clean_q, start_ts, end_ts = parse_temporal_query(query, reference_time=ref)

    assert "yesterday afternoon" not in clean_q.lower()
    assert "vector databases" in clean_q
    assert start_ts is not None and end_ts is not None
    # 12:00 to 18:00 on Nov 9
    start_dt = datetime.fromtimestamp(start_ts)
    end_dt = datetime.fromtimestamp(end_ts)
    assert start_dt.day == 9
    assert start_dt.hour == 12
    assert end_dt.hour == 18


def test_parse_this_morning():
    ref = datetime(2026, 11, 10, 15, 30, 0)
    query = "Show me articles on python this morning"
    clean_q, start_ts, end_ts = parse_temporal_query(query, reference_time=ref)

    assert "this morning" not in clean_q.lower()
    assert "python" in clean_q
    start_dt = datetime.fromtimestamp(start_ts)
    end_dt = datetime.fromtimestamp(end_ts)
    assert start_dt.day == 10
    assert start_dt.hour == 6
    assert end_dt.hour == 12


def test_parse_two_weeks_ago():
    ref = datetime(2026, 11, 20, 12, 0, 0)
    query = "What did I research about postgres two weeks ago?"
    clean_q, start_ts, end_ts = parse_temporal_query(query, reference_time=ref)

    assert "two weeks ago" not in clean_q.lower()
    assert "postgres" in clean_q
    assert start_ts is not None and end_ts is not None
    assert end_ts > start_ts


def test_parse_last_tuesday():
    # If today is Friday Nov 13, 2026, last Tuesday is Nov 10, 2026
    ref = datetime(2026, 11, 13, 12, 0, 0) # Friday
    query = "Notes on algorithms from last Tuesday"
    clean_q, start_ts, end_ts = parse_temporal_query(query, reference_time=ref)

    assert "last tuesday" not in clean_q.lower()
    start_dt = datetime.fromtimestamp(start_ts)
    assert start_dt.weekday() == 1 # Tuesday

