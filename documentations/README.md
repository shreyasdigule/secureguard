# SecureGuard Governance Model (SGGM) -- Technical Documentation Library

This directory contains the complete, unabridged, in-depth technical specifications, architectural decision records, and operational guides for the SecureGuard cyber-physical governance platform.

---

## Documentation Index

### Core Architecture & Execution
- **[decisions.md](decisions.md)** (340+ lines): Complete Architecture Decision Records (ADRs 1-10). Details the technical rationale, constraints, and tradeoffs behind PySide6 pinning, PyInstaller packaging, Keycloak RS256/JWT authentication, modal startup profile gating, ISA-101 flat industrial theme standards, SQLite/JSONL persistence, and test isolation.
- **[flow.md](flow.md)** (470+ lines): Exhaustive execution flow mapping. Includes full call graphs for `main_qt.py`, the modal startup profile gate (`startup_profile.py`), `dashboard_qt.py`, `dashboard_sync.py`, the multi-tiered pipeline authorization gate, and the runtime QTimer network.

### Operations & Deployment
- **[analysis_and_run_guide.md](analysis_and_run_guide.md)**: Operational analysis, session authentication enhancements, role matrices (`NORMAL`, `DEGRADED`, `RESTRICTED`, `QUARANTINED`), test user profiles, and manual terminal execution instructions.
- **[containers.md](containers.md)**: Deep-dive into container topology (`Dockerfile.api` and `Dockerfile.dashboard`), headless PySide6 under Xvfb, Mesa software OpenGL rasterization, volume ownership, and production Docker Compose recipes.

### Subsystem Engineering & Roadmaps
- **[safety_twin_report.md](safety_twin_report.md)**: Person 3 physical and process safety validation report, detailing the conveyor physics digital twin, safety envelope boundary enforcement, and anomaly residual engine.
- **[advancement_roadmap.md](advancement_roadmap.md)**: Person 4 five-phase engineering roadmap covering automated CI fixes, cryptographic evidence chaining, advanced HMI telemetry, and publication benchmarks.
- **[dashboard_restoration_plan.md](dashboard_restoration_plan.md)**: Specification for dynamic timeout backoff (`timeout_utils.py`), retry jitter, and HMI widget integration to prevent upstream network/RPC timeouts.
