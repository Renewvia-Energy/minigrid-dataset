#!/usr/bin/env python3
"""
Compute 24-hour load profile statistics for one or more tariffs.

Reads sparkmeterreadings parquet files, filters to customers whose most-common
tariff contains the given string (case-insensitive substring match), and writes
summary CSVs to paper/graphics/ for use by plot_load_profile.py.

Run before plot_load_profile.py.

Outputs:
  paper/graphics/load_profile_stats_{tariff_slug}.csv
      One file per tariff. 120 rows: groups 0-95 with type="slot" (15-min
      bins), then groups 0-23 with type="hour".
      Columns: type, group, mean, std, n, median, q1, q3.

  paper/graphics/load_profile_meta.csv
      One row per tariff processed in this run.
      Columns: tariff, tariff_slug, n_customers, n_obs, n_sites,
               site_label, site_slug, tz_label, observed_only.

Usage:
  python figures/prep_load_profile.py --all --tariffs Residential Commercial
  python figures/prep_load_profile.py data/sparkmeterreadings_clean_Ndeda.parquet --tariffs Residential
  python figures/prep_load_profile.py --all --tariffs Residential --utc-offset 3 --observed-only
"""

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

SLOT_MINUTES = 15
BATCH_SIZE = 2_000_000
SHUFFLE_BATCH_SIZE = 10_000_000
OUT_DIR = Path("paper/graphics")


def most_common_tariff_by_customer(raw_files):
    """
    Tally (customer, tariff) occurrences using Arrow's native group_by
    instead of pandas: converting these columns to pandas object dtype
    (tens of millions of individual Python string allocations, most of
    them repeats of a small set of values) is what exhausts memory here,
    not the row count itself.
    """
    # Stream and column-project each file individually rather than building
    # one multi-file Dataset: some years (e.g. an early partial year with
    # zero readings) have meter_customer_code/meter_tariff_name typed `null`
    # by parquet since every value is null, which fails Dataset's automatic
    # schema unification against years typed `string`. Casting explicitly
    # per batch sidesteps that; streaming with bounded readahead keeps a
    # multi-year raw file (tens of millions of rows) from spiking memory.
    scan_kwargs = dict(batch_size=BATCH_SIZE, batch_readahead=1, fragment_readahead=1, use_threads=False)
    tables = []
    for f in raw_files:
        scanner = ds.dataset(f, format="parquet").scanner(
            columns=["meter_customer_code", "meter_tariff_name"], **scan_kwargs
        )
        batches = []
        for batch in scanner.to_batches():
            cust = batch.column("meter_customer_code").cast(pa.string())
            tariff = batch.column("meter_tariff_name").cast(pa.string())
            valid = pc.is_valid(tariff)
            filtered = pa.record_batch(
                [pc.filter(cust, valid), pc.filter(tariff, valid)],
                names=["meter_customer_code", "meter_tariff_name"],
            )
            if filtered.num_rows:
                batches.append(filtered)
        if batches:
            tables.append(pa.Table.from_batches(batches))
    table = pa.concat_tables(tables)
    counts = (
        table.group_by(["meter_customer_code", "meter_tariff_name"])
        .aggregate([("meter_tariff_name", "count")])
        .to_pandas()
    )
    idx = counts.groupby("meter_customer_code")["meter_tariff_name_count"].idxmax()
    return counts.loc[idx].set_index("meter_customer_code")["meter_tariff_name"]


def load_site_reduced(clean_path, matching_codes, utc_offset, observed_only):
    """
    Filter a site's clean parquet file to matching customers using Arrow's
    dataset scanner (filter pushdown into the native engine, no pandas
    object columns materialized for excluded rows) and reduce immediately
    to (tod_slot, tod_hour, energy_kwh). Full clean files hold tens of
    millions of rows; loading them into pandas string columns exhausts
    memory on this machine even when most rows are filtered right back out.
    """
    dataset = ds.dataset(clean_path, format="parquet")
    filter_expr = (ds.field("meter_type") == "customer") & ds.field("meter_customer_code").isin(
        list(matching_codes)
    )
    if observed_only:
        filter_expr = filter_expr & (ds.field("imputation_method") == "observed")

    scan_kwargs = dict(batch_size=BATCH_SIZE, batch_readahead=1, fragment_readahead=1, use_threads=False)

    # Count first so the output arrays can be allocated once; accumulating a
    # list of per-batch arrays and concatenating at the end briefly holds
    # both the fragmented parts and the final array at once (~2x peak), which
    # is enough to exhaust memory on this machine for large sites.
    n_matching = dataset.scanner(columns=["slot_start"], filter=filter_expr, **scan_kwargs).count_rows()
    tod_slot = np.empty(n_matching, dtype="int16")
    tod_hour = np.empty(n_matching, dtype="int8")
    energy_kwh = np.empty(n_matching, dtype="float64")

    pos = 0
    scanner = dataset.scanner(columns=["slot_start", "energy_kwh"], filter=filter_expr, **scan_kwargs)
    for batch in scanner.to_batches():
        n = batch.num_rows
        if n == 0:
            continue
        bdf = batch.to_pandas()
        slot_start_local = bdf["slot_start"] + pd.Timedelta(hours=utc_offset)
        minutes = slot_start_local.dt.hour * 60 + slot_start_local.dt.minute
        tod_slot[pos:pos + n] = (minutes // SLOT_MINUTES).to_numpy()
        tod_hour[pos:pos + n] = slot_start_local.dt.hour.to_numpy()
        energy_kwh[pos:pos + n] = bdf["energy_kwh"].to_numpy()
        pos += n

    return pd.DataFrame({"tod_slot": tod_slot, "tod_hour": tod_hour, "energy_kwh": energy_kwh})


def stats_row(grp, arr):
    n = arr.size
    if n == 0:
        return {"grp": grp, "mean": np.nan, "std": np.nan, "n": 0, "median": np.nan, "q1": np.nan, "q3": np.nan}
    return {
        "grp": grp,
        "mean": arr.mean(),
        "std": arr.std(ddof=1) if n > 1 else np.nan,
        "n": n,
        "median": np.quantile(arr, 0.5),
        "q1": np.quantile(arr, 0.25),
        "q3": np.quantile(arr, 0.75),
    }


def shuffle_to_slot_files(flat_files, tmp_path, n_slots=96):
    """
    Single streaming pass over every site's flat reduced file, splitting
    rows into one file per tod_slot value (0..95) via persistent writer
    handles. Calling ds.write_dataset once per site instead (hive
    partitioning into 96 directories, 27 times) spent 35+ minutes on a
    single large site alone — repeated per-call overhead against a growing
    set of partition directories. One combined single-threaded pass with
    the 96 output files opened once is far cheaper.
    """
    paths = [tmp_path / f"slot_{i}.parquet" for i in range(n_slots)]
    writers = [None] * n_slots
    dataset = ds.dataset(flat_files, format="parquet")
    scanner = dataset.scanner(
        columns=["tod_slot", "energy_kwh"],
        batch_size=SHUFFLE_BATCH_SIZE,
        batch_readahead=1,
        fragment_readahead=1,
        use_threads=False,
    )
    try:
        for batch in scanner.to_batches():
            if batch.num_rows == 0:
                continue
            slots = batch.column("tod_slot").to_numpy()
            energy = batch.column("energy_kwh")
            for slot in np.unique(slots):
                sub = pa.table({"energy_kwh": pc.filter(energy, pa.array(slots == slot))})
                if writers[slot] is None:
                    writers[slot] = pq.ParquetWriter(paths[slot], sub.schema)
                writers[slot].write_table(sub)
    finally:
        for w in writers:
            if w is not None:
                w.close()
    return paths


def compute_group_stats(slot_paths):
    """
    Read the tod_slot-shuffled data back one slot (of 96) at a time and
    compute exact mean/std/count/median/IQR with numpy. A slot's data across
    all sites is a small, bounded slice (~total_rows/96); processing one
    slot at a time keeps memory well under this machine's limit, unlike
    materializing the combined ~700M-row dataset (or DuckDB's own grouped
    quantile computation over it, which spills to disk so slowly it still
    gets OOM-killed before finishing). Slot and hour stats are produced in
    the same pass since tod_hour is just tod_slot // 4.
    """
    slot_rows = []
    hour_rows = []
    for hour in range(24):
        hour_arrays = []
        for slot in range(4 * hour, 4 * hour + 4):
            p = slot_paths[slot]
            arr = pq.read_table(p, columns=["energy_kwh"])["energy_kwh"].to_numpy() if p.exists() else np.array([], dtype="float64")
            slot_rows.append(stats_row(slot, arr))
            hour_arrays.append(arr)
        hour_arr = np.concatenate(hour_arrays) if hour_arrays else np.array([], dtype="float64")
        hour_rows.append(stats_row(hour, hour_arr))

    return {
        "tod_slot": pd.DataFrame(slot_rows).set_index("grp").reindex(range(96)),
        "tod_hour": pd.DataFrame(hour_rows).set_index("grp").reindex(range(24)),
    }


def compute_stats_for_tariff(tariff, file_paths, utc_by_station, utc_offset_override, observed_only):
    """Full pipeline for one tariff string: load sites, shuffle, compute slot/hour stats."""
    tmp_dir_ctx = tempfile.TemporaryDirectory(prefix="load_profile_")
    tmp_path = Path(tmp_dir_ctx.name)
    flat_files = []
    site_names = []
    utc_offsets = []
    n_meters_total = 0
    n_obs_total = 0

    for clean_path in file_paths:
        site_name = clean_path.stem.removeprefix("sparkmeterreadings_clean_")
        data_root = clean_path.parent

        if utc_offset_override is not None:
            utc_offset = utc_offset_override
        elif utc_by_station is not None and site_name in utc_by_station.index and pd.notna(utc_by_station[site_name]):
            utc_offset = int(utc_by_station[site_name])
        else:
            print(f"Warning: UTC offset not found for '{site_name}'.", file=sys.stderr)
            while True:
                raw = input(f"  Enter UTC offset in hours for {site_name} (e.g. 3): ").strip()
                try:
                    utc_offset = int(raw)
                    break
                except ValueError:
                    print("  Please enter an integer.", file=sys.stderr)

        print(f"Site: {site_name}  |  UTC offset: {utc_offset:+d}h")

        raw_path = data_root / f"sparkmeterreadings_{site_name}.parquet"
        if not raw_path.exists():
            print(f"Error: raw parquet file not found: {raw_path}", file=sys.stderr)
            sys.exit(1)

        most_common_tariff = most_common_tariff_by_customer([raw_path])
        matching_codes = most_common_tariff[
            most_common_tariff.str.contains(tariff, case=False, na=False)
        ].index

        if matching_codes.empty:
            print(
                f"  Warning: no meters found with tariff containing '{tariff}' at {site_name}. "
                f"Available tariffs: {most_common_tariff.dropna().unique().tolist()}",
                file=sys.stderr,
            )
            continue

        print(f"  Tariff filter '{tariff}': {len(matching_codes)} meters matched")
        n_meters_total += len(matching_codes)

        site_df = load_site_reduced(clean_path, matching_codes, utc_offset, observed_only)
        n_obs_total += len(site_df)
        site_file = tmp_path / f"{site_name}.parquet"
        site_df.to_parquet(site_file, index=False)
        del site_df
        flat_files.append(str(site_file))
        site_names.append(site_name)
        utc_offsets.append(utc_offset)

    if not flat_files:
        tmp_dir_ctx.cleanup()
        return None

    print(f"Rows after filtering ({tariff}): {n_obs_total:,}")

    slot_paths = shuffle_to_slot_files(flat_files, tmp_path)
    group_stats = compute_group_stats(slot_paths)
    tmp_dir_ctx.cleanup()

    return group_stats, site_names, utc_offsets, n_meters_total, n_obs_total


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(
    description="Compute load profile statistics and write CSVs for plot_load_profile.py."
)
parser.add_argument(
    "parquet_files",
    nargs="*",
    help="Path(s) to sparkmeterreadings_clean_*.parquet files. Omit when using --all.",
)
parser.add_argument(
    "--all", action="store_true", dest="use_all",
    help="Use all parquet files in data/sparkmeterreadings_clean/.",
)
parser.add_argument(
    "--tariffs", nargs="+", required=True, metavar="TARIFF",
    help="One or more tariff strings to process (case-insensitive substring match).",
)
parser.add_argument(
    "--utc-offset", type=int, default=None, metavar="HOURS",
    help="UTC offset in hours applied to all sites. Looked up per site from minigridprojects if omitted.",
)
parser.add_argument(
    "--observed-only", action="store_true",
    help="Include only slots with imputation_method='observed' (direct meter readings).",
)
args = parser.parse_args()

# ---------------------------------------------------------------------------
# Resolve parquet file paths
# ---------------------------------------------------------------------------
if args.use_all:
    if args.parquet_files:
        print("Error: cannot combine --all with explicit parquet files.", file=sys.stderr)
        sys.exit(1)
    data_dir = Path("data")
    file_paths = sorted(data_dir.glob("sparkmeterreadings_clean_*.parquet"))
    if not file_paths:
        print(f"Error: no sparkmeterreadings_clean_*.parquet files found in {data_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"Using all {len(file_paths)} clean site parquet files in {data_dir}")
else:
    if not args.parquet_files:
        print("Error: provide parquet file(s) or use --all.", file=sys.stderr)
        sys.exit(1)
    file_paths = [Path(p) for p in args.parquet_files]

# ---------------------------------------------------------------------------
# Load UTC offsets once (shared across all tariff runs)
# ---------------------------------------------------------------------------
utc_by_station = None
if args.utc_offset is None:
    data_root = file_paths[0].parent
    stations = pd.read_parquet(
        data_root / "meteringbasestations.parquet",
        columns=["meteringBaseStation", "projectName"],
    )
    proj = pd.read_parquet(
        data_root / "minigridprojects.parquet",
        columns=["projectName", "timezoneOffsetUtc"],
    )
    utc_by_station = (
        stations.merge(proj, on="projectName", how="left")
        .set_index(stations["meteringBaseStation"].str.replace(" ", "_"))
        ["timezoneOffsetUtc"]
    )

OUT_DIR.mkdir(parents=True, exist_ok=True)
meta_rows = []

# ---------------------------------------------------------------------------
# Process each tariff
# ---------------------------------------------------------------------------
for tariff in args.tariffs:
    print(f"\n=== Processing tariff: {tariff} ===")
    result = compute_stats_for_tariff(
        tariff, file_paths, utc_by_station, args.utc_offset, args.observed_only
    )
    if result is None:
        print(f"  Skipping '{tariff}': no matching meters found.", file=sys.stderr)
        continue
    group_stats, site_names, utc_offsets, n_meters, n_obs = result

    # Write stats CSV: slot rows (0-95) then hour rows (0-23)
    slot_df = group_stats["tod_slot"].copy()
    slot_df.index.name = "group"
    slot_df.insert(0, "type", "slot")
    hour_df = group_stats["tod_hour"].copy()
    hour_df.index.name = "group"
    hour_df.insert(0, "type", "hour")
    stats_df = pd.concat([slot_df.reset_index(), hour_df.reset_index()])

    tariff_slug = tariff.lower().replace(" ", "_").replace("/", "_")
    stats_path = OUT_DIR / f"load_profile_stats_{tariff_slug}.csv"
    stats_df.to_csv(stats_path, index=False)
    print(f"  Saved {stats_path.resolve()}")

    # Build site labels
    n_sites = len(site_names)
    if n_sites == 1:
        site_label = site_names[0]
        site_slug = site_names[0]
    elif n_sites <= 3:
        site_label = " + ".join(site_names)
        site_slug = "_".join(site_names)
    else:
        site_label = f"{n_sites} Sites"
        site_slug = f"{n_sites}_sites"

    unique_offsets = sorted(set(utc_offsets))
    tz_label = f"UTC{unique_offsets[0]:+d}" if len(unique_offsets) == 1 else "local time"

    meta_rows.append({
        "tariff":       tariff,
        "tariff_slug":  tariff_slug,
        "n_customers":  n_meters,
        "n_obs":        n_obs,
        "n_sites":      n_sites,
        "site_label":   site_label,
        "site_slug":    site_slug,
        "tz_label":     tz_label,
        "observed_only": args.observed_only,
    })

if not meta_rows:
    print("Error: no tariffs produced output.", file=sys.stderr)
    sys.exit(1)

meta_path = OUT_DIR / "load_profile_meta.csv"
pd.DataFrame(meta_rows).to_csv(meta_path, index=False)
print(f"\nSaved {meta_path.resolve()}")
