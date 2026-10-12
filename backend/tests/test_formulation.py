"""QuadraticProgram construction, QUBO conversion and Ising mapping."""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from qiskit_optimization import QuadraticProgram
from qiskit_optimization.converters import QuadraticProgramToQubo

import quantum_engine as qm
from conftest import DEFAULT_CFG
from reference import bits_of, bounded_coeffs, portfolio_objective


def build(model, **over):
    cfg = {**DEFAULT_CFG, **over}
    return qm._build_quadratic_program(mu=model["mu"], B=model["B"], F=model["F"], D=model["D"],
                                       asset_metadata=model["md"], **cfg), cfg


def grid(qp):
    ubs = [int(v.upperbound) for v in qp.variables]
    return [np.array(x, dtype=float) for x in itertools.product(*(range(u + 1) for u in ubs))]


def test_qiskit_sums_symmetric_quadratic_entries():
    """The formulation passes both (i,j) and (j,i); Qiskit must add them (xᵀQx semantics)."""
    qp = QuadraticProgram()
    qp.binary_var("a"); qp.binary_var("b")
    qp.minimize(quadratic={("a", "b"): 1.0, ("b", "a"): 2.0, ("a", "a"): 3.0})
    assert qp.objective.evaluate([1, 1]) == pytest.approx(6.0)


def test_objective_matches_reference_on_whole_grid(model):
    qp, cfg = build(model)
    R, mu, S = cfg["budget_resolution"], model["mu"].values, model["sigma_f"].values
    for x in grid(qp):
        assert qp.objective.evaluate(x) == pytest.approx(portfolio_objective(x / R, mu, S, 0.5), abs=1e-13)


def test_vacuous_basel_minimum_adds_no_penalty(model):
    """Regression: min_cet1 = min_lcr = 0 used to add λ(c·w)² + λ(l·w)², penalising every bank holding."""
    qp, _ = build(model)
    md_no_banks = model["md"].assign(CET1_Ratio=0.0, LCR=0.0)
    qp_ref = qm._build_quadratic_program(mu=model["mu"], B=model["B"], F=model["F"], D=model["D"],
                                         asset_metadata=md_no_banks, **DEFAULT_CFG)
    for x in grid(qp):
        assert qp.objective.evaluate(x) == pytest.approx(qp_ref.objective.evaluate(x), abs=1e-15)


def test_binding_basel_minimum_adds_documented_penalty(model):
    qp, cfg = build(model, min_cet1=0.05, min_lcr=0.5)
    R, mu, S = cfg["budget_resolution"], model["mu"].values, model["sigma_f"].values
    c, l = model["md"]["CET1_Ratio"].values, model["md"]["LCR"].values
    for x in grid(qp):
        w = x / R
        ref = portfolio_objective(w, mu, S, 0.5) + 10 * ((c @ w - 0.05) ** 2 - 0.05 ** 2) \
            + 10 * ((l @ w - 0.5) ** 2 - 0.5 ** 2)
        assert qp.objective.evaluate(x) == pytest.approx(ref, abs=1e-12)


def test_duration_target_is_rounded_on_slice_scale(model):
    """Regression: rhs was round(T)·R, so T=4.5 silently became 4.0 (banker's rounding)."""
    qp, _ = build(model, target_duration=4.5)
    con = qp.get_linear_constraint("duration")
    assert con.rhs == 9                                       # round(4.5 · 2)
    assert con.linear.to_dict(use_name=True)["GS"] == 3       # 2.6 → 3
    assert qm._round_half_up(2.5) == 3 and qm._round_half_up(4.5) == 5


def test_floor_slices_is_robust_to_float_products():
    assert qm._floor_slices(0.29, 100) == 29                  # int(0.29*100) == 28
    assert qm._floor_slices(0.6, 5) == 3


def test_asset_cap_clamp_is_visible(model):
    qp, _ = build(model, max_asset_exposure=0.25)             # ⌊0.25·2⌋ = 0 → clamped to 1 slice = 50 %
    assert all(v.upperbound == 1 for v in qp.variables)
    summary = qm.discretisation_summary(qp, 2)
    assert summary["effective_max_asset_weight"] == 0.5


def test_feasible_count_matches_hand_enumeration(model):
    qp, _ = build(model)
    summary = qm.discretisation_summary(qp, 2)
    durations = {t: qm._round_half_up(d) for t, d in model["md"]["Duration"].items()}
    tickers = list(model["mu"].index)
    feasible = [x for x in itertools.product(range(2), repeat=len(tickers))
                if sum(x) == 2 and sum(durations[t] * xi for t, xi in zip(tickers, x)) == 8
                and x[tickers.index("GS")] + x[tickers.index("JPM")] <= 1]
    assert summary["num_feasible_portfolios"] == len(feasible) == 1
    assert summary["effective_target_duration"] == 4.0


def _qubo_reference_energies(qp, conv, qubo):
    """Objective + P·Σ residual², decoded with an independent bounded-coefficient encoding."""
    names = [v.name for v in qubo.variables]
    groups: dict[str, list[int]] = {}
    for i, nm in enumerate(names):
        groups.setdefault(nm.rsplit("@", 1)[0], []).append(i)
    slack_ub = {f"{c.name}@int_slack": int(c.rhs) for c in qp.linear_constraints if c.sense.name == "LE"}
    var_ub = {v.name: int(v.upperbound) for v in qp.variables}
    n = len(names)
    energies, decoded = np.empty(2 ** n), []
    for k in range(2 ** n):
        b = bits_of(k, n)
        val = {g: sum(cf * b[i] for cf, i in zip(bounded_coeffs(var_ub.get(g, slack_ub.get(g))), idx))
               for g, idx in groups.items()}
        x = np.array([val[v.name] for v in qp.variables])
        resid = 0.0
        for c in qp.linear_constraints:
            lhs = c.evaluate(x) + (val[f"{c.name}@int_slack"] if c.sense.name == "LE" else 0)
            resid += (lhs - c.rhs) ** 2
        energies[k] = qp.objective.evaluate(x) + conv.penalty * resid
        decoded.append(x)
    return energies, decoded


def test_qubo_and_ising_match_reference_for_every_bitstring(model):
    qp, _ = build(model)
    conv = QuadraticProgramToQubo()
    qubo = conv.convert(qp)
    E_ref, decoded = _qubo_reference_energies(qp, conv, qubo)
    n = qubo.get_num_binary_vars()
    E_code = np.array([qubo.objective.evaluate(bits_of(k, n)) for k in range(2 ** n)])
    np.testing.assert_allclose(E_code, E_ref, atol=1e-10)
    for k in range(2 ** n):  # converter decoding agrees with the reference decoding
        np.testing.assert_array_equal(np.asarray(conv.interpret(bits_of(k, n))), decoded[k])
    op, offset = qubo.to_ising()
    assert all(set(p) <= {"I", "Z"} for p in op.paulis.to_labels())          # diagonal
    assert np.allclose(op.coeffs.imag, 0)                                     # Hermitian
    diag = np.real(op.to_matrix(sparse=True).diagonal()) + offset
    np.testing.assert_allclose(diag, E_ref, atol=1e-10)                       # little-endian ordering


def test_qubo_ground_state_is_constrained_optimum(model):
    qp, _ = build(model, target_duration=4.5)  # 2 feasible portfolios → objective decides
    conv = QuadraticProgramToQubo()
    qubo = conv.convert(qp)
    E_ref, decoded = _qubo_reference_energies(qp, conv, qubo)
    best = min((x for x in grid(qp) if qp.is_feasible(x)), key=qp.objective.evaluate)
    np.testing.assert_array_equal(decoded[int(np.argmin(E_ref))], best)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(seed=st.integers(0, 10_000), R=st.integers(1, 3), q=st.floats(0.0, 1.0),
       n_assets=st.integers(2, 3))
def test_property_random_instances(seed, R, q, n_assets):
    """For random small instances: Ising diagonal = QUBO energies, and the QUBO argmin is the best feasible point."""
    rng = np.random.default_rng(seed)
    tickers = [f"T{i}" for i in range(n_assets)]
    mu = pd.Series(rng.normal(0.1, 0.1, n_assets), index=tickers)
    Bm = pd.DataFrame(rng.normal(0, 0.2, (n_assets, 1)), index=tickers, columns=["f"])
    F = pd.DataFrame([[1.0]], index=["f"], columns=["f"])
    D = pd.Series(rng.uniform(0.01, 0.05, n_assets), index=tickers)
    md = pd.DataFrame({"CET1_Ratio": 0.0, "LCR": 0.0, "Duration": rng.integers(1, 6, n_assets).astype(float),
                       "Sector": rng.choice(["S1", "S2"], n_assets)}, index=tickers)
    T = float(rng.integers(1, 6))
    qp = qm._build_quadratic_program(mu=mu, B=Bm, F=F, D=D, asset_metadata=md, budget_resolution=R,
                                     q_factor=q, target_duration=T, max_sector_exposure=1.0,
                                     max_asset_exposure=1.0, min_cet1=0.0, min_lcr=0.0)
    conv = QuadraticProgramToQubo()
    qubo = conv.convert(qp)
    n = qubo.get_num_binary_vars()
    E = np.array([qubo.objective.evaluate(bits_of(k, n)) for k in range(2 ** n)])
    op, offset = qubo.to_ising()
    np.testing.assert_allclose(np.real(op.to_matrix(sparse=True).diagonal()) + offset, E, atol=1e-9)
    feasible = [x for x in grid(qp) if qp.is_feasible(x)]
    if feasible:
        best = min(qp.objective.evaluate(x) for x in feasible)
        x_qubo = np.asarray(conv.interpret(bits_of(int(np.argmin(E)), n)), dtype=float)
        assert qp.is_feasible(x_qubo)
        assert qp.objective.evaluate(x_qubo) == pytest.approx(best, abs=1e-9)
