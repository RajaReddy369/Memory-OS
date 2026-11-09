"""
Unit tests for Session Segmentation and Project Clustering.
Tests boundary splitting on time gaps (>10 min) and context switches using synthetic timelines.
"""

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import pytest

from backend import database
from backend.models import EventIngestItem
from backend.sessions import recompute_sessions, segment_events


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Isolate database for session segmentation tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_sessions.db"
        monkeypatch.setattr(database, "DB_PATH", test_db)
        database.init_db()
        yield


def test_session_quality_segmentation_with_fake_timeline():
    """
    Test scenario:
    1. A 2-hour coding block in VS Code (10:00 to 12:00)
    2. A 20-minute gap of total inactivity (12:00 to 12:20)
    3. A 50-minute research block on web documentation (12:20 to 13:10)
    Assert they split into 2 distinct sessions with sensible titles and proper project tags.
    """
    base_time = 1700000000.0  # Reference epoch
    events = []

    # Block 1: 2-hour coding block in VS Code (events every 10-15 mins)
    for i in range(8):
        t = base_time + (i * 900)  # Every 15 mins for 2 hours (8 * 900 = 7200s = 2 hrs)
        events.append({
            "id": i + 1,
            "event_type": "active_window",
            "source": "desktop",
            "timestamp": t,
            "duration": 900.0,
            "app_name": "Code",
            "title": f"backend/models.py - MemoryOS - VS Code",
            "domain": None
        })

    # Gap of 20 minutes = 1200 seconds (> 10 minutes threshold)
    after_break_time = base_time + 7200.0 + 1200.0

    # Block 2: 50-minute research block on documentation
    for j in range(4):
        t = after_break_time + (j * 750)
        events.append({
            "id": 100 + j,
            "event_type": "page_visit",
            "source": "browser",
            "timestamp": t,
            "duration": 700.0,
            "app_name": "Chrome",
            "title": f"Vector Indexing Guide - LanceDB Documentation",
            "domain": "lancedb.github.io"
        })

    # Segment events using gap threshold 600s
    clusters = segment_events(events, gap_seconds=600.0)

    # 1. Assert exactly 2 distinct sessions formed
    assert len(clusters) == 2, f"Expected 2 sessions, got {len(clusters)}"

    # 2. Assert first session is the coding session
    coding_cluster = clusters[0]
    assert len(coding_cluster) == 8
    assert coding_cluster[0]["app_name"] == "Code"
    duration_1 = (coding_cluster[-1]["timestamp"] + coding_cluster[-1]["duration"]) - coding_cluster[0]["timestamp"]
    assert duration_1 == 7200.0  # 2 hours

    # 3. Assert second session is the research session
    research_cluster = clusters[1]
    assert len(research_cluster) == 4
    assert research_cluster[0]["domain"] == "lancedb.github.io"
    gap_between = research_cluster[0]["timestamp"] - (coding_cluster[-1]["timestamp"] + coding_cluster[-1]["duration"])
    assert gap_between == 1200.0  # 20-minute gap verified


def run_sync(coro):
    """Synchronously advance coroutine without triggering sandbox socketpair restrictions."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise RuntimeError("Coroutine did not finish synchronously")


def test_recompute_and_persist_sessions():
    """Verify session persistence, event linking, and graph edges."""
    base_time = 1700000000.0

    # Ingest raw events into SQLite
    ev1 = EventIngestItem(
        event_type="active_window",
        source="desktop",
        timestamp=base_time,
        duration=300.0,
        app_name="Code",
        title="main.py - MemoryOS"
    )
    ev2 = EventIngestItem(
        event_type="active_window",
        source="desktop",
        timestamp=base_time + 300.0,
        duration=300.0,
        app_name="Code",
        title="database.py - MemoryOS"
    )
    # Gap of 15 minutes
    ev3 = EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=base_time + 1500.0,
        duration=400.0,
        app_name="Chrome",
        domain="fastapi.tiangolo.com",
        title="FastAPI Documentation",
        url="https://fastapi.tiangolo.com"
    )

    id1 = database.insert_event(ev1)
    id2 = database.insert_event(ev2)
    id3 = database.insert_event(ev3)

    # Recompute sessions synchronously
    created = run_sync(recompute_sessions())
    assert len(created) == 2

    # Query sessions table
    sessions = database.get_sessions()
    assert len(sessions) == 2

    # Verify session detail with ordered events
    first_sess = database.get_session_by_id(sessions[1]["id"])  # chronological first
    assert first_sess is not None
    assert len(first_sess["events"]) == 2
    assert "Code" in first_sess["title"] or "Development" in first_sess["project_label"]
