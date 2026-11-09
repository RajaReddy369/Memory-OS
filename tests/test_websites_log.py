"""
Tests for MemoryOS Websites Log & Search Query Extraction.
Tests search query extraction across engines, typing in search boxes,
backfill over legacy events, privacy blocklist enforcement, and website API endpoints.
"""

import json
import time
import pytest
from backend.config import API_TOKEN, DEFAULT_BLOCKED_DOMAINS
from backend.database import (
    backfill_search_queries,
    delete_website_history,
    get_all_searches,
    get_db_connection,
    get_website_detail,
    get_websites_summary,
    init_db,
    insert_event,
)
from backend.models import EventIngestItem
from backend.search_extractor import extract_search_query


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Point database to isolated temporary directory for test."""
    test_db = tmp_path / "test_websites.db"
    monkeypatch.setattr("backend.config.DB_PATH", test_db)
    monkeypatch.setattr("backend.database.DB_PATH", test_db)
    init_db()
    yield test_db


def test_search_query_extractor_engines():
    """Verify URL search query extraction across all supported platforms."""
    # Google
    res = extract_search_query("https://www.google.com/search?q=vector+databases&rlz=1C1")
    assert res is not None
    assert res[0] == "vector databases"
    assert res[1] == "Google"

    # YouTube
    res = extract_search_query("https://www.youtube.com/results?search_query=threejs+masterclass")
    assert res is not None
    assert res[0] == "threejs masterclass"
    assert res[1] == "YouTube"

    # Bing
    res = extract_search_query("https://www.bing.com/search?q=machine+learning+architecture")
    assert res is not None
    assert res[0] == "machine learning architecture"
    assert res[1] == "Bing"

    # DuckDuckGo
    res = extract_search_query("https://duckduckgo.com/?q=sqlite+wal+mode")
    assert res is not None
    assert res[0] == "sqlite wal mode"
    assert res[1] == "DuckDuckGo"

    # Wikipedia
    res = extract_search_query("https://en.wikipedia.org/w/index.php?search=Knowledge_graph")
    assert res is not None
    assert res[0] == "Knowledge_graph"
    assert res[1] == "Wikipedia"

    # GitHub
    res = extract_search_query("https://github.com/search?q=lancedb+python")
    assert res is not None
    assert res[0] == "lancedb python"
    assert res[1] == "GitHub"

    # Amazon
    res = extract_search_query("https://www.amazon.com/s?k=wireless+mechanical+keyboard")
    assert res is not None
    assert res[0] == "wireless mechanical keyboard"
    assert res[1] == "Amazon"

    # Reddit
    res = extract_search_query("https://www.reddit.com/search/?q=local+llm+rag")
    assert res is not None
    assert res[0] == "local llm rag"
    assert res[1] == "Reddit"

    # StackOverflow
    res = extract_search_query("https://stackoverflow.com/search?q=asyncio+exception+handling")
    assert res is not None
    assert res[0] == "asyncio exception handling"
    assert res[1] == "StackOverflow"

    # Generic fallback
    res = extract_search_query("https://docs.trychroma.com/reference?query=embeddings")
    assert res is not None
    assert res[0] == "embeddings"

    # Non-search URL
    assert extract_search_query("https://github.com/facebook/react") is None


def test_ingest_auto_extracts_search_and_blocks_sensitive():
    """Verify ingest creates search_query events and rejects blocked domains."""
    now = time.time()

    # 1. Google search visit
    g_id = insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=now - 50,
        url="https://www.google.com/search?q=vector+databases",
        domain="google.com",
        title="vector databases - Google Search",
        duration=30.0
    ))
    assert g_id is not None

    # 2. YouTube search visit
    yt_id = insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=now - 40,
        url="https://www.youtube.com/results?search_query=threejs+tutorial",
        domain="youtube.com",
        title="threejs tutorial - YouTube",
        duration=45.0,
        referrer_url="https://www.google.com/search?q=vector+databases"
    ))
    assert yt_id is not None

    # 3. Blocked domain (e.g. banking service)
    blocked_id = insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=now - 30,
        url="https://secure.chase.com/web/auth/dashboard",
        domain="chase.com",
        title="Chase Bank Account Overview"
    ))
    assert blocked_id is None, "Blocked banking domain must be rejected on ingest"

    # 4. Debounced typing in search box
    type_id = insert_event(EventIngestItem(
        event_type="typed_input",
        source="browser",
        timestamp=now - 20,
        url="https://github.com/search",
        domain="github.com",
        title="GitHub Search",
        text_content="fastapi sqlite rag",
        metadata={"type": "search", "elementId": "header-search-input"}
    ))
    assert type_id is not None

    # Check search_queries in database
    conn = get_db_connection()
    try:
        cur = conn.execute("SELECT id, title, text_content, domain, metadata_json FROM events WHERE event_type = 'search_query'")
        rows = cur.fetchall()
        queries = [r["text_content"] for r in rows]
        assert "vector databases" in queries
        assert "threejs tutorial" in queries
        assert "fastapi sqlite rag" in queries

        # Verify blocked domain is not in the events table
        cur2 = conn.execute("SELECT COUNT(*) FROM events WHERE domain LIKE '%chase%'")
        assert cur2.fetchone()[0] == 0
    finally:
        conn.close()


def test_backfill_search_queries():
    """Verify backfill scans legacy events and populates search_query events."""
    conn = get_db_connection()
    now = time.time()
    try:
        # Insert raw legacy events directly without search_query generation
        with conn:
            conn.execute("""
            INSERT INTO events (event_type, source, timestamp, url, domain, title, app_name, duration, created_at)
            VALUES ('page_visit', 'browser', ?, 'https://www.bing.com/search?q=langchain+vs+llamaindex', 'bing.com', 'Bing Search', 'Chrome', 20.0, ?)
            """, (now - 100, now))

            conn.execute("""
            INSERT INTO events (event_type, source, timestamp, url, domain, title, app_name, duration, created_at)
            VALUES ('page_visit', 'browser', ?, 'https://en.wikipedia.org/wiki/Special:Search?search=Cosine_similarity', 'wikipedia.org', 'Wikipedia Search', 'Chrome', 15.0, ?)
            """, (now - 80, now))

            # Blocked domain legacy entry (should be skipped during backfill)
            conn.execute("""
            INSERT INTO events (event_type, source, timestamp, url, domain, title, app_name, duration, created_at)
            VALUES ('page_visit', 'browser', ?, 'https://login.chase.com/search?q=statement', 'chase.com', 'Chase Login', 'Chrome', 5.0, ?)
            """, (now - 60, now))
    finally:
        conn.close()

    # Run backfill
    count = backfill_search_queries()
    assert count == 2, f"Expected 2 backfilled events, got {count}"

    # Verify queries
    all_searches = get_all_searches()
    queries = [s["query"] for s in all_searches]
    assert "langchain vs llamaindex" in queries
    assert "Cosine_similarity" in queries
    assert "statement" not in queries  # Blocked domain must not be backfilled

    # Idempotency check: running again should backfill 0
    count_again = backfill_search_queries()
    assert count_again == 0


def test_get_websites_summary_and_detail():
    """Verify aggregated websites summary and full website detail retrieval."""
    now = time.time()

    # Visit 1: Google search
    insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=now - 200,
        url="https://www.google.com/search?q=threejs+materials",
        domain="google.com",
        title="threejs materials - Google Search",
        duration=25.0
    ))

    # Visit 2: Google search 2
    insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=now - 150,
        url="https://www.google.com/search?q=webgl+shaders",
        domain="google.com",
        title="webgl shaders - Google Search",
        duration=35.0
    ))

    # Navigation from Google to docs.trychroma.com
    insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=now - 100,
        url="https://docs.trychroma.com/getting-started",
        domain="docs.trychroma.com",
        title="Chroma Getting Started",
        duration=60.0,
        referrer_url="https://www.google.com/search?q=webgl+shaders"
    ))

    # Highlights and typed text on docs.trychroma.com
    insert_event(EventIngestItem(
        event_type="text_select",
        source="browser",
        timestamp=now - 90,
        url="https://docs.trychroma.com/getting-started",
        domain="docs.trychroma.com",
        title="Chroma Getting Started",
        selected_text="Chroma is the AI-native open-source embedding database."
    ))

    insert_event(EventIngestItem(
        event_type="typed_input",
        source="browser",
        timestamp=now - 80,
        url="https://docs.trychroma.com/getting-started",
        domain="docs.trychroma.com",
        title="Chroma Getting Started",
        text_content="pip install chromadb"
    ))

    # Test summary endpoint
    summary = get_websites_summary()
    assert len(summary) >= 2
    domains = [s["domain"] for s in summary]
    assert "google.com" in domains
    assert "docs.trychroma.com" in domains

    # Verify google summary
    g_summary = next(s for s in summary if s["domain"] == "google.com")
    assert g_summary["total_visits"] >= 2
    assert g_summary["total_active_time"] >= 60.0
    assert g_summary["search_count"] >= 2

    # Test detail endpoint
    detail = get_website_detail("google.com")
    assert detail is not None
    assert detail["domain"] == "google.com"
    assert len(detail["pages_visited"]) >= 2
    assert len(detail["search_queries"]) >= 2
    assert any("threejs materials" in q["query"] for q in detail["search_queries"])
    assert any("webgl shaders" in q["query"] for q in detail["search_queries"])

    # Test detail for chroma with highlights and typed text
    chroma_detail = get_website_detail("docs.trychroma.com")
    assert chroma_detail is not None
    assert len(chroma_detail["highlights"]) >= 1
    assert "Chroma is the AI-native" in chroma_detail["highlights"][0]["text"]
    assert len(chroma_detail["typed_text"]) >= 1
    assert "pip install chromadb" in chroma_detail["typed_text"][0]["text"]

    # Verify referrer navigation link
    assert len(chroma_detail["navigation_links"]) >= 1
    link = chroma_detail["navigation_links"][0]
    assert link["type"] == "came_from"
    assert link["from_domain"] == "google.com"


def test_delete_website_history():
    """Verify deleting a website's history removes all records from database."""
    now = time.time()
    insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=now - 50,
        url="https://example.com/page1",
        domain="example.com",
        title="Example Page 1",
        duration=15.0
    ))
    insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=now - 30,
        url="https://example.com/page2",
        domain="example.com",
        title="Example Page 2",
        duration=20.0
    ))

    # Confirm present
    assert get_website_detail("example.com") is not None

    # Delete history
    deleted_count = delete_website_history("example.com")
    assert deleted_count >= 2

    # Confirm gone
    assert get_website_detail("example.com") is None
    summary = get_websites_summary()
    assert not any(s["domain"] == "example.com" for s in summary)
