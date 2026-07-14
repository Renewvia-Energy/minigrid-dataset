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
import gc
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend; remove to show a window
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd

SLOT_MINUTES = 15

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
# Loop over sites: resolve UTC offset, find matching meters, load clean data
# ---------------------------------------------------------------------------
frames = []
site_names = []
utc_offsets = []
n_meters_total = 0

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

    tariffs = pd.concat(
        [pd.read_parquet(f, columns=["meter_customer_code", "meter_tariff_name"]) for f in raw_files],
        ignore_index=True,
    )
    most_common_tariff = (
        tariffs.groupby("meter_customer_code")["meter_tariff_name"]
        .agg(lambda s: s.dropna().mode().iloc[0] if s.dropna().any() else None)
        .reset_index()
    )
    matching_codes = most_common_tariff.loc[
        most_common_tariff["meter_tariff_name"].str.contains(tariff, case=False, na=False),
        "meter_customer_code",
    ]

    if matching_codes.empty:
        print(
            f"  Warning: no meters found with tariff containing '{tariff}' at {site_name}. "
            f"Available tariffs: {most_common_tariff['meter_tariff_name'].dropna().unique().tolist()}",
            file=sys.stderr,
        )
        continue

    print(f"  Tariff filter '{tariff}': {len(matching_codes)} meters matched")
    n_meters_total += len(matching_codes)

    # Load and filter clean data
    site_clean = pd.read_parquet(
        clean_path,
        columns=["meter_customer_code", "meter_type", "slot_start", "energy_kwh", "imputation_method"],
    )
    site_clean = site_clean[
        (site_clean["meter_type"] == "customer")
        & (site_clean["meter_customer_code"].isin(matching_codes))
    ].copy()

    if args.observed_only:
        site_clean = site_clean[site_clean["imputation_method"] == "observed"]

    slot_start_local = site_clean["slot_start"] + pd.Timedelta(hours=utc_offset)
    minutes = slot_start_local.dt.hour * 60 + slot_start_local.dt.minute
    frames.append(pd.DataFrame({
        "tod_slot": (minutes // SLOT_MINUTES).astype("int16"),
        "tod_hour": slot_start_local.dt.hour.astype("int8"),
        "energy_kwh": site_clean["energy_kwh"].values,
    }))
    site_names.append(site_name)
    utc_offsets.append(utc_offset)

if not frames:
    print(f"Error: no matching meters found across any of the provided sites.", file=sys.stderr)
    sys.exit(1)

clean = pd.concat(frames, ignore_index=True)
del frames
print(f"Rows after filtering: {len(clean):,}")

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
n_obs = len(clean)
site_info = f"{n_sites} sites · " if n_sites > 1 else ""

# ---------------------------------------------------------------------------
# Pre-compute stats for all four variants, then free the raw data
# ---------------------------------------------------------------------------
all_stats = []
for hourly, use_median in [(False, False), (True, False), (False, True), (True, True)]:
    if hourly:
        group_col = "tod_hour"
        n_groups = 24
        scale = 4 * 1000  # avg kWh/15min → total Wh/hour
        times = pd.date_range("00:00", periods=24, freq="1h")
        end_padding = pd.Timedelta(hours=1)
        time_unit = "hour"
        hourly_suffix = "_hourly"
    else:
        group_col = "tod_slot"
        n_groups = 96
        scale = 1000  # kWh → Wh
        times = pd.date_range("00:00", periods=96, freq=f"{SLOT_MINUTES}min")
        end_padding = pd.Timedelta(minutes=SLOT_MINUTES)
        time_unit = "15 min"
        hourly_suffix = ""

    g = clean.groupby(group_col)["energy_kwh"]

    if use_median:
        centre = g.median() * scale
        lo = g.quantile(0.25) * scale
        hi = g.quantile(0.75) * scale
        centre_label = "Median"
        band_label = "Q1–Q3"
        spread_suffix = "_median"
        spread_desc = "median + IQR"
    else:
        agg = g.agg(["mean", "std", "count"])
        centre = agg["mean"] * scale
        margin = 1.96 * agg["std"] / np.sqrt(agg["count"]) * scale
        lo = (centre - margin).clip(lower=0)
        hi = centre + margin
        centre_label = "Mean"
        band_label = "95% CI"
        spread_suffix = "_mean_ci"
        spread_desc = "mean + 95% CI"

    centre = centre.reindex(range(n_groups), fill_value=np.nan)
    lo = lo.reindex(range(n_groups), fill_value=np.nan)
    hi = hi.reindex(range(n_groups), fill_value=np.nan)

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

del clean
gc.collect()

# ---------------------------------------------------------------------------
# Plot from pre-computed stats (clean is now freed)
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
