"""
Independent numerical verification of the QuantumPortfolio pipeline.

Every reference value here is computed from the frozen price snapshot with
NumPy (and, for one cross-check, SciPy's trust-constr), *not* by calling the
function under test. Code under test is only used to obtain the objects whose
correctness is being checked (the QuadraticProgram, the QUBO, the Ising
operator, the QAOA ansatz) and the reported API payloads in audit/results/.

Inputs
  audit/data/prices_insample.csv, audit/data/prices_oos.csv      (snapshot)
  audit/results/original_pipeline_default.json   (code as found, author env)
  audit/results/current_pipeline_default.json    (fixed code)

Outputs
  audit/results/numerics.json        machine-readable check records
  audit/results/numerics_table.md    the table embedded in AUDIT_NUMERICS.md

Run from the repository root:
  python audit/verify_numerics.py
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "audit" / "results"
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "audit"))

import run_pipeline_snapshot as rps  # noqa: E402

qe, qm, _ = rps.import_backend("current")

TRADING_DAYS = 252
DEFAULT = dict(budget_resolution=2, q_factor=0.5, target_duration=4.0, max_sector_exposure=0.60,
               max_asset_exposure=0.50, min_cet1=0.0, min_lcr=0.0)
CHECKS: list[dict] = []


# ---------------------------------------------------------------------------
# bookkeeping
# ---------------------------------------------------------------------------
def record(cid, claim, reported, verified, tol, method, *, status=None, note="", rel=False):
    num = lambda v: float(v) if isinstance(v, (int, float, np.number)) and not isinstance(v, bool) else v  # noqa: E731
    rep, ver = num(reported), num(verified)
    abs_err = rel_err = None
    if isinstance(rep, float) and isinstance(ver, float):
        abs_err = abs(rep - ver)
        rel_err = abs_err / abs(ver) if abs(ver) > 0 else None
        if status is None:
            err = rel_err if (rel and rel_err is not None) else abs_err
            status = "PASS" if err <= tol else "FAIL"
    CHECKS.append(dict(id=cid, claim=claim, reported=rep, verified=ver, abs_err=abs_err, rel_err=rel_err,
                       tolerance=(f"rel ≤ {tol:g}" if rel else f"abs ≤ {tol:g}") if tol is not None else "n/a",
                       method=method, status=status or "INFO", note=note))


def fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


# ---------------------------------------------------------------------------
# independent reference implementations (NumPy only)
# ---------------------------------------------------------------------------
def ref_simple_returns(prices: pd.DataFrame) -> np.ndarray:
    P = prices.to_numpy(dtype=float)
    return P[1:] / P[:-1] - 1.0


def ref_moments(R: np.ndarray):
    return R.mean(axis=0) * TRADING_DAYS, np.cov(R, rowvar=False, ddof=1) * TRADING_DAYS


def ref_factor_covariance(R: np.ndarray, k: int) -> np.ndarray:
    """PCA on the correlation matrix via SVD of standardised returns (code uses eigh of the covariance)."""
    T = R.shape[0]
    s = R.std(axis=0, ddof=1)
    Z = (R - R.mean(axis=0)) / s
    _, sv, Vt = np.linalg.svd(Z, full_matrices=False)
    lam = sv ** 2 / (T - 1)
    Bm = s[:, None] * Vt.T[:, :k]
    sys_cov = Bm @ np.diag(lam[:k] * TRADING_DAYS) @ Bm.T
    full = np.cov(R, rowvar=False, ddof=1) * TRADING_DAYS
    D = np.maximum(np.diag(full) - np.diag(sys_cov), 1e-6)
    return sys_cov + np.diag(D)


def round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def bounded_coeffs(ub: int) -> list[int]:
    """Bounded-coefficient binary encoding of an integer in [0, ub]: 1,2,..,2^(k-1), ub-(2^k-1)."""
    if ub <= 0:
        return []
    k = int(math.floor(math.log2(ub)))
    return [2 ** i for i in range(k)] + [ub - (2 ** k - 1)]


def ref_problem(md: pd.DataFrame, tickers, R_: int, T: float, ms: float, ma: float):
    """Discrete problem data as specified in AUDIT_SCIENCE.md (current formulation)."""
    max_y = max(1, int(math.floor(ma * R_ + 1e-9)))
    cap = max(1, int(math.floor(ms * R_ + 1e-9)))
    d = np.array([round_half_up(md.loc[t, "Duration"]) for t in tickers])
    rhs = round_half_up(T * R_)
    sectors = list(dict.fromkeys(md.loc[tickers, "Sector"]))
    masks = [np.array([md.loc[t, "Sector"] == s for t in tickers], dtype=int) for s in sectors]
    return dict(max_y=max_y, cap=cap, d=d, rhs=rhs, sectors=sectors, masks=masks)


def ref_feasible(x: np.ndarray, prob: dict, R_: int) -> bool:
    return (x.sum() == R_ and int(prob["d"] @ x) == prob["rhs"]
            and all(int(m @ x) <= prob["cap"] for m in prob["masks"])
            and (x >= 0).all() and (x <= prob["max_y"]).all())


def ref_objective(x: np.ndarray, mu: np.ndarray, S: np.ndarray, q: float, R_: int, pen=()) -> float:
    w = x / R_
    val = q * w @ S @ w - (1 - q) * mu @ w
    for lam, c, m in pen:              # soft penalty λ(c·w − m)² without the constant λm²
        val += lam * ((c @ w - m) ** 2 - m ** 2)
    return float(val)


def numpy_qaoa_state(energies: np.ndarray, betas, gammas) -> np.ndarray:
    """|ψ⟩ = Π_l e^{-iβ_l ΣX} e^{-iγ_l H_C} |+⟩^n with H_C = diag(energies); qubit i = bit i of the index."""
    n = int(round(math.log2(energies.size)))
    psi = np.full(energies.size, 1 / math.sqrt(energies.size), dtype=complex)
    for b, g in zip(betas, gammas):
        psi = np.exp(-1j * g * energies) * psi
        c, s = math.cos(b), math.sin(b)
        for i in range(n):
            v = psi.reshape(2 ** (n - 1 - i), 2, 2 ** i)
            a0, a1 = v[:, 0, :].copy(), v[:, 1, :].copy()
            v[:, 0, :] = c * a0 - 1j * s * a1
            v[:, 1, :] = -1j * s * a0 + c * a1
            psi = v.reshape(-1)
    return psi


# ---------------------------------------------------------------------------
def main() -> None:
    snap = rps.load_snapshot()
    prices, prices_oos = snap["insample"], snap["oos"]
    tickers = list(prices.columns)
    orig = json.loads((RES / "original_pipeline_default.json").read_text(encoding="utf-8"))
    cur = json.loads((RES / "current_pipeline_default.json").read_text(encoding="utf-8"))

    # ---------------- A. market inputs ------------------------------------
    R = ref_simple_returns(prices)
    mu_ref, S_ref = ref_moments(R)
    mu_code, S_code = qe.calculate_classical_inputs(prices)
    record("N1", "Annualised mean returns μ (max |Δμ_i|)", float(np.max(np.abs(mu_code.values - mu_ref))), 0.0, 1e-12,
           "NumPy mean of P_t/P_{t-1}−1, ×252", note="μ = " + ", ".join(f"{t} {v:.4f}" for t, v in zip(tickers, mu_ref)))
    d = float(np.max(np.abs(S_code.values - S_ref)))
    record("N2", "Annualised sample covariance Σ (max |ΔΣ_ij|)", d, 0.0, 1e-12, "np.cov(ddof=1)×252")

    B, F, D = qe.generate_statistical_factor_model(prices, num_factors=3)
    Sf_code = (B.dot(F).dot(B.T) + np.diag(D)).to_numpy()
    Sf_ref = ref_factor_covariance(R, 3)
    record("N3", "3-factor PCA covariance BFBᵀ+diag(D) (max |Δ|)", float(np.max(np.abs(Sf_code - Sf_ref))), 0.0,
           1e-12, "SVD of standardised returns (code: eigh of correlation)")
    record("N4", "diag(Σ_factor) = diag(Σ_sample) (max |Δ|)", float(np.max(np.abs(np.diag(Sf_code) - np.diag(S_ref)))),
           0.0, 1e-12, "construction property (D = diag Σ − diag BFBᵀ, unclipped here)")
    rel_frob = float(np.linalg.norm(Sf_code - S_ref) / np.linalg.norm(S_ref))
    corr = lambda M: M / np.sqrt(np.outer(np.diag(M), np.diag(M)))  # noqa: E731
    record("N5", "Factor-model approximation error ‖Σ_f−Σ‖_F/‖Σ‖_F", rel_frob, None, None,
           "informational: how far the QUBO's risk model is from the sample covariance",
           note=f"max |Δcorrelation| = {np.max(np.abs(corr(Sf_code) - corr(S_ref))):.3f}")
    eig_min = float(np.linalg.eigvalsh(Sf_code).min())
    record("N6", "Σ_factor is positive definite (min eigenvalue)", eig_min, None, None, "np.linalg.eigvalsh",
           status="PASS" if eig_min > 0 else "FAIL")

    # ---------------- B. discrete formulation -----------------------------
    md = qe.get_asset_metadata(tickers)
    qp = qm._build_quadratic_program(mu=mu_code, B=B, F=F, D=D, asset_metadata=md, **DEFAULT)
    prob = ref_problem(md, tickers, 2, 4.0, 0.60, 0.50)
    grid = [np.array(x) for x in itertools.product(range(prob["max_y"] + 1), repeat=len(tickers))]
    errs = [abs(qp.objective.evaluate(x.astype(float)) - ref_objective(x, mu_ref, Sf_ref, 0.5, 2)) for x in grid]
    record("N7", "Current QP objective at every integer point (max |Δ|)", float(max(errs)), 0.0, 1e-12,
           f"q·wᵀΣ_f w−(1−q)μᵀw, w=x/R, all {len(grid)} points; no Basel penalty because min_cet1=min_lcr=0")

    spec = importlib.util.spec_from_file_location("orig_quantum_engine",
                                                  ROOT / "audit" / "original_backend" / "quantum_engine.py")
    oqm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oqm)
    oqp = oqm._build_quadratic_program(mu=mu_code, B=B, F=F, D=D, asset_metadata=md, **DEFAULT)
    c = md["CET1_Ratio"].to_numpy(); lcr = md["LCR"].to_numpy()
    pen0 = [(10.0, c, 0.0), (10.0, lcr, 0.0)]
    errs = [abs(oqp.objective.evaluate(x.astype(float)) - ref_objective(x, mu_ref, Sf_ref, 0.5, 2, pen0)) for x in grid]
    record("N8", "Original QP objective incl. its CET1/LCR term (max |Δ|)", float(max(errs)), 0.0, 1e-12,
           "same formula + 10(c·w)² + 10(l·w)²: confirms the original penalty is active at min=0",
           note="implemented as written; the formulation itself is the defect (AUDIT_SCIENCE §4.3)")
    x_gs = np.array([t == "GS" for t in tickers], dtype=float)  # x_GS = 1 → w_GS = 0.5
    record("N9", "Original vacuous Basel penalty on 50% GS (λ[(0.15·0.5)²+(1.30·0.5)²])",
           float(oqp.objective.evaluate(x_gs) - qp.objective.evaluate(x_gs)),
           10 * ((0.15 * 0.5) ** 2 + (1.30 * 0.5) ** 2), 1e-12, "hand calculation",
           note="≈ 65× |portfolio objective| (−0.0645)")

    feas_ref = [tuple(x) for x in grid if ref_feasible(x, prob, 2)]
    feas_code = [tuple(x) for x in grid if qp.is_feasible(x.astype(float))]
    record("N10", "Number of feasible portfolios (dashboard defaults)", len(feas_code), len(feas_ref), 0,
           "hand enumeration of budget/duration/sector/bounds",
           note=f"feasible x = {[dict((tickers[i], v) for i, v in enumerate(f) if v) for f in feas_ref]}")
    if feas_code != feas_ref:
        CHECKS[-1]["status"] = "FAIL"

    from qiskit_optimization.converters import QuadraticProgramToQubo
    conv = QuadraticProgramToQubo()
    qubo = conv.convert(qp)
    n = qubo.get_num_binary_vars()
    n_ref = sum(len(bounded_coeffs(prob["max_y"])) for _ in tickers) + \
        sum(len(bounded_coeffs(prob["cap"])) for _ in prob["masks"])
    record("N11", "Qubit count", cur["qubo"]["num_qubits"], n_ref, 0,
           "Σ_vars bits(ub) + Σ_sector bits(slack ub), bits(U)=⌊log₂U⌋+1", note=f"original also {orig['qubo']['num_qubits']}")

    # independent QUBO energies for all 2^n bitstrings
    names = [v.name for v in qubo.variables]
    groups: dict[str, list[int]] = {}
    for i, nm in enumerate(names):
        groups.setdefault(nm.rsplit("@", 1)[0], []).append(i)
    P = float(conv.penalty)
    E_ref = np.empty(2 ** n)
    E_code = np.empty(2 ** n)
    decoded = np.empty((2 ** n, len(tickers)), dtype=int)
    interp_mismatch = 0
    for k in range(2 ** n):
        bits = np.array([(k >> i) & 1 for i in range(n)])
        val = {}
        for g, idx in groups.items():
            ub = prob["max_y"] if "@int_slack" not in g else prob["cap"]
            val[g] = int(sum(cf * bits[i] for cf, i in zip(bounded_coeffs(ub), idx)))
        x = np.array([val[t] for t in tickers])
        decoded[k] = x
        resid = (x.sum() - 2) ** 2 + (int(prob["d"] @ x) - prob["rhs"]) ** 2
        for j, m in enumerate(prob["masks"]):
            resid += (int(m @ x) + val[f"sector_{j}@int_slack"] - prob["cap"]) ** 2
        E_ref[k] = ref_objective(x, mu_ref, Sf_ref, 0.5, 2) + P * resid
        E_code[k] = qubo.objective.evaluate(bits.astype(float))
        if not np.array_equal(np.asarray(conv.interpret(bits.astype(float))), x):
            interp_mismatch += 1
    record("N12", f"QUBO energy of all {2 ** n} bitstrings (max |Δ|)", float(np.max(np.abs(E_code - E_ref))), 0.0,
           1e-10, "objective + P·Σ(constraint residual)², own bounded-coefficient decoding",
           note=f"P = {P:.6g} (Qiskit auto penalty); decoding disagreements with converter.interpret: {interp_mismatch}")
    resid_zero = np.isclose(E_ref - np.array([ref_objective(decoded[k], mu_ref, Sf_ref, 0.5, 2) for k in range(2 ** n)]), 0)
    margin = float(E_ref[~resid_zero].min() - E_ref[resid_zero].min())
    record("N13", "Penalty sufficiency: min E(violating) − min E(satisfying)", margin, None, None,
           "must be > 0 so the QUBO ground state satisfies the hard constraints", status="PASS" if margin > 0 else "FAIL")

    op, offset = qubo.to_ising()
    diag = np.real(op.to_matrix(sparse=True).diagonal()) + offset
    herm = float(np.max(np.abs((op - op.adjoint()).simplify().coeffs))) if len((op - op.adjoint()).simplify()) else 0.0
    only_z = all(set(lbl) <= {"I", "Z"} for lbl in op.paulis.to_labels())
    record("N14", "Ising diagonal + offset vs QUBO energy, little-endian (max |Δ|)", float(np.max(np.abs(diag - E_ref))),
           0.0, 1e-10, "basis index k ↔ x_i = bit i of k",
           note=f"Hermitian (max |H−H†| coeff {herm:.1e}); only I/Z Paulis: {only_z}")

    kstar = int(np.argmin(E_ref))
    x_star = decoded[kstar]
    exact_w = {t: x_star[i] / 2 for i, t in enumerate(tickers) if x_star[i]}
    record("N15", "Exact optimum weights (Exact solver, original & current)", str(cur["exact"]["weights"]), str(exact_w),
           None, "argmin over all 2^n QUBO energies (brute force)",
           status="PASS" if cur["exact"]["weights"] == exact_w == orig["exact"]["weights"] else "FAIL")

    # ---------------- C. reported metrics ---------------------------------
    def metrics_ref(wd, S):
        w = np.array([wd.get(t, 0.0) for t in tickers])
        ret = float(mu_ref @ w); var = float(w @ S @ w)
        return dict(expected_return=ret, volatility=math.sqrt(var), sharpe_ratio=ret / math.sqrt(var),
                    portfolio_objective=0.5 * var - 0.5 * ret)

    for label, payload, key, S, Sname in [
        ("original", orig, "classical", S_ref, "sample Σ"), ("original", orig, "exact", Sf_ref, "factor Σ"),
        ("original", orig, "sa", Sf_ref, "factor Σ"), ("original", orig, "quantum", Sf_ref, "factor Σ"),
        ("current", cur, "classical", Sf_ref, "factor Σ"), ("current", cur, "exact", Sf_ref, "factor Σ"),
        ("current", cur, "sa", Sf_ref, "factor Σ"), ("current", cur, "quantum", Sf_ref, "factor Σ"),
    ]:
        ref = metrics_ref(payload[key]["weights"], S)
        for m in ("expected_return", "volatility", "sharpe_ratio", "portfolio_objective"):
            if m in payload[key]:
                record(f"N16.{label[0]}.{key}.{m[:3]}", f"{label}: {key} {m}", payload[key][m], ref[m], 1e-9,
                       f"recomputed from reported weights with {Sname}", rel=True)

    w_orig_sa = np.array([orig["sa"]["weights"].get(t, 0.0) for t in tickers])
    e_pen = ref_objective(w_orig_sa * 2, mu_ref, Sf_ref, 0.5, 2, pen0)
    record("N17", "original: SA qubo_energy at x=(AAPL,GS)", orig["sa"]["qubo_energy"], e_pen, 1e-9,
           "objective + 10(c·w)² + 10(l·w)², feasible ⇒ zero constraint penalty", rel=True,
           note="value is dominated by the vacuous Basel penalty (4.28 of 4.22)")
    record("N18", "original: QAOA qubo_fval", orig["quantum"]["qubo_fval"], e_pen, 1e-9,
           "same; note this is the QP objective (incl. soft penalty), not a QUBO energy", rel=True)
    record("N19", "current: SA qubo_energy", cur["sa"]["qubo_energy"], ref_objective(w_orig_sa * 2, mu_ref, Sf_ref, 0.5, 2),
           1e-9, "feasible ⇒ QUBO energy = objective", rel=True)

    # SLSQP optimality: independent algorithm + KKT
    from scipy.optimize import Bounds, LinearConstraint, minimize, lsq_linear
    dur = md["Duration"].to_numpy(); smasks = [np.array(m, dtype=float) for m in prob["masks"]]
    for label, payload, S in [("original", orig, S_ref), ("current", cur, Sf_ref)]:
        A = np.vstack([np.ones(len(tickers)), dur] + smasks)
        lc = LinearConstraint(A, [1.0, 4.0] + [-np.inf] * len(smasks), [1.0, 4.0] + [0.6] * len(smasks))
        fobj = lambda w, S=S: 0.5 * w @ S @ w - 0.5 * mu_ref @ w  # noqa: E731
        grad = lambda w, S=S: S @ w - 0.5 * mu_ref  # noqa: E731
        tc = minimize(fobj, np.full(len(tickers), 0.2), jac=grad, method="trust-constr", constraints=[lc],
                      bounds=Bounds(0, 0.5), options={"gtol": 1e-12, "xtol": 1e-14, "maxiter": 5000})
        w_s = np.array([payload["classical"]["weights"].get(t, 0.0) for t in tickers])
        primal = max(abs(w_s.sum() - 1), abs(dur @ w_s - 4.0), max(0.0, *(m @ w_s - 0.6 for m in smasks)),
                     max(0.0, -w_s.min()), max(0.0, w_s.max() - 0.5))
        excess = fobj(w_s) - fobj(tc.x)
        # One-sided: an interior-point reference stops slightly inside the feasible set, so SLSQP may be
        # (legitimately) lower; it must not be higher, and it must be primal feasible.
        record(f"N20.{label[0]}", f"{label}: SLSQP objective vs trust-constr (one-sided)", fobj(w_s), fobj(tc.x), 1e-7,
               "scipy trust-constr (interior point), same constraints; accept f_SLSQP − f_ref ≤ 1e-7 and primal residual ≤ 1e-6",
               status="PASS" if excess <= 1e-7 and primal <= 1e-6 else "FAIL",
               note=f"f_SLSQP − f_ref = {excess:+.1e}; primal residual {primal:.1e}; max |Δw| = {np.max(np.abs(w_s - tc.x)):.1e}")
        # KKT stationarity at the SLSQP point using active constraints
        g = grad(w_s); cols, lb, ub = [np.ones(len(tickers)), dur], [-np.inf, -np.inf], [np.inf, np.inf]
        for i in range(len(tickers)):
            if w_s[i] < 1e-7:
                cols.append(-np.eye(len(tickers))[i]); lb.append(0); ub.append(np.inf)
            if w_s[i] > 0.5 - 1e-7:
                cols.append(np.eye(len(tickers))[i]); lb.append(0); ub.append(np.inf)
        for m in smasks:
            if m @ w_s > 0.6 - 1e-7:
                cols.append(m); lb.append(0); ub.append(np.inf)
        sol = lsq_linear(np.column_stack(cols), -g, bounds=(lb, ub))
        kkt = float(np.linalg.norm(np.column_stack(cols) @ sol.x + g) / np.linalg.norm(g))
        record(f"N21.{label[0]}", f"{label}: SLSQP KKT stationarity residual (relative)", kkt, 0.0, 1e-6,
               "‖∇f + Σλ∇g_active‖/‖∇f‖ with λ_ineq ≥ 0 (lsq_linear)")

    # backtest
    Roos = ref_simple_returns(prices_oos)
    for label, payload in [("original", orig), ("current", cur)]:
        ts = payload["backtest_timeseries"]
        worst, finals = 0.0, {}
        for strat, key in [("SLSQP", "classical"), ("Exact", "exact"), ("SA", "sa"), ("QAOA", "quantum")]:
            w = np.array([payload[key]["weights"].get(t, 0.0) for t in tickers])
            cm = np.cumprod(1 + Roos @ w) - 1
            got = np.array([row[strat] for row in ts])
            worst = max(worst, float(np.max(np.abs(got - cm))))
            bh = float((prices_oos.iloc[-1].to_numpy() / prices_oos.iloc[0].to_numpy()) @ w - 1)
            finals[strat] = f"{cm[-1]:+.4f} (buy-and-hold {bh:+.4f})"
        record(f"N22.{label[0]}", f"{label}: backtest cumulative returns, all dates & strategies (max |Δ|)", worst, 0.0,
               1e-12, "np.cumprod(1+R_oos·w)−1 (constant-mix)", note=f"{len(ts)} dates; final: {finals}")

    gap = cur["quantum"]["gap_to_optimal_pct"]
    record("N23", "current: QAOA gap_to_optimal_pct", gap, 0.0, 1e-9, "(f(x)−f(x*))/|f(x*)| with identical x")

    # ---------------- D. QAOA circuit ------------------------------------
    from qiskit.circuit.library import QAOAAnsatz
    from qiskit.quantum_info import Statevector
    p = cur["qaoa_config"]["reps"]
    order = [prm.name for prm in QAOAAnsatz(op, reps=p).parameters]
    record("N24", "Qiskit QAOA parameter order", ", ".join(order), "β[0..p-1], γ[0..p-1] (block)", None,
           "QAOAAnsatz(op, reps=3).parameters", status="INFO")
    ip_orig, ip_cur = oqm._linear_ramp_initial_point(p), qm._linear_ramp_initial_point(p)
    mono = lambda v: bool(np.all(np.diff(v[:p]) < 0) and np.all(np.diff(v[p:]) > 0))  # noqa: E731
    record("N25.o", "original: linear-ramp init binds β decreasing, γ increasing",
           f"β={np.round(ip_orig[:p], 4).tolist()}, γ={np.round(ip_orig[p:], 4).tolist()}", "monotone ramps", None,
           "values as bound in Qiskit's block order", status="PASS" if mono(ip_orig) else "FAIL")
    record("N25.c", "current: linear-ramp init binds β decreasing, γ increasing",
           f"β={np.round(ip_cur[:p], 4).tolist()}, γ={np.round(ip_cur[p:], 4).tolist()}", "monotone ramps", None,
           "values as bound in Qiskit's block order", status="PASS" if mono(ip_cur) else "FAIL")

    theta = np.array(cur["quantum"]["optimal_parameters"])
    E_ising = np.real(op.to_matrix(sparse=True).diagonal())
    psi_np = numpy_qaoa_state(E_ising, theta[:p], theta[p:])
    psi_qk = Statevector(QAOAAnsatz(op, reps=p).assign_parameters(theta)).data
    pr_np, pr_qk = np.abs(psi_np) ** 2, np.abs(psi_qk) ** 2
    record("N26", "QAOA state probabilities: NumPy vs Qiskit Statevector (max |Δp|)", float(np.max(np.abs(pr_np - pr_qk))),
           0.0, 1e-10, "independent NumPy simulation of e^{-iβΣX}e^{-iγH_C} layers",
           note=f"Σp = {pr_np.sum():.15f}; ‖ψ‖ − 1 = {abs(np.linalg.norm(psi_np) - 1):.1e}")

    opt_states = np.array([np.array_equal(decoded[k], x_star) for k in range(2 ** n)])
    p_opt_exact = float(pr_np[opt_states].sum())
    p_hat = cur["quantum"]["p_optimal"]
    shots = cur["qaoa_config"]["shots"]
    sigma = math.sqrt(p_opt_exact * (1 - p_opt_exact) / shots)
    record("N27", "current: p_optimal from 1024 Aer shots vs exact |ψ|² at reported θ*", p_hat, p_opt_exact,
           4 * sigma, "binomial: accept |Δ| ≤ 4σ, σ=√(p(1−p)/N)", note=f"σ = {sigma:.4f}, z = {(p_hat - p_opt_exact) / sigma:+.2f}")
    record("N28", "uniform_p_optimal (random guessing)", cur["quantum"]["uniform_p_optimal"], opt_states.mean(), 1e-15,
           f"{int(opt_states.sum())} of {2 ** n} bitstrings decode to x* (slack bits are free)")

    for tag, ip in (("original init", ip_orig), ("intended/current init", ip_cur)):
        pr = np.abs(numpy_qaoa_state(E_ising, ip[:p], ip[p:])) ** 2
        record(f"N29.{tag[:4]}", f"P(x*) of the QAOA state at the {tag}", float(pr[opt_states].sum()), opt_states.mean(),
               None, "NumPy statevector; verified value column = uniform baseline", status="INFO")
    record("N30", "P(x*) of the QAOA state at optimised θ* (exact)", p_opt_exact, opt_states.mean(), None,
           "NumPy statevector; verified value column = uniform baseline", status="INFO",
           note=f"ratio to uniform = {p_opt_exact / opt_states.mean():.2f}×")

    u = float(opt_states.mean())
    rng = np.random.default_rng(12345)
    trials = 200_000
    mc = float((rng.binomial(shots, u, size=trials) > 0).mean())
    analytic = 1 - (1 - u) ** shots
    record("N31", "Null model: P(best-feasible-of-1024 uniform samples = x*)", mc, analytic, 5 * math.sqrt(analytic * (1 - analytic) / trials) + 1e-12,
           f"Monte Carlo ({trials} trials) vs 1−(1−u)^N", note=f"1 − P = {(1 - u) ** shots:.2e}: random sampling 'finds' x* essentially always")
    record("N32", "QAOA: P(x* appears in the final 1024-shot histogram)", 1 - (1 - p_opt_exact) ** shots, analytic, None,
           "1−(1−p)^N with exact p at θ*; verified column = null model", status="INFO")

    # ---------------- E. timing context ----------------------------------
    t0 = time.perf_counter()
    for _ in range(100):
        bits = ((np.arange(2 ** n)[:, None] >> np.arange(n)) & 1).astype(float)
        lin, quad = qubo.objective.linear.to_array(), qubo.objective.quadratic.to_array()
        _ = np.einsum("ki,ij,kj->k", bits, quad, bits) + bits @ lin + qubo.objective.constant
    t_bf = (time.perf_counter() - t0) / 100
    record("N33", "Wall-clock: exhaustive NumPy evaluation of all 512 QUBO energies [s]", cur["execution_time"]["exact_sec"],
           t_bf, None, "vectorised einsum; reported column = Exact solver time, current run", status="INFO",
           note=f"QAOA: {cur['execution_time']['quantum_sec']:.2f}s for {cur['quantum']['cost_function_evals']} "
                f"evaluations × {shots} shots; SA {cur['execution_time']['sa_sec']:.3f}s; original SA (dimod reference) "
                f"{orig['execution_time']['sa_sec']:.2f}s")

    # ---------------- output ----------------------------------------------
    RES.mkdir(parents=True, exist_ok=True)
    (RES / "numerics.json").write_text(json.dumps(CHECKS, indent=2, default=str), encoding="utf-8")
    lines = ["| ID | Claim / metric | Reported | Independently verified | Abs. err | Rel. err | Acceptance | Method | Status | Notes |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for ck in CHECKS:
        lines.append("| " + " | ".join([ck["id"], ck["claim"], fmt(ck["reported"]), fmt(ck["verified"]),
                                         fmt(ck["abs_err"]), fmt(ck["rel_err"]), ck["tolerance"], ck["method"],
                                         f"**{ck['status']}**", ck["note"]]).replace("\n", " ") + " |")
    (RES / "numerics_table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    counts = pd.Series([c["status"] for c in CHECKS]).value_counts().to_dict()
    print("\n".join(lines))
    print("\nstatus counts:", counts)


if __name__ == "__main__":
    main()
