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
- Index backend abstraction: simple lexical fallback for offline dev; optional Chroma vector storage on ark-rag
- Chroma vector database storage (optional backend; not required for laptop dev/tests)
- Context retrieval and prompt assembly
- LLM client boundary (`ark_pi.llm_client`) — mock backend for local dev, OpenAI-compatible HTTP client for future ark-llm calls over Ethernet

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
  -> Web UI (GET /) on ark-rag
  -> POST /api/ingest/text (paste text -> chunks + index) or POST /api/ask
  -> Index search on ark-rag (simple lexical or optional Chroma)
  -> Prompt assembly on ark-rag
  -> LLM client on ark-rag (mock locally; openai-compatible over Ethernet in production)
  -> llama.cpp server on ark-llm
  -> Response back to ark-rag
  -> Answer shown in browser
```

## FastAPI layer (laptop dev)

The RAG API and built-in web UI live in `ark_pi.web`:

```
Browser
  -> GET / or /ui  -> built-in HTML (inline CSS/JS, no CDN)
  -> POST /api/ingest/text -> ingest_pipeline.ingest_text_to_index -> chunking + rag_index.build_index
  -> POST /api/ask -> rag_ask.run_ask -> search + prompting + llm_client
  -> POST /api/search -> rag_index.search_index
  -> GET /api/status -> sanitized config (no network probes)
```

The web UI is a thin client: it calls local API endpoints on the same host and does not duplicate RAG logic. **Web text ingest** accepts pasted plain text only — not file uploads, PDF/DOCX parsing, or OCR. The API does not import `chromadb` at startup; Chroma loads only when a request selects that backend.

## Local development

During scaffold and early development, work happens on a laptop with `ARK_ROLE=dev`. No Pi hardware or external services are required.

The default LLM backend is `mock` (`ARK_LLM_BACKEND=mock`). It validates retrieval, prompt assembly, and client wiring without network calls, llama.cpp, or model files. The `openai-compatible` backend is intended for future llama.cpp server use on ark-llm and is opt-in only.

The default index backend is `simple` (`ARK_INDEX_BACKEND=simple`). It provides deterministic lexical search for offline laptop development and tests. The optional `chroma` backend lazy-loads `chromadb` only when selected and is intended for future ark-rag vector storage — install with `pip install -e '.[chroma]'` when ready. Semantic embedding model selection is a future slice. See the root README for details.
