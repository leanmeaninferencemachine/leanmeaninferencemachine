#!/usr/bin/env python3
import json
import logging
# === 🔥 APPIMAGE COMPATIBILITY: FORCE WRITABLE PATHS ===
import os
import sys  # ← MUST BE HERE for getattr(sys, 'frozen')
from pathlib import Path
from dotenv import load_dotenv

def get_base_dir():
    """Determines the base directory. Inside AppImage, this is the mount point."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    else:
        return Path(__file__).resolve().parent.parent

def get_writable_data_dir():
    """Determines where to write logs/data. Must be writable (Home Dir for AppImage)."""
    env_path = os.getenv('LMIM_DATA_DIR')
    if env_path:
        return Path(env_path)
    if getattr(sys, 'frozen', False):
        return Path.home() / ".lmim_os"
    else:
        return get_base_dir() / "data"

# Define Global Paths Immediately
BASE_DIR = get_base_dir()
DATA_DIR = get_writable_data_dir()
CONFIG_DIR = DATA_DIR / "config"
MEMORIES_DIR = DATA_DIR / "memories"
LOGS_DIR = DATA_DIR / "logs"
AGENDAS_DIR = DATA_DIR / "agendas"
DB_DIR = DATA_DIR / "db"

# Ensure directories exist
for d in [DATA_DIR, CONFIG_DIR, MEMORIES_DIR, LOGS_DIR, AGENDAS_DIR, DB_DIR]:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"⚠️ Warning: Could not create {d}: {e}")

# ==============================================================================
# 🔐 Load .env from Writable Location FIRST (with override)
# ==============================================================================
writable_env = DATA_DIR / ".env"
if writable_env.exists():
    load_dotenv(writable_env, override=True)
else:
    if getattr(sys, 'frozen', False):
        bundle_env = Path(sys._MEIPASS) / ".env"
    else:
        bundle_env = Path(__file__).resolve().parent.parent / ".env"

    if bundle_env.exists():
        load_dotenv(bundle_env, override=True)
        try:
            writable_env.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy(bundle_env, writable_env)
        except Exception as e:
            print(f"⚠️ Could not copy .env to user dir: {e}")

# ==============================================================================
# 🔍 Debug Logging (AFTER .env is loaded)
# ==============================================================================
logger = logging.getLogger(__name__)
logger.info(f"🔍 [CONFIG] LMIM_DATA_DIR={os.getenv('LMIM_DATA_DIR')}")
logger.info(f"🔍 [CONFIG] MODEL_PATH from env: '{os.getenv('MODEL_PATH')}'")
logger.info(f"🔍 [CONFIG] MODEL_NAME from env: '{os.getenv('MODEL_NAME')}'")

model_filename = os.getenv("MODEL_PATH", "")
if model_filename:
    user_model = DATA_DIR / "models" / model_filename
    if getattr(sys, 'frozen', False):
        bundle_root = Path(sys._MEIPASS)
    else:
        bundle_root = Path(__file__).resolve().parent.parent
    bundle_model = bundle_root / "models" / model_filename
    logger.info(f"🔍 [CONFIG] User model: {user_model} (exists: {user_model.exists()})")
    logger.info(f"🔍 [CONFIG] Bundle model: {bundle_model} (exists: {bundle_model.exists()})")

# --- Model Settings ---
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen_Qwen3.5-2B.gguf")
PLANNER_MODEL_NAME = os.getenv("PLANNER_MODEL_NAME", MODEL_NAME)
CHAT_MODEL_NAME = os.getenv("CHAT_MODEL_NAME", MODEL_NAME)
LLM_API_URL = os.getenv("LLM_API_URL", "http://localhost:8080/v1/chat/completions")
LOCAL_INFERENCE_URL = LLM_API_URL
DEFAULT_SYSTEM_USER = os.getenv("DEFAULT_SYSTEM_USER", "admin_user")

# --- Timeouts ---
PLANNER_API_TIMEOUT = int(os.getenv("PLANNER_API_TIMEOUT", "600"))
CHAT_API_TIMEOUT = int(os.getenv("CHAT_API_TIMEOUT", "600"))
BUILDER_API_TIMEOUT = int(os.getenv("BUILDER_API_TIMEOUT", "900"))
BUILDER_CMD_TIMEOUT = int(os.getenv("BUILDER_CMD_TIMEOUT", "600"))
WRAPPER_POLL_INTERVAL = int(os.getenv("WRAPPER_POLL_INTERVAL", "10"))
WRAPPER_MAX_POLL_ATTEMPTS = int(os.getenv("WRAPPER_MAX_POLL_ATTEMPTS", "600"))

# --- Memory Settings ---
MEMORY_DIR = str(MEMORIES_DIR)
MAX_MEMORIES_PER_USER = int(os.getenv("MAX_MEMORIES_PER_USER", "50"))
MEMORY_RETRIEVAL_TOP_K = int(os.getenv("MEMORY_RETRIEVAL_TOP_K", "3"))
PERSISTENT_MEMORY_ENABLED = os.getenv("PERSISTENT_MEMORY_ENABLED", "true").lower() == "true"

def estimate_tokens(text: str) -> int:
    return len(text) // 4 + len(text) // 10

# --- Tool Calling ---
ENABLE_TOOL_CALLING = os.getenv("ENABLE_TOOL_CALLING", "true").lower() == "true"
TOOL_CALL_MARKER_START = os.getenv("TOOL_CALL_MARKER_START", "[TOOL_CALL]")
TOOL_CALL_MARKER_END = os.getenv("TOOL_CALL_MARKER_END", "[/TOOL_CALL]")

# --- RAG ---
ENABLE_RAG = os.getenv("ENABLE_RAG", "false").lower() == "true"
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

# ── Language & Prime Directive ─────────────────────────────────────────
PRIME_DIRECTIVE = os.getenv("PRIME_DIRECTIVE", "")
LANGUAGE = os.getenv("LANGUAGE", "en").lower().strip()

# --- Audit Logging ---
ENABLE_AUDIT_LOGGING = os.getenv("ENABLE_AUDIT_LOGGING", "true").lower() == "true"
LOG_DIR = str(LOGS_DIR)
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", "5242880"))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "3"))

# --- Security ---
ADMIN_USER_IDS = os.getenv("ADMIN_USER_IDS", "wa_+1234567890,usr_admin_uuid").split(",")

# --- Summary ---
SUMMARY_INTERVAL = int(os.getenv("SUMMARY_INTERVAL", "20"))
SUMMARY_MAX_HISTORY_TURNS = int(os.getenv("SUMMARY_MAX_HISTORY_TURNS", "5"))
SUMMARY_PROMPT_TEMPLATE = os.getenv("SUMMARY_PROMPT_TEMPLATE", "default")

# --- Identity Loaders ---
def get_system_identity() -> str:
    path = CONFIG_DIR / "system_identity.md"
    if not path.exists():
        path = Path(__file__).resolve().parent.parent / "config" / "system_identity.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "You are LMIM AI. Follow tool rules strictly."

def get_user_identity() -> dict:
    path = CONFIG_DIR / "user_identity.json"
    if not path.exists():
        path = Path(__file__).resolve().parent.parent / "config" / "user_identity.json"
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading user identity: {e}")
    return {
        "owner": {"name": "User", "role": "Operator"},
        "ai_profile": {
            "name": "LMIM Assistant",
            "tone": "helpful",
            "signature": "",
            "rules": []
        }
    }

def get_agent_display_name() -> str:
    identity = get_user_identity()
    return identity.get("ai_profile", {}).get("name", "Assistant")


# ==============================================================================
# 🧠 DEFAULT_CONTEXT  — Tightened for small local models (~900 tokens vs ~1700)
#
# Key changes vs previous version:
#  1. Tool reference collapsed to one-line-per-tool with EXACT param contracts
#  2. time_range for check_availability explicitly documented as "HH:MM-HH:MM"
#     (root cause of the scheduling_tools.py IndexError in prod logs)
#  3. Removed redundant prose; kept only few-shot examples model needs
#  4. Scheduling workflow condensed — model was ignoring it anyway due to length
# ==============================================================================
DEFAULT_CONTEXT = """
## IDENTITY
You are LMIM, an autonomous AI assistant. Be concise. Execute tasks fully.

## TOOL CALL FORMAT — EXACT SYNTAX REQUIRED
Output ONLY this — nothing before or after:
[TOOL_CALL]{"name":"TOOL_NAME","parameters":{...}}[/TOOL_CALL]

CRITICAL RULES:
- ONE tool call per response. STOP immediately after [/TOOL_CALL]. 
- Do NOT write [Tool result: ...] yourself. NEVER fake a result.
- Do NOT write confirmation text. Wait for the real system result.
- If you write anything after [/TOOL_CALL], it will be IGNORED.
- NEVER claim a booking succeeded without seeing "✅ SUCCESS" from the system.

## TOOLS (name → required params | optional params)
store_memory      → key:str, value:str | scope:"user"(default)/"global"
recall_memory     → query:str | scope:"user"(default)/"global"
web_search        → query:str | num_results:int(default 5)
send_email        → to:str, subject:str, body:str
send_whatsapp     → phone:str(+country code), message:str  [ADMIN ONLY]
send_telegram     → chat_id:str, message:str
check_availability→ date:YYYY-MM-DD, tenant_id:str | time_range:HH:MM-HH:MM(default "09:00-18:00")
schedule_meeting  → date:YYYY-MM-DD, time:HH:MM, user_name:str, user_phone:str(+country), meeting_type:str, tenant_id:str | notes:str
read_file         → path:str
write_file        → path:str, content:str
list_files        → directory:str(default ".")
run_command       → cmd:str | timeout:int(default 200)
search_files       → pattern:str, file_pattern:str(default "*"), use_regex:bool(default false), case_sensitive:bool(default false), max_results:int(default 50)

## SCHEDULING WORKFLOW
1. If any of date/time/name/phone/type is missing → ask first.
2. Call check_availability → confirm slot with user → call schedule_meeting.
3. Exception: if user provides ALL details in one message → skip to schedule_meeting directly.

## MEMORY SCOPES
scope="user": facts about this user (default)
scope="global": model self-insights (rare)

## EXAMPLES

User: "Remember I prefer short examples"
You: [TOOL_CALL]{"name":"store_memory","parameters":{"key":"example_style","value":"short","scope":"user"}}[/TOOL_CALL]
[Tool result: ✓ Stored]
You: "Got it — keeping examples concise."

User: "What do you know about my preferences?"
You: [TOOL_CALL]{"name":"recall_memory","parameters":{"query":"preferences","scope":"user"}}[/TOOL_CALL]
[Tool result: example_style: short]
You: "You prefer short examples."

User: "Check availability for tomorrow afternoon"
You: [TOOL_CALL]{"name":"check_availability","parameters":{"date":"2026-03-29","tenant_id":"hexa","time_range":"12:00-18:00"}}[/TOOL_CALL]
[Tool result: Available: 13:00, 14:00, 15:00, 16:00]
You: "Open slots tomorrow afternoon: 1pm, 2pm, 3pm, 4pm. Which works?"

User: "Schedule Pedro tomorrow at 3pm, phone +5215551234"
You: [TOOL_CALL]{"name":"check_availability","parameters":{"date":"2026-03-29","tenant_id":"hexa","time_range":"15:00-16:00"}}[/TOOL_CALL]
[Tool result: Available: 15:00]
You: [TOOL_CALL]{"name":"schedule_meeting","parameters":{"date":"2026-03-29","time":"15:00","user_name":"Pedro","user_phone":"+5215551234","meeting_type":"class","tenant_id":"hexa"}}[/TOOL_CALL]
[Tool result: ✓ Booked + WhatsApp sent]
You: "✅ Booked Pedro for Mar 29 at 3pm. Confirmation sent to +5215551234."
""".strip()

# Context management
MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "8"))
CONTEXT_WINDOW_TOKENS = int(os.getenv("CONTEXT_WINDOW_TOKENS", "20000"))
RESPONSE_RESERVED_TOKENS = int(os.getenv("RESPONSE_RESERVED_TOKENS", "4000"))
SYSTEM_RESERVED_TOKENS = len(DEFAULT_CONTEXT) // 4

# ==============================================================================
# 🛠️ AVAILABLE_TOOLS  — Compact format; descriptions trimmed for token budget.
# The full parameter contracts live in DEFAULT_CONTEXT above (single source of
# truth for the model). This list is used programmatically by model_interface.py
# to validate/dispatch tool calls — keep in sync with DEFAULT_CONTEXT.
# ==============================================================================
AVAILABLE_TOOLS = [
    {
        "name": "scrape_website",
        "description": "Extract text content from a web page. Respects robots.txt.",
        "parameters": {
            "url": "the website URL to scrape",
            "extract_text_only": "optional, default True (returns just the text)"
        }
    },
    {
        "name": "search_files",
        "description": "Search for text inside files within the workspace. Supports plain text or regex.",
        "parameters": {
            "pattern": "text or regex to search for",
            "file_pattern": "optional glob filter (e.g., '*.py')",
            "use_regex": "optional boolean, default false",
            "case_sensitive": "optional boolean, default false",
            "max_results": "optional integer, default 50"
        }
    },
    {
        "name": "store_memory",
        "description": "Save a fact or preference for future recall.",
        "parameters": {
            "key": "short identifier (e.g. 'learning_goal')",
            "value": "information to store",
            "scope": "optional: 'user' (default) or 'global'",
            "tags": "optional: comma-separated keywords"
        }
    },
    {
        "name": "recall_memory",
        "description": "Retrieve previously stored information.",
        "parameters": {
            "query": "keywords or question to search",
            "scope": "optional: 'user' (default) or 'global'"
        }
    },
    {
        "name": "web_search",
        "description": "Search the web for real-time information.",
        "parameters": {
            "query": "search query string",
            "num_results": "optional: number of results (default 5)"
        }
    },
    {
        "name": "send_email",
        "description": "Send an email via SMTP.",
        "parameters": {
            "to": "recipient email address",
            "subject": "subject line",
            "body": "email body text"
        }
    },
    {
        "name": "send_telegram",
        "description": "Send a Telegram message.",
        "parameters": {
            "chat_id": "Telegram Chat ID or @username",
            "message": "message text"
        }
    },
    {
        "name": "send_whatsapp",
        "description": "Send a WhatsApp message. ADMIN ONLY.",
        "parameters": {
            "phone": "phone number with country code",
            "message": "message text"
        }
    },
    {
        "name": "check_availability",
        "description": "Check free time slots for a date. time_range MUST be 'HH:MM-HH:MM' format (e.g. '09:00-17:00').",
        "parameters": {
            "date": "YYYY-MM-DD",
            "tenant_id": "tenant ID (e.g. 'hexa')",
            "time_range": "optional: 'HH:MM-HH:MM' (default '09:00-18:00')"
        }
    },
    {
        "name": "schedule_meeting",
        "description": "Book a meeting and send WhatsApp confirmation.",
        "parameters": {
            "date": "YYYY-MM-DD",
            "time": "HH:MM",
            "user_name": "name of the person",
            "user_phone": "phone with country code (e.g. +52...)",
            "meeting_type": "'class', 'meeting', 'task', or 'assessment'",
            "tenant_id": "tenant ID (e.g. 'hexa')",
            "notes": "optional notes"
        }
    },
    {
        "name": "read_file",
        "description": "Read a file's content.",
        "parameters": {
            "path": "relative file path"
        }
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file.",
        "parameters": {
            "path": "relative file path",
            "content": "full text content"
        }
    },
    {
        "name": "list_files",
        "description": "List files in a directory.",
        "parameters": {
            "directory": "relative directory path (default '.')"
        }
    },
    {
        "name": "run_command",
        "description": "Execute a safe shell command.",
        "parameters": {
            "cmd": "command string",
            "timeout": "optional: seconds before timeout (default 200)"
        }
    },
]

# ==============================================================================
# 🔧 INSPECTOR / BUILDER PROMPTS (unchanged)
# ==============================================================================
INSPECTOR_PROMPT = """
You are a Senior Code Debugger. Your job is to ANALYZE errors and provide a SURGICAL PATCH.
Do NOT rewrite the whole file. Only fix the specific broken lines.

INPUT:
- File: {file_path}
- Content:
{file_content}
- Error Log:
{error_log}

TASK:
Analyze the error and output a STRICT JSON object to apply a minimal fix.
{{
  "problem": "Short description of the root cause",
  "line_start": <number>,
  "line_end": <number>,
  "replacement_code": "The exact corrected code lines to insert"
}}

RULES:
- Output ONLY raw JSON. No markdown. No explanations.
- `line_start` and `line_end` must accurately cover the broken code block.
- If you need to INSERT lines (not replace), set `line_end` = `line_start` - 1.
- `replacement_code` should include proper indentation.
""".strip()

BUILDER_CODE_GEN_PROMPT = """
You are an expert {language} code generator.
{spec}

🚫 CRITICAL CONSTRAINTS:
- YOU ARE IN BUILD MODE. DO NOT CALL TOOLS. DO NOT SAVE MEMORY.
- Output ONLY raw {language} code. NO markdown, NO explanations.
- If the task includes "SOURCE FILE" context, analyze it carefully and apply the requested improvements/refactors to generate the NEW file.
- Assume ONLY Python Standard Library is available unless specified.
- If a library is missing, USE STDLIB FALLBACK.

BEGIN CODE NOW:
""".strip()

BUILDER_CODE_FIX_PROMPT = """
🚨 CRITICAL FIX MODE: Repair broken code.
YOU FAILED PREVIOUSLY.

❌ ERROR REPORT:
{error}

🚫 STRICT RULES:
- DO NOT call tools. DO NOT save memory. DO NOT output JSON.
- Output ONLY raw {language} code.
- If error contains 'INSPECTOR DIAGNOSIS', FOLLOW THAT STRATEGY EXACTLY.
- If error is 'ModuleNotFoundError': SWITCH TO STDLIB immediately.
- If error is 'SyntaxError': Fix the specific line cited.

📋 PREVIOUS BROKEN CODE:
{previous_code}

CORRECTED CODE (raw {language} only):
""".strip()
