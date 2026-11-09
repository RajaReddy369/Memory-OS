"""
Integration and unit tests for RAG pipeline, chunking, vector search, and chat endpoint.
"""

from pathlib import Path
import tempfile
import pytest

from backend import database
from backend.chunker import chunk_text, create_chunks_for_event
from backend.config import API_TOKEN
from backend.embeddings import get_embedding_provider
from backend.main import chat_memory
from backend.models import ChatRequest, EventIngestItem
from backend.rag import get_rag_engine
from backend.vector_store import SQLiteDenseVectorStore, get_vector_store
import backend.vector_store


def run_sync(coro):
    """Advance non-blocking coroutine synchronously."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise RuntimeError("Coroutine did not finish synchronously")


@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    """Isolate databases for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_rag.db"
        test_vec = Path(tmpdir) / "test_rag_vec.db"
        monkeypatch.setattr(database, "DB_PATH", test_db)
        database.init_db()

        vec_store = SQLiteDenseVectorStore(test_vec)
        import backend.vector_store
        monkeypatch.setattr(backend.vector_store, "_vector_store_instance", vec_store)
        yield


def test_chunking_logic():
    text = (
        "Retrieval-augmented generation (RAG) is an AI framework. "
        "It improves the quality of LLM responses by grounding them in external facts. "
        "Dense vectors and sparse keywords are combined using hybrid search. "
        "Reciprocal Rank Fusion merges multiple ranked lists effectively."
    )
    chunks = chunk_text(text, target_chunk_chars=120, overlap_chars=30)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) > 0


def test_vector_store_and_hybrid_search():
    provider = get_embedding_provider()
    store = backend.vector_store.get_vector_store()

    # Ingest event into SQLite
    event = EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=1700000000.0,
        url="https://docs.trychroma.com",
        domain="docs.trychroma.com",
        title="Chroma Embedding Database",
        text_content="Chroma is the open-source embedding database for AI application development."
    )
    eid = database.insert_event(event)
    assert eid is not None

    # Chunk and embed
    chunks = create_chunks_for_event(
        event_id=eid,
        text=event.text_content,
        title=event.title,
        url=event.url,
        domain=event.domain,
        timestamp=event.timestamp
    )
    embeddings = provider.embed_documents([c["text"] for c in chunks])
    for c, emb in zip(chunks, embeddings):
        c["vector"] = emb
    store.add_chunks(chunks)

    # Execute Hybrid Retrieval
    engine = get_rag_engine()
    passages, tinfo = engine.retrieve("What is Chroma embedding database?", top_k=3)
    assert len(passages) >= 1
    assert "Chroma" in passages[0]["title"]
    assert passages[0]["url"] == "https://docs.trychroma.com"
    assert passages[0]["score"] > 0


def test_chat_endpoint_grounded_answer():
    # Setup test event and vector chunk
    provider = get_embedding_provider()
    store = backend.vector_store.get_vector_store()

    event = EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=1700000000.0,
        url="https://lancedb.com",
        domain="lancedb.com",
        title="LanceDB Architecture",
        text_content="LanceDB is a serverless vector database built on top of the Lance columnar data format."
    )
    eid = database.insert_event(event)

    chunks = create_chunks_for_event(eid, event.text_content, event.title, event.url, event.domain, timestamp=event.timestamp)
    for c, emb in zip(chunks, provider.embed_documents([c["text"] for c in chunks])):
        c["vector"] = emb
    store.add_chunks(chunks)

    # Query matching information
    chat_req = ChatRequest(message="What columnar format does LanceDB use?")
    chat_res = run_sync(chat_memory(chat_req, _=None))

    assert len(chat_res.citations) >= 1
    assert "Lance" in chat_res.citations[0].snippet or "columnar" in chat_res.citations[0].snippet
    assert chat_res.citations[0].url == "https://lancedb.com"
    assert "LanceDB" in chat_res.answer or "columnar" in chat_res.answer


def test_chat_special_commands_remember_and_forget():
    # 1. Test "remember that ..."
    rem_req = ChatRequest(message="remember that my preferred Python version is 3.12")
    rem_res = run_sync(chat_memory(rem_req, _=None))
    assert "remember that" in rem_res.answer.lower()
    assert len(rem_res.citations) == 0

    # 2. Test "forget this"
    event = EventIngestItem(
        event_type="page_visit",
        url="https://secret-domain.com/notes",
        domain="secret-domain.com",
        title="Secret Notes",
        text_content="Temporary notes"
    )
    database.insert_event(event)
    assert database.get_event_count() >= 1

    forget_req = ChatRequest(message="forget what I read on secret-domain.com")
    forget_res = run_sync(chat_memory(forget_req, _=None))
    assert "forgotten and deleted" in forget_res.answer.lower()
