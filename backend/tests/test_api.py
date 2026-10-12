"""HTTP surface: validation, task lifecycle, CORS (offline: market data is synthetic)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
import quant_engine as qe
from conftest import make_prices

SMALL = dict(tickers=["AAPL", "JPM", "JNJ", "WMT", "GS"], qaoa_reps=1, qaoa_maxiter=5, qaoa_shots=128,
             sa_num_reads=20, sa_num_sweeps=100)


@pytest.fixture
def client(monkeypatch):
    def fake_fetch(tickers, start, end):
        seed = 1 if str(start) < "2023-01-01" else 2  # fixed seeds: in-sample vs out-of-sample window
        return make_prices(sorted(tickers), n_days=300, seed=seed, start=start)
    monkeypatch.setattr(qe, "fetch_universe_data", fake_fetch)
    return TestClient(main.app)


def test_optimize_round_trip(client):
    r = client.post("/api/optimize", json=SMALL)
    assert r.status_code == 200
    task = client.get(f"/api/task/{r.json()['task_id']}").json()  # TestClient runs background tasks inline
    assert task["status"] == "COMPLETED", task
    res = task["result"]
    assert {"classical", "exact", "sa", "quantum", "backtest_timeseries", "qubo", "data"} <= res.keys()
    assert res["qubo"]["num_feasible_portfolios"] == 1
    assert res["classical"]["success"] is True
    assert res["data"]["metadata_defaulted"] == []


@pytest.mark.parametrize("bad", [
    {"q_factor": 1.5},
    {"budget_resolution": 0},
    {"budget_resolution": 50},
    {"tickers": ["AAPL"]},
    {"tickers": ["AAPL", "aapl"]},
    {"end_date": "2019-01-01"},
    {"qaoa_maxiter": 10_000},
])
def test_invalid_requests_are_rejected(client, bad):
    assert client.post("/api/optimize", json={**SMALL, **bad}).status_code == 422


def test_unknown_task_is_404(client):
    assert client.get("/api/task/does-not-exist").status_code == 404


def test_failures_are_reported(client, monkeypatch):
    def boom(*a, **k):
        raise ValueError("no data")
    monkeypatch.setattr(qe, "fetch_universe_data", boom)
    tid = client.post("/api/optimize", json=SMALL).json()["task_id"]
    task = client.get(f"/api/task/{tid}").json()
    assert task == {"status": "FAILED", "error": "ValueError: no data"}


def test_cors_only_allows_configured_origins(client):
    ok = client.get("/api/universe", headers={"Origin": "http://localhost:3000"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    other = client.get("/api/universe", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers
