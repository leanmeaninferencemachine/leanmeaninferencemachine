# app/tools/contacts_tools.py
import json
import re
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

def _get_contacts_dir() -> Path:
    data_dir = Path.home() / '.lmim_os'
    contacts_dir = data_dir / 'contacts'
    contacts_dir.mkdir(parents=True, exist_ok=True)
    return contacts_dir

def _get_contacts_path(user_id: str = "default") -> Path:
    return _get_contacts_dir() / f"{user_id}.json"

def load_contacts(user_id: str = "default") -> List[Dict]:
    path = _get_contacts_path(user_id)
    if not path.exists():
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('contacts', [])
    except Exception:
        return []

def save_contacts(user_id: str, contacts: List[Dict]) -> bool:
    path = _get_contacts_path(user_id)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({"contacts": contacts, "updated_at": datetime.now().isoformat()}, f, indent=2)
        return True
    except Exception:
        return False

def add_contact(user_id: str, name: str, phone: str, email: str = "", notes: str = "") -> Dict:
    contacts = load_contacts(user_id)
    # Check for duplicate phone
    for c in contacts:
        if c.get('phone') == phone:
            return {"success": False, "error": f"Contact with phone {phone} already exists"}
    new_contact = {
        "id": str(uuid.uuid4())[:8],
        "name": name.strip(),
        "phone": phone.strip(),
        "email": email.strip() if email else "",
        "notes": notes.strip() if notes else "",
        "created_at": datetime.now().isoformat()
    }
    contacts.append(new_contact)
    if save_contacts(user_id, contacts):
        return {"success": True, "contact": new_contact}
    return {"success": False, "error": "Failed to save"}

def delete_contact(user_id: str, contact_id: str) -> Dict:
    contacts = load_contacts(user_id)
    original_len = len(contacts)
    contacts = [c for c in contacts if c.get('id') != contact_id]
    if len(contacts) == original_len:
        return {"success": False, "error": "Contact not found"}
    if save_contacts(user_id, contacts):
        return {"success": True}
    return {"success": False, "error": "Failed to save"}

def list_contacts_api(user_id: str = "default") -> Dict:
    contacts = load_contacts(user_id)
    safe_contacts = []
    for c in contacts:
        safe_contacts.append({
            "id": c.get('id'),
            "name": c.get('name'),
            "phone": c.get('phone'),
            "email": c.get('email', ''),
            "notes": c.get('notes', '')
        })
    return {"success": True, "contacts": safe_contacts}

def find_contact_by_name(user_id: str, name: str) -> Optional[Dict]:
    """Find a contact by name (fuzzy matching)."""
    import re
    contacts = load_contacts(user_id)
    name_lower = name.lower().strip()
    
    # Exact match first
    for c in contacts:
        if c.get('name', '').lower() == name_lower:
            return c
    
    # Partial match
    for c in contacts:
        if name_lower in c.get('name', '').lower():
            return c
    
    return None

def find_contact_by_phone(user_id: str, phone: str) -> Optional[Dict]:
    """Find a contact by phone number."""
    contacts = load_contacts(user_id)
    phone_clean = re.sub(r'[^\d+]', '', phone)
    
    for c in contacts:
        c_phone_clean = re.sub(r'[^\d+]', '', c.get('phone', ''))
        if c_phone_clean == phone_clean or phone_clean in c_phone_clean:
            return c
    return None

def resolve_recipient(user_id: str, identifier: str) -> Optional[str]:
    """Resolve a name or phone to a phone number."""
    import re
    
    # Check if it's already a phone number
    if re.match(r'^[\+\d\s\-]{8,}$', identifier.strip()):
        return re.sub(r'[^\d+]', '', identifier)
    
    # Try to find by name
    contact = find_contact_by_name(user_id, identifier)
    if contact:
        return contact.get('phone')
    
    return None
