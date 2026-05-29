# app/tools/shell_tools.py
import subprocess
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

# 🔥 CRITICAL: Dynamic Working Directory
def get_writable_workspace() -> Path:
    env_path = os.getenv('LMIM_DATA_DIR')
    if env_path:
        ws = Path(env_path) / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        return ws
    if getattr(sys, 'frozen', False):
        ws = Path.home() / ".lmim_os" / "workspace"
    else:
        ws = Path(__file__).resolve().parent.parent.parent / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws

WORKSPACE_ROOT = get_writable_workspace()

ALLOWED_PREFIXES = ["python3 ", "python -m ", "pip install ", "cat ", "ls ", "grep ", "pytest ", "echo ", "mkdir ", "rm ", "cp ", "mv "]

# app/tools/shell_tools.py (updated section)
from app.workspace import get_workspace  # add at top

def run_command(cmd: str, timeout: int = 30) -> Dict[str, Any]:
    if not any(cmd.startswith(p) for p in ALLOWED_PREFIXES):
        return {"success": False, "error": f"Command blocked: {cmd[:20]}..."}
    
    dangerous = ["rm -rf /", "sudo", "chmod 777", "wget", "curl"]
    if any(d in cmd for d in dangerous):
        return {"success": False, "error": "Dangerous command pattern detected."}

    # Determine working directory: active workspace or fallback
    ws = get_workspace()
    if ws:
        cwd = ws
    else:
        # Fallback to the writable workspace debug folder
        cwd = str(get_writable_workspace())

    try:
        logger.info(f"⚙️ Executing: {cmd} (CWD: {cwd})")
        result = subprocess.run(
            cmd, 
            shell=True, 
            capture_output=True, 
            text=True, 
            timeout=timeout,
            cwd=cwd
        )
        return {"success": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip(), "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}
