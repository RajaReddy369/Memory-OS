"""
Pytest configuration for MemoryOS test suite.
Configures test environment variables.
"""

import os

# Use embedded SQLite dense vector store during unit tests in isolated sandbox
os.environ["MEMORYOS_USE_SQLITE_VECTORS"] = "1"

