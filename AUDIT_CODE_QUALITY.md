# Audit — Phase 5: Software architecture and code quality

Scope: `backend/*.py` (≈ 830 lines originally, ≈ 1000 now), `frontend/src/app/*.tsx` (≈ 480 lines).
The goal is readable, scientifically transparent code for a demo, not enterprise abstraction. Recommendations
are only made where they have a concrete benefit.

## 1. Architecture

| Aspect | Assessment |
|---|---|
| Separation of concerns | **Good at module level.** `quant_engine` (data, statistics, classical solver, metrics, backtest) has no quantum dependency. `quantum_engine` holds formulation and discrete solvers. `main` is orchestration and HTTP. The UI is one client component. |
| Dependency direction | Acyclic: `main → quant_engine`, `main → quantum_engine → quant_engine.portfolio_metrics`. |
| Duplication | Originally the metric/feasibility logic existed twice (`_metrics` for discrete solvers, ad-hoc code in SLSQP), which is how the two drifted apart (SLSQP had no feasibility report). Now one `portfolio_metrics` serves all four solvers. The frontend had a duplicated `formatChartData` (removed). |
| Interfaces | Weakest point. Every function returns untyped `dict[str, Any]`; the API response has no schema; the TypeScript `OptimizeResult` type is maintained by hand and drifted (`p=5` fallback). **Recommendation:** pydantic response models in `main.py` give an OpenAPI schema and validation for free. |
| Function size | `optimize_portfolio_qaoa` (~200 lines) builds the QP, converts it, runs three solvers and computes diagnostics. It is still linear and readable, but splitting into `run_exact`, `run_sa`, `run_qaoa` would make each solver testable in isolation. Not done, to keep the diff reviewable. |
| Public API | Tests and audit scripts call underscore-private functions (`_build_quadratic_program`, `_linear_ramp_initial_point`). That is acceptable for a demo; promote them if the package is reused. |
| Configuration | Hard-coded values are now named module constants (`MAX_EXACT_QUBITS`, `MAX_QAOA_QUBITS`, `AER_METHOD`, `CONSTRAINT_TOL`, `DURATION_TOLERANCE_FRAC`, `MAX_TASKS`) or request fields. Still embedded: λ_CET1 = λ_LCR = 10, 3 factors, 252 days, Δt = 0.75, round-off tolerance 1e-12, the metadata table and the 5-ticker universe. |

## 2. Correctness and maintainability

| Aspect | Original | Now |
|---|---|---|
| Type annotations | Signatures annotated; return types `Dict[str, Any]`. | Same style kept; new code annotated. No static type checker configured. |
| Input validation | None (any float/int accepted). | Pydantic bounds and validators on every field; `ValueError` for oversize QUBOs, empty downloads and too little history. |
| Error handling | SLSQP failure masked by equal weights; task errors stored without traceback; exact-solver errors downgraded to a warning; frontend `catch {}` with a generic message. | Failures surface as `success`/`violations`/`FAILED` with `logger.exception`; HTTP errors shown in the UI. Exact-solver errors still downgrade to `exact: null` (logged), which is acceptable because the API shape allows it. |
| Logging | Module loggers but no configuration, so INFO messages were never emitted. | `logging.basicConfig` when run as `python main.py`. Under the `uvicorn main:app` CLI, uvicorn's log config applies and engine INFO logs stay hidden. A `--log-config` file is recommended for deployments. |
| Hidden global state | Unbounded `TASKS`; global `random` state in SA. | `TASKS` bounded; SA seeded through its API. `TASKS` remains process-local. |
| Magic numbers | Many (AUDIT_REPOSITORY.md §4). | Most now named; see the table above for the rest. |
| Naming | Mostly clear; `q_factor` is the risk-aversion weight (now documented); `Sigma` vs `Sigma_full` vs `Sigma_f` inconsistent; `l` as a variable name (E741, fixed). | |
| Numerical robustness | Float flooring `int(x·R)`; banker's rounding; round-off Pauli terms crashing QAOA at 18 qubits. | `_floor_slices`, `_round_half_up`, `_NormalizedCostSolver`; all regression-tested. |
| Static analysis | Ruff (E,F,W,B,UP): 23 findings in the original backend (2 unused imports, 1 ambiguous name, 20 style). | Production modules: 0 Pyflakes (F) findings; remaining 25 are `typing.Dict`-style (UP006/UP035, matching the existing idiom) and one `zip` without `strict=` over equal-length sequences. |

## 3. Python and scientific computing

| Aspect | Assessment |
|---|---|
| Dependency versions | Originally unpinned → broken on fresh installs (D1). Now exact pins (`requirements.txt`) + full lock (`requirements-lock.txt`) + dev pins. Tested on CPython 3.11.5 and 3.13.5. |
| NumPy / SciPy usage | Correct and idiomatic. `np.cov(ddof=1)` semantics via pandas; `eigh` on a symmetric matrix; SLSQP on a convex QP with analytic objective (no gradient supplied, so finite differences, which is fine at n = 5). |
| Qiskit usage | As found, used the deprecated V1 primitives and the unmaintained `qiskit-algorithms`. Now `qiskit_optimization.minimum_eigensolvers` + Aer `SamplerV2` + an explicit pass manager. One upstream interaction (Qiskit 2.5 cannot hash some parameter expressions) is worked around with a mathematically neutral operator clean-up and documented in place. |
| RNG handling | QAOA: `seed` → Aer (each circuit execution re-uses the seed, i.e. common random numbers across optimiser iterations — deliberate and reproducible). SA: seed through dwave-samplers. Audit scripts: `np.random.default_rng(seed)`. No global seeding. Verified by `test_same_seed_is_reproducible`. |
| dtype / device | float64 throughout; CPU only; no GPU paths. |
| Memory / complexity | Statevector simulation is 2^n·16 B per circuit (256 MB at the 24-qubit cap). Exact solver is exponential in n (capped at 24). `discretisation_summary` enumerates the integer grid in Python, but only when it has ≤ 200 000 points. `_uniform_probability` loops over 2^n bitstrings, but only when n ≤ 12. |
| Resource cleanup | No files, sockets or threads are left open by the backend; Aer manages its own thread pool. |
| Notebooks | None exist; no hidden notebook state. |

## 4. Frontend

* Single 480-line client component. Acceptable for one page; extracting `StrategyCard`/`Slider` into files would
  help if the UI grows.
* `npx tsc --noEmit` and `npm run lint` (ESLint 9, `eslint-config-next`) pass; `npm run build` succeeds on Next
  16.2.4 and, after the security upgrade, on 16.4.0 (Turbopack). No frontend tests exist.
* The API URL is now `NEXT_PUBLIC_API_BASE_URL` (inlined at build time, per the Next.js docs bundled in
  `node_modules/next/dist/docs/01-app/02-guides/environment-variables.md`), defaulting to `http://localhost:8000`.
* Rendered and exercised in Chrome at desktop width (AUDIT_TESTING.md §4). That check found and fixed a stale
  SA label, an inaccurate SLSQP label and pre-existing Recharts `width(-1)` console warnings.
* Not reviewed: accessibility (slider labels are not programmatically associated with inputs) and phone-width layout.

## 5. Prioritised recommendations

1. Response models (pydantic) for the API, with a generated TypeScript type for the UI.
2. (Git now exists.) Add CI that runs `pytest -m "not slow"`, `ruff check`, `tsc`, `eslint`.
3. Split `optimize_portfolio_qaoa` into one function per solver.
4. Add a Python formatter/linter configuration (ruff) and optionally mypy with `--ignore-missing-imports`.
5. Move the metadata table into a data file with sources (R2 in AUDIT_CORRECTNESS.md).
