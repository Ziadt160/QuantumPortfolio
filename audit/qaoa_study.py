"""
Repeated-trial study of the project's CVaR-QAOA versus simulated annealing and
a uniform-random-sampling null model, on the frozen data snapshot.

For each configuration and seed it calls quantum_engine.optimize_portfolio_qaoa
(the code under audit) and records:
  - success      : returned portfolio == exact optimum
  - p_opt_hist   : fraction of the final 1024 shots that decode to the optimum
  - p_opt_exact  : |ψ(θ*)|² mass on the optimum, from an independent NumPy
                   statevector simulation at the optimiser's final parameters
For the null model (sample N uniform bitstrings, return the best feasible one,
which is exactly MinimumEigenOptimizer's selection rule) the success
probability is 1 − (1 − u)^N with u = (#bitstrings decoding to x*) / 2^n.

`--init original` reproduces the original initial point (interleaved β/γ
order, positive β, no energy scaling) inside the current code, to isolate
the effect of the initial-point corrections.

Usage (repo root):
  python audit/qaoa_study.py --configs C1,C2 --seeds 20 --out audit/results/qaoa_study_9q.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "audit"))
import run_pipeline_snapshot as rps  # noqa: E402
from verify_numerics import numpy_qaoa_state  # noqa: E402

qe, qm, _ = rps.import_backend("current")

BASE = dict(q_factor=0.5, min_cet1=0.0, min_lcr=0.0, qaoa_reps=3, qaoa_cvar_alpha=0.25,
            qaoa_maxiter=80, qaoa_shots=1024, sa_num_reads=200, sa_num_sweeps=1000)
CONFIGS = {
    "C1": dict(budget_resolution=2, target_duration=4.0, max_sector_exposure=0.6, max_asset_exposure=0.5),
    "C2": dict(budget_resolution=2, target_duration=4.5, max_sector_exposure=0.6, max_asset_exposure=0.5),
    "C3": dict(budget_resolution=4, target_duration=4.0, max_sector_exposure=0.6, max_asset_exposure=0.5),
}


def original_interleaved_init(reps: int, dt: float = 0.75, energy_scale: float = 1.0) -> np.ndarray:
    """The initial point exactly as the original code built it ([β0, γ0, β1, γ1, ...], β > 0, unscaled)."""
    params = np.empty(2 * reps, dtype=float)
    for i in range(reps):
        s = (i + 1) / (reps + 1)
        params[2 * i] = (1 - s) * dt
        params[2 * i + 1] = s * dt
    return params


def problem_objects(cfg):
    from qiskit_optimization.converters import QuadraticProgramToQubo
    prices = rps.load_snapshot()["insample"]
    mu, _ = qe.calculate_classical_inputs(prices)
    B, F, D = qe.generate_statistical_factor_model(prices, 3)
    md = qe.get_asset_metadata(list(prices.columns))
    qp = qm._build_quadratic_program(mu=mu, B=B, F=F, D=D, asset_metadata=md, q_factor=BASE["q_factor"],
                                     min_cet1=0.0, min_lcr=0.0, **cfg)
    conv = QuadraticProgramToQubo()
    qubo = conv.convert(qp)
    n = qubo.get_num_binary_vars()
    # decoding is linear (all lower bounds are 0): x = bits @ M
    M = np.array([np.asarray(conv.interpret(np.eye(n)[j]), dtype=float) for j in range(n)])
    assert np.allclose(np.asarray(conv.interpret(np.zeros(n)), dtype=float), 0)
    op, _ = qubo.to_ising()
    scale = float(np.max(np.abs(op.coeffs)))
    # QAOA runs on the operator normalised to max|c| = 1 (quantum_engine._NormalizedCostSolver)
    return dict(mu=mu, B=B, F=F, D=D, md=md, qp=qp, n=n, M=M,
                E=np.real(op.to_matrix(sparse=True).diagonal()) / scale, scale=scale)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="C1,C2")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--inits", default="current,original")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    current_init = qm._linear_ramp_initial_point

    for cname in args.configs.split(","):
        cfg = CONFIGS[cname]
        po = problem_objects(cfg)
        n, M = po["n"], po["M"]
        idx = np.arange(2 ** n)
        bits = ((idx[:, None] >> np.arange(n)) & 1).astype(float)
        X = np.rint(bits @ M).astype(int)
        for init in args.inits.split(","):
            qm._linear_ramp_initial_point = original_interleaved_init if init == "original" else current_init
            for seed in range(args.seeds):
                t0 = time.time()
                res = qm.optimize_portfolio_qaoa(mu=po["mu"], B=po["B"], F=po["F"], D=po["D"],
                                                 asset_metadata=po["md"], seed=seed, **BASE, **cfg)
                exact_w, q = res["exact"]["weights"], res["qaoa"]
                x_star = np.array([round(exact_w.get(t, 0.0) * cfg["budget_resolution"]) for t in po["mu"].index])
                opt_mask = (X == x_star).all(axis=1)
                u = float(opt_mask.mean())
                theta = np.array(q["optimal_parameters"])
                p = BASE["qaoa_reps"]
                p_exact = float((np.abs(numpy_qaoa_state(po["E"], theta[:p], theta[p:])) ** 2)[opt_mask].sum())
                theta0 = qm._linear_ramp_initial_point(p)
                p_init = float((np.abs(numpy_qaoa_state(po["E"], theta0[:p], theta0[p:])) ** 2)[opt_mask].sum())
                rec = dict(config=cname, init=init, seed=seed, n_qubits=n,
                           num_feasible=res["qubo"]["num_feasible_portfolios"],
                           qaoa_success=q["weights"] == exact_w, qaoa_gap=q.get("gap_to_optimal_pct"),
                           qaoa_qp_feasible=q["qp_feasible"], p_opt_hist=q.get("p_optimal"),
                           p_opt_exact=p_exact, p_opt_init=p_init, u_uniform=u,
                           null_success_prob=1 - (1 - u) ** BASE["qaoa_shots"],
                           evals=q["cost_function_evals"], qaoa_sec=res["timings"]["qaoa_sec"],
                           sa_success=res["sa"]["weights"] == exact_w, sa_sec=res["timings"]["sa_sec"],
                           exact_sec=res["timings"]["exact_sec"], wall=time.time() - t0)
                with out.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec) + "\n")
                print(json.dumps(rec), flush=True)
    qm._linear_ramp_initial_point = current_init


if __name__ == "__main__":
    main()
