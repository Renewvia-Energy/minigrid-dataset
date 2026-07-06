#!/usr/bin/env python3
"""
Generate clean 15-minute energy time series from raw SparkMeter heartbeat data.

For each meter (identified by meter_customer_code + meter_type), this script:

  1. Sorts readings by heartbeatStart.
  2. Diffs the cumulative `energy` counter to get per-transition consumption.
  3. Nulls diffs where:
       - energy_diff < 0            (meter reset — counter rolled back)
       - state != 1 at either end   (error / off / unknown state)
  4. Builds a 96-slot daily load profile from consecutive single-slot transitions.
  5. For multi-slot gaps with a known total, redistributes energy proportionally
     using the load profile. Slots whose time-of-day bucket has no clean
     observations fall back to a uniform (constant) rate.
  6. Null-diff transitions produce no output rows (absent from clean series).

Output columns per site (data/sparkmeterreadings_clean/<site>.parquet):
  meter_customer_code   pseudonymized customer ID
  meter_type            'customer', 'totalizer', or 'pue'
  slot_start            UTC start of the 15-minute slot (matches heartbeatStart)
  energy_kwh            energy consumed during this slot (kWh)
  imputation_method     'observed' | 'profile' | 'uniform'
  tariff                most-common tariff name for this customer (e.g. 'Residential')

Usage:
  python scripts/clean_readings.py                    # process all sites (skip existing)
  python scripts/clean_readings.py <site>             # process one site by name (e.g. Akipelai)
  python scripts/clean_readings.py --overwrite        # reprocess all sites
  python scripts/clean_readings.py <site> --overwrite # reprocess one site
"""

import glob
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

SLOT_MINUTES = 15
SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES  # 96
SLOT_NS = SLOT_MINUTES * 60 * 1_000_000_000  # nanoseconds per slot

INPUT_DIR = Path("data/sparkmeterreadings")
OUTPUT_DIR = Path("data/sparkmeterreadings_clean")
COLS = ["meter_customer_code", "meter_type", "heartbeatStart", "energy", "state", "meter_tariff_name"]

OUTPUT_SCHEMA = pa.schema([
    pa.field("meter_customer_code", pa.string()),
    pa.field("meter_type", pa.string()),
    pa.field("slot_start", pa.timestamp("ns")),
    pa.field("energy_kwh", pa.float64()),
    pa.field("imputation_method", pa.string()),
    pa.field("tariff", pa.string()),
])


# ---------------------------------------------------------------------------
# Per-customer logic (fully vectorized — no Python loop over transitions)
# ---------------------------------------------------------------------------

def _slot_of_day(ts_ns: np.ndarray) -> np.ndarray:
    """Convert nanosecond timestamps to 0-95 time-of-day slot indices."""
    seconds_of_day = (ts_ns // 1_000_000_000) % 86400
    return (seconds_of_day // (SLOT_MINUTES * 60)).astype(int)


def _build_load_profile(t_prev_ns: np.ndarray, energy_diffs: np.ndarray):
    """
    96-slot daily load profile from clean (single-slot) transitions.

    Unobserved slots use the customer's overall mean (uniform fallback).

    Returns
    -------
    profile : np.ndarray shape (96,) — mean kWh per time-of-day slot
    slot_has_data : np.ndarray shape (96,) bool
    """
    idx = _slot_of_day(t_prev_ns)
    totals = np.zeros(SLOTS_PER_DAY)
    counts = np.zeros(SLOTS_PER_DAY, dtype=int)
    np.add.at(totals, idx, energy_diffs)
    np.add.at(counts, idx, 1)

    slot_has_data = counts > 0
    profile = np.where(slot_has_data, totals / np.maximum(counts, 1), 0.0)
    overall_mean = profile[slot_has_data].mean() if slot_has_data.any() else 0.0
    profile[~slot_has_data] = overall_mean
    return profile, slot_has_data


def process_customer(
    times_ns: np.ndarray,
    energy: np.ndarray,
    state: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Vectorised processing of one meter's sorted time series.

    Parameters
    ----------
    times_ns  : int64 nanosecond timestamps, already sorted ascending
    energy    : float64 cumulative energy (kWh)
    state     : float64 meter state codes (1 = normal)

    Returns
    -------
    slot_start_ns   : int64 array of slot start timestamps
    energy_kwh      : float64 array of per-slot energy
    methods         : object (str) array of imputation_method values
    raw_valid_total : float — sum of valid raw energy diffs (for conservation check)

    All array outputs have the same length. Returns empty arrays if there is
    insufficient data.
    """
    n = len(times_ns)
    if n < 2:
        empty = np.array([], dtype=np.int64)
        return empty, np.array([], dtype=np.float64), np.array([], dtype=object), 0.0

    diffs = np.diff(energy)
    time_diffs_ns = np.diff(times_ns)
    gap_slots = np.round(time_diffs_ns / SLOT_NS).astype(int)
    t_prev_ns = times_ns[:-1]

    state_filled = np.where(np.isnan(state), -1, state)
    valid = (
        (diffs >= 0)
        & (state_filled[:-1] == 1)
        & (state_filled[1:] == 1)
        & (gap_slots > 0)
    )
    clean = valid & (gap_slots == 1)

    if clean.any():
        profile, slot_has_data = _build_load_profile(t_prev_ns[clean], diffs[clean])
    else:
        profile = np.zeros(SLOTS_PER_DAY)
        slot_has_data = np.zeros(SLOTS_PER_DAY, dtype=bool)

    valid_idx = np.where(valid)[0]
    if len(valid_idx) == 0:
        empty = np.array([], dtype=np.int64)
        return empty, np.array([], dtype=np.float64), np.array([], dtype=object), 0.0

    # --- Vectorised expansion of all valid transitions ---
    n_slots_v = gap_slots[valid_idx]            # slots per transition
    t_prev_v = t_prev_ns[valid_idx]             # base timestamp per transition
    diffs_v = diffs[valid_idx]                  # energy per transition

    total_out = int(n_slots_v.sum())

    # rep_idx[k] = index into valid_idx for output row k
    rep_idx = np.repeat(np.arange(len(valid_idx)), n_slots_v)

    # slot offset within each transition
    slot_offset = np.concatenate([np.arange(n, dtype=np.int64) for n in n_slots_v])

    # absolute slot start timestamps
    slot_start_ns = t_prev_v[rep_idx] + slot_offset * SLOT_NS

    # time-of-day slot indices
    tod_idx = _slot_of_day(slot_start_ns)

    # which output rows are direct observations (single-slot transitions)
    is_single = n_slots_v == 1
    is_obs = is_single[rep_idx]

    # profile weights per slot
    weights = profile[tod_idx]

    # sum of profile weights per transition (needed for normalisation)
    w_sum_per_trans = np.zeros(len(valid_idx))
    np.add.at(w_sum_per_trans, rep_idx, weights)
    w_sum = w_sum_per_trans[rep_idx]

    total_per_slot = diffs_v[rep_idx]
    n_slots_per_slot = n_slots_v[rep_idx]

    safe_w_sum = np.where(w_sum > 0, w_sum, 1.0)  # avoid divide-by-zero in np.where
    energy_kwh = np.where(
        is_obs,
        total_per_slot,
        np.where(
            w_sum > 0,
            total_per_slot * weights / safe_w_sum,
            total_per_slot / n_slots_per_slot,
        ),
    )

    methods = np.where(
        is_obs,
        "observed",
        np.where(slot_has_data[tod_idx], "profile", "uniform"),
    )

    return slot_start_ns, energy_kwh, methods, float(diffs_v.sum())


# ---------------------------------------------------------------------------
# Site-level I/O
# ---------------------------------------------------------------------------

def process_site(site_dir: Path, output_path: Path) -> None:
    files = sorted(glob.glob(str(site_dir / "*.parquet")))
    if not files:
        return

    frames = [pd.read_parquet(f, columns=COLS) for f in files]
    df = pd.concat(frames, ignore_index=True)

    if df.empty:
        return

    # Normalise dtypes that vary across parquet files / years
    df["state"] = pd.to_numeric(df["state"], errors="coerce")
    df["energy"] = pd.to_numeric(df["energy"], errors="coerce")
    df["heartbeatStart"] = pd.to_datetime(df["heartbeatStart"])
    df = df.dropna(subset=["meter_customer_code"])
    df["meter_customer_code"] = df["meter_customer_code"].astype("category")
    df["meter_type"] = df["meter_type"].astype("category")

    # Most-common tariff per customer (constant per output row)
    tariff_map = (
        df.groupby("meter_customer_code", observed=True)["meter_tariff_name"]
        .agg(lambda s: s.dropna().mode().iloc[0] if s.dropna().any() else "Unknown")
        .to_dict()
    )

    groups = list(df.groupby(
        ["meter_customer_code", "meter_type"], observed=True, sort=False
    ))

    n_rows_out = 0
    raw_total = 0.0
    out_total = 0.0
    with pq.ParquetWriter(output_path, OUTPUT_SCHEMA) as writer:
        for (code, mtype), group in tqdm(groups, desc="meters", unit="meter", leave=False):
            g = group.sort_values("heartbeatStart")
            times_ns = g["heartbeatStart"].to_numpy(dtype="datetime64[ns]").view(np.int64)
            energy = g["energy"].to_numpy(dtype=float)
            state = g["state"].to_numpy(dtype=float)

            slot_ns, ekwh, methods, customer_raw_total = process_customer(times_ns, energy, state)
            if len(slot_ns) == 0:
                continue

            tariff = tariff_map.get(code, "Unknown")
            batch = pa.table({
                "meter_customer_code": pa.array([code] * len(slot_ns), pa.string()),
                "meter_type": pa.array([mtype] * len(slot_ns), pa.string()),
                "slot_start": pa.array(slot_ns, pa.timestamp("ns")),
                "energy_kwh": pa.array(ekwh, pa.float64()),
                "imputation_method": pa.array(methods, pa.string()),
                "tariff": pa.array([tariff] * len(slot_ns), pa.string()),
            })
            writer.write_table(batch)
            n_rows_out += len(slot_ns)
            raw_total += customer_raw_total
            out_total += float(ekwh.sum())

    n_meters = len(groups)
    conservation_ok = np.isclose(raw_total, out_total, rtol=1e-5)
    check = "✓" if conservation_ok else "!! MISMATCH"
    print(f"{n_meters} meters → {n_rows_out:,} rows | energy {check} ({out_total:.3f} kWh)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    all_sites = sorted(
        d for d in INPUT_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")
    )

    args = sys.argv[1:]
    overwrite = "--overwrite" in args
    args = [a for a in args if a != "--overwrite"]

    if args:
        name = args[0]
        matching = [d for d in all_sites if d.name == name]
        if not matching:
            print(f"No site named '{name}'. Available sites:")
            for d in all_sites:
                print(f"  {d.name}")
            sys.exit(1)
        sites = matching
    else:
        sites = all_sites

    print(f"Processing {len(sites)} site(s) → {OUTPUT_DIR}/")

    for site_dir in sites:
        output_path = OUTPUT_DIR / f"{site_dir.name}.parquet"
        if output_path.exists() and not overwrite:
            print(f"  [skip] {site_dir.name}")
            continue
        print(f"  [proc] {site_dir.name}")
        t0 = time.time()
        process_site(site_dir, output_path)
        print(f"  ({time.time() - t0:.0f}s)")

    print("Done.")


if __name__ == "__main__":
    main()
