"""
RAG Lite for LMIM OS v2.1
- Document ingestion (PDF, TXT, MD)
- Smart chunking respecting markdown and code structure
- Embedding with sentence-transformers (all-MiniLM-L6-v2)
- Persistent storage in DATA_DIR/rag/{user_id}.json
- Cosine similarity retrieval with MMR-lite deduplication
- CPU torch bundled for cross-platform compatibility
"""

import json
import math
import os
import re
import sys
import time
import logging
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from functools import lru_cache

logger = logging.getLogger(__name__)

# ── Frozen-env path guard ─────────────────────────────────────────────────────
# In a PyInstaller frozen binary, sys._MEIPASS is the bundle root.
# Ensure it (and torch/lib) are on sys.path / LD_LIBRARY_PATH so that
# sentence_transformers can find torch, tokenizers, etc.
if getattr(sys, 'frozen', False):
    import ctypes
    _meipass = sys._MEIPASS
    # Add bundle root to sys.path if not already there
    if _meipass not in sys.path:
        sys.path.insert(0, _meipass)
    # Ensure torch/lib is in LD_LIBRARY_PATH (belt-and-suspenders alongside main.js)
    _torch_lib = os.path.join(_meipass, 'torch', 'lib')
    if os.path.isdir(_torch_lib):
        _cur_ld = os.environ.get('LD_LIBRARY_PATH', '')
        if _torch_lib not in _cur_ld:
            os.environ['LD_LIBRARY_PATH'] = f"{_torch_lib}:{_cur_ld}" if _cur_ld else _torch_lib
            # Attempt to reload linker (Linux only, best-effort)
            try:
                ctypes.CDLL(os.path.join(_torch_lib, 'libtorch_cpu.so'))
            except Exception:
                pass
# ─────────────────────────────────────────────────────────────────────────────

_model = None
_MODEL_NAME = "all-MiniLM-L6-v2"
_CACHE_DIR = None

# =============================================================================
# PATH MANAGEMENT
# =============================================================================

def _get_rag_dir() -> Path:
    from app.config import DATA_DIR
    rag_dir = DATA_DIR / 'rag'
    rag_dir.mkdir(parents=True, exist_ok=True)
    return rag_dir

def _get_cache_dir() -> Path:
    global _CACHE_DIR
    if _CACHE_DIR is None:
        from app.config import DATA_DIR
        _CACHE_DIR = DATA_DIR / 'cache' / 'sentence_transformers'
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        os.environ['SENTENCE_TRANSFORMERS_HOME'] = str(_CACHE_DIR)
    return _CACHE_DIR

def _get_bundled_model_path() -> Optional[Path]:
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent
    bundled = base / 'models' / _MODEL_NAME
    return bundled if bundled.exists() else None

# =============================================================================
# MODEL LOADING
# =============================================================================

def _get_model():
    """
    Lazy-load the embedding model.
    Tries bundled path first, falls back to HuggingFace download.
    Always uses CPU.
    """
    global _model
    if _model is not None:
        return _model

    try:
        from sentence_transformers import SentenceTransformer
        import torch

        torch.set_num_threads(min(4, os.cpu_count() or 2))
        cache_dir = _get_cache_dir()

        bundled_path = _get_bundled_model_path()
        if bundled_path and bundled_path.exists():
            logger.info(f"Loading embedding model from bundled path: {bundled_path}")
            _model = SentenceTransformer(str(bundled_path), device='cpu')
        else:
            logger.info(f"Loading embedding model: {_MODEL_NAME}")
            _model = SentenceTransformer(_MODEL_NAME, device='cpu', cache_folder=str(cache_dir))
            # Cache locally for future bundling
            local_cache = Path(__file__).resolve().parent.parent / 'models' / _MODEL_NAME
            if not local_cache.exists():
                try:
                    _model.save(str(local_cache))
                    logger.info(f"Model cached to {local_cache}")
                except Exception as e:
                    logger.warning(f"Could not cache model locally: {e}")

        logger.info("✅ Embedding model ready (CPU)")
        return _model

    except Exception as e:
        import traceback
        logger.error(f"RAG import failed (real error): {e}\n{traceback.format_exc()}")
        raise RuntimeError(
            f"RAG import failed: {e}. "
            "Check logs for full traceback."
        ) from e
    except Exception as e:
        logger.error(f"Failed to load embedding model: {e}")
        raise RuntimeError(f"Embedding model load failed: {e}")

# =============================================================================
# SMART CHUNKING
# =============================================================================

def _clean_text(text: str) -> str:
    """Normalize whitespace and remove junk but preserve structure."""
    # Collapse 4+ newlines to 3
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    # Remove trailing whitespace on each line
    text = re.sub(r'[ \t]+\n', '\n', text)
    # Remove zero-width chars and BOM
    text = text.replace('\u200b', '').replace('\ufeff', '')
    return text.strip()

def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> List[str]:
    """
    Smart chunking that respects document structure.

    Priority order for split points:
    1. Markdown headings  (#, ##, ###)
    2. Code block boundaries (```)
    3. Paragraph boundaries (double newline)
    4. Sentence boundaries (.!?)
    5. Word boundaries (last resort)

    Returns chunks with guaranteed minimum length to avoid noise.
    """
    if not text or not text.strip():
        return []

    text = _clean_text(text)

    # Try heading-aware split first for markdown/blueprint documents
    heading_pattern = re.compile(r'(^|\n)(#{1,4}\s+[^\n]+)', re.MULTILINE)
    heading_matches = list(heading_pattern.finditer(text))

    if heading_matches and len(text) > chunk_size * 1.5:
        sections = []
        positions = [m.start() for m in heading_matches] + [len(text)]
        # Add content before first heading if any
        if positions[0] > 0:
            preamble = text[:positions[0]].strip()
            if preamble:
                sections.append(preamble)
        for i in range(len(heading_matches)):
            section = text[positions[i]:positions[i + 1]].strip()
            if section:
                sections.append(section)

        chunks = []
        for section in sections:
            if len(section) <= chunk_size:
                if len(section) >= 80:
                    chunks.append(section)
            else:
                chunks.extend(_split_by_paragraphs(section, chunk_size, overlap))
        return chunks

    return _split_by_paragraphs(text, chunk_size, overlap)


def _split_by_paragraphs(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Split text by paragraphs then sentences if needed, with overlap."""
    # Detect and preserve code blocks
    code_block_pattern = re.compile(r'```[\s\S]*?```', re.MULTILINE)
    code_blocks = {}
    placeholder_idx = 0

    def stash_code(m):
        nonlocal placeholder_idx
        key = f"\x00CODE{placeholder_idx}\x00"
        code_blocks[key] = m.group()
        placeholder_idx += 1
        return key

    text = code_block_pattern.sub(stash_code, text)

    # Split by paragraphs
    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks = []
    current_parts: List[str] = []
    current_len = 0

    for para in paragraphs:
        # Restore code blocks for length calculation
        real_para = para
        for key, code in code_blocks.items():
            real_para = real_para.replace(key, code)
        para_len = len(real_para)

        if para_len > chunk_size:
            # Flush current
            if current_parts:
                full = '\n\n'.join(current_parts)
                for key, code in code_blocks.items():
                    full = full.replace(key, code)
                chunks.append(full)
                # Keep last part for overlap
                current_parts = current_parts[-1:]
                current_len = sum(len(p) for p in current_parts)

            # Split large paragraph by sentences
            sub = _split_by_sentences(real_para, chunk_size, overlap)
            if sub:
                chunks.extend(sub[:-1])
                # Put last sub-chunk into current for overlap with next para
                last = sub[-1]
                current_parts = [last]
                current_len = len(last)

        elif current_len + para_len + 2 > chunk_size and current_parts:
            # Flush
            full = '\n\n'.join(current_parts)
            for key, code in code_blocks.items():
                full = full.replace(key, code)
            chunks.append(full)
            # Overlap: keep last part
            current_parts = current_parts[-1:]
            current_len = sum(len(p) for p in current_parts)
            current_parts.append(para)
            current_len += para_len
        else:
            current_parts.append(para)
            current_len += para_len

    if current_parts:
        full = '\n\n'.join(current_parts)
        for key, code in code_blocks.items():
            full = full.replace(key, code)
        chunks.append(full)

    # Restore code blocks in all chunks and filter noise
    final = []
    for ch in chunks:
        for key, code in code_blocks.items():
            ch = ch.replace(key, code)
        ch = ch.strip()
        if len(ch) >= 80:
            final.append(ch)

    logger.debug(f"Chunked into {len(final)} chunks (size={chunk_size}, overlap={overlap})")
    return final


def _split_by_sentences(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Split a large paragraph into sentence-bounded chunks."""
    # Split on sentence-ending punctuation followed by whitespace + uppercase
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z\u00C0-\u024F])', text)
    if not sentences:
        # Hard split as last resort
        return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size - overlap)]

    chunks = []
    current = []
    current_len = 0

    for sent in sentences:
        sent_len = len(sent)
        if current_len + sent_len > chunk_size and current:
            chunks.append(' '.join(current))
            # Keep last 1-2 sentences for overlap
            overlap_sents = current[-2:] if len(current) >= 2 else current[-1:]
            current = overlap_sents[:]
            current_len = sum(len(s) for s in current)
        current.append(sent)
        current_len += sent_len

    if current:
        chunks.append(' '.join(current))

    return [c for c in chunks if len(c) >= 60]

# =============================================================================
# SIMILARITY & RETRIEVAL
# =============================================================================

def _cosine(a, b) -> float:
    """Cosine similarity between two vectors."""
    try:
        import numpy as np
        a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))
    except Exception:
        # Pure-Python fallback
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb + 1e-10) if na and nb else 0.0


def _mmr_rerank(
    query_emb: list,
    chunk_embs: list,
    indices: list,
    top_k: int,
    lambda_: float = 0.6,
) -> List[int]:
    """
    Maximal Marginal Relevance — balances relevance and diversity.
    lambda_=1.0 → pure relevance, lambda_=0.0 → pure diversity.
    """
    if not indices:
        return []

    selected = []
    remaining = list(indices)

    while remaining and len(selected) < top_k:
        best_idx = None
        best_score = -float('inf')

        for i in remaining:
            rel = _cosine(query_emb, chunk_embs[i])
            if selected:
                max_sim = max(_cosine(chunk_embs[i], chunk_embs[s]) for s in selected)
            else:
                max_sim = 0.0
            score = lambda_ * rel - (1 - lambda_) * max_sim
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx is not None:
            selected.append(best_idx)
            remaining.remove(best_idx)

    return selected

# =============================================================================
# DOCUMENT STORAGE
# =============================================================================

def store_document(user_id: str, text: str, filename: str, metadata: Optional[Dict] = None) -> Dict:
    """
    Chunk, embed, and persist a document for a user.
    Returns dict with 'chunks', 'filename', and optionally 'error'.
    """
    if not text or not text.strip():
        return {"error": "Empty document", "chunks": 0, "filename": filename}

    logger.info(f"Storing document for '{user_id}': {filename} ({len(text):,} chars)")

    try:
        model = _get_model()
        chunks = _chunk_text(text)

        if not chunks:
            return {"error": "No valid chunks extracted", "chunks": 0, "filename": filename}

        # Batch embed for memory efficiency
        batch_size = 32
        embeddings = []
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            batch_embs = model.encode(batch, show_progress_bar=False).tolist()
            embeddings.extend(batch_embs)

        doc_hash = hashlib.md5(text.encode()).hexdigest()

        data = {
            "filename": filename,
            "chunks": chunks,
            "embeddings": embeddings,
            "timestamp": time.time(),
            "doc_hash": doc_hash,
            "char_count": len(text),
            "metadata": metadata or {},
        }

        rag_dir = _get_rag_dir()
        path = rag_dir / f"{user_id}.json"
        temp_path = path.with_suffix('.tmp')

        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_path.rename(path)

        logger.info(f"✅ Stored: {filename} → {len(chunks)} chunks → {path}")
        return {"chunks": len(chunks), "filename": filename, "hash": doc_hash[:8]}

    except RuntimeError as e:
        logger.error(f"RAG dependency error: {e}")
        return {"error": str(e), "chunks": 0, "filename": filename}
    except Exception as e:
        logger.error(f"Failed to store document: {e}", exc_info=True)
        return {"error": str(e), "chunks": 0, "filename": filename}

# =============================================================================
# RETRIEVAL
# =============================================================================

def retrieve_chunks(
    user_id: str,
    query: str,
    top_k: int = 5,
    min_similarity: float = 0.12,
    use_mmr: bool = True,
) -> List[str]:
    """
    Retrieve the most relevant, diverse chunks for a query.

    Args:
        user_id:        User identifier.
        query:          Search query / question.
        top_k:          Number of chunks to return.
        min_similarity: Minimum cosine similarity threshold.
        use_mmr:        Whether to apply MMR reranking for diversity.

    Returns:
        List of relevant text chunks (ordered best-first).
    """
    rag_dir = _get_rag_dir()
    path = rag_dir / f"{user_id}.json"

    if not path.exists():
        logger.debug(f"No RAG document for user '{user_id}'")
        return []

    if not query or not query.strip():
        return []

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        chunks = data.get("chunks", [])
        embeddings = data.get("embeddings", [])

        if not chunks or not embeddings or len(chunks) != len(embeddings):
            logger.warning(f"Corrupted RAG data for {user_id}")
            return []

        model = _get_model()
        query_emb = model.encode([query], show_progress_bar=False)[0].tolist()

        # Score all chunks
        scored = sorted(
            [(i, _cosine(query_emb, emb)) for i, emb in enumerate(embeddings)],
            key=lambda x: x[1],
            reverse=True,
        )

        # Apply similarity threshold
        candidates = [i for i, score in scored if score >= min_similarity]

        if not candidates:
            # Report best score for debugging
            best_score = scored[0][1] if scored else 0
            logger.debug(
                f"No chunks above threshold {min_similarity} "
                f"(best={best_score:.3f}). "
                f"Lowering threshold to 0.0 for fallback."
            )
            # Return best matches anyway so the model can try
            candidates = [i for i, _ in scored[:top_k * 2]]

        if not candidates:
            return []

        if use_mmr and len(candidates) > top_k:
            selected_indices = _mmr_rerank(query_emb, embeddings, candidates, top_k)
        else:
            selected_indices = candidates[:top_k]

        result = [chunks[i] for i in selected_indices if i < len(chunks)]

        if result:
            best = scored[0][1] if scored else 0
            logger.debug(
                f"Retrieved {len(result)} chunks "
                f"(best_score={best:.3f}, mmr={use_mmr})"
            )

        return result

    except json.JSONDecodeError as e:
        logger.error(f"Corrupted RAG JSON for {user_id}: {e}")
        return []
    except Exception as e:
        logger.error(f"Failed to retrieve chunks: {e}", exc_info=True)
        return []

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def has_document(user_id: str) -> bool:
    """Check if user has an active RAG document."""
    return (_get_rag_dir() / f"{user_id}.json").exists()


def get_document_info(user_id: str) -> Optional[Dict]:
    """Get metadata about the active document."""
    path = _get_rag_dir() / f"{user_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return {
            "filename":   data.get("filename"),
            "chunks":     len(data.get("chunks", [])),
            "char_count": data.get("char_count", 0),
            "timestamp":  data.get("timestamp"),
            "hash":       data.get("doc_hash", "")[:8],
            "metadata":   data.get("metadata", {}),
        }
    except Exception:
        return None


def clear_document(user_id: str) -> bool:
    """Delete the stored document for a user."""
    path = _get_rag_dir() / f"{user_id}.json"
    if path.exists():
        try:
            path.unlink()
            logger.info(f"Cleared RAG document for '{user_id}'")
            return True
        except Exception as e:
            logger.error(f"Failed to clear document: {e}")
            return False
    return True


def extract_text_from_file(file) -> Tuple[str, str]:
    """
    Extract plain text from an uploaded file object (Flask FileStorage).
    Supports: PDF, TXT, MD, and any UTF-8 text file.

    Returns:
        (text_content, filename)
    """
    filename = getattr(file, 'filename', None) or "unknown"

    try:
        if filename.lower().endswith('.pdf'):
            try:
                from pypdf import PdfReader
                reader = PdfReader(file)
                pages = []
                for page_num, page in enumerate(reader.pages, 1):
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        pages.append(page_text)
                    else:
                        logger.debug(f"PDF page {page_num} has no extractable text (may be scanned)")
                text = "\n\n".join(pages)
                if not text.strip():
                    return "", filename  # Scanned PDF — caller should report this
                logger.info(f"Extracted PDF: {filename} ({len(text):,} chars, {len(reader.pages)} pages)")
            except ImportError:
                raise RuntimeError(
                    "PDF support requires pypdf. Install: pip install pypdf"
                )
        else:
            raw = file.read()
            # Try UTF-8, fall back to latin-1
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                text = raw.decode('latin-1', errors='replace')
            logger.info(f"Extracted text file: {filename} ({len(text):,} chars)")

        return text, filename

    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"Failed to extract text from {filename}: {e}")
        return "", filename
