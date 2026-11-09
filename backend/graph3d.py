"""
MemoryOS 3D Graph Service.
Extracts real database events, sessions, and domain nodes for the 3D World Map.
Caches stable 3D layout coordinates in SQLite so the world map never reshuffles.
Caps nodes around 2,000 for high-performance rendering.
"""

import hashlib
import json
import logging
import math
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.config import DB_PATH, DEFAULT_BLOCKED_DOMAINS
from backend.database import get_db_connection
from backend.scrubber import extract_domain, is_domain_blocked

logger = logging.getLogger("memoryos.graph3d")


def init_graph3d_db():
    """Ensure layout cache table exists in database."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_layout_cache (
                node_id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                x REAL NOT NULL,
                y REAL NOT NULL,
                z REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_layout_type ON graph_layout_cache(node_type);")
    finally:
        conn.close()


def compute_deterministic_position(seed_str: str, radius_min: float = 12.0, radius_max: float = 85.0) -> Tuple[float, float, float]:
    """Compute deterministic, stable 3D coordinates on terrain from string hash."""
    h = hashlib.sha256(seed_str.encode("utf-8")).hexdigest()
    val_angle = int(h[:8], 16) / 0xffffffff
    val_rad = int(h[8:16], 16) / 0xffffffff
    val_y = int(h[16:24], 16) / 0xffffffff

    angle = val_angle * 2.0 * math.pi
    radius = radius_min + (val_rad * (radius_max - radius_min))
    x = math.cos(angle) * radius
    z = math.sin(angle) * radius
    y = (val_y * 1.5)  # slight terrain elevation variation
    return round(x, 2), round(y, 2), round(z, 2)


def get_or_create_layout_position(node_id: str, node_type: str, seed: Optional[str] = None) -> Tuple[float, float, float]:
    """Retrieve cached position or compute and cache a stable position."""
    conn = get_db_connection()
    try:
        cur = conn.execute("SELECT x, y, z FROM graph_layout_cache WHERE node_id = ?", (node_id,))
        row = cur.fetchone()
        if row:
            return float(row["x"]), float(row["y"]), float(row["z"])

        # Determine spatial ring by node type
        if node_type == "region":
            rad_min, rad_max = 50.0, 90.0
        elif node_type == "city":
            rad_min, rad_max = 18.0, 65.0
        else:
            rad_min, rad_max = 6.0, 30.0

        x, y, z = compute_deterministic_position(seed or node_id, rad_min, rad_max)
        now = time.time()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO graph_layout_cache (node_id, node_type, x, y, z, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (node_id, node_type, x, y, z, now)
            )
        return x, y, z
    finally:
        conn.close()


def get_real_graph3d_data(
    from_time: Optional[float] = None,
    to_time: Optional[float] = None,
    level: str = "session",
    source: Optional[str] = None,
    max_nodes: int = 2000
) -> Dict[str, Any]:
    """
    Build real 3D World graph from SQLite database rows.
    Returns: { nodes, edges, meta }
    """
    init_graph3d_db()
    conn = get_db_connection()
    try:
        conditions = ["1=1"]
        params: List[Any] = []

        if from_time is not None:
            conditions.append("e.timestamp >= ?")
            params.append(from_time)
        if to_time is not None:
            conditions.append("e.timestamp <= ?")
            params.append(to_time)
        if source and source != "all":
            conditions.append("e.source = ?")
            params.append(source)

        where_clause = " AND ".join(conditions)

        # 1. Fetch metadata summary
        count_cur = conn.execute(f"""
        SELECT 
            COUNT(*) as total_events,
            MIN(timestamp) as min_ts,
            MAX(timestamp) as max_ts,
            COUNT(DISTINCT domain) as total_domains
        FROM events e
        WHERE {where_clause}
        """, params)
        summary = count_cur.fetchone()
        total_events = summary["total_events"] if summary else 0

        if total_events == 0:
            return {
                "nodes": [],
                "edges": [],
                "meta": {
                    "total_nodes": 0,
                    "total_edges": 0,
                    "total_events": 0,
                    "date_span_days": 0,
                    "total_domains": 0,
                    "data_source": "Live database (empty)"
                }
            }

        min_ts = summary["min_ts"] or 0
        max_ts = summary["max_ts"] or 0
        date_span_days = max(1, math.ceil((max_ts - min_ts) / 86400.0))

        # 2. Extract distinct real domains and apps as "Cities"
        city_cur = conn.execute(f"""
        SELECT 
            COALESCE(e.domain, e.app_name, 'General') as city_name,
            e.source,
            COUNT(*) as event_count,
            SUM(COALESCE(e.duration, 0.0)) as total_duration,
            MIN(e.timestamp) as first_visit,
            MAX(e.timestamp) as last_visit
        FROM events e
        WHERE {where_clause} AND (e.domain IS NOT NULL OR e.app_name IS NOT NULL)
        GROUP BY city_name
        ORDER BY event_count DESC
        LIMIT 100
        """, params)

        cities = city_cur.fetchall()
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        city_positions: Dict[str, Tuple[float, float, float]] = {}

        # Top 5 most-used entities become landmarks
        top_cities = [c["city_name"] for c in cities[:5]]

        for c in cities:
            cname = c["city_name"]
            if is_domain_blocked(cname, DEFAULT_BLOCKED_DOMAINS):
                continue

            node_id = f"city_{cname}"
            pos = get_or_create_layout_position(node_id, "city", seed=cname)
            city_positions[cname] = pos

            is_landmark = cname in top_cities
            landmark_type = None
            if is_landmark:
                idx = top_cities.index(cname)
                landmark_types = ["monument_tower", "lighthouse", "citadel", "obelisk", "cathedral"]
                landmark_type = landmark_types[idx % len(landmark_types)]

            nodes.append({
                "id": node_id,
                "name": cname,
                "type": "city",
                "category": "domain" if "." in cname else "app",
                "source": c["source"],
                "event_count": c["event_count"],
                "total_duration": round(float(c["total_duration"] or 0.0), 1),
                "first_visit": c["first_visit"],
                "last_visit": c["last_visit"],
                "position": [pos[0], pos[1], pos[2]],
                "is_landmark": is_landmark,
                "landmark_type": landmark_type,
                "provenance": c["source"]
            })

        # 3. Extract individual real pages, documents, or search queries as "Buildings"
        building_limit = max(50, max_nodes - len(nodes))
        bld_cur = conn.execute(f"""
        SELECT 
            e.id,
            e.event_type,
            e.source,
            e.timestamp,
            e.url,
            COALESCE(e.domain, e.app_name, 'General') as city_name,
            e.title,
            e.duration,
            e.scroll_depth,
            e.referrer_url,
            e.from_event_id,
            e.metadata_json
        FROM events e
        WHERE {where_clause}
        ORDER BY e.timestamp DESC
        LIMIT ?
        """, params + [building_limit])

        buildings = bld_cur.fetchall()
        for b in buildings:
            cname = b["city_name"]
            if is_domain_blocked(cname, DEFAULT_BLOCKED_DOMAINS):
                continue

            bid = f"event_{b['id']}"
            parent_city_pos = city_positions.get(cname, (0.0, 0.0, 0.0))

            # Compute local offset around parent city
            h_offset = int(hashlib.md5(bid.encode()).hexdigest()[:6], 16)
            angle = (h_offset % 360) * (math.pi / 180.0)
            dist = 2.0 + ((h_offset % 100) / 100.0) * 6.5
            bx = parent_city_pos[0] + math.cos(angle) * dist
            bz = parent_city_pos[2] + math.sin(angle) * dist
            by = parent_city_pos[1]

            dur = float(b["duration"] or 0.0)
            # Building height proportional to time spent, minimum height for clicks
            height = max(1.2, min(24.0, dur * 0.12 if dur > 0 else 1.5))

            nodes.append({
                "id": bid,
                "eventId": b["id"],
                "name": b["title"] or b["url"] or f"Event {b['id']}",
                "type": "building",
                "subType": b["event_type"],
                "city": cname,
                "url": b["url"],
                "source": b["source"],
                "timestamp": b["timestamp"],
                "duration": dur,
                "height": round(height, 2),
                "scroll_depth": b["scroll_depth"],
                "position": [round(bx, 2), round(by, 2), round(bz, 2)],
                "provenance": b["source"]
            })

            # Road connection from parent city to building
            edges.append({
                "id": f"edge_city_{bid}",
                "source": f"city_{cname}",
                "target": bid,
                "type": "branch",
                "weight": 1.0
            })

            # 4. Referrer links (navigation roads between sites)
            if b["referrer_url"]:
                ref_dom = extract_domain(b["referrer_url"])
                if ref_dom and ref_dom != cname and ref_dom in city_positions:
                    edges.append({
                        "id": f"road_{ref_dom}_{cname}_{b['id']}",
                        "source": f"city_{ref_dom}",
                        "target": f"city_{cname}",
                        "type": "referrer",
                        "weight": 2.0
                    })

        return {
            "nodes": nodes,
            "edges": edges,
            "meta": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "total_events": total_events,
                "date_span_days": date_span_days,
                "total_domains": len(cities),
                "data_source": "Live database"
            }
        }
    finally:
        conn.close()


def get_real_graph3d_node_detail(node_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve full detail for a specific 3D node."""
    conn = get_db_connection()
    try:
        if node_id.startswith("event_"):
            ev_id = int(node_id.replace("event_", ""))
            cur = conn.execute("SELECT * FROM events WHERE id = ?", (ev_id,))
            row = cur.fetchone()
            if not row:
                return None
            res = dict(row)
            res["type"] = "event"
            res["provenance"] = row["source"]
            return res

        elif node_id.startswith("city_"):
            cname = node_id.replace("city_", "")
            cur = conn.execute("""
            SELECT 
                COUNT(*) as total_events,
                MIN(timestamp) as first_visit,
                MAX(timestamp) as last_visit,
                SUM(COALESCE(duration, 0.0)) as total_duration
            FROM events
            WHERE domain = ? OR app_name = ?
            """, (cname, cname))
            row = cur.fetchone()
            if not row or row["total_events"] == 0:
                return None

            # Get recent 20 pages
            p_cur = conn.execute("""
            SELECT id, title, url, timestamp, duration, event_type, scroll_depth
            FROM events
            WHERE domain = ? OR app_name = ?
            ORDER BY timestamp DESC
            LIMIT 20
            """, (cname, cname))

            return {
                "type": "city",
                "name": cname,
                "total_events": row["total_events"],
                "first_visit": row["first_visit"],
                "last_visit": row["last_visit"],
                "total_duration": row["total_duration"],
                "recent_pages": [dict(p) for p in p_cur.fetchall()]
            }
        return None
    finally:
        conn.close()

