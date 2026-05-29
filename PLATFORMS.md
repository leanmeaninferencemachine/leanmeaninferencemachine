# Platform Support & Build Guide

## Overview
LMIM OS runs on **Linux** and **Windows** with full feature parity.  
macOS support is planned for v3.0.

| Feature | Linux | Windows |
|---------|-------|---------|
| Full LMIM OS | ✅ | ✅ |
| GPU acceleration | ✅ (CUDA) | ✅ (CUDA) |
| Voice (STT/TTS) | ✅ | ✅ |
| WhatsApp daemon | ✅ | ✅ |
| Directory Workspace | ✅ | ✅ |
| RAG Lite | ✅ | ✅ |
| Web Scraper | ✅ | ✅ |

---

## Running from Source (Development)

### Linux (Ubuntu 22.04+, Fedora 40+, Debian 11+)

```bash
# Clone and enter directory
git clone https://github.com/leanmeaninferencemachine/leanmeaninferencemachine
cd leanmeaninferencemachine

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Download voice components
bash scripts/setup_voice.sh

# Download appropriate LLM model (auto-detects GPU)
python3 scripts/download_model.py

# Run LMIM
python3 run_app.py
```

### Windows (10/11 x64, PowerShell as Administrator)

```powershell
# Clone and enter directory
git clone https://github.com/leanmeaninferencemachine/leanmeaninferencemachine
cd leanmeaninferencemachine

# Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Download voice components
.\scripts\setup_voice.ps1

# Download appropriate LLM model
python scripts\download_model.py

# Run LMIM
python run_app.py
```

---

## Building Distributables

### Linux (AppImage)

```bash
# Build the Electron AppImage
./build_electron_appimage.sh

# Output: electron/dist_electron/LMIM_OS_*.AppImage
```

### Windows (Installer)

```powershell
# Build the Windows installer (requires Inno Setup)
.\build_windows.ps1

# Output: dist/LMIM_OS-Setup-*.exe
```

---

## Runtime File Structure

Both platforms use the same internal structure:

```
LMIM_OS/
├── app/                  # Python backend source
├── daemons/              # WhatsApp, Telegram, Email daemons
├── electron/             # Electron shell (main.js, preload.js)
├── voice/
│   └── bin/              # whisper-cli, piper (downloaded at runtime)
├── models/               # LLM models (downloaded at runtime)
├── data/                 # User data (~/.lmim_os on Linux, %APPDATA% on Windows)
├── run_app.py            # Main launcher (cross-platform)
├── run_app_backend.py    # Backend-only (for Electron mode)
└── requirements.txt      # Python dependencies
```

---

## Platform-Specific Notes

### Linux
- AppImage bundles everything (no installation required)
- Data stored in `~/.lmim_os/`
- Uses `pkill` for process management
- Library path: `LD_LIBRARY_PATH`

### Windows
- Installer places files in `Program Files\LMIM_OS`
- Data stored in `%APPDATA%\LMIM_OS`
- Uses `taskkill` for process management
- Library path: `PATH`
- Requires Visual C++ Redistributable (included in installer)

---

## File Reference

| File | Platform | Purpose |
|------|----------|---------|
| `run_app.py` | Both | Main launcher (Flask + llama-server + Electron) |
| `run_app_backend.py` | Both | Backend-only (for headless or custom GUI) |
| `build_electron_appimage.sh` | Linux | Builds AppImage distribution |
| `build_windows.ps1` | Windows | Builds Windows installer |
| `lmim_backend.spec` | Both | PyInstaller spec (cross-platform) |
| `requirements.txt` | Both | Python dependencies |
| `scripts/setup_voice.sh` | Linux | Downloads voice binaries |
| `scripts/setup_voice.ps1` | Windows | Downloads voice binaries |
| `scripts/download_model.py` | Both | Downloads LLM model (hardware-aware) |
| `scripts/download_embedding_model.py` | Both | Downloads RAG embedding model |

---

## Troubleshooting

### Linux: "llama-server: command not found"
```bash
# Ensure voice/bin is in PATH or run from base directory
cd ~/LMIM_OS
./run_app.py
```

### Windows: "python is not recognized"
```powershell
# Add Python to PATH or use full path
C:\Python311\python.exe run_app.py
```

### GPU Not Detected
- **Linux**: Ensure NVIDIA drivers (545+) and CUDA 12.x are installed
- **Windows**: Install CUDA Toolkit 12.x and latest drivers

### Voice Not Working
- Run setup script manually:
  ```bash
  bash scripts/setup_voice.sh  # Linux
  ```
  ```powershell
  .\scripts\setup_voice.ps1   # Windows (PowerShell)
  ```

---

## Contributing

Both platforms are actively maintained. When contributing:
- Test changes on both platforms when possible
- Use `sys.platform` checks for OS-specific code
- Keep scripts in both `.sh` (Linux) and `.ps1` (Windows) formats when needed

---

## Roadmap

| Version | Focus |
|---------|-------|
| v2.1.0 | Linux + Windows parity (current) |
| v2.2.0 | ARM64 support, improved GPU detection |
| v3.0.0 | macOS support, M1/M2/M3 native |

