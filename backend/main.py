"""
MemoryOS FastAPI Application.
Handles secured event ingestion, WebSocket broadcasting, FTS5 search,
hybrid RAG chat with citations, streaming, and background embedding.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Set
from fastapi import FastAPI, Header, HTTPException, Query, Request, Security, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from backend.config import (
    API_TOKEN,
    CORS_ORIGIN_REGEX,
    DATA_DIR,
    DB_PATH,
    HOST,
    OLLAMA_CHAT_MODEL,
    OLLAMA_EMBEDDING_MODEL,
    OLLAMA_HOST,
    PORT,
)
from backend.database import (
    backfill_search_queries,
    delete_website_history,
    get_all_searches,
    get_db_connection,
    get_event_count,
    get_projects,
    get_recent_events,
    get_session_by_id,
    get_sessions,
    get_website_detail,
    get_websites_summary,
    init_db,
    insert_event,
    insert_events_batch,
    search_events,
)
from backend.embedding_worker import enqueue_for_embedding, start_worker, stop_worker
from backend.llm import get_llm_client
from backend.memory import handle_special_memory_commands
from backend.models import (
    BatchIngestRequest,
    ChatRequest,
    ChatResponse,
    CitationItem,
    EventIngestItem,
    SearchResponse,
    SearchResultItem,
    StatusResponse,
)
from backend.rag import format_timestamp, get_rag_engine
from backend.reranker import get_active_reranker_info
from backend.sessions import recompute_sessions
from backend.vector_store import get_vector_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("memoryos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for database initialization, worker startup, and cleanup."""
    init_db()
    try:
        backfilled = backfill_search_queries()
        if backfilled > 0:
            logger.info(f"Backfilled {backfilled} search query events from existing URLs")
    except Exception as e:
        logger.warning(f"Search backfill warning: {e}")
    start_worker()
    logger.info(f"MemoryOS started on {HOST}:{PORT}")
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info(f"Database path: {DB_PATH}")
    logger.info(f"Security token initialized (length={len(API_TOKEN)})")
    yield
    stop_worker()


app = FastAPI(
    title="MemoryOS API",
    description="Privacy-first, secured local cognitive memory engine",
    version="1.0.0",
    lifespan=lifespan
)

# Active WebSocket subscribers for live event streaming
active_websockets: Set[WebSocket] = set()

# Global recording pause state (runtime toggle)
is_recording_paused: bool = False


# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


def verify_api_key(
    x_memoryos_key: Optional[str] = Header(None, alias="X-MemoryOS-Key"),
    authorization: Optional[str] = Header(None)
):
    """
    Validate that incoming requests carry the correct secret API token.
    Prevents malicious websites running in the browser from querying or writing memory data.
    """
    token_provided = x_memoryos_key if isinstance(x_memoryos_key, str) else None

    if not token_provided and isinstance(authorization, str):
        if authorization.startswith("Bearer "):
            token_provided = authorization[7:].strip()
        else:
            token_provided = authorization.strip()

    if not token_provided or token_provided != API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing MemoryOS security token. Provide header 'X-MemoryOS-Key'."
        )


@app.get("/api/health")
async def health_check():
    """Unauthenticated health check endpoint."""
    return {
        "status": "ok",
        "service": "MemoryOS",
        "version": "1.0.0"
    }


async def check_ollama_status() -> str:
    """Check connectivity to local Ollama instance."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            res = await client.get(f"{OLLAMA_HOST}/api/tags")
            if res.status_code == 200:
                return "online"
    except Exception:
        pass
    logger.warning("[MemoryOS Warning] Local Ollama server is unreachable on %s", OLLAMA_HOST)
    return "unreachable (warning: running in fallback mode)"


@app.get("/api/status", response_model=StatusResponse)
async def get_status(_: None = Security(verify_api_key)):
    """Retrieve system status, event statistics, and Ollama connection health."""
    total_events = get_event_count()
    vector_store = get_vector_store()
    total_vectors = vector_store.count()
    ollama_stat = await check_ollama_status()

    return StatusResponse(
        status="active",
        data_dir=str(DATA_DIR),
        db_path=str(DB_PATH),
        total_events=total_events,
        total_vectors=total_vectors,
        recording_active=not is_recording_paused,
        ollama_status=ollama_stat,
        chat_model=OLLAMA_CHAT_MODEL,
        embedding_model=OLLAMA_EMBEDDING_MODEL,
        reranker=get_active_reranker_info()
    )


@app.get("/api/sessions")
async def list_sessions(
    from_time: Optional[float] = Query(None, alias="from"),
    to_time: Optional[float] = Query(None, alias="to"),
    project: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Security(verify_api_key)
):
    """Retrieve list of segmented user activity sessions."""
    sessions = get_sessions(start_time=from_time, end_time=to_time, project=project, limit=limit)
    return {"sessions": sessions, "count": len(sessions)}


@app.get("/api/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    _: None = Security(verify_api_key)
):
    """Retrieve detailed session data including ordered event graph for 3D visualization."""
    session = get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.post("/api/sessions/segment")
async def trigger_session_segmentation(
    start_time: Optional[float] = Query(None),
    end_time: Optional[float] = Query(None),
    _: None = Security(verify_api_key)
):
    """Trigger on-demand re-computation of activity sessions."""
    created = await recompute_sessions(start_time=start_time, end_time=end_time)
    return {"status": "ok", "sessions_created": len(created), "sessions": created}


@app.post("/api/recording/toggle")
async def toggle_recording(paused: Optional[bool] = None, _: None = Security(verify_api_key)):
    """Toggle or set recording pause state."""
    global is_recording_paused
    if paused is not None:
        is_recording_paused = paused
    else:
        is_recording_paused = not is_recording_paused

    await broadcast_ws({"type": "status_change", "recording_active": not is_recording_paused})
    return {"recording_active": not is_recording_paused}


@app.post("/api/events/ingest")
async def ingest_single_event(
    event: EventIngestItem,
    _: None = Security(verify_api_key)
):
    """Ingest a single activity event and enqueue for background embedding."""
    if is_recording_paused:
        return {"status": "paused", "stored": False}

    event_id = insert_event(event)
    if event_id:
        event_dict = event.model_dump()
        event_dict["id"] = event_id
        await enqueue_for_embedding(event_dict)

        await broadcast_ws({
            "type": "new_event",
            "event": {
                "id": event_id,
                "event_type": event.event_type,
                "source": event.source,
                "title": event.title,
                "url": event.url,
                "domain": event.domain,
                "app_name": event.app_name,
                "timestamp": event.timestamp,
                "duration": event.duration,
                "referrer_url": event.referrer_url,
                "from_event_id": event.from_event_id
            }
        })
        return {"status": "ok", "id": event_id, "stored": True}
    return {"status": "skipped", "stored": False}


@app.post("/api/events/batch")
async def ingest_batch_events(
    batch: BatchIngestRequest,
    _: None = Security(verify_api_key)
):
    """Ingest a batch of activity events."""
    if is_recording_paused:
        return {"status": "paused", "stored_count": 0}

    stored_count = 0
    for item in batch.events:
        eid = insert_event(item)
        if eid:
            stored_count += 1
            d = item.model_dump()
            d["id"] = eid
            await enqueue_for_embedding(d)

    return {"status": "ok", "stored_count": stored_count}


@app.get("/api/events/recent")
async def get_recent(
    limit: int = Query(50, ge=1, le=200),
    _: None = Security(verify_api_key)
):
    """Fetch recent recorded activity events."""
    limit_val = limit if isinstance(limit, int) else 50
    events = get_recent_events(limit=limit_val)
    return {"events": events}


@app.get("/api/search", response_model=SearchResponse)
async def search_memory(
    q: str = Query(..., min_length=1, description="Keywords to search in memory"),
    limit: int = Query(25, ge=1, le=100),
    domain: Optional[str] = Query(None),
    app_name: Optional[str] = Query(None),
    start_time: Optional[float] = Query(None),
    end_time: Optional[float] = Query(None),
    _: None = Security(verify_api_key)
):
    """Search memory events using SQLite FTS5 BM25 index."""
    limit_val = limit if isinstance(limit, int) else 25
    domain_val = domain if isinstance(domain, str) else None
    app_val = app_name if isinstance(app_name, str) else None
    start_val = start_time if isinstance(start_time, (int, float)) else None
    end_val = end_time if isinstance(end_time, (int, float)) else None

    results = search_events(
        query=q,
        limit=limit_val,
        domain=domain_val,
        app_name=app_val,
        start_time=start_val,
        end_time=end_val
    )
    return SearchResponse(
        query=q,
        total=len(results),
        results=results
    )


@app.post("/api/chat")
async def chat_memory(
    req: ChatRequest,
    _: None = Security(verify_api_key)
):
    """
    RAG Chat endpoint. Grounded question-answering with structured citations.
    Supports natural language time filtering ('last Tuesday', 'yesterday afternoon')
    and streaming responses.
    """
    # 1. Check for 'remember that ...' or 'forget this ...' instructions
    special_reply = handle_special_memory_commands(req.message)
    if special_reply:
        return ChatResponse(
            answer=special_reply,
            citations=[],
            temporal_filter=None
        )

    # 2. Hybrid Retrieval (Time-aware + Dense + BM25 + Cross-Encoder)
    rag_engine = get_rag_engine()
    passages, temporal_info = rag_engine.retrieve(
        query=req.message,
        top_k=req.top_k,
        domain=req.domain,
        app_name=req.app_name,
        start_time_override=req.start_time,
        end_time_override=req.end_time
    )

    # Check for matching work sessions in the requested timeframe
    st = temporal_info.get("start_time") or req.start_time
    et = temporal_info.get("end_time") or req.end_time
    if st is not None and et is not None:
        matching_sessions = get_sessions(start_time=st, end_time=et, limit=3)
        for s in reversed(matching_sessions):
            passages.insert(0, {
                "id": s["id"],
                "event_id": 0,
                "title": f"Session: {s['title']} [{s['project_label']}]",
                "url": f"/api/sessions/{s['id']}",
                "domain": s.get("primary_domain") or s.get("primary_app") or "desktop",
                "source": "session",
                "timestamp": s["start_time"],
                "time_str": format_timestamp(s["start_time"]),
                "snippet": f"Session Summary: {s['summary']} Duration: {round(s['duration']/60, 1)} minutes across {s['event_count']} actions in {s.get('primary_app', 'desktop')}.",
                "score": 0.95
            })

    citations = [
        CitationItem(
            event_id=int(p.get("event_id") or p.get("id") or 0) if str(p.get("event_id") or p.get("id") or "0").isdigit() else 0,
            title=p.get("title") or "Untitled",
            url=p.get("url"),
            domain=p.get("domain"),
            source=p.get("source") or "browser",
            timestamp=float(p.get("timestamp") or 0.0),
            time_str=p.get("time_str") or "",
            snippet=p.get("snippet") or "",
            score=float(p.get("score") or 0.0)
        )
        for p in passages
    ]

    llm_client = get_llm_client()

    # 3. Handle Streaming Response
    if req.stream:
        async def stream_generator() -> AsyncGenerator[str, None]:
            # Send citations first as metadata event
            citations_meta = {
                "type": "citations",
                "citations": [c.model_dump() for c in citations],
                "temporal_filter": temporal_info
            }
            yield f"data: {json.dumps(citations_meta)}\n\n"

            # Stream LLM tokens
            async for token in llm_client.stream_generate(req.message, passages):
                yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    # 4. Standard Non-Streaming Response
    if not passages:
        answer = "I couldn't find that in your memory."
    else:
        answer = await llm_client.generate(req.message, passages)

    return ChatResponse(
        answer=answer,
        citations=citations,
        temporal_filter=temporal_info
    )


async def broadcast_ws(payload: dict):
    """Send real-time updates to connected WebSockets."""
    if not active_websockets:
        return
    message = json.dumps(payload)
    stale = []
    for ws in active_websockets:
        try:
            await ws.send_text(message)
        except Exception:
            stale.append(ws)
    for ws in stale:
        active_websockets.discard(ws)


@app.websocket("/ws/events")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
):
    """Live WebSocket feed for events. Requires valid security token in query param."""
    if token != API_TOKEN:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    active_websockets.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        active_websockets.discard(websocket)
    except Exception:
        active_websockets.discard(websocket)


# ==============================================================================
# Websites & Search Query Log Endpoints
# ==============================================================================

@app.get("/api/websites")
async def get_websites_endpoint(
    from_time: Optional[float] = Query(None, alias="from"),
    to_time: Optional[float] = Query(None, alias="to"),
    q: Optional[str] = Query(None),
    _: None = Security(verify_api_key)
):
    """
    Retrieve aggregated activity records per visited website domain.
    Returns: domain, first_visit, last_visit, total_visits, total_active_time, and pages visited.
    """
    return get_websites_summary(from_time=from_time, to_time=to_time, q=q)


@app.get("/api/websites/{domain:path}")
async def get_website_detail_endpoint(
    domain: str,
    _: None = Security(verify_api_key)
):
    """
    Retrieve full chronological activity log for a specific website domain:
    pages visited, search queries, typed text (scrubbed), highlights, and referrer navigation links.
    """
    detail = get_website_detail(domain)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No activity records found for domain '{domain}' or domain is restricted."
        )
    return detail


@app.delete("/api/websites/{domain:path}")
async def delete_website_endpoint(
    domain: str,
    _: None = Security(verify_api_key)
):
    """
    Delete all activity records for a specific website domain across events and FTS5.
    """
    count = delete_website_history(domain)
    return {
        "status": "success",
        "domain": domain,
        "deleted_count": count
    }


@app.post("/api/websites/backfill")
async def backfill_websites_endpoint(
    _: None = Security(verify_api_key)
):
    """
    Run extraction of search queries over existing page visit URLs in database.
    """
    count = backfill_search_queries()
    return {
        "status": "success",
        "backfilled_count": count
    }


@app.get("/api/searches")
async def get_searches_endpoint(
    domain: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    from_time: Optional[float] = Query(None, alias="from"),
    to_time: Optional[float] = Query(None, alias="to"),
    limit: int = Query(500),
    _: None = Security(verify_api_key)
):
    """
    Retrieve all search queries across every visited website in a unified chronological timeline.
    """
    return get_all_searches(domain=domain, q=q, from_time=from_time, to_time=to_time, limit=limit)


def main():
    """Convenience runner function."""
    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
