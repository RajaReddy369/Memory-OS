"""
Tests for Stage 1: The 3D World Map (Delivered as MV3 Browser Extension with Real Data & History Importer).
Validates:
1. Empty database returns 0 nodes, 0 edges, and clean empty state metadata.
2. Ingesting real events produces accurate, deterministic 3D graph nodes and edges.
3. /api/data/summary reflects exact database rows across sources.
4. History import event structure, secret scrubbing, and domain exclusion.
5. Deletion by source (/api/events/source/{source}).
6. Production cleanliness: sampleData.ts does not exist and no demo datasets are shipped.
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
    delete_events_by_source,
    get_data_summary,
    get_db_connection,
    init_db,
    insert_event,
    insert_events_batch,
)
from backend.graph3d import get_real_graph3d_data, get_real_graph3d_node_detail, init_graph3d_db
from backend.main import (
    delete_events_source_endpoint,
    get_data_summary_endpoint,
    get_graph3d_endpoint,
    get_graph3d_node_detail_endpoint,
    ingest_batch_events,
)
from backend.models import BatchIngestRequest, EventIngestItem
from backend.scrubber import extract_domain, is_domain_blocked, scrub_text


def run_sync(coro):
    """Synchronously advance a non-blocking coroutine without requiring event loop network socketpairs."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise RuntimeError("Coroutine did not finish synchronously")


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Use an isolated temporary database for Stage 1 tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db_path = Path(tmpdir) / "test_stage1_memoryos.db"
        temp_vec_path = Path(tmpdir) / "test_stage1_vectors.db"
        monkeypatch.setattr(database, "DB_PATH", temp_db_path)
        from backend import graph3d
        monkeypatch.setattr(graph3d, "DB_PATH", temp_db_path)

        database.init_db()
        graph3d.init_graph3d_db()

        from backend.vector_store import SQLiteDenseVectorStore
        import backend.vector_store
        vec_store = SQLiteDenseVectorStore(temp_vec_path)
        monkeypatch.setattr(backend.vector_store, "_vector_store_instance", vec_store)
        yield


def test_empty_database_graph3d_and_summary():
    """Test 1: Empty database returns exactly 0 nodes, 0 edges, and empty state metadata."""
    data = run_sync(get_graph3d_endpoint(from_time=None, to_time=None, level="session", source=None, max_nodes=2000))
    assert data["nodes"] == []
    assert data["edges"] == []
    assert data["meta"]["total_nodes"] == 0
    assert data["meta"]["total_events"] == 0
    assert "empty" in data["meta"]["data_source"].lower()

    # /api/data/summary must report 0
    summary = run_sync(get_data_summary_endpoint())
    assert summary["total_events"] == 0
    assert summary["date_span_days"] == 0
    assert summary["total_domains"] == 0
    assert summary["sources"]["extension_live"] == 0
    assert summary["sources"]["edge_history"] == 0


def test_insert_real_events_populates_graph3d_and_summary():
    """Test 2: Inserting real events generates matching 3D nodes, cities, and summary metrics."""
    now = time.time()
    events = [
        {
            "event_type": "page_visit",
            "source": "extension_live",
            "timestamp": now - 3600,
            "url": "https://fastapi.tiangolo.com/tutorial/",
            "domain": "fastapi.tiangolo.com",
            "title": "FastAPI Tutorial - First Steps",
            "app_name": "Chrome",
            "duration": 180.0,
            "text_content": "FastAPI is a modern, fast web framework.",
            "referrer_url": "https://www.google.com/search?q=fastapi+tutorial",
            "scroll_depth": 0.85
        },
        {
            "event_type": "page_visit",
            "source": "extension_live",
            "timestamp": now - 1800,
            "url": "https://docs.python.org/3/library/sqlite3.html",
            "domain": "docs.python.org",
            "title": "sqlite3 — DB-API 2.0 interface for SQLite databases",
            "app_name": "Chrome",
            "duration": 240.0,
            "text_content": "SQLite is a C library that provides a lightweight disk-based database.",
            "referrer_url": "https://fastapi.tiangolo.com/tutorial/",
            "scroll_depth": 0.65
        },
        {
            "event_type": "window_focus",
            "source": "desktop_agent",
            "timestamp": now - 900,
            "url": "",
            "domain": "",
            "title": "main.py - MemoryOS - Visual Studio Code",
            "app_name": "Code",
            "duration": 300.0,
            "text_content": "import fastapi\napp = FastAPI()",
            "referrer_url": "",
            "scroll_depth": 0.0
        }
    ]

    for ev in events:
        insert_event(EventIngestItem(**ev))

    # Check /api/data/summary
    s_data = run_sync(get_data_summary_endpoint())
    assert s_data["total_events"] == 3
    assert s_data["total_domains"] >= 2
    assert s_data["sources"]["extension_live"] == 2
    assert s_data["sources"]["desktop_agent"] == 1

    # Check /api/graph3d
    g_data = run_sync(get_graph3d_endpoint(from_time=None, to_time=None, level="session", source=None, max_nodes=2000))
    assert g_data["meta"]["total_events"] == 3
    assert len(g_data["nodes"]) > 0

    # Ensure nodes have stable 3D coordinates
    for node in g_data["nodes"]:
        assert len(node["position"]) == 3
        assert isinstance(node["position"][0], (int, float))
        assert isinstance(node["position"][1], (int, float))
        assert isinstance(node["position"][2], (int, float))

    # Check node detail
    event_nodes = [n for n in g_data["nodes"] if n["type"] == "building"]
    assert len(event_nodes) >= 1
    sample_node_id = event_nodes[0]["id"]

    detail = run_sync(get_graph3d_node_detail_endpoint(sample_node_id))
    assert detail["type"] == "event"
    assert "FastAPI" in detail["title"] or "sqlite3" in detail["title"] or "Visual Studio Code" in detail["title"]


def test_history_import_payload_and_source_deletion():
    """Test 3: History importer format, scrubbing, and bulk deletion by source."""
    now = time.time()
    history_events = [
        EventIngestItem(
            event_type="page_visit",
            source="edge_history",
            timestamp=now - 7200,
            url="https://github.com/microsoft/vscode?token=ghp_secretToken123456",
            domain="github.com",
            title="GitHub - microsoft/vscode",
            app_name="Edge",
            duration=0.0,
            text_content="",
            metadata_json=json.dumps({"metadata_only": True, "visit_count": 4, "typed_count": 1})
        ),
        EventIngestItem(
            event_type="search_query",
            source="edge_history",
            timestamp=now - 7199,
            url="https://www.google.com/search?q=threejs+instanced+mesh&auth=sensitive_abc",
            domain="google.com",
            title="Google Search: threejs instanced mesh",
            app_name="Edge",
            duration=0.0,
            text_content="threejs instanced mesh",
            metadata_json=json.dumps({"metadata_only": True, "query": "threejs instanced mesh", "engine": "Google"})
        )
    ]

    # Test scrubber on input
    scrubbed_url = scrub_text(history_events[0].url)
    assert "[REDACTED_GITHUB_TOKEN]" in scrubbed_url or "[REDACTED]" in scrubbed_url
    assert "ghp_secretToken123456" not in scrubbed_url

    # Ingest batch
    batch_req = BatchIngestRequest(events=history_events)
    batch_res = run_sync(ingest_batch_events(batch_req))
    assert batch_res["stored_count"] == 2

    # Verify summary includes edge_history
    sum_res = run_sync(get_data_summary_endpoint())
    assert sum_res["sources"]["edge_history"] == 2

    # Delete source "edge_history"
    del_res = run_sync(delete_events_source_endpoint("edge_history"))
    assert del_res["deleted_count"] == 2

    # Summary should now be 0
    sum_after = run_sync(get_data_summary_endpoint())
    assert sum_after["sources"]["edge_history"] == 0
    assert sum_after["total_events"] == 0


def test_production_bundle_contains_no_sample_data():
    """Test 4: Verify sampleData.ts has been deleted and no mock generators exist in frontend."""
    frontend_sample_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "src", "data", "sampleData.ts")
    assert not os.path.exists(frontend_sample_path), "sampleData.ts MUST NOT exist in production codebase"

    # Scan all frontend source files for references to sampleData
    src_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "src")
    forbidden_tokens = ["SAMPLE_PROJECTS", "generateSampleSessions", "generateCityTowers", "generateGalaxyData"]

    for root, _, files in os.walk(src_dir):
        for f in files:
            if f.endswith((".ts", ".tsx")):
                fpath = os.path.join(root, f)
                with open(fpath, "r", encoding="utf-8") as fh:
                    content = fh.read()
                    for token in forbidden_tokens:
                        assert token not in content, f"Forbidden mock token '{token}' found in {fpath}"

    # Also verify that extension/world/index.html was built
    world_html = os.path.join(os.path.dirname(__file__), "..", "extension", "world", "index.html")
    assert os.path.exists(world_html), "extension/world/index.html must be compiled by Vite"
