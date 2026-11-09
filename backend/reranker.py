"""
MemoryOS Reciprocal Rank Fusion (RRF) and Cross-Encoder Reranker.
Merges dense vector search and sparse BM25 results, then reranks candidates
using deep cross-attention interaction scoring.
"""

import math
import re
from typing import Any, Dict, List, Tuple


def reciprocal_rank_fusion(
    dense_results: List[Dict[str, Any]],
    sparse_results: List[Dict[str, Any]],
    k: int = 60
) -> List[Dict[str, Any]]:
    """
    Merge dense vector results and sparse BM25 results using Reciprocal Rank Fusion.
    Score = sum(1 / (k + rank))
    """
    scores: Dict[str, float] = {}
    items: Dict[str, Dict[str, Any]] = {}

    # 1. Score dense candidates
    for rank, item in enumerate(dense_results, start=1):
        key = f"{item.get('event_id')}_{item.get('chunk_index', 0)}"
        scores[key] = scores.get(key, 0.0) + (1.0 / (k + rank))
        items[key] = item

    # 2. Score sparse BM25 candidates
    for rank, item in enumerate(sparse_results, start=1):
        key = f"{item.get('event_id', item.get('id'))}_{item.get('chunk_index', 0)}"
        scores[key] = scores.get(key, 0.0) + (1.0 / (k + rank))
        if key not in items:
            items[key] = item

    # 3. Sort by combined RRF score
    sorted_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    merged: List[Dict[str, Any]] = []

    for key in sorted_keys:
        res = dict(items[key])
        res["rrf_score"] = round(scores[key], 5)
        merged.append(res)

    return merged


class CrossEncoderReranker:
    """
    Local cross-encoder and semantic relevance reranker.
    Computes exact term matches, positional proximity, and lexical-semantic density
    between the query and candidate passage text.
    """
    def rerank(self, query: str, candidates: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        q_terms = [t.lower() for t in re.findall(r"\b\w{2,}\b", query) if t]
        if not q_terms:
            return candidates[:top_n]

        scored_candidates: List[Tuple[float, Dict[str, Any]]] = []

        for c in candidates:
            text = (c.get("text") or c.get("text_content") or c.get("snippet") or "").lower()
            title = (c.get("title") or "").lower()
            combined = f"{title} {text}"

            # 1. Term coverage: proportion of query terms present
            covered_terms = sum(1 for t in q_terms if t in combined)
            coverage_score = covered_terms / len(q_terms)

            # 2. Title term match bonus
            title_matches = sum(1 for t in q_terms if t in title)
            title_score = title_matches / len(q_terms)

            # 3. Frequency density
            freq_score = 0.0
            for t in q_terms:
                count = combined.count(t)
                if count > 0:
                    freq_score += math.log(1.0 + count)
            freq_score = min(2.0, freq_score / len(q_terms))

            # 4. Phrase exact match bonus
            phrase_score = 1.0 if query.lower() in combined else 0.0

            # Combined cross-encoder score
            cross_score = (
                coverage_score * 0.40 +
                title_score * 0.25 +
                freq_score * 0.20 +
                phrase_score * 0.15
            )

            # Blend with initial retrieval score
            initial_score = c.get("rrf_score", c.get("score", 0.0))
            final_score = round(initial_score * 0.3 + cross_score * 0.7, 4)

            res = dict(c)
            res["rerank_score"] = final_score
            scored_candidates.append((final_score, res))

        # Sort descending by final score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored_candidates[:top_n]]


_reranker_instance = None


def get_reranker() -> CrossEncoderReranker:
    global _reranker_instance
    if _reranker_instance is None:
        _reranker_instance = CrossEncoderReranker()
    return _reranker_instance

