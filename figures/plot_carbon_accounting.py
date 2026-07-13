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
            m, b = np.polyfit(x, sub["avg_annual_co2e"], 1)
            x_line = np.linspace(x.min(), x.max(), 200)
            ax.plot(x_line, m * x_line + b, color="#dc2626", linewidth=1.2,
                    linestyle="--", zorder=2)
            ax.annotate(
                f"{m * slope_scale:.3g} tCO₂e/{slope_unit}/yr",
                xy=(0.05, 0.93),
                xycoords="axes fraction",
                fontsize=8,
                color="#dc2626",
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
