"""
Statistical Randomness Tests for the Hybrid RNG Dashboard.

Handles arbitrary integer sizes from the Pico:
  - PRNG: 32-bit values (0 to 2^32-1)
  - TRNG: 16-bit values (0 to 65535)
  - HYBRID: variable (XOR of PRNG ^ TRNG)

Implements:
  - Frequency (Monobit) Test
  - Runs Test
  - Autocorrelation Test
  - Chi-Square Goodness-of-Fit Test
"""

import math
import numpy as np
from scipy import stats as sp_stats


def _numbers_to_bits(numbers: list[int], bit_width: int = 16) -> list[int]:
    """Convert a list of integers to a flat list of bits (MSB first)."""
    bits = []
    for n in numbers:
        for i in range(bit_width - 1, -1, -1):
            bits.append((n >> i) & 1)
    return bits


def _detect_bit_width(numbers: list[int]) -> int:
    """Auto-detect the bit width from the data values."""
    if not numbers:
        return 16
    max_val = max(numbers)
    if max_val > 65535:
        return 32
    elif max_val > 255:
        return 16
    else:
        return 8


# ── Frequency (Monobit) Test ──────────────────────────────────────────────

def frequency_test(numbers: list[int], bit_width: int = 16) -> dict:
    """
    Check the proportion of 1s and 0s in the bit stream.
    A truly random sequence should have roughly equal counts.
    Uses a two-sided z-test; p > 0.01 indicates pass.
    """
    bits = _numbers_to_bits(numbers, bit_width)
    n = len(bits)
    if n == 0:
        return {"name": "Frequency (Monobit)", "statistic": 0, "p_value": 0, "passed": False}

    s = sum(2 * b - 1 for b in bits)          # map 0→-1, 1→+1
    s_obs = abs(s) / math.sqrt(n)
    p_value = math.erfc(s_obs / math.sqrt(2))

    return {
        "name": "Frequency (Monobit)",
        "statistic": round(s_obs, 6),
        "p_value": round(p_value, 6),
        "passed": p_value >= 0.01,
    }


# ── Runs Test ─────────────────────────────────────────────────────────────

def runs_test(numbers: list[int], bit_width: int = 16) -> dict:
    """
    Count the total number of uninterrupted runs of identical bits
    and compare against the expected value for a random sequence.
    """
    bits = _numbers_to_bits(numbers, bit_width)
    n = len(bits)
    if n == 0:
        return {"name": "Runs Test", "statistic": 0, "p_value": 0, "passed": False}

    ones = sum(bits)
    pi = ones / n

    # Pre-test: if proportion is too far from 0.5, skip
    if abs(pi - 0.5) >= (2.0 / math.sqrt(n)):
        return {
            "name": "Runs Test",
            "statistic": 0,
            "p_value": 0.0,
            "passed": False,
        }

    # Count runs
    runs = 1
    for i in range(1, n):
        if bits[i] != bits[i - 1]:
            runs += 1

    num = abs(runs - 2 * n * pi * (1 - pi))
    den = 2 * math.sqrt(2 * n) * pi * (1 - pi)
    if den == 0:
        return {"name": "Runs Test", "statistic": 0, "p_value": 0, "passed": False}

    z = num / den
    p_value = math.erfc(z / math.sqrt(2))

    return {
        "name": "Runs Test",
        "statistic": round(z, 6),
        "p_value": round(p_value, 6),
        "passed": p_value >= 0.01,
    }


# ── Autocorrelation Test ──────────────────────────────────────────────────

def autocorrelation_test(numbers: list[int], bit_width: int = 16, lag: int = 1) -> dict:
    """
    Measure the correlation between the bit sequence and a shifted
    version of itself. Low correlation indicates independence.
    """
    bits = _numbers_to_bits(numbers, bit_width)
    n = len(bits)
    if n <= lag:
        return {"name": "Autocorrelation", "statistic": 0, "p_value": 0, "passed": False}

    # Count agreements
    matches = sum(1 for i in range(n - lag) if bits[i] == bits[i + lag])
    d = n - lag
    stat = 2 * (matches - d / 2) / math.sqrt(d)

    p_value = math.erfc(abs(stat) / math.sqrt(2))

    return {
        "name": "Autocorrelation",
        "statistic": round(stat, 6),
        "p_value": round(p_value, 6),
        "passed": p_value >= 0.01,
    }


# ── Chi-Square Goodness-of-Fit Test ──────────────────────────────────────

def chi_square_test(numbers: list[int], num_bins: int = 64) -> dict:
    """
    Test that the generated numbers follow a uniform distribution.
    Uses adaptive binning based on the actual data range.
    """
    if len(numbers) == 0:
        return {"name": "Chi-Square", "statistic": 0, "p_value": 0, "passed": False}

    arr = np.array(numbers, dtype=np.float64)
    lo, hi = float(arr.min()), float(arr.max())
    if hi == lo:
        return {"name": "Chi-Square", "statistic": 0, "p_value": 0, "passed": False}

    observed, _ = np.histogram(arr, bins=num_bins, range=(lo, hi + 1))
    expected = np.full(num_bins, len(numbers) / num_bins)

    chi2, p_value = sp_stats.chisquare(observed, f_exp=expected)

    return {
        "name": "Chi-Square",
        "statistic": round(float(chi2), 6),
        "p_value": round(float(p_value), 6),
        "passed": float(p_value) >= 0.01,
    }


# ── Run All Tests ─────────────────────────────────────────────────────────

def run_all_tests(numbers: list[int], bit_width: int | None = None) -> list[dict]:
    """Run all four statistical tests and return a list of result dicts."""
    if bit_width is None:
        bit_width = _detect_bit_width(numbers)

    return [
        frequency_test(numbers, bit_width),
        runs_test(numbers, bit_width),
        autocorrelation_test(numbers, bit_width),
        chi_square_test(numbers),
    ]
