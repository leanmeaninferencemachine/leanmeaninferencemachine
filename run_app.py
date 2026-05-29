#!/usr/bin/env python3
# === DAEMON MODE ENTRY POINT (Frozen-compatible) - MUST BE ABSOLUTE FIRST ===
import sys, os
if '--run-daemon' in sys.argv:
    try:
        daemon_name = sys.argv[sys.argv.index('--run-daemon') + 1]
    except (ValueError, IndexError):
        print("ERROR: --run-daemon requires daemon name", file=sys.stderr)
        sys.exit(1)

    if getattr(sys, 'frozen', False):
        daemon_script = os.path.join(sys._MEIPASS, "daemons", f"{daemon_name}_daemon.py")
    else:
        daemon_script = os.path.join(os.path.dirname(__file__), "daemons", f"{daemon_name}_daemon.py")

    if not os.path.exists(daemon_script):
        print(f"ERROR: Daemon script not found: {daemon_script}", file=sys.stderr)
        sys.exit(1)

    import runpy
    idx = sys.argv.index('--run-daemon')
    sys.argv = [daemon_script] + sys.argv[idx+2:]
    runpy.run_path(daemon_script, run_name='__main__')
    sys.exit(0)
# === END DAEMON MODE - NORMAL APP CONTINUES BELOW ===

# === CRITICAL: ALL IMPORTS FIRST ===
import io, time, signal, subprocess, logging, socket, threading, shutil, ctypes, re
from pathlib import Path
import dotenv
from dotenv import load_dotenv

# === PYINSTALLER SAFE LOGGING PATCH ===
_is_pyi_analysis = (
    not getattr(sys, 'frozen', False) and
    'pyimod02_importers' in sys.modules
)
if _is_pyi_analysis:
    for name in list(logging.root.manager.loggerDict):
        _logger = logging.getLogger(name)
        _logger.handlers.clear()
        _logger.propagate = False
    logging.basicConfig(level=logging.CRITICAL, force=True)
    sys.stdout = open(os.devnull, 'w', encoding='utf-8', errors='replace')
    sys.stderr = open(os.devnull, 'w', encoding='utf-8', errors='replace')
# === END PATCH ===

# === WINDOWS UNICODE FIX ===
if sys.platform == "win32":
    for stream in [sys.stdout, sys.stderr]:
        if stream is not None and hasattr(stream, 'buffer'):
            try:
                setattr(sys, stream.name.lstrip('<').rstrip('>'),
                       io.TextIOWrapper(stream.buffer, encoding='utf-8', errors='replace'))
            except: pass
    try: ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except: pass
    os.environ['PYTHONIOENCODING'] = 'utf-8'

# --- PATHS ---
def _resolve_resource_root():
    """
    Walk likely candidates and pick the first that has either models/ or
    llama.cpp/ next to it. Works whether frozen onedir, onefile, or dev.
    """
    candidates = []

    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(Path(meipass))
        candidates.append(Path(meipass).parent)

    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).resolve().parent
    else:
        exe_dir = Path(__file__).resolve().parent
    candidates.append(exe_dir)
    candidates.append(exe_dir / "_internal")
    candidates.append(exe_dir.parent)

    for c in candidates:
        if (c / "models").exists() or (c / "llama.cpp").exists():
            return c

    return exe_dir


def get_base_dir():
    return _resolve_resource_root()

def get_data_dir():
    return Path(os.getenv('LMIM_DATA_DIR')) if os.getenv('LMIM_DATA_DIR') else (
        Path.home() / ".lmim_os" if getattr(sys, 'frozen', False) else get_base_dir() / "data")

BASE_DIR = get_base_dir()
DATA_DIR = get_data_dir()
LOG_DIR  = DATA_DIR / "logs"
DAEMONS_DIR = BASE_DIR / "daemons"
for d in [DATA_DIR, LOG_DIR, DATA_DIR/"models", DATA_DIR/"config"]:
    d.mkdir(parents=True, exist_ok=True)
os.environ['LMIM_DATA_DIR'] = str(DATA_DIR)

# === LOGGING SETUP ===
# Must come BEFORE any _log() calls.
def _safe_log(msg):
    if sys.platform == "win32" and isinstance(msg, str):
        return re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF]+', '', msg)
    return msg

_log_file_handler = logging.FileHandler(LOG_DIR / "launcher.log", encoding='utf-8', errors='replace')
_log_file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s'))
logging.basicConfig(
    level=logging.INFO,
    handlers=[_log_file_handler],
    force=True,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)
logger = logging.getLogger("LMIM-Launcher")

def _log(lvl, msg, *a, **kw):
    try: logger.log(lvl, _safe_log(msg), *a, **kw)
    except: pass

# === STARTUP DIAGNOSTIC ===
# Now safe to call _log — logging is fully configured above.
_log(logging.INFO, "=== STARTUP FILE CHECK (v2.1) ===")
# Quick check for v2.1-specific modules
for _mod in ["app.workspace", "app.rag", "app.tools.scraper_tools",
             "app.tools.contacts_tools", "app.tools.search_files_tool"]:
    _mod_path = BASE_DIR / "app" / (_mod.replace("app.", "").replace(".", "/") + ".py")
    # Also check _internal layout
    if not _mod_path.exists():
        _mod_path = BASE_DIR / "_internal" / "app" / (_mod.replace("app.", "").replace(".", "/") + ".py")
    _log(logging.INFO, f"  {'OK' if _mod_path.exists() else 'WARN'}: {_mod}")
_critical = ["base_library.zip", "python3.dll", "python311.dll",
             "vcruntime140.dll", "vcruntime140_1.dll"]
for _f in _critical:
    _root_path     = BASE_DIR / _f
    _internal_path = BASE_DIR / "_internal" / _f
    _found_root    = _root_path.exists()
    _found_int     = _internal_path.exists()
    if not _found_root and not _found_int:
        _log(logging.ERROR, f"MISSING: {_f} (not in root or _internal)")
    elif _found_root and _found_int:
        _log(logging.INFO,  f"OK: {_f} (both locations)")
    elif _found_root:
        _log(logging.INFO,  f"OK: {_f} (root only)")
    else:
        _log(logging.INFO,  f"OK: {_f} (_internal only)")

_log(logging.INFO, " Starting LMIM OS v2.1.0 (Tezcat Sharpened)...")
_log(logging.INFO, f" Base: {BASE_DIR} | Data: {DATA_DIR}")
_log(logging.INFO, f" frozen={getattr(sys, 'frozen', False)} sys.executable={sys.executable}")
_log(logging.INFO, f" _MEIPASS={getattr(sys, '_MEIPASS', 'N/A')}")
_log(logging.INFO, f" __file__={__file__}")

# === FROZEN-ENV PATH FIX (v2.1) ===
# Ensures torch DLLs / .so files and all RAG packages are findable
# when running as a frozen PyInstaller binary.
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    _meipass = sys._MEIPASS
    # Add bundle root to sys.path if not already there
    if _meipass not in sys.path:
        sys.path.insert(0, _meipass)
    # Windows: add torch\lib to PATH so torch DLLs are loadable
    if sys.platform == 'win32':
        _torch_lib = os.path.join(_meipass, 'torch', 'lib')
        if os.path.isdir(_torch_lib):
            os.environ['PATH'] = _torch_lib + os.pathsep + os.environ.get('PATH', '')
    # Linux: add torch/lib to LD_LIBRARY_PATH (belt-and-suspenders alongside main.js)
    else:
        _torch_lib = os.path.join(_meipass, 'torch', 'lib')
        if os.path.isdir(_torch_lib):
            _cur = os.environ.get('LD_LIBRARY_PATH', '')
            if _torch_lib not in _cur:
                os.environ['LD_LIBRARY_PATH'] = _torch_lib + ':' + _cur if _cur else _torch_lib
# === END FROZEN-ENV PATH FIX ===

# === LOAD .ENV ===
def preload_env():
    """Load .env files: bundle defaults, then user overrides."""
    _scan_dirs = [DATA_DIR / "models", BASE_DIR / "models"]

    def _model_exists(name):
        if not name:
            return False
        candidates = [d / name for d in _scan_dirs]
        if Path(name).is_absolute():
            candidates.append(Path(name))
        return any(p.exists() for p in candidates)

    bundle_env = BASE_DIR / ".env"
    if bundle_env.exists():
        load_dotenv(bundle_env, override=True)
        _log(logging.INFO, f"Loaded base .env: {bundle_env}")

    bundle_model = os.getenv("MODEL_PATH", "")

    user_env = Path.home() / ".lmim_os" / ".env"
    if user_env.exists():
        user_cfg = dotenv.dotenv_values(user_env)
        user_model = user_cfg.get("MODEL_PATH", "")
        load_dotenv(user_env, override=True)
        if user_model and not _model_exists(user_model):
            _log(logging.WARNING,
                 f"User .env MODEL_PATH='{user_model}' not found on disk — "
                 f"ignoring. Update {user_env} to silence this.")
            if bundle_model:
                os.environ["MODEL_PATH"] = bundle_model
            else:
                os.environ.pop("MODEL_PATH", None)
        else:
            _log(logging.INFO, f"Loaded user .env: {user_env}")

    model_name = os.getenv("MODEL_PATH", "")
    if _model_exists(model_name):
        _log(logging.INFO, f"Model resolved: {model_name}")
        return True

    _log(logging.WARNING,
         f"MODEL_PATH='{model_name}' not found. Scanning for any .gguf...")
    for d in _scan_dirs:
        if d.exists():
            ggufs = sorted(d.glob("*.gguf"))
            if ggufs:
                fallback = ggufs[0].name
                os.environ["MODEL_PATH"] = fallback
                _log(logging.INFO, f"Auto-selected model: {fallback}  (from {d})")
                return True

    _log(logging.ERROR,
         f"No .gguf model found in: {[str(d) for d in _scan_dirs]}")
    return False

child_processes = []

def signal_handler(sig, frame):
    _log(logging.WARNING, " Shutting down...")
    for p in reversed(child_processes):
        if p.poll() is None:
            try: p.terminate(); p.wait(timeout=3)
            except: p.kill()
    os._exit(0) if sys.platform == "win32" else sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def kill_proc(name):
    exe = f"{name}.exe" if sys.platform == "win32" else name
    subprocess.run(["taskkill","/F","/IM",exe],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) \
        if sys.platform == "win32" else \
        subprocess.run(["pkill","-f",name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# === LLAMA SERVER ===
def _get_flags(bin_path):
    try:
        h = subprocess.run(
            [str(bin_path), "--help"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        ).stdout or ""
        flags = []
        if "--no-warmup" in h:
            flags.append("--no-warmup")
        if "--chat-template-kwargs" in h:
            flags += ["--chat-template-kwargs", '{"enable_thinking":false}']
        if "--reasoning" in h:
            flags += ["--reasoning", "off"]
        return flags
    except:
        return []

def _find_llama_resources():
    """Find llama-server binary + lib dir. Returns (bin_path, lib_dir) or (None, None)."""
    bin_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    search_roots = []

    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        search_roots.append(Path(meipass))
        search_roots.append(Path(meipass).parent)
    search_roots.append(BASE_DIR)
    search_roots.append(BASE_DIR.parent)
    if getattr(sys, 'frozen', False):
        search_roots.append(Path(sys.executable).resolve().parent)
        search_roots.append(Path(sys.executable).resolve().parent / "_internal")

    seen = set()
    for root in search_roots:
        if root in seen:
            continue
        seen.add(root)
        candidate_bin = root / "llama.cpp" / "build" / "bin" / bin_name
        if candidate_bin.exists():
            lib_dir = root / "lib"
            if not lib_dir.exists():
                lib_dir = candidate_bin.parent
            return candidate_bin, lib_dir

    return None, None


def start_llama_server():
    model = os.getenv("MODEL_PATH", "Qwen3.5-2B-Q4_K_M.gguf")
    model_path = next(
        (p for p in [DATA_DIR / "models" / model, BASE_DIR / "models" / model]
         if p.exists()), None)
    if not model_path:
        _log(logging.WARNING, f"Model '{model}' not found, scanning for any .gguf...")
        for _d in [DATA_DIR / "models", BASE_DIR / "models"]:
            if _d.exists():
                _ggufs = sorted(_d.glob("*.gguf"))
                if _ggufs:
                    model_path = _ggufs[0]
                    os.environ["MODEL_PATH"] = model_path.name
                    _log(logging.INFO, f"Auto-selected model: {model_path}")
                    break
        if not model_path:
            _log(logging.ERROR,
                 f"No model found in {DATA_DIR}/models or {BASE_DIR}/models")
            return False
    _log(logging.INFO, f"Using model: {model_path}")

    bin_path, lib_dir = _find_llama_resources()
    if not bin_path:
        _log(logging.ERROR,
             f"llama-server binary not found anywhere under BASE_DIR={BASE_DIR} "
             f"or _MEIPASS={getattr(sys, '_MEIPASS', 'N/A')}")
        return False
    _log(logging.INFO, f"llama-server: {bin_path}")
    _log(logging.INFO, f"llama lib dir: {lib_dir}")

    kill_proc("llama-server"); time.sleep(1)
    env = os.environ.copy()
    lib = str(lib_dir)
    env["PATH"] = f"{lib};{env.get('PATH', '')}" \
        if sys.platform == "win32" \
        else f"{lib}:{env.get('LD_LIBRARY_PATH', '')}"

    cmd = [
        str(bin_path), "-m", str(model_path),
        "--port",     "8080",
        "--ctx-size", os.getenv("LLAMA_CTX_SIZE", "16000"),
        "--threads",  os.getenv("LLAMA_THREADS",  "6"),
        "--host",     "127.0.0.1",
        "--temp",     os.getenv("LLAMA_TEMP",     "0.3"),
        "--top-p",    os.getenv("LLAMA_TOP_P",    "0.9"),
    ] + _get_flags(bin_path)

    logf = open(LOG_DIR / "llama_server.log", "a", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=logf,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
                      if sys.platform == "win32" else 0,
        preexec_fn=os.setsid if sys.platform != "win32" else None
    )
    child_processes.append(proc)
    _log(logging.INFO, f" llama-server PID:{proc.pid}")

    for i in range(90):
        time.sleep(1)
        if proc.poll() is not None:
            _log(logging.ERROR, f"llama-server exited after {i+1}s")
            logf.close()
            return False
        try:
            s = socket.socket()
            s.settimeout(1)
            if s.connect_ex(('127.0.0.1', 8080)) == 0:
                s.close()
                _log(logging.INFO, f"LLM ready after {i+1}s")
                logf.close()
                return True
            s.close()
        except:
            continue
    _log(logging.ERROR, "LLM timeout")
    logf.close()
    return False

# === FLASK IN THREAD ===
def _flask_wrapper():
    _log(logging.INFO, " Flask thread started")
    _log(logging.INFO,
         f"  frozen={getattr(sys,'frozen',False)}, "
         f"_MEIPASS={getattr(sys,'_MEIPASS','N/A')}")

    try:
        from flask import jsonify
        _log(logging.INFO, " flask.jsonify imported")
    except Exception as e:
        _log(logging.ERROR, f" Flask import failed: {e}", exc_info=True)
        return

    _log(logging.INFO, " Attempting: from app.main import app")
    try:
        from app.main import app
        _log(logging.INFO, " app.main imported successfully")
        _log(logging.INFO,
             f" Registered routes: "
             f"{[rule.rule for rule in app.url_map.iter_rules() if not rule.rule.startswith('/static')]}")
    except ImportError as e:
        _log(logging.ERROR, f" CRITICAL: app.main import failed: {e}", exc_info=True)
        crash = DATA_DIR / "logs" / "flask_import_crash.log"
        with open(crash, "w", encoding="utf-8") as f:
            import traceback
            f.write(traceback.format_exc())
        _log(logging.ERROR, f" Crash log written to: {crash}")
        return
    except Exception as e:
        _log(logging.ERROR,
             f" UNEXPECTED: app.main import failed: {type(e).__name__}: {e}",
             exc_info=True)
        return

    @app.errorhandler(Exception)
    def _err(e):
        import traceback
        tb = traceback.format_exc()
        _log(logging.ERROR, f"Flask unhandled exception: {e}\n{tb}", exc_info=True)
        crash = DATA_DIR / "logs" / "flask_unhandled.log"
        try:
            with open(crash, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n{tb}")
        except:
            pass
        return jsonify({
            "error": "Internal",
            "debug": str(e) if os.getenv('PYWEBVIEW_DEBUG') else None
        }), 500

    _log(logging.INFO,
         f" Calling app.run() host=127.0.0.1:5000 "
         f"frozen={getattr(sys,'frozen',False)}")
    try:
        app.run(port=5000, debug=False, use_reloader=False,
                threaded=True, host='127.0.0.1')
    except OSError as e:
        if "Address already in use" in str(e):
            _log(logging.ERROR, "Port 5000 in use — kill existing process")
        else:
            _log(logging.ERROR, f"app.run OSError: {e}", exc_info=True)
    except Exception as e:
        _log(logging.ERROR, f"app.run crashed: {e}", exc_info=True)
        crash = DATA_DIR / "logs" / "flask_runtime_crash.log"
        with open(crash, "w", encoding="utf-8") as f:
            import traceback
            f.write(traceback.format_exc())
            
            # Add to your startup sequence
def ensure_dependencies():
    import os
    import subprocess
    
    # Check voice binaries
    if not os.path.exists("voice/bin/whisper-cli"):
        print("🔊 Setting up voice...")
        subprocess.run(["bash", "scripts/setup_voice.sh"])
    
    # Check LLM model
    if not any(f.endswith(".gguf") for f in os.listdir("models/") if os.path.isfile(os.path.join("models/", f))):
        print("🤖 Downloading LLM model...")
        subprocess.run(["python3", "scripts/download_model.py"])
    
    # Check embedding model
    if not os.path.exists("models/all-MiniLM-L6-v2"):
        print("📚 Downloading embedding model...")
        subprocess.run(["python3", "scripts/download_embedding_model.py"])
    
    # Check llama.cpp
    if not os.path.exists("bin/llama-server"):
        print("🦙 Setting up llama.cpp...")
        subprocess.run(["bash", "scripts/download_llama_cpp.sh"])

def wait_flask(timeout=20):
    for i in range(timeout):
        try:
            import urllib.request
            urllib.request.urlopen('http://127.0.0.1:5000/api/internal/health',
                                   timeout=1)
            _log(logging.INFO, f" Flask ready after {i+1}s")
            return True
        except Exception as e:
            if i % 5 == 0:
                _log(logging.DEBUG,
                     f"Waiting Flask... ({i+1}/{timeout}) {type(e).__name__}")
            time.sleep(1)
    _log(logging.ERROR, " Flask timeout")
    return False

# === MAIN ===
if __name__ == '__main__':
    if not preload_env():
        _log(logging.ERROR, "Cannot start without a valid model")
        sys.exit(1)

    if not start_llama_server():
        _log(logging.ERROR, "Cannot start without LLM")
        sys.exit(1)

    _log(logging.INFO, "Starting Flask thread...")
    t = threading.Thread(target=_flask_wrapper, daemon=True)
    t.start()

    if not wait_flask(timeout=30):
        _log(logging.ERROR, "Flask failed to start")
        sys.exit(1)

    _log(logging.INFO, "Backend ready — Electron handles the GUI")
    try:
        while True:
            time.sleep(5)
    except (KeyboardInterrupt, SystemExit):
        _log(logging.INFO, "Shutting down...")
        sys.exit(0)
