#!/usr/bin/env python3
"""
Aggregate sparkmeterreadings_clean parquet files into monthly per-customer
energy totals and save to paper/graphics/acpu_monthly.csv.

Run this once before plot_acpu.py. Processing ~650M 15-min rows file-by-file
keeps peak memory manageable by aggregating before concatenating.

Usage:
  python figures/prep_acpu.py
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

OUT_CSV = Path("paper/graphics/acpu_monthly.csv")

READ_COLUMNS = ["meter_customer_code", "meter_type", "slot_start", "energy_kwh", "tariff"]
BATCH_SIZE = 2_000_000

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

def aggregate_file(fpath):
    """
    Stream a site's parquet file in row-group batches and reduce straight
    to (customer, cust_class, ym) -> monthly_kwh. Full site files hold
    100M+ rows; loading them whole via pd.read_parquet (as string columns
    meter_customer_code/meter_type/tariff) exhausts memory on this machine.
    """
    acc: dict[tuple[str, str, str], float] = defaultdict(float)
    n_rows = 0
    pf = pq.ParquetFile(fpath)
    for batch in pf.iter_batches(batch_size=BATCH_SIZE, columns=READ_COLUMNS):
        bdf = batch.to_pandas()
        bdf = bdf[bdf["meter_type"] == "customer"]
        if bdf.empty:
            continue
        cust_class = np.where(bdf["tariff"].str.strip().str.lower() == "residential", "Residential", "Commercial")
        ym = bdf["slot_start"].dt.to_period("M").dt.strftime("%Y-%m")
        grouped = (
            bdf.assign(cust_class=cust_class, ym=ym)
            .groupby(["meter_customer_code", "cust_class", "ym"])["energy_kwh"]
            .sum()
        )
        for key, value in grouped.items():
            acc[key] += value
        n_rows += len(bdf)

    rows = [(cust, cls, ym, kwh) for (cust, cls, ym), kwh in acc.items()]
    agg = pd.DataFrame(rows, columns=["meter_customer_code", "cust_class", "ym", "monthly_kwh"])
    return agg, n_rows


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

    agg, n_rows = aggregate_file(fpath)
    agg["projectName"] = project_name
    agg["country"]     = country
    monthly_chunks.append(agg)
    print(f"  {fpath.name}: {n_rows:,} rows → {len(agg):,} user-months")

monthly = pd.concat(monthly_chunks, ignore_index=True)
print(f"\n  Total user-months: {len(monthly):,}")
print(f"  Unique customers:  {monthly['meter_customer_code'].nunique():,}")

monthly.to_csv(OUT_CSV, index=False)
print(f"\nSaved {OUT_CSV}")
