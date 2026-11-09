"""
Unit tests for SQLite storage, deduplication, and FTS5 search.
"""

import os
import tempfile
from pathlib import Path
import pytest

from backend import database
from backend.models import EventIngestItem


@pytest.fixture(autouse=True)
def setup_temp_db(monkeypatch):
    """Isolate tests into a temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db_path = Path(tmpdir) / "test_memoryos.db"
        monkeypatch.setattr(database, "DB_PATH", temp_db_path)
        database.init_db()
        yield


def test_insert_and_fts_search():
    item = EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=1700000000.0,
        url="https://docs.trychroma.com/getting-started",
        domain="docs.trychroma.com",
        title="Chroma Vector Database Getting Started Guide",
        text_content="Chroma is the AI-native open-source embedding database for building LLM apps.",
        duration=45.0
    )

    event_id = database.insert_event(item)
    assert event_id is not None
    assert event_id > 0

    # Search for "vector database"
    results = database.search_events("vector database")
    assert len(results) >= 1
    assert results[0].id == event_id
    assert "Chroma" in results[0].title
    assert results[0].domain == "docs.trychroma.com"


def test_deduplication():
    item1 = EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=1700000000.0,
        url="https://example.com/article",
        title="Sample Article on RAG",
        text_content="This is a detailed article explaining retrieval augmented generation."
    )
    # Same content shortly after
    item2 = EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=1700000100.0,
        url="https://example.com/article",
        title="Sample Article on RAG",
        text_content="This is a detailed article explaining retrieval augmented generation."
    )

    id1 = database.insert_event(item1)
    id2 = database.insert_event(item2)

    assert id1 is not None
    assert id2 is None  # Deduplicated and skipped
    assert database.get_event_count() == 1


def test_blocked_domain_rejection():
    item = EventIngestItem(
        event_type="page_visit",
        source="browser",
        url="https://chase.com/my-account",
        title="Chase Bank Online Services",
        text_content="Sensitive balance information"
    )
    result = database.insert_event(item)
    assert result is None
    assert database.get_event_count() == 0

