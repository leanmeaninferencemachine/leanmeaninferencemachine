# app/tools/scheduling_tools.py
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, date as date_type
from app.tools.base_tool import BaseTool
from app.tools.comms_tools import SendWhatsAppTool

logger = logging.getLogger(__name__)

# 🔥 CRITICAL: Dynamic Writable Agenda Dir
def get_writable_agenda_dir() -> Path:
    env_path = os.getenv('LMIM_DATA_DIR')
    if env_path:
        agenda_dir = Path(env_path) / "agendas"
        agenda_dir.mkdir(parents=True, exist_ok=True)
        return agenda_dir
    if getattr(sys, 'frozen', False):
        agenda_dir = Path.home() / ".lmim_os" / "agendas"
    else:
        agenda_dir = Path(__file__).resolve().parent.parent.parent / "data" / "agendas"
    agenda_dir.mkdir(parents=True, exist_ok=True)
    return agenda_dir

AGENDA_DIR = get_writable_agenda_dir()

def _parse_time_range(time_range: str, default_start: str = "09:00", default_end: str = "18:00"):
    """
    Safely parse a time_range string into (start_h, start_m, end_h, end_m).

    Accepts:
      - "HH:MM-HH:MM"  →  normal full range  (e.g. "09:00-17:00")
      - "HH:MM"        →  single time; treat as start, use default_end
      - anything else  →  fall back to defaults and log a warning

    Returns: (start_h: int, start_m: int, end_h: int, end_m: int)
    """
    def _split_time(t: str):
        parts = t.strip().split(':')
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
        raise ValueError(f"Invalid time token: '{t}'")

    try:
        if '-' in time_range:
            segments = time_range.split('-')
            if len(segments) >= 2:
                start_h, start_m = _split_time(segments[0])
                end_h,   end_m   = _split_time(segments[1])
                # Sanity-check: if model passed a single time like "16:00" and it
                # landed in segments[0] with segments[1] being empty or garbage,
                # fall through to the single-time branch below.
                if end_h > start_h or (end_h == start_h and end_m > start_m):
                    return start_h, start_m, end_h, end_m
            # Fall through — malformed range
            logger.warning(f"⚠️ time_range '{time_range}' looks malformed; treating as single start time.")
            start_h, start_m = _split_time(segments[0])
            def_h, def_m = _split_time(default_end)
            return start_h, start_m, def_h, def_m
        else:
            # Single time provided — treat as start, use default_end
            logger.warning(f"⚠️ time_range '{time_range}' has no '-'; using as start time with default end {default_end}.")
            start_h, start_m = _split_time(time_range)
            def_h, def_m = _split_time(default_end)
            return start_h, start_m, def_h, def_m

    except Exception as e:
        logger.warning(f"⚠️ Could not parse time_range '{time_range}': {e}. Using defaults {default_start}-{default_end}.")
        s_h, s_m = _split_time(default_start)
        e_h, e_m = _split_time(default_end)
        return s_h, s_m, e_h, e_m


def _normalize_date(date_str: str) -> str:
    """
    Normalize date to YYYY-MM-DD using current year if year is missing,
    in the past, or unreasonably far in the future.
    """
    current_year = datetime.now().year  # Live — no hardcoding

    if not date_str:
        return date_str

    try:
        # "MM-DD" or "M-D" shorthand
        if len(date_str) <= 5 and '-' in date_str:
            return f"{current_year}-{date_str.zfill(5)}"

        # Full YYYY-MM-DD
        if len(date_str) == 10 and date_str.count('-') == 2:
            parts = date_str.split('-')
            parsed_year = int(parts[0])
            if parsed_year < current_year or parsed_year > current_year + 5:
                logger.warning(f"⚠️ Year {parsed_year} out of expected range; correcting to {current_year}.")
                return f"{current_year}-{parts[1]}-{parts[2]}"
            return date_str

    except Exception as e:
        logger.warning(f"⚠️ Date normalization failed for '{date_str}': {e}. Returning as-is.")

    return date_str


class CheckAvailabilityTool(BaseTool):
    name = "check_availability"
    description = (
        "Check free time slots for a specific date and tenant. "
        "time_range must be 'HH:MM-HH:MM' (e.g. '09:00-17:00'). "
        "Default range: 09:00-18:00."
    )
    args_schema = {
        "type": "object",
        "properties": {
            "date":       {"type": "string", "description": "YYYY-MM-DD"},
            "tenant_id":  {"type": "string", "description": "Tenant ID (e.g. 'hexa')"},
            "time_range": {"type": "string", "description": "HH:MM-HH:MM (e.g. '09:00-17:00')"}
        },
        "required": ["date"]
    }

    def execute(self, params: Dict[str, Any]) -> str:
        date_str  = params.get('date')
        tenant_id = params.get('tenant_id', 'hexa').lower().replace(" ", "_")
        time_range = params.get('time_range', '09:00-18:00')

        if not date_str:
            return "❌ ERROR: Missing required parameter 'date'."

        date_str = _normalize_date(date_str)

        # Load agenda
        agenda_file = AGENDA_DIR / f"{tenant_id}_agenda.json"
        agenda = {}
        if agenda_file.exists():
            try:
                with open(agenda_file, 'r', encoding='utf-8') as f:
                    agenda = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load agenda for {tenant_id}: {e}")

        day_schedule = agenda.get(date_str, [])
        booked_times = {slot['time'] for slot in day_schedule if slot.get('status') == 'booked'}

        # ✅ FIXED: defensive parse — no more IndexError on single-time input
        start_h, start_m, end_h, end_m = _parse_time_range(time_range)

        available_slots = []
        current_h = start_h
        while current_h < end_h:
            time_slot = f"{current_h:02d}:{start_m:02d}"
            if time_slot not in booked_times:
                available_slots.append(time_slot)
            current_h += 1

        if not available_slots:
            return f"⚠️ No available slots on {date_str} between {time_range}."
        return f"✅ Available on {date_str}: {', '.join(available_slots)}"


class ScheduleMeetingTool(BaseTool):
    name = "schedule_meeting"
    description = "Book a meeting/class and send WhatsApp confirmation."
    args_schema = {
        "type": "object",
        "properties": {
            "date":         {"type": "string", "description": "YYYY-MM-DD"},
            "time":         {"type": "string", "description": "HH:MM"},
            "user_phone":   {"type": "string", "description": "Phone with country code"},
            "user_name":    {"type": "string", "description": "Name of the person"},
            "meeting_type": {"type": "string", "description": "Type of meeting. Default is 'meeting'. Options: 'meeting', 'class', 'task', 'assessment'"},
            "tenant_id":    {"type": "string", "description": "Tenant ID (e.g. 'hexa')"},
            "notes":        {"type": "string", "description": "Optional notes"}
        },
        "required": ["date", "time", "user_phone", "user_name", "meeting_type"]
    }

    def execute(self, params: Dict[str, Any]) -> str:
        date_str   = params.get('date')
        time_slot  = params.get('time')
        phone      = params.get('user_phone')
        name       = params.get('user_name', 'Unknown')
        m_type     = params.get('meeting_type', 'meeting')
        tenant_id  = params.get('tenant_id', 'hexa').lower().replace(" ", "_")
        notes      = params.get('notes', '')

        # Validate required fields up front
        missing = [f for f, v in [('date', date_str), ('time', time_slot), ('user_phone', phone)] if not v]
        if missing:
            return f"❌ ERROR: Missing required parameters: {', '.join(missing)}."

        date_str = _normalize_date(date_str)

        # Normalize time slot — accept "3pm", "15:00", "3:00 PM"
        time_slot = _normalize_time_slot(time_slot)
        if not time_slot:
            return "❌ ERROR: Could not parse 'time'. Use HH:MM format (e.g. '15:00')."

        # Load agenda
        agenda_file = AGENDA_DIR / f"{tenant_id}_agenda.json"
        agenda = {}
        if agenda_file.exists():
            try:
                with open(agenda_file, 'r', encoding='utf-8') as f:
                    agenda = json.load(f)
            except Exception:
                agenda = {}

        if date_str not in agenda:
            agenda[date_str] = []

        # Conflict check
        for slot in agenda[date_str]:
            if slot.get('time') == time_slot and slot.get('status') == 'booked':
                return f"❌ CONFLICT: {time_slot} on {date_str} is already booked."

        # Book it
        meeting_id = f"MTG_{tenant_id.upper()}_{int(time.time())}"
        new_entry = {
            "time":         time_slot,
            "status":       "booked",
            "user_phone":   phone,
            "user_name":    name,
            "meeting_type": m_type,
            "meeting_id":   meeting_id,
            "notes":        notes,
            "created_at":   time.time()
        }
        agenda[date_str].append(new_entry)

        try:
            with open(agenda_file, 'w', encoding='utf-8') as f:
                json.dump(agenda, f, indent=2, ensure_ascii=False)
            logger.info(f"✅ Booked: {meeting_id} — {name} @ {date_str} {time_slot}")
        except Exception as e:
            return f"❌ ERROR: Failed to save agenda: {e}"

        # Auto WhatsApp confirmation
        confirm_msg = (
            f"✅ *Confirmed!* {m_type.title()} scheduled.\n"
            f"📅 {date_str}  ⏰ {time_slot}\n"
            f"👤 {name}\n"
            f"🆔 {meeting_id}"
        )
        if notes:
            confirm_msg += f"\n📝 {notes}"

        try:
            wa_result = SendWhatsAppTool().execute({"phone": phone, "message": confirm_msg})
            if "ERROR" in wa_result:
                logger.warning(f"WhatsApp confirmation failed: {wa_result}")
        except Exception as e:
            logger.error(f"WhatsApp tool error: {e}")

        return f"✅ SUCCESS: {m_type.title()} booked for {name} on {date_str} at {time_slot}. Confirmation sent to {phone}."


def _normalize_time_slot(time_str: str) -> str:
    """
    Convert various time formats to HH:MM 24h.
    Accepts: "15:00", "3pm", "3:00pm", "3:00 PM", "15"
    Returns: "HH:MM" or "" on failure.
    """
    if not time_str:
        return ""
    t = time_str.strip().lower().replace(" ", "")
    try:
        # Already HH:MM
        if ':' in t and len(t) <= 5 and 'a' not in t and 'p' not in t:
            h, m = map(int, t.split(':'))
            return f"{h:02d}:{m:02d}"
        # 12h with am/pm
        for fmt in ('%I:%M%p', '%I%p'):
            try:
                parsed = datetime.strptime(t, fmt)
                return parsed.strftime('%H:%M')
            except ValueError:
                continue
        # Plain integer hour like "15"
        if t.isdigit():
            h = int(t)
            if 0 <= h <= 23:
                return f"{h:02d}:00"
    except Exception as e:
        logger.warning(f"⚠️ Could not normalize time '{time_str}': {e}")
    return ""
