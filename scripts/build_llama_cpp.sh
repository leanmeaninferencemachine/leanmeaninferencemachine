#!/bin/bash
# Clone and build llama.cpp from source

git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp

# Build for CPU
make

# Or for CUDA
make LLAMA_CUDA=1

# Copy binary
cp llama-server ../bin/
