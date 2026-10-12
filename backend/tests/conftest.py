"""Shared fixtures: deterministic synthetic market data (no network access)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import quant_engine as qe  # noqa: E402

TICKERS = ["AAPL", "GS", "JNJ", "JPM", "WMT"]  # all present in the metadata table


def make_prices(tickers=TICKERS, n_days=400, seed=7, start="2021-01-04") -> pd.DataFrame:
    """Correlated geometric random walk with one market factor (fixed seed)."""
    rng = np.random.default_rng(seed)
    k = len(tickers)
    market = rng.normal(0.0004, 0.01, size=n_days)
    beta = np.linspace(0.6, 1.4, k)
    idio = rng.normal(0.0002, 0.012, size=(n_days, k))
    rets = market[:, None] * beta[None, :] + idio
    prices = 100 * np.cumprod(1 + rets, axis=0)
    idx = pd.bdate_range(start, periods=n_days)
    return pd.DataFrame(prices, index=idx, columns=tickers)


@pytest.fixture(scope="session")
def prices() -> pd.DataFrame:
    return make_prices()


@pytest.fixture(scope="session")
def model(prices):
    mu, sigma = qe.calculate_classical_inputs(prices)
    B, F, D = qe.generate_statistical_factor_model(prices, num_factors=3)
    md = qe.get_asset_metadata(list(prices.columns))
    sigma_f = (B.dot(F).dot(B.T) + np.diag(D))
    return dict(mu=mu, sigma=sigma, B=B, F=F, D=D, md=md, sigma_f=sigma_f)


DEFAULT_CFG = dict(budget_resolution=2, q_factor=0.5, target_duration=4.0, max_sector_exposure=0.6,
                   max_asset_exposure=0.5, min_cet1=0.0, min_lcr=0.0)
