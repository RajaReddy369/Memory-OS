"""
MemoryOS Vector Database Module.
Provides dense vector storage and cosine similarity search with LanceDB and an
in-process SQLite+NumPy vector store fallback for isolated execution environments.
"""

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np

from backend.config import DATA_DIR

logger = logging.getLogger("memoryos.vector_store")

LANCE_DIR = DATA_DIR / "lancedb"


class SQLiteDenseVectorStore:
    """
    High-performance in-process vector store using SQLite for metadata and NumPy for vectorized cosine search.
    Stores raw float32 vector buffers directly in an embedded database.
    Guaranteed zero external service dependencies.
    """
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (DATA_DIR / "vectors.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            with conn:
                conn.execute("""
                CREATE TABLE IF NOT EXISTS chunk_vectors (
                    id TEXT PRIMARY KEY,
                    event_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    vector_blob BLOB NOT NULL,
                    timestamp REAL NOT NULL,
                    url TEXT,
                    domain TEXT,
                    title TEXT,
                    source TEXT,
                    session_id TEXT,
                    created_at REAL NOT NULL
                );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_vec_timestamp ON chunk_vectors(timestamp);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_vec_domain ON chunk_vectors(domain);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_vec_event ON chunk_vectors(event_id);")
        finally:
            conn.close()

    def add_chunks(self, records: List[Dict[str, Any]]) -> int:
        """Add list of chunk records with float vector arrays."""
        if not records:
            return 0
        conn = self._get_conn()
        try:
            with conn:
                for r in records:
                    vec = np.array(r["vector"], dtype=np.float32)
                    # Normalize vector
                    norm = np.linalg.norm(vec)
                    if norm > 1e-9:
                        vec = vec / norm
                    conn.execute("""
                    INSERT OR REPLACE INTO chunk_vectors (
                        id, event_id, chunk_index, text, vector_blob, timestamp,
                        url, domain, title, source, session_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        r["id"],
                        r["event_id"],
                        r["chunk_index"],
                        r["text"],
                        vec.tobytes(),
                        r.get("timestamp", 0.0),
                        r.get("url", ""),
                        r.get("domain", ""),
                        r.get("title", ""),
                        r.get("source", "browser"),
                        r.get("session_id", ""),
                        r.get("timestamp", 0.0)
                    ))
            return len(records)
        finally:
            conn.close()

    def search(
        self,
        query_vector: List[float],
        limit: int = 20,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        domain: Optional[str] = None,
        source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Vectorized cosine similarity search with SQL metadata pre-filtering."""
        q_vec = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm > 1e-9:
            q_vec = q_vec / q_norm

        conn = self._get_conn()
        try:
            conditions = ["1=1"]
            params: List[Any] = []
            if start_time is not None:
                conditions.append("timestamp >= ?")
                params.append(start_time)
            if end_time is not None:
                conditions.append("timestamp <= ?")
                params.append(end_time)
            if domain:
                conditions.append("domain = ?")
                params.append(domain)
            if source:
                conditions.append("source = ?")
                params.append(source)

            where_sql = " AND ".join(conditions)
            cursor = conn.execute(f"""
            SELECT id, event_id, chunk_index, text, vector_blob, timestamp, url, domain, title, source, session_id
            FROM chunk_vectors
            WHERE {where_sql}
            """, params)

            rows = cursor.fetchall()
            if not rows:
                return []

            results: List[Dict[str, Any]] = []
            for row in rows:
                doc_vec = np.frombuffer(row["vector_blob"], dtype=np.float32)
                # Cosine similarity
                sim = float(np.dot(q_vec, doc_vec))
                results.append({
                    "id": row["id"],
                    "event_id": row["event_id"],
                    "chunk_index": row["chunk_index"],
                    "text": row["text"],
                    "timestamp": row["timestamp"],
                    "url": row["url"],
                    "domain": row["domain"],
                    "title": row["title"],
                    "source": row["source"],
                    "session_id": row["session_id"],
                    "score": round(sim, 4),
                    "distance": round(1.0 - sim, 4)
                })

            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]
        finally:
            conn.close()

    def delete_by_event_ids(self, event_ids: List[int]) -> int:
        if not event_ids:
            return 0
        conn = self._get_conn()
        try:
            with conn:
                placeholders = ",".join("?" for _ in event_ids)
                cursor = conn.execute(f"DELETE FROM chunk_vectors WHERE event_id IN ({placeholders})", event_ids)
                return cursor.rowcount
        finally:
            conn.close()

    def delete_by_domain(self, domain: str) -> int:
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute("DELETE FROM chunk_vectors WHERE domain = ?", (domain,))
                return cursor.rowcount
        finally:
            conn.close()

    def delete_by_time_range(self, start_time: float, end_time: float) -> int:
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute("DELETE FROM chunk_vectors WHERE timestamp >= ? AND timestamp <= ?", (start_time, end_time))
                return cursor.rowcount
        finally:
            conn.close()

    def count(self) -> int:
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM chunk_vectors;")
            return cursor.fetchone()[0]
        finally:
            conn.close()


class LanceDBStore:
    """LanceDB embedded vector database store."""
    def __init__(self, db_dir: Optional[Path] = None):
        import lancedb
        import pyarrow as pa
        self.db_dir = db_dir or LANCE_DIR
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.db_dir))
        self.schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("event_id", pa.int64()),
            pa.field("chunk_index", pa.int64()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 768)),
            pa.field("timestamp", pa.float64()),
            pa.field("url", pa.string()),
            pa.field("domain", pa.string()),
            pa.field("title", pa.string()),
            pa.field("source", pa.string()),
            pa.field("session_id", pa.string()),
        ])
        if "chunks" not in self.db.table_names():
            self.tbl = self.db.create_table("chunks", schema=self.schema)
        else:
            self.tbl = self.db.open_table("chunks")

    def add_chunks(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        self.tbl.add(records)
        return len(records)

    def search(
        self,
        query_vector: List[float],
        limit: int = 20,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        domain: Optional[str] = None,
        source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = self.tbl.search(query_vector).limit(limit)
        filters = []
        if start_time is not None:
            filters.append(f"timestamp >= {start_time}")
        if end_time is not None:
            filters.append(f"timestamp <= {end_time}")
        if domain:
            safe_domain = domain.replace("'", "")
            filters.append(f"domain = '{safe_domain}'")
        if source:
            safe_source = source.replace("'", "")
            filters.append(f"source = '{safe_source}'")

        if filters:
            query = query.where(" AND ".join(filters))

        raw_results = query.to_list()
        results: List[Dict[str, Any]] = []
        for r in raw_results:
            dist = float(r.get("_distance", 0.0))
            # Convert L2 distance or cosine distance to [0, 1] similarity score
            score = round(max(0.0, 1.0 - (dist / 2.0)), 4)
            results.append({
                "id": r["id"],
                "event_id": r["event_id"],
                "chunk_index": r["chunk_index"],
                "text": r["text"],
                "timestamp": r["timestamp"],
                "url": r["url"],
                "domain": r["domain"],
                "title": r["title"],
                "source": r["source"],
                "session_id": r["session_id"],
                "score": score,
                "distance": dist
            })
        return results

    def delete_by_event_ids(self, event_ids: List[int]) -> int:
        if not event_ids:
            return 0
        ids_str = ",".join(str(i) for i in event_ids)
        self.tbl.delete(f"event_id IN ({ids_str})")
        return len(event_ids)

    def delete_by_domain(self, domain: str) -> int:
        safe_domain = domain.replace("'", "")
        self.tbl.delete(f"domain = '{safe_domain}'")
        return 1

    def delete_by_time_range(self, start_time: float, end_time: float) -> int:
        self.tbl.delete(f"timestamp >= {start_time} AND timestamp <= {end_time}")
        return 1

    def count(self) -> int:
        return self.tbl.count_rows()


_vector_store_instance = None


def get_vector_store():
    """Retrieve vector store instance (prefers LanceDB when running outside sandbox, fallback to SQLiteDenseVectorStore)."""
    global _vector_store_instance
    if _vector_store_instance is None:
        use_sqlite = os.environ.get("MEMORYOS_USE_SQLITE_VECTORS", "0") == "1"
        if not use_sqlite:
            try:
                # Attempt to initialize LanceDB
                _vector_store_instance = LanceDBStore()
                logger.info("LanceDB vector store initialized.")
            except Exception as e:
                logger.debug(f"LanceDB init skipped or failed ({e}); using SQLite dense vector store.")
                _vector_store_instance = SQLiteDenseVectorStore()
        else:
            _vector_store_instance = SQLiteDenseVectorStore()
    return _vector_store_instance

