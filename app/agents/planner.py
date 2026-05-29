# app/agents/planner.py
"""
LMIM Project Architect (AppImage Safe).
Generates build manifests with forensic logging.
"""
import json, logging, re, os, sys
from pathlib import Path
from typing import Dict, Optional, List
import requests
from app.config import LLM_API_URL, MODEL_NAME, PLANNER_API_TIMEOUT

logger = logging.getLogger(__name__)

# 🔥 CRITICAL FIX: Dynamic Path Helpers
def get_writable_data_dir():
    env_path = os.getenv('LMIM_DATA_DIR')
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parent.parent.parent / "data"

def get_bundle_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent

DATA_DIR = get_writable_data_dir()
BUNDLE_DIR = get_bundle_dir()

# Prompt original
PLANNER_PROMPT = """You are the LMIM Project Architect. Output STRICT JSON only.
USER REQUEST: "{user_prompt}"

CRITICAL INSTRUCTION:
1. If the user asks to "read", "improve", "fix", or "modify" an EXISTING file, you MUST list that file in `dependencies`.
2. You MUST list the output filename in `build_order`. **NEVER set build_order to null or empty.**
3. All filenames in `files` and `build_order` must be RELATIVE to workspace root (e.g., "main.py", NOT "workspace/main.py").

OUTPUT FORMAT (NO MARKDOWN, NO EXPLANATIONS):
{{
  "project_name": "snake_case_name",
  "description": "One line summary",
  "language": "python",
  "dependencies": ["path/to/source_file.py"], 
  "files": [
    {{"name": "output_filename.py", "type": "python", "role": "main", "instructions": "Specific instructions here"}}
  ],
  "build_order": ["output_filename.py"],
  "test_command": "python3 output_filename.py"
}}
BEGIN JSON:
"""

def parse_manifest(raw: str) -> Optional[Dict]:
    """Parser con logging forense paso a paso."""
    logger.info("🔍 [PARSE] Starting manifest parsing...")
    if not raw:
        logger.error("[PARSE] Input is empty.")
        return None
        
    clean = raw.strip()
    clean = re.sub(r'```json\s*', '', clean, flags=re.I)
    clean = re.sub(r'```\s*', '', clean)
    
    match = re.search(r'\{.*\}', clean, re.DOTALL)
    if not match:
        logger.error("[PARSE] FAILED: No JSON block found.")
        return None
    
    candidate = match.group()
    try:
        data = json.loads(candidate)
        logger.info("[PARSE] SUCCESS: Parsed directly.")
        return data
    except json.JSONDecodeError as e:
        logger.warning(f"[PARSE] Direct load failed: {e}. Attempting repairs...")
        fixed = re.sub(r',\s*([}\]])', r'\1', candidate)
        try:
            data = json.loads(fixed)
            logger.info("[PARSE] SUCCESS: Parsed after fixing commas.")
            return data
        except json.JSONDecodeError as e2:
            aggressive = fixed
            aggressive = re.sub(r"'([^']*)'", r'"\1"', aggressive)
            aggressive = re.sub(r'(?<![{\[,"\'])([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'"\1":', aggressive)
            try:
                data = json.loads(aggressive)
                logger.info("[PARSE] SUCCESS: Parsed after aggressive repairs.")
                return data
            except json.JSONDecodeError as e3:
                logger.error(f"[PARSE] ALL STRATEGIES FAILED: {e3}")
                return None

async def plan_project(user_prompt: str, user_id: str, workspace_root: str = "workspace") -> Optional[Dict]:
    logger.info(f"🧠 Planning: {user_prompt[:50]}...")
    model = os.getenv("PLANNER_MODEL_NAME", MODEL_NAME)
    
    # 🔥 CRITICAL: Use Writable Data Dir for Workspace
    ws_path = DATA_DIR / workspace_root
    manifest_path = ws_path / "manifest.json"
    
    logger.info(f"📂 Target Workspace: {ws_path}")
    
    final_prompt = PLANNER_PROMPT.format(user_prompt=user_prompt)
    
    try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": final_prompt}],
            "temperature": 0.2,
            "max_tokens": 10048,
            "stream": False
        }
        
        resp = requests.post(
            LLM_API_URL, # Uses global from config
            json=payload,
            timeout=500
        )
        
        if resp.status_code != 200:
            logger.error(f"❌ HTTP Error {resp.status_code}: {resp.text}")
            return None
            
        resp_json = resp.json()
        choices = resp_json.get("choices", [])
        if not choices:
            return None
            
        raw = choices[0].get("message", {}).get("content", "")
        manifest = parse_manifest(raw)
        
        if manifest:
            if "dependencies" not in manifest:
                manifest["dependencies"] = []
            
            if not manifest.get("build_order"):
                if manifest.get("files") and len(manifest["files"]) > 0:
                    manifest["build_order"] = [manifest["files"][0]["name"]]
                else:
                    return None

            # Sanitization
            for f in manifest.get("files", []):
                if f["name"].startswith("workspace/"):
                    f["name"] = f["name"][len("workspace/"):]
            
            manifest["build_order"] = [
                f[len("workspace/"):] if f.startswith("workspace/") else f 
                for f in manifest.get("build_order", [])
            ]

            # Write to Writable Dir
            try:
                ws_path.mkdir(exist_ok=True)
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2)
                logger.info(f"✅ Manifest saved to: {manifest_path}")
            except Exception as write_err:
                logger.error(f"❌ FAILED TO WRITE MANIFEST: {write_err}")
            
            return manifest
        else:
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"💥 Network Error: {e}")
        return None
    except Exception as e:
        logger.error(f"💥 Unexpected Error: {e}", exc_info=True)
        return None
