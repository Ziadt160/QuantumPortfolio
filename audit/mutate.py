"""
Mutation check for the regression tests (AUDIT_TESTING.md §3).

Copies backend/ to a scratch directory, re-introduces one original defect at a
time, and runs the regression test that should catch it.

Usage: python audit/mutate.py <scratch_dir> <python_executable>
"""
import shutil, subprocess, sys, os
from pathlib import Path
SRC = Path(__file__).resolve().parents[1] / "backend"
WORK = Path(sys.argv[1]); PY = sys.argv[2]
MUTANTS = {
 "M1 interleaved QAOA init": ("quantum_engine.py", "    return np.concatenate([betas, gammas])", "    return np.column_stack([betas, gammas]).ravel()", "tests/test_qaoa.py::test_linear_ramp_binds_to_the_right_parameters"),
 "M2 vacuous Basel penalty": ("quantum_engine.py", 'if "CET1_Ratio" in asset_metadata.columns and min_cet1 > 0:', 'if "CET1_Ratio" in asset_metadata.columns:', "tests/test_formulation.py::test_vacuous_basel_minimum_adds_no_penalty"),
 "M3 duration rhs round(T)*R": ("quantum_engine.py", "rhs=_round_half_up(target_duration * budget_resolution),", "rhs=int(round(target_duration)) * budget_resolution,", "tests/test_formulation.py::test_duration_target_is_rounded_on_slice_scale"),
 "M4 asset-cap check removed": ("quant_engine.py", "    if over:\n", "    if False:\n", "tests/test_metrics_and_classical.py::test_metrics_reports_asset_cap_violation"),
 "M5 SLSQP failure hidden": ("quant_engine.py", 'out["success"] = bool(res.success)', 'out["success"] = True', "tests/test_metrics_and_classical.py::test_slsqp_failure_is_reported_not_replaced"),
 "M6 bfill look-ahead": ("quant_engine.py", "prices = prices.ffill().dropna()", "prices = prices.ffill().bfill()", "tests/test_market_model.py::test_fetch_does_not_backfill_future_prices"),
 "M7 positional metadata": ("quant_engine.py", "    md = asset_metadata.reindex(mu.index)\n", "    md = asset_metadata\n", "tests/test_metrics_and_classical.py::test_metrics_align_metadata_by_label_not_position"),
}
for name, (f, old, new, test) in MUTANTS.items():
    if WORK.exists(): shutil.rmtree(WORK)
    shutil.copytree(SRC, WORK, ignore=shutil.ignore_patterns(".venv", "__pycache__", ".pytest_cache"))
    p = WORK / f; s = p.read_text(encoding="utf-8")
    assert s.count(old) == 1, (name, old)
    p.write_text(s.replace(old, new), encoding="utf-8")
    r = subprocess.run([PY, "-m", "pytest", "-p", "no:cacheprovider", "-q", test], cwd=WORK, capture_output=True, text=True,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
    last = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l][-1:]
    print(f"{name:32s} -> {'KILLED (test fails)' if r.returncode != 0 else 'SURVIVED'} | {last}")
shutil.rmtree(WORK)
