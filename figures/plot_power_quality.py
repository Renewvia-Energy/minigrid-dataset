#!/usr/bin/env python3
"""
Power quality visualizations from sparkmeterreadings.

Reads CSVs produced by power_quality.py and saves:
  paper/graphics/power_quality_scatter.png
      2D density: average voltage (x) vs. average power factor (y),
      Kenya (240 V nominal) and Nigeria (230 V nominal) side by side.
  paper/graphics/voltage_histograms.png
      Overlaid density histograms of minimum, average, and maximum voltages
      per heartbeat, Kenya and Nigeria side by side with their respective
      nominal and ±10 % tolerance reference lines.

Bin parameters must match power_quality.py.

Usage:
  python figures/plot_power_quality.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

OUT_DIR = Path("paper/graphics")

HIST_CSV   = {
    "Kenya":   OUT_DIR / "power_quality_histograms_kenya.csv",
    "Nigeria": OUT_DIR / "power_quality_histograms_nigeria.csv",
}
SCATTER_CSV = {
    "Kenya":   OUT_DIR / "power_quality_scatter_kenya.csv",
    "Nigeria": OUT_DIR / "power_quality_scatter_nigeria.csv",
}
NOMINAL_V = {"Kenya": 240, "Nigeria": 230}

V_LO,  V_HI,  V_BINS  = 50.0, 300.0, 250
PF_LO, PF_HI, PF_BINS =  0.0,   1.0, 200

v_edges  = np.linspace(V_LO,  V_HI,  V_BINS  + 1)
pf_edges = np.linspace(PF_LO, PF_HI, PF_BINS + 1)

COUNTRIES = ["Kenya", "Nigeria"]

# ── 1. Load CSVs ──────────────────────────────────────────────────────────────

hist_df    = {c: pd.read_csv(HIST_CSV[c])    for c in COUNTRIES}
scatter_df = {c: pd.read_csv(SCATTER_CSV[c]) for c in COUNTRIES}

# ── 2. Figure 1: average voltage vs. power factor ────────────────────────────

fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)

for ax, country in zip(axes, COUNTRIES):
    df = scatter_df[country]
    pivot = df.pivot_table(
        index="pf_bin_center",
        columns="v_bin_center",
        values="count",
        fill_value=0,
    )
    grid = pivot.values.astype(float)
    v_centers  = pivot.columns.values
    pf_centers = pivot.index.values

    dv  = v_centers[1]  - v_centers[0]
    dpf = pf_centers[1] - pf_centers[0]
    v_plot_edges  = np.append(v_centers  - dv  / 2, v_centers[-1]  + dv  / 2)
    pf_plot_edges = np.append(pf_centers - dpf / 2, pf_centers[-1] + dpf / 2)

    mesh = ax.pcolormesh(
        v_plot_edges,
        pf_plot_edges,
        grid,
        norm=mcolors.LogNorm(vmin=1, vmax=grid.max()),
        cmap="YlOrRd",
        rasterized=True,
    )
    fig.colorbar(mesh, ax=ax, label="Number of readings")

    nom = NOMINAL_V[country]
    ax.axvline(nom, color="#1e3a8a", linewidth=1.2, linestyle="--",
               label=f"{nom} V nominal")
    ax.axvline(0.9 * nom, color="#6b7280", linewidth=0.9, linestyle=":",
               label="±10 % tolerance")
    ax.axvline(1.1 * nom, color="#6b7280", linewidth=0.9, linestyle=":",
               label="_nolegend_")

    ax.set_xlim(V_LO, V_HI)
    ax.set_ylim(PF_LO, PF_HI)
    ax.set_xlabel("Average voltage per heartbeat (V)", fontsize=11)
    ax.set_title(country, fontsize=12)
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(linewidth=0.3, alpha=0.4)

axes[0].set_ylabel("Average power factor per heartbeat", fontsize=11)

fig.suptitle("Power Quality: Average Voltage vs. Power Factor\n"
             "(customer meters)", fontsize=13)
plt.tight_layout()
out = OUT_DIR / "power_quality_scatter.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved {out}")
plt.close(fig)

# ── 3. Figure 2: voltage histograms (min, avg, max) ─────────────────────────

BIN_WIDTH = (V_HI - V_LO) / V_BINS

SERIES = [
    ("voltageMin", "Minimum",  "#dc2626", 0.45),
    ("voltageAvg", "Average",  "#2563eb", 0.55),
    ("voltageMax", "Maximum",  "#16a34a", 0.45),
]

fig, axes = plt.subplots(1, 2, figsize=(16, 5), sharey=False)

for ax, country in zip(axes, COUNTRIES):
    df  = hist_df[country]
    nom = NOMINAL_V[country]

    for col, label, color, alpha in SERIES:
        sub     = df[df["series"] == col]
        centers = sub["bin_center"].values
        counts  = sub["count"].values.astype(float)
        total   = counts.sum()
        density = counts / (total * BIN_WIDTH)
        mean_v  = (centers * counts).sum() / total

        ax.bar(centers, density, width=BIN_WIDTH, alpha=alpha, color=color,
               label=f"{label}  (mean = {mean_v:.1f} V)",
               align="center", linewidth=0)

    ax.axvline(nom, color="black", linewidth=1.3, linestyle="--",
               label=f"{nom} V nominal")
    ax.axvline(0.9 * nom, color="#6b7280", linewidth=0.9, linestyle=":",
               label="±10 % tolerance")
    ax.axvline(1.1 * nom, color="#6b7280", linewidth=0.9, linestyle=":",
               label="_nolegend_")

    total_v = int(df[df["series"] == "voltageAvg"]["count"].sum())
    ax.text(0.98, 0.97, f"n = {total_v:,} heartbeats",
            transform=ax.transAxes, fontsize=8, color="gray", va="top", ha="right")

    ax.set_xlim(nom - 50, nom + 50)
    ax.set_xlabel("Voltage (V)", fontsize=11)
    ax.set_title(country, fontsize=12)
    ax.legend(fontsize=9)
    ax.grid(axis="y", linewidth=0.3, alpha=0.4)

axes[0].set_ylabel("Density", fontsize=11)

fig.suptitle("Voltage Distribution: Minimum, Average, and Maximum per Heartbeat\n"
             "(customer meters)", fontsize=13)
plt.tight_layout()
out = OUT_DIR / "voltage_histograms.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved {out}")
plt.close(fig)
