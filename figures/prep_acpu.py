#!/usr/bin/env python3
"""
Aggregate sparkmeterreadings_clean parquet files into monthly per-customer
energy totals and save to data/acpu_monthly.csv.

Run this once before plot_acpu.py. Processing ~650M 15-min rows file-by-file
keeps peak memory manageable by aggregating before concatenating.

Usage:
  python figures/prep_acpu.py
"""

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT_CSV = Path("data/acpu_monthly.csv")

FILENAME_MAP: dict[str, tuple[str, str]] = {
    "Akipelai":                            ("Akipelai",              "Nigeria"),
    "Balep":                               ("Balep",                 "Nigeria"),
    "Bendeghe-Afi":                        ("Bendeghe-Afi",          "Nigeria"),
    "Ekong_Anaku":                         ("Ekong Anaku",           "Nigeria"),
    "Emereoke":                            ("Emereoke",              "Nigeria"),
    "Kakuma_3A":                           ("Kakuma 3 - Okapi",      "Kenya"),
    "Kalobeyei_Settlement_Village_1A":     ("Kalobeyei Settlement",  "Kenya"),
    "Kalobeyei_Settlement_Village_1B":     ("Kalobeyei Settlement",  "Kenya"),
    "Kalobeyei_Settlement_Village_2A":     ("Kalobeyei Settlement",  "Kenya"),
    "Kalobeyei_Settlement_Village_2B":     ("Kalobeyei Settlement",  "Kenya"),
    "Kalobeyei_Settlement_Village_3A":     ("Kalobeyei Settlement",  "Kenya"),
    "Kalobeyei_Town":                      ("Kalobeyei Town",        "Kenya"),
    "Kangitan_Kori":                       ("Kangitan Kori",         "Kenya"),
    "Kapelbok":                            ("Kapelbok",              "Kenya"),
    "Katiko":                              ("Katiko",                "Kenya"),
    "Locheremoit":                         ("Locheremoit",           "Kenya"),
    "Lomekwi":                             ("Lomekwi",               "Kenya"),
    "Lorengelup":                          ("Lorengelup",            "Kenya"),
    "Nakukulas":                           ("Nakukulas",             "Kenya"),
    "Ndeda":                               ("Ndeda",                 "Kenya"),
    "Ngurunit":                            ("Ngurunit",              "Kenya"),
    "Olkiramatian":                        ("Olkiramatian",          "Kenya"),
    "Oloibiri":                            ("Oloibiri",              "Nigeria"),
    "Opu":                                 ("Opu",                   "Nigeria"),
    "Oyamo":                               ("Oyamo",                 "Kenya"),
    "Ozuzu":                               ("Ozuzu",                 "Nigeria"),
    "Ringiti":                             ("Ringiti",               "Kenya"),
}

data_dir = Path("data/sparkmeterreadings_clean")
all_files = sorted(data_dir.glob("*.parquet"))
named_files = [f for f in all_files if not re.match(r"[0-9a-f]{8}-", f.stem)]

print(f"Processing {len(named_files)} site parquet files …")

monthly_chunks = []
for fpath in named_files:
    stem = fpath.stem
    if stem not in FILENAME_MAP:
        print(f"  Skipping unmapped file: {fpath.name}", file=sys.stderr)
        continue
    project_name, country = FILENAME_MAP[stem]

    df = pd.read_parquet(
        fpath,
        columns=["meter_customer_code", "meter_type", "slot_start", "energy_kwh", "tariff"],
    )
    df = df[df["meter_type"] == "customer"]
    df["cust_class"] = np.where(
        df["tariff"].str.strip().str.lower() == "residential",
        "Residential",
        "Commercial",
    )
    df["ym"] = df["slot_start"].dt.to_period("M").dt.strftime("%Y-%m")

    agg = (
        df.groupby(["meter_customer_code", "cust_class", "ym"], observed=True)["energy_kwh"]
        .sum()
        .reset_index()
        .rename(columns={"energy_kwh": "monthly_kwh"})
    )
    agg["projectName"] = project_name
    agg["country"]     = country
    monthly_chunks.append(agg)
    print(f"  {fpath.name}: {len(df):,} rows → {len(agg):,} user-months")

monthly = pd.concat(monthly_chunks, ignore_index=True)
print(f"\n  Total user-months: {len(monthly):,}")
print(f"  Unique customers:  {monthly['meter_customer_code'].nunique():,}")

monthly.to_csv(OUT_CSV, index=False)
print(f"\nSaved {OUT_CSV}")
