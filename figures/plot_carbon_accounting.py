#!/usr/bin/env python3
"""
Plot average annual CO₂e avoided per mini-grid vs. capacity, customers, and CAPEX.

Reads paper/graphics/carbon_accounting.csv produced by carbon_accounting.py.
Saves paper/graphics/carbon_accounting.png.

Usage:
  python figures/plot_carbon_accounting.py
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

CSV_PATH = Path("paper/graphics/carbon_accounting.csv")
OUT_PATH  = Path("paper/graphics/carbon_accounting.png")

# (xcol, xlabel, x_scale, slope_scale, slope_unit)
PANELS = [
    ("sizePv",         "Installed PV Capacity (kWp)",  1,      1,   "kWp"),
    ("customer_count", "Customer Count",               1,    100,   "100 customers"),
    ("capex",          "Capital Expenditure (kUSD)",   1e-3,   1,   "kUSD"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-kalobeyei", action="store_true",
                        help="Exclude Kalobeyei Settlement from all plots")
    args = parser.parse_args()

    result = pd.read_csv(CSV_PATH)
    if args.no_kalobeyei:
        result = result[result["project"] != "Kalobeyei Settlement"]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle("Average Annual CO₂e Avoided per Mini-Grid (AMS-III.BB)", fontsize=13)

    for ax, (xcol, xlabel, x_scale, slope_scale, slope_unit) in zip(axes, PANELS):
        sub = result.dropna(subset=[xcol, "avg_annual_co2e"])
        x = sub[xcol] * x_scale
        ax.scatter(x, sub["avg_annual_co2e"], color="#2563eb", s=60, zorder=3)

        if len(sub) >= 2:
            x_arr = x.values
            y_arr = sub["avg_annual_co2e"].values
            n = len(x_arr)

            # No-intercept OLS: β̂ = Σ(xᵢyᵢ) / Σ(xᵢ²)
            Sxx0 = np.dot(x_arr, x_arr)
            slope = np.dot(x_arr, y_arr) / Sxx0
            residuals = y_arr - slope * x_arr
            ss_res = np.dot(residuals, residuals)
            se_resid = np.sqrt(ss_res / (n - 1))  # df = n-1 (no intercept estimated)

            # Uncentered R² = 1 − SS_res / Σyᵢ²
            r2 = 1 - ss_res / np.dot(y_arr, y_arr)

            # One-tailed t-test (H₁: slope > 0), df = n-1
            t_stat = slope / (se_resid / np.sqrt(Sxx0))
            p_value = stats.t.sf(t_stat, df=n - 1)

            x_line = np.linspace(0, x.max(), 200)
            y_line = slope * x_line
            ax.plot(x_line, y_line, color="#dc2626", linewidth=1.2,
                    linestyle="--", zorder=2)

            # 95% CI band: SE(ŷ₀) = x₀ · s / √Σxᵢ²
            t_crit = stats.t.ppf(0.975, df=n - 1)
            se_line = se_resid * x_line / np.sqrt(Sxx0)
            ax.fill_between(x_line,
                            y_line - t_crit * se_line,
                            y_line + t_crit * se_line,
                            color="#dc2626", alpha=0.15, zorder=1)

            p_str = f"={p_value:.3f}" if p_value >= 0.001 else "<0.001"
            ax.annotate(
                f"{slope * slope_scale:.3g} tCO₂e/{slope_unit}/yr\n"
                f"$R^2={r2:.2f}$,  $p_{{1}}{p_str}$",
                xy=(0.05, 0.93),
                xycoords="axes fraction",
                fontsize=8,
                color="#dc2626",
                verticalalignment="top",
            )

        ax.set_xlabel(xlabel, fontsize=10)
        ax.set_ylabel("Avg annual CO₂e avoided (tCO₂e/yr)", fontsize=10)
        ax.grid(axis="both", linewidth=0.4, alpha=0.5)
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)

    plt.tight_layout()
    plt.savefig(OUT_PATH, dpi=150)
    print(f"Saved {OUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
