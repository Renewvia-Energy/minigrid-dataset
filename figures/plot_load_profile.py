#!/usr/bin/env python3
"""
Plot 24-hour load profiles from precomputed statistics CSVs.

Reads the outputs of prep_load_profile.py and saves figures to paper/graphics/.

Run prep_load_profile.py first.

Outputs (for each tariff):
  paper/graphics/load_profile_{tariff}_{centre}_{site}{hourly}{obs}.png
      Four variants per tariff: mean + 95% CI and median + IQR, each at
      15-min and hourly resolution.

  With --side-by-side TARIFF_A TARIFF_B:
  paper/graphics/load_profile_{tariff_a}_vs_{tariff_b}_{site}{obs}.png
      Panels (a) and (b): median + IQR + dashed mean at 15-min resolution.
      Panel (c): ACF mean across sites (if acf_periodicity.py has been run).

Usage:
  python figures/plot_load_profile.py                                      # all tariffs in meta
  python figures/plot_load_profile.py Residential                          # one tariff
  python figures/plot_load_profile.py --side-by-side Residential Commercial
  python figures/plot_load_profile.py Residential Commercial --side-by-side Residential Commercial
"""

import argparse
import importlib.util
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd

SLOT_MINUTES = 15
OUT_DIR = Path("paper/graphics")
META_PATH = OUT_DIR / "load_profile_meta.csv"


def load_stats(tariff_slug):
    """Read a stats CSV back into the group_stats dict used by the plot code."""
    path = OUT_DIR / f"load_profile_stats_{tariff_slug}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    slot = df[df["type"] == "slot"].drop(columns="type").set_index("group").reindex(range(96))
    hour = df[df["type"] == "hour"].drop(columns="type").set_index("group").reindex(range(24))
    return {"tod_slot": slot, "tod_hour": hour}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(
    description="Plot load profiles from CSVs produced by prep_load_profile.py."
)
parser.add_argument(
    "tariffs",
    nargs="*",
    help="Tariff name(s) to plot. Defaults to all tariffs in load_profile_meta.csv.",
)
parser.add_argument(
    "--side-by-side", nargs=2, metavar=("TARIFF_A", "TARIFF_B"),
    help="Produce a two-panel comparison figure for the given pair of tariffs.",
)
args = parser.parse_args()

# ---------------------------------------------------------------------------
# Load metadata
# ---------------------------------------------------------------------------
if not META_PATH.exists():
    print(
        f"Error: {META_PATH} not found. Run `python figures/prep_load_profile.py` first.",
        file=sys.stderr,
    )
    sys.exit(1)

meta = pd.read_csv(META_PATH)

# Resolve which tariffs to plot for the four-variant figures
if args.tariffs:
    slugs_requested = [t.lower().replace(" ", "_").replace("/", "_") for t in args.tariffs]
    missing = [s for s in slugs_requested if s not in meta["tariff_slug"].values]
    if missing:
        print(
            f"Error: no stats found for {missing}. "
            "Available: " + ", ".join(meta["tariff_slug"].tolist()),
            file=sys.stderr,
        )
        sys.exit(1)
    plot_meta = meta[meta["tariff_slug"].isin(slugs_requested)]
else:
    plot_meta = meta

OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Four-variant figures (one per tariff)
# ---------------------------------------------------------------------------
for _, row in plot_meta.iterrows():
    tariff       = row["tariff"]
    tariff_slug  = row["tariff_slug"]
    n_customers  = int(row["n_customers"])
    n_obs        = int(row["n_obs"])
    n_sites      = int(row["n_sites"])
    site_label   = row["site_label"]
    site_slug    = row["site_slug"]
    tz_label     = row["tz_label"]
    observed_only = bool(row["observed_only"])

    group_stats = load_stats(tariff_slug)
    if group_stats is None:
        print(f"Warning: stats file missing for '{tariff_slug}', skipping.", file=sys.stderr)
        continue

    observed_suffix = "_observed" if observed_only else ""
    site_info = f"{n_sites} sites · " if n_sites > 1 else ""

    all_stats = []
    for hourly, use_median in [(False, False), (True, False), (False, True), (True, True)]:
        if hourly:
            group_col    = "tod_hour"
            scale        = 4 * 1000  # avg kWh/15min → total Wh/hour
            times        = pd.date_range("00:00", periods=24, freq="1h")
            end_padding  = pd.Timedelta(hours=1)
            time_unit    = "hour"
            hourly_suffix = "_hourly"
        else:
            group_col    = "tod_slot"
            scale        = 1000  # kWh → Wh
            times        = pd.date_range("00:00", periods=96, freq=f"{SLOT_MINUTES}min")
            end_padding  = pd.Timedelta(minutes=SLOT_MINUTES)
            time_unit    = "15 min"
            hourly_suffix = ""

        g = group_stats[group_col]

        if use_median:
            centre       = g["median"] * scale
            lo           = g["q1"] * scale
            hi           = g["q3"] * scale
            centre_label = "Median"
            band_label   = "Q1–Q3"
            spread_desc  = "median + IQR"
        else:
            centre       = g["mean"] * scale
            margin       = 1.96 * g["std"] / np.sqrt(g["n"]) * scale
            lo           = (centre - margin).clip(lower=0)
            hi           = centre + margin
            centre_label = "Mean"
            band_label   = "95% CI"
            spread_desc  = "mean + 95% CI"

        times_plot = times.append(pd.DatetimeIndex([times[-1] + end_padding]))

        subtitle_parts = []
        if observed_only:
            subtitle_parts.append("observed only")
        if hourly:
            subtitle_parts.append("hourly totals")
        subtitle_parts.append(spread_desc)

        all_stats.append({
            "times":        times_plot,
            "centre":       np.append(centre.values, centre.values[0]),
            "lo":           np.append(lo.values, lo.values[0]),
            "hi":           np.append(hi.values, hi.values[0]),
            "centre_label": centre_label,
            "band_label":   band_label,
            "time_unit":    time_unit,
            "subtitle":     ", ".join(subtitle_parts),
            "outfile":      OUT_DIR / f"load_profile_{tariff_slug}_{centre_label.lower()}_{site_slug}{hourly_suffix}{observed_suffix}.png",
        })

    for s in all_stats:
        title  = f"24-Hour Load Profile — {tariff} Customers, {site_label}\n({s['subtitle']})"
        ylabel = f"{s['centre_label']} energy (Wh per {s['time_unit']})"

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.fill_between(s["times"], s["lo"], s["hi"], alpha=0.25, color="#2563eb", label=s["band_label"])
        ax.plot(s["times"], s["centre"], linewidth=1.5, color="#2563eb", label=s["centre_label"])

        ax.set_xlabel(f"Time of day ({tz_label})")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.set_ylim(bottom=0)
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H"))
        ax.xaxis.set_minor_locator(mdates.HourLocator())
        ax.set_xlim(s["times"][0], s["times"][-1])
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.0f"))
        ax.grid(axis="y", linewidth=0.5, alpha=0.5)
        ax.grid(axis="x", linewidth=0.3, alpha=0.3, which="minor")
        ax.legend(loc="upper left", fontsize=9)

        plt.tight_layout()
        plt.savefig(s["outfile"], dpi=150)
        plt.close(fig)
        print(f"Saved {s['outfile'].resolve()}")

# ---------------------------------------------------------------------------
# Optional: side-by-side comparison figure (15-min, median + IQR + mean + ACF)
# ---------------------------------------------------------------------------
if args.side_by_side:
    tariff_a_name, tariff_b_name = args.side_by_side
    slug_a = tariff_a_name.lower().replace(" ", "_").replace("/", "_")
    slug_b = tariff_b_name.lower().replace(" ", "_").replace("/", "_")

    for slug, name in [(slug_a, tariff_a_name), (slug_b, tariff_b_name)]:
        if slug not in meta["tariff_slug"].values:
            print(
                f"Error: no stats found for '{name}'. "
                "Run `python figures/prep_load_profile.py --tariffs {name}` first.",
                file=sys.stderr,
            )
            sys.exit(1)

    row_a = meta[meta["tariff_slug"] == slug_a].iloc[0]
    row_b = meta[meta["tariff_slug"] == slug_b].iloc[0]

    gs_a = load_stats(slug_a)
    gs_b = load_stats(slug_b)

    scale = 1000  # kWh → Wh
    times = pd.date_range("00:00", periods=96, freq=f"{SLOT_MINUTES}min")
    times_plot = times.append(pd.DatetimeIndex([times[-1] + pd.Timedelta(minutes=SLOT_MINUTES)]))

    def _panel_arrays(group_stats):
        g = group_stats["tod_slot"]
        def _wrap(col):
            v = (g[col] * scale).values
            return np.append(v, v[0])
        return _wrap("median"), _wrap("q1"), _wrap("q3"), _wrap("mean")

    med_a, q1_a, q3_a, mean_a = _panel_arrays(gs_a)
    med_b, q1_b, q3_b, mean_b = _panel_arrays(gs_b)

    colors = ["#2563eb", "#16a34a"]

    # Try to load ACF data for the third panel
    acf_dir = OUT_DIR
    acf_csvs = {
        "native":   acf_dir / "acf_by_site_15min.csv",
        "hourly":   acf_dir / "acf_by_site_hourly.csv",
        "coverage": acf_dir / "acf_site_coverage.csv",
    }
    missing_csvs = [str(p) for p in acf_csvs.values() if not p.exists()]
    include_acf = not missing_csvs
    if missing_csvs:
        print(
            f"Warning: ACF CSVs not found ({', '.join(missing_csvs)}); "
            "omitting ACF panel. Run `python figures/acf_periodicity.py` first.",
            file=sys.stderr,
        )
    else:
        _spec = importlib.util.spec_from_file_location(
            "_acf_plot_mod", Path(__file__).resolve().parent / "plot_acf_periodicity.py"
        )
        _acf_mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_acf_mod)

        acf_native   = _acf_mod.lag_indexed(acf_csvs["native"])
        acf_hourly   = _acf_mod.lag_indexed(acf_csvs["hourly"])
        coverage     = pd.read_csv(acf_csvs["coverage"])
        coverage["in_mean"] = _acf_mod.as_bool(coverage["in_mean"])
        in_mean = [s for s in acf_native.columns
                   if s in set(coverage.loc[coverage.in_mean, "site"])]
        obs_per_site = (coverage.loc[coverage.in_mean, "n_slots"]
                        - coverage.loc[coverage.in_mean, "n_missing"])
        n_obs_acf = max(int(obs_per_site.min()), 1)
        if not in_mean:
            print("Warning: no sites passed the ACF missing-fraction gate; omitting ACF panel.", file=sys.stderr)
            include_acf = False

    # Build figure
    if include_acf:
        fig    = plt.figure(figsize=(14, 10))
        gs_fig = fig.add_gridspec(2, 2, height_ratios=[5, 4.5], hspace=0.5)
        ax_acf = fig.add_subplot(gs_fig[1, :])
    else:
        fig    = plt.figure(figsize=(14, 5))
        gs_fig = fig.add_gridspec(1, 2)

    tz_label_a = row_a["tz_label"]
    panels = [
        (fig.add_subplot(gs_fig[0, 0]), med_a, q1_a, q3_a, mean_a,
         tariff_a_name, int(row_a["n_customers"]), int(row_a["n_obs"]),
         int(row_a["n_sites"]), colors[0]),
        (fig.add_subplot(gs_fig[0, 1]), med_b, q1_b, q3_b, mean_b,
         tariff_b_name, int(row_b["n_customers"]), int(row_b["n_obs"]),
         int(row_b["n_sites"]), colors[1]),
    ]
    for panel_idx, (ax, med, q1, q3, mean, label, n_cust, n_obs_panel, n_s, color) in enumerate(panels):
        ax.fill_between(times_plot, q1, q3, alpha=0.25, color=color, label="IQR (Q1–Q3)")
        ax.plot(times_plot, med,  linewidth=1.5, color=color,             label="Median")
        ax.plot(times_plot, mean, linewidth=1.0, color=color, linestyle="--", label="Mean")

        ax.set_title(f"{label} Customers")
        ax.set_xlabel(f"Time of day ({tz_label_a})")
        ax.set_ylabel("Energy (Wh per 15 min)")
        ax.set_ylim(bottom=0)
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H"))
        ax.xaxis.set_minor_locator(mdates.HourLocator())
        ax.set_xlim(times_plot[0], times_plot[-1])
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.0f"))
        ax.grid(axis="y", linewidth=0.5, alpha=0.5)
        ax.grid(axis="x", linewidth=0.3, alpha=0.3, which="minor")
        ax.legend(loc="upper left", fontsize=9)
        panel_site_info = f"{n_s} sites · " if n_s > 1 else ""
        ax.text(
            0.01, 0.88,
            f"{panel_site_info}{n_cust} customers · {n_obs_panel:,} slots",
            transform=ax.transAxes, va="top", fontsize=9, color="gray",
        )
        ax.text(-0.07, 1.02, "ab"[panel_idx], transform=ax.transAxes,
                fontsize=11, fontweight="bold", va="bottom", ha="right")

    if include_acf:
        _acf_mod.panel_mean(ax_acf, acf_native, acf_hourly, in_mean, n_obs_acf)
        ax_acf.text(-0.07, 1.02, "c", transform=ax_acf.transAxes,
                    fontsize=11, fontweight="bold", va="bottom", ha="right")

    site_label_a  = row_a["site_label"]
    observed_only = bool(row_a["observed_only"])
    obs_note      = " (observed only)" if observed_only else ""
    fig.suptitle(f"24-Hour Load Profiles — {site_label_a}{obs_note}", y=1.01)
    plt.tight_layout()

    observed_suffix = "_observed" if observed_only else ""
    out_sbs = OUT_DIR / f"load_profile_{slug_a}_vs_{slug_b}_{row_a['site_slug']}{observed_suffix}.png"
    plt.savefig(out_sbs, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out_sbs.resolve()}")
