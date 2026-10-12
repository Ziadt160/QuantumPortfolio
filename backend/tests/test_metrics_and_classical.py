"""portfolio_metrics (hand-calculated cases), SLSQP baseline and backtest."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import Bounds, LinearConstraint, minimize

import quant_engine as qe
from conftest import DEFAULT_CFG

TOY_MU = pd.Series([0.10, 0.20], index=["A", "B"])
TOY_SIGMA = np.array([[0.04, 0.01], [0.01, 0.09]])
TOY_MD = pd.DataFrame({"CET1_Ratio": [0.0, 0.15], "LCR": [0.0, 1.2], "Duration": [5.0, 3.0],
                       "Sector": ["Tech", "Fin"]}, index=["A", "B"])


def toy_metrics(weights, **over):
    kw = dict(q_factor=0.5, target_duration=4.0, max_sector_exposure=1.0, max_asset_exposure=1.0,
              min_cet1=0.0, min_lcr=0.0)
    kw.update(over)
    return qe.portfolio_metrics(weights, TOY_MU, TOY_SIGMA, TOY_MD, **kw)


def test_metrics_hand_calculated():
    m = toy_metrics({"A": 0.5, "B": 0.5})
    # ret = 0.5·0.1 + 0.5·0.2; var = .25·.04 + 2·.25·.01 + .25·.09 = 0.0375
    assert m["expected_return"] == pytest.approx(0.15, abs=1e-15)
    assert m["volatility"] == pytest.approx(math.sqrt(0.0375), abs=1e-15)
    assert m["sharpe_ratio"] == pytest.approx(0.15 / math.sqrt(0.0375), abs=1e-14)
    assert m["portfolio_objective"] == pytest.approx(0.5 * 0.0375 - 0.5 * 0.15, abs=1e-15)
    assert m["feasible"] and m["violations"] == []  # duration = 0.5·5 + 0.5·3 = 4


def test_metrics_reports_asset_cap_violation():
    """Regression: the per-asset cap check had been removed, hiding max(1, ⌊cap·R⌋) clamp violations."""
    m = toy_metrics({"A": 0.5, "B": 0.5}, max_asset_exposure=0.25)
    assert not m["feasible"]
    assert any("asset cap" in v for v in m["violations"])


@pytest.mark.parametrize("over, needle", [
    (dict(max_sector_exposure=0.4), "sector"),
    (dict(target_duration=6.0), "duration"),
    (dict(min_cet1=0.10), "CET1"),
    (dict(min_lcr=0.8), "LCR"),
])
def test_metrics_detects_each_violation(over, needle):
    m = toy_metrics({"A": 0.5, "B": 0.5}, **over)
    assert any(needle in v for v in m["violations"]), m["violations"]


def test_metrics_budget_and_empty():
    assert any("budget" in v for v in toy_metrics({"A": 0.3, "B": 0.3})["violations"])
    empty = toy_metrics({})
    assert empty["violations"] == ["empty"] and not empty["feasible"]


def test_metrics_align_metadata_by_label_not_position():
    """Metadata rows in a different order must give identical results (asymmetric weights expose misalignment)."""
    w = {"A": 0.7, "B": 0.3}
    a = toy_metrics(w, min_lcr=0.8)
    b = qe.portfolio_metrics(w, TOY_MU, TOY_SIGMA, TOY_MD.iloc[::-1], q_factor=0.5,
                             target_duration=4.0, max_sector_exposure=1.0, max_asset_exposure=1.0,
                             min_cet1=0.0, min_lcr=0.8)
    assert a == b
    assert any("LCR 0.360" in v for v in a["violations"])  # 0.3 · 1.2, not 0.7 · 1.2


def _slsqp(model, **over):
    kw = {k: v for k, v in DEFAULT_CFG.items() if k != "budget_resolution"}
    kw.update(over)
    return qe.get_classical_benchmark(mu=model["mu"], Sigma=model["sigma_f"], asset_metadata=model["md"], **kw)


def test_slsqp_matches_independent_solver(model):
    res = _slsqp(model)
    assert res["success"] and res["feasible"]
    tickers = list(model["mu"].index)
    w = np.array([res["weights"].get(t, 0.0) for t in tickers])
    S, mu, md = model["sigma_f"].values, model["mu"].values, model["md"]
    sectors = md["Sector"].unique()
    A = np.vstack([np.ones(len(tickers)), md["Duration"].values] +
                  [(md["Sector"] == s).values.astype(float) for s in sectors])
    lc = LinearConstraint(A, [1, 4] + [-np.inf] * len(sectors), [1, 4] + [0.6] * len(sectors))
    f = lambda x: 0.5 * x @ S @ x - 0.5 * mu @ x  # noqa: E731
    ref = minimize(f, np.full(len(tickers), 0.2), jac=lambda x: S @ x - 0.5 * mu, method="trust-constr",
                   constraints=[lc], bounds=Bounds(0, 0.5), options={"gtol": 1e-12, "xtol": 1e-14, "maxiter": 5000})
    assert f(w) <= f(ref.x) + 1e-7          # SLSQP is not worse than an interior-point reference
    assert abs(res["duration_residual"]) < 1e-6
    np.testing.assert_allclose(w, ref.x, atol=1e-3)


def test_slsqp_failure_is_reported_not_replaced(model):
    """Regression: on failure the solver used to silently return equal weights as if optimal."""
    res = _slsqp(model, target_duration=50.0)  # no portfolio of these assets has duration 50
    assert res["success"] is False
    assert not res["feasible"]
    assert res["solver_message"]


def test_backtest_hand_calculated():
    prices = pd.DataFrame({"A": [100.0, 110.0, 99.0], "B": [50.0, 50.0, 55.0]},
                          index=pd.to_datetime(["2023-01-02", "2023-01-03", "2023-01-04"]))
    out = qe.calculate_backtest({"S": {"weights": {"A": 0.5, "B": 0.5}}}, prices)
    # day 1: 0.5·10% + 0.5·0% = 5%; day 2: 0.5·(−10%) + 0.5·10% = 0% → cumulative 5%, 5%
    assert [r["date"] for r in out] == ["2023-01-03", "2023-01-04"]
    assert out[0]["S"] == pytest.approx(0.05, abs=1e-15)
    assert out[1]["S"] == pytest.approx(0.05, abs=1e-15)
