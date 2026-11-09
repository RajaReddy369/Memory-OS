"""
MemoryOS RAG Benchmark & Evaluation Suite.
Tests hybrid retrieval (dense + BM25 + RRF + cross-encoder) and answer faithfulness
across 12 ground-truth question/answer pairs.
"""

from datetime import datetime, timedelta
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add workspace to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import database
from backend.chunker import create_chunks_for_event
from backend.embeddings import get_embedding_provider
from backend.models import EventIngestItem
from backend.rag import get_rag_engine
from backend.vector_store import SQLiteDenseVectorStore, get_vector_store

# Ground truth test dataset
TEST_CORPUS = [
    {
        "id": 1,
        "title": "Chroma Vector Database Guide",
        "url": "https://docs.trychroma.com/getting-started",
        "domain": "docs.trychroma.com",
        "time_offset_days": 1, # Yesterday
        "time_hour": 14, # Afternoon
        "content": "Chroma is the AI-native open-source embedding database. Chroma makes it easy to build LLM apps by making knowledge, facts, and skills pluggable for LLMs."
    },
    {
        "id": 2,
        "title": "Retrieval Augmented Generation Overview",
        "url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
        "domain": "en.wikipedia.org",
        "time_offset_days": 1,
        "time_hour": 10, # Morning
        "content": "Retrieval-augmented generation (RAG) is an AI framework for improving the quality of LLM-generated responses by grounding the model on external sources of knowledge."
    },
    {
        "id": 3,
        "title": "LanceDB Columnar Storage Architecture",
        "url": "https://lancedb.github.io/lancedb/architecture",
        "domain": "lancedb.github.io",
        "time_offset_days": 3,
        "time_hour": 16,
        "content": "LanceDB is an open-source serverless vector database built on top of the Lance columnar data format, delivering fast random access and vector search."
    },
    {
        "id": 4,
        "title": "FastAPI Web Framework Tutorial",
        "url": "https://fastapi.tiangolo.com/tutorial/",
        "domain": "fastapi.tiangolo.com",
        "time_offset_days": 0, # Today
        "time_hour": 8, # Morning
        "content": "FastAPI is a modern, fast (high-performance) web framework for building APIs with Python 3.8+ based on standard Python type hints."
    },
    {
        "id": 5,
        "title": "Reciprocal Rank Fusion in Information Retrieval",
        "url": "https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf",
        "domain": "uwaterloo.ca",
        "time_offset_days": 7, # Last week
        "time_hour": 15,
        "content": "Reciprocal Rank Fusion (RRF) is a simple yet effective method for combining multiple ranked lists by summing the reciprocal of their ranks with a constant k=60."
    },
    {
        "id": 6,
        "title": "SQLite FTS5 Extension Documentation",
        "url": "https://www.sqlite.org/fts5.html",
        "domain": "sqlite.org",
        "time_offset_days": 0,
        "time_hour": 11,
        "content": "FTS5 is an SQLite virtual table module that provides full-text search capability to database applications, implementing the BM25 ranking algorithm."
    }
]

BENCHMARK_QUERIES = [
    {
        "query": "What is Chroma database used for?",
        "expected_url": "https://docs.trychroma.com/getting-started",
        "must_contain": ["chroma", "embedding"]
    },
    {
        "query": "What does RAG stand for?",
        "expected_url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
        "must_contain": ["retrieval-augmented generation"]
    },
    {
        "query": "Which vector database uses the Lance columnar format?",
        "expected_url": "https://lancedb.github.io/lancedb/architecture",
        "must_contain": ["lancedb", "columnar"]
    },
    {
        "query": "How does Reciprocal Rank Fusion combine rankings?",
        "expected_url": "https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf",
        "must_contain": ["reciprocal", "rank"]
    },
    {
        "query": "What ranking algorithm is implemented by SQLite FTS5?",
        "expected_url": "https://www.sqlite.org/fts5.html",
        "must_contain": ["bm25", "fts5"]
    },
    {
        "query": "FastAPI web framework Python",
        "expected_url": "https://fastapi.tiangolo.com/tutorial/",
        "must_contain": ["fastapi", "python"]
    },
    {
        "query": "What was that article about vector databases I read yesterday afternoon?",
        "expected_url": "https://docs.trychroma.com/getting-started",
        "must_contain": ["chroma"]
    },
    {
        "query": "Show me what I read this morning on fastapi.tiangolo.com",
        "expected_url": "https://fastapi.tiangolo.com/tutorial/",
        "must_contain": ["fastapi"]
    },
    {
        "query": "What did I read about external knowledge for LLMs yesterday morning?",
        "expected_url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
        "must_contain": ["rag", "retrieval"]
    },
    {
        "query": "What is the constant k used in RRF last week?",
        "expected_url": "https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf",
        "must_contain": ["60", "rrf"]
    },
    {
        "query": "What recipe did I look up for chocolate cake?",
        "expected_url": None, # Negative query
        "must_contain": []
    },
    {
        "query": "Who won the basketball championship last night?",
        "expected_url": None, # Negative query
        "must_contain": []
    }
]


def setup_eval_data(now: datetime, vector_store: Optional[SQLiteDenseVectorStore] = None) -> SQLiteDenseVectorStore:
    """Populate test database with time-anchored corpus."""
    database.init_db()
    if vector_store is None:
        vector_store = SQLiteDenseVectorStore()
    provider = get_embedding_provider()

    for doc in TEST_CORPUS:
        target_date = now.date() - timedelta(days=doc["time_offset_days"])
        ts = datetime.combine(target_date, datetime.min.time()).replace(hour=doc["time_hour"]).timestamp()

        item = EventIngestItem(
            event_type="page_visit",
            source="browser",
            timestamp=ts,
            url=doc["url"],
            domain=doc["domain"],
            title=doc["title"],
            text_content=doc["content"],
            duration=45.0
        )
        eid = database.insert_event(item)
        if eid:
            chunks = create_chunks_for_event(
                event_id=eid,
                text=doc["content"],
                title=doc["title"],
                url=doc["url"],
                domain=doc["domain"],
                timestamp=ts
            )
            embeddings = provider.embed_documents([c["text"] for c in chunks])
            for c, emb in zip(chunks, embeddings):
                c["vector"] = emb
            vector_store.add_chunks(chunks)

    return vector_store


def run_evaluation() -> Dict[str, Any]:
    """Run recall@5 and answer faithfulness benchmarks."""
    now = datetime.now()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "eval_memoryos.db"
        vec_path = Path(tmpdir) / "eval_vectors.db"
        database.DB_PATH = db_path

        vec_store = SQLiteDenseVectorStore(vec_path)
        # Monkeypatch vector store singleton
        import backend.vector_store
        backend.vector_store._vector_store_instance = vec_store

        setup_eval_data(now, vec_store)

        engine = get_rag_engine()
        results: List[Dict[str, Any]] = []
        hits_at_5 = 0
        faithfulness_scores = []
        total_evaluable = 0

        for test in BENCHMARK_QUERIES:
            t0 = time.perf_counter()
            passages, temporal_info = engine.retrieve(query=test["query"], top_k=5)
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)

            expected_url = test["expected_url"]
            retrieved_urls = [p["url"] for p in passages]

            is_hit = False
            faithfulness = 1.0

            if expected_url is not None:
                total_evaluable += 1
                if expected_url in retrieved_urls:
                    hits_at_5 += 1
                    is_hit = True

                # Faithfulness check: check presence of key concepts in top snippet
                top_text = (passages[0]["snippet"] if passages else "").lower()
                matched_must = sum(1 for term in test["must_contain"] if term.lower() in top_text)
                faithfulness = matched_must / len(test["must_contain"]) if test["must_contain"] else 1.0
                faithfulness_scores.append(faithfulness)
            else:
                # Negative query test: should return empty or low score
                is_hit = len(passages) == 0 or passages[0]["score"] < 0.25
                faithfulness = 1.0 if is_hit else 0.5
                faithfulness_scores.append(faithfulness)

            results.append({
                "query": test["query"],
                "expected": expected_url,
                "hit_at_5": is_hit,
                "latency_ms": latency_ms,
                "top_result": passages[0]["title"] if passages else "None",
                "faithfulness": round(faithfulness, 2)
            })

        recall_5 = round((hits_at_5 / total_evaluable) * 100, 1) if total_evaluable else 0.0
        avg_faithfulness = round((sum(faithfulness_scores) / len(faithfulness_scores)) * 100, 1)
        avg_latency = round(sum(r["latency_ms"] for r in results) / len(results), 2)

        return {
            "total_queries": len(BENCHMARK_QUERIES),
            "recall_at_5": f"{recall_5}%",
            "faithfulness": f"{avg_faithfulness}%",
            "avg_latency_ms": f"{avg_latency}ms",
            "detailed_results": results
        }


if __name__ == "__main__":
    print("=" * 60)
    print("       MemoryOS RAG Benchmark & Evaluation Suite       ")
    print("=" * 60)
    report = run_evaluation()
    print(f"Total Test Cases   : {report['total_queries']}")
    print(f"Retrieval Recall@5 : {report['recall_at_5']}")
    print(f"Answer Faithfulness: {report['faithfulness']}")
    print(f"Average Latency    : {report['avg_latency_ms']}")
    print("-" * 60)
    for r in report["detailed_results"]:
        status_icon = "✓" if r["hit_at_5"] else "✗"
        print(f"[{status_icon}] Query: {r['query'][:45]:<45} | Hit: {r['hit_at_5']} | Latency: {r['latency_ms']}ms")
    print("=" * 60)
