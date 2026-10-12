# Audit — Phase 2: Scientific feasibility and mathematical verification

The formulation below is reconstructed from the code (`audit/original_backend/` as found, `backend/` after the
audit), not from comments. Every equation marked ✔ was checked numerically by an independent implementation
(check IDs refer to AUDIT_NUMERICS.md).

## 1. Problem being solved

**Data.** Daily dividend/split-adjusted closes P_{t,i} for n tickers (default AAPL, GS, JNJ, JPM, WMT; 2020-01-02 →
2022-12-30, 756 days). Simple returns r_{t,i} = P_{t,i}/P_{t−1,i} − 1.

**Moments** ✔ (N1, N2): μ = 252·mean(r) (per year), Σ = 252·cov(r, ddof=1) (per year²). Arithmetic annualisation,
no compounding, no shrinkage. With 755 observations and 5 assets the sample covariance is well conditioned.

**Risk model of the discrete solvers** ✔ (N3–N6): PCA on the *correlation* matrix, k = 3 factors:
Z = standardised returns, Corr = VΛVᵀ, B = diag(s)·V_k, F = 252·Λ_k, D_i = max(Σ_ii − (BFBᵀ)_ii, 10⁻⁶),
Σ_f = BFBᵀ + diag(D). Properties verified: symmetric positive definite (λ_min = 0.0102), diag(Σ_f) = diag(Σ)
exactly (no clipping occurred), equal to an SVD-based re-derivation to 1.7·10⁻¹⁶. With 5 assets a 3-factor model
discards real information: ‖Σ_f − Σ‖_F/‖Σ‖_F = 9.2 %, max correlation error 0.18 (N5). That is a modelling choice,
not an error, but it means the discrete solvers optimise a different risk model from the sample covariance, and
for 5 assets a factor model brings no computational benefit (the QUBO is dense either way).

**Stated (continuous) problem** — solved by SLSQP:

```
minimise_w   q·wᵀΣw − (1−q)·μᵀw                       q ∈ [0,1] (default 0.5)
subject to   Σ_i w_i = 1,   0 ≤ w_i ≤ a_max            (budget, long-only, per-asset cap)
             Σ_i d_i w_i = T                           (portfolio "duration", years)
             Σ_{i∈S} w_i ≤ s_max   for every sector S
             Σ_i c_i w_i ≥ m_c,  Σ_i ℓ_i w_i ≥ m_ℓ      (CET1, LCR; only if some ratio > 0)
```
Σ is PSD and q ≥ 0, so this is a convex QP; a KKT point is the global optimum. Units are consistent
(objective in "variance per year" ≈ return per year with q acting as a risk-aversion weight).

**Discrete problem** — solved by Exact, SA and QAOA. Integer slices x_i ∈ {0,…,U}, w = x/R (R = budget
resolution):

```
minimise_x   q·xᵀΣ_f x / R² − (1−q)·μᵀx / R  [+ λ((cᵀx/R − m_c)² − m_c²) if m_c > 0]  [+ same for LCR]
subject to   Σ x_i = R
             Σ round(d_i)·x_i = round(T·R)                         (original: round(T)·R)
             Σ_{i∈S} x_i ≤ max(1, ⌊s_max·R⌋)
             0 ≤ x_i ≤ U = max(1, ⌊a_max·R⌋)
```
✔ The QuadraticProgram objective equals this formula at all 32 integer points to 8·10⁻¹⁷ (N7). The code passes
both (i,j) and (j,i) quadratic entries; Qiskit sums them (verified, `test_qiskit_sums_symmetric_quadratic_entries`),
so xᵀΣx is encoded correctly, not doubled or halved.

**QUBO / Ising** ✔ (N11–N14). Each integer is binary-encoded with bounded coefficients 1, 2, …, 2^{k−1},
U − (2^k − 1); each `≤` constraint gets an integer slack s ∈ {0,…,rhs} encoded the same way; then

  E(b) = f(x(b)) + P·Σ_constraints (a·x(b) [+ s(b)] − rhs)²,   P = Qiskit's automatic penalty.

The mapping b_i = (1 − Z_i)/2 gives a diagonal Hermitian H_C (only I/Z Paulis) with ⟨b|H_C|b⟩ + offset = E(b) for
every one of the 512 bitstrings (max error 7·10⁻¹⁴), qubit i ↔ binary variable i, basis index little-endian.
Penalty sufficiency (the QUBO minimum satisfies all hard constraints) holds with margin P = 1.395 (N13).

**QAOA** ✔ (N26): |ψ(β,γ)⟩ = Π_{l=1}^{p} e^{−iβ_l ΣX} e^{−iγ_l H_C} |+⟩^{⊗n}, p = 3. Matches an independent
NumPy simulation to 5·10⁻¹⁶ in probability; normalised; unitary (test). The parameters are optimised by COBYLA
(≤ 80 iterations) on the CVaR_α objective (α = 0.25) ✔ (N34): (1/α)∫₀^α F⁻¹(u) du of the sampled energy
distribution, as defined by Barkoutsos et al. (2020). The returned solution is chosen by Qiskit's
`MinimumEigenOptimizer`: **the best feasible bitstring among all 1024 shots of the final circuit.**

## 2. Claims and verdicts

| # | Claim (where) | Verdict | Evidence |
|---|---|---|---|
| C1 | Exact = "ground-truth optimum" | **Valid for the discrete QUBO** (exhaustive). It is not the optimum of the stated continuous problem. | N13, N15 |
| C2 | All solvers solve "the same constrained problem" (`quant_engine.py` docstring) | **False as found.** SLSQP used the sample Σ, the others the factor Σ; SLSQP uses exact durations, an exact duration equality and hard CET1/LCR ≥; the discrete problem rounds durations, floors caps and uses a soft, two-sided CET1/LCR penalty. Σ now aligned (factor model for all four); the rest is inherent to discretisation and is now reported (`qubo.effective_*`). | §3 |
| C3 | "Basel III" constraints; "real CET1/LCR from FY24 filings" | **Not regulation.** CET1 and LCR are bank-level prudential ratios. Basel III imposes no floor on an investor's *portfolio-weighted average* of investee banks' ratios. The constraint is a stylised device. The numbers are hand-entered and not traced to filings (not verified). | §4.1 |
| C4 | CET1/LCR soft penalty "(zero slack qubits, per Barkoutsos 2020)" | **Misattributed.** Barkoutsos et al. (2020) introduce CVaR aggregation, not penalty encodings. Quadratic penalties are the standard method (Lucas 2014; Glover, Kochenberger & Du 2019). | references |
| C5 | Soft penalty "biases toward Basel-compliant allocations" | **False at the default.** With m = 0 the term λ(c·w)² + λ(ℓ·w)² is added anyway and penalises *every* bank holding (4.28 on a 50 % GS position, 65× the whole objective). The constraint is vacuous because ratios are ≥ 0. Fixed. For m > 0 the penalty is two-sided (also penalises over-compliance): documented. | N8, N9, §4.3 |
| C6 | "Linear-ramp init (Sack & Serbyn 2021)" | **False as found**, for three independent reasons: (a) values interleaved [β₀,γ₀,β₁,…] while Qiskit orders [β₀..β_{p−1}, γ₀..γ_{p−1}], so the bound values are not ramps; (b) sign convention: the paper's mixer is −ΣX, Qiskit's is +ΣX, so positive β anneals to the *maximum* of H_C; (c) Δt ≈ 0.75 is calibrated for unit-coupling MaxCut while max|coeff| of H_C here is 25 (9 qubits) to 50 (18 qubits). All three fixed. | N24, N25, N29, §5.2 |
| C7 | Linear ramp "avoids the barren-plateau issue" | **Unsupported.** Sack & Serbyn address convergence to sub-optimal *local minima*, and explicitly distinguish this from barren plateaus (McClean et al. 2018: exponentially vanishing gradients of random, deep circuits). Barren plateaus are not studied or relevant at n = 9, p = 3. Claim removed. | paper p. 1 |
| C8 | CVaR-QAOA (Barkoutsos 2020) | **Correctly implemented** (library aggregation verified independently). | N34 |
| C9 | "qiskit-aer MPS backend" | **Valid but a poor choice.** MPS without truncation is exact, but all-to-all ZZ layers are its worst case: 18.2 s vs 0.10 s per circuit at 18 qubits. Switched to statevector (also exact). | NUMERICS §5 |
| C10 | SA is "the fair head-to-head opponent for QAOA" | **Not as implemented.** dimod's `SimulatedAnnealingSampler` is a pure-Python reference that its own docstring says is "not an appropriate sampler for benchmarking". It was unseeded (5.1 s for 9 variables). Replaced with dwave-samplers (compiled, seeded): 0.03 s. | NUMERICS §5 |
| C11 | QAOA "finds the optimum" (gap 0 %) | **True but uninformative.** At ≤ 9 qubits, a uniform random sampler with the same selection rule finds the optimum with probability 1 − 7.6·10⁻¹⁵. | N31, §5.3 |
| C12 | Implied quantum advantage / "Literature-Validated" | **No advantage is established, and none is possible at these sizes.** Exhaustive classical evaluation of all 512 QUBO energies takes 0.35 ms; QAOA (noiseless simulation) takes 2.6 s. QAOA is a simulated heuristic here, not a speed-up. | N33 |
| C13 | Sharpe ratio | Reported with a zero risk-free rate (now documented). | — |
| C14 | "Out-of-sample backtest" | Correct arithmetic for a **daily-rebalanced (constant-mix)** portfolio without costs; that convention was undocumented. Buy-and-hold differs by ≤ 0.3 pp over 2023. | N22 |

## 3. Discretisation: the discrete problem is not the stated problem

The default dashboard request (R = 2, T = 4.0, s_max = 0.60, a_max = 0.50) gives:

* effective per-asset cap 0.50 (= stated); effective sector cap **0.50** (stated 0.60);
* durations rounded to whole years (AAPL 5.2→5, GS 2.6→3, JNJ 7.2→7, JPM 2.1→2, WMT 4.1→4);
* **exactly one feasible portfolio: {AAPL 50 %, GS 50 %}** (N10).

So the risk–return objective has no influence on the Exact, SA or QAOA answer at the default settings; the solvers
only have to find the single bitstring that satisfies the constraints. Across 84 configurations (R ∈ {2,3,4},
T ∈ {3.0,…,6.0}, s_max, a_max ∈ {0.6/0.5, 1.0}) the number of feasible portfolios never exceeded 7, even at 27
qubits (≈1.3·10⁸ basis states). This is because an *equality* on integer-rounded durations is a very sparse
constraint. The problem is dominated by constraint satisfaction, not optimisation. The API now reports
`num_feasible_portfolios` and the effective caps/target so this is visible. A duration *band* (two inequalities)
would make the objective matter, at the cost of slack qubits. That is a modelling decision for the owner
(recommendation R3 in AUDIT_CORRECTNESS.md).

Other discretisation effects, now reported instead of hidden:
* `max(1, ⌊a·R⌋)` **loosens** the cap when a·R < 1 (e.g. a = 0.25, R = 2 → 50 % positions). The original
  `_metrics` removed the per-asset check, arguing that floor rounding would cause false positives. That reasoning is wrong:
  flooring can only *tighten* a cap, and only the clamp loosens it. The original reported such portfolios as
  "feasible". Reproduced: `audit/results/original_repro_asset_cap.json`.
* `int(round(T))·R` lost resolution and used round-half-to-even (T = 4.5 → 4.0). Now `round_half_up(T·R)` (4.5 → 9/2).
* `int(x·R)` is vulnerable to float products (0.29·100 → 28); now ⌊x·R + 10⁻⁹⌋. No slider value was affected.
* Duration feasibility is reported with a ±25 % tolerance because exact equality on unrounded durations is
  generally unattainable on the grid. The tolerance is a reporting convention, now a named constant.

## 4. Domain-model assumptions

### 4.1 CET1 and LCR
Basel III's CET1 ratio (CET1 capital / risk-weighted assets) and LCR (HQLA / 30-day net outflows) are requirements
on a *bank's own* balance sheet. A weighted average of investee banks' ratios has no regulatory meaning for an
investor, and non-banks are assigned 0, which makes the "constraint" a minimum-bank-allocation rule. It is
legitimate as a stylised side-constraint in a demo, but must not be presented as Basel III compliance. The values
in `_METADATA_DB` are not sourced; I did not verify them against filings.

### 4.2 Equity "duration"
Duration is a fixed-income concept. Equity duration estimates exist in the literature, but the values here
(AAPL 5.2, TSLA 8.5, …) are unsourced constants. Treat them as arbitrary linear side-constraint coefficients.

### 4.3 The CET1/LCR penalty
Inequality c·w ≥ m cannot be expressed by a single quadratic penalty without slack variables. λ(c·w − m)²
is minimised at c·w = m and penalises exceeding the minimum as much as falling short. Two corrections are
possible:
* **Applied:** omit the term when m ≤ 0. The constraint is then vacuous because c ≥ 0, so adding the term only
  distorts the objective. This is unambiguous and restores consistency with SLSQP at the default.
* **Recommended, not applied** (changes qubit counts and the problem the UI presents): encode c·x ≥ ⌈m·R⌉ as a
  hard constraint with integer-scaled coefficients (CET1 in 0.1 %, LCR in %). By my estimate this adds ≈ 8 slack
  qubits per ratio at R = 2 (≈ 25 qubits total), which matches SLSQP's semantics exactly.

## 5. Quantum-specific verification

### 5.1 Hilbert space and encoding
n = 9 qubits at the default: 5 decision bits plus 4 sector-slack bits. Three of the four sector constraints are
**redundant**: a single-asset sector with U ≤ cap can never violate its cap. Their slack qubits enlarge the
Hilbert space 8× without changing the feasible set. Dropping constraints whose maximal LHS ≤ rhs would give 6 qubits
at the default and 12 instead of 18 at R = 4 (derived by hand; recommendation R4). Endianness, Hermiticity,
diagonality and the QUBO↔Ising energy identity are verified for every basis state (N14), and for random small
instances by a property-based test.

### 5.2 Initial point (TQA)
Sack & Serbyn (2021, Eq. 6): γ_i = (i/p)Δt, β_i = (1 − i/p)Δt, with mixer H_B = −ΣX whose ground state
|+⟩^{⊗n} is the initial state; Δt ≈ 0.75 for unweighted 3-regular MaxCut (their Fig. 3). Qiskit's `QAOAAnsatz`
applies e^{−iβΣX}, i.e. H_B = +ΣX, for which |+⟩^{⊗n} is the highest state. Because the initial state and
H_C are real, Qiskit's (β, γ) gives the same probabilities as the paper's (β, −γ). The original positive
angles therefore anneal toward the **maximum** of H_C. Measured on the default problem: as the original code ran it
(raw H_C), the original start has ⟨H_C⟩ = +9.9 against 0 for the uniform state and 0.51× the uniform probability on
the optimum (N25.o, N29.orig). The same angles applied to the normalised H_C give 0.03× (study, AUDIT_NUMERICS §4). The
corrected start (block order, β ≤ 0, H_C/max|c|) has ⟨H_C⟩ = −1.47 (normalised units) and 2.33× uniform on the
optimum (N25.c, N29.curr). The corrected code uses s_i = (i+1)/(p+1) instead of i/p (so the last mixer layer is not zero).
That variant is documented in the code.

### 5.3 What QAOA's reported success means
`MinimumEigenOptimizer` returns the best *feasible* sample of the final histogram. At the default, 16 of 512 basis
states decode to the optimum (the 4 slack bits are free), so u = 1/32. With 1024 shots:

* a uniform random sampler succeeds with probability 1 − (1 − 1/32)^1024 = 1 − 7.6·10⁻¹⁵ (N31);
* QAOA after the fixes puts 2.5–2.6× u on the optimum (N30; study in AUDIT_NUMERICS.md §4).

Both "succeed" 20/20 in repeated trials. Success at this size is evidence that **sampling** works, not that QAOA
works. The honest metric is the probability mass on the optimum (now returned as `p_optimal`, alongside
`uniform_p_optimal`). At 18 qubits (R = 4, 5 feasible portfolios) the null model succeeds only 63 % of the time.
That is the regime where QAOA's concentration becomes distinguishable; see the 18-qubit study.

### 5.4 Noise, hardware, scalability
* Everything is **ideal, noiseless simulation**. No noise model, no hardware execution, no transpilation to a
  real device's connectivity. Nothing here supports a claim about NISQ hardware performance.
* Shot noise is the only stochasticity in QAOA. The 1024-shot estimate of P(optimum) agrees with the exact value
  (z = −0.84, N27).
* Resource scaling: n = Σ_i(⌊log₂U⌋+1) + Σ_sectors(⌊log₂cap⌋+1); each layer has O(n²) dense RZZ terms
  (109 transpiled operations at 9 qubits, 352 at 18). Classical simulation cost is 2^n. The code refuses > 24 qubits.
* Barren plateaus and initialisation sensitivity at larger n, p were **not** studied.

## 6. Distinctions the project must make explicit

| | Status |
|---|---|
| Mathematically valid vs experimentally demonstrated | The QUBO/Ising/QAOA construction is mathematically valid (verified). Optimisation quality is demonstrated only on 9–18-qubit noiseless simulations of one data snapshot. |
| Ideal simulation vs noisy simulation vs hardware | Ideal simulation only. |
| Quantum implementation vs quantum-inspired classical method | QAOA is a genuine quantum circuit, executed by a classical simulator. SA and Exact are classical. |
| Valid algorithm vs practical advantage | Valid algorithm; no advantage, and none is expected at ≤ 24 qubits. |
| Asymptotic complexity vs wall-clock | No asymptotic claim is made or supported. Wall-clock: exhaustive 0.35 ms < SA 30 ms < Exact (Qiskit) 22 ms < QAOA 2.6 s at 9 qubits. |

## 7. References (verified against arXiv / journal pages on 2026-10-12)

* Barkoutsos, Nannicini, Robert, Tavernelli, Woerner. *Improving Variational Quantum Optimization using CVaR.*
  Quantum 4, 256 (2020). arXiv:1907.04769.
* Sack, Serbyn. *Quantum annealing initialization of the quantum approximate optimization algorithm.*
  Quantum 5, 491 (2021). arXiv:2101.05742 (Eq. 6; Fig. 3 for Δt ≈ 0.75; §1 on local minima vs barren plateaus).
* Farhi, Goldstone, Gutmann. *A Quantum Approximate Optimization Algorithm.* arXiv:1411.4028 (2014).
* Lucas. *Ising formulations of many NP problems.* Frontiers in Physics 2, 5 (2014). arXiv:1302.5843.
* Glover, Kochenberger, Du. *A Tutorial on Formulating and Using QUBO Models.* arXiv:1811.11538 (2019).
* McClean, Boixo, Smelyanskiy, Babbush, Neven. *Barren plateaus in quantum neural network training landscapes.*
  Nature Communications 9, 4812 (2018). arXiv:1803.11173.
