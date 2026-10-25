# AgentWindTunnel V1

A local evaluation harness for refund support agents. FastAPI serves a seven-section HTML/JavaScript dashboard. SQLAlchemy stores runs, a persistent queue, scenario fixtures, traces, checks, and refund requests in SQLite (WAL mode with a five-second lock wait). A worker executes scenarios sequentially using either the deterministic mock or a real tool-calling provider.

V1 covers `get_order`, `check_refund_eligibility`, and idempotent `request_refund`. It simulates refund requests; `REFUND_REQUESTED` never proves money was returned. It does not connect to a payment gateway or support arbitrary external agents. Only SQLite is verified; PostgreSQL support and migrations have not been tested. Fresh schemas use SQLAlchemy `create_all`; there is no versioned migration system. Back up existing databases before upgrading.

## PowerShell setup and startup

```powershell
Set-Location D:\AgentWindTunnel
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Only for initial setup when .env does not already exist:
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$env:DATABASE_URL = 'sqlite:///./agent_wind_tunnel.db'
$env:AWT_EMBEDDED_WORKER = '1'
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

On the existing Python environment used for verification, the exact startup is:

```powershell
Set-Location D:\AgentWindTunnel
$env:DATABASE_URL = 'sqlite:///./agent_wind_tunnel.db'
$env:AWT_EMBEDDED_WORKER = '1'
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. `/healthz` checks the API process; `/readyz` checks database connectivity. Readiness does not prove worker liveness. Python 3.13 with the existing installed dependencies was used for delivery testing. The clean-environment attempt and any limitations are recorded in the delivery report; dependency declarations currently use minimum versions rather than a lockfile.

The default `AWT_EMBEDDED_WORKER=1` starts one worker in the API process. Use one API process; avoid `--reload` and multiple uvicorn workers for this mode. For a standalone worker, set the following in **both terminals**:

```powershell
Set-Location D:\AgentWindTunnel
$env:DATABASE_URL = 'sqlite:///./agent_wind_tunnel.db'
$env:AWT_EMBEDDED_WORKER = '0'
```

API terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Worker terminal:

```powershell
.\.venv\Scripts\python.exe -m backend.worker
```

Worker claims use conditional SQLite status updates. Heartbeats run about every three seconds; jobs with a heartbeat older than 30 seconds are reaped as failed. Active scenario attempts become `INTERRUPTED`, with their existing evidence preserved. Paid jobs are never automatically replayed. Cancellation stops between scenarios; it cannot revoke an already committed simulated write. Refreshing the browser does not stop the worker.

## Providers, credentials, and bounds

Mock is explicitly selected and does not make provider calls. Selecting Gemini or OpenAI requires its project-configured environment key; a missing or failing key does not cause fallback to mock. Credentials are server-side. `.env` is ignored and excluded from Docker build context. Settings indicate configuration presence, not successful authentication or verified tool calling. Model discovery is advisory; actual live tool-call evidence is required.

Default scenario limits: six turns, ten tool calls, 15,000 tokens, 30-second scenario deadline, five-second tool timeout. Queued configuration is passed to the runner. Provider requests receive a remaining-time timeout with implicit SDK retries disabled. Final model responses are also checked against elapsed scenario time. These are cooperative bounds, not process termination: scheduling, database commits, network cleanup, and up to 0.5 seconds of settlement per active future can extend observed duration. Token checks occur between calls, so a response may exceed the remaining budget. A timed-out tool future remains tracked; cancellation tokens guard late writes and unresolved writes prevent state-dependent checks from claiming certainty. Each production tool future owns its own SQLAlchemy session; background traces are buffered and persisted in order by the runner thread. Timeout trace persistence occurs during settlement, outside the deadline-sensitive return path.

## Evaluation and outcomes

`OWNERSHIP` checks customer/order scope; `ELIGIBILITY` checks refund policy against a fixed scenario clock; `DUPLICATE` checks idempotency; `STATE` checks saved amounts and refund state; `COMPLETION` checks bounded execution. Expectations are scenario-specific. These deterministic checks do not prove general model safety or semantic truth of every answer. Inspect the final answer and trace.

Scenario `PASSED`/`FAILED` describe evaluated behavior; `PROVIDER_ERROR` excludes provider setup failures from a behavioral conclusion; unresolved state can yield non-evaluated checks. Parent `COMPLETED` means the selected attempts finished, and can include behavioral failures. Infrastructure exceptions cause parent `FAILED` and retain a sanitized queue error. `CANCELLED` and `INTERRUPTED` must be interpreted separately. Saved aggregate pass rates are descriptive, not claims of benchmark improvement. One provider execution is not a repeatability study.

## Web verification and automated tests

In Test Studio, select provider, its model, agent version and a single scenario. Run once, then run Development Suite. Watch progress, refresh during execution, reopen the hash URL, and inspect Evaluator Checks, Trace Stepper, Database State, Final Answer and Raw JSON. Test History filters; compare compatible runs and a model/provider mismatch. Download JSON and Report and compare with `/api/runs/{id}`. Cancel a development suite. Inspect all seven sections at desktop and 390px widths; check console/network failures and loading, empty and error states.

```powershell
Set-Location D:\AgentWindTunnel
.\.venv\Scripts\python.exe -m pytest tests -q
```

The test configuration creates a temporary SQLite database before application imports, so API tests do not use the user database. Local browser verification used Python Playwright and installed Chromium. Evidence, exact outcomes and remaining checks are in [the delivery report](docs/reports/delivery-2026-10-24/VERIFICATION.md). The retained `verify_*.py` scripts reproduce the delivery checks; Playwright is an optional development dependency (`python -m pip install playwright`, then `python -m playwright install chromium`). Verification scripts bind ports 8765/8766 and use databases in the report directory.

## Docker and deployment

```powershell
Set-Location D:\AgentWindTunnel
docker compose up --build
```

Compose packages a web service with its embedded worker disabled and a separate worker sharing the `awt_data` named volume at `/data`. The image creates writable `/data` for its unprivileged user. The worker disables the API-specific image health probe. API health and readiness are available through port 8000. Compose binds the host port to loopback. Keep the named volume to preserve history; do not run `docker compose down -v` against data you need.

Docker build, service health and persistence are pending wherever Docker is unavailable. No public hosting target is configured or authorized in this repository. Before public exposure, supply a hosting account/service, persistent SQLite storage, TLS, authentication that protects every API route, and server-enforced paid-execution admission/concurrency and spending limits (including direct execution endpoints). V1 currently has no authentication or global spending cap. Keep it on loopback until those requirements are implemented and verified. No public URL is claimed.

## Three-minute demonstration

1. **0:00–0:40:** Open Overview and Scenarios. Explain fixed fixtures, simulated refunds and separate behavioral/completion rates.
2. **0:40–1:20:** Select Mock, Version B and an eligible scenario. Run it; inspect its checks, final answer and `REFUND_REQUESTED` ledger entry.
3. **1:20–2:10:** Run Development Suite and refresh while it executes. Reopen the same run URL. Select timeout-after-write and inspect fault trace and idempotency evidence. Never describe a request as money returned.
4. **2:10–3:00:** Open History, apply filters, compare two runs and explain any mismatch. Download JSON and Markdown. Open Settings to show credential configuration status and local execution bounds.
