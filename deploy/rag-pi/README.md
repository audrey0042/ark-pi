# ark-rag deployment (placeholder)

Future responsibilities for the RAG Pi. **Not implemented in the initial scaffold.**

## Static Ethernet

- Assign a static IP on the direct link to ark-llm (e.g. `192.168.50.1/24`).
- Ensure ark-llm is reachable at the configured `ARK_LLM_BASE_URL`.

## WiFi access point

- Configure hostapd (or equivalent) so phones/laptops can connect to ark-rag.
- DHCP for WiFi clients; route/API traffic to the local RAG service.

## systemd services

- `ark-rag.service`: RAG API and web UI (future).
- Optional ingest/index rebuild timer or oneshot unit.

## Storage mounts

- Mount NVMe (or other durable storage) at `/srv/ark-pi/`.
- Expected layout:
  - `/srv/ark-pi/data`: source documents
  - `/srv/ark-pi/indexes`: vector index (Chroma under `indexes/chroma`)

Subdirectories `systemd/`, `network/`, and `wifi-ap/` are reserved for future config snippets. No executable scripts in the scaffold pass.
