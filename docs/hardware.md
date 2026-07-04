# Hardware

## Overview

Ark Pi uses two Raspberry Pi 5 units connected directly over Ethernet.

| Device | Primary role |
|--------|--------------|
| ark-rag | WiFi AP, RAG pipeline, vector index storage |
| ark-llm | llama.cpp inference, GGUF model storage |

## Networking

- **Ethernet**: Direct link between the two Pis (no switch required for the minimal setup).
- **WiFi**: ark-rag provides the access point for phones and laptops.
- Static IPs on the Ethernet link (e.g. ark-rag `192.168.50.1`, ark-llm `192.168.50.2`). Deploy docs TBD.

## Storage

### ark-rag (index and data)

- **NVMe strongly preferred** for `/srv/ark-pi/data` and `/srv/ark-pi/indexes`.
- Index writes are heavy. Don't put Chroma on microSD if you can avoid it; they wear out fast.
- Source documents and generated chunks/embeddings are local runtime artifacts, not repo contents.

### ark-llm (models)

- GGUF model files live under `/srv/ark-pi/models/` on the LLM Pi.
- Models are large, versioned externally, and never committed to git.

## Generated artifacts

The following are created at runtime and excluded from git:

- `data/`: source documents and ingest intermediates
- `indexes/`: Chroma DB and related index files
- `models/`: GGUF weights
- `logs/`: service logs

The repo contains the recipe to rebuild indexes from source documents.
