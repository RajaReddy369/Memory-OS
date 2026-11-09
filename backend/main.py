"""
MemoryOS FastAPI Application.
Handles secured event ingestion, WebSocket broadcasting, FTS5 search, and health status.
"""

import asyncio
import json
import logging
from typing import List, Optional, Set
from fastapi import FastAPI, Header, HTTPException, Query, Request, Security, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import API_TOKEN, CORS_ORIGIN_REGEX, DATA_DIR, DB_PATH, HOST, PORT
from backend.database import (
    get_db_connection,
    get_event_count,
    get_recent_events,
    init_db,
    insert_event,
    insert_events_batch,
    search_events,
)
from backend.models import (
    BatchIngestRequest,
    EventIngestItem,
    SearchResponse,
    SearchResultItem,
    StatusResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("memoryos")

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for database initialization and cleanup."""
    init_db()
    logger.info(f"MemoryOS started on {HOST}:{PORT}")
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info(f"Database path: {DB_PATH}")
    logger.info(f"Security token initialized (length={len(API_TOKEN)})")
    yield

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
    allow_methods=["GET", "POST", "OPTIONS"],
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


@app.get("/api/status", response_model=StatusResponse)
async def get_status(_: None = Security(verify_api_key)):
    """Retrieve system status and event statistics."""
    total = get_event_count()
    return StatusResponse(
        status="active",
        data_dir=str(DATA_DIR),
        db_path=str(DB_PATH),
        total_events=total,
        recording_active=not is_recording_paused
    )


@app.post("/api/recording/toggle")
async def toggle_recording(paused: Optional[bool] = None, _: None = Security(verify_api_key)):
    """Toggle or set recording pause state."""
    global is_recording_paused
    if paused is not None:
        is_recording_paused = paused
    else:
        is_recording_paused = not is_recording_paused
    
    # Broadcast status change to connected UI clients
    await broadcast_ws({"type": "status_change", "recording_active": not is_recording_paused})
    return {"recording_active": not is_recording_paused}


@app.post("/api/events/ingest")
async def ingest_single_event(
    event: EventIngestItem,
    _: None = Security(verify_api_key)
):
    """Ingest a single activity event."""
    if is_recording_paused:
        return {"status": "paused", "stored": False}

    event_id = insert_event(event)
    if event_id:
        # Broadcast event to WebSocket subscribers for live dashboard
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
                "duration": event.duration
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

    stored_count = insert_events_batch(batch.events)
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
    # Ensure parameter types are primitives when called internally or via test
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
            # Keep-alive loop and receiver for client pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        active_websockets.discard(websocket)
    except Exception:
        active_websockets.discard(websocket)


def main():
    """Convenience runner function."""
    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
