# Audit — Phase 6: Testing and reproducibility

## 1. Reproducibility of the project as found

* **No tests, no README, no setup instructions, no lock file** existed. `backend/requirements.txt` held 11
  unpinned package names.
* **Clean install on 2026-10-12** (fresh venv, CPython 3.11.5, Windows 11):
  1. The first `pip install -r requirements.txt` failed: `error: failed-wheel-build-for-install … docplex`
     (docplex is a transitive dependency of qiskit-optimization). Installing `docplex` on its own then worked, and
     a second full install succeeded. I did not determine the root cause; it was observed once.
  2. The install resolves qiskit 2.5.2, qiskit-aer 0.17.2, qiskit-algorithms 0.4.0, qiskit-optimization 0.7.0,
     numpy 2.4.6, pandas 3.0.6. Imports succeed, but every optimisation fails inside QAOA with
     `TypeError: Invalid circuits, expected Sequence[QuantumCircuit]` (defect D1).
* **The author's environment** (`backend/.venv`, CPython 3.13.5, qiskit 1.2.4, qiskit-algorithms 0.3.1, …) runs the
  original code. All "original" numbers in this audit come from that environment, used read-only (nothing was
  installed into it).
* Market data was fetched live on every request, so results could not be reproduced exactly even in that
  environment.

## 2. What was added

### Test suite (`backend/tests/`, 41 test functions → 50 test cases)

| Level | Tests (file :: name) | What they establish |
|---|---|---|
| Unit — maths | `test_market_model::test_moments_match_independent_numpy`, `…test_factor_model_*` (3) | μ, Σ against NumPy; factor model against an SVD re-derivation; k = n factors reconstruct Σ exactly; PD and variance preservation. |
| Unit — hand-calculated reference | `test_metrics_and_classical::test_metrics_hand_calculated`, `…test_backtest_hand_calculated` | Two-asset portfolio (return 0.15, variance 0.0375, …) and a 3-day backtest computed by hand. |
| Unit — formulation | `test_formulation::test_objective_matches_reference_on_whole_grid`, `…binding_basel_minimum…`, `…qiskit_sums_symmetric…`, `…feasible_count_matches_hand_enumeration`, `…floor_slices…` | QP objective = formula at every integer point; penalty term exactly λ((c·w−m)²−m²); Qiskit's (i,j)+(j,i) semantics; feasible set. |
| Quantum invariants | `test_formulation::test_qubo_and_ising_match_reference_for_every_bitstring`; `test_qaoa::test_ansatz_matches_independent_statevector`, `…is_unitary_and_trivial_at_zero_angles`, `…cost_operator_is_cleaned_and_normalised` | QUBO energy = objective + P·residual² for all 512 bitstrings; independent decoding = converter decoding; Ising diagonal (+offset) = QUBO energy (little-endian); Hamiltonian diagonal and Hermitian; QAOA state = NumPy simulation; normalisation; U U† = I; γ = β = 0 gives uniform. |
| Property-based (Hypothesis, 25 random instances) | `test_formulation::test_property_random_instances` | For random μ, Σ, durations, sectors, R ∈ {1,2,3}, q ∈ [0,1]: Ising diagonal = QUBO energies, and the QUBO argmin is the best feasible point (penalty sufficiency). |
| Integration | `test_qaoa::test_exact_solver_matches_brute_force`, `…discrete_results_are_consistent`; `test_api::test_optimize_round_trip`, `…failures_are_reported` | Full discrete pipeline (Exact/SA/QAOA) and full HTTP round trip (validation → background task → payload) on synthetic data. |
| Regression (one per fixed defect) | D2 `test_vacuous_basel_minimum_adds_no_penalty`; D3 `test_linear_ramp_binds_to_the_right_parameters`, `test_linear_ramp_anneals_towards_the_minimum`; D4 `test_slsqp_failure_is_reported_not_replaced`; D5 `test_metrics_reports_asset_cap_violation`, `test_asset_cap_clamp_is_visible`; D10 `test_cost_operator_is_cleaned_and_normalised`; D11 `test_duration_target_is_rounded_on_slice_scale`; D12 `test_fetch_does_not_backfill_future_prices`; D15 `test_metrics_align_metadata_by_label_not_position`; D16 `test_invalid_requests_are_rejected` (7 cases), `test_qubit_guard`; D18 `test_fetch_raises_on_empty_download`; D21 `test_unknown_task_is_404`; D22 `test_cors_only_allows_configured_origins` | Each fails if its defect is re-introduced (see §3). |
| Numerical reference vs independent solver | `test_metrics_and_classical::test_slsqp_matches_independent_solver` | SLSQP ≤ trust-constr objective + 1e-7, duration residual < 1e-6, weights within 1e-3. |
| Edge cases | budget violation, empty weights, each constraint violation (4 parametrised), infeasible duration target, single/duplicate tickers, reversed dates, out-of-range parameters, empty downloads, late-starting tickers, all-factor model (D clipped to its floor) | |
| Reproducibility | `test_qaoa::test_same_seed_is_reproducible` | Same seed → identical Exact/SA/QAOA weights, optimised parameters and P(optimum). |
| Performance (`@pytest.mark.slow`) | `test_performance::test_default_request_runs_within_budget` | Default 9-qubit discrete solve: exact < 5 s, SA < 5 s, total < 120 s (≈ 7–10 s here). |

All tests are offline. Market data is a seeded synthetic random walk (`conftest.make_prices`); the API test
replaces `fetch_universe_data`. Reference values come from hand calculation or `tests/reference.py` (NumPy only),
never from the function under test.

### Executable numerical audit (`audit/`)
`verify_numerics.py` (69 checks, AUDIT_NUMERICS.md), `qaoa_study.py` + `analyze_qaoa_study.py` (repeated
trials), `run_pipeline_snapshot.py` (offline pipeline on the frozen data, original or current code).

## 3. Do the regression tests actually detect the defects?

Mutation check (`mutate.py`, run in a scratch copy of `backend/`): each defect was re-introduced on its own and
its regression test re-run.

| Mutant | Result |
|---|---|
| M1 interleaved QAOA initial point | killed |
| M2 Basel penalty added when min = 0 | killed |
| M3 duration rhs `int(round(T))·R` | killed |
| M4 per-asset cap check removed | killed |
| M5 SLSQP failure hidden (`success` forced true) | killed |
| M6 `bfill()` look-ahead | killed |
| M7 positional metadata alignment | survived at first: the test used symmetric 50/50 weights, which hide misalignment. Strengthened to asymmetric weights → killed |

## 4. Test runs (actually executed)

| Environment | Command | Result |
|---|---|---|
| Audit env: CPython 3.11.5, requirements as pinned | `cd backend && python -m pytest` | **50 passed**, 0 failed, 0 skipped, 11 warnings, ≈ 20 s (≈ 76 s while other jobs ran) |
| Same | `python -m pytest -m "not slow"` | **49 passed**, 1 deselected, 20 s |
| **Clean** venv, CPython 3.11.5 (Anaconda base), `pip install --no-cache-dir -r requirements-dev.txt` | `python -m pytest` | **50 passed** in 32.9 s; `pip check`: no broken requirements; installed versions equal the pins |
| **Clean** venv, CPython 3.13.5 (author's interpreter, new venv) | same | **50 passed** in 36.2 s; `pip check` clean. Lock differs only by networkx 3.7 (3.6.1 on 3.11) and setuptools. |
| Frontend (Node 22.19.0) | `npx tsc --noEmit -p .`; `npm run lint`; `npm run build` | 0 type errors; 0 lint findings; production build succeeded on Next 16.2.4 and again after the upgrade to 16.4.0 (Turbopack). |
| Browser (Chrome + Claude extension) | dev servers on :8000/:3000, click Run | Browser check (2026-10-12, Chrome via the Claude extension, 1568×760 window, live data): page loads with every request 200; Run completes (POST `/api/optimize` 200, task polls 200); all four cards, the "Feasible 1" chip, real status messages, "P(optimum) 7.1 % vs 3.1 % random" and the backtest render without clipping. Fixed during the check: stale "dimod" label on the SA card, "Continuous relaxation" wording on the SLSQP card, and 10 Recharts `width(-1)` console warnings (pre-existing; `initialDimension` set). After the fixes the console shows no errors or warnings. A follow-up headless-Chrome run (Playwright) at 390 px width found the header stat chips overflowing horizontally; the header now stacks on small screens and the re-run shows no horizontal overflow, no clipped cards and no console errors. Not checked: accessibility. |
| Live end-to-end (Yahoo Finance, 2026-10-12) | `uvicorn main:app --port 8765`, POST default request, poll | COMPLETED in 10.9 s; weights identical to the snapshot run; 249 backtest rows; unknown task → 404; invalid request → 422. |

The 11 warnings all come from third-party code: Qiskit's `NLocal`/`BlueprintCircuit` deprecations (raised inside
`QAOAAnsatz`), SciPy `SparseEfficiencyWarning` (inside Qiskit's `Operator`), and Starlette's TestClient/httpx
notice. None comes from project code. A clean-install attempt on Python 3.13 failed once at `pip install --upgrade
pip` (`WinError 32`, a file lock on pip's own temporary wheel, i.e. environment, not project); the rerun without
the pip self-upgrade succeeded.

## 5. Reproducible instructions

See the root `README.md`. The commands there were executed as written in clean environments (§4). In short:

```
cd backend
python -m venv .venv
.venv\Scripts\activate            # PowerShell; on bash: source .venv/Scripts/activate (Windows) or .venv/bin/activate
python -m pip install -r requirements-dev.txt     # or requirements-lock.txt for the exact transitive set
python -m pytest
```

## 6. Limitations

* No frontend unit/component tests. Browser checks at desktop and 390 px width (§4); accessibility unchecked.
* The live Yahoo path is covered by a manual smoke test, not by the automated suite (which is deliberately
  offline).
* Property-based tests cover ≤ 3 assets and R ≤ 3 (≤ 10 qubits) to keep runtime low.
* QAOA tests use reduced iterations/shots (p = 2, 15 iterations, 256 shots). Algorithm quality is assessed by the
  audit study, not by unit tests.
* The performance test uses a generous ceiling to avoid flakiness; it detects order-of-magnitude regressions only.
* Tested on Windows 11 only.
