"""
MemoryOS Branch Tree & YouTube Activity Service.
Constructs nested hierarchical branch trees (Website -> Search Query -> Visited Pages/Videos -> Referrer Navigation)
and provides structured YouTube video and search analytics.
"""

from typing import Any, Dict, List, Optional
import sqlite3
import time

from backend.config import DB_PATH, DEFAULT_BLOCKED_DOMAINS
from backend.database import get_db_connection
from backend.scrubber import extract_domain, is_domain_blocked


def get_tree_roots(
    from_time: Optional[float] = None,
    to_time: Optional[float] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve root domains that initiated browsing branches or search queries.
    """
    conn = get_db_connection()
    try:
        conditions = ["domain IS NOT NULL", "domain != ''"]
        params: List[Any] = []
        if from_time is not None and isinstance(from_time, (int, float)):
            conditions.append("timestamp >= ?")
            params.append(float(from_time))
        if to_time is not None and isinstance(to_time, (int, float)):
            conditions.append("timestamp <= ?")
            params.append(float(to_time))

        where_sql = " AND ".join(conditions)
        sql = f"""
        SELECT 
            domain,
            COUNT(*) as total_events,
            SUM(CASE WHEN event_type = 'search_query' THEN 1 ELSE 0 END) as search_count,
            SUM(CASE WHEN event_type = 'youtube_video' OR (domain = 'youtube.com' AND url LIKE '%watch%') THEN 1 ELSE 0 END) as video_count,
            MIN(timestamp) as first_seen,
            MAX(timestamp) as last_seen,
            SUM(COALESCE(duration, 0.0)) as total_active_time
        FROM events
        WHERE {where_sql}
        GROUP BY domain
        ORDER BY total_events DESC;
        """
        rows = conn.execute(sql, params).fetchall()

        results = []
        for r in rows:
            dom = r["domain"]
            if is_domain_blocked(dom, DEFAULT_BLOCKED_DOMAINS):
                continue
            results.append({
                "domain": dom,
                "total_events": r["total_events"],
                "search_count": r["search_count"],
                "video_count": r["video_count"],
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
                "total_active_time": round(float(r["total_active_time"] or 0.0), 1)
            })
        return results
    finally:
        conn.close()


def get_nested_branch_tree(
    domain: Optional[str] = None,
    from_time: Optional[float] = None,
    to_time: Optional[float] = None
) -> List[Dict[str, Any]]:
    """
    Build nested branch tree representation:
    Website Domain
      └── Search Queries (e.g. Google/Bing/YouTube query)
            └── Pages & Videos Visited
                  └── Next Navigated Pages (via from_event_id / referrer)
    """
    conn = get_db_connection()
    try:
        conditions = ["1=1"]
        params: List[Any] = []
        if domain and isinstance(domain, str) and domain.strip():
            conditions.append("(e.domain = ? OR e.referrer_url LIKE ?)")
            params.extend([domain.strip(), f"%{domain.strip()}%"])
        if from_time is not None and isinstance(from_time, (int, float)):
            conditions.append("e.timestamp >= ?")
            params.append(float(from_time))
        if to_time is not None and isinstance(to_time, (int, float)):
            conditions.append("e.timestamp <= ?")
            params.append(float(to_time))

        where_sql = " AND ".join(conditions)

        # 1. Fetch all search queries
        sq_sql = f"""
        SELECT id, source, timestamp, url, domain, title, text_content, metadata_json, session_id
        FROM events e
        WHERE event_type = 'search_query' AND {where_sql}
        ORDER BY timestamp ASC;
        """
        sq_rows = conn.execute(sq_sql, params).fetchall()

        # 2. Fetch pages and videos
        pv_sql = f"""
        SELECT id, event_type, source, timestamp, url, domain, title, duration, 
               scroll_depth, from_event_id, referrer_url, metadata_json, session_id
        FROM events e
        WHERE event_type IN ('page_visit', 'page_summary', 'youtube_video') AND {where_sql}
        ORDER BY timestamp ASC;
        """
        pv_rows = conn.execute(pv_sql, params).fetchall()

        # 3. Fetch youtube_videos records for rich video metadata
        yt_sql = "SELECT video_id, title, channel, duration, play_time, search_query, event_id FROM youtube_videos;"
        yt_rows = conn.execute(yt_sql).fetchall()
        yt_by_event: Dict[int, Dict[str, Any]] = {}
        yt_by_query: Dict[str, List[Dict[str, Any]]] = {}
        for y in yt_rows:
            yd = dict(y)
            if y["event_id"]:
                yt_by_event[y["event_id"]] = yd
            q = (y["search_query"] or "").strip().lower()
            if q:
                if q not in yt_by_query:
                    yt_by_query[q] = []
                yt_by_query[q].append(yd)

        # Map pages by from_event_id
        children_by_parent: Dict[int, List[Dict[str, Any]]] = {}
        orphan_pages: List[Dict[str, Any]] = []

        for p in pv_rows:
            parent_id = p["from_event_id"]
            p_dict = dict(p)

            # Check if this is a YouTube video
            if p["id"] in yt_by_event:
                yinfo = yt_by_event[p["id"]]
                p_dict["is_video"] = True
                p_dict["channel"] = yinfo.get("channel")
                p_dict["play_time"] = yinfo.get("play_time", 0.0)
                p_dict["video_id"] = yinfo.get("video_id")
            elif "youtube.com" in (p["domain"] or ""):
                p_dict["is_video"] = True

            if parent_id:
                if parent_id not in children_by_parent:
                    children_by_parent[parent_id] = []
                children_by_parent[parent_id].append(p_dict)
            else:
                orphan_pages.append(p_dict)

        # Recursively construct page navigation subtrees
        def build_page_tree(page_item: Dict[str, Any], visited_set: set) -> Dict[str, Any]:
            pid = page_item["id"]
            if pid in visited_set:
                return {
                    "id": f"page_{pid}",
                    "type": "video" if page_item.get("is_video") else "page",
                    "title": page_item.get("title") or page_item.get("url"),
                    "url": page_item.get("url"),
                    "domain": page_item.get("domain"),
                    "duration": float(page_item.get("duration") or 0.0),
                    "play_time": float(page_item.get("play_time") or 0.0),
                    "timestamp": page_item.get("timestamp"),
                    "children": []
                }
            visited_set.add(pid)

            sub_children = []
            for child in children_by_parent.get(pid, []):
                sub_children.append(build_page_tree(child, visited_set))

            return {
                "id": f"page_{pid}",
                "type": "video" if page_item.get("is_video") else "page",
                "title": page_item.get("title") or page_item.get("url"),
                "url": page_item.get("url"),
                "domain": page_item.get("domain"),
                "duration": float(page_item.get("duration") or 0.0),
                "play_time": float(page_item.get("play_time") or 0.0),
                "channel": page_item.get("channel"),
                "timestamp": page_item.get("timestamp"),
                "children": sub_children
            }

        # Build search branches
        search_nodes = []
        global_visited = set()

        for sq in sq_rows:
            sq_id = sq["id"]
            global_visited.add(sq_id)
            query_str = (sq["text_content"] or sq["title"] or "").replace("Search: ", "").strip()

            # Linked pages under this search
            direct_pages = children_by_parent.get(sq_id, [])

            page_children = [build_page_tree(dp, global_visited) for dp in direct_pages]

            search_nodes.append({
                "id": f"search_{sq_id}",
                "type": "search",
                "query": query_str,
                "domain": sq["domain"],
                "url": sq["url"],
                "timestamp": sq["timestamp"],
                "children": page_children
            })

        # Group by Root Domain
        domains_map: Dict[str, Dict[str, Any]] = {}
        for sn in search_nodes:
            d = sn["domain"] or "other"
            if d not in domains_map:
                domains_map[d] = {
                    "id": f"domain_{d}",
                    "type": "domain",
                    "label": d,
                    "children": []
                }
            domains_map[d]["children"].append(sn)

        # Unattached orphan pages go into "Direct Visits" branch
        unattached = [p for p in orphan_pages if p["id"] not in global_visited]
        if unattached:
            for up in unattached:
                d = up["domain"] or "other"
                if d not in domains_map:
                    domains_map[d] = {
                        "id": f"domain_{d}",
                        "type": "domain",
                        "label": d,
                        "children": []
                    }
                pt = build_page_tree(up, global_visited)
                domains_map[d]["children"].append(pt)

        return list(domains_map.values())
    finally:
        conn.close()


def get_youtube_searches_list(limit: int = 100) -> List[Dict[str, Any]]:
    """Retrieve list of searches conducted on YouTube with linked videos count."""
    conn = get_db_connection()
    try:
        sql = """
        SELECT 
            e.id,
            e.timestamp,
            e.url,
            e.text_content as query,
            COUNT(DISTINCT y.video_id) as video_count,
            SUM(COALESCE(y.play_time, 0.0)) as total_watch_time
        FROM events e
        LEFT JOIN youtube_videos y ON (y.search_query = e.text_content OR y.event_id = e.id)
        WHERE e.event_type = 'search_query' AND (e.domain LIKE '%youtube%' OR e.url LIKE '%youtube%')
        GROUP BY e.id
        ORDER BY e.timestamp DESC
        LIMIT ?;
        """
        rows = conn.execute(sql, (limit,)).fetchall()
        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "url": r["url"],
                "query": r["query"],
                "video_count": r["video_count"],
                "total_watch_time": round(float(r["total_watch_time"] or 0.0), 1)
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_youtube_videos_list(
    query: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Retrieve list of watched YouTube videos with real play times and channels."""
    conn = get_db_connection()
    try:
        conditions = ["1=1"]
        params: List[Any] = []
        if query and isinstance(query, str) and query.strip():
            conditions.append("(title LIKE ? OR channel LIKE ? OR search_query LIKE ?)")
            q_pat = f"%{query.strip()}%"
            params.extend([q_pat, q_pat, q_pat])

        where_sql = " AND ".join(conditions)
        lim = limit if isinstance(limit, int) else 100
        params.append(lim)

        sql = f"""
        SELECT 
            video_id,
            title,
            channel,
            description,
            duration,
            play_time,
            upload_date,
            search_query,
            referrer_url,
            event_id,
            created_at,
            updated_at
        FROM youtube_videos
        WHERE {where_sql}
        ORDER BY updated_at DESC
        LIMIT ?;
        """
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
