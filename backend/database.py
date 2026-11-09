"""
MemoryOS SQLite Database Module with FTS5 Full-Text Search and Journey Graph Linking.
Enables high-performance local structured storage, keyword search, and referrer tracking.
"""

import hashlib
import json
import math
import sqlite3
import time
from typing import Any, Dict, List, Optional
from pathlib import Path

from backend.config import DB_PATH, DEFAULT_BLOCKED_DOMAINS, FETCH_YOUTUBE_TRANSCRIPTS
from backend.models import EventIngestItem, SearchResultItem
from backend.scrubber import extract_domain, is_domain_blocked, scrub_text
from backend.search_extractor import extract_search_query, extract_youtube_video_id


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

            # 6. Sessions, session events, and projects tables (Phase 3)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                project_label TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                duration REAL NOT NULL,
                event_count INTEGER NOT NULL,
                primary_app TEXT,
                primary_domain TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS session_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_id INTEGER NOT NULL,
                sequence_order INTEGER NOT NULL,
                app_or_domain TEXT,
                referrer_url TEXT,
                from_event_id INTEGER,
                timestamp REAL NOT NULL
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                name TEXT PRIMARY KEY,
                description TEXT,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                total_duration REAL DEFAULT 0.0,
                session_count INTEGER DEFAULT 0
            );
            """)

            # 7. YouTube Videos Table (Stage 2)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS youtube_videos (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                channel TEXT,
                description TEXT,
                duration REAL DEFAULT 0.0,
                play_time REAL DEFAULT 0.0,
                upload_date TEXT,
                search_query TEXT,
                referrer_url TEXT,
                event_id INTEGER,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_yt_query ON youtube_videos(search_query);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_yt_created ON youtube_videos(created_at);")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_time ON sessions(start_time, end_time);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_label);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session_events_sid ON session_events(session_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session_events_eid ON session_events(event_id);")

            # 8. Unified Graph Store (Nodes & Edges for Apps, Documents, Websites, and GraphRAG)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                label TEXT NOT NULL,
                weight REAL DEFAULT 0.0,
                source TEXT,
                parent_id TEXT,
                properties TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_gn_type ON graph_nodes(node_type);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_gn_parent ON graph_nodes(parent_id);")

            conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_edges (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                confidence TEXT DEFAULT 'confirmed',
                properties TEXT,
                created_at REAL NOT NULL
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ge_source ON graph_edges(source_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ge_target ON graph_edges(target_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ge_type ON graph_edges(edge_type);")
    finally:
        conn.close()


def upsert_youtube_video(
    video_id: str,
    title: str,
    channel: Optional[str] = None,
    description: Optional[str] = None,
    duration: float = 0.0,
    play_time: float = 0.0,
    upload_date: Optional[str] = None,
    search_query: Optional[str] = None,
    referrer_url: Optional[str] = None,
    event_id: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None
) -> None:
    """Insert or update a watched YouTube video record with real play time and search query link."""
    now = time.time()
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    try:
        cur = conn.execute("SELECT play_time, search_query, duration FROM youtube_videos WHERE video_id = ?", (video_id,))
        row = cur.fetchone()
        if row:
            new_play_time = max(float(row["play_time"] or 0.0), play_time)
            effective_query = search_query or row["search_query"]
            effective_duration = duration if duration > 0 else float(row["duration"] or 0.0)
            conn.execute("""
            UPDATE youtube_videos SET
                title = ?,
                channel = COALESCE(?, channel),
                description = COALESCE(?, description),
                duration = ?,
                play_time = ?,
                upload_date = COALESCE(?, upload_date),
                search_query = ?,
                referrer_url = COALESCE(?, referrer_url),
                event_id = COALESCE(?, event_id),
                updated_at = ?
            WHERE video_id = ?
            """, (title, channel, description, effective_duration, new_play_time, upload_date, effective_query, referrer_url, event_id, now, video_id))
        else:
            conn.execute("""
            INSERT INTO youtube_videos (
                video_id, title, channel, description, duration, play_time,
                upload_date, search_query, referrer_url, event_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (video_id, title, channel, description, duration, play_time, upload_date, search_query, referrer_url, event_id, now, now))
        if should_close:
            conn.commit()
    finally:
        if should_close:
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

    # For YouTube videos, assemble title + channel + description if text_content is not set
    if (item.event_type == "youtube_video" or (domain and "youtube.com" in domain)) and not clean_text:
        meta = item.metadata or {}
        ch = meta.get("channel") or ""
        desc = meta.get("description") or ""
        clean_text = scrub_text(f"{clean_title} ({ch}). {desc}".strip())

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

            # Referrer fallback: attach orphan page/video to nearest earlier search in same session or past 30 mins
            if from_event_id is None and item.event_type not in ("search_query", "window_focus", "clipboard"):
                fb_cond = ["event_type = 'search_query'", "timestamp <= ?", "timestamp >= ?"]
                fb_params: List[Any] = [event_timestamp, event_timestamp - 1800]
                if item.session_id:
                    fb_cond.append("session_id = ?")
                    fb_params.append(item.session_id)
                fb_cur = conn.execute(
                    f"SELECT id, url FROM events WHERE {' AND '.join(fb_cond)} ORDER BY timestamp DESC LIMIT 1",
                    fb_params
                )
                fb_row = fb_cur.fetchone()
                if fb_row:
                    from_event_id = fb_row["id"]
                    if not item.referrer_url:
                        item.referrer_url = fb_row["url"]

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
            last_id = cursor.lastrowid

            # 1. Automatic Search-Query extraction from page URLs
            if item.event_type != "search_query" and item.url:
                extracted = extract_search_query(item.url)
                if extracted:
                    query_text, engine_name = extracted
                    sq_meta = json.dumps({
                        "query": query_text,
                        "engine": engine_name,
                        "parent_event_id": last_id,
                        "extracted_from_url": True
                    })
                    sq_title = f"{engine_name} Search: {query_text}"
                    conn.execute(
                        """
                        INSERT INTO events (
                            event_type, source, timestamp, url, domain, title, app_name,
                            duration, text_content, selected_text, scroll_depth,
                            metadata_json, content_hash, referrer_url, from_event_id,
                            session_id, is_embedded, created_at
                        ) VALUES ('search_query', ?, ?, ?, ?, ?, ?, 0.0, ?, NULL, 0.0, ?, NULL, ?, ?, ?, 0, ?)
                        """,
                        (
                            item.source,
                            event_timestamp,
                            item.url,
                            domain,
                            sq_title,
                            item.app_name,
                            query_text,
                            sq_meta,
                            item.referrer_url,
                            last_id,
                            item.session_id,
                            now
                        )
                    )

            # 2. Capture search queries from debounced typed input in search boxes
            if item.event_type == "typed_input" and clean_text:
                meta = item.metadata or {}
                elem_id = str(meta.get("elementId") or "").lower()
                elem_name = str(meta.get("name") or "").lower()
                is_search_box = (
                    meta.get("type") == "search"
                    or "search" in elem_id
                    or "query" in elem_id
                    or "search" in elem_name
                    or "query" in elem_name
                    or (domain and any(k in domain for k in ["google", "bing", "duckduckgo", "youtube", "amazon", "github", "reddit", "stackoverflow"]))
                )
                if is_search_box and len(clean_text) >= 2:
                    engine_name = domain.replace("www.", "").split(".")[0].capitalize() if domain else "Search"
                    sq_meta = json.dumps({
                        "query": clean_text,
                        "engine": engine_name,
                        "parent_event_id": last_id,
                        "typed_in_box": True
                    })
                    sq_title = f"{engine_name} Search: {clean_text}"
                    conn.execute(
                        """
                        INSERT INTO events (
                            event_type, source, timestamp, url, domain, title, app_name,
                            duration, text_content, selected_text, scroll_depth,
                            metadata_json, content_hash, referrer_url, from_event_id,
                            session_id, is_embedded, created_at
                        ) VALUES ('search_query', ?, ?, ?, ?, ?, ?, 0.0, ?, NULL, 0.0, ?, NULL, ?, ?, ?, 0, ?)
                        """,
                        (
                            item.source,
                            event_timestamp,
                            item.url,
                            domain,
                            sq_title,
                            item.app_name,
                            clean_text,
                            sq_meta,
                            item.referrer_url,
                            last_id,
                            item.session_id,
                            now
                        )
                    )

            # 3. YouTube video tracking & watch-time linking
            video_id = extract_youtube_video_id(item.url) if item.url else None
            if item.event_type == "youtube_video" or (domain and "youtube.com" in domain and video_id):
                if video_id:
                    meta = item.metadata or {}
                    yt_channel = meta.get("channel")
                    yt_desc = meta.get("description")
                    yt_dur = float(meta.get("duration") or item.duration or 0.0)
                    yt_play = float(meta.get("play_time") or 0.0)
                    yt_date = meta.get("upload_date")
                    yt_query = meta.get("search_query")

                    if not yt_query and from_event_id:
                        fe_cur = conn.execute("SELECT text_content, title, event_type FROM events WHERE id = ?", (from_event_id,))
                        fe_row = fe_cur.fetchone()
                        if fe_row and fe_row["event_type"] == "search_query":
                            yt_query = fe_row["text_content"] or fe_row["title"].replace("YouTube Search: ", "")

                    upsert_youtube_video(
                        video_id=video_id,
                        title=clean_title,
                        channel=yt_channel,
                        description=yt_desc,
                        duration=yt_dur,
                        play_time=yt_play,
                        upload_date=yt_date,
                        search_query=yt_query,
                        referrer_url=item.referrer_url,
                        event_id=last_id,
                        conn=conn
                    )

            try:
                from backend.apps_graph import invalidate_graph_cache
                invalidate_graph_cache()
            except Exception:
                pass

            return last_id
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


def save_session_record(session_data: Dict[str, Any], event_rows: List[Dict[str, Any]]) -> str:
    """Save or update a computed session, linking its events and updating projects table."""
    conn = get_db_connection()
    sid = session_data["id"]
    now = time.time()
    try:
        with conn:
            # 1. Insert or update session
            conn.execute("""
            INSERT OR REPLACE INTO sessions (
                id, title, summary, project_label, start_time, end_time,
                duration, event_count, primary_app, primary_domain, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sid,
                session_data["title"],
                session_data["summary"],
                session_data["project_label"],
                session_data["start_time"],
                session_data["end_time"],
                session_data["duration"],
                session_data["event_count"],
                session_data.get("primary_app", ""),
                session_data.get("primary_domain", ""),
                session_data.get("created_at", now),
                now
            ))

            # 2. Clear old session events links and re-link
            conn.execute("DELETE FROM session_events WHERE session_id = ?", (sid,))
            for seq, ev in enumerate(event_rows):
                conn.execute("""
                INSERT INTO session_events (
                    session_id, event_id, sequence_order, app_or_domain,
                    referrer_url, from_event_id, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    sid,
                    ev["id"],
                    seq,
                    ev.get("domain") or ev.get("app_name") or "desktop",
                    ev.get("referrer_url"),
                    ev.get("from_event_id"),
                    ev.get("timestamp", 0.0)
                ))
                # Update event's session_id in main events table
                conn.execute("UPDATE events SET session_id = ? WHERE id = ?", (sid, ev["id"]))

            # 3. Update projects table
            proj_name = session_data["project_label"]
            conn.execute("""
            INSERT INTO projects (name, description, first_seen, last_seen, total_duration, session_count)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(name) DO UPDATE SET
                last_seen = MAX(projects.last_seen, excluded.last_seen),
                total_duration = projects.total_duration + excluded.total_duration,
                session_count = projects.session_count + 1
            """, (
                proj_name,
                f"Project for {proj_name}",
                session_data["start_time"],
                session_data["end_time"],
                session_data["duration"]
            ))

        return sid
    finally:
        conn.close()


def get_sessions(
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    project: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Retrieve list of segmented sessions."""
    conn = get_db_connection()
    try:
        conditions = ["1=1"]
        params: List[Any] = []
        if start_time is not None:
            conditions.append("end_time >= ?")
            params.append(start_time)
        if end_time is not None:
            conditions.append("start_time <= ?")
            params.append(end_time)
        if project:
            conditions.append("project_label = ?")
            params.append(project)

        where_sql = " AND ".join(conditions)
        params.append(limit)

        cursor = conn.execute(f"""
        SELECT id, title, summary, project_label, start_time, end_time,
               duration, event_count, primary_app, primary_domain, created_at, updated_at
        FROM sessions
        WHERE {where_sql}
        ORDER BY start_time DESC
        LIMIT ?
        """, params)

        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_session_by_id(session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve complete session detail including ordered events and referrer links for 3D view."""
    conn = get_db_connection()
    try:
        cursor = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if not row:
            return None

        session_dict = dict(row)

        # Get linked events with details
        ev_cursor = conn.execute("""
        SELECT se.sequence_order, se.app_or_domain, se.referrer_url, se.from_event_id,
               e.id as event_id, e.event_type, e.source, e.timestamp, e.url, e.domain,
               e.title, e.app_name, e.duration, e.selected_text, e.scroll_depth
        FROM session_events se
        JOIN events e ON se.event_id = e.id
        WHERE se.session_id = ?
        ORDER BY se.sequence_order ASC
        """, (session_id,))

        events = [dict(r) for r in ev_cursor.fetchall()]
        session_dict["events"] = events

        # Build graph edges between events for the 3D journey view
        edges = []
        for ev in events:
            if ev.get("from_event_id"):
                edges.append({
                    "source": ev["from_event_id"],
                    "target": ev["event_id"],
                    "type": "referrer"
                })

        session_dict["edges"] = edges
        return session_dict
    finally:
        conn.close()


def get_projects() -> List[Dict[str, Any]]:
    """Retrieve all identified projects with aggregated stats."""
    conn = get_db_connection()
    try:
        cursor = conn.execute("""
        SELECT name, description, first_seen, last_seen, total_duration, session_count
        FROM projects
        ORDER BY last_seen DESC
        """)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_raw_events_for_period(start_time: Optional[float] = None, end_time: Optional[float] = None) -> List[Dict[str, Any]]:
    """Fetch raw events in chronological order for session segmentation."""
    conn = get_db_connection()
    try:
        conditions = ["1=1"]
        params: List[Any] = []
        if start_time is not None:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time is not None:
            conditions.append("timestamp <= ?")
            params.append(end_time)

        where_sql = " AND ".join(conditions)
        cursor = conn.execute(f"""
        SELECT id, event_type, source, timestamp, url, domain, title, app_name,
               duration, text_content, selected_text, scroll_depth, referrer_url,
               from_event_id, session_id
        FROM events
        WHERE {where_sql}
        ORDER BY timestamp ASC
        """, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def backfill_search_queries() -> int:
    """
    Backfill search_query events from all stored page URLs across the database.
    Idempotent: skips events that already have a corresponding search_query recorded.
    """
    conn = get_db_connection()
    backfilled_count = 0
    now = time.time()
    try:
        with conn:
            cursor = conn.execute("""
            SELECT id, source, timestamp, url, domain, title, app_name, referrer_url, from_event_id, session_id
            FROM events
            WHERE url IS NOT NULL AND url != '' AND event_type != 'search_query'
            ORDER BY timestamp ASC
            """)
            rows = cursor.fetchall()
            for r in rows:
                url = r["url"]
                if is_domain_blocked(url, DEFAULT_BLOCKED_DOMAINS):
                    continue

                extracted = extract_search_query(url)
                if not extracted:
                    continue

                query_text, engine_name = extracted
                # Check if search_query event already exists for this url and timestamp
                exist_cur = conn.execute(
                    "SELECT id FROM events WHERE event_type = 'search_query' AND url = ? AND timestamp = ?",
                    (url, r["timestamp"])
                )
                if exist_cur.fetchone():
                    continue

                sq_meta = json.dumps({
                    "query": query_text,
                    "engine": engine_name,
                    "parent_event_id": r["id"],
                    "extracted_from_url": True,
                    "backfilled": True
                })
                sq_title = f"{engine_name} Search: {query_text}"
                conn.execute(
                    """
                    INSERT INTO events (
                        event_type, source, timestamp, url, domain, title, app_name,
                        duration, text_content, selected_text, scroll_depth,
                        metadata_json, content_hash, referrer_url, from_event_id,
                        session_id, is_embedded, created_at
                    ) VALUES ('search_query', ?, ?, ?, ?, ?, ?, 0.0, ?, NULL, 0.0, ?, NULL, ?, ?, ?, 0, ?)
                    """,
                    (
                        r["source"],
                        r["timestamp"],
                        url,
                        r["domain"],
                        sq_title,
                        r["app_name"],
                        query_text,
                        sq_meta,
                        r["referrer_url"],
                        r["id"],
                        r["session_id"],
                        now
                    )
                )
                backfilled_count += 1
        return backfilled_count
    finally:
        conn.close()


def get_websites_summary(
    from_time: Optional[float] = None,
    to_time: Optional[float] = None,
    q: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Returns aggregated domain summary: domain, first_visit, last_visit,
    total_visits, total_active_time, search_count, typed_count, and visited pages.
    Excludes any blocked domains.
    """
    conn = get_db_connection()
    try:
        conditions = ["domain IS NOT NULL", "domain != ''"]
        params: List[Any] = []

        if from_time is not None:
            conditions.append("timestamp >= ?")
            params.append(from_time)
        if to_time is not None:
            conditions.append("timestamp <= ?")
            params.append(to_time)
        if q and q.strip():
            pattern = f"%{q.strip().lower()}%"
            conditions.append("(LOWER(domain) LIKE ? OR LOWER(title) LIKE ?)")
            params.extend([pattern, pattern])

        where_sql = " AND ".join(conditions)
        sql = f"""
        SELECT 
            domain,
            MIN(timestamp) as first_visit,
            MAX(timestamp) as last_visit,
            COUNT(CASE WHEN event_type IN ('page_visit', 'page_summary') THEN 1 END) as page_visits,
            COUNT(*) as total_events,
            SUM(COALESCE(duration, 0.0)) as total_active_time,
            COUNT(CASE WHEN event_type = 'search_query' THEN 1 END) as search_count,
            COUNT(CASE WHEN event_type = 'typed_input' THEN 1 END) as typed_count
        FROM events
        WHERE {where_sql}
        GROUP BY domain
        ORDER BY last_visit DESC;
        """
        cursor = conn.execute(sql, params)
        domain_rows = cursor.fetchall()

        results = []
        for row in domain_rows:
            domain = row["domain"]
            if is_domain_blocked(domain, DEFAULT_BLOCKED_DOMAINS):
                continue

            page_params: List[Any] = [domain]
            page_cond = ["domain = ?", "url IS NOT NULL", "url != ''"]
            if from_time is not None:
                page_cond.append("timestamp >= ?")
                page_params.append(from_time)
            if to_time is not None:
                page_cond.append("timestamp <= ?")
                page_params.append(to_time)

            page_where = " AND ".join(page_cond)
            page_cur = conn.execute(f"""
            SELECT id, title, url, timestamp, duration, scroll_depth
            FROM events
            WHERE {page_where} AND event_type IN ('page_visit', 'page_summary')
            ORDER BY timestamp DESC
            LIMIT 50
            """, page_params)

            pages = [dict(p) for p in page_cur.fetchall()]

            total_visits = row["page_visits"] if row["page_visits"] > 0 else row["total_events"]
            results.append({
                "domain": domain,
                "first_visit": row["first_visit"],
                "last_visit": row["last_visit"],
                "total_visits": total_visits,
                "total_active_time": round(float(row["total_active_time"] or 0.0), 1),
                "search_count": row["search_count"],
                "typed_count": row["typed_count"],
                "pages": pages
            })

        return results
    finally:
        conn.close()


def get_website_detail(domain: str) -> Optional[Dict[str, Any]]:
    """
    Returns complete chronological activity for a specific website domain:
    pages_visited, search_queries, typed_text, highlights, and referrer navigation links.
    """
    clean_domain = domain.strip().lower()
    if is_domain_blocked(clean_domain, DEFAULT_BLOCKED_DOMAINS):
        return None

    domain_variants = [clean_domain]
    if clean_domain.startswith("www."):
        domain_variants.append(clean_domain[4:])
    else:
        domain_variants.append(f"www.{clean_domain}")

    conn = get_db_connection()
    try:
        placeholders = ",".join("?" * len(domain_variants))

        cur = conn.execute(
            f"SELECT MIN(timestamp) as first_visit, MAX(timestamp) as last_visit, SUM(COALESCE(duration, 0.0)) as total_active_time, COUNT(*) as total_events FROM events WHERE domain IN ({placeholders})",
            domain_variants
        )
        stats = cur.fetchone()
        if not stats or stats["total_events"] == 0:
            return None

        # 1. Pages visited in time order
        pages_cur = conn.execute(
            f"""
            SELECT id, title, url, timestamp, duration, scroll_depth, referrer_url, from_event_id
            FROM events
            WHERE domain IN ({placeholders}) AND event_type IN ('page_visit', 'page_summary')
            ORDER BY timestamp ASC
            """,
            domain_variants
        )
        pages_visited = [dict(r) for r in pages_cur.fetchall()]

        # 2. Search queries on this domain
        sq_cur = conn.execute(
            f"""
            SELECT id, text_content as query, metadata_json, timestamp, url
            FROM events
            WHERE domain IN ({placeholders}) AND event_type = 'search_query'
            ORDER BY timestamp ASC
            """,
            domain_variants
        )
        search_queries = []
        for r in sq_cur.fetchall():
            item = dict(r)
            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except Exception:
                    pass
            item["engine"] = meta.get("engine", "Search")
            search_queries.append(item)

        # 3. Typed text snippets (scrubbed)
        typed_cur = conn.execute(
            f"""
            SELECT id, text_content as text, metadata_json, timestamp, url
            FROM events
            WHERE domain IN ({placeholders}) AND event_type = 'typed_input'
            ORDER BY timestamp ASC
            """,
            domain_variants
        )
        typed_text = [dict(r) for r in typed_cur.fetchall()]

        # 4. Text highlights / selections
        hl_cur = conn.execute(
            f"""
            SELECT id, selected_text as text, timestamp, url
            FROM events
            WHERE domain IN ({placeholders}) AND event_type = 'text_select'
            ORDER BY timestamp ASC
            """,
            domain_variants
        )
        highlights = [dict(r) for r in hl_cur.fetchall()]

        # 5. Referrer / navigation links (came from and went to next)
        navigation_links = []

        ref_cur = conn.execute(
            f"""
            SELECT id, referrer_url, url, timestamp
            FROM events
            WHERE domain IN ({placeholders}) AND referrer_url IS NOT NULL AND referrer_url != ''
            ORDER BY timestamp ASC
            """,
            domain_variants
        )
        for r in ref_cur.fetchall():
            raw_ref = extract_domain(r["referrer_url"])
            ref_domain = raw_ref.replace("www.", "") if raw_ref else ""
            if ref_domain and ref_domain not in [d.replace("www.", "") for d in domain_variants] and not is_domain_blocked(ref_domain, DEFAULT_BLOCKED_DOMAINS):
                navigation_links.append({
                    "type": "came_from",
                    "from_domain": ref_domain,
                    "to_domain": clean_domain.replace("www.", ""),
                    "referrer_url": r["referrer_url"],
                    "target_url": r["url"],
                    "timestamp": r["timestamp"]
                })

        next_cur = conn.execute(
            f"""
            SELECT id, domain, url, referrer_url, timestamp
            FROM events
            WHERE domain NOT IN ({placeholders}) AND referrer_url IS NOT NULL AND referrer_url != ''
            ORDER BY timestamp ASC
            """,
            domain_variants
        )
        for r in next_cur.fetchall():
            raw_ref = extract_domain(r["referrer_url"])
            ref_dom = raw_ref.replace("www.", "") if raw_ref else ""
            clean_target = (r["domain"] or "").replace("www.", "")
            if ref_dom in [d.replace("www.", "") for d in domain_variants] and not is_domain_blocked(clean_target, DEFAULT_BLOCKED_DOMAINS):
                navigation_links.append({
                    "type": "went_to",
                    "from_domain": clean_domain.replace("www.", ""),
                    "to_domain": clean_target,
                    "referrer_url": r["referrer_url"],
                    "target_url": r["url"],
                    "timestamp": r["timestamp"]
                })

        navigation_links.sort(key=lambda x: x["timestamp"])

        return {
            "domain": clean_domain,
            "first_visit": stats["first_visit"],
            "last_visit": stats["last_visit"],
            "total_visits": len(pages_visited) if pages_visited else stats["total_events"],
            "total_active_time": round(float(stats["total_active_time"] or 0.0), 1),
            "pages_visited": pages_visited,
            "search_queries": search_queries,
            "typed_text": typed_text,
            "highlights": highlights,
            "navigation_links": navigation_links
        }
    finally:
        conn.close()


def delete_website_history(domain: str) -> int:
    """
    Deletes all activity events for a specific domain from SQLite and FTS5.
    Returns the count of deleted events.
    """
    clean_domain = domain.strip().lower()
    domain_variants = [clean_domain]
    if clean_domain.startswith("www."):
        domain_variants.append(clean_domain[4:])
    else:
        domain_variants.append(f"www.{clean_domain}")

    conn = get_db_connection()
    try:
        with conn:
            placeholders = ",".join("?" * len(domain_variants))
            cur = conn.execute(
                f"SELECT id FROM events WHERE domain IN ({placeholders})",
                domain_variants
            )
            event_ids = [r["id"] for r in cur.fetchall()]
            if not event_ids:
                return 0

            id_placeholders = ",".join("?" * len(event_ids))
            conn.execute(
                f"DELETE FROM session_events WHERE event_id IN ({id_placeholders})",
                event_ids
            )
            conn.execute(
                f"DELETE FROM events WHERE id IN ({id_placeholders})",
                event_ids
            )
            return len(event_ids)
    finally:
        conn.close()


def get_all_searches(
    domain: Optional[str] = None,
    q: Optional[str] = None,
    from_time: Optional[float] = None,
    to_time: Optional[float] = None,
    limit: int = 500
) -> List[Dict[str, Any]]:
    """
    Retrieve all search queries across every site in chronological order.
    Optionally filters by domain, query text, or time bounds.
    """
    conn = get_db_connection()
    try:
        conditions = ["event_type = 'search_query'"]
        params: List[Any] = []

        if domain and domain.strip():
            clean_dom = domain.strip().lower()
            conditions.append("(LOWER(domain) = ? OR LOWER(domain) = ?)")
            params.extend([clean_dom, f"www.{clean_dom}"])

        if q and q.strip():
            conditions.append("LOWER(text_content) LIKE ?")
            params.append(f"%{q.strip().lower()}%")

        if from_time is not None:
            conditions.append("timestamp >= ?")
            params.append(from_time)

        if to_time is not None:
            conditions.append("timestamp <= ?")
            params.append(to_time)

        where_sql = " AND ".join(conditions)
        params.append(limit)

        sql = f"""
        SELECT id, text_content as query, domain, url, title, timestamp, metadata_json, from_event_id
        FROM events
        WHERE {where_sql}
        ORDER BY timestamp DESC
        LIMIT ?;
        """
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()

        results = []
        for r in rows:
            if is_domain_blocked(r["domain"] or "", DEFAULT_BLOCKED_DOMAINS):
                continue

            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except Exception:
                    pass

            result_page = None
            parent_id = r["from_event_id"] or meta.get("parent_event_id")
            if parent_id:
                p_cur = conn.execute(
                    "SELECT title, url FROM events WHERE id = ? AND event_type IN ('page_visit', 'page_summary')",
                    (parent_id,)
                )
                p_row = p_cur.fetchone()
                if p_row:
                    result_page = {"title": p_row["title"], "url": p_row["url"]}

            results.append({
                "id": r["id"],
                "query": r["query"],
                "engine": meta.get("engine", "Search"),
                "domain": r["domain"],
                "url": r["url"],
                "title": r["title"],
                "timestamp": r["timestamp"],
                "result_page": result_page
            })

        return results
    finally:
        conn.close()


def get_data_summary() -> Dict[str, Any]:
    """Retrieve event counts by source, first and last timestamp, and number of sites/apps/files."""
    conn = get_db_connection()
    try:
        cur = conn.execute("""
        SELECT 
            COUNT(*) as total_events,
            MIN(timestamp) as first_timestamp,
            MAX(timestamp) as last_timestamp,
            COUNT(DISTINCT domain) as total_domains,
            COUNT(DISTINCT app_name) as total_apps
        FROM events;
        """)
        row = cur.fetchone()
        total_events = row["total_events"] if row else 0
        first_ts = row["first_timestamp"] if row and row["first_timestamp"] else None
        last_ts = row["last_timestamp"] if row and row["last_timestamp"] else None

        date_span_days = 0
        if first_ts and last_ts:
            date_span_days = max(1, math.ceil((last_ts - first_ts) / 86400.0))

        # Counts by source
        src_cur = conn.execute("SELECT source, COUNT(*) as cnt FROM events GROUP BY source;")
        sources = {r["source"]: r["cnt"] for r in src_cur.fetchall()}

        # Counts for standard sources (ensuring zeros present)
        for s in ["extension_live", "edge_history", "desktop_agent", "vscode", "chatbot"]:
            if s not in sources:
                sources[s] = 0

        # Total files touched count
        file_cur = conn.execute("SELECT COUNT(*) FROM events WHERE event_type LIKE 'file_%';")
        total_files = file_cur.fetchone()[0]

        # Total graph nodes and edges
        node_cur = conn.execute("SELECT COUNT(*) FROM graph_nodes;")
        total_graph_nodes = node_cur.fetchone()[0]
        edge_cur = conn.execute("SELECT COUNT(*) FROM graph_edges;")
        total_graph_edges = edge_cur.fetchone()[0]

        return {
            "total_events": total_events,
            "first_timestamp": first_ts,
            "last_timestamp": last_ts,
            "date_span_days": date_span_days,
            "total_domains": row["total_domains"] if row else 0,
            "total_apps": row["total_apps"] if row else 0,
            "total_files": total_files,
            "total_graph_nodes": total_graph_nodes,
            "total_graph_edges": total_graph_edges,
            "sources": sources
        }
    finally:
        conn.close()


def delete_events_by_source(source: str) -> int:
    """Bulk delete all events associated with a specific source (e.g. edge_history)."""
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.execute("SELECT id FROM events WHERE source = ?", (source,))
            event_ids = [r["id"] for r in cur.fetchall()]
            if not event_ids:
                return 0

            id_placeholders = ",".join("?" * len(event_ids))
            conn.execute(f"DELETE FROM session_events WHERE event_id IN ({id_placeholders})", event_ids)
            conn.execute(f"DELETE FROM events WHERE id IN ({id_placeholders})", event_ids)
            return len(event_ids)
    finally:
        conn.close()

