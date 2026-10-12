# Audit — Phase 7: Production-readiness and operational review

> The audit brief was truncated mid-sentence in this phase ("Logging without leaking secrets or sensitive…").
> Requirements after that point, and any later phases, were not visible. This document covers the listed items
> plus the operational concerns normally reviewed at this stage (security, resource limits, external services,
> deployment).

## 1. Deployment model (defined here, because the repository defines none)

Evidence: hard-coded `localhost` URLs, no Dockerfile/CI/process manager, in-memory task store, `reload=True`,
dev servers only. The intended model is therefore:

**A single-user, local research/portfolio demo**: FastAPI on 127.0.0.1:8000 plus `next dev` (or `next start`)
on :3000, run by one person on their own machine, using public market data, no accounts, no secrets.

Everything below is judged against that standard first. §5 lists what a hosted multi-user API would additionally
require.

## 2. Assessment

| Area | Status | Notes |
|---|---|---|
| Dependency pinning / environment reproducibility | **Meets** | Exact pins (`requirements.txt`), full lock (`requirements-lock.txt`), dev pins; clean installs verified on CPython 3.11.5 and 3.13.5; npm `package-lock.json`. Not enforced: Python version (no `pyproject.toml` / `python_requires`), Node version (no `engines`). |
| Configuration | **Meets** | `QP_ALLOWED_ORIGINS` (backend CORS), `NEXT_PUBLIC_API_BASE_URL` (frontend, build-time). Algorithm settings are request fields with bounds; remaining constants are named in code. |
| Secrets | **N/A** | The code uses no credentials or API keys. `.env*` and `*.pem` are git-ignored. |
| Input validation | **Meets** | Every request field is bounded (pydantic); tickers normalised and de-duplicated; date order enforced; QUBOs > 24 qubits refused. |
| Resource limits | **Partial** | Per-request work is bounded by field limits and the 24-qubit cap (statevector ≤ 256 MB per circuit). There is **no** per-task timeout, no limit on concurrent tasks (Starlette's thread pool runs them in parallel), and no rate limiting. A 24-qubit request was not timed; at 18 qubits QAOA takes ≈ 10 s. Acceptable for one local user, not for a shared server. |
| Exception handling | **Meets** | Task failures become `{"status": "FAILED", "error": …}` and are logged with traceback. Solver non-convergence is reported in the payload rather than hidden. HTTP 404/422 are used correctly. |
| Observability / logging | **Partial** | Module loggers exist, but engine INFO logs only appear with `python main.py` (which calls `basicConfig`). Under `uvicorn main:app` only access logs show (verified). No metrics, tracing or health endpoint (`/api/universe` works as a liveness probe). |
| Logging without leaking sensitive data | **Meets** | No secrets or personal data are processed. Logs contain tickers, parameters, timings and exception messages. |
| Security — network exposure | **Meets (local)** | Backend now binds 127.0.0.1 (was 0.0.0.0). CORS restricted to the configured origins without credentials (was `*` + credentials). No authentication, which is appropriate only on localhost. |
| Security — dependencies | **Meets after upgrade** | `pip-audit` on the full Python lock: no known vulnerabilities (2026-10-12). `npm audit`: Next 16.2.4 had 30 advisories, rated critical (including GHSA-p293-qw3h-jr36, "Unauthenticated Remote Code Execution on windows-hosted servers", and several SSRF/DoS/cache-poisoning issues), plus postcss/sharp/nanoid/source-map-js. Upgraded to next 16.4.0 and eslint-config-next 16.4.0, then `npm audit fix` → **0 vulnerabilities in production dependencies**. Remaining: 5 high findings that are all one `braces` DoS advisory in the ESLint toolchain (dev-only); npm's only "fix" is a downgrade to eslint-config-next 14, so it was left. Exploitability of the Next advisories in this app was not assessed; the upgrade was made on severity. |
| Resource management | **Meets** | Task store bounded at 100 entries (FIFO). No files or sockets held open. Simulation memory bounded by the qubit cap. |
| External services | **Partial** | Yahoo Finance via the unofficial `yfinance` client: no retry/backoff, no caching, subject to rate limits and Yahoo's terms. Failures surface as task errors. Results change over time (adjusted-price revisions), so the frozen snapshot is the reproducibility reference. |
| Data licensing | **Owner decision** | `audit/data/*.csv` (Yahoo-derived prices) is now committed in the owner's repository. Check Yahoo's terms before publishing the repository publicly; the audit scripts can re-download it (`fetch_universe_data`). |
| Deployment workflow | **Absent** | No Dockerfile, CI, process manager or release process. `main.py`'s `__main__` uses `reload=True` (development only). |
| Scientific honesty in the product | **Meets after fixes** | The UI no longer fabricates progress, reports feasible-portfolio counts, P(optimum) vs random, solver non-convergence and constraint violations, and does not attribute the penalty method to Barkoutsos. |

## 3. Changes made in this phase

* Backend: CORS from `QP_ALLOWED_ORIGINS`, no credentials, methods/headers restricted; bind 127.0.0.1;
  bounded task store; `logger.exception` on task failure; `RUNNING` status; 404 for unknown tasks.
* Frontend: `next` 16.2.4 → 16.4.0 and `eslint-config-next` 16.2.4 → 16.4.0 (exact versions), `npm audit fix` for
  transitive packages. Re-verified: `tsc` 0 errors, ESLint 0 findings, `npm run build` succeeded. A pre-upgrade
  copy of `package.json`/`package-lock.json` is in git history (owner's commit `095d9b5`).

## 4. Verdict

* **As found:** not usable outside the author's machine. A fresh install crashed on every request (D1), and the
  results presented were partly misleading (AUDIT_CORRECTNESS.md, Critical/High).
* **Now, against the defined standard (local single-user demo): ready**, with the documented limitations.
  It installs from pinned requirements on two Python versions, passes 50 tests, runs end to end against live data,
  validates input, reports failures, and has no known vulnerable production dependencies.
* **As a hosted, multi-user service: not production-ready**, and this audit does not claim otherwise.

## 5. What a hosted API would additionally need

1. Authentication and rate limiting; HTTPS termination; CORS for the real origin only.
2. A real job queue with persistence and per-job timeouts/cancellation (Redis + taskiq, as scaffolded in the
   unused `worker.py`, or similar), plus a cap on concurrent QAOA jobs; run CPU-bound work outside the web process.
3. A market-data layer with caching, retries and a licensed data source.
4. Structured logging, metrics (job duration, failures, queue depth) and a health endpoint.
5. Container image + CI (tests, `ruff`, `tsc`, `eslint`, `pip-audit`, `npm audit`) + pinned base image.
6. API response schemas (pydantic models) and API versioning, since this audit already changed the payload.
