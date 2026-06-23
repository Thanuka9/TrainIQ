# TrainIQ Production Deployment

This guide covers the multi-process layout, observability stack, and optional infrastructure features added for production hardening.

## Architecture overview

```
                    ┌─────────────┐     ┌──────────────┐
  Users ──────────► │  web :5000  │     │ platform     │
  (LMS tenants)     │ SERVICE_MODE│     │ :5001        │
                    │    = web    │     │ = platform   │
                    └──────┬──────┘     └──────┬───────┘
                           │                    │
                           └────────┬───────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
        PostgreSQL            MongoDB + GridFS         Redis
        (+ read replica)      (+ read URI)        sessions / event bus
              ▲
              │
        ┌─────┴──────┐
        │ ops-worker │  APScheduler + event bus consumer
        └────────────┘
```

| Process | `SERVICE_MODE` | Scheduler | Event bus consumer |
|---------|----------------|-----------|-------------------|
| LMS web | `web` | off | off |
| Platform CEO console | `platform` | off | off |
| Ops worker | `full` (or any) | on | on |
| Monolith (dev) | `full` | optional | optional |

## Quick start (Docker Compose)

### 0. Production preflight (any host)

Before first traffic, validate env and connectivity:

```bash
cp .env.production.example .env
# fill SECRET_KEY, DATABASE_URL, REDIS_URI, CEO credentials, mail, Stripe, etc.
python scripts/production_preflight.py --generate-secret   # optional helper
python scripts/production_preflight.py                     # must pass
```

On Linux/macOS or Windows:

```bash
./scripts/start_production.sh          # preflight → flask db upgrade → gunicorn
.\scripts\start_production.ps1         # same on Windows
```

### 1. Full staging stack (Postgres + Mongo + Redis + app)

Self-contained production-like stack for staging or single-host deploy:

```bash
cp .env.production.example .env
docker compose -f docker-compose.prod.yml up -d --build
```

Runs `migrate` once, then **web** (:5000), **platform** (:5001), and **ops-worker**.

### 2. Application services (external DB)

Requires external Postgres and MongoDB (or run your own). Copy `.env.example` → `.env` and set secrets.

```bash
docker compose -f docker-compose.services.yml up -d --build
```

- **web** — tenant LMS + admin on port 5000  
- **platform** — `/platform/*` CEO console on port 5001  
- **ops-worker** — scheduled DB monitor, ops agents, event bus consumer  

### 3. Observability stack

```bash
docker compose -f docker-compose.observability.yml up -d
```

| Service | URL | Notes |
|---------|-----|-------|
| Prometheus | http://localhost:9090 | Scrapes app `/metrics` |
| Grafana | http://localhost:3000 | Default admin / `$GRAFANA_ADMIN_PASSWORD` |
| Alertmanager | http://localhost:9093 | Routes alerts to webhook/email |

On the app set:

```env
PROMETHEUS_METRICS_ENABLED=true
PROMETHEUS_METRICS_TOKEN=<random-secret>
```

Create `deploy/observability/trainiq_metrics.token` from `trainiq_metrics.token.example` with the same value as `PROMETHEUS_METRICS_TOKEN` (compose mounts the example file by default for local dev).

## Environment variables (infrastructure)

### Service split

```env
SERVICE_MODE=full          # full | web | platform
RUN_SCHEDULER=false        # true only on ops-worker
OPS_WORKER_MODE=true       # ops-worker only
```

### Event bus (Redis Streams)

```env
EVENT_BUS_ENABLED=true
EVENT_BUS_CONSUMER=true    # ops-worker only
EVENT_BUS_STREAM=trainiq:ops:events
EVENT_BUS_GROUP=trainiq-ops-workers
REDIS_URI=redis://redis:6379/0
```

CEO agent actions queue to Redis when the bus is enabled; the ops worker executes them via `execute_agent_action_sync`.

### Read replicas

**PostgreSQL** — analytics queries (CEO dashboard) use the replica bind when set:

```env
DATABASE_READ_REPLICA_URL=postgresql://reader:pass@replica:5432/collective_rcm
```

**MongoDB** — file reads and profile pictures prefer secondary when configured:

```env
MONGO_READ_URI=mongodb://secondary:27017
MONGO_READ_PREFERENCE=secondaryPreferred
```

Writes always use `MONGO_URI` (primary).

### AI cache (S3)

```env
AI_CACHE_S3_BUCKET=trainiq-prod-ai-cache
AI_CACHE_S3_PREFIX=trainiq/ai-cache
AWS_REGION=us-east-1
```

Requires `boto3` and IAM credentials on the host/instance. Falls back to `instance/ai_cache/` on disk if S3 is unavailable.

### Safe auto-remediation

```env
OPS_AUTO_REMEDIATE_SAFE=false   # set true only after validating safe index rules
```

When enabled, scheduled health scans apply **safe-tier** index fixes automatically after detecting issues.

### Schema freeze (production)

```env
SCHEMA_GUARDS_FROZEN=true
DB_BOOTSTRAP_ON_STARTUP=false
```

## Manual deployment (without Docker)

```bash
# Web
set SERVICE_MODE=web
set RUN_SCHEDULER=false
python scripts/run_web.py

# Platform console (separate host/port)
set SERVICE_MODE=platform
set PORT=5001
python scripts/run_web.py

# Ops worker
set RUN_SCHEDULER=true
set OPS_WORKER_MODE=true
set EVENT_BUS_CONSUMER=true
python scripts/run_ops_worker.py
```

Production WSGI (recommended):

```bash
python scripts/production_preflight.py
flask db upgrade
gunicorn -c gunicorn.conf.py app:app
```

Or use `scripts/start_production.sh` / `scripts/start_production.ps1` for the full sequence.

## Migrations

Run once against primary Postgres before starting web workers:

```bash
flask db upgrade
```

## Health checks

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness — Postgres + Redis required for `healthy` |
| `GET /metrics` | Prometheus (token auth when enabled) |

Run `python scripts/verify_infrastructure.py` after deploy to confirm files, env keys, and core routes.

Run `python scripts/production_preflight.py` before cutover to validate secrets, connectivity, and migration head.

## Load / chaos smoke scripts

Optional scripts for staging (not run in CI by default):

```bash
python scripts/load_smoke.py --url http://localhost:5000 --requests 50
python scripts/chaos_smoke.py --redis-uri redis://localhost:6379/0
```

## GDPR hard delete

Platform tenant detail → **Anonymize organization** with **Purge storage** checked:

- Anonymizes users (soft delete)
- Drops tenant Mongo database + GridFS
- Deletes tenant-scoped Postgres content rows

Cannot be applied to the TrainIQ platform organization.

## What is not included

These require separate infra projects (not in this repo):

- MongoDB sharding / multi-region replication setup
- Dedicated CQRS analytics service
- Pen-test remediation automation
- Separate Git repos per microservice

The `SERVICE_MODE` split provides a **deployment boundary** within one codebase; extract to separate services when scale requires it.
