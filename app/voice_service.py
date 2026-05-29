# app/voice_service.py
"""
Voice STT/TTS service for LMIM OS.

Directory layout expected under BASE_DIR/voice/:
    voice/
    ├── bin/
    │   ├── piper               ← Piper TTS binary
    │   ├── whisper-cli         ← whisper.cpp CLI binary (or 'main')
    │   └── *.so / *.dylib      ← shared libs (piper_phonemize, onnxruntime…)
    ├── espeak-ng-data/         ← eSpeak-NG data dir required by Piper
    └── models/
        ├── stt/
        │   └── ggml-small.bin  ← (or ggml-base.bin / ggml-tiny.bin)
        └── tts/
            ├── en_US-ryan-high.onnx
            ├── en_US-ryan-high.onnx.json
            ├── es_MX-claude-high.onnx
            └── es_MX-claude-high.onnx.json

Usage:
    from app.voice_service import tts_synthesize, stt_transcribe, check_voice_ready, warmup_piper
"""

import json
import logging
import os
import subprocess
import sys
import threading
import queue
import time
from pathlib import Path
from typing import Optional, Tuple

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path resolution — mirrors _voice_path() in main.py so they stay in sync
# ---------------------------------------------------------------------------

def _vp(rel: str) -> Path:
    """Resolve a path inside the voice/ directory (AppImage-aware)."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'voice' / rel
    return Path(BASE_DIR) / 'voice' / rel


VOICE_BIN_DIR    = _vp('bin')
ESPEAK_DATA_DIR  = _vp('espeak-ng-data')
STT_MODELS_DIR   = _vp('models/stt')
TTS_MODELS_DIR   = _vp('models/tts')

PIPER_BIN        = VOICE_BIN_DIR / 'piper'
WHISPER_BIN      = VOICE_BIN_DIR / 'whisper-cli'   # fallback: 'main'

# Preferred STT model (first found wins)
_STT_CANDIDATES  = ['ggml-small.bin', 'ggml-base.bin', 'ggml-base.en.bin', 'ggml-tiny.bin']

# Built-in voice map  lang_code → onnx stem
VOICE_MAP: dict[str, str] = {
    'es': 'es_MX-claude-high',
    'en': 'en_US-ryan-high',
    'pt': 'pt_BR-faber-medium',
    'fr': 'fr_FR-upmc-medium',
    'de': 'de_DE-thorsten-medium',
}
DEFAULT_VOICE = 'en_US-ryan-high'


# ---------------------------------------------------------------------------
# Singleton Piper Process Manager (keeps Piper alive across requests)
# ---------------------------------------------------------------------------

class PiperProcessManager:
    """
    Manages a persistent Piper subprocess that stays alive across TTS requests.
    This prevents the 30-second timeout/hang that occurs when spawning new
    Piper processes repeatedly.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._process: Optional[subprocess.Popen] = None
        self._process_lock = threading.Lock()
        self._request_queue = queue.Queue()
        self._response_queue = queue.Queue()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._current_language = 'en'
        self._current_model: Optional[Path] = None
        
    def _get_model_for_language(self, language: str) -> Optional[Path]:
        """Get the model path for a given language."""
        lang_code = language[:2].lower() if language else 'en'
        voice_name = VOICE_MAP.get(lang_code, DEFAULT_VOICE)
        model = TTS_MODELS_DIR / f'{voice_name}.onnx'
        if model.exists():
            return model
        # Fallback
        for fb in [DEFAULT_VOICE, 'es_MX-claude-high']:
            p = TTS_MODELS_DIR / f'{fb}.onnx'
            if p.exists():
                logger.warning('Requested voice %s not found, falling back to %s', voice_name, fb)
                return p
        return None
    
    def _start_process(self, language: str = 'en') -> bool:
        """Start or restart the Piper subprocess."""
        with self._process_lock:
            # Kill existing process if any
            self._stop_process()
            
            model = self._get_model_for_language(language)
            if not model:
                logger.error(f"No TTS model found for language {language}")
                return False
            
            self._current_language = language
            self._current_model = model
            
            # Read sample rate (not needed for the process, but kept for reference)
            sample_rate = 22050
            json_path = model.with_suffix('.onnx.json')
            if json_path.exists():
                try:
                    cfg = json.loads(json_path.read_text())
                    sample_rate = cfg.get('audio', {}).get('sample_rate', 22050)
                except Exception:
                    pass
            
            cmd = [
                str(PIPER_BIN),
                '--model', str(model),
                '--output-raw',
                '--espeak_data', str(ESPEAK_DATA_DIR),  # ← CRITICAL: explicit espeak path
            ]
            
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=_piper_env(),
                    text=False,  # binary mode
                )
                logger.info(f"🔊 Piper process started (PID: {self._process.pid}) for language {language}")
                return True
            except Exception as e:
                logger.error(f"Failed to start Piper process: {e}")
                self._process = None
                return False
    
    def _stop_process(self):
        """Terminate the Piper subprocess."""
        if self._process:
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)
            except Exception as e:
                logger.warning(f"Error terminating Piper process: {e}")
            finally:
                self._process = None
    
    def _worker(self):
        """Background worker that handles TTS requests."""
        import select
        import fcntl
        import os as os_module
        
        while self._running:
            try:
                # Wait for a request (with timeout to check _running periodically)
                try:
                    request = self._request_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                if request is None:  # Poison pill
                    break
                
                text = request.get('text')
                language = request.get('language', 'en')
                response_queue = request.get('response_queue')
                
                # Ensure process is running for this language
                if self._process is None or self._current_language != language:
                    if not self._start_process(language):
                        response_queue.put({'error': f'Failed to start Piper for language {language}'})
                        continue
                
                # Send text to Piper
                try:
                    # Write text as bytes to stdin
                    self._process.stdin.write(text.encode('utf-8'))
                    self._process.stdin.flush()
                    
                    # Read audio output
                    audio_data = bytearray()
                    
                    # Set stdout to non-blocking
                    fd = self._process.stdout.fileno()
                    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os_module.O_NONBLOCK)
                    
                    start_time = time.time()
                    timeout = 60  # 60 seconds max
                    
                    while time.time() - start_time < timeout:
                        try:
                            chunk = self._process.stdout.read(8192)
                            if chunk:
                                audio_data.extend(chunk)
                            else:
                                # Small delay to avoid busy loop
                                time.sleep(0.05)
                                # Check if process is still alive
                                if self._process.poll() is not None:
                                    break
                        except (BlockingIOError, OSError):
                            time.sleep(0.05)
                            continue
                    
                    if not audio_data:
                        response_queue.put({'error': 'No audio data received from Piper'})
                    else:
                        response_queue.put({'audio': bytes(audio_data), 'sample_rate': 22050})
                        
                except BrokenPipeError:
                    logger.warning("Broken pipe to Piper process, restarting")
                    response_queue.put({'error': 'Piper process died, restarting'})
                    self._start_process(language)
                except Exception as e:
                    logger.error(f"Piper worker error: {e}")
                    response_queue.put({'error': str(e)})
                    
            except Exception as e:
                logger.error(f"Piper worker loop error: {e}")
    
    def start(self):
        """Start the background worker thread."""
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()
        # Warm up with a dummy request
        try:
            self.synthesize(".", language='en')
            logger.info("🔊 Piper warmup completed")
        except Exception as e:
            logger.warning(f"Piper warmup failed: {e}")
    
    def stop(self):
        """Stop the background worker and terminate Piper."""
        self._running = False
        if self._worker_thread:
            self._request_queue.put(None)  # Poison pill
            self._worker_thread.join(timeout=5)
        self._stop_process()
    
    def synthesize(self, text: str, language: str = 'en') -> bytes:
        """
        Synthesize text using the persistent Piper process.
        
        Returns:
            WAV bytes
            
        Raises:
            RuntimeError: If synthesis fails
        """
        if not self._running:
            self.start()
        
        response_queue = queue.Queue()
        self._request_queue.put({
            'text': text,
            'language': language,
            'response_queue': response_queue
        })
        
        try:
            result = response_queue.get(timeout=90)  # 90 seconds timeout
            if 'error' in result:
                raise RuntimeError(result['error'])
            
            # Convert raw PCM to WAV
            sample_rate = result.get('sample_rate', 22050)
            return _pcm_to_wav(result['audio'], sample_rate=sample_rate)
            
        except queue.Empty:
            raise RuntimeError("Piper synthesis timeout after 90 seconds")


# Singleton instance
_piper_manager = None

def _get_piper_manager() -> PiperProcessManager:
    """Get or create the singleton Piper process manager."""
    global _piper_manager
    if _piper_manager is None:
        _piper_manager = PiperProcessManager()
    return _piper_manager


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_whisper_bin() -> Optional[Path]:
    if WHISPER_BIN.exists():
        return WHISPER_BIN
    fallback = VOICE_BIN_DIR / 'main'
    return fallback if fallback.exists() else None


def _get_stt_model() -> Optional[Path]:
    for name in _STT_CANDIDATES:
        p = STT_MODELS_DIR / name
        if p.exists():
            return p
    return None


def _get_tts_model(lang: str) -> Optional[Path]:
    lang_code  = lang[:2].lower() if lang else 'en'
    voice_name = VOICE_MAP.get(lang_code, DEFAULT_VOICE)
    model      = TTS_MODELS_DIR / f'{voice_name}.onnx'
    if model.exists():
        return model
    # Fallback: try any available onnx
    for fb in [DEFAULT_VOICE, 'es_MX-claude-high']:
        p = TTS_MODELS_DIR / f'{fb}.onnx'
        if p.exists():
            logger.warning('Requested voice %s not found, falling back to %s', voice_name, fb)
            return p
    return None


def _piper_env() -> dict:
    """
    Environment for Piper and Whisper subprocesses.
    - ESPEAK_DATA_PATH  : required by piper for phoneme lookup
    - LD_LIBRARY_PATH   : voice/bin must be first so piper finds its bundled
                          libonnxruntime / libpiper_phonemize .so files.
                          CUDA lib path is inherited from the parent process
                          (set by run_app_backend.py at startup).
    """
    env = os.environ.copy()
    env['ESPEAK_DATA_PATH'] = str(ESPEAK_DATA_DIR)

    voice_bin = str(VOICE_BIN_DIR)
    current   = env.get('LD_LIBRARY_PATH', '')
    # Prepend voice/bin only if not already there
    if voice_bin not in current.split(':'):
        env['LD_LIBRARY_PATH'] = f"{voice_bin}:{current}" if current else voice_bin

    return env


def _pcm_to_wav(pcm: bytes, sample_rate: int = 22050) -> bytes:
    """Wrap raw 16-bit mono PCM bytes in a minimal WAV container."""
    import struct
    n_ch, bits  = 1, 16
    data_size   = len(pcm)
    byte_rate   = sample_rate * n_ch * bits // 8
    blk_align   = n_ch * bits // 8
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + data_size, b'WAVE',
        b'fmt ', 16, 1, n_ch, sample_rate,
        byte_rate, blk_align, bits,
        b'data', data_size,
    )
    return header + pcm


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def stt_transcribe(audio_path: str, language: str = 'auto') -> Tuple[str, float]:
    """
    Transcribe an audio file using whisper-cli.

    The file must already be a 16 kHz mono WAV — see voice_transcribe() in
    main.py which handles the WebM→WAV conversion before calling this.

    Returns:
        (transcript: str, confidence: float)  confidence is a heuristic (0–1).

    Raises:
        FileNotFoundError  – audio file or binary missing
        RuntimeError       – whisper returned non-zero exit code
        subprocess.TimeoutExpired
    """
    audio_path = str(audio_path)
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f'Audio file not found: {audio_path}')

    whisper_bin = _get_whisper_bin()
    if not whisper_bin:
        raise FileNotFoundError(
            f'whisper-cli binary not found — expected at {WHISPER_BIN}'
        )

    model = _get_stt_model()
    if not model:
        raise FileNotFoundError(
            f'No STT model found in {STT_MODELS_DIR}. '
            f'Download one of: {_STT_CANDIDATES}'
        )

    lang_arg = language if language not in ('auto', '') else 'en'

    cmd = [
        str(whisper_bin),
        '-m', str(model),
        '-f', audio_path,
        '--no-timestamps',
        '-l', lang_arg,
        '-ng', '0',
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        env=_piper_env(),
    )

    if result.returncode != 0:
        raise RuntimeError(f'Whisper error (rc={result.returncode}): {result.stderr[:300]}')

    import re
    transcript = result.stdout.strip()
    transcript = re.sub(r'\[.*?\]', '', transcript)
    transcript = re.sub(r'\(.*?\)', '', transcript).strip()

    confidence = 0.85
    logger.info('🎤 STT (%s): "%s…"', model.name, transcript[:80])
    return transcript, confidence


def tts_synthesize(text: str, language: str = 'en') -> bytes:
    """
    Synthesize text to speech using Piper (fresh process each time).
    
    Returns:
        WAV bytes

    Raises:
        FileNotFoundError  – binary or model missing
        RuntimeError       – synthesis failed
        subprocess.TimeoutExpired
    """
    if not text or not text.strip():
        raise ValueError('Empty text passed to tts_synthesize()')

    if not PIPER_BIN.exists():
        raise FileNotFoundError(f'Piper binary not found — expected at {PIPER_BIN}')

    # Ensure we have a model for this language
    model = _get_tts_model(language)
    if not model:
        raise FileNotFoundError(
            f'No TTS model found in {TTS_MODELS_DIR} for language "{language}".'
        )

    # Read sample rate from companion JSON
    sample_rate = 22050
    json_path = model.with_suffix('.onnx.json')
    if json_path.exists():
        try:
            cfg = json.loads(json_path.read_text())
            sample_rate = cfg.get('audio', {}).get('sample_rate', 22050)
        except Exception:
            pass

    cmd = [
        str(PIPER_BIN),
        '--model', str(model),
        '--output-raw',
        '--espeak_data', str(ESPEAK_DATA_DIR),
    ]

    # Simple subprocess - no complex non-blocking
    result = subprocess.run(
        cmd,
        input=text.encode('utf-8'),
        capture_output=True,
        timeout=60,
        env=_piper_env(),
    )

    if result.returncode != 0:
        stderr_msg = result.stderr.decode(errors='replace')[:500] if result.stderr else ''
        raise RuntimeError(f'Piper error (rc={result.returncode}): {stderr_msg}')

    if not result.stdout:
        # Check stderr for errors
        stderr_msg = result.stderr.decode(errors='replace')[:500] if result.stderr else ''
        raise RuntimeError(f'Piper produced no audio output. Stderr: {stderr_msg}')

    wav = _pcm_to_wav(result.stdout, sample_rate=sample_rate)
    logger.info('🔊 TTS: %d chars → %d bytes @ %d Hz', len(text), len(wav), sample_rate)
    return wav


def warmup_piper() -> bool:
    """
    Pre-initialize the persistent Piper process.
    Call this once when the application starts.
    """
    try:
        manager = _get_piper_manager()
        manager.start()
        logger.info("🔊 Piper warmed up successfully")
        return True
    except Exception as e:
        logger.warning(f"Piper warmup failed (non-fatal): {e}")
        return False


def shutdown_piper() -> None:
    """
    Shutdown the persistent Piper process.
    Call this during application shutdown.
    """
    global _piper_manager
    if _piper_manager:
        _piper_manager.stop()
        _piper_manager = None
        logger.info("🔊 Piper shut down")


def get_available_voices() -> list[dict]:
    """Return metadata for every .onnx model found in the TTS models dir."""
    voices = []
    if not TTS_MODELS_DIR.exists():
        return voices
    for onnx in sorted(TTS_MODELS_DIR.glob('*.onnx')):
        meta: dict = {'id': onnx.stem, 'model': str(onnx)}
        json_path = onnx.with_suffix('.onnx.json')
        if json_path.exists():
            try:
                meta.update(json.loads(json_path.read_text()))
            except Exception:
                pass
        voices.append(meta)
    return voices


def check_voice_ready() -> dict:
    """
    Probe the voice subsystem and return a readiness summary.
    Useful for the /api/voice/status endpoint and startup diagnostics.
    """
    whisper_bin = _get_whisper_bin()
    stt_model   = _get_stt_model()
    tts_models  = list(TTS_MODELS_DIR.glob('*.onnx')) if TTS_MODELS_DIR.exists() else []

    return {
        'stt_ready':   bool(whisper_bin and stt_model),
        'tts_ready':   PIPER_BIN.exists() and len(tts_models) > 0,
        'espeak_ok':   ESPEAK_DATA_DIR.exists(),
        'whisper_bin': str(whisper_bin) if whisper_bin else None,
        'piper_bin':   str(PIPER_BIN),
        'stt_model':   str(stt_model) if stt_model else None,
        'tts_voices':  [m.stem for m in tts_models],
        'espeak_data': str(ESPEAK_DATA_DIR),
    }
