#!/usr/bin/env python3
"""
Extract power quality statistics from sparkmeterreadings for plotting.

Streams all parquet files in data/sparkmeterreadings/, accumulates binned
counts incrementally (no full dataset in memory), and saves:

  paper/graphics/power_quality_histograms.csv
      Binned counts for voltageMin, voltageAvg, and voltageMax per heartbeat.
      Columns: series, bin_center, count

  paper/graphics/power_quality_scatter.csv
      2D binned counts of voltageAvg vs. powerFactorAvg.
      Columns: v_bin_center, pf_bin_center, count  (zero-count cells omitted)

Filters applied:
  - meter_type == 'customer'
  - voltage in (50, 300] V  — excludes zero/idle readings and 3-phase outliers
  - powerFactorAvg in (0, 1] — excludes idle-meter zeros and encoding artefacts

Bin parameters are hardcoded here and must match plot_power_quality.py.

Usage:
  python figures/power_quality.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from tqdm import tqdm

OUT_DIR  = Path("paper/graphics")
DATA_DIR = Path("data/sparkmeterreadings")
OUT_DIR.mkdir(parents=True, exist_ok=True)

COLS = ["voltageMin", "voltageMax", "voltageAvg", "powerFactorAvg", "meter_type"]

V_LO,  V_HI,  V_BINS  = 50.0, 300.0, 250   # 1 V per bin
PF_LO, PF_HI, PF_BINS =  0.0,   1.0, 200   # 0.005 per bin

v_edges  = np.linspace(V_LO,  V_HI,  V_BINS  + 1)
pf_edges = np.linspace(PF_LO, PF_HI, PF_BINS + 1)

hist_vmin = np.zeros(V_BINS,            dtype=np.int64)
hist_vavg = np.zeros(V_BINS,            dtype=np.int64)
hist_vmax = np.zeros(V_BINS,            dtype=np.int64)
hist_2d   = np.zeros((V_BINS, PF_BINS), dtype=np.int64)

print("Loading sparkmeterreadings …")
site_dirs = sorted(d for d in DATA_DIR.iterdir() if d.is_dir())
for site_dir in tqdm(site_dirs, desc="sites", unit="site"):
    for parquet_path in sorted(site_dir.glob("*.parquet")):
        chunk = pq.read_table(parquet_path, columns=COLS).to_pandas()
        chunk = chunk[chunk["meter_type"] == "customer"]

        v_mask = (
            (chunk["voltageMin"] >  V_LO) & (chunk["voltageMin"] <= V_HI)
            & (chunk["voltageAvg"] >  V_LO) & (chunk["voltageAvg"] <= V_HI)
            & (chunk["voltageMax"] >  V_LO) & (chunk["voltageMax"] <= V_HI)
        )
        pf_mask = (chunk["powerFactorAvg"] > PF_LO) & (chunk["powerFactorAvg"] <= PF_HI)

        valid_v  = chunk.loc[v_mask]
        valid_pq = chunk.loc[v_mask & pf_mask]

        hist_vmin += np.histogram(valid_v["voltageMin"], bins=v_edges)[0].astype(np.int64)
        hist_vavg += np.histogram(valid_v["voltageAvg"], bins=v_edges)[0].astype(np.int64)
        hist_vmax += np.histogram(valid_v["voltageMax"], bins=v_edges)[0].astype(np.int64)

        h2d, _, _ = np.histogram2d(
            valid_pq["voltageAvg"], valid_pq["powerFactorAvg"],
            bins=[v_edges, pf_edges],
        )
        hist_2d += h2d.astype(np.int64)

# ── Histogram CSV ─────────────────────────────────────────────────────────────

v_centers = (v_edges[:-1] + v_edges[1:]) / 2
rows = []
for series, counts in [
    ("voltageMin", hist_vmin),
    ("voltageAvg", hist_vavg),
    ("voltageMax", hist_vmax),
]:
    for center, count in zip(v_centers, counts):
        rows.append({"series": series, "bin_center": round(float(center), 4), "count": int(count)})

out = OUT_DIR / "power_quality_histograms.csv"
pd.DataFrame(rows).to_csv(out, index=False)
print(f"Saved {out}")

# ── 2D scatter CSV (sparse: zero-count cells omitted) ─────────────────────────

pf_centers = (pf_edges[:-1] + pf_edges[1:]) / 2
vi, pi = np.where(hist_2d > 0)
scatter_df = pd.DataFrame({
    "v_bin_center":  np.round(v_centers[vi], 4),
    "pf_bin_center": np.round(pf_centers[pi], 4),
    "count":         hist_2d[vi, pi],
})

out = OUT_DIR / "power_quality_scatter.csv"
scatter_df.to_csv(out, index=False)
print(f"Saved {out}")

# ── Summary ───────────────────────────────────────────────────────────────────

total_v  = int(hist_vavg.sum())
total_pq = int(hist_2d.sum())
print(f"\n{total_v:,} heartbeats with valid voltage")
print(f"{total_pq:,} heartbeats with valid voltage and power factor")
