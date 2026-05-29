#!/usr/bin/env python3
"""Download embedding model for RAG"""
import os
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"
MODEL_PATH = f"models/{MODEL_NAME}"

if not os.path.exists(MODEL_PATH):
    print(f"📦 Downloading embedding model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)
    model.save(MODEL_PATH)
    print(f"✅ Model saved to: {MODEL_PATH}")
else:
    print(f"✅ Embedding model already exists")
