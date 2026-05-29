# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# LMIM OS — PyInstaller 5.13.2 spec (flat layout, no collect_all)
# Clean build: rm -rf build/ dist/ pyi_hooks/ before running
# =============================================================================
import sys, os, glob
sys.setrecursionlimit(1000000)

VENV  = '/home/ais/LMIM_base/venv_build/lib/python3.11/site-packages'
VOICE = '/home/ais/LMIM_base/voice'

# ── Datas ─────────────────────────────────────────────────────────────────────
datas = [
    ('app',           'app'),
    ('app/templates', 'app/templates'),
    ('app/static',    'app/static'),
    ('daemons',       'daemons'),
    ('scripts',       'scripts'),
    ('config',        'config'),
    ('models',        'models'),
    ('.env',          '.'),
    ('readme.md',     '.'),
    (f'{VOICE}/espeak-ng-data', 'voice/espeak-ng-data'),
    (f'{VOICE}/models/tts',    'voice/models/tts'),
    (f'{VOICE}/models/stt',    'voice/models/stt'),
]

# ── Binaries ──────────────────────────────────────────────────────────────────
binaries = [
    ('llama.cpp/build/bin/llama-server',     'llama.cpp/build/bin'),
    ('llama.cpp/build/bin/libmtmd.so.0',     'lib'),
    ('llama.cpp/build/bin/libggml.so.0',     'lib'),
    ('llama.cpp/build/bin/libggml-base.so.0','lib'),
    ('llama.cpp/build/bin/libggml-cpu.so.0', 'lib'),
    ('llama.cpp/build/bin/libllama.so.0',    'lib'),
    (f'{VOICE}/bin',                         'voice/bin'),
    ('/usr/bin/ffmpeg',                      '.'),
    ('/lib/x86_64-linux-gnu/libsndfile.so.1','.'),
]

# ── Torch: walk filesystem (avoids import-time segfault) ──────────────────────
_torch_root = os.path.join(VENV, 'torch')
if os.path.isdir(_torch_root):
    _torch_lib = os.path.join(_torch_root, 'lib')
    if os.path.isdir(_torch_lib):
        for _f in os.listdir(_torch_lib):
            if _f.endswith('.so') or '.so.' in _f:
                binaries.append((os.path.join(_torch_lib, _f), 'torch/lib'))
    # _C extension — fixed name for CPython 3.11 x86_64
    _c_so = os.path.join(_torch_root, '_C.cpython-311-x86_64-linux-gnu.so')
    if os.path.exists(_c_so):
        binaries.append((_c_so, 'torch'))
    _torch_count = len([b for b in binaries if 'torch' in b[1]])
    print(f"✅ torch: {_torch_count} files collected from filesystem")

# ── tokenizers .so — must be on disk, not in PYZ ─────────────────────────────
_tok_so = os.path.join(VENV, 'tokenizers', 'tokenizers.cpython-311-x86_64-linux-gnu.so')
if os.path.exists(_tok_so):
    binaries.append((_tok_so, 'tokenizers'))
    print("✅ tokenizers: .so binary collected")

# ── Hidden imports ────────────────────────────────────────────────────────────
hiddenimports = [
    # App
    'app.main', 'app.router', 'app.model_interface', 'app.config',
    'app.memory_functions', 'app.voice_service', 'app.workspace', 'app.rag',
    'app.agents.whatsapp_agent', 'app.agents.telegram_agent',
    'app.tools.scraper_tools', 'app.tools.contacts_tools',
    'app.tools.search_files_tool',
    # Web
    'flask', 'flask_cors', 'dotenv',
    # Audio
    'soundfile', '_cffi_backend', 'cffi',
    # Multiprocessing — required by PyInstaller on Linux
    'multiprocessing', 'multiprocessing.popen_spawn_posix',
    # RAG
    'sentence_transformers', 'sentence_transformers.models',
    'sentence_transformers.util', 'sentence_transformers.SentenceTransformer',
    'sentence_transformers.LoggingHandler', 'sentence_transformers.readers',
    'sentence_transformers.cross_encoder', 'sentence_transformers.cross_encoder.CrossEncoder',
    'transformers', 'tokenizers',
    'torch', 'torch.nn', 'torch.nn.functional',
    'torch.utils.data', 'torch.utils.data.dataloader',
    'torch.utils.data.dataset', 'torch.utils.data.sampler',
    'torch.cuda', 'torch.backends', 'torch.backends.cudnn',
    'pypdf', 'PIL', 'PIL.Image',
    'numpy', 'scipy', 'sklearn',
    # HuggingFace
    'tqdm', 'tqdm.auto', 'tqdm.std',
    'huggingface_hub', 'huggingface_hub.utils', 'huggingface_hub.file_download',
    'safetensors', 'safetensors.torch',
    'filelock', 'packaging',
    # Network
    'requests', 'urllib3', 'certifi', 'charset_normalizer',
    'aiohttp', 'aiofiles', 'yarl', 'multidict', 'frozenlist',
    # Misc
    'regex', 'joblib', 'threadpoolctl', 'pyparsing', 'click',
    'typing_extensions',
]

# ── Collect submodules + data files (safe packages only) ──────────────────────
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

# sentence_transformers: walk disk — collect_submodules triggers hf_hub crash
_st_base = os.path.join(VENV, 'sentence_transformers')
if os.path.isdir(_st_base):
    for _root, _dirs, _files in os.walk(_st_base):
        for _file in _files:
            if _file.endswith('.py') or _file.endswith('.json'):
                _src = os.path.join(_root, _file)
                _rel = os.path.relpath(os.path.dirname(_src), VENV)
                datas.append((_src, _rel))
    print("✅ sentence_transformers: collected from disk")

for _pkg in ['transformers', 'tokenizers', 'scipy', 'sklearn']:
    try:
        hiddenimports += collect_submodules(_pkg)
        datas         += collect_data_files(_pkg)
        binaries      += collect_dynamic_libs(_pkg)
        print(f"✅ {_pkg}: collected")
    except Exception as _e:
        print(f"⚠️  {_pkg}: {_e}")

for _pkg in ['tqdm', 'huggingface_hub', 'safetensors', 'filelock']:
    try:
        datas += collect_data_files(_pkg)
    except Exception:
        pass

# ── No-op hook: prevents dataclasses.__version__ AttributeError ───────────────
_hooks_dir = os.path.join(os.path.dirname(os.path.abspath(SPEC)), 'pyi_hooks')
os.makedirs(_hooks_dir, exist_ok=True)
_th = os.path.join(_hooks_dir, 'hook-transformers.py')
with open(_th, 'w') as _fh:
    _fh.write("# no-op: overrides broken hook-transformers in pyinstaller-hooks-contrib\n")
    _fh.write("hiddenimports = []\nexcludedimports = []\ndatas = []\nbinaries = []\n")
print("✅ hook-transformers.py: no-op override written")

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    ['run_app_backend.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[_hooks_dir],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5', 'pywebview', 'gi', 'tkinter',
        'torch.distributed', 'torch.testing',
        'IPython', 'matplotlib', 'pandas',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='lmim_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        # UPX on torch/ggml libs causes segfaults — exclude them
        'libtorch_cpu.so', 'libtorch_python.so', 'libtorch.so',
        'libggml*.so*', 'libllama*.so*', 'libmtmd*.so*',
    ],
    name='lmim_backend',
)

# ── Post-build verification ───────────────────────────────────────────────────
# PyInstaller 5.x flat layout: all packages in dist/lmim_backend/ directly
_dist = os.path.join('dist', 'lmim_backend')
_required = [
    'lmim_backend',
    'sentence_transformers/__init__.py',
    'torch/__init__.py',
    'torch/lib/libtorch_cpu.so',
    'torch/_C.cpython-311-x86_64-linux-gnu.so',
    'transformers/__init__.py',
    'tokenizers/__init__.py',
    'tokenizers/tokenizers.cpython-311-x86_64-linux-gnu.so',
    'tqdm/__init__.py',
    'typing_extensions.py',
    'huggingface_hub/__init__.py',
    'safetensors/__init__.py',
    'numpy/__init__.py',
    'scipy/__init__.py',
    'sklearn/__init__.py',
    'voice/bin/piper',
    'voice/bin/whisper-cli',
    'llama.cpp/build/bin/llama-server',
]
print("\n=== Post-build verification (PyInstaller 5.x flat) ===")
_missing = []
for _f in _required:
    _p = os.path.join(_dist, _f)
    if os.path.exists(_p):
        print(f"  ✅ {_f}")
    else:
        print(f"  ❌ MISSING: {_f}")
        _missing.append(_f)
if _missing:
    print(f"\n⚠️  {len(_missing)} item(s) missing — check above")
else:
    print("\n✅ All items present in dist/lmim_backend/")
print("=" * 54 + "\n")
