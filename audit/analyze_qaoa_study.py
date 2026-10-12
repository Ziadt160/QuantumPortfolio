"""
Summarise audit/results/qaoa_study_*.jsonl (written by qaoa_study.py).

Reports, per configuration and initial point:
  - QAOA success rate (returned portfolio == exact optimum), Wilson 95 % CI
  - SA success rate, Wilson 95 % CI
  - null-model success probability (uniform sampling, same shots and selection rule)
  - P(x*) of the QAOA state at the initial point and at θ* (exact, NumPy statevector)
    vs the uniform baseline u
  - paired comparison of P(x*) at θ* between the current and the original
    (interleaved) initial point, same seeds (Wilcoxon signed-rank)

Usage: python audit/analyze_qaoa_study.py audit/results/qaoa_study_9q.jsonl [more.jsonl ...]
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return centre - half, centre + half


def main(paths: list[str]) -> None:
    rows = [json.loads(line) for p in paths for line in Path(p).read_text(encoding="utf-8").splitlines() if line]
    out = ["| Config | Qubits | Feasible | Init | Trials | QAOA success [95% CI] | SA success [95% CI] | "
           "Null-model success | P(x*) at init | P(x*) at θ* (mean ± sd) | Uniform u | θ*/u | Evals (mean) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["config"], r["init"]), []).append(r)
    for (cfg, init), rs in sorted(groups.items()):
        n = len(rs)
        kq = sum(r["qaoa_success"] for r in rs)
        ks = sum(r["sa_success"] for r in rs)
        pe = np.array([r["p_opt_exact"] for r in rs])
        u = rs[0]["u_uniform"]
        lo, hi = wilson(kq, n)
        slo, shi = wilson(ks, n)
        out.append(f"| {cfg} | {rs[0]['n_qubits']} | {rs[0]['num_feasible']} | {init} | {n} | "
                   f"{kq}/{n} [{lo:.2f}, {hi:.2f}] | {ks}/{n} [{slo:.2f}, {shi:.2f}] | "
                   f"{rs[0]['null_success_prob']:.6f} | {rs[0]['p_opt_init']:.4f} | {pe.mean():.4f} ± {pe.std(ddof=1) if n > 1 else 0:.4f} | "
                   f"{u:.4f} | {pe.mean() / u:.2f} | {np.mean([r['evals'] for r in rs]):.1f} |")
    print("\n".join(out))
    for cfg in sorted({r["config"] for r in rows}):
        cur = {r["seed"]: r["p_opt_exact"] for r in rows if r["config"] == cfg and r["init"] == "current"}
        org = {r["seed"]: r["p_opt_exact"] for r in rows if r["config"] == cfg and r["init"] == "original"}
        seeds = sorted(set(cur) & set(org))
        if len(seeds) >= 5:
            d = np.array([cur[s] - org[s] for s in seeds])
            stat = wilcoxon(d) if np.any(d != 0) else None
            print(f"\n{cfg}: paired P(x*) at θ*, current − original init over {len(seeds)} seeds: "
                  f"mean {d.mean():+.4f}, median {np.median(d):+.4f}, "
                  f"Wilcoxon p = {stat.pvalue:.3g}" if stat else f"\n{cfg}: no paired differences")
    t = [r["qaoa_sec"] for r in rows]
    print(f"\nQAOA wall-clock per run: median {np.median(t):.2f}s (runs were concurrent with other jobs; "
          f"use isolated pipeline runs for timing claims)")


if __name__ == "__main__":
    main(sys.argv[1:])
