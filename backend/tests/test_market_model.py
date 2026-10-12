"""Market inputs, factor model, metadata and data fetching."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import quant_engine as qe
from conftest import make_prices
from reference import simple_returns


def test_moments_match_independent_numpy(prices):
    mu, sigma = qe.calculate_classical_inputs(prices)
    R = simple_returns(prices.to_numpy())
    np.testing.assert_allclose(mu.values, R.mean(axis=0) * 252, rtol=0, atol=1e-14)
    np.testing.assert_allclose(sigma.values, np.cov(R, rowvar=False, ddof=1) * 252, rtol=0, atol=1e-14)


def test_factor_model_with_all_factors_reconstructs_covariance(prices):
    """k = n factors span the whole correlation matrix: BFBᵀ = Σ, so D hits its 1e-6 floor."""
    n = prices.shape[1]
    B, F, D = qe.generate_statistical_factor_model(prices, num_factors=n)
    _, sigma = qe.calculate_classical_inputs(prices)
    recon = B.values @ F.values @ B.values.T
    np.testing.assert_allclose(recon, sigma.values, atol=1e-12)
    np.testing.assert_allclose(D.values, 1e-6)


def test_factor_model_preserves_variances_and_is_positive_definite(model):
    sf = model["sigma_f"].values
    np.testing.assert_allclose(np.diag(sf), np.diag(model["sigma"].values), atol=1e-14)
    assert np.allclose(sf, sf.T)
    assert np.linalg.eigvalsh(sf).min() > 0


def test_factor_model_matches_svd_reference(prices, model):
    """Independent PCA via SVD of standardised returns (the code uses eigh); sign-invariant comparison."""
    R = simple_returns(prices.to_numpy())
    s = R.std(axis=0, ddof=1)
    Z = (R - R.mean(axis=0)) / s
    _, sv, Vt = np.linalg.svd(Z, full_matrices=False)
    lam = sv ** 2 / (len(R) - 1)
    Bm = s[:, None] * Vt.T[:, :3]
    sys_cov = Bm @ np.diag(lam[:3] * 252) @ Bm.T
    full = np.cov(R, rowvar=False, ddof=1) * 252
    ref = sys_cov + np.diag(np.maximum(np.diag(full) - np.diag(sys_cov), 1e-6))
    np.testing.assert_allclose(model["sigma_f"].values, ref, atol=1e-13)


def test_metadata_defaults_are_reported():
    md = qe.get_asset_metadata(["AAPL", "ZZZZ"])
    assert md.attrs["defaulted_tickers"] == ["ZZZZ"]
    assert md.loc["ZZZZ", "Sector"] == "Other"
    assert md.loc["AAPL", "Duration"] == pytest.approx(5.2)


def _fake_download(frame):
    def download(tickers, start, end, progress, auto_adjust):
        assert auto_adjust is True  # adjusted prices requested explicitly, not via a version-dependent default
        return pd.concat({"Close": frame}, axis=1)
    return download


def test_fetch_does_not_backfill_future_prices(monkeypatch):
    """Regression: bfill() used to copy later prices into earlier missing dates (look-ahead)."""
    frame = make_prices(["AAPL", "GS", "WMT"], n_days=30)
    frame.iloc[:5, 1] = np.nan  # GS starts trading on day 6
    monkeypatch.setattr(qe.yf, "download", _fake_download(frame))
    out = qe.fetch_universe_data(["AAPL", "GS", "WMT"], "2021-01-01", "2021-03-01")
    assert out.index[0] == frame.index[5]
    assert not out.isna().any().any()


def test_fetch_raises_on_empty_download(monkeypatch):
    monkeypatch.setattr(qe.yf, "download", lambda *a, **k: pd.DataFrame())
    with pytest.raises(ValueError, match="No price data"):
        qe.fetch_universe_data(["AAPL", "GS"], "2021-01-01", "2021-03-01")
