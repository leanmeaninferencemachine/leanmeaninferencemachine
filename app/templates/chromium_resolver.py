"""
app/utils/chromium_resolver.py
Finds the best available Chromium executable for the WhatsApp daemon.

Resolution order:
  1. Bundled Playwright Chromium (AppImage bundle — guaranteed version)
  2. PLAYWRIGHT_BROWSERS_PATH env var (user-configured)
  3. Playwright's own auto-resolved path (~/.cache/ms-playwright)
  4. System Chromium (chromium-browser, chromium, google-chrome)
  5. None — caller falls back to browser-mode (no daemon window)

Usage:
    from app.utils.chromium_resolver import resolve_chromium, get_daemon_env
    exec_path = resolve_chromium()   # str path or None
    env = get_daemon_env()           # dict to pass to subprocess.Popen(env=...)
"""

import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _base_dir() -> Path:
    """AppImage bundle root or project root in dev mode."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent


def resolve_chromium() -> str | None:
    """
    Find the best Chromium executable. Returns absolute path string or None.
    """
    base = _base_dir()

    # ── 1. Bundled Playwright Chromium (AppImage) ─────────────────────────────
    # Playwright bundles chromium at a versioned path inside the AppImage.
    # We search both the bundle and the standard Playwright cache.
    bundle_playwright_dirs = [
        base / 'playwright_driver' / 'browser_packages',   # AppImage bundle
        base / 'playwright_driver' / 'browser_packages' / 'chromium',
    ]

    # Also check PLAYWRIGHT_BROWSERS_PATH if set
    pw_env = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if pw_env:
        bundle_playwright_dirs.insert(0, Path(pw_env))

    for pw_dir in bundle_playwright_dirs:
        if not pw_dir.exists():
            continue
        # Search for chrome executable recursively (handles versioned dirs)
        for exe_name in ['chrome', 'chromium', 'chrome-headless-shell']:
            hits = list(pw_dir.rglob(exe_name))
            for hit in hits:
                if hit.is_file() and os.access(hit, os.X_OK):
                    logger.info(f'✅ [Chromium] Found bundled Playwright: {hit}')
                    return str(hit)

    # ── 2. Playwright auto-resolve (uses ~/.cache/ms-playwright) ─────────────
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            auto_path = p.chromium.executable_path
            if auto_path and Path(auto_path).exists():
                logger.info(f'✅ [Chromium] Playwright auto-resolved: {auto_path}')
                return auto_path
    except Exception as e:
        logger.debug(f'Playwright auto-resolve failed: {e}')

    # ── 3. System Chromium ────────────────────────────────────────────────────
    system_candidates = [
        'chromium-browser',
        'chromium',
        'google-chrome',
        'google-chrome-stable',
        '/usr/bin/chromium-browser',
        '/usr/bin/chromium',
        '/usr/bin/google-chrome',
        '/snap/bin/chromium',
        '/var/lib/flatpak/exports/bin/org.chromium.Chromium',
    ]
    import shutil
    for candidate in system_candidates:
        found = shutil.which(candidate) or (Path(candidate).exists() and candidate)
        if found:
            logger.info(f'✅ [Chromium] System fallback: {found}')
            return str(found)

    logger.warning('⚠️  [Chromium] No Chromium found — WhatsApp daemon will use browser fallback')
    return None


def get_playwright_browsers_path() -> str | None:
    """
    Returns the path to set as PLAYWRIGHT_BROWSERS_PATH so Playwright
    finds the bundled Chromium without downloading.
    Returns None if only system Chromium is available (Playwright manages itself).
    """
    base = _base_dir()

    # Check bundle first
    bundle_dir = base / 'playwright_driver' / 'browser_packages'
    if bundle_dir.exists():
        # Verify it actually has a chromium subdir
        chromium_dirs = [d for d in bundle_dir.iterdir()
                         if d.is_dir() and 'chromium' in d.name.lower()]
        if chromium_dirs:
            logger.info(f'📦 [Chromium] Using bundled browsers: {bundle_dir}')
            return str(bundle_dir)

    # Check env var
    pw_env = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if pw_env and Path(pw_env).exists():
        return pw_env

    # System Playwright cache
    default_cache = Path.home() / '.cache' / 'ms-playwright'
    if default_cache.exists():
        return str(default_cache)

    return None


def get_daemon_env() -> dict:
    """
    Build the environment dict to pass when spawning the WhatsApp daemon.
    Ensures PLAYWRIGHT_BROWSERS_PATH and CHROMIUM_EXEC are set correctly.
    """
    env = os.environ.copy()

    # Set Playwright browser path
    pw_path = get_playwright_browsers_path()
    if pw_path:
        env['PLAYWRIGHT_BROWSERS_PATH'] = pw_path
        logger.info(f'🌐 [Daemon env] PLAYWRIGHT_BROWSERS_PATH={pw_path}')
    else:
        env.pop('PLAYWRIGHT_BROWSERS_PATH', None)

    # Set explicit chromium path
    chromium = resolve_chromium()
    if chromium:
        env['CHROMIUM_EXEC'] = chromium
        logger.info(f'🌐 [Daemon env] CHROMIUM_EXEC={chromium}')
    else:
        env.pop('CHROMIUM_EXEC', None)

    # Ensure LMIM_DATA_DIR is passed through
    if 'LMIM_DATA_DIR' not in env:
        data_dir = Path.home() / '.lmim_os'
        env['LMIM_DATA_DIR'] = str(data_dir)

    # Display vars — daemon needs these for Chromium window
    if 'DISPLAY' not in env and 'WAYLAND_DISPLAY' not in env:
        env['DISPLAY'] = ':0'

    return env
