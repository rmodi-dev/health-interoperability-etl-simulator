# Health Data Interoperability & ETL Simulator

A **synthetic-data-only** lab-results interoperability pipeline: HL7 v2.5.1 over
MLLP, LIS2-A2 (formerly ASTM E1381/E1394) and FHIR R4B inputs are landed raw,
normalised, quality-gated, and projected into a curated PostgreSQL store with
full lineage.

> **Status: Stage 1 (foundation) — in progress.** The VM platform is built and
> verified; the Python package foundation is being established. Pipeline code
> does not exist yet. Nothing here is production experience — this is newly
> built portfolio work.

## Honesty statement

- **All data is synthetic.** No real patient data, no PHI, anywhere.
- **No invented metrics.** No benchmark, uptime, throughput or user-count claims
  appear in this repo unless backed by a captured log in `docs/evidence/`.
- FHIR output targets **R4B (4.3.0)** via `fhir.resources.R4B`. The mapped subset
  is **AU Core-inspired, not AU Core conformant** (AU Core is based on FHIR R4).
- The API is a **FHIR-subset facade**, not a conformant full FHIR server.
- ISO 15189 rules are **informed by** the standard's data-quality intent and
  mapped to DAMA-DMBOK dimensions; this project is not a certification claim.

## Platform (built and verified)

Ubuntu 26.04.1 LTS on Hyper-V · 8 GB static RAM · 4 vCPU · 64 GB disk ·
4 GB encrypted swap · Docker CE 29.10.1 + Compose plugin v5.8.0 ·
Node.js 24.22.3 · uv 0.13.10 managing Python 3.12.16 ·
Tailscale private mesh for all developer/SSH/MLLP access.

Reproducible VM infrastructure lives in [`vm/`](vm/README.md).

## Quick start (current stage)

```bash
git clone https://github.com/rmodi-dev/health-interoperability-etl-simulator.git
cd health-interoperability-etl-simulator
uv sync                 # Python 3.12, locked dependencies
uv run pytest -q        # foundation smoke tests
uv run ruff check .
```

## Planned architecture

```
synthetic generator
  ├─ HL7 v2.5.1 ORU^R01 / MLLP :2575
  ├─ LIS2-A2 frames / TCP :3000 → Node.js gateway
  └─ FHIR R4B Bundle / HTTP :8000
        ↓
   raw (immutable payload + sha256 + dedupe)
        ↓  parse → stg
   DQA engine (ISO 15189-informed, DAMA-mapped)
        ├─ pass → core → FHIR R4B projection
        └─ fail → quarantine (rule, severity, dimension, lineage)
        ↓
   PostgreSQL: raw | stg | core | dq | fhir | analytics KPI views
```

## Licence

MIT — see [LICENSE](LICENSE).