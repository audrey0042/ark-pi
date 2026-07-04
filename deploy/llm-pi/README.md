# ark-llm deployment (placeholder)

Future responsibilities for the LLM Pi. **Not implemented in the initial scaffold.**

## Static Ethernet

- Assign a static IP on the direct link to ark-rag (e.g. `192.168.50.2/24`).
- Listen on `ARK_LLAMA_HOST:ARK_LLAMA_PORT` for inference requests from ark-rag only.

## llama.cpp build and install

- Build llama.cpp server for aarch64 (Pi 5).
- Notes and build flags will live under `llama-cpp/` when added.

## Model storage

- Place GGUF files under `/srv/ark-pi/models/`.
- Set `ARK_MODEL_PATH` to the active model file.
- Models are never committed to git.

## systemd service

- `ark-llm.service`: llama.cpp server on the Ethernet interface.
- Restart policy and resource limits TBD.

Subdirectories `systemd/` and `llama-cpp/` are reserved for future config snippets. No executable scripts in the scaffold pass.
