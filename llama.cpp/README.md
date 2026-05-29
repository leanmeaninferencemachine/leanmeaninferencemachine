# llama.cpp (Submodule Reference)

LMIM uses llama.cpp for LLM inference. The actual source is not included in this repo to keep it small.

## Building from source:
```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
make
```

## Or use pre-built binaries:
- Linux: `llama.cpp/build/bin/llama-server`
- Windows: `llama.cpp/build/bin/llama-server.exe`

These are downloaded at runtime via `scripts/download_llama_cpp.sh` (or built from source).
