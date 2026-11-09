"""
MemoryOS Reciprocal Rank Fusion (RRF) and Cross-Encoder Reranker.
Merges dense vector search and sparse BM25 results, then reranks candidates
using deep neural cross-attention (BAAI/bge-reranker-base) or lexical-semantic fallback.
"""

import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from backend import config

logger = logging.getLogger("memoryos.reranker")


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


class LexicalSemanticReranker:
    """
    Fast local lexical-semantic relevance reranker.
    Computes exact term coverage, positional proximity, and density.
    Used as primary baseline and high-speed fallback.
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

            # Combined score
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


# Alias for backward compatibility
CrossEncoderReranker = LexicalSemanticReranker


class NeuralCrossEncoderReranker:
    """
    Real neural cross-encoder using FastEmbed ONNX Runtime (BAAI/bge-reranker-base).
    Computes cross-attention score between query and candidate documents.
    Falls back to LexicalSemanticReranker if initialization or inference fails.
    """
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or config.NEURAL_RERANKER_MODEL
        self._model = None
        self._init_model()

    def _init_model(self):
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            self._model = TextCrossEncoder(model_name=self.model_name)
            logger.info(f"Initialized neural cross-encoder: {self.model_name}")
        except Exception as e:
            logger.warning(f"Could not load neural cross-encoder {self.model_name}: {e}. Running in fallback mode.")
            self._model = None

    def rerank(self, query: str, candidates: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
        if not candidates:
            return []
        if self._model is None:
            return LexicalSemanticReranker().rerank(query, candidates, top_n=top_n)

        # Prepare candidate passage texts
        documents: List[str] = []
        for c in candidates:
            title = c.get("title") or ""
            text = c.get("text") or c.get("text_content") or c.get("snippet") or ""
            documents.append(f"{title}: {text}"[:1000])

        try:
            scores = list(self._model.rerank(query, documents))
            scored_candidates: List[Tuple[float, Dict[str, Any]]] = []
            for score, c in zip(scores, candidates):
                res = dict(c)
                num_score = round(float(score), 4)
                res["rerank_score"] = num_score
                scored_candidates.append((num_score, res))

            scored_candidates.sort(key=lambda x: x[0], reverse=True)
            return [item for _, item in scored_candidates[:top_n]]
        except Exception as e:
            logger.warning(f"Neural rerank failed: {e}. Falling back to lexical scorer.")
            return LexicalSemanticReranker().rerank(query, candidates, top_n=top_n)


_reranker_instance = None


def get_reranker():
    """Retrieve active reranker instance based on configuration."""
    global _reranker_instance
    if _reranker_instance is None:
        if config.USE_NEURAL_RERANKER:
            try:
                _reranker_instance = NeuralCrossEncoderReranker(model_name=config.NEURAL_RERANKER_MODEL)
                if _reranker_instance._model is None:
                    _reranker_instance = LexicalSemanticReranker()
            except Exception:
                _reranker_instance = LexicalSemanticReranker()
        else:
            _reranker_instance = LexicalSemanticReranker()
    return _reranker_instance


def reset_reranker():
    """Reset singleton instance (used for tests toggling config flags)."""
    global _reranker_instance
    _reranker_instance = None


def get_active_reranker_info() -> Dict[str, Any]:
    """Report active reranker type and model for /api/status."""
    reranker = get_reranker()
    is_neural = isinstance(reranker, NeuralCrossEncoderReranker) and reranker._model is not None
    return {
        "active_type": "neural_cross_encoder" if is_neural else "lexical_semantic_fallback",
        "neural_enabled": config.USE_NEURAL_RERANKER,
        "model_name": config.NEURAL_RERANKER_MODEL if is_neural else "keyword_lexical_scorer"
    }
