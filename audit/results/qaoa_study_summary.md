| Config | Qubits | Feasible | Init | Trials | QAOA success [95% CI] | SA success [95% CI] | Null-model success | P(x*) at init | P(x*) at θ* (mean ± sd) | Uniform u | θ*/u | Evals (mean) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | 9 | 1 | current | 20 | 20/20 [0.84, 1.00] | 20/20 [0.84, 1.00] | 1.000000 | 0.0728 | 0.0814 ± 0.0085 | 0.0312 | 2.61 | 46.1 |
| C1 | 9 | 1 | original | 20 | 20/20 [0.84, 1.00] | 20/20 [0.84, 1.00] | 1.000000 | 0.0011 | 0.0587 ± 0.0291 | 0.0312 | 1.88 | 60.0 |
| C2 | 9 | 2 | current | 20 | 20/20 [0.84, 1.00] | 20/20 [0.84, 1.00] | 1.000000 | 0.0721 | 0.0781 ± 0.0034 | 0.0312 | 2.50 | 48.0 |
| C2 | 9 | 2 | original | 20 | 20/20 [0.84, 1.00] | 20/20 [0.84, 1.00] | 1.000000 | 0.0006 | 0.0689 ± 0.0448 | 0.0312 | 2.20 | 55.9 |
| C3 | 18 | 5 | current | 10 | 10/10 [0.72, 1.00] | 8/10 [0.49, 0.94] | 0.632300 | 0.0026 | 0.0033 ± 0.0003 | 0.0010 | 3.33 | 51.5 |
| C3 | 18 | 5 | original | 10 | 9/10 [0.60, 0.98] | 8/10 [0.49, 0.94] | 0.632300 | 0.0000 | 0.0022 ± 0.0015 | 0.0010 | 2.28 | 57.3 |

C1: paired P(x*) at θ*, current − original init over 20 seeds: mean +0.0228, median +0.0224, Wilcoxon p = 0.00365

C2: paired P(x*) at θ*, current − original init over 20 seeds: mean +0.0092, median +0.0205, Wilcoxon p = 0.0484

C3: paired P(x*) at θ*, current − original init over 10 seeds: mean +0.0010, median +0.0009, Wilcoxon p = 0.0645

QAOA wall-clock per run: median 2.78s (runs were concurrent with other jobs; use isolated pipeline runs for timing claims)
