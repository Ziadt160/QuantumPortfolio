# QuantumPortfolio

A local demo that solves one constrained mean–variance portfolio problem four ways and shows the results side by side:

| Solver | What it is |
|---|---|
| **SLSQP** | Classical continuous optimisation (SciPy). |
| **Exact QUBO** | Exhaustive minimisation of the discretised problem's QUBO (Qiskit `NumPyMinimumEigensolver`). |
| **Simulated annealing** | Classical heuristic on the same QUBO (dwave-samplers). |
| **CVaR-QAOA** | The quantum approximate optimisation algorithm (p = 3, CVaR α = 0.25, linear-ramp start), **simulated noiselessly on a classical computer** with qiskit-aer. |

Inputs are 2020–2022 daily prices from Yahoo Finance; the portfolio is back-tested on 2023.

## What this project does and does not show

* It shows a complete, verified pipeline: data → factor model → QUBO/Ising encoding → QAOA circuit → decoding, with
  every step checked against independent calculations (`AUDIT_NUMERICS.md`).
* It does **not** show a quantum advantage. At the sizes it can simulate (≤ 24 qubits), enumerating every
  solution classically takes milliseconds while simulated QAOA takes seconds. QAOA's state puts 2.5–3.3× the
  random-guess probability on the optimum (9–18 qubits). At the default settings the discrete problem has exactly
  one feasible portfolio, so every discrete solver returns the same answer.
* No real quantum hardware or noise model is used.
* The "Basel III" CET1/LCR constraints are a stylised device (portfolio-weighted averages of bank ratios), not a
  regulatory requirement. Equity "durations" and bank ratios are illustrative constants.

Details: `AUDIT_SUMMARY.md`.

## Requirements

* Python 3.11 or 3.13 (both tested), Windows 11 (tested; Linux/macOS should work but were not tested)
* Node.js 22 (tested with 22.19.0) and npm
* Internet access for Yahoo Finance when using the app (tests and the audit scripts run offline)

## Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate                 # PowerShell / cmd.  Git Bash: source .venv/Scripts/activate
python -m pip install -r requirements-dev.txt   # runtime + test tools (exact pins)
# or, for the exact transitive set tested on CPython 3.11:  pip install -r requirements-lock.txt

python -m pytest                       # 50 tests, ~20-35 s, offline
python -m pytest -m "not slow"         # skip the end-to-end timing test

uvicorn main:app --port 8000           # API on http://127.0.0.1:8000 (used in the audit's live run)
# or: python main.py                   # same, with auto-reload and engine INFO logs (not launched in the audit)
```

Configuration (environment variables):

| Variable | Default | Purpose |
|---|---|---|
| `QP_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Browser origins allowed by CORS |

API: `GET /api/universe`, `POST /api/optimize` (returns `task_id`), `GET /api/task/{task_id}`
(`PENDING` → `RUNNING` → `COMPLETED` / `FAILED`; unknown id → 404; invalid request → 422).
Interactive docs at `http://127.0.0.1:8000/docs`.

## Frontend

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000  (the backend must be running)
npm run build          # production build (verified in the audit)
```

`NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`) sets the backend URL. It is inlined at build time.
This Next.js version (16.4) differs from older releases; read `frontend/AGENTS.md` before changing frontend code.
The audit verified `tsc`, `npm run lint`, `npm run build`, and a full run of the dashboard in Chrome at desktop
width (`npm run dev` + backend). Phone-width layout was not checked.

## Reproducing the audit

From the repository root, with the backend environment active:

```bash
python audit/run_pipeline_snapshot.py --code current --out audit/results/current_pipeline_default.json
python audit/verify_numerics.py                        # 69 independent checks → audit/results/numerics_table.md
python audit/qaoa_study.py --configs C1,C2 --seeds 20 --out audit/results/qaoa_study_9q.jsonl
python audit/qaoa_study.py --configs C3 --seeds 10 --out audit/results/qaoa_study_18q.jsonl
python audit/analyze_qaoa_study.py audit/results/qaoa_study_9q.jsonl audit/results/qaoa_study_18q.jsonl
python audit/mutate.py <scratch_dir> <python_exe>      # regression tests vs re-introduced defects
```

`audit/data/` holds the frozen Yahoo snapshot (SHA-256 in `AUDIT_NUMERICS.md`). `audit/original_backend/` is the
backend as found, verified byte-exact. It only runs with qiskit-algorithms 0.3.x (e.g. the original
`backend/.venv`); `run_pipeline_snapshot.py --code original` reproduces its results there.

## Audit documents

| File | Content |
|---|---|
| `AUDIT_SUMMARY.md` | Verdicts and the most important findings |
| `AUDIT_REPOSITORY.md` | Repository map, data flow, dead code, hidden state |
| `AUDIT_SCIENCE.md` | Mathematical formulation, claims and verdicts, quantum-specific checks |
| `AUDIT_NUMERICS.md` | Independent recomputation of every reported number; QAOA repeated-trial study |
| `AUDIT_CORRECTNESS.md` | Prioritised defect list with locations, impact, reproduction and fixes |
| `AUDIT_CODE_QUALITY.md` | Architecture and code-quality review |
| `AUDIT_TESTING.md` | Test suite, mutation check, clean-install runs |
| `AUDIT_PRODUCTION.md` | Deployment model, security, operational readiness |
