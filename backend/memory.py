"""
MemoryOS Conversation Memory & Forget Module.
Tracks user-stated facts and preferences, and handles 'forget this' privacy actions.
"""

import re
import time
from typing import Any, Dict, Optional, Tuple

from backend.database import get_db_connection
from backend.temporal import parse_temporal_query
from backend.vector_store import get_vector_store


def init_memory_tables():
    """Ensure user preferences and conversation facts table exists."""
    conn = get_db_connection()
    try:
        with conn:
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


def store_preference(key: str, value: str):
    """Store or update user preference or fact."""
    conn = get_db_connection()
    now = time.time()
    try:
        with conn:
            conn.execute("""
            INSERT INTO user_preferences (key, value, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """, (key.strip().lower(), value.strip(), now, now))
    finally:
        conn.close()


def get_all_preferences() -> Dict[str, str]:
    """Retrieve all user preferences and facts."""
    conn = get_db_connection()
    try:
        cursor = conn.execute("SELECT key, value FROM user_preferences;")
        return {row["key"]: row["value"] for row in cursor.fetchall()}
    finally:
        conn.close()


def handle_special_memory_commands(query: str) -> Optional[str]:
    """
    Check if query is a 'remember that ...' or 'forget this ...' instruction.
    Returns response message if handled, or None if it's a standard question.
    """
    lower = query.strip().lower()

    # 1. "Remember that ..."
    remember_match = re.match(r"^remember\s+that\s+(.*)$", lower)
    if remember_match:
        fact = remember_match.group(1).strip()
        store_preference(f"fact_{int(time.time())}", fact)
        return f"Got it! I will remember that: \"{fact}\""

    # 2. "Forget this" / "Forget what I read on [domain]" / "Forget yesterday"
    if lower.startswith("forget"):
        vector_store = get_vector_store()
        conn = get_db_connection()

        # A. Forget by domain: "forget what I read on reddit.com" or "forget domain.com"
        domain_match = re.search(r"([a-z0-9\-]+\.[a-z]{2,})", lower)
        if domain_match:
            target_domain = domain_match.group(1).lower()
            try:
                with conn:
                    # Find event IDs to delete
                    cur = conn.execute("SELECT id FROM events WHERE domain LIKE ?", (f"%{target_domain}%",))
                    ids = [r["id"] for r in cur.fetchall()]
                    if ids:
                        placeholders = ",".join("?" for _ in ids)
                        conn.execute(f"DELETE FROM events WHERE id IN ({placeholders})", ids)
                        vector_store.delete_by_event_ids(ids)
                return f"I have forgotten and deleted all records and vector embeddings from domain: {target_domain}."
            finally:
                conn.close()

        # B. Forget by time: "forget yesterday", "forget last week"
        clean_q, start_ts, end_ts = parse_temporal_query(lower)
        if start_ts is not None and end_ts is not None:
            try:
                with conn:
                    cur = conn.execute("SELECT id FROM events WHERE timestamp >= ? AND timestamp <= ?", (start_ts, end_ts))
                    ids = [r["id"] for r in cur.fetchall()]
                    if ids:
                        placeholders = ",".join("?" for _ in ids)
                        conn.execute(f"DELETE FROM events WHERE id IN ({placeholders})", ids)
                        vector_store.delete_by_time_range(start_ts, end_ts)
                return f"I have deleted all recorded memories between {time.strftime('%x %X', time.localtime(start_ts))} and {time.strftime('%x %X', time.localtime(end_ts))}."
            finally:
                conn.close()

        # C. Generic "forget this" (deletes the most recent event)
        try:
            with conn:
                cur = conn.execute("SELECT id, title, url FROM events ORDER BY timestamp DESC LIMIT 1;")
                row = cur.fetchone()
                if row:
                    last_id = row["id"]
                    title = row["title"]
                    conn.execute("DELETE FROM events WHERE id = ?", (last_id,))
                    vector_store.delete_by_event_ids([last_id])
                    return f"I have deleted your most recent memory: \"{title}\"."
                return "No recorded memories to delete."
        finally:
            conn.close()

    return None
