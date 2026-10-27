#!/usr/bin/env python3
"""
Extract power quality statistics from sparkmeterreadings for plotting.

Streams all parquet files in data/sparkmeterreadings/, accumulates binned
counts incrementally (no full dataset in memory), and saves per-country CSVs:

  paper/graphics/power_quality_histograms_{kenya,nigeria}.csv
      Binned counts for voltageMin, voltageAvg, and voltageMax per heartbeat.
      Columns: series, bin_center, count

  paper/graphics/power_quality_scatter_{kenya,nigeria}.csv
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
DATA_DIR = Path("data")
OUT_DIR.mkdir(parents=True, exist_ok=True)

COLS = ["voltageMin", "voltageMax", "voltageAvg", "powerFactorAvg", "meter_type",
        "meter_id", "heartbeatStart"]

# SMRPI-01-00018BCE at Kalobeyei 1A reported spurious ~132 V / PF~0.13 while
# idle (current=0) before a firmware update on 2022-03-08. Exclude those readings.
_BAD_METER_ID  = "d4be6f4d-9d59-4a8e-bff5-211b3fd51f94"
_BAD_METER_END = pd.Timestamp("2022-03-08")

V_LO,  V_HI,  V_BINS  = 50.0, 300.0, 250   # 1 V per bin
PF_LO, PF_HI, PF_BINS =  0.0,   1.0, 200   # 0.005 per bin

v_edges  = np.linspace(V_LO,  V_HI,  V_BINS  + 1)
pf_edges = np.linspace(PF_LO, PF_HI, PF_BINS + 1)

KENYA_SITES = frozenset([
    "Kakuma_3A",
    "Kalobeyei_Settlement_Village_1A",
    "Kalobeyei_Settlement_Village_1B",
    "Kalobeyei_Settlement_Village_2A",
    "Kalobeyei_Settlement_Village_2B",
    "Kalobeyei_Settlement_Village_3A",
    "Kalobeyei_Town",
    "Kangitan_Kori",
    "Kapelbok",
    "Katiko",
    "Locheremoit",
    "Lomekwi",
    "Lorengelup",
    "Nakukulas",
    "Ndeda",
    "Ngurunit",
    "Olkiramatian",
    "Oyamo",
    "Ringiti",
])

NIGERIA_SITES = frozenset([
    "Akipelai",
    "Balep",
    "Bendeghe-Afi",
    "Ekong_Anaku",
    "Emereoke",
    "Oloibiri",
    "Opu",
    "Ozuzu",
])

accumulators = {
    "kenya": {
        "hist_vmin": np.zeros(V_BINS,            dtype=np.int64),
        "hist_vavg": np.zeros(V_BINS,            dtype=np.int64),
        "hist_vmax": np.zeros(V_BINS,            dtype=np.int64),
        "hist_2d":   np.zeros((V_BINS, PF_BINS), dtype=np.int64),
    },
    "nigeria": {
        "hist_vmin": np.zeros(V_BINS,            dtype=np.int64),
        "hist_vavg": np.zeros(V_BINS,            dtype=np.int64),
        "hist_vmax": np.zeros(V_BINS,            dtype=np.int64),
        "hist_2d":   np.zeros((V_BINS, PF_BINS), dtype=np.int64),
    },
}

print("Loading sparkmeterreadings …")
site_files = sorted(
    f for f in DATA_DIR.glob("sparkmeterreadings_*.parquet")
    if not f.stem.startswith("sparkmeterreadings_clean_")
)
for parquet_path in tqdm(site_files, desc="sites", unit="site"):
    site = parquet_path.stem[len("sparkmeterreadings_"):]
    if site in KENYA_SITES:
        acc = accumulators["kenya"]
    elif site in NIGERIA_SITES:
        acc = accumulators["nigeria"]
    else:
        tqdm.write(f"  WARNING: unknown site {site!r}, skipping")
        continue

    chunk = pq.read_table(parquet_path, columns=COLS).to_pandas()
    chunk = chunk[chunk["meter_type"] == "customer"]
    chunk = chunk[~(
        (chunk["meter_id"] == _BAD_METER_ID)
        & (pd.to_datetime(chunk["heartbeatStart"]) < _BAD_METER_END)
    )]

    v_mask = (
        (chunk["voltageMin"] >  V_LO) & (chunk["voltageMin"] <= V_HI)
        & (chunk["voltageAvg"] >  V_LO) & (chunk["voltageAvg"] <= V_HI)
        & (chunk["voltageMax"] >  V_LO) & (chunk["voltageMax"] <= V_HI)
    )
    pf_mask = (chunk["powerFactorAvg"] > PF_LO) & (chunk["powerFactorAvg"] <= PF_HI)

    valid_v  = chunk.loc[v_mask]
    valid_pq = chunk.loc[v_mask & pf_mask]

    acc["hist_vmin"] += np.histogram(valid_v["voltageMin"], bins=v_edges)[0].astype(np.int64)
    acc["hist_vavg"] += np.histogram(valid_v["voltageAvg"], bins=v_edges)[0].astype(np.int64)
    acc["hist_vmax"] += np.histogram(valid_v["voltageMax"], bins=v_edges)[0].astype(np.int64)

    h2d, _, _ = np.histogram2d(
        valid_pq["voltageAvg"], valid_pq["powerFactorAvg"],
        bins=[v_edges, pf_edges],
    )
    acc["hist_2d"] += h2d.astype(np.int64)

v_centers  = (v_edges[:-1]  + v_edges[1:])  / 2
pf_centers = (pf_edges[:-1] + pf_edges[1:]) / 2

for country, acc in accumulators.items():
    # ── Histogram CSV ──────────────────────────────────────────────────────────
    rows = []
    for series, counts in [
        ("voltageMin", acc["hist_vmin"]),
        ("voltageAvg", acc["hist_vavg"]),
        ("voltageMax", acc["hist_vmax"]),
    ]:
        for center, count in zip(v_centers, counts):
            rows.append({"series": series, "bin_center": round(float(center), 4), "count": int(count)})

    out = OUT_DIR / f"power_quality_histograms_{country}.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"Saved {out}")

    # ── 2D scatter CSV (sparse: zero-count cells omitted) ──────────────────────
    vi, pi = np.where(acc["hist_2d"] > 0)
    scatter_df = pd.DataFrame({
        "v_bin_center":  np.round(v_centers[vi], 4),
        "pf_bin_center": np.round(pf_centers[pi], 4),
        "count":         acc["hist_2d"][vi, pi],
    })

    out = OUT_DIR / f"power_quality_scatter_{country}.csv"
    scatter_df.to_csv(out, index=False)
    print(f"Saved {out}")

# ── Summary ───────────────────────────────────────────────────────────────────

for country, acc in accumulators.items():
    total_v  = int(acc["hist_vavg"].sum())
    total_pq = int(acc["hist_2d"].sum())
    print(f"\n{country.capitalize()}: {total_v:,} heartbeats with valid voltage, "
          f"{total_pq:,} with valid voltage and power factor")
