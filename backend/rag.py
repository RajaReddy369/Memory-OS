"""
MemoryOS Hybrid RAG Engine.
Combines time-aware query parsing, dense vector similarity, SQLite FTS5 BM25,
Reciprocal Rank Fusion, and cross-encoder reranking.
"""

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.database import search_events
from backend.embeddings import get_embedding_provider
from backend.reranker import get_reranker, reciprocal_rank_fusion
from backend.temporal import parse_temporal_query
from backend.vector_store import get_vector_store

logger = logging.getLogger("memoryos.rag")


def format_timestamp(ts: float) -> str:
    """Format Unix timestamp into human-readable local date/time string."""
    try:
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%b %d, %Y, %I:%M %p")
    except Exception:
        return "Unknown Date"


class HybridRAGEngine:
    """Performs time-aware, multi-source hybrid retrieval."""

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        domain: Optional[str] = None,
        source: Optional[str] = None,
        app_name: Optional[str] = None,
        start_time_override: Optional[float] = None,
        end_time_override: Optional[float] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Execute full hybrid retrieval pipeline:
        1. Extract natural language temporal constraints ("last Tuesday", "yesterday afternoon")
        2. Query SQLite FTS5 (sparse BM25)
        3. Query Vector Store (dense embeddings)
        4. Merge with Reciprocal Rank Fusion (RRF)
        5. Rerank top candidates with cross-encoder
        """
        # 1. Parse time
        clean_query, start_ts, end_ts = parse_temporal_query(query)
        if start_time_override is not None:
            start_ts = start_time_override
        if end_time_override is not None:
            end_ts = end_time_override

        temporal_info = {
            "parsed_query": clean_query,
            "start_time": start_ts,
            "end_time": end_ts,
            "start_str": format_timestamp(start_ts) if start_ts else None,
            "end_str": format_timestamp(end_ts) if end_ts else None
        }

        # 2. Sparse Search (BM25 via FTS5)
        # Fall back to original query if temporal parser stripped everything
        search_text = clean_query if len(clean_query.strip()) >= 2 else query
        sparse_hits = search_events(
            query=search_text,
            limit=25,
            domain=domain,
            app_name=app_name,
            start_time=start_ts,
            end_time=end_ts
        )
        sparse_candidates = [hit.model_dump() for hit in sparse_hits]

        # 3. Dense Search (LanceDB / Vector Store)
        vector_store = get_vector_store()
        provider = get_embedding_provider()
        query_vector = provider.embed_query(search_text)

        dense_candidates = vector_store.search(
            query_vector=query_vector,
            limit=25,
            start_time=start_ts,
            end_time=end_ts,
            domain=domain,
            source=source
        )

        # 4. Reciprocal Rank Fusion
        fused = reciprocal_rank_fusion(dense_candidates, sparse_candidates, k=60)

        # 5. Cross-Encoder Reranker
        reranker = get_reranker()
        top_passages = reranker.rerank(query=search_text, candidates=fused, top_n=top_k)

        # Format citations
        formatted_results: List[Dict[str, Any]] = []
        for p in top_passages:
            ts = float(p.get("timestamp") or 0.0)
            text_snippet = p.get("text") or p.get("snippet") or p.get("text_content") or ""
            # Truncate snippet if too long
            if len(text_snippet) > 400:
                text_snippet = text_snippet[:397] + "..."

            formatted_results.append({
                "id": p.get("id"),
                "event_id": p.get("event_id") or p.get("id"),
                "title": p.get("title") or "Untitled Page",
                "url": p.get("url") or "",
                "domain": p.get("domain") or "",
                "source": p.get("source") or "browser",
                "timestamp": ts,
                "time_str": format_timestamp(ts),
                "snippet": text_snippet,
                "score": p.get("rerank_score", p.get("rrf_score", 0.0))
            })

        return formatted_results, temporal_info


_rag_engine_instance = None


def get_rag_engine() -> HybridRAGEngine:
    global _rag_engine_instance
    if _rag_engine_instance is None:
        _rag_engine_instance = HybridRAGEngine()
    return _rag_engine_instance
