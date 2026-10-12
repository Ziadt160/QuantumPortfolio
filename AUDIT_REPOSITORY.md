# Audit — Phase 1: Repository reconnaissance

Audit date: 2026-10-12. Scope: everything under `D:\TahaSelim\QuantumPortfolio` except third-party
directories (`frontend/node_modules`, `backend/.venv`). The as-found state was inspected **before** any
change. The original backend is preserved byte-for-byte in `audit/original_backend/` (see "Provenance").

## 1. What the project is

A local full-stack demo that compares four portfolio optimisers on one constrained mean–variance problem:

| Solver | Kind | Where |
|---|---|---|
| SLSQP | classical, continuous weights | `backend/quant_engine.py` `get_classical_benchmark` |
| Exact QUBO | classical, exhaustive over the QUBO (`NumPyMinimumEigensolver`) | `backend/quantum_engine.py` |
| Simulated annealing | classical heuristic on the same QUBO | `backend/quantum_engine.py` `_solve_simulated_annealing` |
| CVaR-QAOA | variational quantum algorithm, **noiseless classical simulation** (qiskit-aer) | `backend/quantum_engine.py` `optimize_portfolio_qaoa` |

No real quantum hardware is used or reachable from the code. Intended users: the author and anyone viewing the
demo (portfolio / interview piece). There is no deployment configuration; the only supported mode is two local
dev servers (FastAPI on :8000, Next.js on :3000).

## 2. Repository map

```
QuantumPortfolio/                    as found: not a git repository (see "Version control" below)
├── backend/                         as found: not version-controlled at all
│   ├── main.py                      FastAPI app: request model, pipeline orchestration, in-memory task store
│   ├── quant_engine.py              market data (yfinance), μ/Σ, PCA factor model, metadata table,
│   │                                SLSQP, portfolio_metrics (added in audit), backtest
│   ├── quantum_engine.py            QuadraticProgram construction, QUBO conversion, exact / SA / QAOA,
│   │                                discretisation diagnostics (added in audit)
│   ├── worker.py                    taskiq + Redis broker scaffold — DEAD CODE (never imported)
│   ├── requirements.txt             was 11 unpinned names; now exact pins (audit)
│   ├── requirements-dev.txt         (audit) pytest, hypothesis, httpx
│   ├── pytest.ini, tests/           (audit) 50 tests
│   └── .venv/                       author's environment (Python 3.13.5) — not touched by the audit
├── frontend/                        as found: its own nested git repo, 1 commit ("Initial commit from
│   │                                Create Next App"), uncommitted edits to Dashboard.tsx / package.json
│   ├── src/app/page.tsx             renders <Dashboard/>
│   ├── src/app/Dashboard.tsx        the whole UI (client component): sliders → POST → poll → charts
│   ├── src/app/layout.tsx           root layout, fonts, metadata
│   ├── AGENTS.md / CLAUDE.md        "This is NOT the Next.js you know" (Next 16.2.4)
│   └── README.md, public/*.svg      create-next-app boilerplate (unused assets)
└── audit/                           (audit) verification scripts, data snapshot, results, original code
```

### Module dependencies

```
Dashboard.tsx ──HTTP──▶ main.py ──▶ quant_engine.py ◀── quantum_engine.py
                                  └─▶ quantum_engine.py ──▶ qiskit_optimization, qiskit_aer, dwave.samplers
```
`quant_engine` has no quantum dependency; `quantum_engine` imports `portfolio_metrics` from it (one shared
evaluator for all solvers). Dependency direction is acyclic.

### Data flow of one request

1. `Dashboard.tsx` fetches `/api/universe` (hard-coded 5 tickers), then POSTs slider values to `/api/optimize`.
2. `main.optimize` stores `{"status": "PENDING"}` in the in-process `TASKS` dict and schedules
   `run_optimization_task_logic` as a FastAPI background task (runs in the worker thread pool after the response).
3. Pipeline: `yf.download` (2020-01-01→2023-01-01) → simple daily returns → μ, Σ (×252) → 3-factor PCA model
   (B, F, D) → metadata lookup → SLSQP → QuadraticProgram → QUBO → Exact, SA, QAOA → metrics →
   second `yf.download` (2023 → 2024) → constant-mix backtest.
4. The dashboard polls `/api/task/{id}` every 2 s and renders four strategy cards and a backtest chart.

## 3. Environment and dependencies (as found)

* `backend/requirements.txt` listed `fastapi uvicorn yfinance numpy pandas scipy qiskit>=1.0 qiskit-algorithms
  qiskit-optimization qiskit-aer dimod` with **no versions** and no lock file, no Python version, no README.
* The author's working environment (`backend/.venv`, identical to conda env `quantum`): Python 3.13.5,
  qiskit 1.2.4, qiskit-aer 0.16.0, **qiskit-algorithms 0.3.1**, qiskit-optimization 0.7.0, numpy 2.2.5,
  pandas 2.2.3, scipy 1.15.3, dimod 0.12.20, yfinance 1.3.0 — plus many packages the code never imports
  (dwave-ocean-sdk, qiskit-finance, qiskit-ibm-runtime, qiskit-machine-learning, qiskit-nature, taskiq, redis).
* A clean install of the unpinned file on 2026-10-12 resolves qiskit 2.5.2 / qiskit-algorithms 0.4.0, under
  which the original QAOA call **crashes** (`TypeError: Invalid circuits, expected Sequence[QuantumCircuit]`,
  V1 sampler passed to a V2-only API). qiskit-algorithms 0.4.0 was released 2025-08-29, before the project was
  created, so a fresh install has been broken for the project's whole life; it only ran in the author's
  pre-existing environment. Details: AUDIT_TESTING.md §1.
* Frontend: Next 16.2.4 (upgraded to 16.4.0 during the audit, see AUDIT_PRODUCTION.md §3), React 19.2.4, recharts 3.8.1, framer-motion 12, lucide-react 1.14, Tailwind 4,
  locked by `package-lock.json`.
* No CI/CD, Dockerfile, deployment scripts, logging configuration, notebooks, datasets or tests existed.

## 4. Findings from reconnaissance

### Dead / unreachable code
| Item | Evidence |
|---|---|
| `backend/worker.py` | Never imported; its packages (`taskiq`, `taskiq_redis`, `taskiq_fastapi`) are not in requirements; `TaskiqState` unused. Kept (not deleted) — removal is the owner's call. |
| `"exact_classical"` key in `optimize_portfolio_qaoa` result | "legacy alias", not consumed by `main.py` or the UI. Kept for compatibility. |
| `Sigma` ndarray branch in `_build_quadratic_program` | `Sigma` is always a DataFrame there. |
| Single-ticker branch of `fetch_universe_data` | Unreachable via the API now (`min_length=2`). |
| "Skipping exact solver" branch | Unreachable while `MAX_EXACT_QUBITS == MAX_QAOA_QUBITS == 24` (QAOA guard raises first). |
| Inner `formatChartData` in `Dashboard.tsx` | Shadowed duplicate of the module-level helper (removed in audit). |
| `frontend/public/*.svg`, `frontend/README.md` | create-next-app boilerplate. |

### Hard-coded parameters (none configurable before the audit)
λ_CET1 = λ_LCR = 10; 3 PCA factors; 252 trading days; TQA Δt = 0.75; COBYLA optimiser; 1024 shots; seed 42
(QAOA only — SA was unseeded); simulator method MPS; exact-solver cut-off 24 qubits; duration tolerance ±25 %;
constraint tolerance 1e-3; the 17-ticker metadata table; the 5-ticker universe; date windows and API URL
`http://localhost:8000` in the UI; 2 s × 300 polls.

### Undocumented assumptions (made explicit in AUDIT_SCIENCE.md)
Portfolio-weighted CET1/LCR as a "Basel III" constraint; equity "duration" values; zero risk-free rate in the
Sharpe ratio; constant-mix (daily-rebalanced) backtest without costs; adjusted prices via a version-dependent
yfinance default; factor-model covariance for the discrete solvers vs sample covariance for SLSQP; integer
rounding of durations; ⌊·⌋ and max(1,·) in cap discretisation.

### Hidden state
* In-process `TASKS` dict (unbounded before the audit; lost on restart; not shared across workers).
* `yfinance` live downloads: results depend on the day they are fetched (adjusted prices are revised after
  dividends), so results were not reproducible run-to-run.
* SA used the global `random` module state (unseeded).

### Provenance (important)
`backend/` had no version control, so the audit's edits would otherwise have destroyed the only copy of the
original. `audit/original_backend/` holds a reconstruction of `main.py`, `quant_engine.py`,
`quantum_engine.py` (plus copies of `worker.py`, `requirements.txt`). It is **verified exact**: each file has
the original byte size (5461 / 8963 / 16701, LF line endings) and compiles to bytecode identical to the
CPython 3.11 `.pyc` files cached from the originals before any edit (kept in
`audit/original_backend/pyc_evidence/`).

### Version control
As found, only `frontend/` was a git repository (one create-next-app commit), and the backend had no history at
all. During the audit (2026-10-12 21:50) the owner initialised a repository at the root (commit `095d9b5`,
"Initial commit: QuantumPortfolio", 55 files, with a `.gitignore` that keeps the `.pyc` evidence) and removed the
nested `frontend/.git`. Audit work after that commit appears as uncommitted changes. The audit itself made
no commits.
