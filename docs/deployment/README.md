# Deployment docs

`ark deploy *` is dry-run only. It writes templates and zip bundles for review. Nothing here installs services or touches system dirs.

Right now you deploy by hand: [two-pi-manual.md](two-pi-manual.md). [install.sh](../../install.sh) can install apt-based OS prerequisites, bootstrap the app, render templates, and install service files with `--install-services`. Full Pi setup: [roadmap §36](../roadmap.md#36-installer-bootstrap).

| Doc | |
|-----|--|
| [two-pi-manual.md](two-pi-manual.md) | Manual ark-rag / ark-llm setup (current path) |
| [installer-bootstrap-contract.md](installer-bootstrap-contract.md) | Installer contract; OS packages + app bootstrap live |
| [../architecture.md](../architecture.md) | Why two Pis |
| [../roadmap.md](../roadmap.md) | Done vs future |
| [../../deploy/rag-pi/](../../deploy/rag-pi/README.md) | ark-rag placeholders |
| [../../deploy/llm-pi/](../../deploy/llm-pi/README.md) | ark-llm placeholders |

```bash
ark deploy render
ark deploy preflight
ark deploy plan
ark deploy bundle
ark deploy verify-bundle
ark deploy unpack-bundle
```

Full walkthrough: [two-pi-manual.md](two-pi-manual.md).
