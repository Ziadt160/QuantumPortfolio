# Audit — Phase 4: Algorithm and implementation correctness

The pipeline was traced from request to response (AUDIT_REPOSITORY.md §2). Intermediate objects were checked, not
only outputs: moments, factor covariance, the QuadraticProgram at every integer point, the QUBO and the Ising
operator at every basis state, the bound circuit parameters, the QAOA state vector, the sampled histogram, the
selection rule, metrics and the backtest (AUDIT_NUMERICS.md).

**Code that executes vs code that is correct.** Every metric the original code reported is arithmetically correct
for the quantities it computed (AUDIT_NUMERICS.md §2). The defects are in *what* was computed and presented: a
problem that differed from the stated one, a "ramp" that wasn't, a success criterion a random sampler meets, and
failure paths that returned plausible numbers.

Line numbers refer to `audit/original_backend/<file>` (the code as found, preserved byte-exact). "Now" points to the
current code. Status: **Fixed** (code changed, regression test added), **Reported** (behaviour kept, now made
visible in the API/UI), **Open** (recommendation only).

## Critical

| ID | Defect | Where | Impact | Reproduce | Fix / status |
|---|---|---|---|---|---|
| D1 | Fresh installs crash in QAOA: `TypeError: Invalid circuits, expected Sequence[QuantumCircuit]`. Unpinned `qiskit-algorithms` resolves to 0.4.x (released 2025-08-29), which only accepts V2 primitives; the code passes Aer's deprecated V1 `Sampler`. | `quantum_engine.py:34-36, 395-398`; `requirements.txt` | Every `/api/optimize` task ends FAILED on any new machine. The project only ran in the author's pre-existing env. | `pip install -r audit/original_backend/requirements.txt` in a clean venv, then `python audit/run_pipeline_snapshot.py --code original …` | **Fixed.** QAOA/NumPyMinimumEigensolver/COBYLA from `qiskit_optimization.minimum_eigensolvers` (supports V1+V2), `qiskit_aer.primitives.SamplerV2` + transpiler pass manager, exact version pins + lock file. Verified clean installs on Python 3.11 and 3.13. |
| D2 | CET1/LCR "soft constraint" is added even when the minimum is 0 (the default), as λ(c·w)² + λ(ℓ·w)². | `quantum_engine.py:90-115` | The discrete objective penalises *every* bank holding: 4.28 for 50 % GS vs a portfolio objective of −0.064. Whenever several portfolios are feasible, banks are pushed out by a constraint that does not exist. SLSQP (hard ≥ 0, vacuous) solved a different problem. | N8, N9; `test_vacuous_basel_minimum_adds_no_penalty` | **Fixed** (now `quantum_engine.py:139,153`: penalty only if min > 0). Two-sidedness for min > 0 is **Reported** (docstring, UI hint) with **Open** R1. |
| D3 | QAOA initial point is not the advertised linear ramp: (a) interleaved [β₀,γ₀,β₁,…] vs Qiskit's block order; (b) positive β with Qiskit's +ΣX mixer anneals toward the *maximum* of H_C; (c) Δt = 0.75 applied to an operator with max coefficient 25–50, so phases wrap. | `quantum_engine.py:242-253, 400` | The start state had ⟨H_C⟩ = +9.9 (> uniform 0) and 0.5× uniform probability on the optimum. The documented algorithm (Sack & Serbyn TQA) was never run. | N25.o, N29; `test_linear_ramp_binds_to_the_right_parameters`, `test_linear_ramp_anneals_towards_the_minimum` | **Fixed** (`_linear_ramp_initial_point` :278, `_NormalizedCostSolver` :244 normalises H_C to max\|c\| = 1). The corrected start gives 2.3× uniform; final P(optimum) improves significantly at 9 qubits (AUDIT_NUMERICS §4). |

## High

| ID | Defect | Where | Impact | Reproduce | Fix / status |
|---|---|---|---|---|---|
| D4 | SLSQP failure silently replaced by equal weights, renormalised, reported with no status. | `quant_engine.py:163-167` | A non-converged, constraint-violating portfolio (e.g. 20 % each when T = 9) is displayed as the classical optimum. | `audit/results/original_repro_slsqp_failure.json`; `test_slsqp_failure_is_reported_not_replaced` | **Fixed**: last iterate returned with `success`, `solver_message`, `feasible`, `violations`, `duration_residual`. UI shows "solver did not converge". |
| D5 | Per-asset cap can be silently exceeded: `max(1, ⌊a·R⌋)` loosens the cap when a·R < 1, and the per-asset check was removed from `_metrics` (its comment's reasoning is wrong: flooring only tightens). | `quantum_engine.py:71, 207-210` | a = 0.25, R = 2: Exact/SA/QAOA return 50 % positions labelled `feasible: true`. | `audit/results/original_repro_asset_cap.json`; `test_metrics_reports_asset_cap_violation` | **Fixed** (check restored in `portfolio_metrics`) + **Reported** (`qubo.effective_max_asset_weight`). |
| D6 | "Same constrained problem" is false: SLSQP optimised the sample covariance, the discrete solvers the 3-factor covariance. Risk numbers on the four cards were not comparable. | `main.py:54, 62` | Mixed risk models on one dashboard (SLSQP vol 0.3126 vs 0.3181 on the factor model). | N16 | **Fixed**: all four use Σ_f; the risk model is reported in `data.risk_model`. Remaining inherent differences (rounding, caps, soft vs hard) are **Reported** (AUDIT_SCIENCE §3). |
| D7 | The default configuration has exactly one feasible discrete portfolio, so Exact/SA/QAOA cannot differ and the objective is irrelevant. | design (`_build_quadratic_program`, defaults) | The headline comparison is degenerate. | N10 | **Reported**: `qubo.num_feasible_portfolios` in the API and a "Feasible" chip in the UI. **Open** R3. |
| D8 | QAOA quality is presented through the best-of-1024-shots feasible sample, which a uniform random sampler matches at ≤ 9 qubits. No probability metric was exposed. | `quantum_engine.py:408-413` (MEO selection) | "QAOA found the optimum, gap 0 %" is uninformative and reads as evidence of quantum performance. | N31, study | **Reported**: `p_optimal`, `uniform_p_optimal`, `p_feasible`, `p_returned_solution`, `qaoa_config.selection` in the API; "P(optimum) x % vs y % random" on the QAOA card. |
| D9 | `gap_to_optimal_pct` measured on `portfolio_objective` (no penalties) while Exact minimises the penalised objective, and gated on tolerance-based `feasible`. | `quantum_engine.py:417-424` | With min CET1/LCR > 0 the "optimum" is not optimal for the measured quantity; negative gaps possible. | — | **Fixed**: gap on `qp_objective` (what Exact minimises), gated on `qp_feasible` (hard constraints of the discrete QP). |
| D10 | After D1's migration, QAOA crashed at 18 qubits (`OverflowError` hashing parameter expressions) because the Ising operator contains round-off coefficients (\|c\| < 1e-12) and Qiskit 2.5 cannot hash those expressions. | upstream interaction; triggered in `meo.solve` | R = 4 requests fail. | `audit/qaoa_study.py --configs C3` before the fix | **Fixed**: `_NormalizedCostSolver` drops terms with \|c\| ≤ 1e-12·max\|c\|. Test: `test_cost_operator_is_cleaned_and_normalised`. |

## Medium

| ID | Defect | Where | Impact | Fix / status |
|---|---|---|---|---|
| D11 | Duration target `int(round(T))·R` uses round-half-to-even on T before scaling. | `quantum_engine.py:131` | T = 4.5 silently treated as 4.0 (dashboard step is 0.5). | **Fixed**: `round_half_up(T·R)`; `test_duration_target_is_rounded_on_slice_scale`. |
| D12 | `ffill().bfill()` copies future prices into earlier gaps (look-ahead, zero returns). | `quant_engine.py:34` | Biased μ/Σ for tickers with late starts. | **Fixed**: `ffill().dropna()`; `test_fetch_does_not_backfill_future_prices`. |
| D13 | SA baseline used dimod's pure-Python reference sampler (documented as unsuitable for benchmarking), unseeded. | `quantum_engine.py:290` | Non-reproducible; 5.1 s instead of 0.03 s distorted the wall-clock comparison. | **Fixed**: `dwave.samplers.SimulatedAnnealingSampler(seed=…)`. |
| D14 | MPS simulator for dense all-to-all ZZ circuits. | `quantum_engine.py:396` | 18.2 s vs 0.10 s per circuit at 18 qubits. | **Fixed**: `AER_METHOD = "statevector"` (also exact). |
| D15 | Metadata aligned to weights by *position* (`.values`) in `_metrics`/SLSQP. | `quant_engine.py:147-157`; `quantum_engine.py:212-228` | Latent: correct only because both come from `prices.columns`. | **Fixed**: label-based `reindex(mu.index)`; `test_metrics_align_metadata_by_label_not_position`. |
| D16 | No request validation (q_factor, exposures, resolution, reps, shots, tickers, dates). | `main.py:28-45` | Nonsense inputs accepted; `budget_resolution` or `qaoa_reps` large enough to exhaust CPU/RAM. | **Fixed**: pydantic `Field` bounds, ticker/date validators, `MAX_QAOA_QUBITS = 24`; `test_invalid_requests_are_rejected`, `test_qubit_guard`. |
| D17 | Dashboard progress log is fabricated on a timer ("Running Exact…", "QAOA optimisation step 24…"). Also: "Processing statevector" (backend was MPS), fallback "p=5" (backend default 3), "(Barkoutsos 2020)" penalty attribution, silent exit after 10 min of polling, no `res.ok` checks. | `frontend/src/app/Dashboard.tsx` | Misrepresents what ran. | **Fixed**: real status + elapsed time, explicit timeout and HTTP errors, corrected labels. The browser check also fixed the stale "dimod" SA label and Recharts `width(-1)` warnings. |
| D18 | Adjusted vs raw prices depended on yfinance's default; empty downloads produced obscure downstream errors. | `quant_engine.py:28` | Version-dependent data semantics. | **Fixed**: `auto_adjust=True`, explicit `ValueError`s; `test_fetch_raises_on_empty_download`. |
| D19 | Unknown tickers silently receive invented metadata (duration 5.0, sector "Other"). | `quant_engine.py:107-115` | Constraints silently built on placeholders. | **Reported**: warning log + `data.metadata_defaulted` in the response. |
| D20 | `qubo_fval` is the QP objective incl. soft penalty, not a QUBO energy. | `quantum_engine.py:413` | Mislabelled metric. | **Fixed**: replaced by `qp_objective` / `qp_feasible` on every discrete solver. |

## Low

| ID | Defect | Where | Fix / status |
|---|---|---|---|
| D21 | Unknown task id returns HTTP 200 with `FAILED`. | `main.py:139-142` | **Fixed**: 404. |
| D22 | CORS `allow_origins=["*"]` with `allow_credentials=True` (Starlette reflects any origin). | `main.py:17-23` | **Fixed**: origins from `QP_ALLOWED_ORIGINS` (default localhost:3000), no credentials. |
| D23 | Unbounded in-memory `TASKS`. | `main.py:25` | **Fixed** (bounded to 100); still per-process (Open R6). |
| D24 | Worker exceptions stored without traceback; exact-solver exceptions only logged at warning. | `main.py:130-132`; `quantum_engine.py:380-381` | **Fixed** for tasks (`logger.exception`); exact-solver path unchanged (returns `exact: null`). |
| D25 | Dev server bound to 0.0.0.0. | `main.py:159` | **Fixed**: 127.0.0.1. |
| D26 | `req.dict()` deprecated in pydantic v2. | `main.py:134` | **Fixed**: `model_dump()`. |
| D27 | Redundant sector constraints get slack qubits (4 of 9 qubits at default do nothing useful). | `quantum_engine.py:134-148` | **Open** R4. |
| D28 | Dead code: `worker.py`, `exact_classical` alias, unreachable branches. | see AUDIT_REPOSITORY.md §4 | **Open** (left in place). |

## API changes made by the fixes
Added: `qp_objective`, `qp_feasible` (all discrete solvers); `success`, `solver_message`, `duration_residual`,
`portfolio_objective`, `feasible`, `violations` (SLSQP); `p_optimal`, `uniform_p_optimal`, `p_feasible`,
`p_returned_solution`, `cost_function_evals`, `optimal_parameters` (QAOA); `qubo.constraint_penalty`,
`effective_*`, `rounded_durations`, `integer_grid_size`, `num_feasible_portfolios`; `sa_config`; `data`.
Removed: `quantum.qubo_fval`. Changed: unknown task → 404; invalid request → 422; `qaoa_config.backend/init`
strings. The dashboard was updated to match.

## Open recommendations

| ID | Recommendation |
|---|---|
| R1 | Encode CET1/LCR as one-sided hard constraints (integer-scaled coefficients plus slack, ≈ 8 qubits each at R = 2) when they must match SLSQP's semantics, or rename them "targets". |
| R2 | Source and cite the metadata (CET1, LCR, durations) or label them illustrative in the UI. |
| R3 | Replace the duration equality on rounded durations with a band (two inequalities), or default to settings with several feasible portfolios, so the optimisation objective matters. |
| R4 | Skip constraints whose maximal LHS ≤ rhs (no slack qubits). Default: 9 → 6 qubits; R = 4: 18 → 12. |
| R5 | If QAOA is to be compared with classical heuristics, use equal sample budgets, report approximation ratio and time-to-solution distributions over many instances, and use sizes where exhaustive search is not trivial. |
| R6 | Use a persistent task store / job queue (the existing `worker.py` taskiq scaffold) for anything beyond a single local process. |
| R7 | Put the whole repository under version control. **Done by the owner during the audit** (root commit `095d9b5`). |
| R8 | Study QAOA sensitivity to p, α, COBYLA's initial step, and Δt before drawing conclusions from QAOA results. |
