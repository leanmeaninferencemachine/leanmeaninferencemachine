#!/usr/bin/env python3
import os
import logging
import json
import time
import asyncio
import sys
import glob
import csv
import subprocess
import signal
import requests
import threading
import re  
import urllib.request
import urllib.error
import psutil
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from flask_cors import CORS
from flask import Flask, request, Response, jsonify, render_template

# App imports
from app.router import route_request
from app.memory_functions import update_session_memory, get_session_context, get_recent_chat_history
from app.model_interface import query_model
from app.config import (
    LOG_LEVEL, LOG_MAX_BYTES, LOG_BACKUP_COUNT, ENABLE_AUDIT_LOGGING,
    BASE_DIR, DATA_DIR, CONFIG_DIR, MEMORIES_DIR, LOGS_DIR, AGENDAS_DIR, DB_DIR  # ← Added DB_DIR
)
from app.events.base import event_bus, EventType, emit

_WA_IPC_PORT = int(os.getenv('LMIM_WA_IPC_PORT', '5002'))
_WA_IPC_BASE = f'http://127.0.0.1:{_WA_IPC_PORT}'

# ==============================================================================
# 🔧 HELPER FUNCTIONS
# ==============================================================================
def kill_process_by_name(name: str):
    """Cross-platform process killer."""
    exe_name = name + ".exe" if sys.platform == "win32" else name
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/IM", exe_name], 
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        subprocess.run(["pkill", "-f", name], 
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

# ==============================================================================
# 🔥 APPIMAGE COMPATIBILITY: FORCE WRITABLE PATHS (Already defined in config.py)
# ==============================================================================
# DATA_DIR, CONFIG_DIR, etc. are imported from app.config above
# Ensure they exist immediately
for d in [DATA_DIR, CONFIG_DIR, MEMORIES_DIR, LOGS_DIR, AGENDAS_DIR, DB_DIR]:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"⚠️ Warning: Could not create {d}: {e}")

print(f"✅ [MAIN] Data Dir set to: {DATA_DIR}")
print(f"✅ [MAIN] Config Dir set to: {CONFIG_DIR}")
print(f"✅ [MAIN] Memories Dir set to: {MEMORIES_DIR}")

# ==============================================================================
# 🔐 Logging setup
# ==============================================================================
def setup_logging():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    app_handler = RotatingFileHandler(
        LOGS_DIR / "app.log",
        maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT
    )
    app_handler.setLevel(LOG_LEVEL)
    app_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S'
    ))
    
    if ENABLE_AUDIT_LOGGING:
        audit_handler = RotatingFileHandler(
            LOGS_DIR / "memory_audit.log",
            maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT
        )
        audit_handler.setLevel(logging.INFO)
        audit_handler.setFormatter(logging.Formatter('%(message)s'))
        audit_logger = logging.getLogger("audit")
        audit_logger.setLevel(logging.INFO)
        audit_logger.addHandler(audit_handler)
        audit_logger.propagate = False
    else:
        audit_logger = None

    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)
    root_logger.addHandler(app_handler)
    
    console = logging.StreamHandler()
    console.setLevel(LOG_LEVEL)
    console.setFormatter(logging.Formatter('%(levelname)s | %(message)s'))
    root_logger.addHandler(console)
    
    return audit_logger

audit_logger = setup_logging()
logger = logging.getLogger(__name__)

app = Flask(__name__)
from flask_cors import CORS
CORS(app, resources={r"/*": {"origins": ["*"]}})

# === 🛠️ BUILD STATUS CACHE (Global Singleton) ===
_build_results = {}

def _on_build_success(event):
    payload = event.payload
    task_id = payload.get('task_id')
    if task_id and task_id in _build_results:
        _build_results[task_id].update({
            'status': 'success',
            'file_path': payload.get('file_path'),
            'file': payload.get('file'),
            'attempts': payload.get('attempts', 1)
        })

def _on_build_error(event):
    payload = event.payload
    task_id = payload.get('task_id')
    if task_id and task_id in _build_results:
        _build_results[task_id].update({
            'status': 'failed',
            'error': payload.get('error', 'Unknown error')
        })

def _on_build_step(event):
    payload = event.payload
    task_id = payload.get('task_id')
    attempt = payload.get('attempt')
    if task_id:
        logger.debug(f"🔄 {task_id}: step {attempt} complete")

def _register_status_handlers(bus):
    if bus:
        bus.subscribe(EventType.BUILD_SUCCESS, _on_build_success, priority=5)
        bus.subscribe(EventType.BUILD_ERROR, _on_build_error, priority=5)
        bus.subscribe(EventType.BUILD_STEP_COMPLETE, _on_build_step, priority=1)

# === 🚀 ROUTES & LOGIC ===

@app.route("/", methods=["GET"])
def home():
    return "LMIM AI Engine is live. Visit /dev for dashboard."

@app.route('/dev')
def dev_interface():
    return render_template('dev_dashboard.html',
                           user="admin_dev_andres",
                           status="online")
              


@app.route("/ask", methods=["POST"])
def ask():
    # Legacy endpoint compatibility
    msg = request.form.get("prompt", "")
    user_id = request.form.get("userToken") or request.remote_addr
    try:
        reply = query_model(msg, user_id)
        return Response(reply, mimetype="text/plain")
    except Exception as e:
        logger.error(f"Error in /ask: {e}")
        return Response("Error", status=500)

# === 🧠 CENTRAL ROUTER LOGIC ===
def route_request(user_prompt: str, user_id: str, source: str = "unknown"):
    """
    Decide qué agente procesar la solicitud basándose SOLO en la intención.
    """
    prompt_lower = user_prompt.lower()
    
    # 1. DETECTAR INTENCIÓN DE CONSTRUCCIÓN (Builder/Planner)
    build_keywords = [
        "create a script", "write code", "build a tool", "generate python",
        "make a file", "fix the code", "refactor", "create a function",
        "automate this", "write a test", "implement feature",
        "crear un script", "escribir código", "generar archivo"
    ]
    is_build_request = any(kw in prompt_lower for kw in build_keywords)
    
    if is_build_request:
        logger.info(f"🔨 Intent Detected: BUILD. Routing to Planner...")
        return trigger_build_flow(user_prompt, user_id, source)
    
    # 2. DETECTAR ORIGEN ESPECÍFICO (WhatsApp Agent tiene lógica de perfil/transcripción)
    if source == "whatsapp":
        logger.info(f"📱 Source Detected: WhatsApp. Routing to WhatsAppAgent...")
        from app.agents.whatsapp_agent import WhatsAppAgent
        agent = WhatsAppAgent()
        phone = user_id.replace("wa_", "") if user_id.startswith("wa_") else "0000000000"
        return agent.process_message_sync(phone, user_prompt)
    
    # 3. DEFAULT: Base Agent Logic (Chat General + Herramientas)
    logger.info(f"💬 Intent Detected: GENERAL CHAT. Routing to Base Flow...")
    return trigger_base_chat_flow(user_prompt, user_id)

# === 🏗️ BUILD FLOW TRIGGER ===
def trigger_build_flow(prompt: str, user_id: str, source: str):
    """Lanza el proceso asíncrono de Planner -> Builder."""
    import asyncio
    from app.agents.planner import plan_project
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        manifest = loop.run_until_complete(plan_project(prompt, user_id))
    finally:
        loop.close()
        
    if manifest:
        base_time = int(time.time())
        task_id = f"build_{user_id}_{base_time}"
        
        # Sanitize filename
        files_list = manifest.get('files', [])
        filename = "solution.py"
        if files_list:
            filename = files_list[0].get('name', 'solution.py')
            if filename.startswith('workspace/'):
                filename = filename[len('workspace/'):]
        
        emit(EventType.BUILD_REQUEST, payload={
            "task_id": task_id,
            "description": prompt,
            "language": manifest.get('language', 'python'),
            "filename": filename,
            "max_attempts": 10,
            "user_id": user_id,
            "source": source,
            "dependencies": manifest.get('dependencies', [])
        })
        
        # Update local cache for immediate UI feedback
        _build_results[task_id] = {"status": "started", "file": filename}
        
        return f"🚀 **Build Started!**\nProject: `{manifest.get('project_name')}`\nTask ID: `{task_id}`\nFile: `{filename}`\nCheck status in the 'Build Logs' tab."
    else:
        return "❌ Failed to plan the project. Please be more specific."

# === 💬 BASE CHAT FLOW (Con Memoria y Herramientas) ===
def trigger_base_chat_flow(prompt: str, user_id: str):
    """Flujo estándar de chat con memoria persistente y herramientas."""
    from app.memory_functions import get_recent_chat_history, log_whatsapp_chat_turn
    from app.model_interface import query_model
    
    # 1. Cargar Memoria
    history = get_recent_chat_history(user_id, limit=10)
    conv_hist = []
    if history:
        for entry in history:
            conv_hist.append({"role": entry["role"], "content": entry["content"]})
    
    # 2. Llamar al Modelo
    reply = query_model(
        prompt=prompt,
        user_id=user_id,
        conversation_history=conv_hist,
        conversation_summary="",
        builder_mode=False
    )
    
    # 3. Guardar Memoria
    log_whatsapp_chat_turn(user_id, prompt, reply, max_turns=20)
    return reply

# === 🛠️ DEV INTERFACE ENDPOINT (ROUTER-BASED) ===
@app.route("/api/dev/chat", methods=["POST"])
def dev_chat_unified():
    data = request.get_json(force=True, silent=True) or {}
    msg = data.get("prompt")
    user_id = data.get("user_id", "dev_admin")
    if not msg: 
        return jsonify({"reply": "Empty prompt"}), 400  # ← No trailing space
        
    try:
        from app.router import route_request
        response_text = route_request(msg, user_id, source="dev_interface")  # ← No trailing spaces
        is_build = "Task ID:" in response_text and "Build Started" in response_text  # ← No trailing spaces
        
        # ✅ FIXED: No trailing spaces in JSON keys
        return jsonify({
            "reply": response_text,
            "build_triggered": is_build,
            "routing": "unified_router"
        })
    except Exception as e:
        logger.error(f"Router Endpoint Error: {e}", exc_info=True)
        return jsonify({"reply": f"System Error: {str(e)}"}), 500

# === 📊 INTERNAL STATUS ENDPOINTS (For Dashboard) ===

@app.route("/api/internal/wa-status", methods=["GET"])
def wa_status():
    """Read WhatsApp Queue directly."""
    try:
        # ✅ UPDATED: Use global DATA_DIR
        queue_file = DATA_DIR / "whatsapp_outbound_queue.json"
        
        if queue_file.exists():
            with open(queue_file, 'r', encoding='utf-8') as f:
                queue = json.load(f)
            pending = len([x for x in queue if x.get('status') == 'pending'])
            sent = len([x for x in queue if x.get('status') == 'sent'])
            return jsonify({
                "total": len(queue),
                "pending": pending,
                "sent": sent,
                "last_updated": datetime.now().isoformat()
            })
        return jsonify({"total": 0, "pending": 0, "message": "Queue file empty or missing"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/internal/build-status", methods=["GET"])
def build_status_from_disk():
    """Scans workspace/debug/ for recent build artifacts."""
    # ✅ UPDATED: Use global DATA_DIR for workspace
    workspace_dir = DATA_DIR / "workspace"
    debug_dir = workspace_dir / "debug"
    
    if not debug_dir.exists():
        debug_dir.mkdir(parents=True, exist_ok=True)
        return jsonify({"info": "Created workspace/debug/ directory. No builds yet."})
    
    files = sorted(glob.glob(str(debug_dir / "*.py")), key=os.path.getmtime, reverse=True)[:20]
    tasks = {}
    
    for i, f_path in enumerate(files):
        fname = os.path.basename(f_path)
        try:
            with open(f_path, 'r', encoding='utf-8') as f:
                content = f.read()
            tasks[f"build_{i}"] = {
                "file": fname,
                "status": "Completed",
                "preview": content[:300] + "...",
                "path": str(f_path)
            }
        except Exception as e:
            tasks[f"build_{i}"] = {"file": fname, "error": str(e)}
            
    return jsonify(tasks if tasks else {"info": "No .py files found in workspace/debug/"})

@app.route("/api/internal/config-status", methods=["GET"])
def get_config_status():
    """Returns current configuration from .env and user_identity.json (secrets masked)."""
    import json
    from dotenv import load_dotenv, dotenv_values
    
    # 🔥 CRITICAL: Explicitly load from writable DATA_DIR with override
    env_path = DATA_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)  # ← Force reload latest values
        logger.debug(f"🔄 Reloaded .env from: {env_path}")
    else:
        # Fallback to bundle if user .env missing (first run)
        bundle_env = BASE_DIR / ".env"
        if bundle_env.exists():
            load_dotenv(bundle_env, override=True)
            logger.debug(f"📦 Loaded default .env from bundle: {bundle_env}")
    
    # Debug log to verify Python sees the variables
    model_path = os.getenv("MODEL_PATH")
    logger.debug(f"🔍 DEBUG: MODEL_PATH in memory: '{model_path}'")
    
    def get_val(key, default="Not Set"):
        val = os.getenv(key, default)
        # Mask secrets only if they exist and are long enough
        if any(k in key.lower() for k in ["token", "pass", "secret", "key"]):
            if val and val != default and len(str(val)) > 8:
                return str(val)[:4] + "********" + str(val)[-4:]
        return val if val else default

    # 2. READ USER IDENTITY (user_identity.json)
    identity_path = CONFIG_DIR / "user_identity.json"
    
    user_identity = {}
    if identity_path.exists():
        try:
            with open(identity_path, 'r', encoding='utf-8') as f:
                user_identity = json.load(f)
            logger.debug("✅ Loaded user_identity.json")
        except Exception as e:
            logger.error(f"❌ Failed to load user_identity.json: {e}")
            user_identity = {}
    else:
        logger.debug("⚠️ user_identity.json not found, using defaults.")

    # 3. READ WHATSAPP SESSION STATUS
    wa_session_path = DATA_DIR / "whatsapp_daemon_session.json"
    
    wa_session_active = False
    if wa_session_path.exists():
        try:
            with open(wa_session_path, 'r', encoding='utf-8') as f:
                wa_data = json.load(f)
                wa_session_active = bool(wa_data.get('session') or wa_data.get('status') == 'connected')
            logger.debug(f"✅ WhatsApp Session Status: {'Active' if wa_session_active else 'Inactive'}")
        except Exception as e:
            logger.error(f"❌ Failed to read WA session: {e}")

    # 4. BUILD JSON RESPONSE
    response_data = {
        # Basic Identity (.env)
        "default_user_name": get_val("DEFAULT_USER_NAME"),
        "default_user_id":   get_val("DEFAULT_USER_ID"),
        "email_address": get_val("EMAIL_ADDRESS"),
        
        # Communications (.env)
        "telegram_bot_token": get_val("TELEGRAM_BOT_TOKEN"),
        "telegram_mode": get_val("TELEGRAM_MODE", "polling"),
        "slack_bot_token": get_val("SLACK_BOT_TOKEN"),
        "slack_signing_secret": get_val("SLACK_SIGNING_SECRET"),
        "discord_bot_token": get_val("DISCORD_BOT_TOKEN"),
        
        # Email (.env)
        "smtp_server": get_val("SMTP_SERVER"),
        "smtp_port": get_val("SMTP_PORT"),
        "smtp_user": get_val("SMTP_USER"),
        "smtp_pass": get_val("SMTP_PASS"),
        "smtp_from_name": get_val("SMTP_FROM_NAME"),
        
        # Local AI (.env)
        "model_path": get_val("MODEL_PATH"),
        "llama_ctx_size": get_val("LLAMA_CTX_SIZE", "16000"),
        "llama_threads": get_val("LLAMA_THREADS", "6"),
        "llama_temp": get_val("LLAMA_TEMP", "0.7"),
        "llama_top_p": get_val("LLAMA_TOP_P", "0.9"),
        
        # AI Provider (.env)
        "ai_provider": get_val("AI_PROVIDER", "local"),
        
        # Cloud Keys (.env)
        "openai_api_key": get_val("OPENAI_API_KEY"),
        "openai_model": get_val("CLOUD_MODEL_OPENAI", "gpt-4o-mini"),
        "anthropic_api_key": get_val("ANTHROPIC_API_KEY"),
        "anthropic_model": get_val("CLOUD_MODEL_ANTHROPIC", "claude-3-5-sonnet-20241022"),
        "groq_api_key": get_val("GROQ_API_KEY"),
        "groq_model": get_val("CLOUD_MODEL_GROQ", "llama-3.3-70b-versatile"),

        # 🔥 User Identity Fields (From JSON)
        "user_role": user_identity.get("owner", {}).get("role"),
        "user_preferences": user_identity.get("owner", {}).get("preferences"),
        "ai_name": user_identity.get("ai_profile", {}).get("name"),
        "ai_persona": user_identity.get("ai_profile", {}).get("base_persona"),
        "ai_tone": user_identity.get("ai_profile", {}).get("tone"),
        "ai_signature": user_identity.get("ai_profile", {}).get("signature"),
        "ai_rules": "\n".join(user_identity.get("ai_profile", {}).get("rules", [])),

        # 🔥 WhatsApp Session Indicator
        "whatsapp_session_active": wa_session_active
    }
    
    # 🔥 CRITICAL: Add cache-busting headers to prevent browser caching
    response = jsonify(response_data)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response
@app.route("/api/internal/save-config", methods=["POST"])
def save_configuration():
    import json
    import fcntl
    from dotenv import dotenv_values, load_dotenv  # ← Added load_dotenv import

    data = request.json
    
    # ✅ UPDATED: Save .env to DATA_DIR (Writable)
    env_path = DATA_DIR / ".env"
    
    if not env_path.exists():
        # Create it if missing
        try:
            env_path.touch()
        except Exception as e:
            return jsonify({"success": False, "error": f"Could not create .env: {str(e)}"}), 500

    logger.info(f"🔒 Starting atomic save to {env_path}...")
    
    try:
        with open(env_path, "r+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            logger.debug("🔒 Lock acquired.")
            
            current_env = dotenv_values(stream=f)
            logger.debug(f"📖 Loaded {len(current_env)} variables from disk.")
            
            # Standard Mapping
            mapping = {
                "default_user_name": "DEFAULT_USER_NAME",
                "default_user_id":   "DEFAULT_USER_ID",   # ← wizard persists this
                "default_user_id": "DEFAULT_USER_ID",
                "email_address": "EMAIL_ADDRESS",
                "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
                "telegram_mode": "TELEGRAM_MODE",
                "slack_bot_token": "SLACK_BOT_TOKEN",
                "slack_signing_secret": "SLACK_SIGNING_SECRET",
                "discord_bot_token": "DISCORD_BOT_TOKEN",
                "smtp_server": "SMTP_SERVER",
                "smtp_port": "SMTP_PORT",
                "smtp_user": "SMTP_USER",
                "smtp_pass": "SMTP_PASS",
                "smtp_from_name": "SMTP_FROM_NAME",
                "llama_ctx_size": "LLAMA_CTX_SIZE",
                "llama_threads": "LLAMA_THREADS",
                "llama_temp": "LLAMA_TEMP",
                "ai_provider": "AI_PROVIDER",
                "openai_api_key": "OPENAI_API_KEY",
                "openai_model": "CLOUD_MODEL_OPENAI",
                "anthropic_api_key": "ANTHROPIC_API_KEY",
                "anthropic_model": "CLOUD_MODEL_ANTHROPIC",
                "groq_api_key": "GROQ_API_KEY",
                "groq_model": "CLOUD_MODEL_GROQ"
            }
            
            changes_made = 0
            new_model_filename = None

            # 1. Process Standard Fields
            for form_key, env_key in mapping.items():
                if form_key in data and data[form_key] is not None:
                    new_val = str(data[form_key]).strip()
                    if not new_val: continue
                    
                    # Sensitive Key Filter
                    if any(k in env_key for k in ["KEY", "TOKEN", "SECRET", "PASS"]):
                        if new_val.lower() in ["local", "not set", "undefined", "null", "none", "placeholder"]:
                            continue
                    
                    old_val = current_env.get(env_key, "")
                    if old_val != new_val:
                        current_env[env_key] = new_val
                        changes_made += 1
                        logger.info(f"✏️ Updated {env_key}")

            # 2. 🔥 SPECIAL LOGIC: Sync All Model Variables
            if "model_path" in data and data["model_path"]:
                new_model_filename = str(data["model_path"]).strip()
                old_model = current_env.get("MODEL_PATH", "")
                if old_model: old_model = Path(old_model).name
                
                if new_model_filename != old_model:
                    logger.info(f"🔄 Model Change Detected: {old_model} -> {new_model_filename}")
                    model_keys = ["MODEL_PATH", "MODEL_NAME", "PLANNER_MODEL_NAME", "CHAT_MODEL_NAME"]
                    for key in model_keys:
                        if current_env.get(key) != new_model_filename:
                            current_env[key] = new_model_filename
                            changes_made += 1
                            logger.info(f"✅ Synced {key} = {new_model_filename}")
            
            if "llama_top_p" in data and data["llama_top_p"]:
                 val = str(data["llama_top_p"]).strip()
                 if current_env.get("LLAMA_TOP_P") != val:
                     current_env["LLAMA_TOP_P"] = val
                     changes_made += 1

            # 3. Atomic Write
            if changes_made > 0:
                f.seek(0)
                f.truncate()
                content_lines = [f"{key}={value}" for key, value in current_env.items() if value is not None]
                f.write("\n".join(content_lines) + "\n")
                f.flush()
                os.fsync(f.fileno())
                logger.info(f"✅ .env Save complete. {changes_made} variables updated.")
                
                # 🔥 CRITICAL FIX: Force reload env with override so new values take effect IMMEDIATELY
                load_dotenv(env_path, override=True)
                logger.info("🔄 Environment reloaded with override=True - new config values now active")
            else:
                logger.info("ℹ️ No changes detected.")

            # 4. Save User Identity JSON
            # ✅ UPDATED: Use global CONFIG_DIR
            identity_fields = ['user_role', 'user_preferences', 'ai_name', 'ai_persona', 'ai_tone', 'ai_signature', 'ai_rules']
            if any(k in data for k in identity_fields):
                try:
                    identity_path = CONFIG_DIR / "user_identity.json"
                    if identity_path.exists():
                        with open(identity_path, 'r', encoding='utf-8') as f:
                            identity_data = json.load(f)
                    else:
                        identity_data = {"owner": {}, "ai_profile": {}}
                    
                    if data.get('default_user_name'): identity_data['owner']['name'] = data['default_user_name']
                    if data.get('user_role'): identity_data['owner']['role'] = data['user_role']
                    if data.get('user_preferences'): identity_data['owner']['preferences'] = data['user_preferences']
                    if data.get('ai_name'): identity_data['ai_profile']['name'] = data['ai_name']
                    if data.get('ai_persona'): identity_data['ai_profile']['base_persona'] = data['ai_persona']
                    if data.get('ai_tone'): identity_data['ai_profile']['tone'] = data['ai_tone']
                    if data.get('ai_signature'): identity_data['ai_profile']['signature'] = data['ai_signature']
                    if data.get('ai_rules'):
                        identity_data['ai_profile']['rules'] = [r.strip() for r in data['ai_rules'].split('\n') if r.strip()]
                    
                    with open(identity_path, 'w', encoding='utf-8') as f:
                        json.dump(identity_data, f, indent=2)
                    logger.info("✅ User Identity JSON updated successfully.")
                except Exception as e:
                    logger.error(f"❌ Failed to update user_identity.json: {e}")

            return jsonify({
                "success": True,
                "message": f"Configuration saved successfully ({changes_made} changes)."
            })

    except Exception as e:
        logger.error(f"💥 Critical error saving .env: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
@app.route("/api/internal/available-models", methods=["GET"])
def list_available_models():
    import os
    from dotenv import load_dotenv
    
    # 1. Force reload .env from Writable Dir to get latest selection
    env_file_path = DATA_DIR / ".env"
    if env_file_path.exists():
        load_dotenv(env_file_path, override=True)
    else:
        load_dotenv(override=True)
    
    models = []
    seen_filenames = set() # Prevent duplicates if user copies bundled model to home

    # --- LOCATION 1: BUNDLED MODELS (Read-Only) ---
    if getattr(sys, 'frozen', False):
        bundle_base = Path(sys._MEIPASS)
    else:
        bundle_base = Path(__file__).resolve().parent.parent
    
    bundle_models_dir = bundle_base / "models"
    
    if bundle_models_dir.exists():
        logger.info(f"📦 Scanning Bundled Models: {bundle_models_dir}")
        for f in sorted(bundle_models_dir.glob("*.gguf")):
            size_gb = f.stat().st_size / (1024**3)
            is_active = False # Check later
            
            models.append({
                "filename": f.name,
                "size_gb": f"{size_gb:.2f} GB",
                "active": False, # Will update below
                "path": str(f),
                "source": "bundled",
                "writable": False
            })
            seen_filenames.add(f.name)

    # --- LOCATION 2: USER MODELS (Writable) ---
    user_models_dir = DATA_DIR / "models"
    user_models_dir.mkdir(parents=True, exist_ok=True) # Ensure it exists
    
    if user_models_dir.exists():
        logger.info(f"👤 Scanning User Models: {user_models_dir}")
        for f in sorted(user_models_dir.glob("*.gguf")):
            if f.name in seen_filenames:
                continue # Skip if already found in bundle
            
            size_gb = f.stat().st_size / (1024**3)
            models.append({
                "filename": f.name,
                "size_gb": f"{size_gb:.2f} GB",
                "active": False,
                "path": str(f),
                "source": "user",
                "writable": True
            })

    # --- CHECK ACTIVE MODEL ---
    env_model_path = os.getenv("MODEL_PATH", "")
    active_filename = ""
    if env_model_path:
        active_filename = Path(env_model_path).name
        
        # Mark the active model in our list
        for model in models:
            if model["filename"] == active_filename:
                model["active"] = True
                break
    
    logger.info(f"✅ Found {len(models)} total models. Active: {active_filename}")
    
    if not models:
        return jsonify([{"error": "No .gguf models found in bundle or user directory.", "active": False}])
        
    return jsonify(models)

@app.route("/api/internal/restart-llm", methods=["POST"])
def restart_llm():
    """Restarts llama-server with FULL environment inheritance."""
    import subprocess, time, os as os_mod
    from dotenv import load_dotenv
    
    logger.warning("⚠️ Restarting LLM Server requested...")
    
    # Reload .env from writable DATA_DIR with override
    env_file_path = DATA_DIR / ".env"
    if env_file_path.exists():
        load_dotenv(env_file_path, override=True)
    
    # Kill existing process (cross-platform)
    kill_process_by_name("llama-server")
    time.sleep(1)
    
    # Get MODEL_PATH
    model_path = os.getenv("MODEL_PATH", "")
    if not model_path:
        return jsonify({"error": "MODEL_PATH not set"}), 400
    
    # Resolve paths
    if getattr(sys, 'frozen', False):
        bundle_root = Path(sys._MEIPASS)
    else:
        bundle_root = BASE_DIR
    
    # Resolve model file
    model_path_obj = Path(model_path)
    if not model_path_obj.is_absolute():
        user_model = DATA_DIR / "models" / model_path
        model_file = user_model if user_model.exists() else bundle_root / "models" / model_path
    else:
        model_file = model_path_obj
    
    # Locate binary
    llama_bin = bundle_root / "llama.cpp" / "build" / "bin" / "llama-server"
    if not llama_bin.exists():
        llama_bin = bundle_root / "llama.cpp" / "llama-server"
    
    if not llama_bin.exists() or not model_file.exists():
        return jsonify({"error": "Binary or model not found"}), 400
    
    # 🔥 CRITICAL: Prepare environment with LD_LIBRARY_PATH/PATH
    env = os.environ.copy()
    lib_dir = str(bundle_root / "lib")
    
    if sys.platform == "win32":
        # Windows: Add to PATH so DLLs are found
        current_path = env.get("PATH", "")
        env["PATH"] = f"{lib_dir};{current_path}" if current_path else lib_dir
        logger.info(f"🔧 PATH updated for Windows DLLs")
    else:
        # Linux: Use LD_LIBRARY_PATH
        current_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{lib_dir}:{current_ld}" if current_ld else lib_dir
        logger.info(f"🔧 LD_LIBRARY_PATH={env['LD_LIBRARY_PATH'][:150]}...")
    
    # Build command (NO --keep-alive)
    cmd = [
        str(llama_bin), "-m", str(model_file),
        "--port", "8080", "--ctx-size", os.getenv("LLAMA_CTX_SIZE", "16000"),
        "--threads", os.getenv("LLAMA_THREADS", "6"), "--host", "127.0.0.1",
        "--temp", os.getenv("LLAMA_TEMP", "0.4"), "--top-p", os.getenv("LLAMA_TOP_P", "0.9"),
        "--reasoning", "off", "--no-warmup"
    ]
    
    # Spawn with signal isolation
    log_path = DATA_DIR / "logs" / "llama_server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    DEVNULL = open(os_mod.devnull, 'rb')
    
    if sys.platform == "win32":
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=open(log_path, 'a'),
            stderr=subprocess.STDOUT, env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        proc = subprocess.Popen(
            cmd, stdin=DEVNULL, stdout=open(log_path, 'a'),
            stderr=subprocess.STDOUT, env=env,
            preexec_fn=os_mod.setsid
        )
    
    logger.info(f"✅ Restarted llama-server (PID: {proc.pid})")
    return jsonify({"message": f"Restarted (PID: {proc.pid})", "pid": proc.pid})

@app.route("/api/internal/chat-history", methods=["GET"])
def get_chat_history():
    """Loads conversation history for a specific user/chat ID."""
    user_id = request.args.get('user_id', 'admin_user')
    logger.info(f"🔍 API Request: Loading history for user='{user_id}'")
    
    try:
        from app.memory_functions import get_recent_chat_history
        history = get_recent_chat_history(user_id, limit=50)
        logger.info(f"✅ Loaded {len(history)} messages for {user_id}")
        if not history:
            logger.warning(f"⚠️ History is empty for {user_id}. Check file content.")
        return jsonify({"messages": history})
    except Exception as e:
        logger.error(f"❌ Error loading history: {e}", exc_info=True)
        return jsonify({"error": str(e), "messages": []}), 500

@app.route("/api/tools/blaster", methods=["POST"])
def run_campaign_blaster():
    import subprocess
    data = request.json
    platform = data.get('platform', 'whatsapp')
    csv_path = data.get('csv_path')
    subject = data.get('subject', '')
    content = data.get('content', '')
    
    # ✅ UPDATED: Scripts are in the bundle (read-only), but CSV path is user-provided
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent.parent
        
    scripts_dir = base_dir / "scripts"
    
    try:
        if platform == 'whatsapp':
            cmd = ["python3", str(scripts_dir / "bulk_whatsapp.py"), "--csv", csv_path, "--message", content]
            script_name = "bulk_whatsapp.py"
        elif platform == 'email':
            cmd = ["python3", str(scripts_dir / "bulk_mailer.py"), "--csv", csv_path, "--subject", subject, "--body", content]
            script_name = "bulk_mailer.py"
        else:
            return jsonify({"error": "Platform not supported"}), 400

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            return jsonify({"status": "success", "output": result.stdout, "script": script_name})
        else:
            return jsonify({"status": "failed", "error": result.stderr, "script": script_name}), 500
            
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Script timed out after 60s"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === 📅 AGENDA DATA (Fixed Paths) ===

@app.route("/api/internal/agenda-data", methods=["GET"])
def get_agenda_data():
    """Returns all events from all tenant agendas formatted for FullCalendar."""
    events = []
    
    # ✅ Use global AGENDAS_DIR (defined at module top)
    agenda_dir = AGENDAS_DIR
    
    # Fallback for dev if not created yet
    if not agenda_dir.exists():
        if getattr(sys, 'frozen', False):
            base_dir = Path(sys._MEIPASS)
        else:
            base_dir = Path(__file__).resolve().parent.parent
        agenda_dir = base_dir / "data" / "agendas"
        agenda_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"📅 Agenda API: Scanning {agenda_dir}...")

    if not agenda_dir.exists():
        logger.error(f"❌ Agenda directory missing: {agenda_dir}")
        return jsonify([])

    try:
        # Scan for BOTH patterns: *_agenda.json AND agenda_*.json
        json_files = list(agenda_dir.glob("*.json"))
        logger.info(f"📂 Found {len(json_files)} agenda files: {[f.name for f in json_files]}")
        
        for file in json_files:
            # Handle both "hexa_agenda.json" and "agenda_hexa.json" patterns
            stem = file.stem
            if stem.endswith("_agenda"):
                tenant_id = stem.replace("_agenda", "")
            elif stem.startswith("agenda_"):
                tenant_id = stem.replace("agenda_", "")
            else:
                tenant_id = stem  # Fallback
            
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"❌ Corrupt JSON in {file}: {e}")
                continue
            
            # data format: { "2026-03-25": [ { "time": "15:00", "status": "booked", ... }, ... ] }
            for date_str, slots in data.items():
                if not isinstance(slots, list): 
                    continue
                for slot in slots:
                    if slot.get('status') != 'booked': 
                        continue
                    
                    time_str = slot.get('time', '09:00')
                    iso_start = f"{date_str}T{time_str}:00"
                    
                    # Calculate end time (1 hour default)
                    try:
                        h, m = map(int, time_str.split(':'))
                        end_h = h + 1
                        if end_h >= 24: 
                            end_h = 23
                        iso_end = f"{date_str}T{end_h:02d}:{m:02d}:00"
                    except:
                        iso_end = iso_start

                    events.append({
                        "id": slot.get('meeting_id', f"{tenant_id}_{date_str}_{time_str}"),
                        "title": f"{slot.get('meeting_type', 'Meeting').title()} - {slot.get('user_name', 'Unknown')}",
                        "start": iso_start,
                        "end": iso_end,
                        "backgroundColor": "#6366f1" if tenant_id == "hexa" else "#10b981",
                        "borderColor": "#ffffff",
                        "extendedProps": {
                            "tenant": tenant_id,
                            "phone": slot.get('user_phone', 'N/A'),
                            "notes": slot.get('notes', ''),
                            "meeting_id": slot.get('meeting_id', '')
                        }
                    })
        
        logger.info(f"🚀 Agenda API: Returning {len(events)} events to frontend.")
        return jsonify(events)
        
    except Exception as e:
        logger.error(f"💥 Critical Error in Agenda API: {e}", exc_info=True)
        return jsonify([])
# === 📡 DAEMON STATUS (Heartbeat Based) ===

@app.route("/api/internal/daemon-status", methods=["GET"])
def get_daemon_status():
    """Returns unified status/logs from all communication daemons."""
    status = {
        "whatsapp": {"status": "offline", "queue": 0, "last_activity": "N/A"},
        "telegram": {"status": "offline", "last_activity": "N/A"},
        "email": {"status": "offline", "last_activity": "N/A"},
        "slack": {"status": "offline", "last_activity": "N/A"},
        "discord": {"status": "offline", "last_activity": "N/A"},
        "recent_logs": []
    }
    
    daemons = ["whatsapp", "telegram", "email", "slack", "discord"]
    current_time = time.time()
    
    for name in daemons:
        # ✅ UPDATED: Use global DATA_DIR
        heartbeat_file = DATA_DIR / f"daemon_status_{name}.json"
        
        if heartbeat_file.exists():
            try:
                with open(heartbeat_file, 'r') as f:
                    data = json.load(f)
                last_seen = data.get('timestamp', 0)
                if current_time - last_seen < 15:
                    status[name]["status"] = "online"
                    status[name]["pid"] = data.get('pid')
                    status[name]["last_activity"] = datetime.fromtimestamp(last_seen).strftime('%H:%M:%S')
                else:
                    status[name]["status"] = "stale"
            except Exception as e:
                logger.warning(f"Error reading heartbeat for {name}: {e}")
                status[name]["status"] = "error"

    # WhatsApp Queue Specifics
    wa_queue = DATA_DIR / "whatsapp_outbound_queue.json"
    if wa_queue.exists():
        try:
            with open(wa_queue, 'r') as f:
                queue = json.load(f)
            status["whatsapp"]["queue"] = len([x for x in queue if x.get('status') == 'pending'])
            status["whatsapp"]["sent_total"] = len([x for x in queue if x.get('status') == 'sent'])
        except: pass

    # Recent Logs
    log_file = LOGS_DIR / "app.log"
    if log_file.exists():
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()[-50:]
                relevant = [l.strip() for l in lines if any(k in l for k in ["WhatsApp", "Telegram", "Email", "Daemon", "Queue", "send_"])]
                status["recent_logs"] = relevant[-15:]
        except: pass

    return jsonify(status)

# === 🎛️ DAEMON CONTROL LOGIC ===
DAEMON_PROCESSES = {}

def is_whatsapp_session_valid():

    # ── Primary: Query Electron's whatsapp-window.js via IPC ─────────────
    try:
        resp = requests.get(f'{_WA_IPC_BASE}/status', timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            # ✅ CRITICAL: session valid ONLY if user enabled AND logged in
            user_enabled = bool(data.get('userEnabled', False))
            logged_in = bool(data.get('loggedIn', False))
            return user_enabled and logged_in
    except requests.exceptions.ConnectionError:
        # Electron IPC server not reachable — fall through to legacy check
        pass
    except requests.exceptions.Timeout:
        logger.warning('⚠️ WA IPC status check timed out')
    except Exception as e:
        logger.warning(f'⚠️ WA IPC status check failed: {e}')

    # ── Fallback: Legacy heartbeat file (dev mode without Electron) ─────
    heartbeat_file = DATA_DIR / 'daemon_status_whatsapp.json'
    if not heartbeat_file.exists():
        return False
    try:
        with open(heartbeat_file, 'r') as f:
            data = json.load(f)
        last_seen = data.get('timestamp', 0)
        # Stale if no heartbeat in 15 seconds
        if (time.time() - last_seen) > 15:
            return False
        pid = data.get('pid')
        if pid:
            import psutil
            try:
                return psutil.Process(pid).is_running()
            except psutil.NoSuchProcess:
                pass
        return False
    except Exception as e:
        logger.warning(f'⚠️ Could not verify WA session via heartbeat: {e}')
        return False

@app.route("/api/internal/daemon-control", methods=["POST"])
def control_daemon():
    """
    Start/stop communication daemons.

    WhatsApp is now managed by Electron (whatsapp-window.js) — we talk to it
    via HTTP on port 5002 instead of spawning a Python subprocess.

    All other daemons (telegram, email, slack, discord) behave exactly as before.
    """
    data = request.json
    if not data:
        return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

    daemon_name = data.get('daemon')
    action      = data.get('action')

    if not daemon_name or action not in ['start', 'stop']:
        return jsonify({'success': False, 'error': 'Invalid request'}), 400
# =========================================================================
    # WHATSAPP — Baileys daemon
    # =========================================================================
    if daemon_name == 'whatsapp':
        if action == 'start':

            # ── Force-kill any existing daemon first ─────────────────────────
            # Critical on Fedora: pkill alone doesn't reliably kill processes
            # in separate sessions. We use multiple strategies.
            _kill_baileys()

            # Brief wait for port to free — critical so the IPC check below
            # doesn't find a zombie process from the previous session.
            import socket as _sock
            for _ in range(6):  # up to 3s
                try:
                    s = _sock.socket(); s.settimeout(0.3)
                    if s.connect_ex(('127.0.0.1', 5002)) != 0:
                        s.close()
                        break  # port free
                    s.close()
                except Exception:
                    break
                time.sleep(0.5)

            # ── Find Baileys script ──────────────────────────────────────────
            daemon_script_str = os.environ.get('LMIM_BAILEYS_SCRIPT', '')
            if daemon_script_str and Path(daemon_script_str).exists():
                daemon_script = Path(daemon_script_str)
                base_dir = daemon_script.parent.parent
            elif getattr(sys, 'frozen', False):
                base_dir = Path(sys._MEIPASS)
                daemon_script = base_dir.parent / 'daemons' / 'whatsapp-baileys.js'
            else:
                base_dir = Path(__file__).resolve().parent.parent
                daemon_script = base_dir / 'daemons' / 'whatsapp-baileys.js'

            if not daemon_script.exists():
                return jsonify({'success': False, 'error': f'Baileys script not found: {daemon_script}'}), 404

            # ── Find node — use env var set by run_app_backend.py ────────────
            # run_app_backend.py already verified the node binary with --version.
            # We trust that result. If it somehow isn't set, fall back ourselves.
            node_bin = os.environ.get('LMIM_NODE_BIN', '')
            if not node_bin:
                # run_app_backend didn't run (e.g., dev mode without launcher)
                # Try shutil.which first (cross-distro, SELinux-safe)
                import shutil as _shutil
                node_bin = _shutil.which('node') or _shutil.which('nodejs') or ''
                if not node_bin:
                    for c in ['/usr/bin/node', '/usr/local/bin/node',
                              '/usr/bin/nodejs', '/usr/local/bin/nodejs']:
                        if Path(c).exists():
                            node_bin = c
                            break
                if not node_bin:
                    node_bin = 'node'  # last resort

            node_modules = os.environ.get('LMIM_NODE_MODULES', str(base_dir / 'node_modules'))
            data_dir     = Path.home() / '.lmim_os'
            log_dir      = data_dir / 'logs'
            log_dir.mkdir(parents=True, exist_ok=True)
            baileys_log_path = log_dir / 'baileys.log'

            env = os.environ.copy()
            env['LMIM_DATA_DIR']    = str(data_dir)
            env['LMIM_WA_IPC_PORT'] = '5002'
            env['NODE_PATH']        = node_modules
            env.setdefault('DISPLAY', ':0')
            env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')

            # Strip AppImage bundled lib dirs from LD_LIBRARY_PATH before
            # spawning Baileys. PyInstaller's bootloader prepends _MEIPASS to
            # LD_LIBRARY_PATH which includes Ubuntu-built libcrypto.so.3.
            # System node on Fedora requires OPENSSL_3.4.0 and crashes when it
            # finds the Ubuntu version first. Baileys uses system node only —
            # it must inherit system libs, not the AppImage bundle libs.
            _ldp = env.get('LD_LIBRARY_PATH', '')
            if _ldp:
                _clean = [p for p in _ldp.split(':')
                          if p
                          and '/tmp/.mount_' not in p
                          and '/resources/backend' not in p]
                if _clean:
                    env['LD_LIBRARY_PATH'] = ':'.join(_clean)
                else:
                    env.pop('LD_LIBRARY_PATH', None)
            logger.info(f'🔧 Baileys LD_LIBRARY_PATH: {env.get("LD_LIBRARY_PATH", "EMPTY (clean)")}')

            logger.info(f'🚀 Spawning Baileys: {node_bin} {daemon_script}')

            try:
                baileys_log = open(baileys_log_path, 'a', encoding='utf-8')
                proc = subprocess.Popen(
                    [node_bin, str(daemon_script)],
                    cwd=str(base_dir),
                    env=env,
                    stdout=baileys_log,
                    stderr=baileys_log,       # log to file — NOT DEVNULL
                    start_new_session=True,
                )
            except (FileNotFoundError, PermissionError, OSError) as e:
                # Bundled node failed (SELinux, missing binary, etc.)
                # Try system node as fallback
                logger.warning(f'⚠️  Primary node failed ({e}) — trying system node fallback')
                import shutil as _shutil2
                system_node = _shutil2.which('node') or _shutil2.which('nodejs')
                if not system_node:
                    logger.error('❌ No working Node.js found on this system')
                    return jsonify({
                        'success': False,
                        'error': (
                            f'Node.js not executable: {node_bin}. '
                            'Install Node.js: sudo dnf install nodejs (Fedora) '
                            'or sudo apt install nodejs (Ubuntu/Debian)'
                        ),
                    }), 500
                logger.info(f'🔄 Retrying with system node: {system_node}')
                try:
                    baileys_log = open(baileys_log_path, 'a', encoding='utf-8')
                    proc = subprocess.Popen(
                        [system_node, str(daemon_script)],
                        cwd=str(base_dir),
                        env=env,
                        stdout=baileys_log,
                        stderr=baileys_log,
                        start_new_session=True,
                    )
                    # Update env var for future calls in this session
                    os.environ['LMIM_NODE_BIN'] = system_node
                    logger.info(f'✅ Fallback node working: {system_node}')
                except Exception as e2:
                    logger.error(f'❌ Fallback node also failed: {e2}')
                    return jsonify({'success': False, 'error': str(e2)}), 500

            DAEMON_PROCESSES['whatsapp'] = proc
            logger.info(f'✅ Baileys daemon started (PID: {proc.pid})')

            # ── Wait for IPC to come up (up to 12s) ─────────────────────────
            # 12s because broken-session path: clear auth → reconnect → QR takes ~10s
            ipc_up = False
            for _ in range(24):    # 24 × 0.5s = 12s
                time.sleep(0.5)

                # Check if proc died
                if proc.poll() is not None:
                    try:
                        baileys_log.flush()
                        log_tail = baileys_log_path.read_text(errors='replace').splitlines()[-30:]
                        log_excerpt = '\n'.join(log_tail)
                    except Exception:
                        log_excerpt = '(log unavailable)'
                    logger.error(
                        f'❌ Baileys died early (code {proc.returncode})\n{log_excerpt}'
                    )
                    return jsonify({
                        'success': False,
                        'error': (
                            f'Baileys exited (code {proc.returncode}). '
                            f'Check {baileys_log_path} for details.'
                        ),
                        'log_tail': log_excerpt,
                    }), 500

                # Check IPC port
                try:
                    s = _sock.socket()
                    s.settimeout(0.3)
                    if s.connect_ex(('127.0.0.1', 5002)) == 0:
                        s.close()
                        ipc_up = True
                        break
                    s.close()
                except Exception:
                    pass

            if not ipc_up:
                # Proc is alive but IPC not up yet — still loading / reconnecting.
                # Don't kill it. Return started + tell frontend to keep polling.
                logger.warning(f'⚠️  Baileys IPC not ready after 12s (proc alive)')
                return jsonify({
                    'success':   True,
                    'message':   'WhatsApp starting — scan QR when it appears.',
                    'hasQR':     False,
                    'pid':       proc.pid,
                    'ipc_ready': False,
                    'poll':      True,   # tells frontend: keep polling daemon-states
                })

            # IPC is up
            try:
                resp  = requests.get(f'{_WA_IPC_BASE}/status', timeout=2)
                wa    = resp.json() if resp.status_code == 200 else {}
                has_qr = bool(wa.get('hasQR', False))
                logged_in = bool(wa.get('loggedIn', False))
                if logged_in:
                    msg = 'WhatsApp connected.'
                elif has_qr:
                    msg = 'WhatsApp running — scan QR to link.'
                else:
                    msg = 'WhatsApp starting — QR will appear shortly.'
                return jsonify({
                    'success':   True,
                    'message':   msg,
                    'hasQR':     has_qr,
                    'loggedIn':  logged_in,
                    'pid':       proc.pid,
                    'ipc_ready': True,
                    'poll':      not (has_qr or logged_in),
                })
            except Exception:
                return jsonify({
                    'success':   True,
                    'message':   'WhatsApp daemon started.',
                    'hasQR':     False,
                    'pid':       proc.pid,
                    'ipc_ready': True,
                    'poll':      True,
                })

        elif action == 'stop':
            _kill_baileys()
            return jsonify({'success': True, 'message': 'WhatsApp stopped.'})

    # =========================================================================
    # ALL OTHER DAEMONS — original Python subprocess logic (unchanged)
    # =========================================================================
    
    # UPDATED: Daemons are in the bundle (read-only)
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent.parent
        
    daemon_script = base_dir / "daemons" / f"{daemon_name}_daemon.py"

    if not daemon_script.exists():
        return jsonify({"success": False, "error": f"Daemon script not found: {daemon_name}"}), 404

    try:
        if action == 'stop':
            proc = DAEMON_PROCESSES.get(daemon_name)
            if proc:
                pid = proc.pid if hasattr(proc, 'pid') else proc.get('pid')
                if pid:
                    try:
                        if hasattr(proc, 'terminate'):
                            proc.terminate()
                        else:
                            os.kill(pid, signal.SIGTERM)
                        time.sleep(1)
                        if hasattr(proc, 'kill'):
                            proc.kill()
                        else:
                            os.kill(pid, signal.SIGKILL)
                        del DAEMON_PROCESSES[daemon_name]
                        logger.info(f"🛑 Stopped {daemon_name} (PID: {pid})")
                        return jsonify({"success": True, "message": f"{daemon_name} stopped."})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 500
            # Aggressive fallback
            subprocess.run(["pkill", "-f", f"{daemon_name}_daemon.py"], check=False)
            return jsonify({"success": True, "message": f"{daemon_name} stopped (aggressive)."})

        elif action == 'start':
            # Check if already running
            proc = DAEMON_PROCESSES.get(daemon_name)
            if proc:
                pid = proc.pid if hasattr(proc, 'pid') else proc.get('pid')
                is_alive = False
                if hasattr(proc, 'poll'):
                    is_alive = proc.poll() is None
                else:
                    try:
                        os.kill(pid, 0)
                        is_alive = True
                    except OSError:
                        pass
                
                if is_alive:
                    return jsonify({
                        "success": False, 
                        "error": f"{daemon_name} already running (PID: {pid})."
                    }), 400

            # Build command
            python_bin = os.environ.get('LMIM_PYTHON_BIN', 'python3')
            
            # Fallback: scan common venv locations if env var not set
            if python_bin == 'python3':
                for venv_candidate in [
                    base_dir / 'venv_build' / 'bin' / 'python3',
                    base_dir / 'venv' / 'bin' / 'python3',
                    base_dir / '.venv' / 'bin' / 'python3',
                ]:
                    if venv_candidate.exists():
                        python_bin = str(venv_candidate)
                        logger.info(f"🐍 Found venv python: {python_bin}")
                        break

            logger.info(f"🚀 Spawning daemon with: {python_bin}")
            args = [python_bin, str(daemon_script)]

            # Build env: inherit everything + ensure display vars are set
            env = os.environ.copy()
            env['LMIM_DATA_DIR'] = str(DATA_DIR)
            
            # 🔧 CRITICAL: Explicitly propagate PLAYWRIGHT_BROWSERS_PATH
            if 'PLAYWRIGHT_BROWSERS_PATH' in os.environ:
                env['PLAYWRIGHT_BROWSERS_PATH'] = os.environ['PLAYWRIGHT_BROWSERS_PATH']
                logger.info(f"📦 Daemon PLAYWRIGHT_BROWSERS_PATH={env['PLAYWRIGHT_BROWSERS_PATH']}")
            elif getattr(sys, 'frozen', False):
                pw_candidate = Path(sys._MEIPASS) / 'playwright_driver' / 'browser_packages'
                if pw_candidate.exists():
                    env['PLAYWRIGHT_BROWSERS_PATH'] = str(pw_candidate)
                    logger.info(f"📦 Fallback Playwright path: {pw_candidate}")
            
            # Ensure display environment reaches the daemon
            uid = os.getuid() if hasattr(os, 'getuid') else 1000
            env.setdefault('DISPLAY', ':0')
            env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{uid}')
            if 'WAYLAND_DISPLAY' not in env:
                xdg_rt = env.get('XDG_RUNTIME_DIR', f'/run/user/{uid}')
                for wl in ['wayland-0', 'wayland-1']:
                    if Path(xdg_rt, wl).exists():
                        env['WAYLAND_DISPLAY'] = wl
                        break
            
            logger.info(f"🖥️  Daemon env: DISPLAY={env.get('DISPLAY')} "
                       f"WAYLAND_DISPLAY={env.get('WAYLAND_DISPLAY')} "
                       f"XDG_RUNTIME_DIR={env.get('XDG_RUNTIME_DIR')}")
            
            # Spawn daemon with isolated session + full env
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env
            )

            DAEMON_PROCESSES[daemon_name] = proc
            logger.info(f"✅ Started {daemon_name} (PID: {proc.pid})")
            return jsonify({"success": True, "message": f"{daemon_name} started."})

    except Exception as e:
        logger.error(f"❌ Control Error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
        



def _kill_baileys():
    """
    Kill the Baileys daemon using every available method.
    Robust across Ubuntu, Fedora, Arch — handles session isolation and SELinux.
    """
    # 1. Kill tracked proc object
    proc = DAEMON_PROCESSES.get('whatsapp')
    if proc and hasattr(proc, 'poll') and proc.poll() is None:
        try:
            proc.terminate()
            time.sleep(0.3)
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
    if 'whatsapp' in DAEMON_PROCESSES:
        try:
            del DAEMON_PROCESSES['whatsapp']
        except Exception:
            pass
    # pkill by script name — catches orphans from previous sessions
    subprocess.run(['pkill', '-f', 'whatsapp-baileys.js'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Kill whatever is on port 5002 — most reliable cross-distro
    try:
        subprocess.run(['fuser', '-k', '5002/tcp'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    time.sleep(0.5)

@app.route("/api/internal/chat-list", methods=["GET"])
def get_chat_list():
    """Returns a list of all user chat directories."""
    base_dir = MEMORIES_DIR / "users"
    if not base_dir.exists():
        return jsonify([])
    chats = []
    for item in base_dir.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            if item.name.endswith('.json'):
                continue
            chats.append(item.name)
    chats.sort(key=lambda x: (not x.startswith('admin'), x))
    return jsonify(chats)

@app.route("/api/internal/delete-chat", methods=["POST"])
def delete_chat():
    """Delete a chat conversation and its history."""
    import shutil
    data = request.json or {}
    chat_id = data.get('chat_id', '').strip()
    if not chat_id or chat_id == 'admin_user':
        return jsonify({"success": False, "error": "Cannot delete this chat"}), 400
    chat_dir = MEMORIES_DIR / "users" / chat_id
    if not chat_dir.exists():
        return jsonify({"success": True, "message": "Already gone"})
    try:
        shutil.rmtree(chat_dir)
        logger.info(f"🗑️ Deleted chat: {chat_id}")
        return jsonify({"success": True, "message": f"Deleted {chat_id}"})
    except Exception as e:
        logger.error(f"❌ Failed to delete chat {chat_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/internal/daemon-states", methods=["GET"])
def get_daemon_states():

    states = {
        'whatsapp': {'running': False, 'session_valid': False},
        'telegram': {'running': False},
        'email':    {'running': False},
        'slack':    {'running': False},
        'discord':  {'running': False},
    }
 
    # ── WhatsApp: query Baileys IPC (only if daemon was spawned) ─────────────
    try:
        resp = requests.get(f'{_WA_IPC_BASE}/status', timeout=2)
        if resp.status_code == 200:
            wa_data   = resp.json()
            logged_in = bool(wa_data.get('loggedIn', False))
            has_qr    = bool(wa_data.get('hasQR', False))
            states['whatsapp']['running']       = True
            states['whatsapp']['session_valid'] = logged_in
            states['whatsapp']['has_qr']        = has_qr
            states['whatsapp']['phone']         = wa_data.get('phone')
    except requests.exceptions.ConnectionError:
        # Daemon not running — stays running: False
        pass
    except Exception as e:
        logger.debug(f'WA IPC state check: {e}')
    # ── Other daemons: check DAEMON_PROCESSES ────────────────────────────────
    for name in list(DAEMON_PROCESSES.keys()):
        if name == 'whatsapp':
            continue   # handled above
        proc     = DAEMON_PROCESSES[name]
        is_alive = False
        if hasattr(proc, 'poll'):
            if proc.poll() is None:
                is_alive = True
            else:
                del DAEMON_PROCESSES[name]
        elif isinstance(proc, dict):
            pid = proc.get('pid')
            if pid:
                try:
                    os.kill(pid, 0)
                    is_alive = True
                except OSError:
                    del DAEMON_PROCESSES[name]
        if is_alive:
            states[name]['running'] = True
 
    return jsonify(states)
 

@app.route("/api/internal/set-identity", methods=["POST"])
def set_user_identity():
    import json
    # ✅ UPDATED: Use global CONFIG_DIR
    identity_path = CONFIG_DIR / "user_identity.json"
    
    data = request.json
    if not data or "owner" not in data:
        return jsonify({"success": False, "error": "Invalid identity structure"}), 400
        
    try:
        with open(identity_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        logger.info(f"✅ User identity updated: {data['owner'].get('name')}")
        return jsonify({"success": True, "message": "Identity configured successfully"})
    except Exception as e:
        logger.error(f"❌ Error saving identity: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/internal/system-metrics", methods=["GET"])
def get_system_metrics():
    """Returns real-time system resource usage."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        ram_used_gb = mem.used / (1024**3)
        ram_total_gb = mem.total / (1024**3)
        ram_percent = mem.percent
        
        disk_io_start = psutil.disk_io_counters()
        time.sleep(1) 
        disk_io_end = psutil.disk_io_counters()
        read_bytes = disk_io_end.read_bytes - disk_io_start.read_bytes
        write_bytes = disk_io_end.write_bytes - disk_io_start.write_bytes
        total_io_mb_s = (read_bytes + write_bytes) / (1024**2)
        
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        uptime_seconds = time.time() - psutil.boot_time()
        
        return jsonify({
            "cpu": round(cpu_percent, 1),
            "ram_used_gb": round(ram_used_gb, 2),
            "ram_total_gb": round(ram_total_gb, 2),
            "ram_percent": ram_percent,
            "disk_io_mb_s": round(total_io_mb_s, 2),
            "disk_percent": disk_percent,
            "uptime_seconds": round(uptime_seconds, 1)
        })
    except Exception as e:
        logger.error(f"Error fetching system metrics: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ==============================================================================
# === 📦 VERSION CHECK ===
# ==============================================================================

VERSION_CHECK_URL = "https://lmim.tech/version.json"
APP_VERSION       = os.getenv("APP_VERSION", "1.21.0")

def _fetch_remote_version(timeout: int = 6):
    """Fetch version.json from lmim.tech. Returns None on any network/parse error."""
    try:
        req = urllib.request.Request(
            VERSION_CHECK_URL,
            headers={"User-Agent": f"LMIM-OS/{APP_VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.debug(f"Version check fetch failed (non-critical): {e}")
        return None

@app.route("/api/internal/version-check", methods=["GET"])
def version_check():
    """
    Returns version status for the GUI update notification system.
    Always responds — never raises. Offline state is handled gracefully.
    """
    platform_hint = "windows" if sys.platform == "win32" else "linux"
    remote = _fetch_remote_version()

    if remote is None:
        return jsonify({
            "current":          APP_VERSION,
            "latest":           APP_VERSION,
            "update_available": False,
            "critical":         False,
            "notes":            "",
            "downloads":        {},
            "changelog_url":    "",
            "release_date":     "",
            "platform":         platform_hint,
            "offline":          True,
        })

    try:
        # Use simple tuple comparison to avoid requiring 'packaging' as a dep
        def _parse_ver(v):
            return tuple(int(x) for x in str(v).strip().split(".")[:3])

        update_available = _parse_ver(remote["version"]) > _parse_ver(APP_VERSION)
        critical         = bool(remote.get("critical", False))

        # Force critical if installed version is below minimum_version
        min_ver = remote.get("minimum_version", "0.0.0")
        if _parse_ver(APP_VERSION) < _parse_ver(min_ver):
            critical = True

    except Exception as e:
        logger.warning(f"Version comparison failed: {e}")
        update_available = False
        critical         = False

    return jsonify({
        "current":          APP_VERSION,
        "latest":           remote.get("version", APP_VERSION),
        "update_available": update_available,
        "critical":         critical,
        "notes":            remote.get("notes", ""),
        "downloads":        remote.get("downloads", {}),
        "changelog_url":    remote.get("changelog_url", ""),
        "release_date":     remote.get("release_date", ""),
        "platform":         platform_hint,
        "offline":          False,
    })

@app.route("/api/internal/reset-setup", methods=["POST"])
def reset_setup():
    import shutil
    # ✅ UPDATED: Use global CONFIG_DIR and DATA_DIR
    identity_path = CONFIG_DIR / "user_identity.json"
    if identity_path.exists():
        shutil.move(identity_path, identity_path.with_suffix('.json.bak'))
        logger.info(f"✅ Moved identity to {identity_path.with_suffix('.json.bak')}")

    env_path = DATA_DIR / ".env"
    if env_path.exists():
        try:
            with open(env_path, 'r') as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                if not (line.startswith("DEFAULT_USER_NAME=") or line.startswith("DEFAULT_USER_ID=")):
                    new_lines.append(line)
                else:
                    logger.info(f"🗑️ Cleared env var: {line.strip()}")
            with open(env_path, 'w') as f:
                f.writelines(new_lines)
            logger.info("✅ .env defaults cleared.")
        except Exception as e:
            logger.error(f"Failed to clear .env: {e}")

    return jsonify({"success": True})
  
@app.route("/api/debug/raw-tool-test", methods=["POST"])
def debug_raw_tool_test():
    """Minimal prompt to test if model outputs tool calls."""
    data = request.json or {}
    prompt = data.get("prompt", "schedule a meeting")
    
    # Ultra-minimal system prompt for 2B model
    system = f"""You are LMIM. You have tools.
To schedule, output EXACTLY:
[TOOL_CALL]{{"name": "schedule_meeting", "parameters": {{"date": "2026-03-27", "time": "17:00", "user_phone": "+123", "user_name": "Pedro", "meeting_type": "meeting", "tenant_id": "hexa"}}}}[/TOOL_CALL]
Do not explain. Output ONLY the marker."""
    
    try:
        resp = requests.post(
            LOCAL_INFERENCE_URL,
            json={"model": MODEL_NAME, "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ], "temperature": 0.2, "max_tokens": 300},
            timeout=30
        )
        result = resp.json()
        raw = result["choices"][0]["message"]["content"]
        from app.model_interface import _parse_tool_call
        parsed = _parse_tool_call(raw)
        return jsonify({
            "raw_reply": raw,
            "parsed_tool": parsed,
            "success": bool(parsed),
            "model": MODEL_NAME
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
        
        

@app.route("/api/internal/wa-qr", methods=["GET"])
def get_wa_qr():
    """Returns the WhatsApp QR code from Baileys for pairing."""

    # Primary: ask Baileys IPC directly — returns in-memory QR (always current)
    try:
        resp = requests.get(f'{_WA_IPC_BASE}/qr', timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            qr = data.get('qr')
            if qr:
                qr_type = 'dataurl' if qr.startswith('data:') else 'text'
                return jsonify({"ok": True, "qr": qr, "type": qr_type})
    except Exception:
        pass

    # Fallback: read from file — check both possible DATA_DIR locations
    qr_candidates = [
        DATA_DIR / "baileys_qr.txt",
        Path.home() / ".lmim_os" / "baileys_qr.txt",
    ]
    for qr_file in qr_candidates:
        if qr_file.exists():
            try:
                qr_data = qr_file.read_text().strip()
                if qr_data:
                    return jsonify({
                        "ok":   True,
                        "qr":   qr_data,
                        "type": "dataurl" if qr_data.startswith('data:') else "text"
                    })
            except Exception as e:
                logger.warning(f"QR file read error {qr_file}: {e}")

    return jsonify({"ok": False, "qr": None, "message": "QR not available yet"})
# ==============================================================================
# === 📡 WEBHOOKS DE COMUNICACIÓN ===
# ==============================================================================

@app.route("/webhooks/slack/incoming", methods=["POST"])
def slack_incoming_webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON"}), 400
    user_id = f"slack_{data.get('sender')}"
    text = data.get("body")
    logger.info(f"🟣 Slack Webhook: {user_id} - {text[:50]}...")
    try:
        from app.router import route_request
        reply = route_request(text, user_id, source="slack")
        return jsonify({"status": "processed", "reply": reply}), 200
    except Exception as e:
        logger.error(f"Error in Slack Router: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/webhooks/discord/incoming", methods=["POST"])
def discord_incoming_webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON"}), 400
    user_id = f"discord_{data.get('sender')}"
    text = data.get("body")
    logger.info(f"🔵 Discord Webhook: {user_id} - {text[:50]}...")
    try:
        from app.router import route_request
        reply = route_request(text, user_id, source="discord")
        return jsonify({"status": "processed", "reply": reply}), 200
    except Exception as e:
        logger.error(f"Error in Discord Router: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/webhooks/email/incoming", methods=["POST"])
def email_incoming_webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON"}), 400
    sender = data.get("sender")
    subject = data.get("subject")
    body = data.get("body")
    if not sender or not body:
        return jsonify({"error": "Missing sender or body"}), 400
    user_id = f"email_{sender}"
    full_text = f"Subject: {subject}\n{body}"
    logger.info(f"📧 Email Webhook: {user_id} - '{subject}'")
    try:
        from app.router import route_request
        reply = route_request(full_text, user_id, source="email")
        return jsonify({"status": "processed", "reply": reply}), 200
    except Exception as e:
        logger.error(f"Error in Email Router: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/webhooks/telegram/incoming", methods=["POST"])
def telegram_incoming_webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON"}), 400
    user_id = data.get("user_id")
    text = data.get("text")
    if not user_id or not text:
        return jsonify({"error": "Missing user_id or text"}), 400
    logger.info(f"✈️ Telegram Webhook: {user_id} - {text[:50]}...")
    try:
        from app.router import route_request
        reply = route_request(text, user_id, source="telegram")
        return jsonify({"status": "processed", "reply": reply}), 200
    except Exception as e:
        logger.error(f"Error in Telegram Router: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/webhooks/whatsapp/incoming", methods=["POST"])
def whatsapp_incoming_webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON"}), 400
    
    phone = data.get("phone")
    text = data.get("text")
    
    # ✅ NEW: Use chat_name if phone missing (for polling events from background chats)
    chat_name = data.get("chat_name")
    if chat_name and not phone:
        import re
        # Extract phone number from chat name if it looks like one
        match = re.search(r'\+?\d[\d\s\-]{7,}\d', chat_name)
        if match:
            phone = re.sub(r'[^\d+]', '', match.group(0))
            logger.debug(f"🔍 Extracted phone from chat_name: {phone}")
    
    if not phone or not text:
        return jsonify({"error": "Missing phone or text"}), 400
    
    user_id = f"wa_{phone}"
    logger.info(f"📱 WhatsApp Webhook: {user_id} - {text[:50]}...")
    
    try:
        from app.router import route_request
        reply = route_request(text, user_id, source="whatsapp")
        return jsonify({"status": "processed", "reply": reply}), 200
    except Exception as e:
        logger.error(f"Error in WhatsApp Router: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ==============================================================================
# === 🎛️ DAEMON ADOPTION LOGIC ===
# ==============================================================================

def adopt_existing_daemons():
    """Scans heartbeat files for running daemons started by the Orchestrator."""
    import psutil
    daemons = ["whatsapp", "telegram", "email", "slack", "discord"]
    adopted_count = 0
    
    for name in daemons:
        heartbeat_file = DATA_DIR / f"daemon_status_{name}.json"
        if heartbeat_file.exists():
            try:
                with open(heartbeat_file, 'r') as f:
                    data = json.load(f)
                pid = data.get('pid')
                last_seen = data.get('timestamp', 0)
                
                if pid and (time.time() - last_seen) < 15:
                    try:
                        p = psutil.Process(pid)
                        if p.is_running():
                            DAEMON_PROCESSES[name] = {
                                "pid": pid,
                                "psutil_obj": p,
                                "poll": lambda proc=p: None if proc.is_running() else 0,
                                "terminate": lambda proc=p: proc.terminate(),
                                "kill": lambda proc=p: proc.kill()
                            }
                            logger.info(f"🤝 Adopted existing {name} daemon (PID: {pid})")
                            adopted_count += 1
                    except psutil.NoSuchProcess:
                        pass
            except Exception as e:
                logger.warning(f"Could not adopt {name}: {e}")
                
    if adopted_count > 0:
        logger.info(f"✅ Successfully adopted {adopted_count} daemons from Orchestrator.")
    else:
        logger.info("ℹ️ No external daemons found to adopt.")

# ==============================================================================
# === 🔧 PORT MANAGEMENT HELPERS ===
# ==============================================================================

def is_port_in_use(port: int) -> bool:
    """Check if a TCP port is already in use."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def kill_port_5000():
    """Kill any process using port 5000 before Flask starts."""
    import socket
    import psutil
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sock.connect_ex(('localhost', 5000)) == 0:
        logger.warning("⚠️ Port 5000 is in use. Killing stale process...")
        sock.close()
        
        # Find and kill the process
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if 'python' in proc.info['name'].lower() and '5000' in cmdline:
                    logger.info(f"🔪 Killing process {proc.info['pid']} ({proc.info['name']})")
                    proc.terminate()
                    proc.wait(timeout=3)
            except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
                pass
        time.sleep(1)
    else:
        sock.close()

# ==============================================================================
# 🎤 VOICE — Whisper.cpp STT + Piper TTS
# ==============================================================================

def _clean_for_tts(text: str) -> str:
    """Strip markdown, emoji, and tool markers so Piper gets clean prose."""
    import re as _re
    text = _re.sub(r'\[TOOL_CALL\].*?\[/TOOL_CALL\]', '', text, flags=_re.DOTALL)
    text = _re.sub(r'[*_`#>~|]', '', text)
    # Common emoji ranges
    text = _re.sub(r'[\U0001F300-\U0001F9FF\U00002700-\U000027BF'
                   r'\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF]', '', text)
    text = _re.sub(r'[✅❌📅🚀💬🔧📱⚡🛠️🏠☁️📊💾🔍📦🐍🔌📡🎤🔊🔇🔔⚠️]', '', text)
    text = _re.sub(r'\s+', ' ', text).strip()
    return text


def _pcm_to_wav(pcm: bytes, sample_rate: int = 22050) -> bytes:
    """Wrap raw 16-bit mono PCM bytes in a WAV container."""
    import struct
    n_ch, bits = 1, 16
    data_size  = len(pcm)
    byte_rate  = sample_rate * n_ch * bits // 8
    blk_align  = n_ch * bits // 8
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + data_size, b'WAVE',
        b'fmt ', 16, 1, n_ch, sample_rate,
        byte_rate, blk_align, bits,
        b'data', data_size,
    )
    return header + pcm


def _voice_path(rel: str) -> Path:
    """Resolve a path inside the voice/ directory (AppImage-aware)."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'voice' / rel
    return BASE_DIR / 'voice' / rel


@app.route('/api/voice/transcribe', methods=['POST'])
def voice_transcribe():
    """
    STT endpoint. Accepts multipart/form-data with 'audio' field.
    Handles WebM (browser MediaRecorder), OGG, MP3, WAV, FLAC, M4A, AAC.
    Returns: { ok: bool, text: str }
    Requires: voice/bin/whisper-cli + voice/models/stt/ggml-*.bin
    """
    if 'audio' not in request.files:
        return jsonify({'ok': False, 'error': 'No audio file in request (expected field: "audio")'}), 400

    # ── Binary check ─────────────────────────────────────────────────────────
    whisper_bin = _voice_path('bin/whisper-cli')
    if not whisper_bin.exists():
        whisper_bin = _voice_path('bin/main')   # legacy build name
    if not whisper_bin.exists():
        return jsonify({'ok': False,
                        'error': 'whisper-cli not found — expected at voice/bin/whisper-cli'}), 503

    # ── Model check (tiny first for speed; small as quality fallback) ─────────
    model_path = None
    for name in ['ggml-tiny.bin', 'ggml-base.en.bin', 'ggml-base.bin', 'ggml-small.bin']:
        c = _voice_path(f'models/stt/{name}')
        if c.exists():
            model_path = c
            break
    if not model_path:
        return jsonify({'ok': False,
                        'error': 'No Whisper model found in voice/models/stt/. '
                                 'Download ggml-tiny.bin from huggingface.co/ggerganov/whisper.cpp'}), 503

    # ── Temp files ────────────────────────────────────────────────────────────
    tmp_dir = DATA_DIR / 'tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)

    audio_file    = request.files['audio']
    original_name = audio_file.filename or 'audio'
    mime          = (audio_file.content_type or '').split(';')[0].strip()
    ext_map = {
        'audio/webm': '.webm', 'audio/ogg': '.ogg', 'audio/opus': '.opus',
        'audio/wav':  '.wav',  'audio/wave': '.wav', 'audio/x-wav': '.wav',
        'audio/mpeg': '.mp3',  'audio/mp3':  '.mp3',
        'audio/mp4':  '.m4a',  'audio/x-m4a': '.m4a',
        'audio/flac': '.flac', 'audio/aac':  '.aac',
    }
    # Prefer extension from filename, fall back to mime map, fall back to .webm
    suffix  = Path(original_name).suffix or ext_map.get(mime, '.webm')
    tmp_in  = tmp_dir / f'voice_in{suffix}'
    tmp_wav = tmp_dir / 'voice_in.wav'

    try:
        audio_file.save(str(tmp_in))
        file_size = tmp_in.stat().st_size
        logger.info(f'🎙️ Audio received: {file_size} bytes | ext={suffix} | mime={mime}')

        if file_size < 100:
            return jsonify({'ok': False,
                            'error': f'Audio file too small ({file_size} bytes) — recording may have failed'}), 400

        # ── Already a WAV? Skip conversion ────────────────────────────────────
        if suffix.lower() == '.wav':
            tmp_wav   = tmp_in
            converted = True
            logger.debug('✅ Input is already WAV — skipping conversion')
        else:
            converted = False

        # ── ffmpeg conversion (preferred) ─────────────────────────────────────
        if not converted:
            try:
                subprocess.run(
                    ['ffmpeg', '-y', '-i', str(tmp_in),
                     '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(tmp_wav)],
                    check=True, capture_output=True, timeout=20,
                )
                converted = True
                logger.debug('✅ ffmpeg conversion succeeded')
            except FileNotFoundError:
                logger.warning('⚠️ ffmpeg not found — will try soundfile fallback')
            except subprocess.CalledProcessError as ffmpeg_err:
                full_err = (ffmpeg_err.stderr or b'').decode(errors='replace')
                logger.warning(f'⚠️ ffmpeg failed (rc={ffmpeg_err.returncode}):\n{full_err}')
                # Retry forcing the container format explicitly (helps with some WebM/Opus blobs)
                if suffix in ('.webm', '.ogg', '.opus'):
                    try:
                        logger.info('🔄 Retrying ffmpeg with explicit -f webm ...')
                        subprocess.run(
                            ['ffmpeg', '-y', '-f', 'webm', '-i', str(tmp_in),
                             '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(tmp_wav)],
                            check=True, capture_output=True, timeout=20,
                        )
                        converted = True
                        logger.info('✅ ffmpeg retry succeeded')
                    except subprocess.CalledProcessError as retry_err:
                        logger.warning(f'⚠️ ffmpeg retry also failed:\n'
                                       f'{(retry_err.stderr or b"").decode(errors="replace")}')

        # ── soundfile fallback ────────────────────────────────────────────────
        if not converted:
            try:
                import soundfile as sf
                import numpy as np
                data, sr = sf.read(str(tmp_in))
                if data.ndim > 1:
                    data = data.mean(axis=1)
                if sr != 16000:
                    n    = int(len(data) * 16000 / sr)
                    data = np.interp(np.linspace(0, len(data), n), np.arange(len(data)), data)
                sf.write(str(tmp_wav), data.astype('float32'), 16000, subtype='PCM_16')
                converted = True
                logger.info('✅ soundfile fallback conversion succeeded')
            except Exception as sf_err:
                logger.error(f'❌ soundfile fallback failed: {sf_err}')
                return jsonify({'ok': False,
                                'error': f'Audio conversion failed: {sf_err}. '
                                         'Install ffmpeg: sudo apt install ffmpeg'}), 500

        # ── Whisper transcription ─────────────────────────────────────────────
        logger.info(f'🧠 Running whisper: model={model_path.name}')
        result = subprocess.run(
            [
                str(whisper_bin),
                '-m', str(model_path),
                '-f', str(tmp_wav),
                '--no-timestamps',
                '-l', 'auto',
                '--threads', '4',
            ],
            capture_output=True, text=True, timeout=120,
            env=os.environ.copy(),
        )

        if result.returncode != 0:
            err_out = (result.stderr or '').strip()
            logger.error(f'❌ Whisper rc={result.returncode}:\n{err_out}')
            return jsonify({'ok': False,
                            'error': f'Transcription failed (rc={result.returncode}): {err_out[:400]}'}), 500

        transcript = result.stdout.strip()
        transcript = re.sub(r'\[.*?\]', '', transcript)   # strip [BLANK_AUDIO] etc
        transcript = re.sub(r'\(.*?\)', '', transcript).strip()

        if not transcript:
            logger.warning('⚠️ Whisper returned empty transcript')
            return jsonify({'ok': False, 'error': 'No speech detected'}), 200

        logger.info(f'🎤 Transcribed ({model_path.name}): "{transcript[:80]}"')
        return jsonify({'ok': True, 'text': transcript})

    except subprocess.TimeoutExpired:
        logger.error('❌ Whisper timed out — killing process')
        try:
            subprocess.run(['pkill', '-f', 'whisper-cli'], capture_output=True)
            subprocess.run(['pkill', '-f', 'whisper.cpp/main'], capture_output=True)
        except Exception:
            pass
        return jsonify({'ok': False,
                        'error': 'Transcription timed out — whisper killed, ready to retry'}), 504
    except Exception as e:
        import traceback
        logger.error(f'❌ Transcription error: {type(e).__name__}: {e}\n{traceback.format_exc()}')
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {str(e)}'}), 500
    finally:
        # Clean up — be careful not to delete the same file twice if wav == input
        to_delete = {tmp_in, tmp_wav} if tmp_wav != tmp_in else {tmp_in}
        for f in to_delete:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass


@app.route('/api/voice/speak', methods=['POST'])
def voice_speak():
    """
    TTS endpoint.  Accepts JSON { text, language }.
    Returns: audio/wav stream.
    Requires: piper/piper binary + piper/voices/*.onnx models.
    """
    data = request.json or {}
    text = data.get('text', '').strip()
    lang = data.get('language', 'en')
    # voice_model: explicit stem name from frontend (e.g. 'en_US-ryan-high')
    # Falls back to lang-map if not supplied
    explicit_model = data.get('voice_model', '').strip()

    if not text:
        return jsonify({'ok': False, 'error': 'No text'}), 400

    clean = _clean_for_tts(text)
    if not clean:
        return jsonify({'ok': False, 'error': 'Nothing to speak'}), 400

    piper_bin = _voice_path('bin/piper')
    if not piper_bin.exists():
        return jsonify({'ok': False,
                        'error': 'Piper not found — expected at voice/bin/piper'}), 503

    voice_map = {
        'es': 'es_MX-ald-medium',
        'en': 'en_US-ryan-high',
        'pt': 'pt_BR-faber-medium',
        'fr': 'fr_FR-upmc-medium',
        'de': 'de_DE-thorsten-medium',
    }
    lang_code  = lang[:2].lower()
    # Explicit model from UI takes priority; lang-map is fallback
    voice_name = explicit_model if explicit_model else voice_map.get(lang_code, 'en_US-ryan-high')
    voices_dir = _voice_path('models/tts')
    voice_model = voices_dir / f'{voice_name}.onnx'

    if not voice_model.exists():
        for fb in ['en_US-lessac-high', 'es_MX-claude-high']:
            p = voices_dir / f'{fb}.onnx'
            if p.exists():
                voice_model = p
                break
    if not voice_model.exists():
        return jsonify({'ok': False, 'error': f'Voice model not found: {voice_name}'}), 503

    try:
        # Build env with required library paths for Piper
        piper_env = os.environ.copy()
        piper_env['LD_LIBRARY_PATH'] = str(_voice_path('bin'))
        piper_env['ESPEAK_DATA_PATH'] = str(_voice_path('espeak-ng-data'))

        result = subprocess.run(
            [str(piper_bin), '--model', str(voice_model), '--output-raw'],
            input=clean.encode('utf-8'),
            capture_output=True, timeout=30,
            env=piper_env,
        )
        if result.returncode != 0:
            return jsonify({'ok': False,
                            'error': 'Piper error: ' + result.stderr.decode(errors='replace')[:200]}), 500

        # Read sample rate from model config
        sample_rate = 22050
        config_path = voice_model.with_suffix('.onnx.json')
        if config_path.exists():
            try:
                import json as _json
                cfg = _json.loads(config_path.read_text())
                sample_rate = cfg.get('audio', {}).get('sample_rate', 22050)
            except Exception:
                pass

        wav = _pcm_to_wav(result.stdout, sample_rate=sample_rate)
        logger.info(f'🔊 TTS: {len(clean)} chars → {len(wav)} bytes @ {sample_rate} Hz')

        return Response(
            wav,
            mimetype='audio/wav',
            headers={'Content-Disposition': 'inline', 'Cache-Control': 'no-cache'},
        )
    except subprocess.TimeoutExpired:
        logger.error('❌ TTS timed out — killing piper process')
        try:
            import signal as _sig
            subprocess.run(['pkill', '-f', 'piper'], capture_output=True)
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'TTS timed out — piper process killed, retry'}), 504
    except Exception as e:
        logger.error(f'❌ TTS error: {e}', exc_info=True)
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/voice/status", methods=["GET"])
def voice_status():
    """
    Returns readiness of STT and TTS subsystems.
    The dashboard calls this on load to show/hide voice controls gracefully.
    """
    import re as _re2
    whisper_bin = _voice_path("bin/whisper-cli")
    if not whisper_bin.exists():
        whisper_bin = _voice_path("bin/main")
    piper_bin = _voice_path("bin/piper")
    voices_dir = _voice_path("models/tts")
    tts_models = list(voices_dir.glob("*.onnx")) if voices_dir.exists() else []
    stt_model = next(
        (_voice_path(f"models/stt/{n}") for n in
         ["ggml-small.bin", "ggml-base.bin", "ggml-base.en.bin", "ggml-tiny.bin"]
         if _voice_path(f"models/stt/{n}").exists()),
        None
    )
    return jsonify({
        "stt_ready": whisper_bin.exists() and stt_model is not None,
        "tts_ready": piper_bin.exists() and len(tts_models) > 0,
        "espeak_ok": _voice_path("espeak-ng-data").exists(),
        "whisper_bin": str(whisper_bin),
        "piper_bin": str(piper_bin),
        "stt_model": str(stt_model) if stt_model else None,
        "tts_voices": [m.stem for m in tts_models],
    })

# ==============================================================================
# === MAIN EXECUTION ===
# ==============================================================================
if __name__ == "__main__":
    # Only run Flask directly if this file is executed standalone (not via run_app.py)
    # This prevents double-start when run_app.py imports app.main
    import os
    if os.getenv("LMIM_LAUNCHED_BY_RUNNER") != "true":
        logger.info("🌐 Serving Dashboard at: http://localhost:5000/dev (standalone mode)")
        app.run(port=5000, debug=(LOG_LEVEL == "DEBUG"), use_reloader=False, threaded=True)
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, signal_handler)

    # 1. Start LLM Server FIRST (auto-selects model, sets MODEL_PATH in env)
    llama_ready = start_llama_server()
    
    # 2. 🔥 CRITICAL: Reload .env with override so Flask sees updated MODEL_PATH
    env_file = DATA_DIR / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)
        logger.info("🔄 Reloaded .env after LLM start - MODEL_PATH now active")
    
    # 3. Start Daemons (disabled for V1 - users start manually from GUI)
    logger.info("ℹ️ Auto-start of daemons disabled. Users must start them manually from the GUI.")
    
    # 4. Start Flask in Background Thread (NOW sees correct MODEL_PATH)
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    time.sleep(2)  # Brief pause for Flask to initialize
    
    # 5. Open Native Window (pywebview)
    try:
        import webview
        logger.info("🖥️ Opening Native Window...")
        
        window = webview.create_window(
            title='LMIM OS',
            url='http://127.0.0.1:5000/dev',
            width=1280, height=800,
            min_size=(800, 600),
            text_select=True,
            background_color='#050505'
        )
        
        webview.start()
        
    except Exception as e:
        logger.error(f"❌ GUI Failed: {e}")
        time.sleep(10)
        sys.exit(1)
