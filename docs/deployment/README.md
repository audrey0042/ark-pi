# Deployment documentation

Ark Pi deployment tooling is **dry-run only** today. Commands in this repo generate, inspect, bundle, verify, and unpack review artifacts — they do not install services, configure networking, or mutate system directories.

| Document | Purpose |
|----------|---------|
| [Two-Pi manual deployment](two-pi-manual.md) | Operator guide for setting up **ark-rag** and **ark-llm** by hand |
| [Architecture: two-Pi layout](../architecture.md) | Design rationale and request flow |
| [Roadmap: deployment slices](../roadmap.md) | What exists today vs. future installer work |
| [deploy/rag-pi/](../../deploy/rag-pi/README.md) | Placeholder notes for ark-rag networking and systemd |
| [deploy/llm-pi/](../../deploy/llm-pi/README.md) | Placeholder notes for ark-llm and llama.cpp |

## CLI deployment commands (review only)

```bash
ark deploy render      # write example env/systemd templates
ark deploy preflight   # inspect rendered templates
ark deploy plan        # dry-run install plan
ark deploy bundle      # portable zip archive
ark deploy verify-bundle   # read-only validation
ark deploy unpack-bundle   # verified extract to staging dir
```

Start with [Two-Pi manual deployment](two-pi-manual.md) for the full operator workflow.
