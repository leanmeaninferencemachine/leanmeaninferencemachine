# app/router.py
"""
LMIM Central Router v5.0 "Identity-Enforced Orchestrator"
Guarantees System + User Identity injection for ALL conversational flows.
"""
import logging
import asyncio
import time
import re
import json
import os
from typing import Optional, Dict, Any, List
from pathlib import Path
from app.config import (
    BUILDER_API_TIMEOUT, CHAT_API_TIMEOUT, PLANNER_API_TIMEOUT,
    MODEL_NAME, LLM_API_URL, DEFAULT_CONTEXT,
    ENABLE_TOOL_CALLING, TOOL_CALL_MARKER_START, TOOL_CALL_MARKER_END,
    AVAILABLE_TOOLS, ENABLE_AUDIT_LOGGING,
    SUMMARY_INTERVAL, SUMMARY_MAX_HISTORY_TURNS,
    get_system_identity, get_user_identity
)

logger = logging.getLogger(__name__)

# === 🔍 INTENT DETECTION ===
BUILD_TRIGGERS = {
    "build", "create", "write", "generate", "make", "develop", "code", 
    "script", "program", "tool", "function", "module", "automate",
    "python", "js", "javascript", "file", "fix", "debug", "refactor",
    "fibonacci", "calculator", "bot", "daemon", "api", "server"
}

BUILD_PHRASES = [
    "create a script", "write code", "build a tool", "generate python",
    "make a file", "fix the code", "create a function", "automate this",
    "write a test", "implement feature", "crear un script", "escribir código",
    "construir herramienta", "hacer un archivo", "script de", "código para",
    "build a python", "write a python", "create a python", "read file",
    "parse json", "filter data", "process csv"
]

SECURITY_KEYWORDS = [
    "scan for vulnerabilities", "security audit", "check security",
    "is this code safe", "penetration test", "find exploits",
    "analyze risks", "horus scan", "vulnerability assessment",
    "escaneo de seguridad", "buscar vulnerabilidades", "cybersec"
]

SCHEDULE_KEYWORDS = [
    "schedule a meeting", "book a class", "agenda una cita",
    "when are you free", "available slots", "reserve a time",
    "calendar", "meeting request", "class request",
    "agendar reunión", "reservar clase", "disponibilidad", "hora"
]

SEARCH_KEYWORDS = [
    "search for", "look up", "find news", "current events",
    "what's happening", "latest version", "who won",
    "check online", "google this", "buscar en internet",
    "noticias", "información actual", "weather", "clima"
]

def _detect_intent(prompt: str) -> str:
    prompt_lower = prompt.lower()
    if any(phrase in prompt_lower for phrase in BUILD_PHRASES): return 'build'
    if any(kw in prompt_lower for kw in SECURITY_KEYWORDS): return 'security'
    if any(kw in prompt_lower for kw in SCHEDULE_KEYWORDS): return 'schedule'
    if any(kw in prompt_lower for kw in SEARCH_KEYWORDS): return 'search'
    words_found = [w for w in BUILD_TRIGGERS if w in prompt_lower]
    if len(words_found) >= 2: return 'build'
    if sum(1 for k in SECURITY_KEYWORDS if k in prompt_lower) > 0: return 'security'
    return 'base'

# === 📞 PHONE NUMBER NORMALIZATION ===
def normalize_mexican_phone(text: str) -> str:
    """
    Convert Mexican phone formats to international standard (without the 1).
    Converts "+52 1 664 529 7303" to "+52 664 529 7303"
    This prevents the model from misinterpreting the '1' as a prefix.
    """
    if not text:
        return text
    # Pattern: +52 1 664 529 7303 or +52 1 6645297303 or 52 1 664 529 7303
    pattern = r'(\+?52)\s*1\s*(\d{3})\s*(\d{3})\s*(\d{4})'
    replacement = r'\1 \2 \3 \4'
    return re.sub(pattern, replacement, text)

# === 🆔 IDENTITY INJECTION CORE ===
def _build_unified_system_prompt(force_tool_reminder: bool = False) -> str:
    """Constructs the FULL system prompt with Identity + Tools."""
    try:
        system_identity = get_system_identity()
        user_identity = get_user_identity()
    except Exception as e:
        logger.error(f"❌ Failed to load identity files: {e}")
        system_identity = "You are LMIM AI."
        user_identity = {}

    owner_data = user_identity.get("owner", {})
    ai_data = user_identity.get("ai_profile", {})
    
    owner_name = owner_data.get("name", "the User")
    agent_name = ai_data.get("name", "LMIM Assistant")
    tone = ai_data.get("tone", "witty, direct")
    signature = ai_data.get("signature", "- LMIM OS")
    rules_list = ai_data.get("rules", [])
    rules_text = "\n".join([f"- {r}" for r in rules_list]) if rules_list else "None"

    identity_block = f"""
### 👤 ACTIVE OPERATOR PROFILE
**Agent Name:** {agent_name}
**Owner:** {owner_name}
**Tone:** {tone}
**Signature:** {signature}
**Specific Rules:**
{rules_text}

⚠️ INSTRUCTION: You are the assistant for {owner_name}. Adhere strictly to the tone and rules above. Sign off with "{signature}" unless performing a tool call.
"""

    final_prompt = f"{system_identity}\n\n{identity_block}\n\n{DEFAULT_CONTEXT}"
    
    if force_tool_reminder:
        final_prompt += "\n\n⚠️ CRITICAL REMINDER: The user is asking for action. USE YOUR TOOLS immediately."
        
    return final_prompt

# === 🏗️ BUILD FLOW ===
def _trigger_build_flow(prompt: str, user_id: str, source: str) -> str:
    logger.info(f"🔨 Intent: BUILD. Triggering Planner...")
    try:
        from app.agents.planner import plan_project
        from app.events.base import EventType, emit
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            manifest = loop.run_until_complete(plan_project(prompt, user_id))
        finally:
            loop.close()
            
        if not manifest: return "❌ Failed to generate a build plan."
            
        task_ids = []
        base_time = int(time.time())
        dependencies_content = ""
        deps = manifest.get("dependencies", [])
        
        if deps:
            for dep_path in deps:
                try:
                    p = Path(dep_path)
                    if not p.is_absolute(): p = Path(__file__).resolve().parent.parent / dep_path
                    if p.exists():
                        src = p.read_text(encoding="utf-8")
                        dependencies_content += f"\n### SOURCE FILE: {dep_path}\n```python\n{src}\n```\n"
                except Exception as e:
                    logger.error(f"Failed to load dependency {dep_path}: {e}")
        
        for idx, filename in enumerate(manifest.get("build_order", [])):
            try:
                lookup_filename = filename[len("workspace/"):] if filename.startswith("workspace/") else filename
                file_spec = next((f for f in manifest["files"] if f["name"] == lookup_filename), None)
                if not file_spec: continue
                
                clean_filename = filename[len("workspace/"):] if filename.startswith('workspace/') else filename
                task_id = f"auto_{user_id}_{clean_filename}_{base_time}" 
                original_instructions = file_spec.get("instructions", "")
                final_description = original_instructions
                
                if dependencies_content:
                    final_description = f"CONTEXT (EXISTING CODE):\n{dependencies_content}\n\nTASK:\n{original_instructions}"
                
                emit(EventType.BUILD_REQUEST, payload={
                    "task_id": task_id, "description": final_description, 
                    "language": manifest.get('language', 'python'), "filename": clean_filename, 
                    "max_attempts": 10, "user_id": user_id, "source": source, "dependencies": deps
                })
                task_ids.append(task_id)
            except Exception as e:
                logger.error(f"Failed to emit build: {e}")
                continue
        
        if not task_ids: return "❌ Planning succeeded but no files generated."
        first_file = manifest.get('files', [{}])[0].get('name', 'solution.py')
        if first_file.startswith('workspace/'): first_file = first_file[len('workspace/'):]
            
        return f"🚀 **Build Started!**\n**Project:** `{manifest.get('project_name')}`\n**File:** `{first_file}`\nCheck 'Build Logs' tab."
        
    except Exception as e:
        logger.error(f"💥 Build Flow Error: {e}", exc_info=True)
        return f"❌ Build error: {str(e)}"

# === 🛡️ SECURITY FLOW ===
def _trigger_security_flow(prompt: str, user_id: str, source: str) -> str:
    logger.info(f"🛡️ Intent: SECURITY. Triggering Horus Engine...")
    system_prompt = _build_unified_system_prompt(force_tool_reminder=False)
    return _execute_chat_with_prompt(prompt, user_id, system_prompt)

# === 📅 SCHEDULE & 🔍 SEARCH ===
def _trigger_schedule_flow(prompt: str, user_id: str, source: str) -> str:
    logger.info(f"📅 Intent: SCHEDULE. Delegating with Tool Focus...")
    system_prompt = _build_unified_system_prompt(force_tool_reminder=True)
    return _execute_chat_with_prompt(prompt, user_id, system_prompt)

def _trigger_search_flow(prompt: str, user_id: str, source: str) -> str:
    logger.info(f"🔍 Intent: SEARCH. Delegating with Web Search Tool...")
    system_prompt = _build_unified_system_prompt(force_tool_reminder=True)
    return _execute_chat_with_prompt(prompt, user_id, system_prompt)

# === 💬 SHARED EXECUTOR ===
def _execute_chat_with_prompt(prompt: str, user_id: str, system_prompt: str, signature: str = "") -> str:
    """Shared execution logic. Handles Memory Loading + Model Call + Signature Enforcement."""
    try:
        from app.memory_functions import get_recent_chat_history, log_whatsapp_chat_turn
        from app.model_interface import query_model
        
        raw_history = get_recent_chat_history(user_id, limit=10)
        conversation_history = []
        if raw_history:
            for entry in raw_history:
                role = "user" if entry["role"] == "user" else "assistant"
                conversation_history.append({"role": role, "content": entry["content"]})
        
        reply = query_model(
            prompt=prompt,
            user_id=user_id,
            conversation_history=conversation_history,
            conversation_summary="",
            builder_mode=False,
            system_override=system_prompt,  # <--- IDENTITY IS FORCED HERE
            disable_rag=True  # ← IMPORTANT: Disable RAG for base chat
        )
        
        # Append signature if not already present and no tool call
        if signature and "[TOOL_CALL]" not in reply:
            reply_stripped = reply.strip().rstrip('\n')
            sig_clean = signature.lstrip('- \n').strip()
            if not reply_stripped.lower().endswith(sig_clean.lower()):
                reply += f"\n{signature}"
        
        # Always log the turn (outside the if block)
        log_whatsapp_chat_turn(user_id, prompt, reply, max_turns=10)
        return reply
        
    except Exception as e:
        logger.error(f"💥 Chat Execution Error: {e}", exc_info=True)
        return f"❌ System error: {str(e)}"

# === 📱 COMMUNICATION AGENTS ROUTER ===
def _route_to_comm_agent(prompt: str, user_id: str, source: str) -> str:
    """Routes to specific communication agents BUT forces them to use the Global System Prompt."""
    logger.info(f"📡 Routing to {source.upper()} Agent with Global Identity...")
    
    system_prompt = _build_unified_system_prompt(force_tool_reminder=False)
    
    try:
        user_identity = get_user_identity()
        signature = user_identity.get("ai_profile", {}).get("signature", "")
    except:
        signature = ""

    try:
        if source == "whatsapp":
            from app.agents.whatsapp_agent import WhatsAppAgent
            agent = WhatsAppAgent()
            phone = user_id.replace("wa_", "") if user_id.startswith("wa_") else "0000"
            reply = agent.process_message_sync(phone, prompt, system_prompt_override=system_prompt)
            
        elif source == "telegram":
            from app.agents.telegram_agent import TelegramAgent
            agent = TelegramAgent()
            if hasattr(agent, 'process_message_sync'):
                reply = agent.process_message_sync(user_id, prompt, system_prompt_override=system_prompt)
            else:
                logger.warning("⚠️ TelegramAgent missing process_message_sync. Falling back to Base Chat.")
                return _execute_chat_with_prompt(prompt, user_id, system_prompt, signature)
                
        elif source in ["slack", "discord"]:
            logger.info(f"💬 {source.upper()} using Base Chat Flow with Global Identity.")
            return _execute_chat_with_prompt(prompt, user_id, system_prompt, signature)
            
        else:
            return _execute_chat_with_prompt(prompt, user_id, system_prompt, signature)

        # Append signature if not already present and no tool call
        if signature and "[TOOL_CALL]" not in reply:
            reply_stripped = reply.strip().rstrip('\n')
            sig_clean = signature.lstrip('- \n').strip()
            if not reply_stripped.lower().endswith(sig_clean.lower()):
                reply += f"\n{signature}"
        
        # Always log the turn
        from app.memory_functions import log_whatsapp_chat_turn
        log_whatsapp_chat_turn(user_id, prompt, reply, max_turns=10)
        return reply

    except Exception as e:
        logger.error(f"💥 Error in {source.upper()} Agent: {e}", exc_info=True)
        logger.warning(f"⚠️ Falling back to Base Chat for {source}")
        return _execute_chat_with_prompt(prompt, user_id, system_prompt, signature)

# === 💬 BASE CHAT ENTRY POINT ===
def _trigger_base_chat(prompt: str, user_id: str, source: str, force_tool_reminder: bool = False) -> str:
    logger.info(f"💬 Intent: BASE_CHAT. Building Identity...")
    system_prompt = _build_unified_system_prompt(force_tool_reminder=force_tool_reminder)
    
    try:
        user_identity = get_user_identity()
        signature = user_identity.get("ai_profile", {}).get("signature", "")
    except:
        signature = ""
        
    return _execute_chat_with_prompt(prompt, user_id, system_prompt, signature)

# === 🧠 MAIN ROUTER FUNCTION (SINGLE DEFINITION) ===
def route_request(user_prompt: str, user_id: str, source: str = "unknown") -> str:
    """Decide qué agente procesar la solicitud basándose SOLO en la intención."""
    if not user_prompt or not user_prompt.strip():
        return "⚠️ Empty prompt received."

    # 🔥 PHONE NORMALIZATION: Strip the '1' from Mexican mobile numbers
    # This prevents the model from misinterpreting the '1' prefix
    user_prompt = normalize_mexican_phone(user_prompt)

    prompt_lower = user_prompt.lower()
    
    # 🔥 ENHANCED: Detect scheduling keywords ANYWHERE in prompt
    schedule_keywords = [
        "schedule", "book", "agenda", "cita", "reunión", "meeting",
        "programar", "reservar", "fix a time", "set up a meeting"
    ]
    has_schedule_intent = any(kw in prompt_lower for kw in schedule_keywords)
    
    # If scheduling intent detected, check if we have enough params to proceed
    if has_schedule_intent:
        has_date = re.search(r'\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}', prompt_lower)
        has_time = re.search(r'\b\d{1,2}:\d{2}\s*(am|pm)?|\b\d{1,2}\s*(am|pm|o\'?clock)', prompt_lower)
        has_phone = re.search(r'\+?\d[\d\s\-]{7,}\d', prompt_lower)
        has_name = re.search(r'(for|with|to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', prompt_lower)
        
        # If we have most params, route to scheduling flow immediately
        if sum([bool(has_date), bool(has_time), bool(has_phone), bool(has_name)]) >= 3:
            logger.info(f"📅 Scheduling intent detected with sufficient params. Routing to scheduler...")
            return _trigger_schedule_flow(user_prompt, user_id, source)
    
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
        return _trigger_build_flow(user_prompt, user_id, source)
    
    # 2. DETECTAR ORIGEN ESPECÍFICO (WhatsApp Agent tiene lógica de perfil/transcripción)
    if source == "whatsapp":
        logger.info(f"📱 Source Detected: WhatsApp. Routing to WhatsAppAgent...")
        return _route_to_comm_agent(user_prompt, user_id, source)
    
    # 3. DEFAULT: Base Agent Logic (Chat General + Herramientas)
    logger.info(f"💬 Intent Detected: GENERAL CHAT. Routing to Base Flow...")
    return _trigger_base_chat(user_prompt, user_id, source)
