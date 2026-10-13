"""
Run the backend pipeline (`main.run_optimization_task_logic`) offline on the
cached Yahoo Finance snapshot in `audit/data/`, and dump the full API payload
as JSON.

The only thing patched is `quant_engine.fetch_universe_data`, which is replaced
by a reader of the frozen CSV snapshot so that runs are reproducible (Yahoo
adjusted prices are revised retroactively, so live fetches are not).

Usage (from the repository root):
    python audit/run_pipeline_snapshot.py --out audit/results/pipeline_default.json
    python audit/run_pipeline_snapshot.py --request '{"budget_resolution": 4}' --out ...
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "audit" / "data"
BACKEND = ROOT / "backend"

# The request the dashboard sends with its initial slider values
# (frontend/src/app/Dashboard.tsx). qaoa_* / sa_* fields are not sent by the
# dashboard, so the server-side defaults of OptimizationRequest apply.
DASHBOARD_DEFAULT_REQUEST = {
    "tickers": ["AAPL", "JPM", "JNJ", "WMT", "GS"],
    "start_date": "2020-01-01",
    "end_date": "2023-01-01",
    "backtest_start_date": "2023-01-01",
    "backtest_end_date": "2024-01-01",
    "budget_resolution": 2,
    "q_factor": 0.5,
    "target_duration": 4.0,
    "max_sector_exposure": 0.60,
    "max_asset_exposure": 0.50,
    "min_cet1": 0.0,
    "min_lcr": 0.0,
}


def load_snapshot() -> dict[str, pd.DataFrame]:
    out = {}
    for key, fname in (("insample", "prices_insample.csv"), ("oos", "prices_oos.csv")):
        df = pd.read_csv(DATA / fname, index_col=0, parse_dates=True)
        df.columns.name = "Ticker"
        out[key] = df
    return out


def snapshot_fetch(tickers, start_date, end_date):
    """Drop-in replacement for quant_engine.fetch_universe_data backed by the CSV snapshot."""
    snap = load_snapshot()
    start_date, end_date = str(start_date), str(end_date)
    frame = snap["insample"] if start_date < "2023-01-01" else snap["oos"]
    cols = [c for c in frame.columns if c in set(tickers)]
    return frame.loc[(frame.index >= start_date) & (frame.index < end_date), cols].copy()


def import_backend():
    """Import (quant_engine, quantum_engine, main) from backend/ with the snapshot data source."""
    sys.path.insert(0, str(BACKEND))
    qe = importlib.import_module("quant_engine")
    qm = importlib.import_module("quantum_engine")
    mn = importlib.import_module("main")
    qe.fetch_universe_data = snapshot_fetch
    return qe, qm, mn


def _json_default(o):
    try:
        return float(o)
    except (TypeError, ValueError):
        return str(o)


def main_cli() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", default="{}", help="JSON overrides of the default request")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    _, _, mn = import_backend()
    req = mn.OptimizationRequest(**{**DASHBOARD_DEFAULT_REQUEST, **json.loads(args.request)})
    payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    t0 = time.time()
    result = mn.run_optimization_task_logic(payload)
    result["_audit"] = {"request": payload, "wall_sec": time.time() - t0,
                        "python": sys.version.split()[0]}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, default=_json_default), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("classical", "exact", "sa", "quantum", "qubo", "execution_time")},
                     indent=2, default=_json_default))


if __name__ == "__main__":
    main_cli()
