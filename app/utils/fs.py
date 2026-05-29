"""
app/utils/fs.py
Global Filesystem Helper for AppImage Compatibility.
"""
import os
import sys
from pathlib import Path

def get_writable_data_dir():
    """
    Returns the writable data directory.
    1. Checks LMIM_DATA_DIR env var (set by run_app.py for AppImage).
    2. Falls back to local project root for development.
    """
    # Priority 1: Environment Variable (Set by run_app.py in AppImage)
    env_path = os.getenv('LMIM_DATA_DIR')
    if env_path:
        return Path(env_path)
    
    # Priority 2: Smart Fallback for Development
    # Walk up from this file until we find a 'data' folder or hit root
    current = Path(__file__).resolve()
    while current != current.parent:
        if (current / "data").exists():
            return current / "data"
        current = current.parent
    
    # Ultimate Fallback: User Home
    return Path.home() / ".lmim_os"

# Initialize Global Paths Immediately
DATA_DIR = get_writable_data_dir()
LOG_DIR = DATA_DIR / "logs"
MEMORIES_DIR = DATA_DIR / "memories"
SESSIONS_DIR = DATA_DIR / "sessions"
WORKSPACE_DIR = DATA_DIR / "workspace"  # Critical for Builder
DB_DIR = DATA_DIR / "db"

# Ensure ALL directories exist immediately
for d in [DATA_DIR, LOG_DIR, MEMORIES_DIR, SESSIONS_DIR, WORKSPACE_DIR, DB_DIR]:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"⚠️ Warning: Could not create {d}: {e}")

# Export these so other files can just say: from app.utils.fs import DATA_DIR
__all__ = ["DATA_DIR", "LOG_DIR", "MEMORIES_DIR", "SESSIONS_DIR", "WORKSPACE_DIR", "DB_DIR"]
