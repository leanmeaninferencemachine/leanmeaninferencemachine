# app/tools/file_tools.py (modified)
import os
import logging
import shutil
import sys
from pathlib import Path
from datetime import datetime

from app.workspace import get_workspace, safe_path

logger = logging.getLogger(__name__)

def get_bundle_dir() -> Path:
    """Returns the read-only bundle root (sys._MEIPASS) or project root."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent

BUNDLE_ROOT = get_bundle_dir()
ALLOWED_READ_DIRS = [BUNDLE_ROOT, BUNDLE_ROOT / "app", BUNDLE_ROOT / "scripts"]

def _is_safe_read_path(path_str: str) -> bool:
    """Allow reading from bundle directories (read‑only assets)."""
    if not path_str:
        return False
    try:
        target = (BUNDLE_ROOT / path_str).resolve() if not os.path.isabs(path_str) else Path(path_str).resolve()
        target_str = str(target)
        return any(str(d.resolve()) in target_str for d in ALLOWED_READ_DIRS)
    except Exception:
        return False

def _create_backup(file_path: Path) -> str:
    if not file_path.exists():
        return ""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{file_path.name}.bak.auto_{timestamp}"
    backup_path = file_path.parent / backup_name
    try:
        shutil.copy2(file_path, backup_path)
        logger.info(f"💾 Backup created: {backup_name}")
        return str(backup_path)
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return ""

def read_file(path: str = None, **kwargs) -> dict:
    """Read a file. Workspace paths are resolved via safe_path; non‑workspace paths must be in bundle."""
    actual_path = path or kwargs.get('file_path') or kwargs.get('file')
    if not actual_path:
        return {"success": False, "error": "No path provided."}

    # If a workspace is active, try to read from workspace first
    ws = get_workspace()
    if ws:
        try:
            target = Path(safe_path(actual_path))
            if target.exists() and target.is_file():
                with open(target, 'r', encoding='utf-8') as f:
                    content = f.read()
                logger.info(f"📖 Read workspace file: {actual_path}")
                return {"success": True, "content": content, "lines": len(content.splitlines())}
        except (ValueError, PermissionError) as e:
            # Not a valid workspace path – fall through to bundle read
            logger.debug(f"Workspace read failed for {actual_path}: {e}")

    # Fallback: read from bundle (read‑only assets)
    if not _is_safe_read_path(actual_path):
        return {"success": False, "error": f"Access denied: {actual_path}"}
    target = BUNDLE_ROOT / actual_path
    if not target.exists():
        return {"success": False, "error": f"File not found: {actual_path}"}
    if target.is_dir():
        return {"success": False, "error": f"Path is a directory: {actual_path}"}
    try:
        with open(target, 'r', encoding='utf-8') as f:
            content = f.read()
        logger.info(f"📖 Read bundle file: {actual_path}")
        return {"success": True, "content": content, "lines": len(content.splitlines())}
    except Exception as e:
        return {"success": False, "error": str(e)}

def write_file(path: str = None, content: str = "", **kwargs) -> dict:
    """Write a file. If workspace is set, the path must be inside it. Otherwise, writes to workspace/debug."""
    actual_path = path or kwargs.get('file_path') or kwargs.get('file')
    final_content = content or kwargs.get('content', "")
    if not actual_path:
        return {"success": False, "error": "No path provided."}
    if not final_content:
        return {"success": False, "error": "No content provided."}

    ws = get_workspace()
    if ws:
        try:
            target = Path(safe_path(actual_path))
        except (ValueError, PermissionError) as e:
            return {"success": False, "error": str(e)}
    else:
        # No workspace – fallback to ~/.lmim_os/workspace/debug
        data_dir = Path(os.getenv('LMIM_DATA_DIR', Path.home() / '.lmim_os'))
        target = data_dir / "workspace" / "debug" / actual_path
        target = target.resolve()

    backup_path = ""
    if target.exists():
        backup_path = _create_backup(target)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, 'w', encoding='utf-8') as f:
            f.write(final_content)
        logger.info(f"✍️ Wrote file: {target}")
        return {"success": True, "path": str(target), "backup": backup_path}
    except Exception as e:
        return {"success": False, "error": str(e)}

def list_files(directory: str = ".", **kwargs) -> dict:
    """List files in a directory. Workspace‑aware."""
    ws = get_workspace()
    if ws:
        try:
            target_dir = Path(safe_path(directory))
        except (ValueError, PermissionError) as e:
            return {"success": False, "error": str(e)}
    else:
        # No workspace – list from bundle fallback (for compatibility)
        if not _is_safe_read_path(directory):
            return {"success": False, "error": f"Access denied: {directory}"}
        target_dir = BUNDLE_ROOT / directory

    if not target_dir.is_dir():
        return {"success": False, "error": f"Not a directory: {directory}"}
    try:
        files = []
        for item in target_dir.iterdir():
            if item.name.startswith('.'):
                continue
            files.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else 0
            })
        return {"success": True, "files": files, "count": len(files)}
    except Exception as e:
        return {"success": False, "error": str(e)}
