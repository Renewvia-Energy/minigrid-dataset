#!/usr/bin/env python3
"""
Plot the 24-hour average load profile for a given tariff across one or more sites.

Outputs four plots for each run (all combinations of aggregation and spread):
  - mean + 95% CI, 15-minute slots
  - mean + 95% CI, hourly totals
  - median + Q1–Q3, 15-minute slots
  - median + Q1–Q3, hourly totals

Customers are identified by joining to the raw SparkMeter tariff names
(meter_tariff_name containing the given tariff string, case-insensitive).
The UTC offset is looked up from minigridprojects unless overridden.

Usage:
  python figures/plot_load_profile.py <parquet_file> [<parquet_file> ...] <tariff> [options]
  python figures/plot_load_profile.py --all <tariff> [options]

Examples:
  python figures/plot_load_profile.py data/sparkmeterreadings_clean/Ndeda.parquet Residential
  python figures/plot_load_profile.py data/sparkmeterreadings_clean/Akipelai.parquet Residential --utc-offset 3
  python figures/plot_load_profile.py data/sparkmeterreadings_clean/Ndeda.parquet data/sparkmeterreadings_clean/Akipelai.parquet Residential
  python figures/plot_load_profile.py --all Residential

Optional arguments:
  --all               Use all parquet files in data/sparkmeterreadings_clean/
  --utc-offset INT    UTC offset in hours (applied to all sites; default: looked up per site)
  --observed-only     Include only slots with imputation_method='observed'
"""

import argparse
import sys
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend; remove to show a window
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

SLOT_MINUTES = 15
BATCH_SIZE = 2_000_000
SHUFFLE_BATCH_SIZE = 10_000_000


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


parser = argparse.ArgumentParser(
    description="Plot 24-hour load profile from clean sparkmeterreadings parquet file(s)."
)
parser.add_argument(
    "parquet_files",
    nargs="+",
    help="Path(s) to site parquet(s) in data/sparkmeterreadings_clean/. Last positional argument is the tariff. With --all, the only positional argument is the tariff.",
)
parser.add_argument(
    "--all", action="store_true", dest="use_all",
    help="Use all parquet files in data/sparkmeterreadings_clean/ instead of specifying files explicitly.",
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

# Last positional arg is the tariff; the rest are parquet files
if args.use_all:
    if len(args.parquet_files) != 1:
        print("Error: with --all, provide only the tariff as a positional argument.", file=sys.stderr)
        sys.exit(1)
    tariff = args.parquet_files[0]
    clean_dir = Path("data/sparkmeterreadings_clean")
    file_paths = sorted(clean_dir.glob("*.parquet"))
    if not file_paths:
        print(f"Error: no parquet files found in {clean_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"Using all {len(file_paths)} parquet files in {clean_dir}")
else:
    tariff = args.parquet_files[-1]
    file_paths = [Path(p) for p in args.parquet_files[:-1]]
    if not file_paths:
        print("Error: at least one parquet file must be provided before the tariff.", file=sys.stderr)
        sys.exit(1)

# ---------------------------------------------------------------------------
# Load meteringbasestations + minigridprojects once for UTC offset lookups
# ---------------------------------------------------------------------------
utc_by_station = None
if args.utc_offset is None:
    data_root = file_paths[0].parent.parent
    stations = pd.read_parquet(
        data_root / "meteringbasestations" / "data.parquet",
        columns=["meteringBaseStation", "projectName"],
    )
    proj = pd.read_parquet(
        data_root / "minigridprojects" / "data.parquet",
        columns=["projectName", "timezoneOffsetUtc"],
    )
    utc_by_station = (
        stations.merge(proj, on="projectName", how="left")
        .set_index(stations["meteringBaseStation"].str.replace(" ", "_"))
        ["timezoneOffsetUtc"]
    )

# ---------------------------------------------------------------------------
# Loop over sites: resolve UTC offset, find matching meters, load clean data.
# Each site's reduced readings are spilled to a flat temp parquet file
# rather than kept in a Python list: across all 27 sites the combined
# reduced data can run into the multiple-GB range, more than this machine's
# RAM holds at once. They get shuffled into tod_slot-partitioned files in a
# single combined pass afterward (see shuffle_to_slot_files), rather than
# partitioning per site here, which was far slower.
# ---------------------------------------------------------------------------
tmp_dir_ctx = tempfile.TemporaryDirectory(prefix="load_profile_")
tmp_path = Path(tmp_dir_ctx.name)
flat_files = []
site_names = []
utc_offsets = []
n_meters_total = 0
n_obs_total = 0

for clean_path in file_paths:
    site_name = clean_path.stem
    data_root = clean_path.parent.parent

    # Resolve UTC offset for this site
    if args.utc_offset is not None:
        utc_offset = args.utc_offset
    elif site_name in utc_by_station.index and pd.notna(utc_by_station[site_name]):
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

    # Find matching customer codes from raw data
    raw_dir = data_root / "sparkmeterreadings" / site_name
    raw_files = sorted(raw_dir.glob("*.parquet"))
    if not raw_files:
        print(f"Error: no raw parquet files found in {raw_dir}", file=sys.stderr)
        sys.exit(1)

    most_common_tariff = most_common_tariff_by_customer(raw_files)
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

    # Load and filter clean data, streamed in batches to bound memory use,
    # then spill straight to disk rather than holding it alongside other sites.
    site_df = load_site_reduced(clean_path, matching_codes, utc_offset, args.observed_only)
    n_obs_total += len(site_df)
    site_file = tmp_path / f"{site_name}.parquet"
    site_df.to_parquet(site_file, index=False)
    del site_df
    flat_files.append(str(site_file))
    site_names.append(site_name)
    utc_offsets.append(utc_offset)

if not flat_files:
    print(f"Error: no matching meters found across any of the provided sites.", file=sys.stderr)
    tmp_dir_ctx.cleanup()
    sys.exit(1)

print(f"Rows after filtering: {n_obs_total:,}")

# ---------------------------------------------------------------------------
# Shared labels / slugs (computed once)
# ---------------------------------------------------------------------------
if len(site_names) == 1:
    site_label = site_names[0]
    site_slug = site_names[0]
elif len(site_names) <= 3:
    site_label = " + ".join(site_names)
    site_slug = "_".join(site_names)
else:
    site_label = f"{len(site_names)} Sites"
    site_slug = f"{len(site_names)}_sites"

unique_offsets = sorted(set(utc_offsets))
tz_label = f"UTC{unique_offsets[0]:+d}" if len(unique_offsets) == 1 else "local time"

tariff_slug = tariff.lower().replace(" ", "_").replace("/", "_")
observed_suffix = "_observed" if args.observed_only else ""

OUT_DIR = Path("paper/graphics")
OUT_DIR.mkdir(parents=True, exist_ok=True)

n_customers = n_meters_total
n_sites = len(site_names)
n_obs = n_obs_total
site_info = f"{n_sites} sites · " if n_sites > 1 else ""

# ---------------------------------------------------------------------------
# Shuffle into tod_slot-partitioned files (one combined streaming pass),
# then compute grouped stats reading one slot at a time (see
# compute_group_stats) rather than concatenating everything into one
# in-memory DataFrame.
# ---------------------------------------------------------------------------
slot_paths = shuffle_to_slot_files(flat_files, tmp_path)
group_stats = compute_group_stats(slot_paths)
tmp_dir_ctx.cleanup()

# ---------------------------------------------------------------------------
# Pre-compute stats for all four variants
# ---------------------------------------------------------------------------
all_stats = []
for hourly, use_median in [(False, False), (True, False), (False, True), (True, True)]:
    if hourly:
        group_col = "tod_hour"
        scale = 4 * 1000  # avg kWh/15min → total Wh/hour
        times = pd.date_range("00:00", periods=24, freq="1h")
        end_padding = pd.Timedelta(hours=1)
        time_unit = "hour"
        hourly_suffix = "_hourly"
    else:
        group_col = "tod_slot"
        scale = 1000  # kWh → Wh
        times = pd.date_range("00:00", periods=96, freq=f"{SLOT_MINUTES}min")
        end_padding = pd.Timedelta(minutes=SLOT_MINUTES)
        time_unit = "15 min"
        hourly_suffix = ""

    g = group_stats[group_col]

    if use_median:
        centre = g["median"] * scale
        lo = g["q1"] * scale
        hi = g["q3"] * scale
        centre_label = "Median"
        band_label = "Q1–Q3"
        spread_suffix = "_median"
        spread_desc = "median + IQR"
    else:
        centre = g["mean"] * scale
        margin = 1.96 * g["std"] / np.sqrt(g["n"]) * scale
        lo = (centre - margin).clip(lower=0)
        hi = centre + margin
        centre_label = "Mean"
        band_label = "95% CI"
        spread_suffix = "_mean_ci"
        spread_desc = "mean + 95% CI"

    midnight = times[-1] + end_padding
    times_plot = times.append(pd.DatetimeIndex([midnight]))

    subtitle_parts = []
    if args.observed_only:
        subtitle_parts.append("observed only")
    if hourly:
        subtitle_parts.append("hourly totals")
    subtitle_parts.append(spread_desc)

    all_stats.append({
        "times": times_plot,
        "centre": np.append(centre.values, centre.values[0]),
        "lo": np.append(lo.values, lo.values[0]),
        "hi": np.append(hi.values, hi.values[0]),
        "centre_label": centre_label,
        "band_label": band_label,
        "time_unit": time_unit,
        "subtitle": ", ".join(subtitle_parts),
        "outfile": OUT_DIR / f"{site_slug}_{tariff_slug}_load_profile{observed_suffix}{hourly_suffix}{spread_suffix}.png",
    })

# ---------------------------------------------------------------------------
# Plot from pre-computed stats
# ---------------------------------------------------------------------------
for s in all_stats:
    title = f"24-Hour Load Profile — {tariff} Customers, {site_label}\n({s['subtitle']})"
    ylabel = f"{s['centre_label']} energy (Wh per {s['time_unit']})"

    fig, ax = plt.subplots(figsize=(12, 5))

    ax.fill_between(s["times"], s["lo"], s["hi"], alpha=0.25, color="#2563eb", label=s["band_label"])
    ax.plot(s["times"], s["centre"], linewidth=1.5, color="#2563eb", label=s["centre_label"])

    ax.set_xlabel(f"Time of day ({tz_label})")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_ylim(bottom=0)

    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_minor_locator(mdates.HourLocator())
    ax.set_xlim(s["times"][0], s["times"][-1])
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.2f"))
    ax.grid(axis="y", linewidth=0.5, alpha=0.5)
    ax.grid(axis="x", linewidth=0.3, alpha=0.3, which="minor")

    ax.legend(loc="upper left", fontsize=9)

    ax.text(
        0.01, 0.88,
        f"{site_info}{n_customers} customers · {n_obs:,} slots",
        transform=ax.transAxes,
        va="top", fontsize=9, color="gray",
    )

    plt.tight_layout()
    plt.savefig(s["outfile"], dpi=150)
    plt.close(fig)
    print(f"Saved {s['outfile'].resolve()}")
