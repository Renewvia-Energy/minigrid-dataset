#!/usr/bin/env python3
"""
Carbon accounting per AMS-III.BB for all Renewvia mini-grid sites.

Emission factors applied to energy consumed that displaces a diesel/grid baseline:
  Residential customers:
    First 0.055 MWh (55 kWh) per customer-year: 2.72 tCO2e/MWh
    Above 0.055 MWh per customer-year:           0.80 tCO2e/MWh
  All other customers:                           0.80 tCO2e/MWh (flat)

Steps:
  1. Load sparkmeterreadings_clean for all named sites (UUID exports excluded).
  2. Sum annual kWh per customer per project per year.
  3. Apply emission factors → tCO2e avoided per customer-year.
  4. Aggregate to project-year totals.
  5. Drop the first and last calendar year per project (partial years).
  6. Average remaining full years → one tCO2e/year estimate per project.
  7. Save summary table to paper/graphics/carbon_accounting.csv.

Usage:
  python figures/carbon_accounting.py
"""

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

READ_COLUMNS = ["meter_customer_code", "meter_type", "slot_start", "energy_kwh", "tariff"]
BATCH_SIZE = 2_000_000

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESIDENTIAL_THRESHOLD_KWH = 55.0        # 0.055 MWh in kWh
EF_RESIDENTIAL_BELOW = 2.72 / 1000     # tCO2e/kWh
EF_ABOVE = 0.80 / 1000                 # tCO2e/kWh (residential above threshold + all others)

CLEAN_DIR = Path("data/sparkmeterreadings_clean")
OUT_DIR = Path("paper/graphics")

# ---------------------------------------------------------------------------
# File stem → project name mapping
# Kalobeyei sub-sites (including Kakuma 3A) roll up to one project entry.
# All other stems: replace underscores with spaces.
# ---------------------------------------------------------------------------

STEM_OVERRIDES = {
    "Kalobeyei_Settlement_Village_1A": "Kalobeyei Settlement",
    "Kalobeyei_Settlement_Village_1B": "Kalobeyei Settlement",
    "Kalobeyei_Settlement_Village_2A": "Kalobeyei Settlement",
    "Kalobeyei_Settlement_Village_2B": "Kalobeyei Settlement",
    "Kalobeyei_Settlement_Village_3A": "Kalobeyei Settlement",
    "Kakuma_3A": "Kalobeyei Settlement",
}


def stem_to_project(stem: str) -> str:
    return STEM_OVERRIDES.get(stem, stem.replace("_", " "))


# ---------------------------------------------------------------------------
# Load and process all named sites
# ---------------------------------------------------------------------------

def is_uuid(stem: str) -> bool:
    return len(stem) == 36 and stem.count("-") == 4


def annualize_file(f: Path) -> pd.DataFrame:
    """
    Stream a single site's parquet file in row-group batches and reduce
    straight to (customer, year, is_residential) -> annual_kwh. Full site
    files hold 100M+ rows; loading them whole (or concatenating many sites
    before aggregating) exhausts memory on this machine.
    """
    acc: dict[tuple[str, int, bool], float] = defaultdict(float)
    n_rows = 0
    pf = pq.ParquetFile(f)
    for batch in pf.iter_batches(batch_size=BATCH_SIZE, columns=READ_COLUMNS):
        bdf = batch.to_pandas()
        bdf = bdf[bdf["meter_type"] == "customer"]
        if bdf.empty:
            continue
        year = bdf["slot_start"].dt.year
        is_residential = bdf["tariff"].str.contains("Residential", case=False, na=False)
        grouped = (
            bdf.assign(year=year, is_residential=is_residential)
            .groupby(["meter_customer_code", "year", "is_residential"])["energy_kwh"]
            .sum()
        )
        for key, value in grouped.items():
            acc[key] += value
        n_rows += len(bdf)

    rows = [(cust, yr, res, kwh) for (cust, yr, res), kwh in acc.items()]
    annual = pd.DataFrame(rows, columns=["meter_customer_code", "year", "is_residential", "annual_kwh"])
    return annual, n_rows


def load_all_sites() -> pd.DataFrame:
    frames = []
    for f in sorted(CLEAN_DIR.glob("*.parquet")):
        if is_uuid(f.stem):
            continue
        project = stem_to_project(f.stem)
        annual, n_rows = annualize_file(f)
        annual["project"] = project
        frames.append(annual)
        print(f"  Loaded {f.stem} → '{project}' ({n_rows:,} rows)")

    annual = pd.concat(frames, ignore_index=True)
    # Kalobeyei sub-sites roll up to one project; re-sum in case a customer
    # code recurs across sub-site files under the same rolled-up project.
    annual = (
        annual.groupby(["project", "meter_customer_code", "year", "is_residential"], as_index=False)
        ["annual_kwh"].sum()
    )
    return annual


# ---------------------------------------------------------------------------
# AMS-III.BB emission factor calculation
# ---------------------------------------------------------------------------

def compute_co2e(annual_kwh: pd.Series, is_residential: pd.Series) -> pd.Series:
    """
    Vectorised AMS-III.BB formula.
    Returns tCO2e avoided for each customer-year row.
    """
    below = annual_kwh.clip(upper=RESIDENTIAL_THRESHOLD_KWH)
    above = (annual_kwh - RESIDENTIAL_THRESHOLD_KWH).clip(lower=0)

    co2e_residential = below * EF_RESIDENTIAL_BELOW + above * EF_ABOVE
    co2e_other = annual_kwh * EF_ABOVE

    return np.where(is_residential, co2e_residential, co2e_other)


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading clean readings...")
    annual = load_all_sites()

    annual["co2e_tonne"] = compute_co2e(annual["annual_kwh"], annual["is_residential"])

    # Project-year totals
    proj_year = (
        annual.groupby(["project", "year"])["co2e_tonne"]
        .sum()
        .reset_index()
    )

    # Drop first and last calendar year per project (partial years)
    year_range = proj_year.groupby("project")["year"].agg(["min", "max"])
    proj_year = proj_year.merge(year_range, on="project")
    proj_year = proj_year[(proj_year["year"] > proj_year["min"]) & (proj_year["year"] < proj_year["max"])]
    proj_year = proj_year.drop(columns=["min", "max"])

    n_full_years = proj_year.groupby("project")["year"].nunique()
    dropped = [p for p in annual["project"].unique() if p not in proj_year["project"].unique()]
    if dropped:
        print(f"  Warning: no full calendar years remaining for: {dropped}")

    # Average annual CO2e per project
    avg_co2e = proj_year.groupby("project")["co2e_tonne"].mean().reset_index(name="avg_annual_co2e")
    avg_co2e = avg_co2e.merge(n_full_years.rename("n_years"), on="project")

    # Customer count per project (all-time unique customers)
    cust_count = annual.groupby("project")["meter_customer_code"].nunique().reset_index(name="customer_count")

    # Project metadata
    proj_meta = pd.read_parquet(
        "data/minigridprojects/data.parquet",
        columns=["projectName", "sizePv", "capex"],
    ).rename(columns={"projectName": "project"})

    # Merge everything
    result = (
        avg_co2e
        .merge(cust_count, on="project")
        .merge(proj_meta, on="project", how="left")
    )

    out_cols = ["project", "avg_annual_co2e", "n_years", "customer_count", "sizePv", "capex"]
    print("\nProject summary:")
    print(result[out_cols].sort_values("avg_annual_co2e", ascending=False).to_string(index=False))

    outfile = OUT_DIR / "carbon_accounting.csv"
    result[out_cols].sort_values("avg_annual_co2e", ascending=False).to_csv(outfile, index=False)
    print(f"\nSaved {outfile.resolve()}")


if __name__ == "__main__":
    main()
