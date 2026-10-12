"""FastAPI surface for the QuantumPortfolio demo."""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import date
from typing import Any, Dict

import numpy as np
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator

import quant_engine
import quantum_engine

logger = logging.getLogger(__name__)

app = FastAPI(title="Quantum Portfolio Optimization API")

# Comma-separated list of allowed browser origins (the Next.js dev server by default).
_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("QP_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# In-process task store: single worker, not persistent, oldest entries are
# evicted beyond MAX_TASKS. Adequate for a local demo only.
MAX_TASKS = 100
TASKS: Dict[str, Dict[str, Any]] = {}


class OptimizationRequest(BaseModel):
    tickers: list[str] = Field(min_length=2, max_length=12)
    start_date: date = date(2020, 1, 1)
    end_date: date = date(2023, 1, 1)
    backtest_start_date: date = date(2023, 1, 1)
    backtest_end_date: date = date(2024, 1, 1)
    budget_resolution: int = Field(2, ge=1, le=8)
    q_factor: float = Field(0.5, ge=0.0, le=1.0)
    target_duration: float = Field(4.0, gt=0.0, le=30.0)
    max_sector_exposure: float = Field(0.60, gt=0.0, le=1.0)
    max_asset_exposure: float = Field(0.50, gt=0.0, le=1.0)
    min_cet1: float = Field(0.0, ge=0.0, le=1.0)
    min_lcr: float = Field(0.0, ge=0.0, le=5.0)
    qaoa_reps: int = Field(3, ge=1, le=10)
    qaoa_cvar_alpha: float = Field(0.25, gt=0.0, le=1.0)
    qaoa_maxiter: int = Field(80, ge=1, le=1000)
    qaoa_shots: int = Field(1024, ge=16, le=100_000)
    sa_num_reads: int = Field(200, ge=1, le=10_000)
    sa_num_sweeps: int = Field(1000, ge=1, le=100_000)
    seed: int | None = 42

    @field_validator("tickers")
    @classmethod
    def _clean_tickers(cls, v: list[str]) -> list[str]:
        cleaned = [t.strip().upper() for t in v]
        if any(not t or len(t) > 10 for t in cleaned):
            raise ValueError("tickers must be non-empty symbols of at most 10 characters")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("tickers must be unique")
        return cleaned

    @model_validator(mode="after")
    def _check_dates(self) -> "OptimizationRequest":
        if not self.start_date < self.end_date <= self.backtest_start_date < self.backtest_end_date:
            raise ValueError(
                "dates must satisfy start_date < end_date <= backtest_start_date < backtest_end_date"
            )
        return self


def run_optimization_task_logic(req: dict) -> dict:
    start = time.time()
    tickers = req["tickers"]
    dates = {k: str(req[k]) for k in ("start_date", "end_date", "backtest_start_date", "backtest_end_date")}

    # ----- Market data + factor model ----------------------------------
    prices = quant_engine.fetch_universe_data(tickers, dates["start_date"], dates["end_date"])
    mu, _sample_cov = quant_engine.calculate_classical_inputs(prices)
    B, F, D = quant_engine.generate_statistical_factor_model(prices, num_factors=3)
    # All four solvers use the same factor-model covariance, so they optimise
    # the same objective and their risk numbers are comparable.
    Sigma = B.dot(F).dot(B.T) + np.diag(D)
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
        qaoa_shots=req["qaoa_shots"],
        sa_num_reads=req["sa_num_reads"],
        sa_num_sweeps=req["sa_num_sweeps"],
        seed=req["seed"],
    )

    # ----- Out-of-sample backtest --------------------------------------
    prices_oos = quant_engine.fetch_universe_data(
        list(prices.columns),
        dates["backtest_start_date"],
        dates["backtest_end_date"],
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
        "sa_config": quantum_results["sa_config"],
        "data": {
            "tickers_used": list(prices.columns),
            "tickers_dropped": sorted(set(tickers) - set(prices.columns)),
            "metadata_defaulted": asset_metadata.attrs.get("defaulted_tickers", []),
            "risk_model": "PCA factor model, 3 factors (B F Bᵀ + diag D), annualised ×252",
        },
        "execution_time": {
            "classical_sec": classical_time,
            "exact_sec": quantum_results["timings"]["exact_sec"],
            "sa_sec": quantum_results["timings"]["sa_sec"],
            "quantum_sec": quantum_results["timings"]["qaoa_sec"],
            "total_sec": time.time() - start,
        },
    }


def _store_task(task_id: str, record: Dict[str, Any]) -> None:
    TASKS[task_id] = record
    while len(TASKS) > MAX_TASKS:
        TASKS.pop(next(iter(TASKS)))


@app.post("/api/optimize")
async def optimize(req: OptimizationRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    _store_task(task_id, {"status": "PENDING"})

    def process_task(tid: str, payload: dict):
        TASKS[tid] = {"status": "RUNNING"}
        try:
            TASKS[tid] = {"status": "COMPLETED", "result": run_optimization_task_logic(payload)}
        except Exception as exc:  # surface to client, keep traceback in the server log
            logger.exception("Optimization task %s failed", tid)
            TASKS[tid] = {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}

    background_tasks.add_task(process_task, task_id, req.model_dump())
    return {"task_id": task_id}


@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Task not found")
    return TASKS[task_id]


@app.get("/api/universe")
async def get_universe():
    """Default ticker universe: mixed financials + non-financials so the bank constraints can bind."""
    # 5 tickers across 4 sectors, 2 of them banks. At budget_resolution=2 the
    # QUBO has 9 qubits (5 decision + 4 sector-slack).
    return {
        "tickers": ["AAPL", "JPM", "JNJ", "WMT", "GS"]
    }


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
