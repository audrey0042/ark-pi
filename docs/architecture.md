# Ark Pi Architecture

## Two-Pi layout

```
                    +------------------+
                    |  Phone / Laptop  |
                    +--------+---------+
                             | WiFi
                             v
+------------------+  Ethernet   +------------------+
|     ark-rag      |<----------->|     ark-llm      |
|  (Raspberry Pi)  |             |  (Raspberry Pi)  |
+------------------+             +------------------+
```

## What runs on ark-rag

- WiFi access point for client devices
- Web UI / dashboard
- RAG API (FastAPI)
- Document ingestion pipeline
- Text extraction, chunking, embedding, vector indexing
- Chroma vector database storage
- Context retrieval and prompt assembly
- HTTP client to ark-llm over Ethernet

## What runs on ark-llm

- llama.cpp server only
- GGUF model file storage
- Receives fully assembled prompts from ark-rag
- Returns generated text responses

ark-llm does not know about documents, Chroma, WiFi, or the web UI.

## Why ark-rag owns retrieval and prompt assembly

Retrieval requires access to the vector index, embedding model, and source document metadata — all of which live on the RAG Pi. Prompt assembly combines retrieved chunks with the user's question and system instructions. Keeping this logic on ark-rag means:

- The LLM Pi stays simple and stateless
- Index rebuilds happen in one place
- The inference Pi can be swapped or upgraded independently

## Why ark-llm stays stateless

The LLM Pi is a dedicated inference worker. It receives a complete prompt and returns text. No document state, no session history, no index — just model weights and llama.cpp. This separation keeps memory free for the model and avoids coupling inference to retrieval logic.

## Request flow

```
Phone/Laptop
  -> WiFi AP on ark-rag
  -> Web UI / RAG API on ark-rag
  -> Chroma search on ark-rag
  -> Prompt assembly on ark-rag
  -> Ethernet request to ark-llm
  -> llama.cpp server on ark-llm
  -> Response back to ark-rag
  -> Answer shown in browser
```

## Local development

During scaffold and early development, work happens on a laptop with `ARK_ROLE=dev`. No Pi hardware or external services are required. See the root README for details.
