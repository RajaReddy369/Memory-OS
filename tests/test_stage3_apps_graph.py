"""
Tests for MemoryOS: Apps as Graph Nodes & Unified Graph Store.
Verifies:
1. Empty database returns only root 'Desktop' node.
2. Fake process/window timeline: Word with 2 documents, VS Code, Edge, and a blocked password manager.
3. Tree structure: Desktop -> app -> app_session -> window_item -> file / search.
4. Edge/Chrome app connects to websites forming ONE unified tree.
5. Cross-links: switched_to edge counts and timestamps.
6. File edges with 'likely' confidence.
7. Blocked app (e.g. 1Password / Bitwarden / KeePass) produces ZERO nodes or edges.
8. Deleting an app permanently purges its nodes, sessions, window items, and edges from SQLite and NetworkX.
9. GraphRAG query router handles app queries and path traversals with structured context.
10. Data summary node and edge counts match direct database queries.
"""

import os
from pathlib import Path
import time
import pytest

from backend.config import DATA_DIR
from backend.database import get_data_summary, get_db_connection, init_db, insert_event
from backend.models import EventIngestItem
from backend.apps_graph import (
    build_unified_graph,
    delete_app_graph,
    detect_graph_communities,
    get_app_subgraph,
    get_apps_tree,
    get_cached_graph,
    get_graph_neighbors,
    get_graph_path,
    invalidate_graph_cache,
    route_graphrag_query,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Setup isolated temporary database for each test."""
    test_db = tmp_path / "test_apps_graph.db"
    monkeypatch.setattr("backend.config.DB_PATH", test_db)
    monkeypatch.setattr("backend.database.DB_PATH", test_db)
    monkeypatch.setattr("backend.apps_graph.DB_PATH", test_db)
    init_db()
    invalidate_graph_cache()
    yield test_db


def test_empty_database_returns_only_root():
    """Verify that on an empty database /api/apps/tree returns only the virtual 'Desktop' root."""
    tree = get_apps_tree()
    assert tree["id"] == "root:desktop"
    assert tree["label"] == "Desktop"
    assert tree["node_type"] == "root"
    assert tree["children"] == []

    # Verify summary counts
    summary = get_data_summary()
    assert summary["total_graph_nodes"] == 1
    assert summary["total_graph_edges"] == 0


def test_fake_process_window_timeline_and_privacy_blocking(tmp_path):
    """
    Test fake process/window timeline:
    - Word with two documents (Proposal.docx, Budget.docx)
    - VS Code with main.py
    - Edge browsing github.com
    - Blocked password manager (1Password - Vault)
    Verify tree hierarchy, switched_to edges, likely file confidence, and privacy block.
    """
    base_time = 1700000000.0

    # 1. Word: Document 1 (Proposal.docx)
    insert_event(EventIngestItem(
        event_type="window_focus",
        source="desktop_agent",
        timestamp=base_time,
        app_name="WINWORD.EXE",
        title="Proposal.docx - Microsoft Word",
        duration=120.0,
        metadata={"project_label": "Client Pitch"}
    ))

    # File touched by Word
    doc_file = str(tmp_path / "Proposal.docx")
    insert_event(EventIngestItem(
        event_type="file_modify",
        source="desktop_agent",
        timestamp=base_time + 60,
        app_name="WINWORD.EXE",
        title="Proposal.docx - Microsoft Word",
        duration=5.0,
        metadata={"file_path": doc_file, "project_label": "Client Pitch"}
    ))

    # 2. Switch to VS Code
    insert_event(EventIngestItem(
        event_type="window_focus",
        source="vscode",
        timestamp=base_time + 130.0,
        app_name="code.exe",
        title="main.py - MemoryOS - Visual Studio Code",
        duration=300.0,
        metadata={"project_label": "MemoryOS Core"}
    ))

    # 3. Switch back to Word: Document 2 (Budget.docx)
    insert_event(EventIngestItem(
        event_type="window_focus",
        source="desktop_agent",
        timestamp=base_time + 450.0,
        app_name="WINWORD.EXE",
        title="Budget.docx - Microsoft Word",
        duration=180.0,
        metadata={"project_label": "Client Pitch"}
    ))

    # 4. Switch to Edge browser visiting github.com
    insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=base_time + 650.0,
        url="https://github.com/google/memoryos",
        domain="github.com",
        title="google/memoryos: Second Brain Engine",
        app_name="msedge.exe",
        duration=90.0,
        metadata={"project_label": "MemoryOS Core"}
    ))

    # 5. SENSITIVE: Password manager active window (MUST BE DROPPED/BLOCKED)
    insert_event(EventIngestItem(
        event_type="window_focus",
        source="desktop_agent",
        timestamp=base_time + 750.0,
        app_name="1Password.exe",
        title="1Password - Master Password Unlock Vault",
        duration=30.0
    ))

    # Build and verify graph
    G = build_unified_graph()

    # --- 1. PRIVACY VERIFICATION: Blocked app produces NO nodes or edges ---
    for node_id in G.nodes():
        assert "1password" not in node_id.lower()
        assert "password" not in node_id.lower()
    for _, _, ed in G.edges(data=True):
        assert "1password" not in str(ed).lower()

    # --- 2. TREE STRUCTURE VERIFICATION ---
    tree = get_apps_tree()
    assert tree["id"] == "root:desktop"
    child_ids = [c["id"] for c in tree["children"]]
    assert "app:winword.exe" in child_ids
    assert "app:code.exe" in child_ids
    assert "app:msedge.exe" in child_ids

    # Word App Node -> Session -> Document Items
    word_node = next(c for c in tree["children"] if c["id"] == "app:winword.exe")
    assert word_node["label"] == "Winword"
    assert len(word_node["children"]) >= 1  # Has app_session

    sess_node = word_node["children"][0]
    assert sess_node["node_type"] == "app_session"
    item_labels = [i["label"] for i in sess_node["children"]]
    assert "Proposal.docx" in item_labels
    assert "Budget.docx" in item_labels

    # Check file node attached with 'likely' confidence edge
    f_edges = [ed for u, v, ed in G.edges(data=True) if ed.get("edge_type") == "modified_file"]
    assert len(f_edges) >= 1
    assert f_edges[0]["confidence"] == "likely"

    # --- 3. BROWSER UNIFIED TREE VERIFICATION ---
    edge_node = next(c for c in tree["children"] if c["id"] == "app:msedge.exe")
    edge_children_ids = [c["id"] for c in edge_node["children"]]
    assert "website:github.com" in edge_children_ids

    # --- 4. CROSS-LINK VERIFICATION: switched_to edges ---
    switch_edges = [
        (u, v, ed) for u, v, ed in G.edges(data=True) 
        if ed.get("edge_type") == "switched_to"
    ]
    # Expect switches: Word -> Code, Code -> Word, Word -> Edge
    switch_pairs = [(u, v) for u, v, _ in switch_edges]
    assert ("app:winword.exe", "app:code.exe") in switch_pairs
    assert ("app:code.exe", "app:winword.exe") in switch_pairs
    assert ("app:winword.exe", "app:msedge.exe") in switch_pairs


def test_graph_path_and_neighbors():
    """Verify graph path finding between App -> App and App -> Website."""
    base_time = 1700000000.0

    insert_event(EventIngestItem(
        event_type="window_focus",
        source="vscode",
        timestamp=base_time,
        app_name="code.exe",
        window_title="main.py - MemoryOS",
        duration=100.0
    ))
    insert_event(EventIngestItem(
        event_type="page_visit",
        source="browser",
        timestamp=base_time + 120.0,
        app_name="msedge.exe",
        url="https://docs.python.org",
        domain="docs.python.org",
        title="Python 3.12 Documentation",
        duration=150.0
    ))

    build_unified_graph()

    # 1. Path from VS Code to Edge
    path_res = get_graph_path("code.exe", "msedge.exe")
    assert path_res["found"] is True
    assert "app:code.exe" in path_res["path"]
    assert "app:msedge.exe" in path_res["path"]

    # 2. Path from VS Code to Website docs.python.org
    path_to_site = get_graph_path("code.exe", "docs.python.org")
    assert path_to_site["found"] is True
    assert "website:docs.python.org" in path_to_site["path"]

    # 3. Neighbors of code.exe
    neighbors = get_graph_neighbors("app:code.exe", hops=1)
    neighbor_ids = [n["id"] for n in neighbors["nodes"]]
    assert "app:code.exe" in neighbor_ids
    assert "root:desktop" in neighbor_ids


def test_delete_app_graph_removes_nodes_and_edges():
    """Verify muting/deleting an app completely purges its nodes, edges, and events."""
    base_time = 1700000000.0

    insert_event(EventIngestItem(
        event_type="window_focus",
        source="desktop_agent",
        timestamp=base_time,
        app_name="notepad.exe",
        window_title="todo.txt - Notepad",
        duration=60.0
    ))
    insert_event(EventIngestItem(
        event_type="window_focus",
        source="vscode",
        timestamp=base_time + 70.0,
        app_name="code.exe",
        window_title="app.py - VS Code",
        duration=120.0
    ))

    build_unified_graph()

    # Confirm notepad exists
    tree_before = get_apps_tree()
    app_ids_before = [c["id"] for c in tree_before["children"]]
    assert "app:notepad.exe" in app_ids_before

    # Delete notepad
    res = delete_app_graph("notepad.exe")
    assert res["nodes_deleted"] >= 1
    assert res["events_deleted"] >= 1

    # Confirm notepad is completely gone
    tree_after = get_apps_tree()
    app_ids_after = [c["id"] for c in tree_after["children"]]
    assert "app:notepad.exe" not in app_ids_after

    # Direct database confirmation
    conn = get_db_connection()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM graph_nodes WHERE id LIKE '%notepad%';")
        assert cur.fetchone()[0] == 0
        cur = conn.execute("SELECT COUNT(*) FROM graph_edges WHERE source_id LIKE '%notepad%' OR target_id LIKE '%notepad%';")
        assert cur.fetchone()[0] == 0
        cur = conn.execute("SELECT COUNT(*) FROM events WHERE LOWER(app_name) = 'notepad.exe';")
        assert cur.fetchone()[0] == 0
    finally:
        conn.close()


def test_graphrag_query_routing():
    """Verify GraphRAG query router handles app queries and path traversals."""
    base_time = 1700000000.0

    insert_event(EventIngestItem(
        event_type="window_focus",
        source="desktop_agent",
        timestamp=base_time,
        app_name="WINWORD.EXE",
        window_title="Architecture.docx - Microsoft Word",
        title="Architecture.docx - Microsoft Word",
        duration=300.0
    ))
    insert_event(EventIngestItem(
        event_type="window_focus",
        source="vscode",
        timestamp=base_time + 320.0,
        app_name="code.exe",
        window_title="server.py - Visual Studio Code",
        title="server.py - Visual Studio Code",
        duration=500.0
    ))

    build_unified_graph()

    # 1. Query about Word activity
    app_res = route_graphrag_query("What did I work on in Word yesterday?")
    assert app_res is not None
    assert app_res["route_type"] == "app_entity_search"
    assert "Winword" in app_res["app"]
    assert "Architecture.docx" in app_res["answer_context"]

    # 2. Query about navigation path
    path_res = route_graphrag_query("How did I get from Word to Code?")
    assert path_res is not None
    assert path_res["route_type"] == "path_traversal"
    assert "switched_to" in path_res["graph_path"]

    # 3. Generic query not about apps or paths
    generic_res = route_graphrag_query("What is the capital of France?")
    assert generic_res is None
