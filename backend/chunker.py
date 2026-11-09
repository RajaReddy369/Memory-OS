"""
MemoryOS Text Chunking Pipeline.
Splits continuous text content into overlapping semantic chunks with full parent metadata.
"""

import re
from typing import Any, Dict, List, Optional


def split_into_sentences(text: str) -> List[str]:
    """Split text into sentences while handling common abbreviations."""
    if not text:
        return []
    # Normalize whitespaces
    clean = re.sub(r"\s+", " ", text).strip()
    # Sentence splitting by period, exclamation, question mark, or newline followed by space/capital
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])|\n+", clean)
    return [s.strip() for s in sentences if s and len(s.strip()) > 3]


def chunk_text(
    text: str,
    target_chunk_chars: int = 1400,
    overlap_chars: int = 250
) -> List[str]:
    """
    Split text into chunks of roughly target_chunk_chars with overlap_chars overlap.
    Preserves sentence boundaries wherever possible.
    """
    if not text or len(text.strip()) < 50:
        return [text.strip()] if text and text.strip() else []

    sentences = split_into_sentences(text)
    if not sentences:
        return [text[:target_chunk_chars]]

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_len = 0

    for sentence in sentences:
        sentence_len = len(sentence)
        if current_len + sentence_len > target_chunk_chars and current_chunk:
            # Commit current chunk
            chunk_str = " ".join(current_chunk)
            chunks.append(chunk_str)

            # Build overlap from the end of current_chunk
            overlap_accum: List[str] = []
            overlap_len = 0
            for s in reversed(current_chunk):
                if overlap_len + len(s) <= overlap_chars:
                    overlap_accum.insert(0, s)
                    overlap_len += len(s)
                else:
                    break
            current_chunk = overlap_accum
            current_len = sum(len(s) for s in current_chunk)

        current_chunk.append(sentence)
        current_len += sentence_len

    if current_chunk:
        chunk_str = " ".join(current_chunk)
        if not chunks or chunk_str != chunks[-1]:
            chunks.append(chunk_str)

    return chunks


def create_chunks_for_event(
    event_id: int,
    text: str,
    title: Optional[str] = None,
    url: Optional[str] = None,
    domain: Optional[str] = None,
    source: str = "browser",
    timestamp: float = 0.0,
    session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Generate structured chunk records ready for vector database insertion."""
    text_chunks = chunk_text(text)
    records: List[Dict[str, Any]] = []

    for idx, chunk_text_content in enumerate(text_chunks):
        records.append({
            "id": f"{event_id}_{idx}",
            "event_id": event_id,
            "chunk_index": idx,
            "text": chunk_text_content,
            "title": title or "",
            "url": url or "",
            "domain": domain or "",
            "source": source,
            "timestamp": timestamp,
            "session_id": session_id or ""
        })

    return records

