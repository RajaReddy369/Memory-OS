"""
MemoryOS SQLite Database Module with FTS5 Full-Text Search and Journey Graph Linking.
Enables high-performance local structured storage, keyword search, and referrer tracking.
"""

import hashlib
import json
import sqlite3
import time
from typing import Any, Dict, List, Optional
from pathlib import Path

from backend.config import DB_PATH, DEFAULT_BLOCKED_DOMAINS
from backend.models import EventIngestItem, SearchResultItem
from backend.scrubber import extract_domain, is_domain_blocked, scrub_text


def get_db_connection() -> sqlite3.Connection:
    """Create a connection with WAL mode and row factory enabled."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    """Initialize database tables, indexes, FTS5 search, and schema migrations."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db_connection()
    try:
        with conn:
            # 1. Main events table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                timestamp REAL NOT NULL,
                url TEXT,
                domain TEXT,
                title TEXT,
                app_name TEXT,
                duration REAL DEFAULT 0.0,
                text_content TEXT,
                selected_text TEXT,
                scroll_depth REAL DEFAULT 0.0,
                metadata_json TEXT,
                content_hash TEXT,
                referrer_url TEXT,
                from_event_id INTEGER,
                session_id TEXT,
                is_embedded INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            );
            """)

            # Migrations: Add new columns if missing in existing table
            cursor = conn.execute("PRAGMA table_info(events);")
            columns = {row["name"] for row in cursor.fetchall()}
            for col_name, col_def in [
                ("referrer_url", "TEXT"),
                ("from_event_id", "INTEGER"),
                ("session_id", "TEXT"),
                ("is_embedded", "INTEGER DEFAULT 0"),
            ]:
                if col_name not in columns:
                    conn.execute(f"ALTER TABLE events ADD COLUMN {col_name} {col_def};")

            # Indexes for fast filtering and journey links
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_domain ON events(domain);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_app_name ON events(app_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_hash ON events(content_hash);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_from_event ON events(from_event_id);")

            # 2. FTS5 Virtual Table for BM25 full-text keyword search
            conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                title,
                domain,
                app_name,
                text_content,
                selected_text,
                content='events',
                content_rowid='id',
                tokenize='porter unicode61'
            );
            """)

            # 3. Triggers to keep FTS5 synchronized with main table
            conn.execute("""
            CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
                INSERT INTO events_fts(rowid, title, domain, app_name, text_content, selected_text)
                VALUES (new.id, new.title, new.domain, new.app_name, new.text_content, new.selected_text);
            END;
            """)

            conn.execute("""
            CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
                INSERT INTO events_fts(events_fts, rowid, title, domain, app_name, text_content, selected_text)
                VALUES('delete', old.id, old.title, old.domain, old.app_name, old.text_content, old.selected_text);
            END;
            """)

            conn.execute("""
            CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
                INSERT INTO events_fts(events_fts, rowid, title, domain, app_name, text_content, selected_text)
                VALUES('delete', old.id, old.title, old.domain, old.app_name, old.text_content, old.selected_text);
                INSERT INTO events_fts(rowid, title, domain, app_name, text_content, selected_text)
                VALUES (new.id, new.title, new.domain, new.app_name, new.text_content, new.selected_text);
            END;
            """)

            # 4. Settings table for runtime configurations
            conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            """)

            # 5. User preferences and facts table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """)
    finally:
        conn.close()


def compute_content_hash(text: Optional[str]) -> Optional[str]:
    """Compute sha256 of normalized text for deduplication."""
    if not text or len(text.strip()) < 10:
        return None
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def insert_event(item: EventIngestItem) -> Optional[int]:
    """
    Scrub, deduplicate, resolve referrer graph links, and persist a single activity event.
    Returns inserted event ID or None if skipped/blocked.
    """
    # Exclude blocked domains
    if item.url and is_domain_blocked(item.url, DEFAULT_BLOCKED_DOMAINS):
        return None

    # Determine domain if missing
    domain = item.domain or (extract_domain(item.url) if item.url else None)

    # Scrub text fields
    clean_title = scrub_text(item.title)
    clean_text = scrub_text(item.text_content)
    clean_selected = scrub_text(item.selected_text)

    # Deduplicate near-identical content if recent duplicate exists
    content_hash = compute_content_hash(clean_text)
    event_timestamp = item.timestamp if item.timestamp is not None else time.time()
    now = time.time()

    conn = get_db_connection()
    try:
        with conn:
            if content_hash:
                cursor = conn.execute(
                    """
                    SELECT id FROM events 
                    WHERE content_hash = ? AND (url = ? OR app_name = ?) AND timestamp > ?
                    LIMIT 1
                    """,
                    (content_hash, item.url, item.app_name, event_timestamp - 900)
                )
                if cursor.fetchone():
                    return None

            # Resolve from_event_id via referrer_url if not explicitly provided
            from_event_id = item.from_event_id
            if from_event_id is None and item.referrer_url:
                ref_cur = conn.execute(
                    """
                    SELECT id FROM events 
                    WHERE url = ? AND timestamp <= ? 
                    ORDER BY timestamp DESC LIMIT 1
                    """,
                    (item.referrer_url, event_timestamp)
                )
                ref_row = ref_cur.fetchone()
                if ref_row:
                    from_event_id = ref_row["id"]

            metadata_str = json.dumps(item.metadata or {})
            cursor = conn.execute(
                """
                INSERT INTO events (
                    event_type, source, timestamp, url, domain, title, app_name,
                    duration, text_content, selected_text, scroll_depth,
                    metadata_json, content_hash, referrer_url, from_event_id,
                    session_id, is_embedded, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    item.event_type,
                    item.source,
                    event_timestamp,
                    item.url,
                    domain,
                    clean_title,
                    item.app_name,
                    item.duration or 0.0,
                    clean_text,
                    clean_selected,
                    item.scroll_depth or 0.0,
                    metadata_str,
                    content_hash,
                    item.referrer_url,
                    from_event_id,
                    item.session_id,
                    now
                )
            )
            return cursor.lastrowid
    finally:
        conn.close()


def insert_events_batch(items: List[EventIngestItem]) -> int:
    """Insert batch of events efficiently; returns count of stored events."""
    stored_count = 0
    for item in items:
        if insert_event(item):
            stored_count += 1
    return stored_count


def search_events(
    query: str,
    limit: int = 25,
    domain: Optional[str] = None,
    app_name: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None
) -> List[SearchResultItem]:
    """Execute full-text BM25 keyword search using FTS5."""
    clean_query = query.strip()
    if not clean_query:
        return []

    sanitized_tokens = [re_sub for re_sub in clean_query.replace('"', "").replace("'", "").split() if re_sub]
    if not sanitized_tokens:
        return []

    # Filter stopwords for BM25 keyword query to improve natural language question recall
    stopwords = {"what", "is", "a", "an", "the", "for", "in", "on", "of", "to", "did", "do", "does", "i", "you", "about", "which", "how", "that", "was", "me", "show", "tell", "my", "we", "with"}
    content_tokens = [t for t in sanitized_tokens if t.lower() not in stopwords]
    tokens_to_use = content_tokens if content_tokens else sanitized_tokens

    fts_expression = " OR ".join([f'"{token}"*' for token in tokens_to_use])

    conn = get_db_connection()
    results: List[SearchResultItem] = []
    try:
        conditions = ["events_fts MATCH ?"]
        params: List[Any] = [fts_expression]

        if domain:
            conditions.append("e.domain = ?")
            params.append(domain)
        if app_name:
            conditions.append("e.app_name = ?")
            params.append(app_name)
        if start_time is not None:
            conditions.append("e.timestamp >= ?")
            params.append(start_time)
        if end_time is not None:
            conditions.append("e.timestamp <= ?")
            params.append(end_time)

        where_clause = " AND ".join(conditions)
        params.append(limit)

        sql = f"""
        SELECT 
            e.id,
            e.event_type,
            e.source,
            e.timestamp,
            e.url,
            e.domain,
            e.title,
            e.app_name,
            e.duration,
            snippet(events_fts, 3, '<b>', '</b>', '...', 32) AS text_snippet,
            e.selected_text,
            bm25(events_fts) AS rank_score
        FROM events_fts
        JOIN events e ON events_fts.rowid = e.id
        WHERE {where_clause}
        ORDER BY rank_score ASC
        LIMIT ?;
        """

        cursor = conn.execute(sql, params)
        for row in cursor.fetchall():
            snippet = row["text_snippet"] or row["selected_text"] or row["title"] or ""
            score = round(abs(float(row["rank_score"])), 4)
            results.append(
                SearchResultItem(
                    id=row["id"],
                    event_type=row["event_type"],
                    source=row["source"],
                    timestamp=row["timestamp"],
                    url=row["url"],
                    title=row["title"],
                    domain=row["domain"],
                    app_name=row["app_name"],
                    snippet=snippet,
                    score=score,
                    duration=row["duration"] or 0.0
                )
            )
    except sqlite3.OperationalError:
        fallback_sql = """
        SELECT id, event_type, source, timestamp, url, domain, title, app_name, duration, text_content
        FROM events
        WHERE title LIKE ? OR text_content LIKE ?
        ORDER BY timestamp DESC
        LIMIT ?
        """
        pattern = f"%{clean_query}%"
        cursor = conn.execute(fallback_sql, (pattern, pattern, limit))
        for row in cursor.fetchall():
            content = row["text_content"] or ""
            snippet = content[:200] + ("..." if len(content) > 200 else "")
            results.append(
                SearchResultItem(
                    id=row["id"],
                    event_type=row["event_type"],
                    source=row["source"],
                    timestamp=row["timestamp"],
                    url=row["url"],
                    title=row["title"],
                    domain=row["domain"],
                    app_name=row["app_name"],
                    snippet=snippet,
                    score=1.0,
                    duration=row["duration"] or 0.0
                )
            )
    finally:
        conn.close()

    return results


def get_event_count() -> int:
    """Return total number of recorded events in SQLite."""
    conn = get_db_connection()
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM events;")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def get_recent_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve most recent events."""
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """
            SELECT id, event_type, source, timestamp, url, domain, title, app_name,
                   duration, scroll_depth, referrer_url, from_event_id, session_id
            FROM events
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
