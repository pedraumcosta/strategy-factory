"""Plan §17.4's compute-budget check: can per-bar causal EMD refits carry
the factory's three workloads? Measures decompose_last on this machine and
prices each workload in wall-clock terms; the VM is slower than this box,
so read the live-VM line with a ~3x cushion in mind."""

import time

import numpy as np

from factory.screens.cemd import decompose_last

PAIRS = 17
BARS_1D_8Y = 2_900          # ~8 years of daily bars
BARS_1H_5Y = 43_800         # the pre-registered 5-year S5 range at 1h

if __name__ == "__main__":
    rng = np.random.default_rng(0)
    series = 100 * np.exp(np.cumsum(0.02 * rng.standard_normal(50_000)))

    print(f"{'window':>7} {'ms/refit':>9}")
    per_ms = {}
    for n in (64, 128, 256, 365):
        windows = [series[i:i + n]
                   for i in range(0, len(series) - n, n)][:200]
        t0 = time.perf_counter()
        for w in windows:
            decompose_last(w)
        per_ms[n] = (time.perf_counter() - t0) / len(windows) * 1000
        print(f"{n:>7} {per_ms[n]:>9.2f}")

    ms = per_ms[128]  # the working window for the registered feature family
    print(f"\nat window 128 ({ms:.2f} ms/refit), one feature, {PAIRS} pairs:")
    print(f"  S2 screen, 1d x ~8y : {PAIRS * BARS_1D_8Y * ms / 1000 / 60:6.1f} min")
    print(f"  S5 backtest, 1h x 5y: {PAIRS * BARS_1H_5Y * ms / 1000 / 60:6.1f} min")
    print(f"  live VM, per 1h bar : {PAIRS * ms:6.1f} ms")
