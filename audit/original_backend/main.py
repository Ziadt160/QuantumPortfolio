"""FastAPI surface for the QuantumPortfolio demo."""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import quant_engine
import quantum_engine

app = FastAPI(title="Quantum Portfolio Optimization API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TASKS: Dict[str, Dict[str, Any]] = {}


class OptimizationRequest(BaseModel):
    tickers: list[str]
    start_date: str = "2020-01-01"
    end_date: str = "2023-01-01"
    backtest_start_date: str = "2023-01-01"
    backtest_end_date: str = "2024-01-01"
    budget_resolution: int = 2
    q_factor: float = 0.5
    target_duration: float = 4.0
    max_sector_exposure: float = 0.60
    max_asset_exposure: float = 0.50
    min_cet1: float = 0.0
    min_lcr: float = 0.0
    qaoa_reps: int = 3
    qaoa_cvar_alpha: float = 0.25
    qaoa_maxiter: int = 80
    sa_num_reads: int = 200
    sa_num_sweeps: int = 1000


def run_optimization_task_logic(req: dict) -> dict:
    start = time.time()
    tickers = req["tickers"]

    # ----- Market data + factor model ----------------------------------
    prices = quant_engine.fetch_universe_data(tickers, req["start_date"], req["end_date"])
    mu, Sigma = quant_engine.calculate_classical_inputs(prices)
    B, F, D = quant_engine.generate_statistical_factor_model(prices, num_factors=3)
    asset_metadata = quant_engine.get_asset_metadata(list(prices.columns))

    # ----- Classical SLSQP (continuous baseline) -----------------------
    t0 = time.time()
    classical = quant_engine.get_classical_benchmark(
        mu=mu,
        Sigma=Sigma,
        asset_metadata=asset_metadata,
        q_factor=req["q_factor"],
        target_duration=req["target_duration"],
        max_sector_exposure=req["max_sector_exposure"],
        max_asset_exposure=req["max_asset_exposure"],
        min_cet1=req["min_cet1"],
        min_lcr=req["min_lcr"],
    )
    classical_time = time.time() - t0

    # ----- Discrete QUBO solvers: Exact, SA, CVaR-QAOA -----------------
    quantum_results = quantum_engine.optimize_portfolio_qaoa(
        mu=mu,
        B=B,
        F=F,
        D=D,
        asset_metadata=asset_metadata,
        budget_resolution=req["budget_resolution"],
        q_factor=req["q_factor"],
        target_duration=req["target_duration"],
        max_sector_exposure=req["max_sector_exposure"],
        max_asset_exposure=req["max_asset_exposure"],
        min_cet1=req["min_cet1"],
        min_lcr=req["min_lcr"],
        qaoa_reps=req["qaoa_reps"],
        qaoa_cvar_alpha=req["qaoa_cvar_alpha"],
        qaoa_maxiter=req["qaoa_maxiter"],
        sa_num_reads=req["sa_num_reads"],
        sa_num_sweeps=req["sa_num_sweeps"],
    )

    # ----- Out-of-sample backtest --------------------------------------
    prices_oos = quant_engine.fetch_universe_data(
        list(prices.columns),
        req["backtest_start_date"],
        req["backtest_end_date"],
    )
    strategies = {"SLSQP": classical, "SA": quantum_results["sa"], "QAOA": quantum_results["qaoa"]}
    if quantum_results["exact"] is not None:
        strategies["Exact"] = quantum_results["exact"]
    backtest_timeseries = quant_engine.calculate_backtest(strategies, prices_oos)

    return {
        "classical": classical,
        "exact": quantum_results["exact"],
        "sa": quantum_results["sa"],
        "quantum": quantum_results["qaoa"],
        "backtest_timeseries": backtest_timeseries,
        "qubo": quantum_results["qubo"],
        "qaoa_config": quantum_results["qaoa_config"],
        "execution_time": {
            "classical_sec": classical_time,
            "exact_sec": quantum_results["timings"]["exact_sec"],
            "sa_sec": quantum_results["timings"]["sa_sec"],
            "quantum_sec": quantum_results["timings"]["qaoa_sec"],
            "total_sec": time.time() - start,
        },
    }


@app.post("/api/optimize")
async def optimize(req: OptimizationRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    TASKS[task_id] = {"status": "PENDING"}

    def process_task(tid: str, payload: dict):
        try:
            TASKS[tid] = {"status": "COMPLETED", "result": run_optimization_task_logic(payload)}
        except Exception as exc:  # pragma: no cover — surface to client
            TASKS[tid] = {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}

    background_tasks.add_task(process_task, task_id, req.dict())
    return {"task_id": task_id}


@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in TASKS:
        return {"status": "FAILED", "error": "Task not found"}
    return TASKS[task_id]


@app.get("/api/universe")
async def get_universe():
    """Tickers known to the metadata DB — mixed financials + non-financials so Basel constraints bind."""
    # Toy universe — 5 tickers across 4 sectors, 2 of them banks.
    # At budget_resolution=2 → ~5 binary vars + slacks → 8-10 qubits total.
    # Whole pipeline (SLSQP + Exact + SA + CVaR-QAOA + backtest) runs in <10 s.
    return {
        "tickers": ["AAPL", "JPM", "JNJ", "WMT", "GS"]
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
