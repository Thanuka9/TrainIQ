# Staging Smoke Test Checklist

Run after deploy to staging before promoting to production.

## Environment

- [ ] `SECRET_KEY`, `DATABASE_URL`, and mail settings are set (not dev defaults)
- [ ] `REDIS_URI` points to staging Redis; rate limits work across workers
- [ ] `SESSION_COOKIE_SECURE=True` when served over HTTPS
- [ ] `flask db upgrade` applied (includes tenant indexes migration)

## Auth & tenancy

- [ ] Register new org via onboarding — receive Office Key
- [ ] Login with Office Key + email + password for tenant A
- [ ] Login fails with wrong Office Key (same email)
- [ ] Second tenant (B) cannot see tenant A users, exams, or courses in admin

## Admin scoping

- [ ] Admin dashboard counts match tenant-only data
- [ ] Reports CSV exports contain only tenant users/scores
- [ ] Exam access approve/reject works; cannot approve cross-tenant request
- [ ] User deactivate/delete/bulk actions affect only selected tenant users
- [ ] Proctor review list shows only tenant sessions

## Exams

- [ ] Regular exam list/start/submit scoped to tenant
- [ ] Special Exam Paper 1 & 2 use tenant-specific IDs and do not leak across tenants
- [ ] Passing score from exam settings (default 70%) applied correctly

## Session / AFK

- [ ] `/ping` returns 401 when logged out
- [ ] Client ping every 5 min keeps session alive under `SESSION_AFK_MINUTES`
- [ ] AFK warning modal appears after ~14 min idle; activity dismisses it
- [ ] Session expires after configured AFK timeout with flash message

## Infrastructure (split deploy)

- [ ] `python scripts/verify_infrastructure.py` exits 0
- [ ] `SERVICE_MODE=web` on tenant workers — `/platform/*` returns 404
- [ ] `SERVICE_MODE=platform` on CEO host — LMS routes absent, `/platform/dashboard` works
- [ ] Ops worker: `RUN_SCHEDULER=true`, `EVENT_BUS_CONSUMER=true` — scheduled jobs run once
- [ ] `EVENT_BUS_ENABLED=true` — CEO agent actions queue; worker processes them
- [ ] `GET /metrics` returns 401 without token when `PROMETHEUS_METRICS_TOKEN` set
- [ ] `python scripts/load_smoke.py --url https://staging...` passes
- [ ] `python scripts/chaos_smoke.py` passes when Redis down (graceful degrade)

## API safety

- [ ] AI/JSON endpoints return generic errors (no stack traces or DB details)
- [ ] Failed login logs mask email addresses

## Automated tests

```bash
pip install -r requirements.txt
pytest tests/ -q
```
