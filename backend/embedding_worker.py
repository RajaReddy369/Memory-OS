"""
MemoryOS Background Embedding Worker.
Batches text chunking and dense embeddings asynchronously so user browsing is never slowed down.
Skips fleeting page visits (< 5 seconds duration).
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import time

from backend.chunker import create_chunks_for_event
from backend.database import get_db_connection
from backend.embeddings import get_embedding_provider
from backend.vector_store import get_vector_store

logger = logging.getLogger("memoryos.worker")

# Asynchronous work queue
_queue: Optional[asyncio.Queue] = None
_worker_task: Optional[asyncio.Task] = None


def get_queue() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue(maxsize=1000)
    return _queue


async def enqueue_for_embedding(event: Dict[str, Any]):
    """
    Queue an event for background chunking and embedding.
    Filters out fleeting page visits under 5 seconds duration.
    """
    duration = float(event.get("duration") or 0.0)
    text = event.get("text_content") or ""
    event_type = event.get("event_type")

    # Filter rule: Only embed pages with meaningful time spent (skip pages open under 5s unless substantial text)
    if event_type == "page_visit" and duration < 5.0 and len(text) < 250:
        return

    if len(text.strip()) < 40:
        return

    q = get_queue()
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        logger.warning("Embedding queue full; dropping item.")


async def process_batch(items: List[Dict[str, Any]]):
    """Chunk, embed, and store a batch of activity events."""
    if not items:
        return

    provider = get_embedding_provider()
    store = get_vector_store()

    all_chunks: List[Dict[str, Any]] = []
    embedded_event_ids: List[int] = []

    for item in items:
        event_id = item["id"]
        text = item.get("text_content") or ""
        title = item.get("title") or ""
        url = item.get("url") or ""
        domain = item.get("domain") or ""
        source = item.get("source") or "browser"
        timestamp = float(item.get("timestamp") or time.time())
        session_id = item.get("session_id") or ""

        chunks = create_chunks_for_event(
            event_id=event_id,
            text=text,
            title=title,
            url=url,
            domain=domain,
            source=source,
            timestamp=timestamp,
            session_id=session_id
        )
        all_chunks.extend(chunks)
        embedded_event_ids.append(event_id)

    if not all_chunks:
        return

    try:
        # Compute embeddings in batch
        texts_to_embed = [c["text"] for c in all_chunks]
        embeddings = provider.embed_documents(texts_to_embed)

        for chunk, emb in zip(all_chunks, embeddings):
            chunk["vector"] = emb

        # Persist chunks into vector database
        store.add_chunks(all_chunks)

        # Mark events as embedded in SQLite
        conn = get_db_connection()
        try:
            with conn:
                placeholders = ",".join("?" for _ in embedded_event_ids)
                conn.execute(f"UPDATE events SET is_embedded = 1 WHERE id IN ({placeholders})", embedded_event_ids)
        finally:
            conn.close()

        logger.info(f"Successfully embedded {len(all_chunks)} chunks for {len(embedded_event_ids)} events.")
    except Exception as e:
        logger.error(f"Error processing embedding batch: {e}", exc_info=True)


async def embedding_worker_loop():
    """Continuous background loop consuming events from queue in batches."""
    q = get_queue()
    logger.info("Background embedding worker started.")

    while True:
        try:
            batch: List[Dict[str, Any]] = []
            # Wait for at least one item
            first_item = await q.get()
            batch.append(first_item)
            q.task_done()

            # Drain any other ready items up to batch size 10
            while len(batch) < 10:
                try:
                    item = q.get_nowait()
                    batch.append(item)
                    q.task_done()
                except asyncio.QueueEmpty:
                    break

            await process_batch(batch)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Unexpected error in embedding worker: {e}", exc_info=True)
            await asyncio.sleep(1.0)


def start_worker():
    """Start embedding worker in active event loop."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        try:
            loop = asyncio.get_running_loop()
            _worker_task = loop.create_task(embedding_worker_loop())
        except RuntimeError:
            pass


def stop_worker():
    """Stop embedding worker cleanly."""
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        _worker_task = None

