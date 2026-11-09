"""
Integration and endpoint tests for FastAPI routes, security token auth, and business logic.
"""

import tempfile
from pathlib import Path
import pytest
from fastapi import HTTPException

from backend import database
from backend.config import API_TOKEN
from backend.main import (
    get_recent,
    get_status,
    health_check,
    ingest_batch_events,
    ingest_single_event,
    search_memory,
    toggle_recording,
    verify_api_key,
)
from backend.models import BatchIngestRequest, EventIngestItem


def run_sync(coro):
    """Synchronously advance a non-blocking coroutine without requiring event loop network socketpairs."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise RuntimeError("Coroutine did not finish synchronously")


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Use an isolated temporary database for API tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db_path = Path(tmpdir) / "test_api_memoryos.db"
        temp_vec_path = Path(tmpdir) / "test_api_vectors.db"
        monkeypatch.setattr(database, "DB_PATH", temp_db_path)
        database.init_db()

        from backend.vector_store import SQLiteDenseVectorStore
        import backend.vector_store
        vec_store = SQLiteDenseVectorStore(temp_vec_path)
        monkeypatch.setattr(backend.vector_store, "_vector_store_instance", vec_store)
        yield


def test_health_check():
    res = run_sync(health_check())
    assert res["status"] == "ok"
    assert res["service"] == "MemoryOS"


def test_verify_api_key_valid():
    # Should not raise exception
    verify_api_key(x_memoryos_key=API_TOKEN)
    verify_api_key(authorization=f"Bearer {API_TOKEN}")


def test_verify_api_key_invalid():
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(x_memoryos_key="wrong_token")
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(x_memoryos_key=None, authorization=None)
    assert exc_info.value.status_code == 401


def test_status_endpoint():
    status_res = run_sync(get_status(None))
    assert status_res.status == "active"
    assert status_res.total_events == 0
    assert status_res.recording_active is True


def test_ingest_and_search_endpoint():
    event = EventIngestItem(
        event_type="page_visit",
        source="browser",
        url="https://fastapi.tiangolo.com/tutorial/",
        domain="fastapi.tiangolo.com",
        title="FastAPI Framework Documentation",
        text_content="FastAPI is a modern, fast web framework for building APIs with Python.",
        duration=30.0
    )

    # Ingest single event
    ingest_res = run_sync(ingest_single_event(event, None))
    assert ingest_res["status"] == "ok"
    assert ingest_res["stored"] is True
    assert ingest_res["id"] is not None

    # Search for keywords
    search_res = run_sync(search_memory(q="framework", limit=10, _=None))
    assert search_res.total >= 1
    assert "FastAPI" in search_res.results[0].title


def test_batch_ingest_endpoint():
    items = [
        EventIngestItem(
            event_type="page_visit",
            source="browser",
            url="https://en.wikipedia.org/wiki/Vector_database",
            title="Vector database Wikipedia page",
            text_content="A vector database is a database that indexes and stores vector embeddings."
        ),
        EventIngestItem(
            event_type="page_visit",
            source="browser",
            url="https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
            title="Retrieval-augmented generation Wikipedia page",
            text_content="RAG is a technique for enhancing the accuracy and reliability of generative AI models."
        )
    ]
    batch_req = BatchIngestRequest(events=items)
    batch_res = run_sync(ingest_batch_events(batch_req, None))
    assert batch_res["status"] == "ok"
    assert batch_res["stored_count"] == 2

    # Verify search finds both
    rag_search = run_sync(search_memory(q="generative AI", limit=10, _=None))
    assert rag_search.total >= 1
    assert "Retrieval-augmented" in rag_search.results[0].title


def test_recording_toggle_flow():
    # Pause recording
    toggle_res = run_sync(toggle_recording(paused=True, _=None))
    assert toggle_res["recording_active"] is False

    # Attempt ingestion while paused
    event = EventIngestItem(
        event_type="page_visit",
        title="Ignored Page Title",
        text_content="Should not be stored when paused"
    )
    paused_ingest = run_sync(ingest_single_event(event, None))
    assert paused_ingest["status"] == "paused"
    assert paused_ingest["stored"] is False

    # Resume recording
    resume_res = run_sync(toggle_recording(paused=False, _=None))
    assert resume_res["recording_active"] is True
