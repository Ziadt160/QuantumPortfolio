# Audit summary — QuantumPortfolio (2026-10-12)

Full evidence is in the phase documents; every number below was produced by scripts in `audit/` or by the test
suite and can be re-run (README "Reproducing the audit").

## Verdicts on the eight objectives

| # | Objective | As found | Now |
|---|---|---|---|
| 1 | **Scientifically feasible** | Partly. The QUBO/QAOA approach is sound, but the claims were not: "same problem" for all solvers (false), "Basel III constraints" (stylised, not regulation), "linear-ramp (Sack & Serbyn) init" (not implemented correctly), "avoids barren plateaus" (unsupported), penalty method attributed to Barkoutsos (wrong paper). | Claims corrected or removed; assumptions documented (AUDIT_SCIENCE.md §2, §4). No quantum advantage is claimed or possible at ≤ 24 simulated qubits. |
| 2 | **Mathematically correct** | Encodings correct (QUBO, Ising, endianness, Hermiticity, CVaR). Formulation defects: a vacuous CET1/LCR penalty dominated the objective; the duration target was mis-rounded; the cap clamp was hidden; the QAOA start had the wrong order, sign and scale. | Fixed. Every pass/fail check passes except N25.o, which deliberately documents the original initial point (AUDIT_NUMERICS.md). |
| 3 | **Numerically verified** | Never independently checked. | 69 independent checks (61 PASS, 7 INFO, 1 FAIL that documents the original initial point). Every reported metric of both versions reproduces to ≤ 4.3·10⁻¹⁶ relative error. Repeated-trial QAOA study with confidence intervals. |
| 4 | **Algorithmically valid** | QAOA ran, but its start point annealed toward the *worst* solutions. Its reported success (best feasible of 1024 shots) is matched by uniform random sampling with probability 1 − 7.6·10⁻¹⁵. SLSQP failures were masked. | QAOA start is a correct TQA ramp in Qiskit's convention. The API reports P(optimum) vs random; SLSQP reports convergence. At 18 qubits QAOA puts 3.3× uniform probability on the optimum (random sampling succeeds 63 % of the time, QAOA 10/10). |
| 5 | **Software-engineered properly** | Clear modules, but untyped dict interfaces, no validation, duplicated metric logic, silent failure paths, fabricated UI progress messages. | One shared metric evaluator, bounded inputs, explicit errors, honest UI. Remaining: dict-typed API, one long orchestration function (AUDIT_CODE_QUALITY.md). |
| 6 | **Reproducible** | **No.** A fresh install crashed on every request (qiskit-algorithms 0.4 vs V1 primitives); no pins, tests, README or data snapshot; results depended on the download date. | Exact pins + lock; clean installs on CPython 3.11 and 3.13 pass 50/50 tests; frozen data snapshot with SHA-256; seeded SA and QAOA; byte-exact copy of the original code. |
| 7 | **Production-ready (to a defined standard)** | Not usable outside the author's machine. | Ready as a **local single-user demo**. **Not** production-ready as a hosted service (no auth, job queue, timeouts or rate limits). Critical Next.js advisories fixed by upgrading to 16.4.0 (AUDIT_PRODUCTION.md). |
| 8 | **Portfolio/research-ready** | A reviewer could not install it, and the headline result (QAOA = Exact, 0 % gap) was degenerate: the default problem has exactly one feasible portfolio. | Installable, tested, documented, with the limitations stated in the README. It is a sound demonstration of a verified QUBO/QAOA pipeline, not evidence of quantum benefit. |

## Most important findings

1. **Fresh installs were broken** (D1). Unpinned `qiskit-algorithms` resolves to 0.4.x, which rejects the V1 Aer
   sampler, so every optimisation failed. The code only ran in the author's pre-existing environment.
2. **The default problem is degenerate** (D7). Durations are rounded to whole years and enforced by an equality,
   which leaves exactly one feasible portfolio ({AAPL 50 %, GS 50 %}). Exact, SA and QAOA cannot differ, and the
   risk–return objective plays no role. Across 84 configurations there were never more than 7 feasible portfolios.
3. **A constraint that does not bind was dominating the objective** (D2). With min CET1 = min LCR = 0, the
   "soft Basel penalty" still added λ(c·w)² + λ(ℓ·w)². That is 4.28 for a 50 % GS position against a portfolio
   objective of −0.064, i.e. 98 % of the reported SA "energy".
4. **The QAOA starting point was not the cited algorithm** (D3): interleaved parameter order, inverted mixer
   sign (it annealed toward the maximum of H_C), and an unnormalised energy scale. Corrected, it improves the
   final probability of the optimum significantly at 9 qubits (paired Wilcoxon p = 0.004 and 0.048).
5. **QAOA "success" was post-selection** (D8). The best feasible bitstring among 1024 shots is found by random
   guessing as well at 9 qubits. The informative metric, probability on the optimum, was not reported (now it is).
6. **Silent failure paths** (D4, D5). Non-converged SLSQP results were replaced by equal weights; per-asset cap
   violations from the `max(1, ⌊a·R⌋)` clamp were labelled "feasible". Both are now reported and reproduced in
   `audit/results/original_repro_*.json`.
7. **Performance choices distorted the comparison** (D13, D14). The SA baseline was dimod's pure-Python
   reference sampler, which its own docs call unsuitable for benchmarking (5.1 s → 0.03 s now). The MPS simulator
   is the worst case for dense QAOA circuits (18.2 s vs 0.10 s per circuit at 18 qubits).

## What changed (files)

* `backend/quant_engine.py`, `quantum_engine.py`, `main.py`: the fixes in AUDIT_CORRECTNESS.md (all Critical and
  High items, most Medium/Low).
* `backend/requirements*.txt`, `pytest.ini`, `tests/` (50 tests).
* `frontend/src/app/Dashboard.tsx`, `layout.tsx`: honest status/labels, new metrics, configurable API URL.
  `package.json`/lock: next and eslint-config-next 16.4.0.
* `audit/`: verification scripts, data snapshot, results, preserved original backend.
* `README.md` and the eight `AUDIT_*.md` files.

## Not verified

Bank ratios and equity durations against filings; Yahoo price correctness beyond internal consistency; any
hardware or noisy-simulation behaviour; QAOA beyond 18 qubits or other p/α; the UI at phone widths and its
accessibility (desktop rendering was checked in Chrome); Linux and macOS. The audit brief was truncated in Phase 7, so later requirements could not be addressed.
