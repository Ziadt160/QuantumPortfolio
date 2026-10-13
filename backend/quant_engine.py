"""
Classical optimization engine + market data + benchmarks for the
QuantumPortfolio demo.

What lives here:
  - Market data + annualised moments + PCA factor model
  - Asset metadata (stylised duration / sector / bank-ratio table)
  - SLSQP        : continuous-weight baseline (scipy)
  - portfolio_metrics : the single metric/feasibility evaluator used for
                        every solver, so reported numbers are comparable
  - Backtest    : out-of-sample equity curve for all strategies

The discrete solvers (exact, simulated annealing, QAOA) live in
quantum_engine.py.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Absolute tolerance used when checking budget / sector / asset caps /
# CET1 / LCR on reported weights.
CONSTRAINT_TOL = 1e-3
# The discrete encoding rounds every asset duration to whole years, so its
# portfolio duration can only approximate the target. A solution is reported
# as duration-feasible if it is within this fraction of the target.
DURATION_TOLERANCE_FRAC = 0.25


# =========================================================================
# Market data
# =========================================================================
def fetch_universe_data(tickers: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    """Historical dividend/split-adjusted close prices (one column per ticker)."""
    data = yf.download(tickers, start=start_date, end=end_date, progress=False, auto_adjust=True)
    if data is None or data.empty:
        raise ValueError(f"No price data returned for {tickers} between {start_date} and {end_date}")
    if isinstance(data.columns, pd.MultiIndex):
        prices = data["Close"]
    else:
        prices = pd.DataFrame(data["Close"], columns=tickers)
    prices = prices.dropna(axis=1, thresh=len(prices) // 2)
    dropped = sorted(set(tickers) - set(prices.columns))
    if dropped:
        logger.warning("Dropping tickers with insufficient price history: %s", dropped)
    # Forward-fill gaps, then keep only dates where every remaining ticker has
    # a price. (Back-filling would copy future prices into the past.)
    prices = prices.ffill().dropna()
    if prices.shape[1] < 2 or len(prices) < 3:
        raise ValueError(f"Not enough usable price history for {tickers} ({prices.shape})")
    return prices


def calculate_classical_inputs(prices: pd.DataFrame):
    """Annualised expected returns and covariance matrix."""
    returns = prices.pct_change().dropna()
    mu = returns.mean() * 252
    Sigma = returns.cov() * 252
    return mu, Sigma


def generate_statistical_factor_model(prices: pd.DataFrame, num_factors: int = 3):
    """PCA factor model: returns (B, F, D) so that Sigma ≈ B F Bᵀ + diag(D)."""
    returns = prices.pct_change().dropna()
    returns_std = returns.std()
    returns_norm = (returns - returns.mean()) / returns_std
    cov_norm = returns_norm.cov()

    eigenvalues, eigenvectors = np.linalg.eigh(cov_norm)
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]

    factor_loadings = eigenvectors[:, :num_factors]
    B_matrix = factor_loadings * returns_std.values[:, np.newaxis]
    B = pd.DataFrame(
        B_matrix,
        index=returns.columns,
        columns=[f"Factor_{i+1}" for i in range(num_factors)],
    )

    F_matrix = np.diag(eigenvalues[:num_factors]) * 252
    F = pd.DataFrame(F_matrix, index=B.columns, columns=B.columns)

    Sigma = returns.cov() * 252
    systematic_risk = B.dot(F).dot(B.T)
    idiosyncratic_var = np.maximum(np.diag(Sigma) - np.diag(systematic_risk), 1e-6)
    D = pd.Series(idiosyncratic_var, index=returns.columns)
    return B, F, D


# =========================================================================
# Asset metadata — real-world approximations
# =========================================================================
# Public-source approximations as of FY24 filings. Values are coarse but
# realistic enough that the Basel constraints actually bind on a mixed
# universe (financials + non-financials). Non-banks get a notional CET1/LCR
# of 0 so the >= constraints push the optimizer toward a minimum bank
# allocation.
#
# Caveats: CET1 and LCR are bank-level regulatory
# ratios. Basel III does not require an *investor's* portfolio-weighted
# average of investee banks' ratios to exceed a floor, so the CET1/LCR
# constraints here are a stylised device, not regulation. "Duration" for an
# equity is likewise a modelling assumption. The values are hand-entered and
# not traced to specific filings.
_METADATA_DB: Dict[str, Dict] = {
    # --- Mega-cap tech / non-financial ---
    "AAPL":  {"CET1_Ratio": 0.0,   "LCR": 0.0,  "Duration": 5.2, "Sector": "Technology"},
    "MSFT":  {"CET1_Ratio": 0.0,   "LCR": 0.0,  "Duration": 4.8, "Sector": "Technology"},
    "GOOGL": {"CET1_Ratio": 0.0,   "LCR": 0.0,  "Duration": 4.5, "Sector": "Technology"},
    "AMZN":  {"CET1_Ratio": 0.0,   "LCR": 0.0,  "Duration": 6.1, "Sector": "Consumer"},
    "META":  {"CET1_Ratio": 0.0,   "LCR": 0.0,  "Duration": 4.2, "Sector": "Technology"},
    "TSLA":  {"CET1_Ratio": 0.0,   "LCR": 0.0,  "Duration": 8.5, "Sector": "Consumer"},
    "NVDA":  {"CET1_Ratio": 0.0,   "LCR": 0.0,  "Duration": 5.5, "Sector": "Technology"},
    "JNJ":   {"CET1_Ratio": 0.0,   "LCR": 0.0,  "Duration": 7.2, "Sector": "Healthcare"},
    "WMT":   {"CET1_Ratio": 0.0,   "LCR": 0.0,  "Duration": 4.1, "Sector": "Consumer"},
    "PG":    {"CET1_Ratio": 0.0,   "LCR": 0.0,  "Duration": 5.8, "Sector": "Consumer"},
    "V":     {"CET1_Ratio": 0.0,   "LCR": 0.0,  "Duration": 3.8, "Sector": "Financials"},
    # --- US G-SIBs (real CET1 / LCR ratios, public FY24 filings) ---
    "JPM":   {"CET1_Ratio": 0.151, "LCR": 1.13, "Duration": 2.1, "Sector": "Financials"},
    "BAC":   {"CET1_Ratio": 0.117, "LCR": 1.16, "Duration": 2.3, "Sector": "Financials"},
    "C":     {"CET1_Ratio": 0.137, "LCR": 1.17, "Duration": 2.4, "Sector": "Financials"},
    "WFC":   {"CET1_Ratio": 0.114, "LCR": 1.25, "Duration": 2.2, "Sector": "Financials"},
    "GS":    {"CET1_Ratio": 0.150, "LCR": 1.30, "Duration": 2.6, "Sector": "Financials"},
    "MS":    {"CET1_Ratio": 0.155, "LCR": 1.34, "Duration": 2.5, "Sector": "Financials"},
}


_DEFAULT_METADATA = {"CET1_Ratio": 0.0, "LCR": 0.0, "Duration": 5.0, "Sector": "Other"}


def get_asset_metadata(tickers: list[str]) -> pd.DataFrame:
    """Return the (stylised, see _METADATA_DB) Basel-III metadata for each ticker.

    Tickers missing from the table get placeholder values; they are logged and
    listed in ``df.attrs["defaulted_tickers"]`` so callers can surface them.
    """
    data = []
    defaulted = []
    for t in tickers:
        if t in _METADATA_DB:
            data.append(_METADATA_DB[t])
        else:
            data.append(dict(_DEFAULT_METADATA))
            defaulted.append(t)
    if defaulted:
        logger.warning("No metadata for %s; using placeholder values %s", defaulted, _DEFAULT_METADATA)
    df = pd.DataFrame(data, index=tickers)
    df.attrs["defaulted_tickers"] = defaulted
    return df


# =========================================================================
# Shared portfolio evaluation (used for every solver)
# =========================================================================
def portfolio_metrics(
    weights: Dict[str, float],
    mu: pd.Series,
    Sigma: np.ndarray | pd.DataFrame,
    asset_metadata: pd.DataFrame,
    q_factor: float,
    target_duration: float,
    max_sector_exposure: float,
    max_asset_exposure: float,
    min_cet1: float,
    min_lcr: float,
) -> Dict[str, Any]:
    """
    Evaluate a weight vector on the *stated* (continuous) problem.

    portfolio_objective = q·wᵀΣw − (1−q)·μᵀw, with no penalty terms, so it is
    comparable across all solvers. ``violations`` lists every stated
    constraint the weights break (budget, per-asset cap, sector cap, duration
    within ±DURATION_TOLERANCE_FRAC, CET1, LCR).

    Sharpe ratio is reported with a zero risk-free rate.
    """
    base = {
        "weights": dict(weights),
        "expected_return": 0.0,
        "volatility": 0.0,
        "sharpe_ratio": 0.0,
        "portfolio_objective": 0.0,
        "budget_sum": 0.0,
        "feasible": False,
        "violations": ["empty"],
    }
    if not weights:
        return base

    # Align everything on mu's ticker order (label-based, not positional).
    md = asset_metadata.reindex(mu.index)
    Sigma = np.asarray(Sigma.loc[mu.index, mu.index] if isinstance(Sigma, pd.DataFrame) else Sigma)
    w = np.array([float(weights.get(t, 0.0)) for t in mu.index])

    budget_sum = float(w.sum())
    ret = float(np.dot(w, mu.values))
    vol2 = float(w @ Sigma @ w)
    vol = float(np.sqrt(max(vol2, 0.0)))
    obj = q_factor * vol2 - (1 - q_factor) * ret

    violations: list[str] = []
    if abs(budget_sum - 1.0) > CONSTRAINT_TOL:
        violations.append(f"budget {budget_sum:.3f} ≠ 1.0")
    over = [f"{t} {wi:.2f}" for t, wi in zip(mu.index, w) if wi > max_asset_exposure + CONSTRAINT_TOL]
    if over:
        violations.append(f"asset cap {max_asset_exposure:.2f} exceeded: {', '.join(over)}")
    if "Sector" in md.columns:
        for sector in md["Sector"].unique():
            mask = (md["Sector"] == sector).values.astype(float)
            sec_w = float(np.dot(w, mask))
            if sec_w > max_sector_exposure + CONSTRAINT_TOL:
                violations.append(f"sector {sector}: {sec_w:.2f} > {max_sector_exposure:.2f}")
    if "Duration" in md.columns:
        dur = float(np.dot(w, md["Duration"].values))
        if abs(dur - target_duration) > DURATION_TOLERANCE_FRAC * max(target_duration, 1.0):
            violations.append(f"duration {dur:.2f} ≠ {target_duration:.2f}±{DURATION_TOLERANCE_FRAC:.0%}")
    if "CET1_Ratio" in md.columns and md["CET1_Ratio"].sum() > 0:
        c = float(np.dot(w, md["CET1_Ratio"].values))
        if c < min_cet1 - CONSTRAINT_TOL:
            violations.append(f"CET1 {c:.3f} < {min_cet1:.3f}")
    if "LCR" in md.columns and md["LCR"].sum() > 0:
        lcr_w = float(np.dot(w, md["LCR"].values))
        if lcr_w < min_lcr - CONSTRAINT_TOL:
            violations.append(f"LCR {lcr_w:.3f} < {min_lcr:.3f}")

    return {
        "weights": dict(weights),
        "expected_return": ret,
        "volatility": vol,
        "sharpe_ratio": ret / vol if vol > 0 else 0.0,
        "portfolio_objective": obj,
        "budget_sum": budget_sum,
        "feasible": not violations,
        "violations": violations,
    }


# =========================================================================
# Classical baseline #1 — SLSQP (continuous relaxation)
# =========================================================================
def get_classical_benchmark(
    mu: pd.Series,
    Sigma: pd.DataFrame,
    asset_metadata: pd.DataFrame | None = None,
    q_factor: float = 0.5,
    target_duration: float = 4.0,
    max_sector_exposure: float = 0.40,
    max_asset_exposure: float = 0.25,
    min_cet1: float = 0.12,
    min_lcr: float = 1.00,
):
    """
    Continuous-weight SLSQP solution of

        min_w  q·wᵀΣw − (1−q)·μᵀw
        s.t.   Σw = 1, 0 ≤ w ≤ max_asset, w·duration = target,
               sector sums ≤ max_sector, w·CET1 ≥ min_cet1, w·LCR ≥ min_lcr

    using exact (unrounded) durations and hard CET1/LCR inequalities. This is
    convex (Σ PSD, linear constraints), so a converged SLSQP solution is the
    global optimum. If SLSQP does not converge, its last iterate is returned
    with ``success=False`` instead of being replaced by another portfolio.
    """
    from scipy.optimize import minimize

    n = len(mu)
    mu_v = np.asarray(mu.values if isinstance(mu, pd.Series) else mu, dtype=float)
    Sigma_v = np.asarray(Sigma.loc[mu.index, mu.index] if isinstance(Sigma, pd.DataFrame) else Sigma, dtype=float)

    def objective(w):
        return q_factor * float(w @ Sigma_v @ w) - (1 - q_factor) * float(w @ mu_v)

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bounds = tuple((0.0, max_asset_exposure) for _ in range(n))

    if asset_metadata is not None:
        asset_metadata = asset_metadata.reindex(mu.index)
        if "Duration" in asset_metadata.columns:
            durations = asset_metadata["Duration"].values
            constraints.append({"type": "eq", "fun": lambda w: np.dot(w, durations) - target_duration})
        if "Sector" in asset_metadata.columns:
            for sector in asset_metadata["Sector"].unique():
                mask = (asset_metadata["Sector"] == sector).values.astype(float)
                constraints.append({"type": "ineq", "fun": lambda w, m=mask: max_sector_exposure - np.dot(w, m)})
        if "CET1_Ratio" in asset_metadata.columns and asset_metadata["CET1_Ratio"].sum() > 0:
            cet1 = asset_metadata["CET1_Ratio"].values
            constraints.append({"type": "ineq", "fun": lambda w: np.dot(w, cet1) - min_cet1})
        if "LCR" in asset_metadata.columns and asset_metadata["LCR"].sum() > 0:
            lcr = asset_metadata["LCR"].values
            constraints.append({"type": "ineq", "fun": lambda w: np.dot(w, lcr) - min_lcr})

    w0 = np.ones(n) / n
    res = minimize(objective, w0, method="SLSQP", bounds=bounds, constraints=constraints, options={"maxiter": 1000})
    if not res.success:
        logger.warning("SLSQP did not converge: %s", res.message)

    # Remove round-off negatives only; no renormalisation, so the reported
    # weights are exactly what the solver returned (budget is checked below).
    w_opt = np.clip(res.x, 0.0, None)
    weights = {t: float(w_opt[i]) for i, t in enumerate(mu.index) if w_opt[i] > 1e-6}

    md = asset_metadata if asset_metadata is not None else pd.DataFrame(index=mu.index)
    out = portfolio_metrics(
        weights=weights, mu=mu, Sigma=Sigma_v, asset_metadata=md,
        q_factor=q_factor, target_duration=target_duration,
        max_sector_exposure=max_sector_exposure, max_asset_exposure=max_asset_exposure,
        min_cet1=min_cet1, min_lcr=min_lcr,
    )
    if "Duration" in md.columns:
        # SLSQP enforces the duration *equality*; report the exact residual too.
        out["duration_residual"] = float(np.dot(w_opt, md["Duration"].values) - target_duration)
    out["success"] = bool(res.success)
    out["solver_message"] = str(res.message)
    return out


# =========================================================================
# Out-of-sample backtest
# =========================================================================
def calculate_backtest(strategies: dict[str, dict], prices_oos: pd.DataFrame) -> list[dict]:
    """
    Cumulative-return time series for an arbitrary set of strategies.

    `strategies` is a mapping {label: {"weights": {ticker: weight, ...}}}.
    Returns a list of {date, label1, label2, ...} records for recharts.

    Portfolio return on day t is Σ_i w_i r_{i,t}, i.e. weights are reset to
    their targets every day (constant-mix), with no transaction costs. The
    first out-of-sample day only provides a starting price, so the series
    begins on the second trading day.
    """
    daily_returns = prices_oos.pct_change().dropna()
    tickers = list(daily_returns.columns)

    series: dict[str, pd.Series] = {}
    for label, payload in strategies.items():
        w = np.array([payload.get("weights", {}).get(t, 0.0) for t in tickers])
        daily = daily_returns.dot(w)
        series[label] = (1 + daily).cumprod() - 1

    if not series:
        return []
    index = next(iter(series.values())).index
    out = []
    for d in index:
        row = {"date": d.strftime("%Y-%m-%d")}
        for label, s in series.items():
            row[label] = float(s.loc[d])
        out.append(row)
    return out
