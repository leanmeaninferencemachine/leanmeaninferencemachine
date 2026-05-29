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
            ├── en_US-lessac-high.onnx
            ├── en_US-lessac-high.onnx.json
            ├── es_MX-claude-high.onnx
            └── es_MX-claude-high.onnx.json

Usage:
    from app.voice_service import tts_synthesize, stt_transcribe, check_voice_ready
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
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
    'es': 'es_MX-ald-medium',
    'en': 'en_US-ryan-high',
    'pt': 'pt_BR-faber-medium',
    'fr': 'fr_FR-upmc-medium',
    'de': 'de_DE-thorsten-medium',
}
DEFAULT_VOICE = 'en_US-ryan-high'


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
    """Environment dict required by Piper (LD_LIBRARY_PATH + ESPEAK_DATA_PATH)."""
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = str(VOICE_BIN_DIR)
    env['ESPEAK_DATA_PATH'] = str(ESPEAK_DATA_DIR)
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
        # --print-special omitted: boolean flag, no arg needed
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        env=os.environ.copy(),
    )

    if result.returncode != 0:
        raise RuntimeError(f'Whisper error (rc={result.returncode}): {result.stderr[:300]}')

    import re
    transcript = result.stdout.strip()
    transcript = re.sub(r'\[.*?\]', '', transcript)
    transcript = re.sub(r'\(.*?\)', '', transcript).strip()

    # Small model heuristic — upgrade when word-level timestamps are enabled
    confidence = 0.85

    logger.info('🎤 STT (%s): "%s…"', model.name, transcript[:80])
    return transcript, confidence


def tts_synthesize(text: str, language: str = 'en') -> bytes:
    """
    Synthesize text to speech using Piper, returning WAV bytes.

    Raises:
        FileNotFoundError  – binary or model missing
        RuntimeError       – piper returned non-zero exit code
        subprocess.TimeoutExpired
    """
    if not text or not text.strip():
        raise ValueError('Empty text passed to tts_synthesize()')

    if not PIPER_BIN.exists():
        raise FileNotFoundError(f'Piper binary not found — expected at {PIPER_BIN}')

    model = _get_tts_model(language)
    if not model:
        raise FileNotFoundError(
            f'No TTS model found in {TTS_MODELS_DIR} for language "{language}".'
        )

    # Read sample rate from companion JSON (Piper ships one per model)
    sample_rate = 22050
    json_path   = model.with_suffix('.onnx.json')
    if json_path.exists():
        try:
            cfg         = json.loads(json_path.read_text())
            sample_rate = cfg.get('audio', {}).get('sample_rate', 22050)
        except Exception:
            pass

    cmd = [
        str(PIPER_BIN),
        '--model', str(model),
        '--output-raw',       # raw PCM to stdout; we wrap in WAV ourselves
    ]

    result = subprocess.run(
        cmd,
        input=text.encode('utf-8'),
        capture_output=True,
        timeout=30,
        env=_piper_env(),
    )

    if result.returncode != 0:
        raise RuntimeError(
            f'Piper error (rc={result.returncode}): '
            f'{result.stderr.decode(errors="replace")[:300]}'
        )

    wav = _pcm_to_wav(result.stdout, sample_rate=sample_rate)
    logger.info('🔊 TTS: %d chars → %d bytes @ %d Hz', len(text), len(wav), sample_rate)
    return wav


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
