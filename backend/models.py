"""
MemoryOS Pydantic Models for Event Ingestion, Search, and RAG Chat.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EventIngestItem(BaseModel):
    """Single activity event ingested from browser extension or desktop agent."""
    event_type: str = Field(..., description="Event type: page_visit, typed_input, text_select, scroll, active_window, etc.")
    source: str = Field(default="browser", description="Event source: browser, desktop, clipboard")
    timestamp: Optional[float] = Field(default=None, description="Unix timestamp (epoch in seconds)")
    url: Optional[str] = Field(default=None, description="URL for browser events")
    domain: Optional[str] = Field(default=None, description="Domain extracted from URL")
    title: Optional[str] = Field(default=None, description="Page title or Window title")
    app_name: Optional[str] = Field(default=None, description="Application name (Chrome, VS Code, etc.)")
    duration: Optional[float] = Field(default=0.0, description="Active time duration in seconds")
    text_content: Optional[str] = Field(default=None, description="Extracted page text, typed text, or window text")
    selected_text: Optional[str] = Field(default=None, description="Highlighted text snippet")
    scroll_depth: Optional[float] = Field(default=0.0, description="Scroll depth percentage (0 - 100)")
    referrer_url: Optional[str] = Field(default=None, description="Previous page URL from document.referrer")
    from_event_id: Optional[int] = Field(default=None, description="Referrer parent event ID")
    session_id: Optional[str] = Field(default=None, description="Session grouping identifier")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Arbitrary extra metadata")


class BatchIngestRequest(BaseModel):
    """Batch ingestion request payload."""
    events: List[EventIngestItem]


class SearchResultItem(BaseModel):
    """Result item returned by search endpoints."""
    id: int
    event_type: str
    source: str
    timestamp: float
    url: Optional[str] = None
    title: Optional[str] = None
    domain: Optional[str] = None
    app_name: Optional[str] = None
    snippet: str
    score: float
    duration: float = 0.0


class SearchResponse(BaseModel):
    """Search response wrapper."""
    query: str
    total: int
    results: List[SearchResultItem]


class CitationItem(BaseModel):
    """Structured citation referencing source activity event."""
    event_id: int
    title: str
    url: Optional[str] = None
    domain: Optional[str] = None
    source: str = "browser"
    timestamp: float
    time_str: str
    snippet: str
    score: float = 0.0


class ChatRequest(BaseModel):
    """RAG Chat request payload."""
    message: str = Field(..., description="User question or instruction")
    stream: bool = Field(default=False, description="Whether to stream response tokens")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of context passages to retrieve")
    domain: Optional[str] = Field(default=None, description="Filter memory by domain")
    app_name: Optional[str] = Field(default=None, description="Filter memory by app name")
    start_time: Optional[float] = Field(default=None, description="Filter start timestamp")
    end_time: Optional[float] = Field(default=None, description="Filter end timestamp")


class ChatResponse(BaseModel):
    """RAG Chat response payload with grounded citations."""
    answer: str
    citations: List[CitationItem]
    temporal_filter: Optional[Dict[str, Any]] = None


class StatusResponse(BaseModel):
    """API health and status response."""
    status: str
    data_dir: str
    db_path: str
    total_events: int
    total_vectors: int
    recording_active: bool
    ollama_status: str = "unknown"
