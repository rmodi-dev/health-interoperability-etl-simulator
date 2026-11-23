
# Health Interoperability ETL Simulator

An Open-Source Interoperability Stack Topology for HL7 v2 and ASTM to FHIR R4 lab-results pipeline.

## Quick Start

```bash
# Start lightweight core stack (Postgres + App)
docker compose up -d --build

# Start full stack including HAPI FHIR Sandbox
docker compose --profile full up -d --build
```
