#!/usr/bin/env python3
"""
Power quality visualizations from sparkmeterreadings.

Reads CSVs produced by power_quality.py and saves:
  paper/graphics/power_quality_scatter.png
      2D density: average voltage (x) vs. average power factor (y).
  paper/graphics/voltage_histograms.png
      Overlaid density histograms of minimum, average, and maximum voltages
      per heartbeat, with IEC 240 V nominal and ±10 % tolerance reference lines.

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

OUT_DIR      = Path("paper/graphics")
HIST_CSV     = OUT_DIR / "power_quality_histograms.csv"
SCATTER_CSV  = OUT_DIR / "power_quality_scatter.csv"

V_LO,  V_HI,  V_BINS  = 50.0, 300.0, 250
PF_LO, PF_HI, PF_BINS =  0.0,   1.0, 200

v_edges  = np.linspace(V_LO,  V_HI,  V_BINS  + 1)
pf_edges = np.linspace(PF_LO, PF_HI, PF_BINS + 1)

# ── 1. Load CSVs ─────────────────────────────────────────────────────────────

hist_df    = pd.read_csv(HIST_CSV)
scatter_df = pd.read_csv(SCATTER_CSV)

# ── 2. Figure 1: average voltage vs. power factor ────────────────────────────

# Reconstruct 2D grid from sparse representation
pivot = scatter_df.pivot_table(
    index="pf_bin_center",   # y-axis rows
    columns="v_bin_center",  # x-axis cols
    values="count",
    fill_value=0,
)
grid = pivot.values.astype(float)   # shape (nPF, nV)
v_centers  = pivot.columns.values
pf_centers = pivot.index.values

dv  = v_centers[1]  - v_centers[0]
dpf = pf_centers[1] - pf_centers[0]
v_plot_edges  = np.append(v_centers  - dv  / 2, v_centers[-1]  + dv  / 2)
pf_plot_edges = np.append(pf_centers - dpf / 2, pf_centers[-1] + dpf / 2)

total_pq = int(scatter_df["count"].sum())

fig, ax = plt.subplots(figsize=(8, 6))
mesh = ax.pcolormesh(
    v_plot_edges,
    pf_plot_edges,
    grid,
    norm=mcolors.LogNorm(vmin=1, vmax=grid.max()),
    cmap="YlOrRd",
    rasterized=True,
)
fig.colorbar(mesh, ax=ax, label="Number of readings")

NOMINAL_V = 240
ax.axvline(NOMINAL_V, color="#1e3a8a", linewidth=1.2, linestyle="--",
           label=f"{NOMINAL_V} V nominal")
ax.axvline(0.9*NOMINAL_V, color="#6b7280", linewidth=0.9, linestyle=":",
           label="±10 % tolerance")
ax.axvline(1.1*NOMINAL_V, color="#6b7280", linewidth=0.9, linestyle=":",
           label="_nolegend_")

ax.text(0.02, 0.02, f"n = {total_pq:,} readings",
        transform=ax.transAxes, fontsize=8, color="gray", va="bottom")

ax.set_xlim(V_LO, V_HI)
ax.set_ylim(PF_LO, PF_HI)
ax.set_xlabel("Average voltage per heartbeat (V)", fontsize=11)
ax.set_ylabel("Average power factor per heartbeat", fontsize=11)
ax.set_title("Power Quality: Average Voltage vs. Power Factor\n"
             "(customer meters, all sites)", fontsize=12)
ax.legend(fontsize=9, loc="upper left")
ax.grid(linewidth=0.3, alpha=0.4)

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

fig, ax = plt.subplots(figsize=(10, 5))

for col, label, color, alpha in SERIES:
    sub = hist_df[hist_df["series"] == col]
    centers = sub["bin_center"].values
    counts  = sub["count"].values.astype(float)
    total   = counts.sum()
    density = counts / (total * BIN_WIDTH)
    mean_v  = (centers * counts).sum() / total

    ax.bar(centers, density, width=BIN_WIDTH, alpha=alpha, color=color,
           label=f"{label} voltage  (mean = {mean_v:.1f} V)",
           align="center", linewidth=0)

ax.axvline(NOMINAL_V, color="black",   linewidth=1.3, linestyle="--",
           label=f"{NOMINAL_V} V nominal")
ax.axvline(0.9*NOMINAL_V, color="#6b7280", linewidth=0.9, linestyle=":",
           label="±10 % tolerance")
ax.axvline(1.1*NOMINAL_V, color="#6b7280", linewidth=0.9, linestyle=":",
           label="_nolegend_")

total_v = int(hist_df[hist_df["series"] == "voltageAvg"]["count"].sum())
ax.text(0.98, 0.97, f"n = {total_v:,} heartbeats",
        transform=ax.transAxes, fontsize=8, color="gray", va="top", ha="right")

ax.set_xlim(NOMINAL_V-50, NOMINAL_V+50)   # zoom to the interesting range around 240 V nominal
ax.set_xlabel("Voltage (V)", fontsize=11)
ax.set_ylabel("Density", fontsize=11)
ax.set_title("Voltage Distribution: Minimum, Average, and Maximum per Heartbeat\n"
             "(customer meters, all sites)", fontsize=12)
ax.legend(fontsize=9)
ax.grid(axis="y", linewidth=0.3, alpha=0.4)

plt.tight_layout()
out = OUT_DIR / "voltage_histograms.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved {out}")
plt.close(fig)
