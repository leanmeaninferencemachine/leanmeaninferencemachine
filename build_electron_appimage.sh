#!/bin/bash
# =============================================================================
# LMIM OS — Electron AppImage Build Script v2.1 (Production Ready)
# =============================================================================

set -euo pipefail

APP_NAME="LMIM_OS"
APP_VERSION="${APP_VERSION:-2.1.0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

echo ""
echo "╔═══════════════════════════════════════════════════════════════════════╗"
echo "║                    LMIM OS Electron Build v${APP_VERSION}                   ║"
echo "╚═══════════════════════════════════════════════════════════════════════╝"
echo "  Project : $PROJECT_ROOT"
echo ""

# =============================================================================
# PHASE 0: VALIDATION
# =============================================================================
log_step "Phase 0: Validating build environment..."

log_info "Checking required tools..."
for cmd in node npm python3 ffmpeg; do
    if ! command -v $cmd &>/dev/null; then
        log_error "$cmd not found. Please install it first."
    fi
done
log_info "✓ All required tools present"

log_info "Checking project files..."
REQUIRED_FILES=(
    "run_app_backend.py"
    "electron/main.js"
    "electron/package.json"
    "daemons/whatsapp-baileys.js"
    ".env"
    "llama.cpp/build/bin/llama-server"
)
for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$PROJECT_ROOT/$file" ]; then
        log_error "Missing required file: $file"
    fi
done
log_info "✓ All project files present"

log_info "Checking Node modules..."
[ -d "$PROJECT_ROOT/node_modules/@whiskeysockets/baileys" ] || log_error "Baileys not installed. Run: npm install @whiskeysockets/baileys qrcode"
[ -d "$PROJECT_ROOT/node_modules/qrcode" ] || log_error "qrcode not installed"
log_info "✓ Node modules present"

log_info "Checking voice components..."
VOICE_DIR="$PROJECT_ROOT/voice"
VOICE_OK=true
if [ ! -d "$VOICE_DIR" ]; then
    log_warn "voice/ directory not found — voice features will be disabled"
    VOICE_OK=false
else
    [ -x "$VOICE_DIR/bin/piper" ] || { log_warn "piper not found"; VOICE_OK=false; }
    [ -x "$VOICE_DIR/bin/whisper-cli" ] || { log_warn "whisper-cli not found"; VOICE_OK=false; }
    [ -d "$VOICE_DIR/espeak-ng-data" ] || { log_warn "espeak-ng-data not found"; VOICE_OK=false; }
    [ -d "$VOICE_DIR/models/tts" ] || { log_warn "TTS models not found"; VOICE_OK=false; }
    [ -d "$VOICE_DIR/models/stt" ] || { log_warn "STT models not found"; VOICE_OK=false; }
    
    TTS_COUNT=$(find "$VOICE_DIR/models/tts" -name "*.onnx" 2>/dev/null | wc -l)
    STT_COUNT=$(find "$VOICE_DIR/models/stt" -name "*.bin" 2>/dev/null | wc -l)
    [ "$TTS_COUNT" -gt 0 ] || log_warn "No TTS models found"
    [ "$STT_COUNT" -gt 0 ] || log_warn "No STT models found"
    
    if [ "$VOICE_OK" = true ]; then
        log_info "✓ Voice components OK ($TTS_COUNT TTS, $STT_COUNT STT)"
    else
        log_warn "Voice components incomplete — voice may not work"
    fi
fi

log_info "Finding Python virtual environment..."
VENV=""
for v in venv_build venv_311 venv .venv; do
    if [ -f "$PROJECT_ROOT/$v/bin/pyinstaller" ] || [ -f "$PROJECT_ROOT/$v/bin/python" ]; then
        VENV="$PROJECT_ROOT/$v"
        break
    fi
done

if [ -z "$VENV" ]; then
    log_error "No venv with pyinstaller found. Run: python3 -m venv venv_build && source venv_build/bin/activate && pip install pyinstaller"
fi
log_info "✓ Using venv: $VENV"

# Ensure pyinstaller wrapper exists
if [ ! -f "$VENV/bin/pyinstaller" ]; then
    log_info "Creating pyinstaller wrapper..."
    cat > "$VENV/bin/pyinstaller" << 'EOF'
#!/bin/bash
export PYINSTALLER_HOOKS_IGNORE="transformers"
exec python -m PyInstaller "$@"
EOF
    chmod +x "$VENV/bin/pyinstaller"
fi

# =============================================================================
# PHASE 1: VERIFY SPEC FILE EXISTS
# =============================================================================
log_step "Phase 1 & 2: Build backend with PyInstaller..."

# ── Pin compatible deps before freezing ──────────────────────────────────────
log_info "Pinning sentence_transformers/huggingface_hub to known-good versions..."
source "$VENV/bin/activate"
pip install -q \
  "sentence-transformers==2.7.0" \
  "transformers==4.38.2" \
  "huggingface-hub==0.23.4" \
  "tokenizers==0.15.2" > /tmp/lmim_pip_pin.log 2>&1 || {
    log_warn "pip pin returned non-zero — check /tmp/lmim_pip_pin.log"
    tail -5 /tmp/lmim_pip_pin.log
}
ST_VER=$(pip show sentence-transformers 2>/dev/null | grep ^Version | awk '{print $2}')
HF_VER=$(pip show huggingface-hub      2>/dev/null | grep ^Version | awk '{print $2}')
deactivate
log_info "  sentence-transformers=$ST_VER  huggingface-hub=$HF_VER"

# ── Verify spec exists (script and spec live in the same dir) ────────────────
SPEC_FILE="$PROJECT_ROOT/lmim_backend.spec"
if [ ! -f "$SPEC_FILE" ]; then
    log_error "lmim_backend.spec not found at: $SPEC_FILE"
fi
log_info "✓ Using spec: $SPEC_FILE"

# ── Run PyInstaller ──────────────────────────────────────────────────────────
log_info "Running PyInstaller (10-20 min)..."
cd "$PROJECT_ROOT"
source "$VENV/bin/activate"
set +e
python -m PyInstaller --clean --noconfirm --log-level WARN \
    lmim_backend.spec 2>&1 | tee pyinstaller_backend.log
_PI_EXIT=${PIPESTATUS[0]}
set -e
deactivate

if [ "${_PI_EXIT:-0}" -ne 0 ]; then
    log_error "PyInstaller failed (exit $_PI_EXIT) — check pyinstaller_backend.log"
fi

# ── Detect layout (PyInstaller 5=flat, 6=_internal) ─────────────────────────
BACKEND_DIST="$PROJECT_ROOT/dist/lmim_backend"
if [ -f "$BACKEND_DIST/lmim_backend" ]; then
    BUNDLE_ROOT="$BACKEND_DIST"
    log_info "Detected PyInstaller 5.x flat layout"
elif [ -f "$BACKEND_DIST/_internal/lmim_backend" ]; then
    BUNDLE_ROOT="$BACKEND_DIST/_internal"
    log_info "Detected PyInstaller 6.x _internal layout"
else
    log_error "No lmim_backend binary found in dist/lmim_backend/"
fi
log_info "Bundle root: $BUNDLE_ROOT"

BACKEND_SIZE=$(du -sh "$BACKEND_DIST" | cut -f1)
log_info "✓ Backend built (size: $BACKEND_SIZE)"

# ── Post-freeze safety net ────────────────────────────────────────────────────
log_info "Applying post-freeze patches and safety net..."
SITE="$VENV/lib/python3.11/site-packages"

# 1. Patch sentence_transformers: remove training-only datasets import
#    DenoisingAutoEncoderDataset -> torch.utils.data crashes in frozen env
ST_INIT="$BUNDLE_ROOT/sentence_transformers/__init__.py"
if [ -f "$ST_INIT" ]; then
    sed -i 's/^from .datasets import.*$/# disabled: training-only import removed for frozen build/' "$ST_INIT"
    log_info "  ✅ sentence_transformers.__init__ patched"

# 5. Patch transformers dependency_versions_check — frozen env has no .dist-info
#    so importlib.metadata.version() raises PackageNotFoundError on every dep check
_TV="$BUNDLE_ROOT/transformers/dependency_versions_check.py"
if [ -f "$_TV" ]; then
    sed -i 's/^        require_version_core(deps\[pkg\])$/        try:\n            require_version_core(deps[pkg])\n        except Exception:\n            pass  # frozen env: no metadata/' "$_TV" 2>/dev/null || \
    python3 -c "
f=open('$_TV'); c=f.read(); f.close()
old='    require_version_core(deps[pkg])'
new='    try:\n        require_version_core(deps[pkg])\n    except Exception:\n        pass'
open('$_TV','w').write(c.replace(old,new))
"
    log_info "  ✅ transformers/dependency_versions_check.py patched"
fi

# 6. Clear sentence_transformers/datasets/__init__.py — pulls in training-only
#    imports (DenoisingAutoEncoderDataset) that cascade into transformers crash
_SD="$BUNDLE_ROOT/sentence_transformers/datasets/__init__.py"
if [ -f "$_SD" ]; then
    echo "# disabled: training-only datasets removed for frozen build" > "$_SD"
    log_info "  ✅ sentence_transformers/datasets/__init__.py cleared"
fi

fi

# 2. Copy any missing pure-Python deps from venv
_copy() {
    local src="$SITE/$1" dst="$BUNDLE_ROOT/$1" label="${2:-$1}"
    if [ ! -e "$dst" ] && [ -e "$src" ]; then
        cp -r "$src" "$dst" && log_info "  ✅ copied $label" || log_warn "  ⚠️  copy failed: $label"
    elif [ -e "$dst" ]; then
        log_info "  ✓  $label present"
    else
        log_warn "  ⚠️  $label not in venv"
    fi
}
_copy "typing_extensions.py"  "typing_extensions"
_copy "tqdm"                  "tqdm"
_copy "huggingface_hub"       "huggingface_hub"
_copy "safetensors"           "safetensors"
_copy "filelock"              "filelock"
_copy "regex"                 "regex"
_copy "packaging"             "packaging"
_copy "transformers"          "transformers"
_copy "tokenizers"            "tokenizers"
_copy "numpy"                 "numpy"
_copy "scipy"                 "scipy"
_copy "sklearn"               "sklearn"

# 3. Copy all top-level torch .so files from venv into torch/lib/ 
#    (PyInstaller may have put them in root; torch expects them in torch/lib)
TORCH_SRC="$SITE/torch/lib"
TORCH_DST="$BUNDLE_ROOT/torch/lib"
if [ -d "$TORCH_SRC" ] && [ -d "$TORCH_DST" ]; then
    while IFS= read -r -d '' _so; do
        _bn=$(basename "$_so")
        if [ ! -e "$TORCH_DST/$_bn" ]; then
            cp "$_so" "$TORCH_DST/" && log_info "  ✅ torch/lib/$_bn"
        fi
    done < <(find "$TORCH_SRC" -maxdepth 1 -type f \( -name "*.so" -o -name "*.so.*" \) -print0 2>/dev/null)
fi
# Move any torch .so files accidentally in bundle root to torch/lib/
for _so in libtorch*.so libc10*.so libshm*.so libgomp*.so; do
    if [ -f "$BUNDLE_ROOT/$_so" ] && [ -d "$TORCH_DST" ]; then
        cp "$BUNDLE_ROOT/$_so" "$TORCH_DST/" 2>/dev/null || true
    fi
done

# 4. Final verification
log_info "Verifying RAG dependencies in bundle..."
_MISS=0
for _dep in \
    "sentence_transformers/__init__.py" \
    "torch/__init__.py" \
    "torch/lib/libtorch_cpu.so" \
    "torch/_C.cpython-311-x86_64-linux-gnu.so" \
    "transformers/__init__.py" \
    "tokenizers/__init__.py" \
    "tqdm/__init__.py" \
    "typing_extensions.py" \
    "numpy/__init__.py" \
    "voice/bin/piper" \
    "voice/bin/whisper-cli" \
    "llama.cpp/build/bin/llama-server"; do
    if [ -e "$BUNDLE_ROOT/$_dep" ]; then
        log_info "  ✅ $_dep"
    else
        log_warn "  ❌ MISSING: $_dep"
        _MISS=$((_MISS+1))
    fi
done
if [ "$_MISS" -gt 0 ]; then
    log_warn "$_MISS dep(s) still missing after safety net"
else
    log_info "All dependencies confirmed ✅"
fi

log_step "Phase 3: Copying Electron files..."

# Copy pre-built main.js (has correct PYTHONPATH + LD_LIBRARY_PATH for flat/internal layout)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
for _f in main.js package.json; do
    if [ -f "$SCRIPT_DIR/$_f" ]; then
        cp "$SCRIPT_DIR/$_f" "$PROJECT_ROOT/electron/$_f"
        log_info "  ✓ Copied $_f from build dir"
    else
        log_info "  ✓ Using existing electron/$_f"
    fi
done

# Verify preload.js is in package.json
if ! grep -q '"preload.js"' "$PROJECT_ROOT/electron/package.json"; then
    sed -i '/"files": \[/a\      "preload.js",' "$PROJECT_ROOT/electron/package.json"
    log_info "  ✓ preload.js added to package.json"
fi

# =============================================================================
# PHASE 4: STAGE BACKEND
# =============================================================================
log_step "Phase 4: Staging backend for Electron..."

log_info "Copying backend to electron/backend/..."
mkdir -p "$PROJECT_ROOT/electron/backend"
rsync -a --delete "$BACKEND_DIST/" "$PROJECT_ROOT/electron/backend/"
log_info "✓ Backend staged"

# =============================================================================
# PHASE 5: STAGE PLAYWRIGHT BROWSERS
# =============================================================================
log_step "Phase 5: Staging Playwright browsers..."

PW_SRC="$HOME/.cache/ms-playwright"
PW_DEST="$PROJECT_ROOT/electron/backend/playwright_driver/browser_packages"

if [ -d "$PW_SRC" ]; then
    mkdir -p "$PW_DEST"
    STAGED=false
    while IFS= read -r -d '' rev_dir; do
        rev_name=$(basename "$rev_dir")
        if cp -r "$rev_dir" "$PW_DEST/" 2>/dev/null; then
            log_info "  ✓ Staged: $rev_name"
            STAGED=true
        fi
    done < <(find "$PW_SRC" -maxdepth 1 -type d \( -name "chromium-*" -o -name "chrome-headless_shell-*" -o -name "ffmpeg-*" \) -print0 2>/dev/null)
    
    if [ "$STAGED" = true ]; then
        log_info "✓ Playwright browsers staged"
    else
        log_warn "No Playwright revisions found"
    fi
else
    log_warn "Playwright cache not found — will use system cache at runtime"
fi

# =============================================================================
# PHASE 6: STAGE BAILEYS AND NODE MODULES
# =============================================================================
log_step "Phase 6: Staging Baileys daemon and Node modules..."

mkdir -p "$PROJECT_ROOT/electron/backend/daemons"
cp "$PROJECT_ROOT/daemons/whatsapp-baileys.js" "$PROJECT_ROOT/electron/backend/daemons/"
log_info "✓ whatsapp-baileys.js staged"

NODE_MODULES_DEST="$PROJECT_ROOT/electron/baileys_modules"
mkdir -p "$NODE_MODULES_DEST"

if [ -d "$PROJECT_ROOT/node_modules" ]; then
    log_info "Syncing node_modules (this may take a minute)..."
    rsync -a --delete \
        --exclude=".cache" --exclude="*.md" --exclude="*.map" \
        --exclude="test/" --exclude="tests/" --exclude="docs/" \
        --exclude=".bin/" --exclude="example/" --exclude="examples/" \
        "$PROJECT_ROOT/node_modules/" "$NODE_MODULES_DEST/"
    NODE_SIZE=$(du -sh "$NODE_MODULES_DEST" | cut -f1)
    log_info "✓ node_modules staged (size: $NODE_SIZE)"
else
    log_error "node_modules not found — run: npm install"
fi

# =============================================================================
# PHASE 7: BUILD ELECTRON APPIMAGE
# =============================================================================
log_step "Phase 7: Building Electron AppImage..."

cd "$PROJECT_ROOT/electron"

sed -i 's/"version": "2.0.0"/"version": "2.1.0"/' package.json 2>/dev/null || true
npm install --prefer-offline 2>&1 | tail -5

log_info "Running electron-builder (this takes 5-10 minutes)..."
npx electron-builder build --linux AppImage --publish=never 2>&1 | tee eb-build.log

cd "$PROJECT_ROOT"

RAW_APPIMAGE=$(find electron/dist_electron -name "*.AppImage" -type f 2>/dev/null | head -1)

if [ -z "$RAW_APPIMAGE" ]; then
    log_error "electron-builder did not produce an AppImage"
fi

log_info "✓ electron-builder produced: $(basename "$RAW_APPIMAGE")"

# =============================================================================
# PHASE 8: PATCH APPIMAGE WITH CUSTOM APPRUN
# =============================================================================
log_step "Phase 8: Patching AppImage with custom AppRun..."

FINAL_OUT="${PROJECT_ROOT}/${APP_NAME}_${APP_VERSION}_electron.AppImage"

"$RAW_APPIMAGE" --appimage-extract >/dev/null 2>&1 || {
    log_warn "Could not extract AppImage — using raw version"
    cp "$RAW_APPIMAGE" "$FINAL_OUT"
    chmod +x "$FINAL_OUT"
    log_info "✓ AppImage ready (unpatched)"
    exit 0
}

cat > squashfs-root/AppRun << 'APPRUN_EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VOICE_BIN="$SCRIPT_DIR/resources/backend/voice/bin"
if [ -d "$VOICE_BIN" ]; then
    export LD_LIBRARY_PATH="$VOICE_BIN${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export ESPEAK_DATA_PATH="$SCRIPT_DIR/resources/backend/voice/espeak-ng-data"
fi

ELECTRON_BIN=""
for candidate in \
    "$SCRIPT_DIR/lmim-os" \
    "$SCRIPT_DIR/LMIM_OS" \
    "$SCRIPT_DIR/usr/bin/lmim-os" \
    "$SCRIPT_DIR/usr/bin/LMIM_OS" \
    "$SCRIPT_DIR/AppDir/usr/bin/lmim-os" \
    "$SCRIPT_DIR/AppDir/usr/bin/LMIM_OS"
do
    [ -x "$candidate" ] && { ELECTRON_BIN="$candidate"; break; }
done

if [ -z "$ELECTRON_BIN" ]; then
    ELECTRON_BIN=$(find "$SCRIPT_DIR" -maxdepth 3 -type f -executable -name "electron" | head -1)
fi

if [ -z "$ELECTRON_BIN" ] || [ ! -x "$ELECTRON_BIN" ]; then
    echo "❌ Could not find Electron binary" >&2
    exit 1
fi

export PLAYWRIGHT_BROWSERS_PATH="$SCRIPT_DIR/resources/backend/playwright_driver/browser_packages"
export NODE_PATH="$SCRIPT_DIR/resources/node_modules"
export ELECTRON_OZONE_PLATFORM_HINT=auto
export LMIM_DATA_DIR="${HOME}/.lmim_os"
mkdir -p "$LMIM_DATA_DIR"

exec "$ELECTRON_BIN" "$@"
APPRUN_EOF

chmod +x squashfs-root/AppRun

log_info "Rebuilding patched AppImage..."
APPIMAGE_TOOL="$PROJECT_ROOT/appimagetool-x86_64.AppImage"

if [ -x "$APPIMAGE_TOOL" ]; then
    "$APPIMAGE_TOOL" squashfs-root/ "$FINAL_OUT" 2>&1 || {
        log_warn "appimagetool failed — using raw AppImage"
        cp "$RAW_APPIMAGE" "$FINAL_OUT"
    }
elif command -v appimagetool &>/dev/null; then
    appimagetool squashfs-root/ "$FINAL_OUT" 2>&1 || cp "$RAW_APPIMAGE" "$FINAL_OUT"
else
    log_warn "appimagetool not found — using raw AppImage"
    cp "$RAW_APPIMAGE" "$FINAL_OUT"
fi

rm -rf squashfs-root/
chmod +x "$FINAL_OUT" 2>/dev/null || true

# =============================================================================
# PHASE 9: FINAL OUTPUT
# =============================================================================
FINAL_SIZE=$(du -sh "$FINAL_OUT" | cut -f1)
SHA256=$(sha256sum "$FINAL_OUT" | cut -d' ' -f1)

echo ""
echo "╔═══════════════════════════════════════════════════════════════════════╗"
echo "║                    ✅ BUILD COMPLETE!                                 ║"
echo "╚═══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "  File   : $(basename "$FINAL_OUT")"
echo "  Size   : $FINAL_SIZE"
echo "  SHA256 : $SHA256"
echo ""
echo "  Test   : ./$(basename "$FINAL_OUT")"
echo ""

if [ -f "$FINAL_OUT" ] && [ -x "$FINAL_OUT" ]; then
    log_info "AppImage is ready. Run the test command above to launch."
else
    log_error "AppImage verification failed"
fi
