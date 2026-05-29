# app/workspace.py
import os
import pathlib
from pathlib import Path

_workspace_root: str | None = None

def set_workspace(path: str) -> dict:
    """Set the workspace root directory. Returns a dict with 'workspace' or 'error'."""
    resolved = pathlib.Path(path).expanduser().resolve()
    if not resolved.is_dir():
        return {"error": f"Not a directory: {path}"}
    global _workspace_root
    _workspace_root = str(resolved)
    return {"workspace": _workspace_root}

def get_workspace() -> str | None:
    """Return current workspace root, or None if not set."""
    return _workspace_root

def clear_workspace() -> None:
    global _workspace_root
    _workspace_root = None

def safe_path(relative: str) -> str:
    """
    Resolve a relative path inside the workspace.
    Raises ValueError if no workspace set, or PermissionError if the path escapes.
    """
    if _workspace_root is None:
        raise ValueError("No workspace set. Call set_workspace first.")
    full = Path(_workspace_root, relative).resolve()
    if not str(full).startswith(_workspace_root):
        raise PermissionError(f"Path escape attempted: {relative}")
    return str(full)
