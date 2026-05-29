#!/usr/bin/env python3
"""
LMIM OS — Backend-only launcher for Electron mode.
This runs Flask + llama-server but does NOT open any Qt window.
The window is managed by Electron (main.js).

Usage:
  python3 run_app_backend.py          # dev mode
  ./lmim_backend                      # frozen AppImage mode
"""

import os
import sys
import time
import signal
import socket
import subprocess
import threading
import logging
import shutil
from pathlib import Path

# ==============================================================================
# STEP -1 — Aggressive runtime library path discovery (MUST BE EARLY)
# ==============================================================================
def _discover_and_set_library_paths():
    """
    Scans the entire bundle for shared libraries and adds all directories
    containing .so files to LD_LIBRARY_PATH. This ensures libraries are found
    regardless of where PyInstaller placed them (flat or _internal/ layout).
    """
    if not getattr(sys, 'frozen', False):
        return  # Only needed in frozen mode
    
    bundle = sys._MEIPASS
    lib_dirs = set()
    
    # 1. Known critical paths (always add if they exist)
    critical_paths = [
        'torch/lib',
        'lib',
        'llama.cpp/build/bin',
        'voice/bin',
        'llama.cpp/build/lib',
    ]
    
    for rel_path in critical_paths:
        full_path = os.path.join(bundle, rel_path)
        if os.path.isdir(full_path):
            lib_dirs.add(full_path)
            print(f"[PathFix] Added critical: {rel_path}")
    
    # 2. Scan entire bundle for any directory containing .so files
    print("[PathFix] Scanning for shared libraries...")
    for root, dirs, files in os.walk(bundle):
        # Check if this directory contains any .so files
        has_so = any(f.endswith('.so') or '.so.' in f for f in files)
        if has_so and root not in lib_dirs:
            lib_dirs.add(root)
            rel = os.path.relpath(root, bundle)
            if rel != '.':
                print(f"[PathFix] Found lib dir: {rel}")
    
    # 3. Also add parent directories of common patterns
    for pattern in ['*_C*.so', 'libtorch*.so', 'libc10*.so', 'libggml*.so']:
        import glob
        for so_file in glob.glob(os.path.join(bundle, '**', pattern), recursive=True):
            parent = os.path.dirname(so_file)
            if parent not in lib_dirs:
                lib_dirs.add(parent)
                print(f"[PathFix] Added from pattern {pattern}: {os.path.relpath(parent, bundle)}")
    
    # 4. Set LD_LIBRARY_PATH
    existing = os.environ.get('LD_LIBRARY_PATH', '')
    new_paths = ':'.join(lib_dirs)
    
    if new_paths:
        os.environ['LD_LIBRARY_PATH'] = f"{new_paths}:{existing}" if existing else new_paths
        print(f"[PathFix] LD_LIBRARY_PATH set with {len(lib_dirs)} directories")
    
    # 5. Also set Python path
    python_dirs = [bundle]
    for subdir in ['app', 'daemons', 'scripts']:
        p = os.path.join(bundle, subdir)
        if os.path.isdir(p):
            python_dirs.append(p)
    
    existing_py = os.environ.get('PYTHONPATH', '')
    new_py = ':'.join(python_dirs)
    os.environ['PYTHONPATH'] = f"{new_py}:{existing_py}" if existing_py else new_py
    print(f"[PathFix] PYTHONPATH set")

# Run the discovery immediately
_discover_and_set_library_paths()

# ==============================================================================
# STEP 0 — Paths
# ==============================================================================
def _base() -> Path:
    return Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent

def _data() -> Path:
    p = (Path.home() / '.lmim_os') if getattr(sys, 'frozen', False) else (_base() / 'data')
    p.mkdir(parents=True, exist_ok=True)
    return p

BASE_DIR = _base()
DATA_DIR = _data()
LOG_DIR  = DATA_DIR / 'logs'

for d in [LOG_DIR, DATA_DIR / 'models']:
    d.mkdir(parents=True, exist_ok=True)

os.environ['LMIM_DATA_DIR'] = str(DATA_DIR)

# ==============================================================================
# STEP 1 — Logging
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_DIR / 'launcher.log'),
        logging.StreamHandler()
    ],
)
logger = logging.getLogger('LMIM-Backend')
logger.info('🚀 LMIM OS backend starting (Electron mode)...')
logger.info(f'  Base : {BASE_DIR}')
logger.info(f'  Data : {DATA_DIR}')

# ==============================================================================
# STEP 2 — .env
# ==============================================================================
from dotenv import load_dotenv

def preload_env():
    user_env   = Path.home() / '.lmim_os' / '.env'
    bundle_env = BASE_DIR / '.env'
    src = user_env if user_env.exists() else (bundle_env if bundle_env.exists() else None)
    if not src:
        logger.warning('⚠️  No .env found — using defaults.')
        return
    load_dotenv(src, override=True)
    logger.info(f'✅ Loaded .env: {src}')
    if src == bundle_env:
        try:
            user_env.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(bundle_env, user_env)
            bid = BASE_DIR / 'config' / 'user_identity.json'
            uid = Path.home() / '.lmim_os' / 'config' / 'user_identity.json'
            if bid.exists() and not uid.exists():
                uid.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(bid, uid)
        except Exception as e:
            logger.warning(f'Config copy failed: {e}')

preload_env()

# ==============================================================================
# Resolve bundled Playwright path in frozen/AppImage mode
# ==============================================================================
if getattr(sys, 'frozen', False):
    base = Path(sys._MEIPASS)
    for candidate in [
        base / 'playwright_driver' / 'browser_packages',
        base.parent / 'resources' / 'backend' / 'playwright_driver' / 'browser_packages',
        base / 'resources' / 'backend' / 'playwright_driver' / 'browser_packages',
    ]:
        if candidate.exists():
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(candidate)
            logger.info(f'📦 Bundled Playwright path: {candidate}')
            break
    else:
        logger.warning('⚠️  Bundled Playwright browsers not found — falling back to system cache')

# ==============================================================================
# STEP 2b — Voice environment (frozen/AppImage mode)
# ==============================================================================
# When running as a frozen AppImage, voice/bin is inside sys._MEIPASS.
# Set LD_LIBRARY_PATH so piper can find its .so libs (ONNX, phonemize etc.)
# and ESPEAK_DATA_PATH so espeak-ng finds its phoneme data.
# In dev mode these are set by the Flask subprocess call in main.py,
# but we also set them here so the backend process inherits them globally.
def _setup_voice_env():
    voice_bin  = BASE_DIR / 'voice' / 'bin'
    espeak_dir = BASE_DIR / 'voice' / 'espeak-ng-data'
    if voice_bin.exists():
        current_ld = os.environ.get('LD_LIBRARY_PATH', '')
        voice_bin_str = str(voice_bin)
        if voice_bin_str not in current_ld:
            os.environ['LD_LIBRARY_PATH'] = f"{voice_bin_str}:{current_ld}" if current_ld else voice_bin_str
        logger.info(f'🎤 Voice bin dir: {voice_bin}')
    if espeak_dir.exists():
        os.environ['ESPEAK_DATA_PATH'] = str(espeak_dir)
        logger.info(f'🎤 ESPEAK_DATA_PATH: {espeak_dir}')

_setup_voice_env()

# ==============================================================================
# STEP 3 — Process helpers
# ==============================================================================
child_processes = []

def signal_handler(sig, frame):
    logger.warning('🛑 Shutting down backend...')
    for p in reversed(child_processes):
        try:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=3)
        except Exception:
            try: p.kill()
            except Exception: pass
    sys.exit(0)

def kill_by_name(name: str):
    subprocess.run(['pkill', '-f', name],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

def _find_python() -> str:
    for candidate in ['python3', 'python3.11', 'python3.10', 'python3.12', 'python']:
        try:
            r = subprocess.run([candidate, '--version'], capture_output=True, timeout=3)
            if r.returncode == 0 and b'Python 3' in (r.stdout + r.stderr):
                logger.info(f'✅ Python interpreter: {candidate}')
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    logger.warning('⚠️  No python3 found — daemon launch may fail')
    return 'python3'

PYTHON_BIN = _find_python()

def kill_port(port: int):
    try:
        subprocess.run(['fuser', '-k', f'{port}/tcp'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
    except Exception:
        pass

def wait_for_port(port: int, timeout: int = 30) -> bool:
    for i in range(timeout):
        try:
            s = socket.socket()
            s.settimeout(1)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                s.close()
                logger.info(f'✅ Port {port} ready after {i+1}s')
                return True
            s.close()
        except Exception:
            pass
        time.sleep(1)
    logger.error(f'❌ Port {port} not ready after {timeout}s')
    return False

def _verify_node(node_path: str) -> bool:
    """
    Actually execute the node binary to verify it works.
    os.access() is not enough — on Fedora with SELinux enforcing,
    os.access() returns True for squashfs binaries but exec is blocked.
    This catches that case and any other execution failures.
    """
    try:
        r = subprocess.run(
            [node_path, '--version'],
            capture_output=True,
            timeout=5,
        )
        if r.returncode == 0:
            ver = (r.stdout or r.stderr).decode(errors='replace').strip()
            logger.info(f'✅ Node.js verified: {node_path} → {ver}')
            return True
        logger.debug(f'Node {node_path} returned code {r.returncode}')
        return False
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.debug(f'Node {node_path} not executable: {e}')
        return False
    except subprocess.TimeoutExpired:
        logger.debug(f'Node {node_path} timed out')
        return False
    except Exception as e:
        logger.debug(f'Node {node_path} check failed: {e}')
        return False

def _find_node() -> str:
    """
    Find a working Node.js binary.

    Priority order:
    1. System node via shutil.which() — always SELinux-safe, correct distro context
    2. Bundled node_runtime inside AppImage — fallback for systems without node
    3. Known absolute paths (cross-distro coverage)
    4. Bare 'node' via PATH as last resort

    On Fedora with SELinux enforcing: executing binaries from /tmp/.mount_XXX/
    (the squashfs mount point) MAY be blocked even if the file is executable.
    System node is always preferred on Linux for this reason.
    We VERIFY with --version before accepting any candidate.
    """
    candidates = []

    # 1. System node — PATH-aware, SELinux-safe on all distros
    for name in ['node', 'nodejs']:
        found = shutil.which(name)
        if found:
            candidates.append(found)

    # 2. Bundled runtime (AppImage) — works when system node absent
    bundled = str(BASE_DIR / 'node_runtime')
    if bundled not in candidates:
        candidates.append(bundled)

    # 3. Known absolute paths — covers edge cases
    for abs_path in [
        '/usr/bin/node', '/usr/local/bin/node',
        '/usr/bin/nodejs', '/usr/local/bin/nodejs',
        '/opt/homebrew/bin/node',    # macOS Homebrew
        '/snap/bin/node',            # Ubuntu snap
        str(BASE_DIR / 'bin' / 'node'),
    ]:
        if abs_path not in candidates:
            candidates.append(abs_path)

    for c in candidates:
        if Path(c).is_file() and _verify_node(c):
            return c

    # Last resort: bare 'node' — let the OS find it
    logger.warning('⚠️  No verified Node.js found — using bare "node" as fallback')
    return 'node'

# ==============================================================================
# STEP 4 — llama-server
# ==============================================================================
def start_llama_server() -> bool:
    bundle_root = BASE_DIR
    model_path  = None

    for search in [DATA_DIR / 'models', bundle_root / 'models']:
        fname = os.getenv('MODEL_PATH', '')
        if fname:
            c = search / fname
            if c.exists():
                model_path = c
                break
        if not model_path and search.exists():
            hits = list(search.glob(f"{fname.split('.')[0]}*.gguf")) if fname else []
            if not hits:
                hits = list(search.glob('*.gguf'))
            if hits:
                model_path = hits[0]
                logger.info(f'🔍 Using fallback model: {model_path.name}')
                break

    if not model_path:
        logger.error('❌ No .gguf model found.')
        return False

    for k in ('MODEL_PATH', 'MODEL_NAME', 'PLANNER_MODEL_NAME', 'CHAT_MODEL_NAME'):
        os.environ[k] = model_path.name

    llama_bin = bundle_root / 'llama.cpp' / 'build' / 'bin' / 'llama-server'
    if not llama_bin.exists():
        logger.error('❌ llama-server binary not found.')
        return False

    kill_by_name('llama-server')
    time.sleep(1)

    env = os.environ.copy()
    voice_bin_dir = str(bundle_root / 'voice' / 'bin')
    # Auto-detect CUDA lib path so whisper-cli and piper inherit GPU support.
    # whisper-cli resolves ggml-cuda via its own rpath, but still needs
    # libcudart/libcublas on LD_LIBRARY_PATH to initialise the CUDA backend.
    import glob as _glob
    _cuda_lib = next(
        (p for p in
         sorted(_glob.glob('/usr/local/cuda-12*/lib64'), reverse=True)
         + ['/usr/local/cuda/lib64']
         if Path(p).exists()),
        ''
    )

    # ── Also set on os.environ so Flask thread inherits CUDA path ─────────────
    # run_app_backend builds a local `env` dict for llama-server's Popen, but
    # Flask runs as a thread and inherits os.environ directly. whisper-cli is
    # called inside Flask with os.environ.copy() so it needs CUDA here too.
    if _cuda_lib:
        _cur = os.environ.get('LD_LIBRARY_PATH', '')
        _voice = str(bundle_root / 'voice' / 'bin')
        _combined = ':'.join(p for p in [_voice, _cuda_lib, _cur] if p)
        os.environ['LD_LIBRARY_PATH'] = _combined

    ld_parts = [
        str(bundle_root / 'llama.cpp' / 'build' / 'bin'),
        str(bundle_root / 'lib'),
        voice_bin_dir,
        _cuda_lib,                            # ← CUDA libs for whisper GPU
        os.environ.get('LD_LIBRARY_PATH', ''),
    ]
    env['LD_LIBRARY_PATH'] = ':'.join(p for p in ld_parts if p)
    # Voice env — piper needs these even when spawned from Flask subprocess
    espeak_dir = bundle_root / 'voice' / 'espeak-ng-data'
    if espeak_dir.exists():
        env['ESPEAK_DATA_PATH'] = str(espeak_dir)

    cpu_count    = os.cpu_count() or 8
    auto_threads = str(min(12, max(4, int(cpu_count * 0.6))))
    
        # ── GPU auto-detect ──────────────────────────────────────────────────
    gpu_layers = os.getenv('LLAMA_GPU_LAYERS', 'auto')
    use_gpu = False
    if gpu_layers != '0':
        try:
            import subprocess as _sp
            r = _sp.run(['nvidia-smi'], capture_output=True, timeout=3)
            use_gpu = (r.returncode == 0)
        except Exception:
            pass
    if use_gpu:
        ngl = '99' if gpu_layers == 'auto' else gpu_layers
        logger.info(f'⚡ CUDA GPU detected — offloading {ngl} layers')
    # ─────────────────────────────────────────────────────────────────────

    cmd = [
        str(llama_bin), '-m', str(model_path), '--port', '8080',
        '--ctx-size',    os.getenv('LLAMA_CTX_SIZE',    '16192'),
        '--batch-size',  os.getenv('LLAMA_BATCH_SIZE',  '512'),
        '--ubatch-size', os.getenv('LLAMA_UBATCH_SIZE', '256'),
        '--threads',       os.getenv('LLAMA_THREADS',       auto_threads),
        '--threads-batch', os.getenv('LLAMA_THREADS_BATCH', auto_threads),
        '--temp',  os.getenv('LLAMA_TEMP',  '0.4'),
        '--top-p', os.getenv('LLAMA_TOP_P', '0.9'),
        '--host', '127.0.0.1',
        '--reasoning', 'off',  
    ]

    try:
        cpuinfo = Path('/proc/cpuinfo').read_text().lower()
        if 'avx2' in cpuinfo and 'fma' in cpuinfo:
            cmd += ['--flash-attn', 'auto']
            logger.info('⚡ Flash attention enabled')
    except Exception:
        pass

    logger.info(f'🚀 llama cmd: {" ".join(cmd)}')
    log_path = LOG_DIR / 'llama_server.log'
    lf = open(log_path, 'a')
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=lf,
        stderr=subprocess.STDOUT, env=env, preexec_fn=os.setsid,
    )
    child_processes.append(proc)

    for i in range(90):
        time.sleep(1)
        if proc.poll() is not None:
            tail = Path(log_path).read_text().splitlines()[-20:] if Path(log_path).exists() else []
            logger.error('❌ llama-server exited:\n' + '\n'.join(tail))
            lf.close()
            return False
        try:
            s = socket.socket(); s.settimeout(1)
            if s.connect_ex(('127.0.0.1', 8080)) == 0:
                s.close(); logger.info(f'✅ LLM ready ({i+1}s)'); lf.close(); return True
            s.close()
        except Exception:
            pass
        if use_gpu:
            cmd += ['-ngl', ngl]
        cmd += ['--reasoning', 'off']

    logger.error('❌ llama-server timeout')
    lf.close()
    return False
    
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

# ==============================================================================
# STEP 5 — Flask
# ==============================================================================
def start_flask():
    from app.main import app
    app.run(port=5000, debug=False, use_reloader=False, threaded=True, host='127.0.0.1')

# ==============================================================================
# STEP 6 — Main
# ==============================================================================
if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info('🔍 Clearing ports 5000 and 8080...')
    kill_port(5000)
    kill_port(8080)
    time.sleep(0.5)

    # Propagate display/session vars to daemons
    for var in ['DISPLAY', 'XDG_SESSION_TYPE', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR']:
        if var in os.environ:
            os.environ.setdefault(var, os.environ[var])
        if var not in os.environ and var == 'DISPLAY':
            os.environ['DISPLAY'] = ':0'
    logger.info(f"🖥️  Propagated env: DISPLAY={os.environ.get('DISPLAY')} XDG_SESSION_TYPE={os.environ.get('XDG_SESSION_TYPE')}")

    # Export daemon info
    daemon_script = BASE_DIR / 'daemons' / 'whatsapp_daemon.py'
    os.environ['LMIM_PYTHON_BIN']      = PYTHON_BIN
    os.environ['LMIM_DAEMON_DIR']      = str(BASE_DIR / 'daemons')
    os.environ['LMIM_WHATSAPP_DAEMON'] = str(daemon_script)

    # ── Baileys daemon paths ────────────────────────────────────────────────
    baileys_script = BASE_DIR / 'daemons' / 'whatsapp-baileys.js'
    os.environ['LMIM_BAILEYS_SCRIPT'] = str(baileys_script)

    # Find and verify node — SELinux-safe detection with actual exec test
    node_bin = _find_node()
    os.environ['LMIM_NODE_BIN'] = node_bin

    # NODE_PATH for Baileys modules
    node_modules_path = str(BASE_DIR / 'node_modules')
    os.environ['LMIM_NODE_MODULES'] = node_modules_path

    logger.info(f'📦 Baileys: script={baileys_script}')
    logger.info(f'📦 Node: {node_bin}')
    logger.info(f'📦 Modules: {node_modules_path}')
    logger.info(f'📋 Daemon env: PYTHON={PYTHON_BIN}')
    logger.info(f'📋 PLAYWRIGHT_BROWSERS_PATH={os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "NOT SET")}')
    logger.info(f'📋 XDG_RUNTIME_DIR={os.environ.get("XDG_RUNTIME_DIR", "NOT SET")}')

    # Start LLM
    start_llama_server()

    # Start Flask
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    if not wait_for_port(5000, timeout=30):
        logger.error('❌ Flask failed to start.')
        sys.exit(1)

    logger.info('✅ Backend ready on http://127.0.0.1:5000 — waiting for Electron...')

    try:
        while True:
            time.sleep(10)
            try:
                s = socket.socket(); s.settimeout(2)
                if s.connect_ex(('127.0.0.1', 5000)) != 0:
                    logger.error('❌ Flask health check failed — exiting')
                    sys.exit(1)
                s.close()
            except Exception:
                pass
    except KeyboardInterrupt:
        signal_handler(None, None)
