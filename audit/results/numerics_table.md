| ID | Claim / metric | Reported | Independently verified | Abs. err | Rel. err | Acceptance | Method | Status | Notes |
|---|---|---|---|---|---|---|---|---|---|
| N1 | Annualised mean returns μ (max |Δμ_i|) | 0 | 0 | 0 | — | abs ≤ 1e-12 | NumPy mean of P_t/P_{t-1}−1, ×252 | **PASS** | μ = AAPL 0.2580, GS 0.2205, JNJ 0.1133, JPM 0.0850, WMT 0.1077 |
| N2 | Annualised sample covariance Σ (max |ΔΣ_ij|) | 0 | 0 | 0 | — | abs ≤ 1e-12 | np.cov(ddof=1)×252 | **PASS** |  |
| N3 | 3-factor PCA covariance BFBᵀ+diag(D) (max |Δ|) | 1.66533e-16 | 0 | 1.66533e-16 | — | abs ≤ 1e-12 | SVD of standardised returns (code: eigh of correlation) | **PASS** |  |
| N4 | diag(Σ_factor) = diag(Σ_sample) (max |Δ|) | 0 | 0 | 0 | — | abs ≤ 1e-12 | construction property (D = diag Σ − diag BFBᵀ, unclipped here) | **PASS** |  |
| N5 | Factor-model approximation error ‖Σ_f−Σ‖_F/‖Σ‖_F | 0.0915953 | — | — | — | n/a | informational: how far the QUBO's risk model is from the sample covariance | **INFO** | max |Δcorrelation| = 0.179 |
| N6 | Σ_factor is positive definite (min eigenvalue) | 0.0101762 | — | — | — | n/a | np.linalg.eigvalsh | **PASS** |  |
| N7 | QP objective at every integer point (max |Δ|) | 8.32667e-17 | 0 | 8.32667e-17 | — | abs ≤ 1e-12 | q·wᵀΣ_f w−(1−q)μᵀw, w=x/R, all 32 points; no Basel penalty because min_cet1=min_lcr=0 | **PASS** |  |
| N8 | Number of feasible portfolios (dashboard defaults) | 1 | 1 | 0 | 0 | abs ≤ 0 | hand enumeration of budget/duration/sector/bounds | **PASS** | feasible x = [{'AAPL': 1, 'GS': 1}] |
| N9 | Qubit count | 9 | 9 | 0 | 0 | abs ≤ 0 | Σ_vars bits(ub) + Σ_sector bits(slack ub), bits(U)=⌊log₂U⌋+1 | **PASS** |  |
| N10 | QUBO energy of all 512 bitstrings (max |Δ|) | 1.56319e-13 | 0 | 1.56319e-13 | — | abs ≤ 1e-10 | objective + P·Σ(constraint residual)², own bounded-coefficient decoding | **PASS** | P = 1.39529 (Qiskit auto penalty); decoding disagreements with converter.interpret: 0 |
| N11 | Penalty sufficiency: min E(violating) − min E(satisfying) | 1.39529 | — | — | — | n/a | must be > 0 so the QUBO ground state satisfies the hard constraints | **PASS** |  |
| N12 | Ising diagonal + offset vs QUBO energy, little-endian (max |Δ|) | 7.10543e-14 | 0 | 7.10543e-14 | — | abs ≤ 1e-10 | basis index k ↔ x_i = bit i of k | **PASS** | Hermitian (max |H−H†| coeff 0.0e+00); only I/Z Paulis: True |
| N13 | Exact optimum weights (Exact solver) | {'AAPL': 0.5, 'GS': 0.5} | {'AAPL': 0.5, 'GS': 0.5} | — | — | n/a | argmin over all 2^n QUBO energies (brute force) | **PASS** |  |
| N14.classical.exp | classical expected_return | 0.231747 | 0.231747 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.classical.vol | classical volatility | 0.318138 | 0.318138 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.classical.sha | classical sharpe_ratio | 0.728448 | 0.728448 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.classical.por | classical portfolio_objective | -0.0652676 | -0.0652676 | 1.38778e-17 | 2.12629e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.exact.exp | exact expected_return | 0.239268 | 0.239268 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.exact.vol | exact volatility | 0.332194 | 0.332194 | 5.55112e-17 | 1.67105e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.exact.sha | exact sharpe_ratio | 0.720266 | 0.720266 | 2.22045e-16 | 3.08281e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.exact.por | exact portfolio_objective | -0.0644576 | -0.0644576 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.sa.exp | sa expected_return | 0.239268 | 0.239268 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.sa.vol | sa volatility | 0.332194 | 0.332194 | 5.55112e-17 | 1.67105e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.sa.sha | sa sharpe_ratio | 0.720266 | 0.720266 | 2.22045e-16 | 3.08281e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.sa.por | sa portfolio_objective | -0.0644576 | -0.0644576 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.quantum.exp | quantum expected_return | 0.239268 | 0.239268 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.quantum.vol | quantum volatility | 0.332194 | 0.332194 | 5.55112e-17 | 1.67105e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.quantum.sha | quantum sharpe_ratio | 0.720266 | 0.720266 | 2.22045e-16 | 3.08281e-16 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N14.quantum.por | quantum portfolio_objective | -0.0644576 | -0.0644576 | 0 | 0 | rel ≤ 1e-09 | recomputed from reported weights with factor Σ | **PASS** |  |
| N15 | SA qubo_energy | -0.0644576 | -0.0644576 | 1.27676e-15 | 1.98077e-14 | rel ≤ 1e-09 | feasible ⇒ QUBO energy = objective | **PASS** |  |
| N16 | SLSQP objective vs trust-constr (one-sided) | -0.0652676 | -0.0652674 | 1.54043e-07 | 2.36019e-06 | abs ≤ 1e-07 | scipy trust-constr (interior point), same constraints; accept f_SLSQP − f_ref ≤ 1e-7 and primal residual ≤ 1e-6 | **PASS** | f_SLSQP − f_ref = -1.5e-07; primal residual 7.4e-10; max |Δw| = 1.4e-05 |
| N17 | SLSQP KKT stationarity residual (relative) | 4.05033e-16 | 0 | 4.05033e-16 | — | abs ≤ 1e-06 | ‖∇f + Σλ∇g_active‖/‖∇f‖ with λ_ineq ≥ 0 (lsq_linear) | **PASS** |  |
| N18 | Backtest cumulative returns, all dates & strategies (max |Δ|) | 0 | 0 | 0 | — | abs ≤ 1e-12 | np.cumprod(1+R_oos·w)−1 (constant-mix) | **PASS** | 249 dates; final: {'SLSQP': '+0.3444 (buy-and-hold +0.3464)', 'Exact': '+0.3461 (buy-and-hold +0.3488)', 'SA': '+0.3461 (buy-and-hold +0.3488)', 'QAOA': '+0.3461 (buy-and-hold +0.3488)'} |
| N19 | QAOA gap_to_optimal_pct | 0 | 0 | 0 | — | abs ≤ 1e-09 | (f(x)−f(x*))/|f(x*)| with identical x | **PASS** |  |
| N20 | Qiskit QAOA parameter order | β[0], β[1], β[2], γ[0], γ[1], γ[2] | β[0..p-1], γ[0..p-1] (block) | — | — | n/a | QAOAAnsatz(op, reps=3).parameters | **INFO** |  |
| N21 | Initial point is a TQA linear ramp (Sack & Serbyn Eq. 6) in Qiskit's convention | β=[-0.5625, -0.375, -0.1875], γ=[0.1875, 0.375, 0.5625] | β≤0, |β|↓, γ↑, ⟨H⟩ < uniform | — | — | n/a | values as bound in Qiskit's block order; ⟨H⟩ by NumPy statevector | **PASS** | H/max|c| (max|c| = 25.1): ⟨H⟩ at init -1.468 vs uniform +0.000 |
| N22 | QAOA state probabilities: NumPy vs Qiskit Statevector (max |Δp|) | 4.92661e-16 | 0 | 4.92661e-16 | — | abs ≤ 1e-10 | independent NumPy simulation of e^{-iβΣX}e^{-iγH_C} layers | **PASS** | Σp = 0.999999999999999; ‖ψ‖ − 1 = 4.4e-16 |
| N23 | p_optimal from 1024 Aer shots vs exact |ψ|² at reported θ* | 0.0712891 | 0.0783818 | 0.0070927 | 0.0904892 | abs ≤ 0.0335964 | binomial: accept |Δ| ≤ 4σ, σ=√(p(1−p)/N) | **PASS** | σ = 0.0084, z = -0.84 |
| N24 | uniform_p_optimal (random guessing) | 0.03125 | 0.03125 | 0 | 0 | abs ≤ 1e-15 | 16 of 512 bitstrings decode to x* (slack bits are free) | **PASS** |  |
| N25 | P(x*) of the QAOA state at the initial point | 0.0727851 | 0.03125 | 0.0415351 | 1.32912 | n/a | NumPy statevector; verified value column = uniform baseline | **INFO** |  |
| N26 | P(x*) of the QAOA state at optimised θ* (exact) | 0.0783818 | 0.03125 | 0.0471318 | 1.50822 | n/a | NumPy statevector; verified value column = uniform baseline | **INFO** | ratio to uniform = 2.51× |
| N27 | Null model: P(best-feasible-of-1024 uniform samples = x*) | 1 | 1 | 7.54952e-15 | 7.54952e-15 | abs ≤ 9.72437e-10 | Monte Carlo (200000 trials) vs 1−(1−u)^N | **PASS** | 1 − P = 7.60e-15: random sampling 'finds' x* essentially always |
| N28 | QAOA: P(x* appears in the final 1024-shot histogram) | 1 | 1 | 7.54952e-15 | 7.54952e-15 | n/a | 1−(1−p)^N with exact p at θ*; verified column = null model | **INFO** |  |
| N29 | CVaR_α aggregation (200 random discrete distributions, max |Δ|) | 4.9074e-06 | 0 | 4.9074e-06 | — | abs ≤ 0.0001 | (1/α)∫₀^α F⁻¹(u)du by midpoint rule (2·10⁵ nodes); Barkoutsos et al. 2020 definition | **PASS** | tolerance set by the quadrature, not by the library |
| N30 | Wall-clock: exhaustive NumPy evaluation of all 512 QUBO energies [s] | 0.0206482 | 0.000527481 | 0.0201208 | 38.145 | n/a | vectorised einsum; reported column = Exact solver time | **INFO** | QAOA: 2.60s for 53 evaluations × 1024 shots; SA 0.031s |
