"""Wall-clock budget for the default dashboard request (synthetic data, no network)."""
from __future__ import annotations

import time

import pytest

import quantum_engine as qm
from conftest import DEFAULT_CFG


@pytest.mark.slow
def test_default_request_runs_within_budget(model):
    t0 = time.perf_counter()
    res = qm.optimize_portfolio_qaoa(mu=model["mu"], B=model["B"], F=model["F"], D=model["D"],
                                     asset_metadata=model["md"], **DEFAULT_CFG)
    elapsed = time.perf_counter() - t0
    assert res["qubo"]["num_qubits"] == 9
    assert res["timings"]["exact_sec"] < 5
    assert res["timings"]["sa_sec"] < 5
    # Generous ceiling (≈7 s on the audit machine) so slower CI machines do not flake.
    assert elapsed < 120, f"default discrete solve took {elapsed:.1f}s"
