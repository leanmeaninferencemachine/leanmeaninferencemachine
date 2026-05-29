#!/bin/bash
# Downloads pre-compiled llama.cpp binaries for your platform

LLAMA_VERSION="b4053"
PLATFORM=$(uname -m)

# Detect CUDA availability
if command -v nvidia-smi &> /dev/null; then
    CUDA_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | cut -d. -f1)
    if [ "$CUDA_VERSION" -ge 535 ]; then
        BACKEND="cuda"
    else
        BACKEND="cuda11"
    fi
else
    BACKEND="cpu"
fi

echo "📦 Downloading llama.cpp for $BACKEND..."

case $BACKEND in
    "cuda")
        URL="https://lmim.tech/static/llama.cpp/llama-server-cuda-x64"
        ;;
    "cuda11")
        URL="https://lmim.tech/static/llama.cpp/llama-server-cuda11-x64"
        ;;
    "cpu")
        URL="https://lmim.tech/static/llama.cpp/llama-server-cpu-x64"
        ;;
esac

mkdir -p ./bin
wget -O ./bin/llama-server "$URL"
chmod +x ./bin/llama-server

echo "✅ llama.cpp ready at ./bin/llama-server"
