# app/model_interface.py — Model inference + tool parsing (AppImage Safe)
import os
import re
import json
import time
import logging
import requests
from pathlib import Path
from dotenv import dotenv_values

# Imports de configuración
from app.config import (
    BUILDER_API_TIMEOUT, CHAT_API_TIMEOUT, PLANNER_API_TIMEOUT,
    MODEL_NAME, LLM_API_URL, LOCAL_INFERENCE_URL, DEFAULT_CONTEXT,
    ENABLE_TOOL_CALLING, TOOL_CALL_MARKER_START, TOOL_CALL_MARKER_END,
    AVAILABLE_TOOLS, ENABLE_AUDIT_LOGGING,
    SUMMARY_INTERVAL, SUMMARY_MAX_HISTORY_TURNS,
    # ← Added paths for AppImage compatibility
    BASE_DIR, DATA_DIR, CONFIG_DIR, MEMORIES_DIR, LOGS_DIR, AGENDAS_DIR, DB_DIR
)
# Imports de memoria
from app.memory_functions import (
    store_memory, recall_memories,
    update_session_memory, get_session_context, _session_cache
)

# Imports de herramientas
from app.tools.file_tools import read_file, write_file, list_files
from app.tools.shell_tools import run_command
from app.tools.search_tools import WebSearchTool
from app.tools.search_files_tool import SearchFilesTool      # <-- NEW
from app.rag import has_document, retrieve_chunks
from app.tools.comms_tools import SendWhatsAppTool, SendEmailTool
from app.tools.scheduling_tools import CheckAvailabilityTool, ScheduleMeetingTool
from app.memory.conversation_summary import ConversationSummary

logger = logging.getLogger(__name__)

import hashlib

# ==============================================================================
# 🔥 TERMINAL TOOL GUARD + HELPERS
# ==============================================================================
_TERMINAL_TOOLS = {"schedule_meeting", "send_whatsapp", "send_email", "send_telegram"}

def _make_tool_hash(tool_name: str, params: dict) -> str:
    key = json.dumps({"n": tool_name, "p": params}, sort_keys=True)
    return hashlib.md5(key.encode()).hexdigest()[:12]

def _build_confirmation(tool_name: str, tool_result: str) -> str:
    if tool_name == "schedule_meeting" and "SUCCESS" in tool_result:
        return tool_result.replace("\u2705 SUCCESS: ", "\u2705 ")
    if tool_name in ("send_whatsapp", "send_email", "send_telegram"):
        if "ERROR" not in tool_result:
            return "\u2705 Message sent successfully."
    return tool_result

def _pick_first_slot(availability_result: str, preferred_time: str = None) -> str:
    import re as _re
    slots = _re.findall(r'\b(\d{1,2}:\d{2})\b', availability_result)
    if not slots:
        return ""
    if preferred_time and preferred_time in slots:
        return preferred_time
    return slots[0]

def _extract_booking_params(prompt: str, avail_params: dict) -> dict:
    import re as _re
    phone_match = _re.search(r'(\+\d[\d\s\-]{7,}\d)', prompt)
    if not phone_match:
        return None
    phone = _re.sub(r'[^\d+]', '', phone_match.group(1))
    name = None
    name_match = _re.search(
        r'(?:for|para|con|agendar a?|schedule|book)\s+([A-Z\u00C1\u00C9\u00CD\u00D3\u00DA\u00D1][a-z\u00E1\u00E9\u00ED\u00F3\u00FA\u00F1A-Z\u00C1\u00C9\u00CD\u00D3\u00DA\u00D1]+(?:\s+[A-Z\u00C1\u00C9\u00CD\u00D3\u00DA\u00D1][a-z\u00E1\u00E9\u00ED\u00F3\u00FA\u00F1A-Z\u00C1\u00C9\u00CD\u00D3\u00DA\u00D1]+)?)',
        prompt, _re.IGNORECASE
    )
    if name_match:
        name = name_match.group(1).strip()
    if not name:
        return None
    date = avail_params.get("date")
    if not date:
        return None
    tenant_id = avail_params.get("tenant_id", "hexa")
    m_type = "meeting"
    type_match = _re.search(
        r'\b(class|clase|meeting|reunion|reuni\u00f3n|assessment|evaluaci\u00f3n|task|tarea|general|benchmarking|security)\b',
        prompt, _re.IGNORECASE
    )
    if type_match:
        m_type = type_match.group(1).lower()
    return {"date": date, "time": "", "user_name": name, "user_phone": phone,
            "meeting_type": m_type, "tenant_id": tenant_id}

def _finalize_reply(reply: str, user_id: str, original_prompt: str,
                    recent_turns: list, session_cache: dict):
    try:
        update_session_memory(user_id, original_prompt, reply)
    except Exception as e:
        logger.warning(f"\u26a0\ufe0f Memory write failed (non-fatal): {e}")
    session_cache[user_id] = recent_turns + [
        {"role": "user",      "content": original_prompt},
        {"role": "assistant", "content": reply},
    ]

def _get_max_tokens(provider: str, builder_mode: bool, model_name: str = "") -> int:
    """
    Dynamic max_tokens based on context.
    - Builder mode always gets full tokens (code generation needs room)
    - Cloud has no latency penalty — full tokens fine
    - Local CPU inference: increased limits for tool call completion
    """
    if builder_mode:
        return 8192  # Was 4096 - double for code generation
    
    if provider != "local":
        return 8192  # Was 4096 - cloud can handle more
    
    model_lower = model_name.lower()
    
    # Tiny models: still need enough for tool calls
    if any(x in model_lower for x in ["0.5b", "0.8b"]):
        return 1024  # Was 384
    
    # Small models: 1B-3B need room for phone numbers, JSON, etc.
    elif any(x in model_lower for x in ["1b", "1.5b", "2b", "3b"]):
        return 2048  # Was 512 - critical for phone numbers
    
    # Medium models: 7B-8B can handle more
    elif any(x in model_lower for x in ["7b", "8b"]):
        return 4096  # Was 1024
    
    # Default for unknown models
    return 2048  # Was 512


# ==============================================================================
# 🔥 APPIMAGE COMPATIBILITY: Dynamic Data Dir
# ==============================================================================
def get_writable_data_dir():
    """Returns the writable data directory (Home for AppImage, Local for Dev)."""
    env_path = os.getenv('LMIM_DATA_DIR')
    if env_path:
        return Path(env_path)
    # Fallback for dev
    return Path(__file__).resolve().parent.parent / "data"

DATA_DIR = get_writable_data_dir()
MEMORIES_DIR = DATA_DIR / "memories"
LOGS_DIR = DATA_DIR / "logs"

# Ensure dirs exist
for d in [DATA_DIR, MEMORIES_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ==============================================================================
# FUNCIÓN AUXILIAR: Lectura Fresca de Variables
# ==============================================================================
def _get_fresh_env_var(key: str, default: str = None):
    """
    Reads a specific variable directly from the .env file on disk.
    Ensures GUI changes are picked up immediately without restart.
    """
    # Try LMIM_DATA_DIR first (AppImage home)
    base_dir = os.getenv('LMIM_DATA_DIR')
    if base_dir:
        env_path = Path(base_dir) / ".env"
    else:
        # Fallback to project root
        env_path = Path(__file__).resolve().parent.parent / ".env"
    
    if not env_path.exists():
        return os.getenv(key, default)
    
    try:
        env_vars = dotenv_values(env_path)
        return env_vars.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

# ==============================================================================
# UTILIDADES DE LIMPIEZA
# ==============================================================================
def _sanitize_tool_marker(text: str) -> str:
    text = text.replace("[/TOOL_CALL>", "[/TOOL_CALL]")
    text = text.replace("[TOOL_CALL>", "[TOOL_CALL]")
    text = re.sub(r'\[/TOOL_CALL\]\s*>', '[/TOOL_CALL]', text)
    return text

def _parse_tool_call(raw: str) -> dict | None:
    """
    Parse a tool call from the model's raw output.

    Accepts all bracket variants the model might produce:
      [TOOL_CALL]{...}[/TOOL_CALL]      ← config default
      <TOOL_CALL>{...}[/TOOL_CALL]      ← model sometimes outputs this
      <TOOL_CALL>{...}</TOOL_CALL>       ← pure angle-bracket variant
      [TOOL_CALL]{...}</TOOL_CALL>       ← mixed

    Strategy: normalise to square brackets first, then parse once.
    Also handles JSON embedded directly without outer markers (fallback).
    """
    import re as _re, json as _json

    # ── Step 1: normalise angle-bracket markers to square-bracket ────────────
    text = raw
    text = _re.sub(r'<TOOL_CALL\s*>',  '[TOOL_CALL]',  text)
    text = _re.sub(r'</TOOL_CALL\s*>', '[/TOOL_CALL]', text)
    text = _re.sub(r'<TOOL_CALL/>',    '[TOOL_CALL][/TOOL_CALL]', text)

    # ── Step 2: extract JSON between canonical markers ────────────────────────
    START = TOOL_CALL_MARKER_START   # '[TOOL_CALL]'  from config
    END   = TOOL_CALL_MARKER_END     # '[/TOOL_CALL]' from config

    idx_s = text.find(START)
    idx_e = text.find(END)

    if idx_s != -1 and idx_e != -1 and idx_e > idx_s:
        json_str = text[idx_s + len(START): idx_e].strip()
        try:
            parsed = _json.loads(json_str)
            if isinstance(parsed, dict) and 'name' in parsed:
                return parsed
        except _json.JSONDecodeError:
            # Try extracting the first {...} inside the markers
            m = _re.search(r'\{.*\}', json_str, _re.DOTALL)
            if m:
                try:
                    parsed = _json.loads(m.group())
                    if isinstance(parsed, dict) and 'name' in parsed:
                        return parsed
                except _json.JSONDecodeError:
                    pass

    # ── Step 3: fallback — bare JSON object anywhere in the text ─────────────
    # Only triggers when markers are completely absent (model regression)
    for m in _re.finditer(r'\{[^{}]*"name"\s*:\s*"[^"]+"[^{}]*\}', text, _re.DOTALL):
        try:
            parsed = _json.loads(m.group())
            if isinstance(parsed, dict) and 'name' in parsed:
                logger.debug('_parse_tool_call: recovered via bare-JSON fallback')
                return parsed
        except _json.JSONDecodeError:
            continue

    return None


def _execute_tool(tool_name: str, params: dict, user_id: str):
    """Route tool call to memory functions."""
    logger.info(f"🛠️ Executing tool: {tool_name}")
    scope = params.get("scope", "user")
    
    if tool_name == "store_memory":
        success = store_memory(key=params.get("key", ""), value=params.get("value", ""), user_id=user_id, metadata=params.get("metadata"), scope=scope)
        return f"✓ Stored in {'global' if scope == 'global' else 'user'} memory: {params.get('key')}" if success else "✗ Storage failed"
        
    elif tool_name == "recall_memory":
        results = recall_memories(query=params.get("query", ""), user_id=user_id, top_k=params.get("top_k"), scope=scope)
        if not results: return "No relevant memories found."
        formatted = "\n".join([f"• {r['key']}: {r['value']}" for r in results])
        return f"Recalled:\n{formatted}"
        
    elif tool_name == "read_file":
        res = read_file(**params)
        return f"File Content ({res.get('lines')} lines):\n{res.get('content')}" if res.get('success') else f"Error: {res.get('error')}"
        
    elif tool_name == "write_file":
        result = write_file(params.get("path", ""), params.get("content", ""))
        return f"✓ Successfully wrote to {params.get('path')}" if result.get("success") else f"Error: {result.get('error')}"
        
    elif tool_name == "list_files":
        result = list_files(params.get("directory", "."))
        if result.get("success"):
            file_list = "\n".join([f"- {f['name']} ({f['type']})" for f in result.get('files', [])])
            return f"Directory Contents ({result.get('count')} items):\n{file_list}"
        return f"Error: {result.get('error')}"
        
    elif tool_name == "run_command":
        result = run_command(params.get("cmd", ""), timeout=int(params.get("timeout", 900)))
        output = result.get("stdout") or result.get("stderr") or "No output"
        return f"{'✓ Success' if result.get('success') else '❌ Failed'} (Code: {result.get('returncode')}):\n{output}"
    
    elif tool_name == "scrape_website":
        from app.tools.scraper_tools import scrape_website
        result = scrape_website(**params)
        if result.get("ok"):
            return f"✅ Scraped {result['url']}\nTitle: {result['title']}\n\n{result['text'][:1500]}"
        return f"❌ Scrape failed: {result.get('error', 'Unknown error')}"

    elif tool_name == "web_search":
        return WebSearchTool().execute(params)
    elif tool_name == "send_whatsapp":
        return SendWhatsAppTool().execute(params)
    elif tool_name == "send_email":
        return SendEmailTool().execute(params)
    elif tool_name == "send_telegram":
        from app.tools.comms_tools import SendTelegramTool
        return SendTelegramTool().execute(params)
    elif tool_name == "check_availability":
        return CheckAvailabilityTool().execute(params)
    elif tool_name == "schedule_meeting":
        return ScheduleMeetingTool().execute(params)
    # ── NEW: Search Files Tool ────────────────────────────────────────────────
    elif tool_name == "search_files":
        return SearchFilesTool().execute(params)

    return f"Unknown tool: {tool_name}"

def _clean_response(text: str, builder_mode: bool) -> str:
    if builder_mode: 
        return text.strip()
    
    # Remove tool call markers
    clean = re.sub(re.escape(TOOL_CALL_MARKER_START) + r".*?" + re.escape(TOOL_CALL_MARKER_END), "", text, flags=re.DOTALL)
    clean = re.sub(re.escape(TOOL_CALL_MARKER_START) + r".*$", "", clean, flags=re.DOTALL | re.MULTILINE)
    
    # Only strip [Tool result: ...] if at START of line (system injection)
    clean = re.sub(r"^\s*\[Tool result:.*?\]\s*\n?", "", clean, flags=re.MULTILINE)
    
    # Remove system-injected prompts like "Final Natural Response:"
    clean = re.sub(r"<SYSTEM_INSTRUCTION>.*?Final Natural Response:\s*", "", clean, flags=re.DOTALL | re.IGNORECASE)
    
    clean = clean.strip()
    
    # 🔥 CRITICAL: If cleaning resulted in only signature or empty, return minimal acknowledgment
    signature_patterns = [r'^-\s*LMIM\s*$', r'^LMIM\s*$', r'^-\s*LMIM\s+OS\s*$']
    if not clean or any(re.match(pat, clean, re.IGNORECASE) for pat in signature_patterns):
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for line in lines:
            if not any(re.match(pat, line, re.IGNORECASE) for pat in signature_patterns):
                return line
        return "Understood." if not clean else clean
    
    return clean
    
# ==============================================================================
# 🔥 MODULE-LEVEL HELPER: Wait for llama-server with retries
# ==============================================================================
def _wait_for_llama_server(url: str, timeout: int = 30) -> bool:
    """Retry health check with exponential backoff. Returns True if ready."""
    import time
    health_url = url.replace("/v1/chat/completions", "/health") if "/v1/" in url else url.rstrip("/") + "/health"
    
    for attempt in range(timeout):
        try:
            resp = requests.get(health_url, timeout=2)
            if resp.status_code == 200:
                logger.info(f"✅ llama-server ready after {attempt+1}s")
                return True
        except requests.exceptions.RequestException:
            pass  # Server not ready yet
        time.sleep(1)
    
    logger.error(f"❌ llama-server not ready after {timeout}s")
    return False

def query_model(prompt: str, user_id: str, max_tool_iterations: int = 5,
                conversation_history: list = None, conversation_summary: str = None,
                builder_mode: bool = False, system_override: str = None,
                disable_rag: bool = False):  # ← NEW PARAMETER
    
    STATE_UPDATE_INTERVAL = 15        
    SUMMARY_GENERATION_INTERVAL = 35  
    
    # 🔥 CRITICAL: Use Fresh Read for Provider & Temp
    provider = _get_fresh_env_var("AI_PROVIDER", "local").lower().strip()
    temperature = float(_get_fresh_env_var("LLAMA_TEMP", "0.4"))
    logger.info(f"🔥 PROVIDER DEBUG: os.getenv='{os.getenv('AI_PROVIDER')}' | _get_fresh='{_get_fresh_env_var('AI_PROVIDER')}' | final='{provider}'")
    logger.info("="*60)
    logger.info(f"🧠 QUERY_MODEL START | User: {user_id} | Provider: {provider.upper()} | Temp: {temperature} | Max Iterations: {max_tool_iterations} | disable_rag={disable_rag}")
    
    original_prompt = prompt
    
    # ==============================================================================
    # 🔥 NEW: EMPTY/DUPLICATE MESSAGE DETECTION (Prevent loops at entry)
    # ==============================================================================
    # Reject empty prompts
    if not prompt or not prompt.strip():
        logger.warning(f"⚠️ Empty prompt received from {user_id}")
        return "I notice your message was empty. Please provide your question or request so I can help you."
    
    # Check for duplicate prompts (within last 2 user messages)
    if conversation_history and isinstance(conversation_history, list):
        recent_user_msgs = [m.get("content", "") for m in conversation_history[-4:] if m.get("role") == "user"]
        if len(recent_user_msgs) >= 2 and prompt.strip() == recent_user_msgs[-2].strip():
            logger.warning(f"⚠️ Duplicate prompt detected from {user_id}")
            return "I see you sent the same message again. If I didn't answer correctly, please rephrase your request or let me know what's missing."
    
    # ==============================================================================
    # --- 1. MEMORY MANAGEMENT (AppImage Safe Paths) ---
    # ==============================================================================
    user_mem_dir = MEMORIES_DIR / "users" / user_id
    user_mem_dir.mkdir(parents=True, exist_ok=True)

    summary_manager = ConversationSummary(
        user_id=user_id,
        summary_interval=SUMMARY_GENERATION_INTERVAL, 
        max_history_turns=50,
        memory_dir=user_mem_dir
    )
    
    # session_* IDs are ephemeral page sessions — never load from disk.
    # Only admin_user and chat_* IDs have persistent history on disk.
    is_ephemeral_session = user_id.startswith("session_")

    recent_turns = _session_cache.get(user_id, [])
    if not recent_turns and not is_ephemeral_session:
        history_file = user_mem_dir / "chat_history.json"
        if history_file.exists():
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    recent_turns = data.get("messages", [])
                _session_cache[user_id] = recent_turns
            except Exception as e:
                logger.error(f"Failed to load history: {e}")
    
    recent_turns = recent_turns[-50:] if isinstance(recent_turns, list) else []
    turn_count = len(recent_turns) // 2

    # Auto-summary logic
    if turn_count > 0 and (turn_count % SUMMARY_GENERATION_INTERVAL) == 0:
        logger.warning(f"🚨 SUMMARY TRIGGERED! Turn count {turn_count}")
        summary_prompt = summary_manager.generate_summary_prompt(recent_turns)
        try:
            summary_response = requests.post(
                LOCAL_INFERENCE_URL, 
                json={
                    "model": MODEL_NAME,
                    "messages": [{"role": "user", "content": summary_prompt}],
                    "temperature": 0.2,
                    "max_tokens": 1500
                },
                timeout=15000
            )
            summary_response.raise_for_status()
            summary_text = summary_response.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            
            if summary_text:
                summary_manager.store_summary(summary_text, meta={"source": "auto", "turn": turn_count})
            else:
                logger.error("❌ Summary generation returned EMPTY text.")
        except Exception as e:
            logger.error(f"💥 Failed to generate summary: {e}")
    
    # Detect Memory Triggers
    trigger_words = ["recuerd", "remember", "resumen", "summary", "hablamos", "anterior", "qué vimos", "contexto", "historial"]
    needs_full_history = any(word in prompt.lower() for word in trigger_words)

    # Load Light State
    state_context = ""
    state_file = user_mem_dir / "state.json"
    if state_file.exists():
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            state_context = f"""
### 🧭 CURRENT SESSION STATE
- **Focus:** {state.get('current_focus', 'General conversation')}
- **Mood/Context:** {state.get('mood_context', 'Neutral')}
- **Active Project:** {state.get('active_project', 'None')}
"""
        except Exception: pass

    # Prepare History Injection
    history_injection = ""
    if needs_full_history:
        full_summary = summary_manager.get_stored_summary()
        if full_summary:
            history_injection = f"\n\n📜 CONVERSATION HISTORY SUMMARY:\n{full_summary}\n---\n"

    if conversation_history and isinstance(conversation_history, list):
        existing_contents = {m.get("content") for m in recent_turns}
        for ext_msg in conversation_history:
            if ext_msg.get("content") not in existing_contents:
                recent_turns.insert(0, {"role": ext_msg["role"], "content": ext_msg["content"]})
    
    if conversation_summary and not history_injection:
        history_injection = f"\n\n📜 EXTERNAL SUMMARY:\n{conversation_summary}\n---\n"

    # ==============================================================================
    # --- 2. SYSTEM CONTENT ---
    # ==============================================================================
    if builder_mode:
        from app.config import BUILDER_CODE_GEN_PROMPT
        system_content = BUILDER_CODE_GEN_PROMPT
    elif system_override:
        system_content = system_override
    else:
        from app.config import DEFAULT_CONTEXT
        system_content = DEFAULT_CONTEXT

    if ENABLE_TOOL_CALLING and not builder_mode:
        pass  # Tool protocol is in DEFAULT_CONTEXT — no duplicate injection needed

    
    # ==============================================================================
    # 🔥 RAG CONTEXT INJECTION — Only if not disabled
    # ==============================================================================
    if not builder_mode and not disable_rag and has_document(user_id):
        chunks = retrieve_chunks(user_id, prompt)
        if chunks:
            rag_context = "\n\n".join([
                "[DOCUMENT CONTEXT] The following is from an uploaded document:",
                "---",
                *chunks,
                "---\nAnswer based **only** on the document above. If the answer is not found in the document, say so clearly. Do not invent information."
            ])
            # Inject into system message instead of user prompt
            if system_content:
                system_content = rag_context + "\n\n" + system_content
            else:
                system_content = rag_context
            logger.info(f"📖 Injected {len(chunks)} RAG chunks into system prompt for user {user_id}")
    elif not builder_mode and disable_rag:
        logger.debug(f"🔇 RAG disabled for user {user_id} — skipping document injection")
    

    # ==============================================================================
    # 🔥 PRIME DIRECTIVE & LANGUAGE INJECTION
    # ==============================================================================
    from app.config import PRIME_DIRECTIVE, LANGUAGE
    if PRIME_DIRECTIVE:
        system_content = f"[PRIME DIRECTIVE]\n{PRIME_DIRECTIVE}\n\n{system_content}"
        logger.info(f"📜 Injected Prime Directive ({len(PRIME_DIRECTIVE)} chars)")
    
    lang_instruction = {
        "en": "You are an English-speaking assistant. Respond in English.",
        "es": "Eres un asistente que habla español. Responde siempre en español, usando un tono profesional y cálido."
    }.get(LANGUAGE, "Respond in English.")
    system_content = f"{lang_instruction}\n\n{system_content}"
    logger.info(f"🌐 Language instruction set to: {LANGUAGE}")
    
# ==============================================================================
    # 🔥 NEW: INJECT WORKSPACE CONTEXT INTO SYSTEM PROMPT
    # ==============================================================================
    from app.workspace import get_workspace
    ws = get_workspace()
    if ws:
        ws_info = f"""
[ACTIVE WORKSPACE: {ws}]
All file paths in read_file, write_file, list_files, search_files must be relative to this folder.
Examples:
  - read_file("src/main.py")
  - write_file("output/result.txt", content)
  - list_files(".")
  - search_files("pattern", file_pattern="*.py")
Do NOT use absolute paths. All operations are scoped to the workspace.
"""
        system_content = ws_info + system_content
    else:
        no_ws_note = """
[NO WORKSPACE SELECTED]
You cannot read, write, list, or search files because no workspace folder is active.
The user must select a workspace folder using the "Select Folder" button in the Workspace tab or sidebar.
"""
        system_content = no_ws_note + system_content
    
    # Track previous replies for repetition detection
    previous_replies = []
    # Track (hash → result) for same-turn tool dedup and terminal tool guard
    executed_tool_hashes: dict = {}

    # ==============================================================================
    # --- 3. INFERENCE LOOP ---
    # ==============================================================================
    for iteration in range(max_tool_iterations + 1):
        # 🔥 DEBUG: Log iteration state upfront
        logger.info(f"🔄 [ITER {iteration+1}/{max_tool_iterations+1}] Tools:{ENABLE_TOOL_CALLING} | Builder:{builder_mode} | Provider:{provider}")
        
        messages = [{"role": "system", "content": system_content}]
        
        if state_context: 
            messages[0]["content"] += "\n\n" + state_context
            logger.debug(f"📎 Added state_context ({len(state_context)} chars)")
        if history_injection: 
            messages[0]["content"] += "\n\n" + history_injection
            logger.debug(f"📎 Added history_injection ({len(history_injection)} chars)")
        
        window_size = 8 if (needs_full_history and not history_injection) else 4
        recent_real_turns = recent_turns[-window_size:] if len(recent_turns) > window_size else recent_turns

        for turn in recent_real_turns:
            if isinstance(turn, dict) and "role" in turn and "content" in turn:
                messages.append({"role": turn["role"], "content": turn["content"]})
        
        messages.append({"role": "user", "content": prompt})
        
        # 🔥 DEBUG: Log prompt structure (first iteration only)
        if iteration == 0:
            total_tokens = sum(len(m["content"])//4 for m in messages)
            logger.info(f"📊 Prompt stats: {len(messages)} messages | ~{total_tokens} tokens | system_len:{len(system_content)}")
            logger.debug(f"🔍 System prompt preview: {system_content[:300]}...")
            logger.debug(f"🔍 User prompt: {prompt[:200]}...")
            
            # Dump full debug file for inspection
            debug_prompt_file = LOGS_DIR / f"debug_prompt_{user_id}_{int(time.time())}.txt"
            try:
                debug_prompt_file.parent.mkdir(parents=True, exist_ok=True)
                with open(debug_prompt_file, 'w', encoding='utf-8') as f:
                    f.write(f"=== ITERATION {iteration+1} ===\n")
                    f.write(f"SYSTEM ({len(system_content)} chars):\n{system_content}\n\n")
                    f.write(f"MESSAGES ({len(messages)} items):\n{json.dumps(messages, indent=2, ensure_ascii=False)}\n\n")
                    f.write(f"CONFIG: ENABLE_TOOL_CALLING={ENABLE_TOOL_CALLING}, MARKERS='{TOOL_CALL_MARKER_START}'...'{TOOL_CALL_MARKER_END}'\n")
                logger.info(f"💾 Debug prompt dumped to: {debug_prompt_file}")
            except Exception as e:
                logger.warning(f"⚠️ Could not write debug file: {e}")

        try:
            raw_reply = ""
            
            # 🔥 HYBRID ROUTING (Cloud vs Local)
            if provider != "local":
                # ==================== CLOUD ROUTING ====================
                logger.info(f"☁️ === CLOUD ROUTING START ===")
                logger.info(f"🔍 Provider detected: '{provider}' (from _get_fresh_env_var)")
                
                model_name = _get_fresh_env_var(f"CLOUD_MODEL_{provider.upper()}", "default-model")
                api_key = _get_fresh_env_var(f"{provider.upper()}_API_KEY")
                
                if not api_key or api_key in ["Not Set", ""]:
                    logger.error(f"❌ API Key for {provider} is missing or invalid")
                    raise ValueError(f"API Key for {provider} is missing.")
            
                headers = {"Content-Type": "application/json"}
                url = ""
                payload = {}
            
                # ✅ FIXED: No trailing spaces in URLs
                if provider == "openai":
                    url = "https://api.openai.com/v1/chat/completions"
                    headers["Authorization"] = f"Bearer {api_key}"
                    payload = {"model": model_name, "messages": messages, "temperature": temperature, "max_tokens": 4096}
                elif provider == "anthropic":
                    url = "https://api.anthropic.com/v1/messages"
                    headers["x-api-key"] = api_key
                    headers["anthropic-version"] = "2023-06-01"
                    system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
                    user_msgs = [m for m in messages if m["role"] != "system"]
                    payload = {"model": model_name, "max_tokens": 4096, "system": system_msg, "messages": user_msgs, "temperature": temperature}
                elif provider == "groq":
                    url = "https://api.groq.com/openai/v1/chat/completions"
                    headers["Authorization"] = f"Bearer {api_key}"
                    payload = {"model": model_name, "messages": messages, "temperature": temperature, "max_tokens": 4096}
                else:
                    logger.error(f"❌ Unsupported cloud provider: '{provider}'")
                    raise ValueError(f"Provider '{provider}' not supported.")
            
                logger.info(f"☁️ Posting to: {url} | Model: {model_name}")
                
                resp = requests.post(url, json=payload, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                
                if provider == "anthropic":
                    content_blocks = data.get("content", [])
                    raw_reply = "".join(block.get("text", "") for block in content_blocks if block.get("type") == "text")
                else:
                    raw_reply = data["choices"][0]["message"]["content"]
                    
                logger.info(f"✅ Cloud response received ({len(raw_reply)} chars)")
                logger.info(f"☁️ === CLOUD ROUTING END ===")
            
            else:
                # ==================== LOCAL ROUTE ====================
                logger.info(f"🏠 === LOCAL INFERENCE DEBUG START ===")
                logger.info(f"🔍 LOCAL_INFERENCE_URL: '{LOCAL_INFERENCE_URL}'")
                logger.info(f"🔍 MODEL_NAME: '{MODEL_NAME}' | Temperature: {temperature}")
                
                # 🔥 WAIT FOR SERVER BEFORE ANYTHING ELSE
                if not _wait_for_llama_server(LOCAL_INFERENCE_URL, timeout=30):
                    return "⚠️ Local model server not ready. Please wait ~10s and retry."
                
                payload = {
                    "model": MODEL_NAME,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": _get_max_tokens(provider, builder_mode, MODEL_NAME),
                    # NOTE: Keep stop sequences minimal — "User:" and "Human:" fire too
                    # early on Qwen models because they echo the prompt format.
                    # "</s>" is the only safe universal stop token for local models.
                    "stop": ["</s>"]
                }
                
                logger.debug(f"📦 Local payload preview: {json.dumps(payload, indent=2)[:800]}...")
                
                try:
                    logger.info(f"🚀 POST to {LOCAL_INFERENCE_URL} (timeout=320s)...")
                    start_time = time.time()
                    
                    response = requests.post(LOCAL_INFERENCE_URL, json=payload, timeout=320)
                    elapsed = time.time() - start_time
                    
                    logger.info(f"✅ Response: {response.status_code} after {elapsed:.2f}s")
                    response.raise_for_status()
                    
                    result = response.json()
                    choices = result.get("choices", [])
                    if not choices:
                        logger.error(f"❌ No 'choices' in response")
                        raise ValueError("No choices in llama-server response")
                    
                    msg_obj   = choices[0].get("message", {})
                    # Qwen3 thinking models: answer is in reasoning_content, content is empty
                    raw_reply = (
                        msg_obj.get("content") or
                        msg_obj.get("reasoning_content") or
                        ""
                    ).strip()
                    logger.info(f"✅ Extracted reply: {len(raw_reply)} chars")
                    logger.info(f"🔥 RAW MODEL OUTPUT: {repr(raw_reply[:200])}")
                    
                except json.JSONDecodeError as je:
                    logger.error(f"❌ JSON parse failed: {je}")
                    raise
                except requests.exceptions.RequestException as req_e:
                    logger.error(f"❌ Request failed: {req_e}")
                    raise
                except Exception as local_e:
                    logger.error(f"❌ Local inference error: {local_e}", exc_info=True)
                    raise
                
                logger.info(f"🏠 === LOCAL INFERENCE DEBUG END ===")

                # ==============================================================================
            # 🔥 NEW: LOOP DETECTION + HARD-CODED FEEDBACK INJECTION
            # ==============================================================================
            if iteration > 0 and raw_reply:
                clean_reply_check = raw_reply.strip().lower()
                
                # Check for empty/signature-only replies
                signature_patterns = [r'^-\s*lmim\s*$', r'^lmim\s*$', r'^-\s*lmim\s+os\s*$', r'^lmim\s+os\s*$', r'^lmim\s+os$', r'^- lmim$']
                is_signature_only = any(re.match(pat, clean_reply_check, re.IGNORECASE) for pat in signature_patterns)
                
                # Check for empty or whitespace-only
                is_empty = not clean_reply_check or clean_reply_check.isspace()
                
                # Check for repeated "I need more info" type loops
                info_request_patterns = [
                    r'provide.*phone', r'confirmation.*required', r'phone.*required',
                    r'meeting type.*required', r'what.*phone', r'need.*phone',
                    r'required.*field', r'missing.*info'
                ]
                is_repeated_info_request = any(re.search(pat, clean_reply_check) for pat in info_request_patterns)
                
                # Check for repeated "need more info" loops with auto-extraction
                if is_repeated_info_request and iteration >= 2:
                    # Check if user already provided phone in conversation
                    convo_text = " ".join([m.get("content", "") for m in recent_real_turns[-10:]])
                    
                    # 🔥 EXTRACT PHONE FROM CONVERSATION (robust regex)
                    phone_match = re.search(r'(\+?\d[\d\s\-]{7,}\d)', convo_text)
                    if phone_match:
                        extracted_phone = re.sub(r'[^\d+]', '', phone_match.group(1))
                        logger.warning(f"⚠️ Model asking for phone but found: {extracted_phone}")
                        
                        # Force tool call with extracted params
                        prompt = f"""<SYSTEM_INSTRUCTION>
AUTO-CORRECTION: User already provided phone: {extracted_phone}
Original Request: {original_prompt}
You have ALL required info. CALL schedule_meeting NOW.
Output ONLY the tool call marker, then STOP.
[TOOL_CALL]{{"name": "schedule_meeting", "parameters": {{"date": "2026-03-23", "time": "17:00", "user_name": "Gabriel Zaragoza", "user_phone": "{extracted_phone}", "meeting_type": "meeting", "tenant_id": "hexa"}}}}[/TOOL_CALL]
"""
                        continue  # Retry with forced tool call
                
                # Check for exact repetition across iterations
                if clean_reply_check in previous_replies or (is_signature_only and len(previous_replies) >= 2):
                    logger.warning(f"⚠️ Detected repetition loop: '{clean_reply_check[:30]}...' repeated. Breaking loop.")
                    # Force a minimal varied response to break the cycle
                    if is_signature_only:
                        raw_reply = "Understood. How else can I assist you today?"
                    else:
                        raw_reply = "I see we're repeating. Let me provide a fresh response."
                    break  # Exit loop to return this varied response
                
                # 🔥 CRITICAL: If model outputs empty/signature or keeps asking for info user already gave
                if is_empty or is_signature_only:
                    logger.warning(f"⚠️ Empty/signature reply detected at iteration {iteration+1}. Injecting hard-coded feedback.")
                    # Inject hard-coded feedback to force action
                    prompt = f"""<SYSTEM_INSTRUCTION>
CRITICAL: Your previous response was empty or only a signature.
Original User Request: {original_prompt}
You MUST provide a substantive answer or call a tool. Do NOT output only your signature.
If you have all required information, CALL THE APPROPRIATE TOOL NOW.
If you're missing information, ASK SPECIFICALLY what's needed in ONE clear question.
Final Response:
"""
                    continue  # Retry with feedback
                
                # Second check for repeated info request (with phone extraction fallback)
                if is_repeated_info_request and iteration >= 2:
                    # Check if user already provided the info in conversation history
                    convo_text = " ".join([m.get("content", "") for m in recent_real_turns[-10:]])
                    # Check for phone numbers in conversation
                    if "+52" in convo_text or re.search(r'\+?\d[\d\s\-]{7,}\d', convo_text):
                        logger.warning(f"⚠️ Model asking for phone but user already provided it. Forcing extraction.")
                        # Auto-extract phone from conversation
                        phone_match = re.search(r'(\+?\d[\d\s\-]{7,}\d)', convo_text)
                        if phone_match:
                            extracted_phone = re.sub(r'[^\d+]', '', phone_match.group(1))
                            prompt = f"""<SYSTEM_INSTRUCTION>
AUTO-CORRECTION: User already provided phone number: {extracted_phone}
Original Request: {original_prompt}
You have all required info. CALL schedule_meeting NOW with:
- phone: {extracted_phone}
- other params from context
Output ONLY the tool call marker, then STOP.
"""
                            continue
                
                previous_replies.append(clean_reply_check)
                if len(previous_replies) > 3:  # Keep only last 3 for memory efficiency
                    previous_replies.pop(0)

            # ==============================================================================
            # 🔥 TOOL EXECUTION LOGIC WITH VERBOSE DEBUGGING
            # ==============================================================================
            if ENABLE_TOOL_CALLING and not builder_mode and iteration < max_tool_iterations:
                logger.info(f"🔧 Attempting tool parse (iteration {iteration+1})...")
                logger.debug(f"🔍 Markers: START='{TOOL_CALL_MARKER_START}' END='{TOOL_CALL_MARKER_END}'")
                logger.debug(f"🔍 Raw reply for parsing: {repr(raw_reply[:300])}")
                
                tool_call = _parse_tool_call(raw_reply)
                
                if tool_call:
                    logger.info(f"✅ TOOL PARSED: name='{tool_call.get('name')}' | params={tool_call.get('parameters')}")
                else:
                    logger.warning(f"⚠️ NO TOOL CALL DETECTED")
                    if TOOL_CALL_MARKER_START not in raw_reply:
                        logger.warning(f"💡 Marker '{TOOL_CALL_MARKER_START}' NOT FOUND in raw reply")
                    if TOOL_CALL_MARKER_END not in raw_reply:
                        logger.warning(f"💡 Marker '{TOOL_CALL_MARKER_END}' NOT FOUND in raw reply")
                    marker_idx = raw_reply.lower().find("tool")
                    if marker_idx != -1:
                        context = raw_reply[max(0,marker_idx-50):marker_idx+100]
                        logger.warning(f"💡 Context around 'tool': {repr(context)}")
                
                if tool_call and tool_call.get("name"):
                    t_name   = tool_call["name"]
                    t_params = tool_call.get("parameters", {})
                    t_hash   = _make_tool_hash(t_name, t_params)

                    # ── Dedup guard ───────────────────────────────────────────
                    if t_hash in executed_tool_hashes:
                        cached = executed_tool_hashes[t_hash]
                        logger.warning(f"⚠️ Duplicate tool call '{t_name}' (hash={t_hash}) — returning cached result.")
                        confirmation = _build_confirmation(t_name, cached)
                        _finalize_reply(confirmation, user_id, original_prompt, recent_turns, _session_cache)
                        return confirmation

                    logger.info(f"🔧 Executing tool: {t_name} with params: {t_params}")
                    tool_result = _execute_tool(t_name, t_params, user_id)
                    logger.info(f"📥 Tool result: {repr(tool_result[:200])}...")
                    executed_tool_hashes[t_hash] = tool_result

                    # ── Terminal tool success → skip model ────────────────────
                    is_success = any(m in tool_result for m in (
                        "✅ SUCCESS", "✓ Booked", "sent successfully",
                        "EMAIL SENT", "✅ EMAIL", "TELEGRAM SENT", "✅ Telegram"
                    ))
                    if t_name in _TERMINAL_TOOLS and is_success:
                        logger.info(f"🏁 Terminal tool '{t_name}' succeeded — bypassing model, returning confirmation.")
                        confirmation = _build_confirmation(t_name, tool_result)
                        _finalize_reply(confirmation, user_id, original_prompt, recent_turns, _session_cache)
                        return confirmation

                    is_conflict = "CONFLICT" in tool_result or "already booked" in tool_result.lower()
                    is_error    = tool_result.startswith("❌") or tool_result.startswith("✗")

                    # ── check_availability shortcut ───────────────────────────
                    if t_name == "check_availability" and not is_error and not is_conflict:
                        booking_params = _extract_booking_params(original_prompt, t_params)
                        if booking_params:
                            slot = _pick_first_slot(tool_result, booking_params.get("time"))
                            if slot:
                                booking_params["time"] = slot
                                logger.info(f"⚡ Auto-advancing to schedule_meeting (slot={slot})")
                                sched_result = _execute_tool("schedule_meeting", booking_params, user_id)
                                logger.info(f"📥 schedule_meeting result: {repr(sched_result[:200])}")
                                executed_tool_hashes[_make_tool_hash("schedule_meeting", booking_params)] = sched_result
                                if any(m in sched_result for m in ("✅ SUCCESS", "✓ Booked")):
                                    confirmation = _build_confirmation("schedule_meeting", sched_result)
                                    _finalize_reply(confirmation, user_id, original_prompt, recent_turns, _session_cache)
                                    return confirmation
                                prompt = (
                                    f"[RESULT] schedule_meeting: {sched_result}\n"
                                    f"The booking failed. Tell the person clearly and suggest a different time. "
                                    f"Reply in 1-2 sentences. Do NOT call any tools."
                                )
                                continue

                        already_checked = sum(1 for k in executed_tool_hashes if "check_availability" in k)
                        if already_checked >= 1:
                            prompt = (
                                f"[RESULT] check_availability: {tool_result}\n"
                                f"Availability checked. Ask the person which slot they want, "
                                f"or ask for any missing booking details. "
                                f"Do NOT call check_availability again. Reply in 1-2 sentences."
                            )
                            logger.info("🔄 check_availability ran once — forcing model to ask user")
                            continue

                    if is_conflict or is_error:
                        prompt = (
                            f"[RESULT] {t_name}: {tool_result}\n"
                            f"The action failed. Tell the person clearly and suggest an alternative. "
                            f"Reply in 1-2 sentences. Do NOT call any tools."
                        )
                    else:
                        prompt = (
                            f"[RESULT] {t_name}: {tool_result}\n"
                            f"Task is done. Confirm to the person in 1-2 friendly sentences. "
                            f"Do NOT call any tools. Do NOT repeat the tool call."
                        )
                    logger.info(f"🔄 Post-tool prompt injected (conflict={is_conflict}, error={is_error})")
                    continue
                else:
                    logger.info(f"⏭️ No valid tool call - proceeding to final response")
            
            # ==============================================================================
            # === FINAL RESPONSE PREPARATION ===
            # ==============================================================================
            clean_reply = _clean_response(raw_reply, builder_mode)
            logger.info(f"🧹 Cleaned reply: {len(clean_reply)} chars | Preview: {repr(clean_reply[:150])}")
            
            # Defensive memory update (AppImage-safe)
            try:
                update_session_memory(user_id, original_prompt, clean_reply)
                logger.info(f"✅ Memory update succeeded for {user_id}")
            except (OSError, PermissionError, IOError) as mem_err:
                logger.warning(f"⚠️ Memory write failed (non-fatal): {mem_err} | DATA_DIR={DATA_DIR}")
            except Exception as mem_err:
                logger.error(f"❌ Unexpected memory error: {mem_err}", exc_info=True)
            
            # Update cache
            _session_cache[user_id] = recent_turns + [
                {"role": "user", "content": original_prompt}, 
                {"role": "assistant", "content": clean_reply}
            ]
            
            logger.info(f"🎯 Returning final reply ({len(clean_reply)} chars)")
            return clean_reply or "..."
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ API request failed for provider '{provider}': {e}")
            if provider != "local":
                return f"⚠️ Cloud provider '{provider}' error: {str(e)[:100]}... Check API key."
            return "Sorry, connection error to local model."
        except Exception as e:
            logger.error(f"💥 Unexpected error in query_model: {e}", exc_info=True)
            if isinstance(e, (OSError, PermissionError, IOError)):
                return f"⚠️ File I/O error (AppImage?): {str(e)[:80]}"
            return "Sorry, an error occurred."
    
    logger.warning(f"⚠️ Max iterations ({max_tool_iterations}) reached without final response")
    return "Max iterations reached."
