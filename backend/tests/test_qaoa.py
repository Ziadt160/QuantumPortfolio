"""QAOA ansatz semantics, initial point, and the end-to-end discrete solvers."""
from __future__ import annotations

import numpy as np
import pytest
from qiskit.circuit.library import QAOAAnsatz
from qiskit.quantum_info import Operator, SparsePauliOp, Statevector

import quantum_engine as qm
from conftest import DEFAULT_CFG
from reference import qaoa_state

SMALL_OP = SparsePauliOp.from_list([("IIZZ", 0.7), ("ZIIZ", -0.3), ("IZIZ", 0.2), ("ZZII", 0.5),
                                    ("IIIZ", -0.4), ("IZII", 0.1)])


def test_linear_ramp_binds_to_the_right_parameters():
    """Regression: the init used to be interleaved [β0, γ0, β1, …] while Qiskit orders [β0..βp-1, γ0..γp-1]."""
    p, dt, scale = 3, 0.75, 4.0
    ansatz = QAOAAnsatz(SMALL_OP, reps=p)
    bound = {prm.name: v for prm, v in zip(ansatz.parameters, qm._linear_ramp_initial_point(p, dt, scale))}
    for i in range(p):
        s = (i + 1) / (p + 1)
        assert bound[f"β[{i}]"] == pytest.approx(-(1 - s) * dt)
        assert bound[f"γ[{i}]"] == pytest.approx(s * dt / scale)


def test_linear_ramp_anneals_towards_the_minimum(model):
    """Regression: with Qiskit's +ΣX mixer, positive β anneals to the *maximum* of H_C.

    The TQA start must have lower ⟨H_C⟩ than the uniform superposition; the
    original sign/scale gives higher energy than uniform.
    """
    from qiskit_optimization.converters import QuadraticProgramToQubo
    qp = qm._build_quadratic_program(mu=model["mu"], B=model["B"], F=model["F"], D=model["D"],
                                     asset_metadata=model["md"], **DEFAULT_CFG)
    op, _ = QuadraticProgramToQubo().convert(qp).to_ising()
    E = np.real(op.to_matrix(sparse=True).diagonal())
    scale = np.abs(op.coeffs).max()
    th = qm._linear_ramp_initial_point(3, energy_scale=scale)
    e_tqa = np.abs(qaoa_state(E, th[:3], th[3:])) ** 2 @ E
    s = np.arange(1, 4) / 4
    wrong = np.abs(qaoa_state(E, (1 - s) * 0.75, s * 0.75 / scale)) ** 2 @ E   # positive-β convention
    assert e_tqa < E.mean() < wrong


def test_ansatz_matches_independent_statevector():
    rng = np.random.default_rng(3)
    theta = rng.uniform(-np.pi, np.pi, 4)
    ansatz = QAOAAnsatz(SMALL_OP, reps=2)
    psi_qk = Statevector(ansatz.assign_parameters(theta)).data
    energies = np.real(SMALL_OP.to_matrix(sparse=True).diagonal())
    psi_np = qaoa_state(energies, theta[:2], theta[2:])
    np.testing.assert_allclose(np.abs(psi_qk) ** 2, np.abs(psi_np) ** 2, atol=1e-12)
    assert np.sum(np.abs(psi_np) ** 2) == pytest.approx(1.0, abs=1e-12)


def test_ansatz_is_unitary_and_trivial_at_zero_angles():
    ansatz = QAOAAnsatz(SMALL_OP, reps=2)
    U = Operator(ansatz.assign_parameters([0.3, -0.2, 0.9, 0.4])).data
    np.testing.assert_allclose(U @ U.conj().T, np.eye(16), atol=1e-12)
    probs = Statevector(ansatz.assign_parameters(np.zeros(4))).probabilities()
    np.testing.assert_allclose(probs, np.full(16, 1 / 16), atol=1e-12)


def test_cost_operator_is_cleaned_and_normalised():
    seen = {}

    class Recorder(qm.SamplingMinimumEigensolver):
        def compute_minimum_eigenvalue(self, operator, aux_operators=None):
            seen["op"] = operator
            return None

    op = SparsePauliOp.from_list([("ZI", 1.5), ("IZ", -3e-17), ("ZZ", -3.0)])
    solver = qm._NormalizedCostSolver(Recorder())
    solver.compute_minimum_eigenvalue(op)
    got = dict(zip(seen["op"].paulis.to_labels(), seen["op"].coeffs.real))
    assert got == pytest.approx({"ZI": 0.5, "ZZ": -1.0})
    assert solver.scale == 3.0


def run_solvers(model, **over):
    kw = dict(DEFAULT_CFG, qaoa_reps=2, qaoa_maxiter=15, qaoa_shots=256, sa_num_reads=50, sa_num_sweeps=200, seed=11)
    kw.update(over)
    return qm.optimize_portfolio_qaoa(mu=model["mu"], B=model["B"], F=model["F"], D=model["D"],
                                      asset_metadata=model["md"], **kw)


@pytest.fixture(scope="module")
def solved(model):
    return run_solvers(model)


def test_exact_solver_matches_brute_force(model, solved):
    qp = qm._build_quadratic_program(mu=model["mu"], B=model["B"], F=model["F"], D=model["D"],
                                     asset_metadata=model["md"], **DEFAULT_CFG)
    import itertools
    best = min((np.array(x, float) for x in itertools.product(range(2), repeat=5) if qp.is_feasible(list(x))),
               key=qp.objective.evaluate)
    assert solved["exact"]["weights"] == {v.name: b / 2 for v, b in zip(qp.variables, best) if b}
    assert solved["exact"]["qp_feasible"] and solved["qubo"]["num_qubits"] == 9


def test_discrete_results_are_consistent(solved):
    for key in ("sa", "qaoa"):
        m = solved[key]
        assert m["qp_feasible"]
        assert m["gap_to_optimal_pct"] is not None and m["gap_to_optimal_pct"] >= -1e-9
    q = solved["qaoa"]
    assert 0.0 <= q["p_optimal"] <= q["p_feasible"] <= 1.0
    assert q["uniform_p_optimal"] == pytest.approx(16 / 512)
    assert len(q["optimal_parameters"]) == 4


def test_same_seed_is_reproducible(model, solved):
    again = run_solvers(model)
    for key in ("exact", "sa", "qaoa"):
        assert again[key]["weights"] == solved[key]["weights"]
    assert again["qaoa"]["optimal_parameters"] == solved["qaoa"]["optimal_parameters"]
    assert again["qaoa"]["p_optimal"] == solved["qaoa"]["p_optimal"]


def test_qubit_guard(model, monkeypatch):
    monkeypatch.setattr(qm, "MAX_QAOA_QUBITS", 5)
    with pytest.raises(ValueError, match="qubits"):
        run_solvers(model)
