"""
Tests for MemoryOS Stage 0: Gap Fixes from Phase 3.
Covers:
1. Downloads folder: log file name/type only, never index contents.
2. Never index .env, *.pem, *.key, id_rsa*, credentials*, secrets*, *.kdbx.
3. Exclude %APPDATA%\\MemoryOS, .venv, .git, node_modules, __pycache__ from file watching.
4. VS Code/Cursor sensitive file typing suppression (.env, config, secrets).
5. Ollama model names (chat, embedding) configurable without code changes.
6. Neural cross-encoder behind config flag with fallback, reported in /api/status.
"""

from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from backend.config import DATA_DIR, OLLAMA_CHAT_MODEL, OLLAMA_EMBEDDING_MODEL
from backend.database import init_db
from backend.models import StatusResponse
from backend.reranker import (
    LexicalSemanticReranker,
    NeuralCrossEncoderReranker,
    get_active_reranker_info,
    get_reranker,
    reset_reranker,
)
from desktop_agent.file_watcher import (
    MemoryOSFileHandler,
    is_ignored_path,
    is_in_downloads,
    is_sensitive_file,
)
from desktop_agent.typing_tracker import SelectiveTypingWatcher, is_sensitive_editor_title


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_stage0.db"
    monkeypatch.setattr("backend.config.DB_PATH", test_db)
    monkeypatch.setattr("backend.database.DB_PATH", test_db)
    init_db()
    yield test_db


# ==============================================================================
# 1. Downloads folder: metadata only, never index contents
# ==============================================================================

def test_downloads_folder_never_indexes_contents(tmp_path, monkeypatch):
    """Confirm files in Downloads folder log name/type but text_content is strictly empty."""
    downloads_dir = tmp_path / "Downloads"
    downloads_dir.mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    sample_download = downloads_dir / "invoice_analysis.txt"
    sample_download.write_text("Confidential financial statement data", encoding="utf-8")

    captured_events = []
    handler = MemoryOSFileHandler(callback=lambda ev: captured_events.append(ev))

    # Trigger event
    handler._handle_event(str(sample_download), "created")

    assert len(captured_events) == 1
    ev = captured_events[0]
    assert ev["title"] == "Downloaded: invoice_analysis.txt"
    assert ev["text_content"] == "", "Downloads files must NEVER have their contents indexed"
    assert ev["metadata"]["file_name"] == "invoice_analysis.txt"
    assert ev["metadata"]["download_metadata_only"] is True


# ==============================================================================
# 2. Never index .env, *.pem, *.key, id_rsa*, credentials*, secrets*, *.kdbx
# ==============================================================================

def test_sensitive_files_are_never_indexed(tmp_path):
    """Verify is_sensitive_file blocks sensitive credential and key files."""
    sensitive_names = [
        ".env",
        ".env.local",
        ".env.production",
        "id_rsa",
        "id_rsa.pub",
        "credentials.json",
        "aws_credentials",
        "secrets.yaml",
        "client_secrets.json",
        "server.pem",
        "private.key",
        "passwords.kdbx",
    ]

    for name in sensitive_names:
        p = tmp_path / name
        assert is_sensitive_file(p) is True, f"Expected {name} to be identified as sensitive"

    safe_names = [
        "main.py",
        "README.md",
        "styles.css",
        "report.docx",
        "dataset.csv",
    ]
    for name in safe_names:
        p = tmp_path / name
        assert is_sensitive_file(p) is False, f"Expected {name} to be identified as safe"

    # Verify file handler discards sensitive files completely
    captured_events = []
    handler = MemoryOSFileHandler(callback=lambda ev: captured_events.append(ev))

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-1234567890", encoding="utf-8")
    handler._handle_event(str(env_file), "modified")

    assert len(captured_events) == 0, "Sensitive .env file must be completely ignored by file handler"


# ==============================================================================
# 3. Exclude self-monitoring: %APPDATA%\MemoryOS, .venv, .git, node_modules
# ==============================================================================

def test_ignored_paths_exclude_self_and_caches(tmp_path):
    """Verify MemoryOS data directory, .venv, .git, and node_modules are ignored."""
    data_dir_path = DATA_DIR / "memoryos.db"
    assert is_ignored_path(data_dir_path) is True, "MemoryOS data directory must be excluded"

    assert is_ignored_path(Path("e:/rag two/.venv/Lib/site-packages/package.py")) is True
    assert is_ignored_path(Path("e:/rag two/.git/index")) is True
    assert is_ignored_path(Path("e:/rag two/frontend/node_modules/three/package.json")) is True
    assert is_ignored_path(Path("e:/rag two/backend/__pycache__/config.pyc")) is True

    # Valid project code file must not be ignored
    assert is_ignored_path(Path("e:/rag two/backend/main.py")) is False


# ==============================================================================
# 4. In VS Code/Cursor, skip typing capture when open file is .env, config, or secrets
# ==============================================================================

def test_vs_code_sensitive_typing_suppression():
    """Verify typing capture drops input when active editor window is editing secrets/config."""
    sensitive_titles = [
        ".env - myproject - Visual Studio Code",
        "● .env.local - Cursor",
        "config.py - MemoryOS - Visual Studio Code",
        "secrets.json - myapp - Cursor",
        "id_rsa - Visual Studio Code",
        "credentials.yaml - Visual Studio Code",
        "app.key - Visual Studio Code",
        "passwords.kdbx - Cursor",
    ]

    for title in sensitive_titles:
        assert is_sensitive_editor_title(title) is True, f"Expected {title} to trigger sensitive editor filter"

    safe_titles = [
        "app.py - MemoryOS - Visual Studio Code",
        "index.tsx - frontend - Cursor",
        "README.md - Code",
        "models.py - Visual Studio Code",
    ]
    for title in safe_titles:
        assert is_sensitive_editor_title(title) is False, f"Expected {title} to be allowed"

    # Test SelectiveTypingWatcher buffer purge
    captured = []
    watcher = SelectiveTypingWatcher(callback=lambda ev: captured.append(ev))

    # Simulate active sensitive window in Cursor
    with patch("desktop_agent.typing_tracker.get_active_window_info") as mock_win:
        mock_win.return_value = {
            "app_name": "Cursor",
            "process_name": "cursor.exe",
            "title": ".env - MemoryOS - Cursor"
        }
        # Simulate typing
        key = MagicMock()
        key.char = "P"
        watcher._on_press(key)

        assert watcher.accumulated_text == "", "Typing buffer must be purged on sensitive file"
        assert len(captured) == 0


# ==============================================================================
# 5. Ollama model names configurable without code changes
# ==============================================================================

def test_ollama_model_names_configurable(monkeypatch):
    """Verify chat and embedding models can be switched via environment variables."""
    monkeypatch.setenv("MEMORYOS_CHAT_MODEL", "llama3.1")
    monkeypatch.setenv("MEMORYOS_EMBEDDING_MODEL", "bge-m3")

    import importlib
    import backend.config as cfg
    importlib.reload(cfg)

    assert cfg.OLLAMA_CHAT_MODEL == "llama3.1"
    assert cfg.OLLAMA_EMBEDDING_MODEL == "bge-m3"

    # Reset back to default
    monkeypatch.delenv("MEMORYOS_CHAT_MODEL", raising=False)
    monkeypatch.delenv("MEMORYOS_EMBEDDING_MODEL", raising=False)
    importlib.reload(cfg)


# ==============================================================================
# 6. Neural cross-encoder flag, fallback, and /api/status reporting
# ==============================================================================

def test_reranker_fallback_and_neural_toggle(monkeypatch):
    """Verify neural cross-encoder config toggle and fallback mechanism."""
    reset_reranker()

    # 1. Default: Lexical fallback
    monkeypatch.setattr("backend.config.USE_NEURAL_RERANKER", False)
    reset_reranker()
    r_default = get_reranker()
    assert isinstance(r_default, LexicalSemanticReranker)
    info_default = get_active_reranker_info()
    assert info_default["active_type"] == "lexical_semantic_fallback"

    # 2. Neural enabled with mock cross encoder to prevent network weight download in tests
    mock_encoder_instance = MagicMock()
    mock_encoder_instance.rerank.return_value = [0.95, 0.12]
    monkeypatch.setattr("fastembed.rerank.cross_encoder.TextCrossEncoder", lambda model_name: mock_encoder_instance)

    monkeypatch.setattr("backend.config.USE_NEURAL_RERANKER", True)
    reset_reranker()
    r_neural = get_reranker()
    assert isinstance(r_neural, NeuralCrossEncoderReranker)
    info_neural = get_active_reranker_info()
    assert info_neural["neural_enabled"] is True
    assert info_neural["active_type"] == "neural_cross_encoder"

    # 3. Test reranking candidates
    candidates = [
        {"id": 1, "title": "Vector Databases in Python", "text": "LanceDB provides fast local vector search with Apache Arrow.", "score": 0.8},
        {"id": 2, "title": "Cooking Recipes", "text": "How to make homemade sourdough bread with flour and water.", "score": 0.3},
    ]

    ranked = r_neural.rerank("vector database search", candidates, top_n=2)
    assert len(ranked) == 2
    assert ranked[0]["id"] == 1
    assert ranked[0]["rerank_score"] == 0.95

    # Reset
    reset_reranker()


def run_sync(coro):
    """Synchronously advance a non-blocking coroutine."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise RuntimeError("Coroutine did not finish synchronously")


def test_api_status_reports_models_and_reranker():
    """Verify /api/status reports active chat_model, embedding_model, and reranker."""
    from unittest.mock import AsyncMock
    from backend.main import get_status
    with patch("backend.main.check_ollama_status", new_callable=AsyncMock) as mock_ollama:
        mock_ollama.return_value = "offline"
        status_res = run_sync(get_status(None))
        assert status_res.status == "active"
        assert status_res.chat_model == OLLAMA_CHAT_MODEL
        assert status_res.embedding_model == OLLAMA_EMBEDDING_MODEL
        assert status_res.reranker is not None
        assert "active_type" in status_res.reranker
        assert "neural_enabled" in status_res.reranker
