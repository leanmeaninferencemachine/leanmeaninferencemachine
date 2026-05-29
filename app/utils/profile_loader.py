# app/utils/profile_loader.py
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

def get_writable_data_dir() -> Path:
    """
    Returns the writable data directory.
    1. Checks LMIM_DATA_DIR env var (set by run_app.py for AppImage).
    2. Falls back to local project root for development.
    """
    env_path = os.getenv('LMIM_DATA_DIR')
    if env_path:
        return Path(env_path)
    
    # Development fallback
    current_script = Path(__file__).resolve()
    # utils -> app -> ROOT
    return current_script.parent.parent / "data"

def get_agent_profile(user_id: str, source: str = "unknown") -> dict:
    """
    Loads the specific agent profile based on user_id or source.
    Fallback to 'default.json' if not found.
    """
    # 🔥 CRITICAL: Use dynamic data dir
    profiles_dir = get_writable_data_dir() / "profiles"
    profile_name = "default"
    
    # Mapeo inteligente de IDs a perfiles
    # ✅ KEEP PERSONAL REFERENCES: This is your personal OS.
    if "admin" in user_id or "andres" in user_id.lower():
        profile_name = "hexa" # Or "andres" if you have a specific andres.json, otherwise hexa/default often covers admin
        # If you have a specific 'andres.json', uncomment below:
        # profile_name = "andres"
    elif "hexa" in source or "hexa" in user_id.lower():
        profile_name = "hexa"
    elif "happy_fox" in source or "happy_fox" in user_id.lower():
        profile_name = "happy_fox"
    elif "efa" in source or "efa" in user_id.lower():
        profile_name = "default" # Or create efa.json
        
    profile_path = profiles_dir / f"{profile_name}.json"
    
    logger.debug(f"🔍 Looking for profile: {profile_path}")

    if profile_path.exists():
        try:
            with open(profile_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.info(f"✅ Loaded profile: {profile_name}.json for user {user_id}")
            return data
        except Exception as e:
            logger.error(f"❌ Error loading profile {profile_name}: {e}")
    
    logger.warning(f"⚠️ Profile {profile_name} not found at {profile_path}. Using default.")
    # Cargar default si falla
    default_path = profiles_dir / "default.json"
    if default_path.exists():
        with open(default_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    return {} # Vacío si nada existe
