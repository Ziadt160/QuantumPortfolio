"""
Quantum + discrete-QUBO engine for the QuantumPortfolio demo.

Three solvers run on the **same** QuadraticProgram / QUBO:

  1. Exact NumPyMinimumEigensolver       — exact optimum of the QUBO
                                            (exhaustive over 2^n states)
  2. Simulated Annealing (dwave-samplers)— classical heuristic on the QUBO
  3. CVaR-QAOA (Barkoutsos et al. 2020)  — variational quantum heuristic,
     linear-ramp start (Sack & Serbyn       simulated noiselessly with
     2021)                                  qiskit-aer (statevector method)

Constraint strategy:
  - Budget        : equality → quadratic penalty (no slack qubits)
  - Duration      : equality on durations rounded to whole years
                    → quadratic penalty (no slack qubits)
  - Sector cap    : inequality → slack qubits + quadratic penalty
  - Max asset     : integer-variable upper bound (no extra qubits)
  - CET1 / LCR    : soft penalty λ(c·w − min)² in the objective, added only
                    when min > 0. This is the standard penalty method
                    (e.g. Lucas 2014; Glover et al. 2019), not a technique
                    from Barkoutsos et al. Being quadratic it is two-sided:
                    it also penalises exceeding the minimum. Violations are
                    measured explicitly in quant_engine.portfolio_metrics.

Endianness: Qiskit maps QUBO variable i to qubit i, and bitstrings are
little-endian (qubit 0 is the right-most character). MinimumEigenOptimizer
handles the reversal; tests/test_qubo_ising.py checks it.
"""
from __future__ import annotations

import itertools
import logging
import math
import time
from typing import Any, Dict

import numpy as np
import pandas as pd

from qiskit_optimization import QuadraticProgram
from qiskit_optimization.converters import QuadraticProgramToQubo
from qiskit_optimization.algorithms import MinimumEigenOptimizer
from qiskit_optimization.minimum_eigensolvers import QAOA, NumPyMinimumEigensolver, SamplingMinimumEigensolver
from qiskit_optimization.optimizers import COBYLA
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import SamplerV2 as AerSamplerV2

from quant_engine import portfolio_metrics

logger = logging.getLogger(__name__)

# Above this many qubits the exact solver is skipped and QAOA is refused
# (dense simulation / exhaustive enumeration cost grows as 2^n).
MAX_EXACT_QUBITS = 24
MAX_QAOA_QUBITS = 24
# Enumerate the integer grid to count feasible portfolios only if it is small.
MAX_ENUMERATION_POINTS = 200_000
# Exact, noiseless simulation. The original "matrix_product_state" method is
# also exact here but is a poor fit for all-to-all ZZ cost layers: measured
# 0.10 s vs 18.2 s per circuit at 18 qubits (AUDIT_NUMERICS.md §5).
AER_METHOD = "statevector"


def _round_half_up(x: float) -> int:
    """Round to nearest integer, ties away from zero for x ≥ 0 (Python's round() is half-to-even)."""
    return int(math.floor(x + 0.5))


def _floor_slices(fraction: float, budget_resolution: int) -> int:
    """⌊fraction · R⌋, robust to float products like 0.6·5 = 2.9999999999999996."""
    return int(math.floor(fraction * budget_resolution + 1e-9))


# =========================================================================
# QuadraticProgram construction (soft-penalty CET1/LCR formulation)
# =========================================================================
def _build_quadratic_program(
    mu: pd.Series,
    B: pd.DataFrame,
    F: pd.DataFrame,
    D: pd.Series,
    asset_metadata: pd.DataFrame,
    budget_resolution: int,
    q_factor: float,
    target_duration: float,
    max_sector_exposure: float,
    max_asset_exposure: float,
    min_cet1: float,
    min_lcr: float,
    lambda_cet1: float = 10.0,
    lambda_lcr: float = 10.0,
) -> QuadraticProgram:
    """
    Encode the Basel-III-constrained portfolio problem as a QuadraticProgram.

    Decision variables are integers x_i ∈ {0..max_y} with weights w_i = x_i / R
    (R = budget_resolution). The objective is

        q·wᵀΣw − (1−q)·μᵀw  [+ λ_cet1·((c·w − m_c)² − m_c²) if m_c > 0]
                            [+ λ_lcr ·((l·w − m_l)² − m_l²) if m_l > 0]

    (the constant −λm² is dropped, it does not change the argmin).
    CET1 and LCR enter as soft penalties; the other constraints are hard.
    A minimum ≤ 0 can never bind because all ratios are ≥ 0, so no penalty
    is added in that case.

    Discretisation (reported by `discretisation_summary`):
      - per-asset cap  max_y = max(1, ⌊max_asset·R⌋) slices. The max(1, ·)
        clamp loosens the cap when max_asset·R < 1; portfolio_metrics then
        reports the violation.
      - sector cap     max(1, ⌊max_sector·R⌋) slices (same clamp).
      - duration       Σ round(d_i)·x_i == round(T·R).
    """
    Sigma = B.dot(F).dot(B.T) + np.diag(D)
    qp = QuadraticProgram()

    # Decision vars (integer weight slices, capped by max_asset_exposure)
    max_y = max(1, _floor_slices(max_asset_exposure, budget_resolution))
    for ticker in mu.index:
        qp.integer_var(lowerbound=0, upperbound=max_y, name=str(ticker))

    # --- Objective: base risk-return + soft Basel penalties ---
    linear_terms: Dict[str, float] = {
        str(t): -(1 - q_factor) * mu.loc[t] / budget_resolution for t in mu.index
    }
    quadratic_terms: Dict[tuple, float] = {}
    for t1 in mu.index:
        for t2 in mu.index:
            cov = (
                Sigma.loc[t1, t2]
                if isinstance(Sigma, pd.DataFrame)
                else Sigma[list(mu.index).index(t1), list(mu.index).index(t2)]
            )
            quadratic_terms[(str(t1), str(t2))] = q_factor * cov / (budget_resolution ** 2)

    # CET1 soft penalty: λ · (Σ cet1_i · x_i / B  −  min_cet1)²
    if "CET1_Ratio" in asset_metadata.columns and min_cet1 > 0:
        cet1 = {str(t): float(asset_metadata.loc[t, "CET1_Ratio"]) for t in mu.index}
        if any(v > 0 for v in cet1.values()):
            for t1, c1 in cet1.items():
                linear_terms[t1] = linear_terms.get(t1, 0.0) + lambda_cet1 * (
                    -2 * min_cet1 * c1 / budget_resolution
                )
                for t2, c2 in cet1.items():
                    key = (t1, t2)
                    quadratic_terms[key] = quadratic_terms.get(key, 0.0) + lambda_cet1 * (
                        c1 * c2 / (budget_resolution ** 2)
                    )

    # LCR soft penalty: λ · (Σ lcr_i · x_i / B  −  min_lcr)²
    if "LCR" in asset_metadata.columns and min_lcr > 0:
        lcr = {str(t): float(asset_metadata.loc[t, "LCR"]) for t in mu.index}
        if any(v > 0 for v in lcr.values()):
            for t1, l1 in lcr.items():
                linear_terms[t1] = linear_terms.get(t1, 0.0) + lambda_lcr * (
                    -2 * min_lcr * l1 / budget_resolution
                )
                for t2, l2 in lcr.items():
                    key = (t1, t2)
                    quadratic_terms[key] = quadratic_terms.get(key, 0.0) + lambda_lcr * (
                        l1 * l2 / (budget_resolution ** 2)
                    )

    qp.minimize(linear=linear_terms, quadratic=quadratic_terms)

    # --- Hard constraints ---
    qp.linear_constraint(
        linear={str(t): 1 for t in mu.index},
        sense="==",
        rhs=budget_resolution,
        name="budget",
    )
    if "Duration" in asset_metadata.columns:
        # Durations are rounded to whole years so an exact equality has
        # integer solutions. The target is rounded on the slice scale
        # (round(T·R), not round(T)·R) so e.g. T=4.5, R=2 stays 4.5.
        dur = {str(t): _round_half_up(asset_metadata.loc[t, "Duration"]) for t in mu.index}
        qp.linear_constraint(
            linear=dur,
            sense="==",
            rhs=_round_half_up(target_duration * budget_resolution),
            name="duration",
        )
    max_sector_y = max(1, _floor_slices(max_sector_exposure, budget_resolution))
    if "Sector" in asset_metadata.columns:
        for i, sector in enumerate(asset_metadata["Sector"].unique()):
            sector_tickers = [
                str(t)
                for t in asset_metadata[asset_metadata["Sector"] == sector].index
                if t in mu.index
            ]
            if sector_tickers:
                qp.linear_constraint(
                    linear={t: 1 for t in sector_tickers},
                    sense="<=",
                    rhs=max_sector_y,
                    name=f"sector_{i}",
                )

    return qp


# =========================================================================
# Helpers
# =========================================================================
def _decode_weights(x: np.ndarray, qp: QuadraticProgram, budget_resolution: int) -> Dict[str, float]:
    weights: Dict[str, float] = {}
    for i, var in enumerate(qp.variables):
        v = float(x[i])
        if v > 0:
            weights[var.name] = v / budget_resolution
    return weights


def discretisation_summary(qp: QuadraticProgram, budget_resolution: int) -> Dict[str, Any]:
    """
    Report how the discrete QP differs from the stated continuous problem,
    and (for small grids) how many portfolios satisfy its hard constraints.
    """
    R = budget_resolution
    ubs = [int(v.upperbound) for v in qp.variables]
    summary: Dict[str, Any] = {
        "effective_max_asset_weight": (max(ubs) / R) if ubs else None,
    }
    sector_rhs = [c.rhs for c in qp.linear_constraints if c.name.startswith("sector_")]
    if sector_rhs:
        summary["effective_max_sector_weight"] = max(sector_rhs) / R
    if "duration" in [c.name for c in qp.linear_constraints]:
        dcon = qp.get_linear_constraint("duration")
        summary["effective_target_duration"] = dcon.rhs / R
        summary["rounded_durations"] = {k: int(v) for k, v in dcon.linear.to_dict(use_name=True).items()}
    grid = math.prod(u + 1 for u in ubs)
    summary["integer_grid_size"] = grid
    if grid <= MAX_ENUMERATION_POINTS:
        count = sum(1 for x in itertools.product(*(range(u + 1) for u in ubs)) if qp.is_feasible(list(x)))
        summary["num_feasible_portfolios"] = count
    else:
        summary["num_feasible_portfolios"] = None
    return summary


class _RoundoffFilteredSolver(SamplingMinimumEigensolver):
    """
    Delegate to `inner` after dropping Pauli terms whose coefficients are
    floating-point round-off (|c| ≤ rel_tol · max|c|). Such terms appear when
    QUBO→Ising coefficients cancel exactly in theory; their gates rotate by
    ~γ·1e-16, and with Qiskit 2.5 their parameter expressions make
    qiskit-optimization's circuit cache fail with an OverflowError.
    """

    def __init__(self, inner: SamplingMinimumEigensolver, rel_tol: float = 1e-12):
        self._inner = inner
        self._rel_tol = rel_tol

    def compute_minimum_eigenvalue(self, operator, aux_operators=None):
        scale = float(np.max(np.abs(operator.coeffs))) if len(operator) else 0.0
        return self._inner.compute_minimum_eigenvalue(operator.simplify(atol=self._rel_tol * scale), aux_operators)

    @classmethod
    def supports_aux_operators(cls) -> bool:
        # MinimumEigenOptimizer uses this as its "returns an eigenstate" check;
        # QAOA does, and aux operators are passed through unchanged.
        return True


def _linear_ramp_initial_point(reps: int, dt: float = 0.75) -> np.ndarray:
    """
    Linear-ramp (TQA-style, Sack & Serbyn 2021) starting point for QAOA:
    γ_i = s_i·dt increasing, β_i = (1 − s_i)·dt decreasing, s_i = (i+1)/(p+1).

    The returned layout is [β_0..β_{p-1}, γ_0..γ_{p-1}], which is the order
    of QAOAAnsatz.parameters (Qiskit sorts parameters by name, "β" < "γ").
    An interleaved layout would bind the values to the wrong parameters.

    dt = 0.75 is the value Sack & Serbyn report for unit-weight MaxCut; it is
    not calibrated to this Hamiltonian's energy scale.
    """
    s = np.arange(1, reps + 1) / (reps + 1)
    betas = (1 - s) * dt
    gammas = s * dt
    return np.concatenate([betas, gammas])


# =========================================================================
# Simulated Annealing on the same QUBO (classical heuristic baseline)
# =========================================================================
def _solve_simulated_annealing(
    qubo: QuadraticProgram,
    converter: QuadraticProgramToQubo,
    num_reads: int = 200,
    num_sweeps: int = 1000,
    seed: int | None = None,
) -> Dict[str, Any]:
    """
    Simulated annealing (dwave-samplers, compiled, seedable) on the converted
    QUBO. dimod's own SimulatedAnnealingSampler is a pure-Python reference
    implementation that cannot be seeded and is documented as unsuitable
    for benchmarking, so it is not used.
    """
    import dimod
    from dwave.samplers import SimulatedAnnealingSampler

    var_names = [v.name for v in qubo.variables]
    obj = qubo.objective
    linear = obj.linear.to_dict()
    quadratic = obj.quadratic.to_dict()
    constant = float(obj.constant)

    h: Dict[str, float] = {}
    Q: Dict[tuple, float] = {}
    for idx, val in linear.items():
        if abs(val) > 1e-12:
            h[var_names[idx]] = float(val)
    for (i, j), val in quadratic.items():
        if abs(val) <= 1e-12:
            continue
        if i == j:
            # x_i^2 = x_i for binary; fold into the linear term.
            h[var_names[i]] = h.get(var_names[i], 0.0) + float(val)
        else:
            key = (var_names[i], var_names[j]) if i < j else (var_names[j], var_names[i])
            Q[key] = Q.get(key, 0.0) + float(val)

    bqm = dimod.BinaryQuadraticModel(h, Q, constant, vartype="BINARY")
    sampler = SimulatedAnnealingSampler()

    t0 = time.time()
    response = sampler.sample(bqm, num_reads=num_reads, num_sweeps=num_sweeps, seed=seed)
    elapsed = time.time() - t0

    best = response.first
    bin_vec = np.array([int(best.sample[v]) for v in var_names], dtype=float)
    decoded_x = converter.interpret(bin_vec)

    return {
        "x": decoded_x,
        "energy": float(best.energy),
        "time_sec": elapsed,
        "num_reads": num_reads,
        "seed": seed,
    }


# =========================================================================
# Main entry point
# =========================================================================
def _qp_eval(qp: QuadraticProgram, x: np.ndarray) -> Dict[str, Any]:
    """Objective (incl. soft penalties, excl. constants) and hard-constraint feasibility on the discrete QP."""
    x = np.asarray(x, dtype=float)
    return {"qp_objective": float(qp.objective.evaluate(x)), "qp_feasible": bool(qp.is_feasible(x))}


def _uniform_probability(converter: QuadraticProgramToQubo, n_qubits: int, target: np.ndarray) -> float:
    """Probability that a uniformly random bitstring decodes to `target` (exhaustive; small n only)."""
    hits = 0
    for k in range(2 ** n_qubits):
        bits = np.array([(k >> i) & 1 for i in range(n_qubits)], dtype=float)
        if np.array_equal(np.asarray(converter.interpret(bits), dtype=float), target):
            hits += 1
    return hits / 2 ** n_qubits


def optimize_portfolio_qaoa(
    mu: pd.Series,
    B: pd.DataFrame,
    F: pd.DataFrame,
    D: pd.Series,
    asset_metadata: pd.DataFrame,
    budget_resolution: int = 2,
    q_factor: float = 0.5,
    target_duration: float = 4.0,
    max_sector_exposure: float = 0.40,
    max_asset_exposure: float = 0.25,
    min_cet1: float = 0.12,
    min_lcr: float = 1.00,
    qaoa_reps: int = 3,
    qaoa_cvar_alpha: float = 0.25,
    qaoa_maxiter: int = 80,
    qaoa_shots: int = 1024,
    sa_num_reads: int = 200,
    sa_num_sweeps: int = 1000,
    seed: int | None = 42,
) -> Dict[str, Any]:
    """
    Run all three discrete-QUBO solvers on the Basel-III portfolio problem.

    Returns metrics for each solver and the wall-clock timing breakdown.
    Every solver is scored twice: on the stated continuous problem
    (portfolio_metrics: return, risk, violations) and on the discrete QP it
    actually optimises (qp_objective, qp_feasible). gap_to_optimal_pct is
    measured on qp_objective, the quantity the exact solver minimises.

    Raises ValueError if the QUBO needs more than MAX_QAOA_QUBITS qubits.
    """
    asset_metadata = asset_metadata.reindex(mu.index)
    num_assets = len(mu)
    Sigma_full = (B.dot(F).dot(B.T) + np.diag(D)).values

    qp = _build_quadratic_program(
        mu=mu, B=B, F=F, D=D,
        asset_metadata=asset_metadata,
        budget_resolution=budget_resolution,
        q_factor=q_factor,
        target_duration=target_duration,
        max_sector_exposure=max_sector_exposure,
        max_asset_exposure=max_asset_exposure,
        min_cet1=min_cet1,
        min_lcr=min_lcr,
    )

    converter = QuadraticProgramToQubo()
    qubo = converter.convert(qp)
    n_qubits = qubo.get_num_binary_vars()
    logger.info(
        "QP formulated: %d integer vars, %d constraints → QUBO with %d qubits",
        num_assets, qp.get_num_linear_constraints(), n_qubits,
    )
    if n_qubits > MAX_QAOA_QUBITS:
        raise ValueError(
            f"QUBO needs {n_qubits} qubits (> {MAX_QAOA_QUBITS}); reduce budget_resolution or the number of tickers"
        )

    def metrics(x: np.ndarray) -> Dict[str, Any]:
        out = portfolio_metrics(
            weights=_decode_weights(x, qp, budget_resolution), mu=mu, Sigma=Sigma_full,
            asset_metadata=asset_metadata,
            q_factor=q_factor,
            target_duration=target_duration,
            max_sector_exposure=max_sector_exposure,
            max_asset_exposure=max_asset_exposure,
            min_cet1=min_cet1, min_lcr=min_lcr,
        )
        out.update(_qp_eval(qp, x))
        return out

    # --- 1) Exact optimum of the QUBO (NumPyMinimumEigensolver). Skip if too large.
    exact_metrics: Dict[str, Any] | None = None
    exact_time: float | None = None
    exact_x: np.ndarray | None = None
    if n_qubits <= MAX_EXACT_QUBITS:
        t0 = time.time()
        try:
            exact_solver = MinimumEigenOptimizer(NumPyMinimumEigensolver())
            exact_res = exact_solver.solve(qp)
            exact_time = time.time() - t0
            exact_x = np.asarray(exact_res.x, dtype=float)
            exact_metrics = metrics(exact_x)
            logger.info("Exact solver: %.3fs", exact_time)
        except Exception as exc:
            logger.warning("Exact solver failed: %s", exc)
    else:
        logger.info("Skipping exact solver — %d qubits is too large", n_qubits)

    # --- 2) Simulated Annealing on the same QUBO.
    sa_raw = _solve_simulated_annealing(
        qubo=qubo, converter=converter,
        num_reads=sa_num_reads, num_sweeps=sa_num_sweeps, seed=seed,
    )
    sa_metrics = metrics(sa_raw["x"])
    sa_metrics["qubo_energy"] = sa_raw["energy"]
    logger.info("Simulated Annealing: %.3fs", sa_raw["time_sec"])

    # --- 3) CVaR-QAOA with linear-ramp init on a noiseless Aer sampler.
    backend_options = {"method": AER_METHOD}
    sampler = AerSamplerV2(
        default_shots=qaoa_shots,
        seed=seed,
        options={"backend_options": backend_options},
    )
    # Rewrite the ansatz into the simulator's native gate set (V2 primitives
    # do not transpile); this changes gate decomposition, not the unitary.
    pass_manager = generate_preset_pass_manager(optimization_level=1, backend=AerSimulator(**backend_options))
    optimizer = COBYLA(maxiter=qaoa_maxiter)
    initial_point = _linear_ramp_initial_point(qaoa_reps)
    qaoa = QAOA(
        sampler=sampler,
        optimizer=optimizer,
        reps=qaoa_reps,
        initial_point=initial_point,
        aggregation=qaoa_cvar_alpha,  # CVaR-α (Barkoutsos et al. 2020)
        pass_manager=pass_manager,
    )
    meo = MinimumEigenOptimizer(_RoundoffFilteredSolver(qaoa))
    t0 = time.time()
    qaoa_res = meo.solve(qp)
    qaoa_time = time.time() - t0
    qaoa_x = np.asarray(qaoa_res.x, dtype=float)
    qaoa_metrics = metrics(qaoa_x)
    # MinimumEigenOptimizer returns the best *feasible* bitstring observed in
    # the final shot histogram, so also report how much probability the QAOA
    # state actually puts on it (and on feasible / optimal solutions).
    samples = qaoa_res.samples or []
    qaoa_metrics["p_returned_solution"] = float(
        sum(s.probability for s in samples if np.array_equal(np.asarray(s.x, dtype=float), qaoa_x))
    )
    qaoa_metrics["p_feasible"] = float(sum(s.probability for s in samples if qp.is_feasible(s.x)))
    if exact_x is not None:
        qaoa_metrics["p_optimal"] = float(
            sum(s.probability for s in samples if np.array_equal(np.asarray(s.x, dtype=float), exact_x))
        )
        if n_qubits <= 12:
            qaoa_metrics["uniform_p_optimal"] = _uniform_probability(converter, n_qubits, exact_x)
    mes_result = qaoa_res.min_eigen_solver_result
    qaoa_metrics["cost_function_evals"] = int(getattr(mes_result, "cost_function_evals", 0) or 0)
    opt_point = getattr(mes_result, "optimal_point", None)
    qaoa_metrics["optimal_parameters"] = [float(v) for v in opt_point] if opt_point is not None else None
    logger.info("CVaR-QAOA: %.3fs", qaoa_time)

    # --- Gap to optimum, on the QP objective the exact solver minimises.
    if exact_metrics is not None and exact_metrics["qp_feasible"]:
        e_star = exact_metrics["qp_objective"]
        denom = abs(e_star) if abs(e_star) > 1e-9 else 1.0
        for m in (sa_metrics, qaoa_metrics):
            if m["qp_feasible"]:
                m["gap_to_optimal_pct"] = (m["qp_objective"] - e_star) / denom * 100.0
            else:
                m["gap_to_optimal_pct"] = None

    qubo_info = {
        "num_qubits": n_qubits,
        "num_integer_vars": num_assets,
        "num_constraints": qp.get_num_linear_constraints(),
        "constraint_penalty": float(converter.penalty) if converter.penalty is not None else None,
    }
    qubo_info.update(discretisation_summary(qp, budget_resolution))

    return {
        "exact": exact_metrics,
        "exact_classical": exact_metrics,  # legacy alias
        "sa": sa_metrics,
        "qaoa": qaoa_metrics,
        "qubo": qubo_info,
        "timings": {
            "exact_sec": exact_time,
            "sa_sec": sa_raw["time_sec"],
            "qaoa_sec": qaoa_time,
        },
        "qaoa_config": {
            "reps": qaoa_reps,
            "cvar_alpha": qaoa_cvar_alpha,
            "init": "linear_ramp",
            "optimizer": f"COBYLA(maxiter={qaoa_maxiter})",
            "shots": qaoa_shots,
            "seed": seed,
            "backend": f"qiskit-aer SamplerV2 / {AER_METHOD} (noiseless)",
            "selection": "best feasible sample of the final shot histogram",
        },
        "sa_config": {"num_reads": sa_num_reads, "num_sweeps": sa_num_sweeps, "seed": seed},
    }
