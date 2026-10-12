"""
Independent reference implementations used by the tests.

Nothing here imports the code under test; these are the "second opinion"
against which quant_engine / quantum_engine are checked.
"""
from __future__ import annotations

import math

import numpy as np


def simple_returns(prices: np.ndarray) -> np.ndarray:
    return prices[1:] / prices[:-1] - 1.0


def bounded_coeffs(ub: int) -> list[int]:
    """Bounded-coefficient binary encoding of an integer in [0, ub]: 1, 2, …, 2^(k-1), ub − (2^k − 1)."""
    if ub <= 0:
        return []
    k = int(math.floor(math.log2(ub)))
    return [2 ** i for i in range(k)] + [ub - (2 ** k - 1)]


def portfolio_objective(w: np.ndarray, mu: np.ndarray, sigma: np.ndarray, q: float) -> float:
    return float(q * w @ sigma @ w - (1 - q) * mu @ w)


def qaoa_state(energies: np.ndarray, betas, gammas) -> np.ndarray:
    """Π_l e^{-iβ_l ΣX} e^{-iγ_l diag(E)} |+⟩^n; qubit i is bit i of the basis index (little-endian)."""
    n = int(round(math.log2(energies.size)))
    psi = np.full(energies.size, 1 / math.sqrt(energies.size), dtype=complex)
    for b, g in zip(betas, gammas):
        psi = np.exp(-1j * g * energies) * psi
        c, s = math.cos(b), math.sin(b)
        for i in range(n):
            v = psi.reshape(2 ** (n - 1 - i), 2, 2 ** i)
            a0, a1 = v[:, 0, :].copy(), v[:, 1, :].copy()
            v[:, 0, :] = c * a0 - 1j * s * a1
            v[:, 1, :] = -1j * s * a0 + c * a1
            psi = v.reshape(-1)
    return psi


def bits_of(k: int, n: int) -> np.ndarray:
    return np.array([(k >> i) & 1 for i in range(n)], dtype=float)
