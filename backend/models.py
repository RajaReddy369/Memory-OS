"""
MemoryOS Pydantic Models for Event Ingestion and Search.
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


class StatusResponse(BaseModel):
    """API health and status response."""
    status: str
    data_dir: str
    db_path: str
    total_events: int
    recording_active: bool
