# Audit — Phase 3: Independent numerical verification

## 1. Method

Every number the API returns for the dashboard's default request was recomputed by a path that does not call the
function under test:

* **Reference implementations** (`audit/verify_numerics.py`, `backend/tests/reference.py`): NumPy only. Moments from
  raw prices; factor model by SVD (the code uses `eigh`); QP objective by formula; QUBO energies from an
  independent bounded-coefficient decoding plus explicit penalty residuals; Ising energies from the operator's
  diagonal; a NumPy statevector simulation of the QAOA circuit; CVaR by quantile integration; a uniform-sampling
  null model (analytic and Monte Carlo); SLSQP optimality via SciPy `trust-constr` (a different algorithm) plus
  a KKT residual I compute myself.
* **Inputs.** The in-sample (2020-01-02 → 2022-12-30, 756 rows) and out-of-sample (2023-01-03 → 2023-12-29, 250 rows)
  adjusted closes for AAPL, GS, JNJ, JPM, WMT were downloaded once from Yahoo Finance (yfinance 1.7.0) on
  2026-10-12 and frozen:
  `audit/data/prices_insample.csv` SHA-256 `bd91368a5961db0cbb0dfd245237147b079a18180c29f8e73fa6bfcb984211a2`,
  `audit/data/prices_oos.csv` SHA-256 `097ab0d668c8097675acc4f2fdaf051eee09e3c19442aee89960c6405327a23e`.
  Live downloads are not reproducible because adjusted prices are revised after each dividend.
  `audit/run_pipeline_snapshot.py` runs the real pipeline with only `fetch_universe_data` replaced by a CSV reader.
* **"Original reported value"** = output of the code as found (`audit/original_backend/`), run in the author's own
  environment (`backend/.venv`: Python 3.13.5, qiskit 1.2.4, qiskit-aer 0.16.0, qiskit-algorithms 0.3.1,
  qiskit-optimization 0.7.0, numpy 2.2.5). That is the only environment in which it runs (AUDIT_TESTING.md §1).
  File: `audit/results/original_pipeline_default.json`.
* **"Current"** = output of the audited code in a clean environment pinned by `backend/requirements.txt`
  (Python 3.11.5, qiskit 2.5.2, qiskit-aer 0.17.2, qiskit-optimization 0.7.0, numpy 2.4.6, scipy 1.17.1,
  dwave-samplers 1.8.0). File: `audit/results/current_pipeline_default.json`.
* Seeds: QAOA/Aer seed 42 (both versions); SA unseeded originally, seed 42 now; null-model Monte Carlo seed 12345;
  CVaR check seed 7.
* Machine: Intel Core i7-9750H (6 cores), 15.9 GB RAM, Windows 11 Home 10.0.26200. No GPU used.

Commands (repository root, with the environment active):

```
python audit/run_pipeline_snapshot.py --code current  --out audit/results/current_pipeline_default.json
backend/.venv/Scripts/python audit/run_pipeline_snapshot.py --code original --out audit/results/original_pipeline_default.json
python audit/verify_numerics.py            # → audit/results/numerics.json, numerics_table.md
python audit/qaoa_study.py --configs C1,C2 --seeds 20 --out audit/results/qaoa_study_9q.jsonl
python audit/qaoa_study.py --configs C3 --seeds 10 --out audit/results/qaoa_study_18q.jsonl
python audit/analyze_qaoa_study.py audit/results/qaoa_study_9q.jsonl audit/results/qaoa_study_18q.jsonl
```

### Acceptance criteria
* Deterministic linear algebra on identical inputs: absolute ≤ 1e-12 (moments, objectives), ≤ 1e-10 for sums over
  512 energies with penalty ≈ 1.4 and coefficients up to 25 (round-off ≈ n·ε·|E|). Reported metrics: relative ≤ 1e-9.
* SLSQP: one-sided. f_SLSQP − f_ref ≤ 1e-7, primal residual ≤ 1e-6, KKT residual ≤ 1e-6. An interior-point
  reference stops slightly inside the feasible set, so SLSQP may legitimately be *lower* (see N20).
* Shot-based estimates: |p̂ − p| ≤ 4σ with σ = √(p(1−p)/N), N = 1024.
* Monte Carlo vs analytic: ≤ 5 standard errors.

## 2. Summary of findings

* **All numbers the code reports are arithmetically correct** for the problem it actually encodes. Every metric of
  every strategy reproduces to ≤ 4.3·10⁻¹⁶ relative error, in both the original and the current code.
* **The quantities being reported were partly not what was claimed.** The original SA "QUBO energy" of 4.2168 is
  98 % vacuous CET1/LCR penalty (N9, N17). The default problem has exactly one feasible portfolio (N10). QAOA's
  "0 % gap" is matched by uniform random sampling with probability 1 − 7.6·10⁻¹⁵ (N31). The original
  "linear-ramp" start anneals toward the *worst* solutions (N25.o).
* The original SLSQP solution is optimal for its own (sample-covariance) problem (N20.o, N21.o). Its silent-failure
  path (equal weights returned as if optimal) is reproduced in `audit/results/original_repro_slsqp_failure.json`.
* One FAIL remains by design: N25.o documents the original initial point.

### Original vs current, default request (frozen snapshot)

| Metric | Original | Current | Why it changed |
|---|---|---|---|
| SLSQP weights | AAPL .500, GS .433, WMT .067 | AAPL .500, GS .433, WMT .067 | — |
| SLSQP volatility | 0.3126 (sample Σ) | 0.3181 (factor Σ) | all solvers now use one risk model |
| SLSQP objective / feasible / success | not reported | −0.06527 / true / true | now reported |
| Exact = SA = QAOA weights | AAPL .5, GS .5 | AAPL .5, GS .5 | unique feasible point |
| Discrete objective | −0.064458 | −0.064458 | — |
| SA `qubo_energy` | 4.2168 | −0.0645 | vacuous Basel penalty removed |
| QUBO penalty P | 16.38 | 1.395 | auto-penalty scales with objective range |
| Qubits | 9 | 9 | — |
| QAOA P(optimum) at θ* | not reported (exact value at original θ* not recoverable) | 0.0784 (2.51× uniform) | now reported |
| Feasible portfolios | not reported | 1 | now reported |
| Backtest 2023, Exact/SA/QAOA | +34.61 % | +34.61 % | — |
| Time: SLSQP / Exact / SA / QAOA (total) | 0.034 / 0.041 / 5.13 / 8.11 s (14.1 s) | 0.016 / 0.021 / 0.031 / 2.60 s (3.6 s) | compiled SA; statevector instead of MPS; different Python/library versions |

## 3. Results table

Generated by `audit/verify_numerics.py` (also `audit/results/numerics.json`). "Reported" is the code's value. For
checks of an internal quantity the column holds the maximal deviation and "verified" holds 0.

| ID | Claim / metric | Reported | Independently verified | Abs. err | Rel. err | Acceptance | Method | Status | Notes |
|---|---|---|---|---|---|---|---|---|---|
| N1 | Annualised mean returns μ (max |Δμ_i|) | 0 | 0 | 0 | — | abs ≤ 1e-12 | NumPy mean of P_t/P_{t-1}−1, ×252 | **PASS** | μ = AAPL 0.2580, GS 0.2205, JNJ 0.1133, JPM 0.0850, WMT 0.1077 |
| N2 | Annualised sample covariance Σ (max |ΔΣ_ij|) | 0 | 0 | 0 | — | abs ≤ 1e-12 | np.cov(ddof=1)×252 | **PASS** |  |
| N3 | 3-factor PCA covariance BFBᵀ+diag(D) (max |Δ|) | 1.66533e-16 | 0 | 1.66533e-16 | — | abs ≤ 1e-12 | SVD of standardised returns (code: eigh of correlation) | **PASS** |  |
| N4 | diag(Σ_factor) = diag(Σ_sample) (max |Δ|) | 0 | 0 | 0 | — | abs ≤ 1e-12 | construction property (D = diag Σ − diag BFBᵀ, unclipped here) | **PASS** |  |
| N5 | Factor-model approximation error ‖Σ_f−Σ‖_F/‖Σ‖_F | 0.0915953 | — | — | — | n/a | informational: how far the QUBO's risk model is from the sample covariance | **INFO** | max |Δcorrelation| = 0.179 |
| N6 | Σ_factor is positive definite (min eigenvalue) | 0.0101762 | — | — | — | n/a | np.linalg.eigvalsh | **PASS** |  |
| N7 | Current QP objective at every integer point (max |Δ|) | 8.32667e-17 | 0 | 8.32667e-17 | — | abs ≤ 1e-12 | q·wᵀΣ_f w−(1−q)μᵀw, w=x/R, all 32 points; no Basel penalty because min_cet1=min_lcr=0 | **PASS** |  |
| N8 | Original QP objective incl. its CET1/LCR term (max |Δ|) | 3.55271e-15 | 0 | 3.55271e-15 | — | abs ≤ 1e-12 | same formula + 10(c·w)² + 10(l·w)²: confirms the original penalty is active at min=0 | **PASS** | implemented as written; the formulation itself is the defect (AUDIT_SCIENCE §4.3) |
| N9 | Original vacuous Basel penalty on 50% GS (λ[(0.15·0.5)²+(1.30·0.5)²]) | 4.28125 | 4.28125 | 8.88178e-16 | 2.07458e-16 | abs ≤ 1e-12 | hand calculation | **PASS** | ≈ 65× |portfolio objective| (−0.0645) |
| N10 | Number of feasible portfolios (dashboard defaults) | 1 | 1 | 0 | 0 | abs ≤ 0 | hand enumeration of budget/duration/sector/bounds | **PASS** | feasible x = [{'AAPL': 1, 'GS': 1}] |
| N11 | Qubit count | 9 | 9 | 0 | 0 | abs ≤ 0 | Σ_vars bits(ub) + Σ_sector bits(slack ub), bits(U)=⌊log₂U⌋+1 | **PASS** | original also 9 |
| N12 | QUBO energy of all 512 bitstrings (max |Δ|) | 1.56319e-13 | 0 | 1.56319e-13 | — | abs ≤ 1e-10 | objective + P·Σ(constraint residual)², own bounded-coefficient decoding | **PASS** | P = 1.39529 (Qiskit auto penalty); decoding disagreements with converter.interpret: 0 |
| N13 | Penalty sufficiency: min E(violating) − min E(satisfying) | 1.39529 | — | — | — | n/a | must be > 0 so the QUBO ground state satisfies the hard constraints | **PASS** |  |
| N14 | Ising diagonal + offset vs QUBO energy, little-endian (max |Δ|) | 7.10543e-14 | 0 | 7.10543e-14 | — | abs ≤ 1e-10 | basis index k ↔ x_i = bit i of k | **PASS** | Hermitian (max |H−H†| coeff 0.0e+00); only I/Z Paulis: True |
| N15 | Exact optimum weights (Exact solver, original & current) | {'AAPL': 0.5, 'GS': 0.5} | {'AAPL': 0.5, 'GS': 0.5} | — | — | n/a | argmin over all 2^n QUBO energies (brute force) | **PASS** |  |
| N16.o.classical.exp | original: classical expected_return | 0.231747 | 0.231747 | 2.77556e-17 | 1.19767e-16 | rel ≤ 1e-09 | recomputed from reported weights with sample Σ | **PASS** |  |
| N16.o.classical.vol | original: classical volatility | 0.312644 | 0.312644 | 1.11022e-16 | 3.55108e-16 | rel ≤ 1e-09 | recomputed from reported weights with sample Σ | **PASS** |  |
| N16.o.classical.sha | original: classical sharpe_ratio | 0.741249 | 0.741249 | 1.11022e-16 | 1.49777e-16 | rel ≤ 1e-09 | recomputed from reported weights with sample Σ | **PASS** |  |
| N16.o.exact.exp | original: exact expected_return | 0.239268 | 0.239268 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.o.exact.vol | original: exact volatility | 0.332194 | 0.332194 | 5.55112e-17 | 1.67105e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.o.exact.sha | original: exact sharpe_ratio | 0.720266 | 0.720266 | 1.11022e-16 | 1.54141e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.o.exact.por | original: exact portfolio_objective | -0.0644576 | -0.0644576 | 2.77556e-17 | 4.30602e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.o.sa.exp | original: sa expected_return | 0.239268 | 0.239268 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.o.sa.vol | original: sa volatility | 0.332194 | 0.332194 | 5.55112e-17 | 1.67105e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.o.sa.sha | original: sa sharpe_ratio | 0.720266 | 0.720266 | 1.11022e-16 | 1.54141e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.o.sa.por | original: sa portfolio_objective | -0.0644576 | -0.0644576 | 2.77556e-17 | 4.30602e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.o.quantum.exp | original: quantum expected_return | 0.239268 | 0.239268 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.o.quantum.vol | original: quantum volatility | 0.332194 | 0.332194 | 5.55112e-17 | 1.67105e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.o.quantum.sha | original: quantum sharpe_ratio | 0.720266 | 0.720266 | 1.11022e-16 | 1.54141e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.o.quantum.por | original: quantum portfolio_objective | -0.0644576 | -0.0644576 | 2.77556e-17 | 4.30602e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.classical.exp | current: classical expected_return | 0.231747 | 0.231747 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.classical.vol | current: classical volatility | 0.318138 | 0.318138 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.classical.sha | current: classical sharpe_ratio | 0.728448 | 0.728448 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.classical.por | current: classical portfolio_objective | -0.0652676 | -0.0652676 | 1.38778e-17 | 2.12629e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.exact.exp | current: exact expected_return | 0.239268 | 0.239268 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.exact.vol | current: exact volatility | 0.332194 | 0.332194 | 5.55112e-17 | 1.67105e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.exact.sha | current: exact sharpe_ratio | 0.720266 | 0.720266 | 2.22045e-16 | 3.08281e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.exact.por | current: exact portfolio_objective | -0.0644576 | -0.0644576 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.sa.exp | current: sa expected_return | 0.239268 | 0.239268 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.sa.vol | current: sa volatility | 0.332194 | 0.332194 | 5.55112e-17 | 1.67105e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.sa.sha | current: sa sharpe_ratio | 0.720266 | 0.720266 | 2.22045e-16 | 3.08281e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.sa.por | current: sa portfolio_objective | -0.0644576 | -0.0644576 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.quantum.exp | current: quantum expected_return | 0.239268 | 0.239268 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.quantum.vol | current: quantum volatility | 0.332194 | 0.332194 | 5.55112e-17 | 1.67105e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.quantum.sha | current: quantum sharpe_ratio | 0.720266 | 0.720266 | 2.22045e-16 | 3.08281e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N16.c.quantum.por | current: quantum portfolio_objective | -0.0644576 | -0.0644576 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N17 | original: SA qubo_energy at x=(AAPL,GS) | 4.21679 | 4.21679 | 1.07914e-12 | 2.55914e-13 | rel ≤ 1e-09 | objective + 10(c·w)² + 10(l·w)², feasible ⇒ zero constraint penalty | **PASS** | value is dominated by the vacuous Basel penalty (4.28 of 4.22) |
| N18 | original: QAOA qubo_fval | 4.21679 | 4.21679 | 8.88178e-16 | 2.10629e-16 | rel ≤ 1e-09 | same; note this is the QP objective (incl. soft penalty), not a QUBO energy | **PASS** |  |
| N19 | current: SA qubo_energy | -0.0644576 | -0.0644576 | 1.27676e-15 | 1.98077e-14 | rel ≤ 1e-09 | feasible ⇒ QUBO energy = objective | **PASS** |  |
| N20.o | original: SLSQP objective vs trust-constr (one-sided) | -0.0670003 | -0.0670003 | 4.72649e-08 | 7.05443e-07 | abs ≤ 1e-07 | scipy trust-constr (interior point), same constraints; accept f_SLSQP − f_ref ≤ 1e-7 and primal residual ≤ 1e-6 | **PASS** | f_SLSQP − f_ref = -4.7e-08; primal residual 2.7e-10; max |Δw| = 9.8e-06 |
| N21.o | original: SLSQP KKT stationarity residual (relative) | 3.4079e-16 | 0 | 3.4079e-16 | — | abs ≤ 1e-06 | ‖∇f + Σλ∇g_active‖/‖∇f‖ with λ_ineq ≥ 0 (lsq_linear) | **PASS** |  |
| N20.c | current: SLSQP objective vs trust-constr (one-sided) | -0.0652676 | -0.0652674 | 1.54043e-07 | 2.36019e-06 | abs ≤ 1e-07 | scipy trust-constr (interior point), same constraints; accept f_SLSQP − f_ref ≤ 1e-7 and primal residual ≤ 1e-6 | **PASS** | f_SLSQP − f_ref = -1.5e-07; primal residual 7.4e-10; max |Δw| = 1.4e-05 |
| N21.c | current: SLSQP KKT stationarity residual (relative) | 4.05033e-16 | 0 | 4.05033e-16 | — | abs ≤ 1e-06 | ‖∇f + Σλ∇g_active‖/‖∇f‖ with λ_ineq ≥ 0 (lsq_linear) | **PASS** |  |
| N22.o | original: backtest cumulative returns, all dates & strategies (max |Δ|) | 0 | 0 | 0 | — | abs ≤ 1e-12 | np.cumprod(1+R_oos·w)−1 (constant-mix) | **PASS** | 249 dates; final: {'SLSQP': '+0.3444 (buy-and-hold +0.3464)', 'Exact': '+0.3461 (buy-and-hold +0.3488)', 'SA': '+0.3461 (buy-and-hold +0.3488)', 'QAOA': '+0.3461 (buy-and-hold +0.3488)'} |
| N22.c | current: backtest cumulative returns, all dates & strategies (max |Δ|) | 0 | 0 | 0 | — | abs ≤ 1e-12 | np.cumprod(1+R_oos·w)−1 (constant-mix) | **PASS** | 249 dates; final: {'SLSQP': '+0.3444 (buy-and-hold +0.3464)', 'Exact': '+0.3461 (buy-and-hold +0.3488)', 'SA': '+0.3461 (buy-and-hold +0.3488)', 'QAOA': '+0.3461 (buy-and-hold +0.3488)'} |
| N23 | current: QAOA gap_to_optimal_pct | 0 | 0 | 0 | — | abs ≤ 1e-09 | (f(x)−f(x*))/|f(x*)| with identical x | **PASS** |  |
| N24 | Qiskit QAOA parameter order | β[0], β[1], β[2], γ[0], γ[1], γ[2] | β[0..p-1], γ[0..p-1] (block) | — | — | n/a | QAOAAnsatz(op, reps=3).parameters | **INFO** |  |
| N25.o | original: init is a TQA linear ramp (Sack & Serbyn Eq. 6) in Qiskit's convention | β=[0.5625, 0.1875, 0.375], γ=[0.375, 0.1875, 0.5625] | β≤0, |β|↓, γ↑, ⟨H⟩ < uniform | — | — | n/a | values as bound in Qiskit's block order; ⟨H⟩ by NumPy statevector | **FAIL** | raw H: ⟨H⟩ at init +9.908 vs uniform +0.000 |
| N25.c | current: init is a TQA linear ramp (Sack & Serbyn Eq. 6) in Qiskit's convention | β=[-0.5625, -0.375, -0.1875], γ=[0.1875, 0.375, 0.5625] | β≤0, |β|↓, γ↑, ⟨H⟩ < uniform | — | — | n/a | values as bound in Qiskit's block order; ⟨H⟩ by NumPy statevector | **PASS** | H/max|c| (max|c| = 25.1): ⟨H⟩ at init -1.468 vs uniform +0.000 |
| N26 | QAOA state probabilities: NumPy vs Qiskit Statevector (max |Δp|) | 4.92661e-16 | 0 | 4.92661e-16 | — | abs ≤ 1e-10 | independent NumPy simulation of e^{-iβΣX}e^{-iγH_C} layers | **PASS** | Σp = 0.999999999999999; ‖ψ‖ − 1 = 4.4e-16 |
| N27 | current: p_optimal from 1024 Aer shots vs exact |ψ|² at reported θ* | 0.0712891 | 0.0783818 | 0.0070927 | 0.0904892 | abs ≤ 0.0335964 | binomial: accept |Δ| ≤ 4σ, σ=√(p(1−p)/N) | **PASS** | σ = 0.0084, z = -0.84 |
| N28 | uniform_p_optimal (random guessing) | 0.03125 | 0.03125 | 0 | 0 | abs ≤ 1e-15 | 16 of 512 bitstrings decode to x* (slack bits are free) | **PASS** |  |
| N29.orig | P(x*) of the QAOA state at the original init | 0.0159305 | 0.03125 | 0.0153195 | 0.490224 | n/a | NumPy statevector; verified value column = uniform baseline | **INFO** |  |
| N29.curr | P(x*) of the QAOA state at the current (corrected) init | 0.0727851 | 0.03125 | 0.0415351 | 1.32912 | n/a | NumPy statevector; verified value column = uniform baseline | **INFO** |  |
| N30 | P(x*) of the QAOA state at optimised θ* (exact) | 0.0783818 | 0.03125 | 0.0471318 | 1.50822 | n/a | NumPy statevector; verified value column = uniform baseline | **INFO** | ratio to uniform = 2.51× |
| N31 | Null model: P(best-feasible-of-1024 uniform samples = x*) | 1 | 1 | 7.54952e-15 | 7.54952e-15 | abs ≤ 9.72437e-10 | Monte Carlo (200000 trials) vs 1−(1−u)^N | **PASS** | 1 − P = 7.60e-15: random sampling 'finds' x* essentially always |
| N32 | QAOA: P(x* appears in the final 1024-shot histogram) | 1 | 1 | 7.54952e-15 | 7.54952e-15 | n/a | 1−(1−p)^N with exact p at θ*; verified column = null model | **INFO** |  |
| N34 | CVaR_α aggregation (200 random discrete distributions, max |Δ|) | 4.9074e-06 | 0 | 4.9074e-06 | — | abs ≤ 0.0001 | (1/α)∫₀^α F⁻¹(u)du by midpoint rule (2·10⁵ nodes); Barkoutsos et al. 2020 definition | **PASS** | tolerance set by the quadrature, not by the library |
| N33 | Wall-clock: exhaustive NumPy evaluation of all 512 QUBO energies [s] | 0.0206482 | 0.000302465 | 0.0203458 | 67.2665 | n/a | vectorised einsum; reported column = Exact solver time, current run | **INFO** | QAOA: 2.60s for 53 evaluations × 1024 shots; SA 0.031s; original SA (dimod reference) 5.13s |

Status counts: 61 PASS, 7 INFO, 1 FAIL (N25.o — the original initial point, retained deliberately as evidence).

## 4. Stochastic behaviour of QAOA (repeated trials)

`audit/qaoa_study.py` runs the real `optimize_portfolio_qaoa` for many seeds (the seed changes only Aer's shot
sampling; COBYLA and the start point are deterministic). For each run it computes the exact probability that the
final QAOA state assigns to the optimum, using the independent NumPy simulator at the optimiser's final
parameters. The "original" arm reproduces the original initial point (interleaved order, positive β, no energy
scaling) inside the current pipeline, which isolates its effect. Configurations: C1 = dashboard default
(R=2, T=4.0); C2 = R=2, T=4.5 (2 feasible portfolios); C3 = R=4, T=4.0 (18 qubits, 5 feasible portfolios).
95 % intervals are Wilson score intervals.

| Config | Qubits | Feasible | Init | Trials | QAOA success [95% CI] | SA success [95% CI] | Null-model success | P(x*) at init | P(x*) at θ* (mean ± sd) | Uniform u | θ*/u | Evals (mean) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | 9 | 1 | current | 20 | 20/20 [0.84, 1.00] | 20/20 [0.84, 1.00] | 1.000000 | 0.0728 | 0.0814 ± 0.0085 | 0.0312 | 2.61 | 46.1 |
| C1 | 9 | 1 | original | 20 | 20/20 [0.84, 1.00] | 20/20 [0.84, 1.00] | 1.000000 | 0.0011 | 0.0587 ± 0.0291 | 0.0312 | 1.88 | 60.0 |
| C2 | 9 | 2 | current | 20 | 20/20 [0.84, 1.00] | 20/20 [0.84, 1.00] | 1.000000 | 0.0721 | 0.0781 ± 0.0034 | 0.0312 | 2.50 | 48.0 |
| C2 | 9 | 2 | original | 20 | 20/20 [0.84, 1.00] | 20/20 [0.84, 1.00] | 1.000000 | 0.0006 | 0.0689 ± 0.0448 | 0.0312 | 2.20 | 55.9 |
| C3 | 18 | 5 | current | 10 | 10/10 [0.72, 1.00] | 8/10 [0.49, 0.94] | 0.632300 | 0.0026 | 0.0033 ± 0.0003 | 0.0010 | 3.33 | 51.5 |
| C3 | 18 | 5 | original | 10 | 9/10 [0.60, 0.98] | 8/10 [0.49, 0.94] | 0.632300 | 0.0000 | 0.0022 ± 0.0015 | 0.0010 | 2.28 | 57.3 |

C1: paired P(x*) at θ*, current − original init over 20 seeds: mean +0.0228, median +0.0224, Wilcoxon p = 0.00365

C2: paired P(x*) at θ*, current − original init over 20 seeds: mean +0.0092, median +0.0205, Wilcoxon p = 0.0484

C3: paired P(x*) at θ*, current − original init over 10 seeds: mean +0.0010, median +0.0009, Wilcoxon p = 0.0645

QAOA wall-clock per run: median 2.78s (runs were concurrent with other jobs; use isolated pipeline runs for timing claims)

`audit/results/qaoa_study_9q_mps_superseded.jsonl` is an earlier run (MPS simulator, before the sign and scale
corrections of the initial point), kept for transparency and not used in these tables.

Interpretation:

* **At 9 qubits, success rates carry no information.** QAOA, SA and the null model (uniform sampling with the same
  shot budget and selection rule) all succeed with probability ≈ 1.
* **The informative metric is the probability mass on the optimum.** With the corrected start, QAOA's final state
  puts 2.5–3.3× the uniform probability on the optimum, with low seed-to-seed variance. The original start ends
  lower (1.9–2.3×) with 3–10× larger variance. The paired difference is significant for C1 (p = 0.004) and C2
  (p = 0.048) and not significant for C3 at 10 seeds (p = 0.065).
* **At 18 qubits sampling stops being trivial.** The null model succeeds 63 % of the time. QAOA's exact
  probability of observing the optimum in 1024 shots averages 0.96 (corrected) vs 0.78 (original start); observed
  successes 10/10 and 9/10. SA (200 reads) succeeded 8/10. Its two misses were feasible portfolios 14.2 % worse.
  QAOA 10/10 vs SA 8/10 is not significant (Fisher exact p = 0.47), and the budgets (1024 shots vs 200 reads) are
  not equivalent, so **no ranking between QAOA and SA is supported.**
* Concentration of 3× uniform at 18 qubits means P(optimum) ≈ 0.003 per shot. QAOA here is a sampler that is
  mildly biased toward good solutions, not a solver that prepares the optimum.

## 5. Timing (measured, not a benchmark)

Single isolated runs of the default request on the machine above:

| Component | Original (author env) | Current |
|---|---|---|
| SLSQP | 0.034 s | 0.016 s |
| Exact (Qiskit `NumPyMinimumEigensolver`, 9 qubits) | 0.041 s | 0.021 s |
| Exhaustive NumPy evaluation of all 512 QUBO energies (reference) | — | 0.0003 s |
| Simulated annealing (200 reads × 1000 sweeps) | 5.13 s (dimod pure-Python reference) | 0.031 s (dwave-samplers) |
| CVaR-QAOA, p=3, ≤80 COBYLA iterations × 1024 shots | 8.11 s (MPS) | 2.60 s (statevector, 53 evaluations) |
| Total incl. backtest | 14.1 s | 3.6 s |

Per-circuit simulation cost, same transpiled circuit and parameters (`mps_vs_sv` measurement):
9 qubits 0.061 s (MPS) vs 0.020 s (statevector); 18 qubits **18.2 s (MPS) vs 0.10 s (statevector)**.
One 18-qubit QAOA run took 2750 s with MPS (measured while other jobs ran, n = 1). With statevector the median
was 9.9 s over 20 runs (also concurrent).

Timings are not separated into compilation and execution beyond the above. Only total wall-clock per solver is
measured, and on one machine. They support exactly one conclusion: at every size this code accepts (≤ 24 qubits),
exhaustive classical enumeration is orders of magnitude faster than simulated QAOA. **No quantum advantage is
claimed or supported.**

## 6. What could not be verified

| Item | Reason |
|---|---|
| CET1 / LCR / duration values in `_METADATA_DB` | No sources in the repository; not checked against filings. |
| Correctness of Yahoo Finance prices | Only internal consistency was checked; no second data vendor. |
| Results on live data at other dates | Adjusted prices change; only the frozen snapshot is reproducible (a live run on 2026-10-12 gave identical weights). |
| Hardware or noisy-simulation behaviour | Not implemented in the project. |
| QAOA behaviour for n > 18, p ≠ 3, other α | Not studied. |
| Exact P(optimum) of the *original* run | The original code does not return its optimised parameters. |
| Frontend accessibility | Rendering was checked in Chrome at desktop and phone width (AUDIT_TESTING.md §4); accessibility was not. |
