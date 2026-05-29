# build_windows.ps1 -- LMIM OS v2.1.0 (Windows) -- Electron + Baileys
# PyInstaller >= 6.0: _internal subdir layout.
# Includes: RAG (sentence_transformers + torch CPU), Workspace, Scraper, Contacts
# RAG fix: sitecustomize.py + .dist-info copy (importlib.metadata monkey-patch)
# FIX: Include real torch.distributed (not excluded) - required for torch.utils.data
param([string]$Version = "2.1.0")

$APP_NAME     = "LMIM_OS"
$APP_VERSION  = $Version
$PROJECT_ROOT = $PSScriptRoot

Write-Host "+----------------------------------------------+" -ForegroundColor Cyan
Write-Host "|  LMIM OS Windows Build  v$APP_VERSION        " -ForegroundColor Cyan
Write-Host "+----------------------------------------------+" -ForegroundColor Cyan
Write-Host "  Project : $PROJECT_ROOT"

# -- Defender exclusion --------------------------------------------------------
Add-MpPreference -ExclusionPath $PROJECT_ROOT -ErrorAction SilentlyContinue
Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\pyinstaller" -ErrorAction SilentlyContinue

# -- Validate source tree ------------------------------------------------------
Write-Host "`n[>>] Validating..." -ForegroundColor Yellow
foreach ($f in @("run_app.py","electron\main.js","electron\package.json",
                 ".env","daemons\whatsapp-baileys.js")) {
    if (-not (Test-Path "$PROJECT_ROOT\$f")) {
        Write-Host "[FAIL] Missing: $f" -ForegroundColor Red; exit 1
    }
}
if (-not (Test-Path "$PROJECT_ROOT\node_modules\@whiskeysockets\baileys")) {
    Write-Host "[FAIL] Baileys not installed -- run: npm install" -ForegroundColor Red; exit 1
}
$llamaBin = "$PROJECT_ROOT\llama.cpp\build\bin"
if (-not (Test-Path "$llamaBin\llama-server.exe")) {
    Write-Host "[FAIL] llama-server.exe not found at $llamaBin" -ForegroundColor Red; exit 1
}
Write-Host "[*] Source validation OK" -ForegroundColor Green

# -- Find venv -----------------------------------------------------------------
$VENV = $null
foreach ($v in @("venv_windows","venv_build","venv_311","venv",".venv")) {
    if (Test-Path "$PROJECT_ROOT\$v\Scripts\pyinstaller.exe") { $VENV = "$PROJECT_ROOT\$v"; break }
}
if (-not $VENV) { Write-Host "[FAIL] No venv with pyinstaller found" -ForegroundColor Red; exit 1 }
Write-Host "[*] venv : $VENV" -ForegroundColor Green

$SITE = "$VENV\Lib\site-packages"

# -- Pin RAG deps to known-good versions ---------------------------------------
Write-Host "`n[>>] Pinning RAG dependencies to known-good versions..." -ForegroundColor Yellow
& "$VENV\Scripts\pip.exe" install -q `
    "sentence-transformers==2.7.0" `
    "transformers==4.38.2" `
    "huggingface-hub==0.23.4" `
    "tokenizers==0.15.2" 2>&1 | Where-Object { $_ -match "Installing|Successfully|already" }
Write-Host "[*] RAG deps pinned" -ForegroundColor Green

# -- Locate Python runtime files -----------------------------------------------
$pythonHome = & "$VENV\Scripts\python.exe" -c "import sys; print(sys.base_prefix)"
$pythonDll  = Get-ChildItem "$pythonHome\python3*.dll" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $pythonDll) { Write-Host "[FAIL] python3*.dll not found in $pythonHome" -ForegroundColor Red; exit 1 }
Write-Host "[*] Python home : $pythonHome" -ForegroundColor Green
Write-Host "[*] Python DLL  : $($pythonDll.FullName)" -ForegroundColor Green

$pythonDLLsDir = "$pythonHome\DLLs"

function Resolve-PythonFile($name) {
    foreach ($dir in @($pythonDLLsDir, $pythonHome, "$VENV\Scripts", "$VENV\Lib\site-packages")) {
        $hit = Get-ChildItem $dir -Filter $name -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

$addBinaryArgs = @()
foreach ($f in @("libcrypto-3.dll","libssl-3.dll","libffi-8.dll",
                 "select.pyd","_socket.pyd","_ssl.pyd","_ctypes.pyd","_hashlib.pyd")) {
    $p = Resolve-PythonFile $f
    if ($p) {
        Write-Host "  [OK] $f" -ForegroundColor Green
        $addBinaryArgs += "--add-binary"; $addBinaryArgs += "${p};."
    } else {
        Write-Host "  [WARN] $f not found" -ForegroundColor Yellow
    }
}
foreach ($dll in @("MSVCP140.dll","VCOMP140.DLL","concrt140.dll","MSVCP140_1.dll","MSVCP140_2.dll")) {
    $p = Join-Path "$env:SystemRoot\System32" $dll
    if (Test-Path $p) {
        $addBinaryArgs += "--add-binary"; $addBinaryArgs += "${p};."
    }
}
foreach ($cudaDll in @("cublas64_13.dll","cublasLt64_13.dll")) {
    $p = Join-Path $llamaBin $cudaDll
    if (Test-Path $p) {
        $addBinaryArgs += "--add-binary"; $addBinaryArgs += "${p};llama.cpp\build\bin"
    }
}

# -- Cleanup -------------------------------------------------------------------
Write-Host "`n[>>] Cleaning previous build artifacts..." -ForegroundColor Yellow
foreach ($d in @("build","dist\lmim_backend","electron\dist_electron","electron\backend","electron\baileys_modules")) {
    if (Test-Path "$PROJECT_ROOT\$d") {
        Remove-Item -Recurse -Force "$PROJECT_ROOT\$d" -ErrorAction SilentlyContinue
    }
}
Get-ChildItem -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-Process -Name "llama-server","LMIM_OS" -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# -- Create sitecustomize.py (RAG fix: patches importlib.metadata BEFORE PYZ) --
Write-Host "`n[>>] Creating sitecustomize.py (RAG frozen-env fix)..." -ForegroundColor Yellow
$siteCustomize = @"
# sitecustomize.py -- LMIM OS v2.1 Windows
# Python loads this BEFORE any frozen PYZ imports.
# Patches importlib.metadata.version so transformers/sentence_transformers
# never raise PackageNotFoundError in the frozen bundle.
import importlib.metadata as _im

_orig = _im.version

def _safe_version(package):
    try:
        return _orig(package)
    except Exception:
        return '0.0.0'

_im.version = _safe_version
import sys as _sys
if getattr(_sys, 'frozen', False):
    print('[LMIM] sitecustomize: importlib.metadata.version patched for frozen env')
"@
$siteCustomize | Out-File -FilePath "$PROJECT_ROOT\sitecustomize.py" -Encoding UTF8
Write-Host "[*] sitecustomize.py created" -ForegroundColor Green

# -- Step 1: Freeze Flask backend with PyInstaller ----------------------------
Write-Host "`n[>>] Step 1: Freezing Flask backend (v2.1)..." -ForegroundColor Cyan

# Torch lib dir for Windows PATH staging
$torchLibDir = "$SITE\torch\lib"

# Build sentence_transformers data args (disk walk, avoids import crash)
$stDataArgs = @()
$stSrc = "$SITE\sentence_transformers"
if (Test-Path $stSrc) {
    $stDataArgs += "--add-data"; $stDataArgs += "${stSrc};sentence_transformers"
}

# Embedding model if pre-downloaded
$embModelArgs = @()
$embModel = "$PROJECT_ROOT\models\all-MiniLM-L6-v2"
if (Test-Path $embModel) {
    $embModelArgs += "--add-data"; $embModelArgs += "${embModel};models\all-MiniLM-L6-v2"
    Write-Host "  [OK] Embedding model found, will bundle it" -ForegroundColor Green
} else {
    Write-Host "  [WARN] Embedding model not found -- RAG will download on first use" -ForegroundColor Yellow
    Write-Host "         To pre-bundle: python -c `"from sentence_transformers import SentenceTransformer; m=SentenceTransformer('all-MiniLM-L6-v2'); m.save('models/all-MiniLM-L6-v2')`"" -ForegroundColor Gray
}

$pyiArgs = @(
    "--clean","--noconfirm","--onedir","--noupx","--noconsole","--log-level","WARN",
    "--name","lmim_backend",
    "--icon","$PROJECT_ROOT\app\static\logo.ico",
    # Core app data
    "--add-data","$PROJECT_ROOT\app;app",
    "--add-data","$PROJECT_ROOT\app\templates;app\templates",
    "--add-data","$PROJECT_ROOT\app\static;app\static",
    "--add-data","$PROJECT_ROOT\daemons;daemons",
    "--add-data","$PROJECT_ROOT\scripts;scripts",
    "--add-data","$PROJECT_ROOT\config;config",
    "--add-data","$PROJECT_ROOT\.env;.",
    # sitecustomize.py (critical for RAG)
    "--add-data","$PROJECT_ROOT\sitecustomize.py;.",
    # Python runtime
    "--add-binary","$($pythonDll.FullName);.",
    "--add-binary","$pythonHome\vcruntime140.dll;.",
    "--add-binary","$pythonHome\vcruntime140_1.dll;.",
    # llama binaries
    "--add-binary","$llamaBin\llama-server.exe;llama.cpp\build\bin",
    "--add-binary","$llamaBin\ggml.dll;llama.cpp\build\bin",
    "--add-binary","$llamaBin\llama.dll;llama.cpp\build\bin",
    "--add-binary","$llamaBin\ggml-base.dll;llama.cpp\build\bin",
    "--add-binary","$llamaBin\ggml-cpu.dll;llama.cpp\build\bin",
    "--add-binary","$llamaBin\mtmd.dll;llama.cpp\build\bin",
    # Torch CPU libraries (collected via PATH, needed for RAG embeddings)
    # v2.1 hidden imports -- all new modules
    "--hidden-import","app.main",
    "--hidden-import","app.router",
    "--hidden-import","app.model_interface",
    "--hidden-import","app.config",
    "--hidden-import","app.memory_functions",
    "--hidden-import","app.voice_service",
    "--hidden-import","app.workspace",
    "--hidden-import","app.rag",
    "--hidden-import","app.agents.whatsapp_agent",
    "--hidden-import","app.agents.telegram_agent",
    "--hidden-import","app.tools.scraper_tools",
    "--hidden-import","app.tools.contacts_tools",
    "--hidden-import","app.tools.search_files_tool",
    # Framework
    "--hidden-import","flask",
    "--hidden-import","flask_cors",
    "--hidden-import","dotenv",
    "--hidden-import","psutil",
    "--hidden-import","psutil._psutil_windows",
    "--hidden-import","multiprocessing",
    "--hidden-import","multiprocessing.popen_spawn_win32",
    # RAG stack
    "--hidden-import","sentence_transformers",
    "--hidden-import","sentence_transformers.models",
    "--hidden-import","sentence_transformers.util",
    "--hidden-import","sentence_transformers.SentenceTransformer",
    "--hidden-import","sentence_transformers.LoggingHandler",
    "--hidden-import","sentence_transformers.readers",
    "--hidden-import","sentence_transformers.cross_encoder",
    "--hidden-import","sentence_transformers.cross_encoder.CrossEncoder",
    "--hidden-import","transformers",
    "--hidden-import","transformers.models",
    "--hidden-import","transformers.models.auto",
    "--hidden-import","transformers.models.bert",
    "--hidden-import","transformers.models.roberta",
    "--hidden-import","transformers.utils",
    "--hidden-import","tokenizers",
    "--hidden-import","torch",
    "--hidden-import","torch.nn",
    "--hidden-import","torch.nn.functional",
    "--hidden-import","torch.utils.data",
    "--hidden-import","torch.utils.data.dataloader",
    "--hidden-import","torch.utils.data.dataset",
    "--hidden-import","torch.utils.data.sampler",
    "--hidden-import","torch.backends",
    "--hidden-import","numpy",
    "--hidden-import","numpy.core",
    "--hidden-import","scipy",
    "--hidden-import","scipy.spatial",
    "--hidden-import","scipy.spatial.distance",
    "--hidden-import","scipy.special",
    "--hidden-import","sklearn",
    "--hidden-import","sklearn.metrics",
    "--hidden-import","sklearn.metrics.pairwise",
    "--hidden-import","pypdf",
    "--hidden-import","tqdm",
    "--hidden-import","tqdm.auto",
    "--hidden-import","filelock",
    "--hidden-import","huggingface_hub",
    "--hidden-import","huggingface_hub.utils",
    "--hidden-import","safetensors",
    "--hidden-import","safetensors.torch",
    "--hidden-import","typing_extensions",
    "--hidden-import","packaging",
    "--hidden-import","packaging.version",
    "--hidden-import","regex",
    "--hidden-import","PIL",
    "--hidden-import","PIL.Image",
    "--hidden-import","soundfile",
    "--hidden-import","_cffi_backend",
    "--hidden-import","cffi",
    # Collect full packages
    "--collect-all","flask",
    "--collect-all","flask_cors",
    "--collect-all","psutil",
    "--collect-all","transformers",
    "--collect-all","tokenizers",
    "--collect-all","scipy",
    "--collect-all","sklearn",
    "--collect-all","huggingface_hub",
    "--collect-all","safetensors",
    "--collect-all","tqdm",
    "--collect-all","filelock",
    "--collect-all","pypdf",
    # Exclusions (NOTE: torch.distributed is NOT excluded - it's required!)
    "--exclude-module","pywebview",
    "--exclude-module","playwright",
    "--exclude-module","PyQt5",
    "--exclude-module","pythonnet",
    "--exclude-module","gi",
    "--exclude-module","tkinter",
    "--exclude-module","caffe2",
    "--exclude-module","tensorboard",
    "$PROJECT_ROOT\run_app.py"
) + $addBinaryArgs + $stDataArgs + $embModelArgs

$t0 = Get-Date
& "$VENV\Scripts\python.exe" -m PyInstaller @pyiArgs 2>&1 |
    Tee-Object "$PROJECT_ROOT\pyinstaller_backend.log" |
    Where-Object { $_ -match "WARNING|ERROR|completed|failed|Traceback" }
Write-Host "PyInstaller: $([math]::Round(((Get-Date)-$t0).TotalSeconds))s" -ForegroundColor Gray

$distDir = "$PROJECT_ROOT\dist\lmim_backend"
if (-not (Test-Path "$distDir\lmim_backend.exe")) {
    Write-Host "[FAIL] PyInstaller did not produce lmim_backend.exe" -ForegroundColor Red
    Get-Content "$PROJECT_ROOT\pyinstaller_backend.log" -Tail 30
    exit 1
}
Write-Host "[*] Backend frozen OK" -ForegroundColor Green

# -- Step 1.5: Detect layout and locate runtime root --------------------------
Write-Host "`n[>>] Step 1.5: Detecting PyInstaller layout..." -ForegroundColor Cyan
$internalDir = "$distDir\_internal"
if (Test-Path "$internalDir\base_library.zip") {
    $runtimeRoot = $internalDir
    Write-Host "  Layout: _internal  (PyInstaller >= 6.0)" -ForegroundColor Green
} elseif (Test-Path "$distDir\base_library.zip") {
    $runtimeRoot = $distDir
    Write-Host "  Layout: flat  (PyInstaller < 6.0)" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] base_library.zip not found" -ForegroundColor Red; exit 1
}
Write-Host "  Runtime root: $runtimeRoot" -ForegroundColor Green

# -- Step 1.6: Post-freeze RAG patches ----------------------------------------
Write-Host "`n[>>] Step 1.6: Applying post-freeze RAG patches..." -ForegroundColor Cyan

# 1. Patch sentence_transformers __init__.py — remove training-only datasets import
$stInit = "$runtimeRoot\sentence_transformers\__init__.py"
if (Test-Path $stInit) {
    $content = Get-Content $stInit -Raw
    $patched = $content -replace "^from \.datasets import.*$",
        "# disabled: training-only import removed for frozen build"
    if ($patched -ne $content) {
        $patched | Out-File -FilePath $stInit -Encoding UTF8
        Write-Host "  [OK] sentence_transformers.__init__.py patched" -ForegroundColor Green
    } else {
        Write-Host "  [OK] sentence_transformers already patched or pattern changed" -ForegroundColor Gray
    }
} else {
    Write-Host "  [WARN] sentence_transformers __init__.py not found in bundle" -ForegroundColor Yellow
}

# 2. Also patch transformers __init__.py — disable version dependency check
$trInit = "$runtimeRoot\transformers\__init__.py"
if (Test-Path $trInit) {
    $content = Get-Content $trInit -Raw
    $patched = $content -replace "from \. import dependency_versions_check",
        "# LMIM: from . import dependency_versions_check  # disabled: frozen env"
    if ($patched -ne $content) {
        $patched | Out-File -FilePath $trInit -Encoding UTF8
        Write-Host "  [OK] transformers.__init__.py: dependency_versions_check disabled" -ForegroundColor Green
    }
}

# 3. Copy ALL .dist-info from venv into runtime root
Write-Host "  Copying .dist-info directories (importlib.metadata fix)..." -ForegroundColor Yellow
$copied = 0
Get-ChildItem "$SITE" -Filter "*.dist-info" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $dst = "$runtimeRoot\$($_.Name)"
    if (-not (Test-Path $dst)) {
        Copy-Item $_.FullName $dst -Recurse -Force -ErrorAction SilentlyContinue
        $copied++
    }
}
Write-Host "  [OK] $copied .dist-info directories copied" -ForegroundColor Green

# 4. Copy missing pure-Python deps from venv (safety net)
function Copy-IfMissing($name, $label) {
    $src = "$SITE\$name"
    $dst = "$runtimeRoot\$name"
    if ((Test-Path $src) -and (-not (Test-Path $dst))) {
        Copy-Item $src $dst -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  [OK] $label copied" -ForegroundColor Green
    } elseif (Test-Path $dst) {
        Write-Host "  [OK] $label present" -ForegroundColor Gray
    } else {
        Write-Host "  [WARN] $label not in venv: $src" -ForegroundColor Yellow
    }
}
Copy-IfMissing "typing_extensions.py" "typing_extensions"
Copy-IfMissing "tqdm"                 "tqdm"
Copy-IfMissing "huggingface_hub"      "huggingface_hub"
Copy-IfMissing "safetensors"          "safetensors"
Copy-IfMissing "filelock"             "filelock"
Copy-IfMissing "regex"                "regex"
Copy-IfMissing "packaging"            "packaging"
Copy-IfMissing "transformers"         "transformers"
Copy-IfMissing "tokenizers"           "tokenizers"
Copy-IfMissing "numpy"                "numpy"
Copy-IfMissing "scipy"                "scipy"
Copy-IfMissing "sklearn"              "sklearn"
Copy-IfMissing "sentence_transformers" "sentence_transformers"

# 5. Copy torch DLLs into bundle so they're discoverable without CUDA
$torchLib = "$SITE\torch\lib"
$torchDst = "$runtimeRoot\torch\lib"
if ((Test-Path $torchLib) -and (Test-Path $torchDst)) {
    Get-ChildItem "$torchLib\*.dll" -ErrorAction SilentlyContinue | ForEach-Object {
        if (-not (Test-Path "$torchDst\$($_.Name)")) {
            Copy-Item $_.FullName "$torchDst\" -Force
        }
    }
    Write-Host "  [OK] torch DLLs synced to torch\lib" -ForegroundColor Green
}

# 6. CRITICAL: Copy real torch/distributed (required for torch.utils.data.dataloader)
Write-Host "  Copying real torch/distributed (required for RAG)..." -ForegroundColor Yellow
$torchDistSrc = "$SITE\torch\distributed"
$torchDistDst = "$runtimeRoot\torch\distributed"
if (Test-Path $torchDistSrc) {
    if (Test-Path $torchDistDst) { Remove-Item $torchDistDst -Recurse -Force -ErrorAction SilentlyContinue }
    Copy-Item $torchDistSrc $torchDistDst -Recurse -Force
    $fileCount = (Get-ChildItem $torchDistDst -Recurse -File | Measure-Object).Count
    $sizeMB = [math]::Round((Get-ChildItem $torchDistDst -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
    Write-Host "  [OK] Copied real torch/distributed ($fileCount files, $sizeMB MB)" -ForegroundColor Green
} else {
    Write-Host "  [WARN] torch/distributed not found in venv at $torchDistSrc" -ForegroundColor Yellow
}

# 7. Verify RAG deps
Write-Host "`n  Verifying RAG dependencies..." -ForegroundColor Yellow
$ragMissing = 0
@(
    "sentence_transformers\__init__.py",
    "torch\__init__.py",
    "transformers\__init__.py",
    "tokenizers\__init__.py",
    "numpy\__init__.py",
    "tqdm\__init__.py",
    "typing_extensions.py",
    "huggingface_hub\__init__.py",
    "sitecustomize.py",
    "torch\distributed\__init__.py"
) | ForEach-Object {
    $p = "$runtimeRoot\$_"
    if (Test-Path $p) {
        Write-Host "    [OK] $_" -ForegroundColor Green
    } else {
        Write-Host "    [FAIL] MISSING: $_" -ForegroundColor Red
        $ragMissing++
    }
}
if ($ragMissing -gt 0) {
    Write-Host "  [WARN] $ragMissing RAG deps still missing -- check venv" -ForegroundColor Yellow
} else {
    Write-Host "  All RAG dependencies confirmed" -ForegroundColor Green
}

# Ensure llama-server.exe is present
$llamaInDist = "$runtimeRoot\llama.cpp\build\bin\llama-server.exe"
if (-not (Test-Path $llamaInDist)) {
    Write-Host "  llama-server.exe missing from runtime root -- copying" -ForegroundColor Yellow
    $llamaDestDir = "$runtimeRoot\llama.cpp\build\bin"
    New-Item -ItemType Directory -Force -Path $llamaDestDir | Out-Null
    Copy-Item "$llamaBin\llama-server.exe" "$llamaDestDir\" -Force
    Get-ChildItem "$llamaBin\*.dll" -ErrorAction SilentlyContinue |
        ForEach-Object { Copy-Item $_.FullName "$llamaDestDir\" -Force }
}
Write-Host "[*] Post-freeze patches complete" -ForegroundColor Green

# -- Step 2: Stage model -------------------------------------------------------
Write-Host "`n[>>] Step 2: Staging model..." -ForegroundColor Cyan
$MODEL_DEST = "$runtimeRoot\models"
New-Item -ItemType Directory -Force -Path $MODEL_DEST | Out-Null

$MODEL_SRC = Get-ChildItem "$PROJECT_ROOT\models" -Filter "*.gguf" -ErrorAction SilentlyContinue |
             Select-Object -First 1 -ExpandProperty FullName
if ($MODEL_SRC) {
    $modelName = Split-Path $MODEL_SRC -Leaf
    $modelDest = "$MODEL_DEST\$modelName"
    if (-not (Test-Path $modelDest)) {
        Write-Host "  Copying model..." -ForegroundColor Yellow
        Copy-Item $MODEL_SRC $modelDest -Force
    }
    $modelMB = [math]::Round((Get-Item $modelDest).Length / 1MB)
    Write-Host "[*] Model staged: $modelName ($modelMB MB)" -ForegroundColor Green
} else {
    Write-Host "[WARN] No .gguf model found" -ForegroundColor Yellow
}

# -- Step 2.5: Stage voice engine ----------------------------------------------
Write-Host "`n[>>] Step 2.5: Staging voice engine..." -ForegroundColor Cyan
$VOICE_SRC  = "$PROJECT_ROOT\voice"
$VOICE_DEST = "$runtimeRoot\voice"
if (Test-Path "$VOICE_SRC\bin") {
    New-Item -ItemType Directory -Force -Path "$VOICE_DEST\bin" | Out-Null
    Copy-Item "$VOICE_SRC\bin\*" "$VOICE_DEST\bin\" -Recurse -Force
    $n = (Get-ChildItem "$VOICE_DEST\bin" -File -ErrorAction SilentlyContinue | Measure-Object).Count
    Write-Host "  [OK] voice/bin staged ($n files)" -ForegroundColor Green
} else {
    Write-Host "  [WARN] voice\bin not found" -ForegroundColor Yellow
}
if (Test-Path "$VOICE_SRC\models") {
    New-Item -ItemType Directory -Force -Path "$VOICE_DEST\models" | Out-Null
    Copy-Item "$VOICE_SRC\models\*" "$VOICE_DEST\models\" -Recurse -Force
    $mb = [math]::Round((Get-ChildItem "$VOICE_DEST\models" -Recurse -ErrorAction SilentlyContinue |
                          Measure-Object Length -Sum).Sum / 1MB)
    Write-Host "  [OK] voice/models staged ($mb MB)" -ForegroundColor Green
}

# -- Step 3: Install Electron deps ---------------------------------------------
Write-Host "`n[>>] Step 3: Installing Electron deps..." -ForegroundColor Cyan
Push-Location "$PROJECT_ROOT\electron"
npm install --prefer-offline 2>&1 | Out-Null
Pop-Location
Write-Host "[*] Electron deps installed" -ForegroundColor Green

# -- Step 4: Stage backend into Electron resources ----------------------------
Write-Host "`n[>>] Step 4: Staging backend..." -ForegroundColor Cyan
$BACKEND_DEST = "$PROJECT_ROOT\electron\backend"
if (Test-Path $BACKEND_DEST) { Remove-Item -Recurse -Force $BACKEND_DEST }
Copy-Item $distDir $BACKEND_DEST -Recurse -Force
Write-Host "[*] Backend staged" -ForegroundColor Green

Remove-Item -Recurse -Force "$PROJECT_ROOT\dist" -ErrorAction SilentlyContinue
$freeGB = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
Write-Host "[*] dist\ removed -- ${freeGB} GB free" -ForegroundColor Green

# -- Step 5: Stage Baileys daemon + node.exe -----------------------------------
Write-Host "`n[>>] Step 5: Staging Baileys..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "$BACKEND_DEST\daemons" | Out-Null
Copy-Item "$PROJECT_ROOT\daemons\whatsapp-baileys.js" "$BACKEND_DEST\daemons\" -Force
$nodeBin = (Get-Command node -ErrorAction SilentlyContinue).Source
if ($nodeBin) {
    Copy-Item $nodeBin "$BACKEND_DEST\node.exe" -Force
    Write-Host "  [OK] node.exe staged" -ForegroundColor Green
} else {
    Write-Host "[FAIL] node.exe not found in PATH" -ForegroundColor Red; exit 1
}
$BAILEYS_DEST = "$PROJECT_ROOT\electron\baileys_modules"
if (Test-Path $BAILEYS_DEST) { Remove-Item -Recurse -Force $BAILEYS_DEST }
New-Item -ItemType Directory -Force -Path $BAILEYS_DEST | Out-Null
robocopy "$PROJECT_ROOT\node_modules" $BAILEYS_DEST /E /NFL /NDL /NJH /NJS /XD ".cache" /XF "*.md" "*.map" | Out-Null
$baileysMB = [math]::Round((Get-ChildItem $BAILEYS_DEST -Recurse -ErrorAction SilentlyContinue |
                              Measure-Object Length -Sum).Sum / 1MB)
Write-Host "[*] Baileys staged ($baileysMB MB)" -ForegroundColor Green

# -- Step 5.5: Pre-cache rcedit ------------------------------------------------
Write-Host "`n[>>] Pre-caching rcedit..." -ForegroundColor Cyan
$rceditDir = "$env:LOCALAPPDATA\electron-builder\Cache\winCodeSign\winCodeSign-2.6.0"
if (-not (Test-Path "$rceditDir\rcedit-x64.exe")) {
    New-Item -ItemType Directory -Force -Path $rceditDir | Out-Null
    $darwinLib = "$rceditDir\darwin\10.12\lib"
    New-Item -ItemType Directory -Force -Path $darwinLib | Out-Null
    "" | Set-Content "$darwinLib\libcrypto.dylib"
    "" | Set-Content "$darwinLib\libssl.dylib"
    try {
        Invoke-WebRequest -Uri "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe" `
                          -OutFile "$rceditDir\rcedit-x64.exe" -UseBasicParsing
        Write-Host "  [OK] rcedit cached" -ForegroundColor Green
    } catch {
        Write-Host "  [WARN] rcedit download failed -- build may still succeed" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [OK] rcedit already cached" -ForegroundColor Green
}

# -- Step 5.9: Pre-packaging validation ----------------------------------------
Write-Host "`n[>>] Validating staged assets..." -ForegroundColor Cyan
$stagedBackend = $BACKEND_DEST
if (Test-Path "$stagedBackend\_internal\base_library.zip") {
    $stagedRuntime = "$stagedBackend\_internal"
} else {
    $stagedRuntime = $stagedBackend
}

$failed = $false
$mandatory = @(
    "$stagedBackend\lmim_backend.exe",
    "$stagedRuntime\base_library.zip",
    "$stagedRuntime\python3.dll",
    "$stagedRuntime\python311.dll",
    "$stagedRuntime\vcruntime140.dll",
    "$stagedRuntime\vcruntime140_1.dll",
    "$stagedRuntime\llama.cpp\build\bin\llama-server.exe",
    "$stagedRuntime\sentence_transformers\__init__.py",
    "$stagedRuntime\sitecustomize.py",
    "$stagedBackend\daemons\whatsapp-baileys.js",
    "$stagedBackend\node.exe",
    "$PROJECT_ROOT\electron\baileys_modules\@whiskeysockets\baileys",
    "$stagedRuntime\torch\distributed\__init__.py"
)
foreach ($c in $mandatory) {
    $ok  = Test-Path $c
    $rel = $c.Replace($PROJECT_ROOT, "").TrimStart("\")
    Write-Host "  $(if($ok){'[OK]  '}else{'[FAIL]'}) $rel"
    if (-not $ok) { $failed = $true }
}
if ($failed) {
    Write-Host "`n[FAIL] Critical assets missing -- aborting." -ForegroundColor Red; exit 1
}
Write-Host "[*] All mandatory assets present" -ForegroundColor Green

# -- Step 6: Build Electron installer ------------------------------------------
Write-Host "`n[>>] Step 6: Building Electron installer..." -ForegroundColor Cyan
Push-Location "$PROJECT_ROOT\electron"
$env:APP_VERSION = $APP_VERSION
$env:CSC_LINK = $env:CSC_KEY_PASSWORD = $env:WIN_CSC_LINK = $env:WIN_CSC_KEY_PASSWORD = ""
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
npx electron-builder build --win --publish=never 2>&1 |
    Tee-Object "$PROJECT_ROOT\electron\eb-build.log" |
    Select-String -Pattern "packed|building|built|error|Error|nsis|exe"
Pop-Location

$installer = Get-ChildItem "$PROJECT_ROOT\electron\dist_electron" -Filter "*.exe" -ErrorAction SilentlyContinue |
             Select-Object -First 1
if (-not $installer) {
    Write-Host "[FAIL] electron-builder did not produce an installer" -ForegroundColor Red
    Get-Content "$PROJECT_ROOT\electron\eb-build.log" -Tail 20
    exit 1
}

$sizeG = [math]::Round($installer.Length / 1GB, 2)
Write-Host ""
Write-Host "+----------------------------------------------+" -ForegroundColor Green
Write-Host "|  [OK] LMIM OS v$APP_VERSION Windows installer ready!  |" -ForegroundColor Green
Write-Host "+----------------------------------------------+" -ForegroundColor Green
Write-Host "  File : $($installer.Name)  (${sizeG} GB)" -ForegroundColor White
Write-Host "  Path : $($installer.FullName)" -ForegroundColor Gray