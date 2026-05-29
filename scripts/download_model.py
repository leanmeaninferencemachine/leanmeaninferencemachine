#!/usr/bin/env python3
"""Download appropriate model based on available hardware"""
import os
import platform
import subprocess
import sys

MODELS = {
    "cpu": {
        "name": "Qwen3.5-0.8B.Q8_0.gguf",
        "url": "https://lmim.tech/models/cpu/Qwen3.5-0.8B.Q8_0.gguf",
        "size_gb": 0.8,
        "description": "Fast CPU model, works on any machine"
    },
    "gpu_4gb": {
        "name": "Qwen3.5-2B.Q8_0.gguf",
        "url": "https://lmim.tech/models/gpu/Qwen3.5-2B.Q8_0.gguf",
        "size_gb": 2.1,
        "description": "For 4GB GPU laptops (GTX 1650, etc)"
    },
    "gpu_8gb": {
        "name": "Qwen3.5-9B.Q4_K_M.gguf",
        "url": "https://lmim.tech/models/gpu/Qwen3.5-9B.Q4_K_M.gguf",
        "size_gb": 5.5,
        "description": "For 8GB+ GPUs (RTX 3060, 4060, etc)"
    }
}

def detect_hardware():
    """Check if CUDA GPU is available and VRAM size"""
    try:
        # Check for NVIDIA GPU
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.total', '--format=csv,noheader,nounits'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            vram_mb = int(result.stdout.strip().split('\n')[0])
            vram_gb = vram_mb / 1024
            print(f"✅ Detected GPU with {vram_gb:.1f}GB VRAM")
            
            if vram_gb >= 8:
                return "gpu_8gb"
            elif vram_gb >= 4:
                return "gpu_4gb"
    except:
        pass
    
    print("⚠️ No GPU detected or CUDA not available, using CPU model")
    return "cpu"

def download_model(model_key):
    """Download the selected model"""
    model = MODELS[model_key]
    model_path = f"models/{model['name']}"
    
    if os.path.exists(model_path):
        print(f"✅ Model already exists: {model_path}")
        return
    
    print(f"\n📦 Downloading {model['description']}")
    print(f"   Size: ~{model['size_gb']}GB")
    print(f"   From: {model['url']}")
    
    # Use wget with resume support
    cmd = f"wget -c --progress=bar:force -O {model_path} {model['url']}"
    subprocess.run(cmd, shell=True)
    
    print(f"✅ Model saved to: {model_path}")

if __name__ == "__main__":
    print("🔍 Detecting hardware...")
    detected = detect_hardware()
    print(f"\n📌 Recommended model: {MODELS[detected]['description']}")
    
    # Optional: allow override
    if len(sys.argv) > 1:
        detected = sys.argv[1]
    
    download_model(detected)
