#!/usr/bin/env python3
"""
Plot the 24-hour average load profile for a given tariff across one or more sites.

Customers are identified by joining to the raw SparkMeter tariff names
(meter_tariff_name containing the given tariff string, case-insensitive).
The UTC offset is looked up from minigridprojects unless overridden.

Usage:
  python plot_load_profile.py <parquet_file> [<parquet_file> ...] <tariff> [options]

Examples:
  python plot_load_profile.py data/sparkmeterreadings_clean/Ndeda.parquet Residential
  python plot_load_profile.py data/sparkmeterreadings_clean/Ndeda.parquet Shop --hourly
  python plot_load_profile.py data/sparkmeterreadings_clean/Akipelai.parquet Residential --utc-offset 3
  python plot_load_profile.py data/sparkmeterreadings_clean/Ndeda.parquet Residential --spread median --hourly
  python plot_load_profile.py data/sparkmeterreadings_clean/Ndeda.parquet data/sparkmeterreadings_clean/Akipelai.parquet Residential --hourly

Optional arguments:
  --utc-offset INT    UTC offset in hours (applied to all sites; default: looked up per site)
  --spread median     Show median + Q1–Q3 band instead of mean + 95% CI
  --observed-only     Include only slots with imputation_method='observed'
  --hourly            Aggregate to hourly totals (Wh/hr) instead of 15-min slots
"""

import argparse
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
    help="Path(s) to site parquet(s) in data/sparkmeterreadings_clean/. Last positional argument is the tariff.",
)
parser.add_argument(
    "--utc-offset", type=int, default=None, metavar="HOURS",
    help="UTC offset in hours applied to all sites. Looked up per site from minigridprojects if omitted.",
)
parser.add_argument(
    "--spread", choices=["median"], default=None,
    help="'median': show median + Q1–Q3 band. Default: mean + 95%% CI.",
)
parser.add_argument(
    "--observed-only", action="store_true",
    help="Include only slots with imputation_method='observed' (direct meter readings).",
)
parser.add_argument(
    "--hourly", action="store_true",
    help="Aggregate to hourly totals (Wh per hour) instead of 15-minute increments.",
)
args = parser.parse_args()

# Last positional arg is the tariff; the rest are parquet files
tariff = args.parquet_files[-1]
file_paths = [Path(p) for p in args.parquet_files[:-1]]

if not file_paths:
    print("Error: at least one parquet file must be provided before the tariff.", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Load minigridprojects once for UTC offset lookups
# ---------------------------------------------------------------------------
proj = None
if args.utc_offset is None:
    data_root = file_paths[0].parent.parent
    proj_path = data_root / "minigridprojects" / "data.parquet"
    proj = pd.read_parquet(proj_path, columns=["projectName", "timezoneOffsetUtc"])

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
    else:
        match = proj[proj["projectName"] == site_name]
        if match.empty:
            print(
                f"Error: '{site_name}' not found in minigridprojects. "
                "Use --utc-offset to specify the UTC offset manually.",
                file=sys.stderr,
            )
            sys.exit(1)
        utc_offset = int(match["timezoneOffsetUtc"].iloc[0])

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

    site_clean["slot_start_local"] = site_clean["slot_start"] + pd.Timedelta(hours=utc_offset)

    frames.append(site_clean)
    site_names.append(site_name)
    utc_offsets.append(utc_offset)

if not frames:
    print(f"Error: no matching meters found across any of the provided sites.", file=sys.stderr)
    sys.exit(1)

clean = pd.concat(frames, ignore_index=True)
print(f"Rows after filtering: {len(clean):,}")

# ---------------------------------------------------------------------------
# Assign grouping key (15-min slot or hour)
# ---------------------------------------------------------------------------
if args.hourly:
    group_col = "tod_hour"
    clean[group_col] = clean["slot_start_local"].dt.hour
    n_groups = 24
    scale = 4 * 1000  # avg kWh/15min → total Wh/hour
    times = pd.date_range("00:00", periods=24, freq="1h")
    end_padding = pd.Timedelta(hours=1)
else:
    group_col = "tod_slot"
    clean[group_col] = (
        clean["slot_start_local"].dt.hour * 60 + clean["slot_start_local"].dt.minute
    ) // SLOT_MINUTES
    n_groups = 96
    scale = 1000  # kWh → Wh
    times = pd.date_range("00:00", periods=96, freq=f"{SLOT_MINUTES}min")
    end_padding = pd.Timedelta(minutes=SLOT_MINUTES)

# ---------------------------------------------------------------------------
# Compute centre line and spread band
# ---------------------------------------------------------------------------
g = clean.groupby(group_col)["energy_kwh"]

if args.spread == "median":
    centre = g.median() * scale
    lo = g.quantile(0.25) * scale
    hi = g.quantile(0.75) * scale
    centre_label = "Median"
    band_label = "Q1–Q3"
else:
    agg = g.agg(["mean", "std", "count"])
    centre = agg["mean"] * scale
    margin = 1.96 * agg["std"] / np.sqrt(agg["count"]) * scale
    lo = (centre - margin).clip(lower=0)
    hi = centre + margin
    centre_label = "Mean"
    band_label = "95% CI"

centre = centre.reindex(range(n_groups), fill_value=np.nan)
lo = lo.reindex(range(n_groups), fill_value=np.nan)
hi = hi.reindex(range(n_groups), fill_value=np.nan)

# Append the 00:00 value at 24:00 so the line wraps correctly to midnight
midnight = times[-1] + end_padding
times = times.append(pd.DatetimeIndex([midnight]))
centre = np.append(centre.values, centre.values[0])
lo = np.append(lo.values, lo.values[0])
hi = np.append(hi.values, hi.values[0])

# ---------------------------------------------------------------------------
# Build title, ylabel, output filename
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

labels = []
if args.observed_only:
    labels.append("observed only")
if args.hourly:
    labels.append("hourly totals")
labels.append("median + IQR" if args.spread == "median" else "mean + 95% CI")
subtitle = ", ".join(labels)

title = f"24-Hour Load Profile — {tariff} Customers, {site_label}\n({subtitle})"

tariff_slug = tariff.lower().replace(" ", "_").replace("/", "_")
suffix = (
    ("_observed" if args.observed_only else "")
    + ("_hourly" if args.hourly else "")
    + ("_median" if args.spread == "median" else "_mean_ci")
)
outfile = f"{site_slug}_{tariff_slug}_load_profile{suffix}.png"

time_unit = "hour" if args.hourly else "15 min"
ylabel = f"{centre_label} energy (Wh per {time_unit})"

# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(12, 5))

ax.fill_between(times, lo, hi, alpha=0.25, color="#2563eb", label=band_label)
ax.plot(times, centre, linewidth=1.5, color="#2563eb", label=centre_label)

ax.set_xlabel(f"Time of day ({tz_label})")
ax.set_ylabel(ylabel)
ax.set_title(title)
ax.set_ylim(bottom=0)

ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
ax.xaxis.set_minor_locator(mdates.HourLocator())
ax.set_xlim(times[0], times[-1])
ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.2f"))
ax.grid(axis="y", linewidth=0.5, alpha=0.5)
ax.grid(axis="x", linewidth=0.3, alpha=0.3, which="minor")

ax.legend(loc="upper left", fontsize=9)

n_customers = clean["meter_customer_code"].nunique()
n_sites = len(site_names)
n_obs = len(clean)
site_info = f"{n_sites} sites · " if n_sites > 1 else ""
ax.text(
    0.01, 0.88,
    f"{site_info}{n_customers} customers · {n_obs:,} slots",
    transform=ax.transAxes,
    va="top", fontsize=9, color="gray",
)

plt.tight_layout()
plt.savefig(outfile, dpi=150)
print(f"Saved {outfile}")
