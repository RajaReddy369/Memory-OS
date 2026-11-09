"""
Tests for Stage 2: Websites Log, YouTube Module, and Branch Tree.
Validates:
1. Fake YouTube search -> 3 videos -> Google search -> Wikipedia navigation sequence.
2. Referrer fallback attaches orphan visits to nearest earlier search in same session.
3. YouTube video table records real play time vs duration, channel, and originating search query.
4. Blocked domains are strictly excluded across tree, searches, and websites.
5. Endpoints /api/tree/roots, /api/tree, /api/youtube/searches, and /api/youtube/videos.
6. Search query extractor coverage across all required engines and backfill verification.
"""

import json
import os
import tempfile
import time
from pathlib import Path
import pytest

from backend import database
from backend.config import API_TOKEN, DEFAULT_BLOCKED_DOMAINS
from backend.database import (
    backfill_search_queries,
    delete_website_history,
    get_all_searches,
    get_data_summary,
    get_db_connection,
    get_website_detail,
    get_websites_summary,
    init_db,
    insert_event,
    upsert_youtube_video,
)
from backend.main import (
    get_nested_branch_tree_endpoint,
    get_tree_roots_endpoint,
    get_website_detail_endpoint,
    get_websites_endpoint,
    get_youtube_searches_endpoint,
    get_youtube_videos_endpoint,
)
from backend.models import EventIngestItem
from backend.search_extractor import extract_search_query, extract_youtube_video_id
from backend.tree_service import (
    get_nested_branch_tree,
    get_tree_roots,
    get_youtube_searches_list,
    get_youtube_videos_list,
)


def run_sync(coro):
    """Synchronously advance a non-blocking coroutine without requiring event loop network socketpairs."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise RuntimeError("Coroutine did not finish synchronously")


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Use an isolated temporary database for Stage 2 tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db_path = Path(tmpdir) / "test_stage2_memoryos.db"
        temp_vec_path = Path(tmpdir) / "test_stage2_vectors.db"
        monkeypatch.setattr(database, "DB_PATH", temp_db_path)
        from backend import tree_service, graph3d
        monkeypatch.setattr(tree_service, "DB_PATH", temp_db_path)
        monkeypatch.setattr(graph3d, "DB_PATH", temp_db_path)

        database.init_db()

        from backend.vector_store import SQLiteDenseVectorStore
        import backend.vector_store
        vec_store = SQLiteDenseVectorStore(temp_vec_path)
        monkeypatch.setattr(backend.vector_store, "_vector_store_instance", vec_store)
        yield


def test_search_query_extractor_all_required_engines():
    """Verify query extraction for all required engines plus generic fallbacks."""
    test_cases = [
        ("https://www.google.com/search?q=machine+learning+tutorial", "machine learning tutorial", "Google"),
        ("https://www.bing.com/search?q=fastapi+vs+flask", "fastapi vs flask", "Bing"),
        ("https://duckduckgo.com/?q=local+llm+rag", "local llm rag", "DuckDuckGo"),
        ("https://www.youtube.com/results?search_query=threejs+instanced+mesh", "threejs instanced mesh", "YouTube"),
        ("https://en.wikipedia.org/wiki/Special:Search?search=Reciprocal_rank_fusion", "Reciprocal_rank_fusion", "Wikipedia"),
        ("https://github.com/search?q=lancedb+python", "lancedb python", "GitHub"),
        ("https://www.amazon.com/s?k=mechanical+keyboard", "mechanical keyboard", "Amazon"),
        ("https://www.reddit.com/search/?q=local+ai+agents", "local ai agents", "Reddit"),
        ("https://stackoverflow.com/search?q=sqlite3+fts5+porter", "sqlite3 fts5 porter", "StackOverflow"),
        ("https://docs.trychroma.com/search?query=embeddings", "embeddings", "Docs"),
    ]

    for url, expected_query, expected_engine in test_cases:
        res = extract_search_query(url)
        assert res is not None, f"Failed to extract query from {url}"
        extracted_q, engine = res
        assert expected_query.lower() in extracted_q.lower()
        assert expected_engine.lower() in engine.lower()


def test_youtube_video_id_extraction():
    """Test video ID extraction across watch, short, embed, and youtu.be URLs."""
    cases = [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=abc123XYZ09&t=42s", "abc123XYZ09"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/shortVideoId", "shortVideoId"),
        ("https://www.youtube.com/embed/embedVideoId", "embedVideoId"),
    ]
    for url, expected_id in cases:
        assert extract_youtube_video_id(url) == expected_id


def test_workflow_youtube_search_videos_google_wikipedia():
    """
    Test 1: Full user workflow simulation:
    YouTube Search -> 3 Videos watched -> Google Search -> Wikipedia page visit.
    Confirms:
    - Referrer fallback links orphan videos/pages to the search.
    - Real play time tracked in youtube_videos table.
    - Blocked domains (e.g. chase.com) are completely absent.
    """
    now = time.time()
    session_id = "test_sess_workflow_1"

    # 1. YouTube Search
    yt_search_id = insert_event(EventIngestItem(
        event_type="search_query",
        source="browser",
        timestamp=now - 500,
        url="https://www.youtube.com/results?search_query=threejs+tutorial",
        domain="youtube.com",
        title="YouTube Search: threejs tutorial",
        text_content="threejs tutorial",
        session_id=session_id
    ))
    assert yt_search_id is not None

    # 2. Watch 3 Videos from that YouTube Search
    video_events = [
        ("vid001_intro", "Three.js Basics for Beginners", "Web3D Dev", 600.0, 240.0),
        ("vid002_camera", "Three.js Camera & Orbit Controls", "Web3D Dev", 450.0, 310.0),
        ("vid003_shader", "Writing GLSL Shaders in Three.js", "ShaderMaster", 900.0, 520.0),
    ]

    for vid_id, vtitle, vchannel, vdur, vplay in video_events:
        # User opens video without explicit referrer (pasted/new tab) -> referrer fallback must link to yt_search_id!
        ev_id = insert_event(EventIngestItem(
            event_type="youtube_video",
            source="browser",
            timestamp=now - 400 + len(vtitle),
            url=f"https://www.youtube.com/watch?v={vid_id}",
            domain="youtube.com",
            title=vtitle,
            duration=vdur,
            session_id=session_id,
            metadata={
                "video_id": vid_id,
                "channel": vchannel,
                "description": f"Learn {vtitle} step by step in this comprehensive video.",
                "duration": vdur,
                "play_time": vplay,
                "search_query": "threejs tutorial"
            }
        ))
        assert ev_id is not None

    # 3. Sensitive / Blocked Domain visit (must be blocked & absent)
    blocked_id = insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=now - 300,
        url="https://chase.com/login",
        domain="chase.com",
        title="Chase Bank Login",
        session_id=session_id
    ))
    assert blocked_id is None

    # 4. Google Search -> Wikipedia Page
    google_search_id = insert_event(EventIngestItem(
        event_type="search_query",
        source="browser",
        timestamp=now - 200,
        url="https://www.google.com/search?q=WebGL+architecture",
        domain="google.com",
        title="Google Search: WebGL architecture",
        text_content="WebGL architecture",
        session_id=session_id
    ))
    assert google_search_id is not None

    wiki_id = insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=now - 150,
        url="https://en.wikipedia.org/wiki/WebGL",
        domain="en.wikipedia.org",
        title="WebGL - Wikipedia",
        referrer_url="https://www.google.com/search?q=WebGL+architecture",
        duration=120.0,
        session_id=session_id
    ))
    assert wiki_id is not None

    # Verification A: YouTube Videos Table
    yt_videos = run_sync(get_youtube_videos_endpoint(q=None, limit=50))
    assert len(yt_videos) == 3
    for y in yt_videos:
        assert y["video_id"] in ["vid001_intro", "vid002_camera", "vid003_shader"]
        assert y["search_query"] == "threejs tutorial"
        assert y["play_time"] in [240.0, 310.0, 520.0]

    # Verification B: YouTube Searches Endpoint
    yt_searches = run_sync(get_youtube_searches_endpoint(limit=50))
    assert len(yt_searches) >= 1
    found_yt_search = next(s for s in yt_searches if s["query"] == "threejs tutorial")
    assert found_yt_search["video_count"] == 3
    assert found_yt_search["total_watch_time"] == (240.0 + 310.0 + 520.0)

    # Verification C: Branch Tree Endpoint
    tree_roots = run_sync(get_tree_roots_endpoint())
    assert any(r["domain"] == "youtube.com" for r in tree_roots)
    assert any(r["domain"] == "google.com" for r in tree_roots)
    # Blocked domain chase.com must NEVER be in tree roots!
    assert not any("chase.com" in r["domain"] for r in tree_roots)

    # Hierarchical Nested Tree
    full_tree = run_sync(get_nested_branch_tree_endpoint(domain=None))
    yt_tree_node = next(t for t in full_tree if t["label"] == "youtube.com")
    assert len(yt_tree_node["children"]) >= 1

    # Verify search branch under YouTube
    yt_branch = next(b for b in yt_tree_node["children"] if b.get("query") == "threejs tutorial")
    # All 3 videos must be nested children under the YouTube search query!
    assert len(yt_branch["children"]) == 3
    for vchild in yt_branch["children"]:
        assert vchild["type"] == "video"
        assert vchild["play_time"] > 0


def test_referrer_fallback_attaches_orphan_to_earlier_search():
    """Test 2: When an event has no referrer, it attaches to the nearest earlier search query."""
    now = time.time()
    s_id = "test_sess_fallback"

    # Preceding search
    search_id = insert_event(EventIngestItem(
        event_type="search_query",
        source="browser",
        timestamp=now - 100,
        url="https://duckduckgo.com/?q=threejs+performance",
        domain="duckduckgo.com",
        title="DuckDuckGo Search: threejs performance",
        text_content="threejs performance",
        session_id=s_id
    ))

    # Orphan page visit (opened in new tab without referrer)
    orphan_id = insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=now - 80,
        url="https://discourse.threejs.org/t/improving-render-speed/123",
        domain="discourse.threejs.org",
        title="Improving render speed - Three.js forum",
        referrer_url=None,
        session_id=s_id
    ))

    conn = get_db_connection()
    try:
        cur = conn.execute("SELECT from_event_id, referrer_url FROM events WHERE id = ?", (orphan_id,))
        row = cur.fetchone()
        assert row["from_event_id"] == search_id, "Orphan page should have attached to earlier search"
        assert "duckduckgo" in row["referrer_url"], "Referrer URL should have inherited earlier search URL"
    finally:
        conn.close()


def test_backfill_search_queries_and_deletion():
    """Test 3: Backfill extracts queries from past visited page URLs, and deletion works cleanly."""
    now = time.time()
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
            INSERT INTO events (
                event_type, source, timestamp, url, domain, title, app_name,
                duration, text_content, created_at
            ) VALUES (
                'page_visit', 'browser', ?, 'https://www.google.com/search?q=pytest+fixtures+guide',
                'google.com', 'Google Search', 'Chrome', 10.0, '', ?
            );
            """, (now - 100, now))
    finally:
        conn.close()

    # Backfill extraction
    count = backfill_search_queries()
    assert count >= 1

    # Verify search appears in searches list
    searches = get_all_searches(domain="google.com")
    assert any("pytest fixtures guide" in s["query"] for s in searches)

    # Deletion of domain history
    del_count = delete_website_history("google.com")
    assert del_count >= 1

    # Google events should now be gone
    assert len(get_all_searches(domain="google.com")) == 0

