"""
MemoryOS Apps as Graph Nodes & Unified Graph Store.
Represents every application, session, window/document, file, and browser navigation
in a unified graph store (graph_nodes / graph_edges) with NetworkX integration.
REAL DATA ONLY: Built strictly from stored SQLite rows.
"""

from collections import defaultdict
import json
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

from backend.config import BLOCKED_WINDOW_TITLES, DATA_DIR, DB_PATH
from backend.database import get_db_connection
from backend.scrubber import is_domain_blocked, scrub_text

logger = logging.getLogger("memoryos.apps_graph")

# In-memory cached NetworkX DiGraph
_in_memory_nx_graph: Optional[nx.DiGraph] = None
_last_graph_build_ts: float = 0.0


def invalidate_graph_cache():
    """Invalidate in-memory NetworkX graph so future queries re-sync from database."""
    global _in_memory_nx_graph
    _in_memory_nx_graph = None


def is_sensitive_window_or_app(title: Optional[str], app_name: Optional[str]) -> bool:
    """Strict privacy filter: blocks password managers, banking, incognito, etc."""
    combined = f"{title or ''} {app_name or ''}".lower()
    for kw in BLOCKED_WINDOW_TITLES:
        if kw.lower() in combined:
            return True
    return False


def is_blocked_domain(domain: Optional[str]) -> bool:
    """Check if domain is in sensitive financial / banking blocklist."""
    if not domain:
        return False
    return is_domain_blocked(f"https://{domain}")


def clean_app_name(raw_app: Optional[str]) -> str:
    """Standardize application identifier (e.g. C:\\...\\Code.exe -> code.exe)."""
    if not raw_app:
        return "unknown_app"
    base = Path(raw_app).name.lower()
    return base if base else raw_app.lower()


def clean_window_title(raw_title: Optional[str]) -> str:
    """Clean and scrub window titles for display."""
    if not raw_title:
        return "Untitled Window"
    scrubbed = scrub_text(raw_title).strip()
    return scrubbed[:120] if scrubbed else "Untitled Window"


def extract_document_name(window_title: str, app_name: str) -> str:
    """Extract document/file/workspace from window title (e.g. 'report.docx - Word' -> 'report.docx')."""
    if not window_title:
        return "Untitled Document"
    
    app_lower = app_name.lower()
    title = window_title.strip()

    # Common application title separators ( - , • , | )
    for sep in [" - ", " – ", " — ", " • ", " | "]:
        if sep in title:
            parts = title.split(sep)
            # Typically document is the first part, application is the last
            if len(parts) >= 2:
                candidate = parts[0].strip()
                if candidate and candidate.lower() not in app_lower:
                    return candidate[:100]
    return title[:100]


def build_unified_graph(conn: Optional[sqlite3.Connection] = None) -> nx.DiGraph:
    """
    Build unified graph (Desktop -> App -> Session -> Window -> File/Search + Websites)
    strictly from stored database rows and persist into graph_nodes and graph_edges.
    """
    global _in_memory_nx_graph, _last_graph_build_ts

    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    G = nx.DiGraph()
    now = time.time()

    try:
        # 1. Ensure Virtual Root Node: "root:desktop"
        root_node_id = "root:desktop"
        G.add_node(
            root_node_id,
            id=root_node_id,
            node_type="root",
            label="Desktop",
            weight=0.0,
            source="system",
            parent_id=None,
            properties={"platform": "Windows"}
        )

        # 2. Fetch all real events ordered by timestamp
        cur = conn.execute("""
            SELECT id, event_type, source, timestamp, url, domain, app_name, 
                   title, text_content, duration, metadata_json, referrer_url
            FROM events
            ORDER BY timestamp ASC;
        """)
        events = [dict(row) for row in cur.fetchall()]

        if not events:
            # Empty database: persist only root node and return
            _persist_graph_to_sqlite(G, conn)
            _in_memory_nx_graph = G
            _last_graph_build_ts = now
            return G

        # Track structures for tree and cross-links
        apps_data: Dict[str, Dict[str, Any]] = {}
        app_sessions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        app_total_duration: Dict[str, float] = defaultdict(float)
        app_last_source: Dict[str, str] = {}
        window_items: Dict[str, Dict[str, Any]] = {}
        file_nodes: Dict[str, Dict[str, Any]] = {}
        website_nodes: Dict[str, Dict[str, Any]] = {}
        search_query_nodes: Dict[str, Dict[str, Any]] = {}

        # Cross-link tracking
        switch_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        switch_last_time: Dict[Tuple[str, str], float] = {}
        app_files_created: Dict[Tuple[str, str], int] = defaultdict(int)
        app_files_modified: Dict[Tuple[str, str], int] = defaultdict(int)
        app_projects: Dict[Tuple[str, str], int] = defaultdict(int)

        last_foreground_app: Optional[str] = None
        last_foreground_time: float = 0.0

        # Segment into app sessions (time gap > 15 mins = new session)
        app_current_session_id: Dict[str, str] = {}
        app_session_counter: Dict[str, int] = defaultdict(int)
        app_session_last_time: Dict[str, float] = {}

        for ev in events:
            meta = {}
            if ev.get("metadata_json"):
                try:
                    meta = json.loads(ev["metadata_json"])
                except Exception:
                    pass

            raw_app = ev.get("app_name")
            raw_title = ev.get("title") or meta.get("window_title")
            ev_source = ev.get("source") or "desktop_agent"
            ts = float(ev.get("timestamp") or now)
            duration = float(ev.get("duration") or 0.0)
            file_path = meta.get("file_path") or (ev.get("url") if str(ev.get("url") or "").startswith("file://") else None)
            project_label = meta.get("project_label") or meta.get("project")

            # Skip blocked sensitive apps / windows
            if is_sensitive_window_or_app(raw_title, raw_app):
                continue

            # Standardize app name
            app = clean_app_name(raw_app) if raw_app else None

            # If browser event without explicit app_name, assign default browser app
            if not app and (ev.get("domain") or ev.get("url")):
                app = "msedge.exe"
                ev_source = "extension_live" if ev_source == "browser" else ev_source

            if not app:
                continue

            app_node_id = f"app:{app}"
            app_total_duration[app] += max(duration, 5.0)
            app_last_source[app] = ev_source

            # Cross-link: switched_to (from previous distinct foreground app)
            if last_foreground_app and last_foreground_app != app:
                # Discard switch gaps > 1 hour
                if 0 < (ts - last_foreground_time) <= 3600:
                    pair = (f"app:{last_foreground_app}", app_node_id)
                    switch_counts[pair] += 1
                    switch_last_time[pair] = ts

            last_foreground_app = app
            last_foreground_time = ts

            # Session Segmentation for this app
            sess_gap = ts - app_session_last_time.get(app, 0.0)
            if app not in app_current_session_id or sess_gap > 900.0:  # 15 minutes
                app_session_counter[app] += 1
                curr_sid = f"app_session:{app}_s{app_session_counter[app]}"
                app_current_session_id[app] = curr_sid

            app_session_last_time[app] = ts
            curr_sess_id = app_current_session_id[app]

            # Add event to app session
            app_sessions[curr_sess_id].append({
                "app": app,
                "app_node_id": app_node_id,
                "timestamp": ts,
                "duration": duration,
                "event": ev
            })

            # Project cross-link
            if project_label:
                app_projects[(app_node_id, f"project:{project_label}")] += 1

            # Window Item (Document / Window / Tab)
            if raw_title:
                clean_title = clean_window_title(raw_title)
                doc_name = extract_document_name(clean_title, app)
                win_id = f"window_item:{app}_{abs(hash(clean_title)) % 10000000}"
                
                if win_id not in window_items:
                    window_items[win_id] = {
                        "id": win_id,
                        "node_type": "window_item",
                        "label": doc_name,
                        "full_title": clean_title,
                        "parent_id": curr_sess_id,
                        "app": app,
                        "weight": 0.0,
                        "source": ev_source,
                        "files": set()
                    }
                window_items[win_id]["weight"] += max(duration, 5.0)

                # File touch linkage
                if file_path:
                    fpath = str(Path(file_path).as_posix())
                    fid = f"file:{fpath}"
                    file_nodes[fid] = {
                        "id": fid,
                        "node_type": "file",
                        "label": Path(fpath).name,
                        "path": fpath,
                        "parent_id": win_id,
                        "source": ev_source,
                        "weight": 1.0
                    }
                    window_items[win_id]["files"].add(fid)

                    # Likely app created/modified
                    if "create" in (ev.get("event_type") or "").lower():
                        app_files_created[(app_node_id, fid)] += 1
                    else:
                        app_files_modified[(app_node_id, fid)] += 1

            # Website / Browser tree integration
            domain = ev.get("domain")
            if domain and not is_blocked_domain(domain):
                site_id = f"website:{domain.lower()}"
                if site_id not in website_nodes:
                    website_nodes[site_id] = {
                        "id": site_id,
                        "node_type": "website",
                        "label": domain.lower(),
                        "parent_id": app_node_id,  # Edge/Chrome app is parent of website city!
                        "weight": 0.0,
                        "source": ev_source,
                        "pages": set()
                    }
                website_nodes[site_id]["weight"] += max(duration, 10.0)

                # Search query node
                if ev.get("event_type") == "search_query" and ev.get("title"):
                    sq_text = ev["title"]
                    sq_id = f"search_query:{domain.lower()}_{abs(hash(sq_text)) % 1000000}"
                    search_query_nodes[sq_id] = {
                        "id": sq_id,
                        "node_type": "search_query",
                        "label": sq_text,
                        "parent_id": site_id,
                        "source": ev_source,
                        "weight": 1.0
                    }

        # ----------------------------------------------------
        # Build Tree Nodes & Tree Edges
        # ----------------------------------------------------

        # Add Apps
        for app, total_dur in app_total_duration.items():
            app_id = f"app:{app}"
            display_label = app.replace(".exe", "").capitalize()
            G.add_node(
                app_id,
                id=app_id,
                node_type="app",
                label=display_label,
                weight=round(total_dur, 2),
                source=app_last_source.get(app, "desktop_agent"),
                parent_id=root_node_id,
                properties={"app_name": app, "total_foreground_seconds": round(total_dur, 2)}
            )
            # Tree edge: Desktop -> App
            G.add_edge(
                root_node_id,
                app_id,
                id=f"edge:{root_node_id}->{app_id}",
                edge_type="tree_child",
                weight=round(total_dur, 2),
                confidence="confirmed",
                properties={"relationship": "desktop_app"}
            )

        # Add App Sessions
        for sess_id, ev_list in app_sessions.items():
            if not ev_list:
                continue
            app = ev_list[0]["app"]
            app_id = ev_list[0]["app_node_id"]
            sess_dur = sum(e["duration"] for e in ev_list)
            start_ts = min(e["timestamp"] for e in ev_list)
            end_ts = max(e["timestamp"] for e in ev_list)
            sess_label = f"Session ({math.ceil(max(sess_dur, 60)/60)}m)"

            G.add_node(
                sess_id,
                id=sess_id,
                node_type="app_session",
                label=sess_label,
                weight=round(max(sess_dur, 60.0), 2),
                source=app_last_source.get(app, "desktop_agent"),
                parent_id=app_id,
                properties={
                    "start_time": start_ts,
                    "end_time": end_ts,
                    "event_count": len(ev_list)
                }
            )
            # Tree edge: App -> App Session
            G.add_edge(
                app_id,
                sess_id,
                id=f"edge:{app_id}->{sess_id}",
                edge_type="tree_child",
                weight=round(max(sess_dur, 60.0), 2),
                confidence="confirmed",
                properties={"relationship": "app_session"}
            )

        # Add Window Items
        for win_id, wdata in window_items.items():
            parent_sess = wdata["parent_id"]
            # Fallback if session node not present
            if not G.has_node(parent_sess):
                # Attach to app node directly
                parent_sess = f"app:{wdata['app']}"

            G.add_node(
                win_id,
                id=win_id,
                node_type="window_item",
                label=wdata["label"],
                weight=round(wdata["weight"], 2),
                source=wdata["source"],
                parent_id=parent_sess,
                properties={"full_window_title": wdata["full_title"], "app": wdata["app"]}
            )
            # Tree edge: Session -> Window Item
            G.add_edge(
                parent_sess,
                win_id,
                id=f"edge:{parent_sess}->{win_id}",
                edge_type="tree_child",
                weight=round(wdata["weight"], 2),
                confidence="confirmed",
                properties={"relationship": "active_window_item"}
            )

        # Add Files
        for fid, fdata in file_nodes.items():
            p_id = fdata["parent_id"]
            if not G.has_node(p_id):
                p_id = root_node_id

            G.add_node(
                fid,
                id=fid,
                node_type="file",
                label=fdata["label"],
                weight=fdata["weight"],
                source=fdata["source"],
                parent_id=p_id,
                properties={"path": fdata["path"]}
            )
            # Tree edge: Window Item -> File
            G.add_edge(
                p_id,
                fid,
                id=f"edge:{p_id}->{fid}",
                edge_type="tree_child",
                weight=1.0,
                confidence="likely",
                properties={"relationship": "opened_file"}
            )

        # Add Websites & Searches (Unified under Edge/Chrome browser node)
        for sid, sdata in website_nodes.items():
            p_app = sdata["parent_id"]
            if not G.has_node(p_app):
                # Ensure browser app node exists
                G.add_node(p_app, id=p_app, node_type="app", label="Edge", weight=10.0, source="extension_live", parent_id=root_node_id)
                G.add_edge(root_node_id, p_app, id=f"edge:{root_node_id}->{p_app}", edge_type="tree_child", weight=10.0)

            G.add_node(
                sid,
                id=sid,
                node_type="website",
                label=sdata["label"],
                weight=round(sdata["weight"], 2),
                source=sdata["source"],
                parent_id=p_app,
                properties={"domain": sdata["label"]}
            )
            # Tree edge: Browser App -> Website City
            G.add_edge(
                p_app,
                sid,
                id=f"edge:{p_app}->{sid}",
                edge_type="tree_child",
                weight=round(sdata["weight"], 2),
                confidence="confirmed",
                properties={"relationship": "visited_website"}
            )

        for qid, qdata in search_query_nodes.items():
            ws_id = qdata["parent_id"]
            if G.has_node(ws_id):
                G.add_node(
                    qid,
                    id=qid,
                    node_type="search_query",
                    label=qdata["label"],
                    weight=qdata["weight"],
                    source=qdata["source"],
                    parent_id=ws_id,
                    properties={"query": qdata["label"]}
                )
                G.add_edge(
                    ws_id,
                    qid,
                    id=f"edge:{ws_id}->{qid}",
                    edge_type="tree_child",
                    weight=1.0,
                    confidence="confirmed",
                    properties={"relationship": "search_query"}
                )

        # ----------------------------------------------------
        # Cross-Link Edges (Graph Edges)
        # ----------------------------------------------------

        # 1. switched_to (app A -> app B)
        for (src_app, dst_app), count in switch_counts.items():
            if G.has_node(src_app) and G.has_node(dst_app):
                edge_id = f"switch:{src_app}->{dst_app}"
                G.add_edge(
                    src_app,
                    dst_app,
                    id=edge_id,
                    edge_type="switched_to",
                    weight=float(count),
                    confidence="confirmed",
                    properties={
                        "switch_count": count,
                        "last_switched": switch_last_time.get((src_app, dst_app), now)
                    }
                )

        # 2. created_file / modified_file (app -> file) with confidence "likely"
        for (app_node, f_node), cnt in app_files_created.items():
            if G.has_node(app_node) and G.has_node(f_node):
                e_id = f"created:{app_node}->{f_node}"
                G.add_edge(
                    app_node,
                    f_node,
                    id=e_id,
                    edge_type="created_file",
                    weight=float(cnt),
                    confidence="likely",
                    properties={"count": cnt}
                )

        for (app_node, f_node), cnt in app_files_modified.items():
            if G.has_node(app_node) and G.has_node(f_node):
                e_id = f"modified:{app_node}->{f_node}"
                G.add_edge(
                    app_node,
                    f_node,
                    id=e_id,
                    edge_type="modified_file",
                    weight=float(cnt),
                    confidence="likely",
                    properties={"count": cnt}
                )

        # 3. used_in_project (app -> project)
        for (app_node, proj_node), cnt in app_projects.items():
            if G.has_node(app_node):
                if not G.has_node(proj_node):
                    p_name = proj_node.replace("project:", "")
                    G.add_node(proj_node, id=proj_node, node_type="project", label=p_name, weight=float(cnt), source="desktop_agent", parent_id=root_node_id)
                e_id = f"proj:{app_node}->{proj_node}"
                G.add_edge(
                    app_node,
                    proj_node,
                    id=e_id,
                    edge_type="used_in_project",
                    weight=float(cnt),
                    confidence="confirmed",
                    properties={"event_count": cnt}
                )

        # Persist to SQLite
        _persist_graph_to_sqlite(G, conn)
        _in_memory_nx_graph = G
        _last_graph_build_ts = now
        return G

    finally:
        if should_close:
            conn.close()


def _persist_graph_to_sqlite(G: nx.DiGraph, conn: sqlite3.Connection):
    """Save graph nodes and edges into graph_nodes and graph_edges tables."""
    now = time.time()
    with conn:
        conn.execute("DELETE FROM graph_nodes;")
        conn.execute("DELETE FROM graph_edges;")

        # Insert nodes
        for node_id, data in G.nodes(data=True):
            props = data.get("properties") or {}
            conn.execute("""
                INSERT OR REPLACE INTO graph_nodes 
                (id, node_type, label, weight, source, parent_id, properties, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                node_id,
                data.get("node_type", "node"),
                data.get("label", node_id),
                float(data.get("weight", 1.0)),
                data.get("source", "desktop_agent"),
                data.get("parent_id"),
                json.dumps(props),
                now,
                now
            ))

        # Insert edges
        for u, v, data in G.edges(data=True):
            edge_id = data.get("id") or f"edge:{u}->{v}"
            props = data.get("properties") or {}
            conn.execute("""
                INSERT OR REPLACE INTO graph_edges
                (id, source_id, target_id, edge_type, weight, confidence, properties, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                edge_id,
                u,
                v,
                data.get("edge_type", "tree_child"),
                float(data.get("weight", 1.0)),
                data.get("confidence", "confirmed"),
                json.dumps(props),
                now
            ))


def get_cached_graph(conn: Optional[sqlite3.Connection] = None, force_rebuild: bool = False) -> nx.DiGraph:
    """Retrieve in-memory NetworkX DiGraph, refreshing from DB if stale."""
    global _in_memory_nx_graph, _last_graph_build_ts
    if _in_memory_nx_graph is None or force_rebuild or (time.time() - _last_graph_build_ts) > 60.0:
        return build_unified_graph(conn=conn)
    return _in_memory_nx_graph


def get_apps_tree(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Retrieve nested hierarchy starting from 'root:desktop':
    Desktop -> App -> App Session -> Window Item -> File / Search.
    Empty database returns only root node.
    """
    G = get_cached_graph(conn=conn)
    root_id = "root:desktop"
    if not G.has_node(root_id) or len(G.nodes) <= 1:
        G = build_unified_graph(conn=conn)

    # Find root
    if not G.has_node(root_id):
        return {
            "id": root_id,
            "label": "Desktop",
            "node_type": "root",
            "weight": 0.0,
            "source": "system",
            "children": []
        }

    # Recursive builder
    def build_subtree(curr_id: str, visited: Set[str]) -> Dict[str, Any]:
        node_data = G.nodes[curr_id]
        visited.add(curr_id)

        # Children are targets of 'tree_child' edges where parent_id matches curr_id
        children = []
        for _, target, edge_data in G.out_edges(curr_id, data=True):
            if edge_data.get("edge_type") == "tree_child" and target not in visited:
                child_data = G.nodes.get(target)
                if child_data and child_data.get("parent_id") == curr_id:
                    children.append(build_subtree(target, visited))

        # Sort children by weight descending
        children.sort(key=lambda c: c.get("weight", 0.0), reverse=True)

        return {
            "id": curr_id,
            "label": node_data.get("label", curr_id),
            "node_type": node_data.get("node_type", "node"),
            "weight": node_data.get("weight", 0.0),
            "source": node_data.get("source", "desktop_agent"),
            "properties": node_data.get("properties") or {},
            "children": children
        }

    return build_subtree(root_id, set())


def get_graph_neighbors(node_id: str, hops: int = 1, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Retrieve neighbor subgraph around node_id up to 'hops' distance."""
    G = get_cached_graph(conn=conn)

    if not G.has_node(node_id):
        # Case insensitive lookup
        matched = None
        for n in G.nodes():
            if n.lower() == node_id.lower() or G.nodes[n].get("label", "").lower() == node_id.lower():
                matched = n
                break
        if matched:
            node_id = matched
        else:
            return {"center_id": node_id, "nodes": [], "edges": []}

    # BFS exploration
    visited_nodes: Set[str] = {node_id}
    queue: List[Tuple[str, int]] = [(node_id, 0)]

    while queue:
        curr, depth = queue.pop(0)
        if depth >= hops:
            continue
        for neighbor in G.to_undirected().neighbors(curr):
            if neighbor not in visited_nodes:
                visited_nodes.add(neighbor)
                queue.append((neighbor, depth + 1))

    subgraph_nodes = []
    for nid in visited_nodes:
        nd = G.nodes[nid]
        subgraph_nodes.append({
            "id": nid,
            "label": nd.get("label", nid),
            "node_type": nd.get("node_type", "node"),
            "weight": nd.get("weight", 1.0),
            "source": nd.get("source", "desktop_agent"),
            "properties": nd.get("properties") or {}
        })

    subgraph_edges = []
    for u, v, ed in G.edges(visited_nodes, data=True):
        if u in visited_nodes and v in visited_nodes:
            subgraph_edges.append({
                "id": ed.get("id", f"{u}->{v}"),
                "source": u,
                "target": v,
                "edge_type": ed.get("edge_type", "cross_link"),
                "weight": ed.get("weight", 1.0),
                "confidence": ed.get("confidence", "confirmed"),
                "properties": ed.get("properties") or {}
            })

    return {
        "center_id": node_id,
        "hops": hops,
        "nodes": subgraph_nodes,
        "edges": subgraph_edges
    }


def get_graph_path(from_id: str, to_id: str, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Find shortest path between from_id and to_id (app to app, app to website, etc.)."""
    G = get_cached_graph(conn=conn)

    # Resolve loose identifiers
    def resolve_id(ident: str) -> Optional[str]:
        if G.has_node(ident):
            return ident
        # Try prefixes
        for prefix in ["app:", "website:", "file:", "window_item:", ""]:
            cand = f"{prefix}{ident}"
            if G.has_node(cand):
                return cand
        # Match label
        ident_lower = ident.lower()
        for n, d in G.nodes(data=True):
            if d.get("label", "").lower() == ident_lower or n.lower() == ident_lower:
                return n

        # Match common application aliases
        app_aliases = {
            "word": ["winword", "word", "microsoft word"],
            "code": ["code", "vscode", "vs code"],
            "vscode": ["code", "vscode", "vs code"],
            "edge": ["msedge", "edge"],
            "chrome": ["chrome", "google chrome"],
            "notepad": ["notepad"],
            "excel": ["excel"]
        }
        for kw, aliases in app_aliases.items():
            if ident_lower == kw or ident_lower in aliases:
                for n, d in G.nodes(data=True):
                    if d.get("node_type") == "app":
                        app_lbl = d.get("label", "").lower()
                        app_raw = (d.get("properties") or {}).get("app_name", "").lower()
                        if any(a in app_lbl or a in app_raw for a in aliases):
                            return n
        return None

    src = resolve_id(from_id)
    dst = resolve_id(to_id)

    if not src or not dst:
        return {
            "found": False,
            "from_id": from_id,
            "to_id": to_id,
            "error": f"One or both endpoints not found (src={src}, dst={dst})"
        }

    # Search path in undirected view to allow multi-directional navigation
    undirected = G.to_undirected()
    try:
        path_nodes = nx.shortest_path(undirected, source=src, target=dst)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return {
            "found": False,
            "from_id": src,
            "to_id": dst,
            "message": "No connecting path found between nodes."
        }

    # Collect edges along path
    path_edges = []
    formatted_steps = []
    for i in range(len(path_nodes) - 1):
        u, v = path_nodes[i], path_nodes[i + 1]
        u_label = G.nodes[u].get("label", u)
        u_type = G.nodes[u].get("node_type", "node")
        v_label = G.nodes[v].get("label", v)
        v_type = G.nodes[v].get("node_type", "node")

        # Check edge direction in directed graph
        edge_data = G.get_edge_data(u, v) or G.get_edge_data(v, u) or {}
        e_type = edge_data.get("edge_type", "connected_to")
        path_edges.append({
            "source": u,
            "target": v,
            "edge_type": e_type,
            "weight": edge_data.get("weight", 1.0)
        })
        formatted_steps.append(f"[{u_type.capitalize()}: {u_label}] --({e_type})--> [{v_type.capitalize()}: {v_label}]")

    return {
        "found": True,
        "from_id": src,
        "to_id": dst,
        "path": path_nodes,
        "edges": path_edges,
        "formatted": " -> ".join(formatted_steps)
    }


def get_app_subgraph(app_name: str, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Retrieve full subgraph for a given application with all cross-links and sessions."""
    app_clean = clean_app_name(app_name)
    app_id = f"app:{app_clean}"
    return get_graph_neighbors(node_id=app_id, hops=2, conn=conn)


def delete_app_graph(app_name: str, conn: Optional[sqlite3.Connection] = None) -> Dict[str, int]:
    """
    Delete all nodes, sessions, window items, and edges related to an app
    from SQLite graph_nodes, graph_edges, NetworkX graph, and events table.
    """
    global _in_memory_nx_graph
    app_clean = clean_app_name(app_name)
    app_id = f"app:{app_clean}"

    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn:
            # 1. Identify all child nodes (sessions, window items, files owned)
            cur = conn.execute("""
                SELECT id FROM graph_nodes 
                WHERE id = ? OR parent_id = ? OR id LIKE ? OR parent_id LIKE ?;
            """, (app_id, app_id, f"app_session:{app_clean}%", f"app_session:{app_clean}%"))
            node_ids_to_del = [r[0] for r in cur.fetchall()]
            node_ids_to_del.append(app_id)

            # 2. Delete edges connected to any of these nodes
            placeholders = ",".join(["?"] * len(node_ids_to_del))
            edge_cur = conn.execute(f"""
                DELETE FROM graph_edges 
                WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders});
            """, node_ids_to_del + node_ids_to_del)
            edges_deleted = edge_cur.rowcount

            # 3. Delete nodes
            node_cur = conn.execute(f"""
                DELETE FROM graph_nodes WHERE id IN ({placeholders});
            """, node_ids_to_del)
            nodes_deleted = node_cur.rowcount

            # 4. Delete corresponding events from events table
            ev_cur = conn.execute("""
                DELETE FROM events 
                WHERE LOWER(app_name) = ? OR LOWER(app_name) LIKE ?;
            """, (app_clean.lower(), f"%{app_clean.lower()}%"))
            events_deleted = ev_cur.rowcount

        # Invalidate in-memory graph
        _in_memory_nx_graph = None
        build_unified_graph(conn=conn)

        return {
            "app": app_clean,
            "nodes_deleted": nodes_deleted,
            "edges_deleted": edges_deleted,
            "events_deleted": events_deleted
        }
    finally:
        if should_close:
            conn.close()


def detect_graph_communities(conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Detect multi-modal graph communities (apps + websites + files + projects)."""
    G = get_cached_graph(conn=conn)
    undirected = G.to_undirected()

    if undirected.number_of_nodes() < 2:
        return []

    try:
        from networkx.algorithms.community import greedy_modularity_communities
        communities = list(greedy_modularity_communities(undirected))
    except Exception:
        return []

    results = []
    for idx, c in enumerate(communities):
        nodes_in_comm = list(c)
        if len(nodes_in_comm) < 2:
            continue

        apps = [G.nodes[n]["label"] for n in nodes_in_comm if G.nodes[n].get("node_type") == "app"]
        sites = [G.nodes[n]["label"] for n in nodes_in_comm if G.nodes[n].get("node_type") == "website"]
        files = [G.nodes[n]["label"] for n in nodes_in_comm if G.nodes[n].get("node_type") == "file"]
        projects = [G.nodes[n]["label"] for n in nodes_in_comm if G.nodes[n].get("node_type") == "project"]

        # Synthesize a descriptive label
        lead_project = projects[0] if projects else "Workspace Activity"
        lead_apps = " + ".join(apps[:3]) if apps else "Tools"
        summary_label = f"{lead_project}: {lead_apps}"
        if files:
            summary_label += f" ({len(files)} files)"

        results.append({
            "community_id": idx + 1,
            "label": summary_label,
            "node_count": len(nodes_in_comm),
            "apps": apps,
            "websites": sites,
            "files": files[:5],
            "projects": projects
        })

    return results


def route_graphrag_query(query: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """
    GraphRAG Query Router:
    Intercepts app queries like 'which apps did I use for X', 'what did I do in Word yesterday',
    'how did I get from VS Code to that page', performing path / neighbor traversal.
    """
    q_lower = query.lower()
    app_keywords = ["app", "apps", "word", "code", "vs code", "vscode", "excel", "notepad", "edge", "chrome", "switch", "navigate"]
    is_app_query = any(k in q_lower for k in app_keywords)

    if not is_app_query:
        return None

    G = get_cached_graph(conn=conn)

    # 1. Path Query: "from X to Y" or "how did I get from X to Y"
    path_match = re.search(r"from\s+([a-zA-Z0-9_\.\s]+)\s+to\s+([a-zA-Z0-9_\.\s]+)", q_lower)
    if path_match:
        from_cand = path_match.group(1).strip()
        to_cand = path_match.group(2).strip()
        path_res = get_graph_path(from_cand, to_cand, conn=conn)
        if path_res.get("found"):
            return {
                "route_type": "path_traversal",
                "from": from_cand,
                "to": to_cand,
                "graph_path": path_res.get("formatted"),
                "nodes": path_res.get("path"),
                "answer_context": f"Graph path verified from {from_cand} to {to_cand}:\n{path_res.get('formatted')}"
            }

    # 2. App-specific query: "what did I do in Word", "how much time in VS Code"
    target_app = None
    app_alias_map = {
        "word": ["winword", "word", "microsoft word"],
        "code": ["code", "vscode", "vs code"],
        "vscode": ["code", "vscode", "vs code"],
        "edge": ["msedge", "edge"],
        "chrome": ["chrome", "google chrome"],
        "notepad": ["notepad"],
        "excel": ["excel"]
    }

    for n, d in G.nodes(data=True):
        if d.get("node_type") == "app":
            app_lbl = d.get("label", "").lower()
            app_raw = (d.get("properties") or {}).get("app_name", "").lower()
            # Direct containment
            if (app_lbl and app_lbl in q_lower) or (app_raw and app_raw in q_lower):
                target_app = n
                break
            # Alias lookup
            for kw, aliases in app_alias_map.items():
                if kw in q_lower:
                    if any(a in app_lbl or a in app_raw for a in aliases):
                        target_app = n
                        break
            if target_app:
                break

    if target_app:
        app_subgraph = get_graph_neighbors(target_app, hops=2, conn=conn)
        app_data = G.nodes[target_app]
        app_name = app_data.get("label", target_app)
        weight_mins = round(app_data.get("weight", 0.0) / 60.0, 1)

        # Extract touched documents and files
        docs = [n["label"] for n in app_subgraph["nodes"] if n["node_type"] == "window_item"]
        files = [n["label"] for n in app_subgraph["nodes"] if n["node_type"] == "file"]
        switches_to = [
            G.nodes[e["target"]]["label"]
            for e in app_subgraph["edges"]
            if e["edge_type"] == "switched_to" and e["source"] == target_app and G.has_node(e["target"])
        ]

        summary_lines = [
            f"**Application:** {app_name} (Total time: ~{weight_mins} minutes)",
            f"**Recent Documents/Windows:** {', '.join(docs[:4]) if docs else 'None'}",
            f"**Files Touched:** {', '.join(files[:4]) if files else 'None'}",
            f"**Switched To:** {', '.join(set(switches_to)) if switches_to else 'None'}"
        ]

        return {
            "route_type": "app_entity_search",
            "app": app_name,
            "target_node": target_app,
            "answer_context": "\n".join(summary_lines),
            "subgraph": app_subgraph
        }

    return None
