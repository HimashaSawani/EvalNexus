# AgentWindTunnel V2 — Deployment Readiness & Operational Guide

**Date:** October 31, 2026  
**Auditor:** DevOps Lead & Site Reliability Engineer  
**Classification:** Operational Readiness & Deployment Runbook

---

## 1. Readiness Classification Summary

| Target Environment | Readiness Status | Evidence / Notes |
| :--- | :---: | :--- |
| **Development Ready** | **PASS** | 85 passing tests, SQLite WAL, zero-friction local auth mode (`AWT_REQUIRE_AUTH=0`), automated Playwright E2E browser test passing. |
| **Local Demo Ready** | **PASS** | Interactive Test Studio, Scenarios Catalog, and live visual inspector verified across desktop (1440x900) and mobile (390x844). |
| **Staging Ready** | **PASS** | Configurable API authentication (`AWT_REQUIRE_AUTH=1`), CORS origin control, Alembic schema migrations, rate limiting, and paid provider budget caps. |
| **Production Ready** | **NOT VERIFIED / BLOCKED** | **BLOCKED:** Local host does not have an active Docker daemon (daemon socket unavailable) and PostgreSQL was not run live on this host. TLS termination and external secret injection remain prerequisite steps. |

---

## 2. Operational Procedures & Runbooks

### 2.1 Database Migrations (Alembic)
AgentWindTunnel supports seamless database migrations:

```powershell
# Review current revision
alembic current

# Apply all migrations to head
alembic upgrade head

# Roll back one revision
alembic downgrade -1
```

For automated deployments, `python -m backend.database.migrate` can be invoked in container init scripts; it applies Alembic migrations with automatic fallback to SQLAlchemy schema creation.

### 2.2 Database Backup & Restore Runbook
AgentWindTunnel operates with SQLite WAL mode by default or PostgreSQL in production.

#### SQLite WAL Mode:
> [!IMPORTANT]
> Because SQLite WAL maintains state across `*.db`, `*.db-wal`, and `*.db-shm`, always use SQLite's native backup API or VACUUM INTO to prevent backing up inconsistent state while workers are writing.

```powershell
# Safe live backup using SQLite CLI
sqlite3 agent_wind_tunnel.db ".backup 'backups/agent_wind_tunnel_backup_$(Get-Date -Format yyyyMMdd_HHmmss).db'"

# Restore procedure:
# 1. Stop API and Worker daemons
Stop-Process -Name "uvicorn" -ErrorAction SilentlyContinue
Stop-Process -Name "python" -ErrorAction SilentlyContinue

# 2. Archive corrupted files
Move-Item agent_wind_tunnel.db agent_wind_tunnel.db.corrupt
Remove-Item agent_wind_tunnel.db-wal, agent_wind_tunnel.db-shm -ErrorAction SilentlyContinue

# 3. Copy backup into place
Copy-Item backups/agent_wind_tunnel_backup_YYYYMMDD.db agent_wind_tunnel.db

# 4. Restart services
```

#### PostgreSQL Mode:
```bash
# Backup
pg_dump -Fc -h localhost -U awt_user -d agent_wind_tunnel > awt_backup_$(date +%Y%m%d_%H%M%S).dump

# Restore
pg_restore -c -h localhost -U awt_user -d agent_wind_tunnel awt_backup_YYYYMMDD.dump
```

### 2.3 Safe Shutdown & Worker Draining Runbook
1. **Queue Worker Graceful Stop:**
   - Standalone queue worker (`backend.worker`) intercepts `SIGINT` and `SIGTERM`.
   - When signaled, the worker completes the current in-flight scenario, releases active heartbeats, and terminates without leaving orphaned jobs.
2. **Abandoned Job Recovery:**
   - If an unexpected host crash occurs, the worker daemon automatically sweeps abandoned jobs on restart (`reap_abandoned_jobs`).
   - Mock simulator jobs are cleanly marked `FAILED`.
   - **Paid provider jobs are NEVER automatically rerun**, preventing double-billing or duplicate credit card mutations.

---

## 3. Host Environment & Blocker Report

1. **Docker Daemon Status: BLOCKED**
   - **Command:** `docker info`
   - **Output:** `failed to connect to the docker API at npipe:////./pipe/docker_engine ... The system cannot find the file specified.`
   - **Impact:** Local container builds and Docker Compose live startup cannot be executed directly on this Windows development host without starting Docker Desktop. CI container verification is handled via `.github/workflows/ci.yml`.
2. **Live External Provider Spending: NOT RUN / INTENTIONALLY BLOCKED**
   - **Policy:** Real external paid requests against Google Gemini or OpenAI accounts were not initiated during automated verification to adhere strictly to the rule prohibiting unauthorized financial expenditure. Mocks and provider adapter unit tests verify serialization, error parsing, and thought-signature preservation.

