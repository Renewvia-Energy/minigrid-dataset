#!/usr/bin/env python3
"""
Figure: monthly reading completeness and gap-length distribution across all metered
sites (Data Overview / Technical Validation candidate).

Panel (a): monthly completeness per site, defined as the number of distinct
15-minute slots in the month containing at least one directly observed
customer-meter reading (imputation_method = "observed"), divided by the number
of calendar slots in that month. Profile- and uniform-imputed slots are energy
reconstructions across meter silence (see Data Dictionary) and are excluded by
default; pass --include-imputed to count them. Sites are
ordered on the y-axis by date of first operation (first clean slot). White cells
are months before commissioning or without data.

Panel (b): density of gaps longer than 15 minutes between consecutive
site-level valid slots (a slot is valid if any customer meter has a clean
reading in it), split by country, on log-log axes. This matches the
definition used in the manuscript figure.
Because the meters are line-powered, extended gaps generally coincide with
de-energized network states rather than instrument failure, so values should
not be interpolated across gaps.

Input:  the published clean series, one parquet per site, in either layout:
          data/sparkmeterreadings_clean_<Site>.parquet
          data/sparkmeterreadings_clean/<Site>.parquet
        Columns used: meter_customer_code, meter_type, slot_start (UTC).
        Country per site is resolved from data/minigridprojects.parquet if a
        country-like column exists, else from data/meteringbasestations.parquet
        via timezoneOffsetUtc (3 -> Kenya, 1 -> Nigeria), else labeled Unknown.

Usage:
  python figures/plot_completeness.py
  python figures/plot_completeness.py --data-dir data --out figures/fig_completeness

Outputs <out>.png (screen resolution) and <out>.pdf (vector, for submission).
"""

import argparse
import glob
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

KE_COLOR, NG_COLOR, UNK_COLOR = "#378add", "#e2574a", "#999999"
COUNTRY_COLORS = {"Kenya": KE_COLOR, "Nigeria": NG_COLOR}


def find_site_files(data_dir):
    """Return {site_name: path} for both supported clean-series layouts."""
    files = {}
    for p in glob.glob(os.path.join(data_dir, "sparkmeterreadings_clean_*.parquet")):
        site = os.path.basename(p)[len("sparkmeterreadings_clean_"):-len(".parquet")]
        files[site] = p
    for p in glob.glob(os.path.join(data_dir, "sparkmeterreadings_clean", "*.parquet")):
        files[os.path.basename(p)[:-len(".parquet")]] = p
    return files


def _norm(name):
    """Normalize site/project names for matching: lowercase alphanumerics only."""
    import re
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _best_match(key, lookup):
    """Exact match, else longest common-prefix match (>= 7 chars).

    Needed because site filenames and metadata project names diverge for
    multi-station projects: e.g. files Kalobeyei_Settlement_Village_1A..3A all
    belong to the project "Kalobeyei Settlement" (13+ base stations, see Data
    Dictionary), and Kakuma_3A corresponds to "Kakuma 3 - Okapi". Prefix
    matching is safe for country resolution: candidate collisions occur only
    within a project family, which never spans countries.
    """
    if key in lookup:
        return lookup[key]
    best, best_len = None, 6
    for k, v in lookup.items():
        n = 0
        for a, b in zip(key, k):
            if a != b:
                break
            n += 1
        if n > best_len and (n == len(k) or n == len(key) or n >= 7):
            best, best_len = v, n
    return best


def resolve_countries(data_dir, sites):
    """Best-effort site -> country mapping from the release metadata tables.

    Site filenames (e.g. Kalobeyei_Settlement_Village_1A) and metadata
    projectName values (e.g. "Kalobeyei Settlement Village 1A") differ in
    separators and casing, so both sides are normalized to lowercase
    alphanumerics before matching.
    """
    mapping = {}
    proj_path = os.path.join(data_dir, "minigridprojects.parquet")
    if os.path.exists(proj_path):
        proj = pd.read_parquet(proj_path)
        name_col = next((c for c in proj.columns if c.lower() in
                         ("project_name", "projectname", "name")), None)
        country_col = next((c for c in proj.columns if "country" in c.lower()), None)
        if name_col and country_col:
            lookup = {_norm(k): v for k, v in
                      zip(proj[name_col], proj[country_col].astype(str))}
            for s in sites:
                mapping[s] = _best_match(_norm(s), lookup)
    base_path = os.path.join(data_dir, "meteringbasestations.parquet")
    if os.path.exists(base_path):
        base = pd.read_parquet(base_path)
        if {"projectName", "timezoneOffsetUtc"}.issubset(base.columns):
            tz = base.assign(k=base.projectName.map(_norm)
                             ).groupby("k").timezoneOffsetUtc.first()
            for s in sites:
                if mapping.get(s):
                    continue
                off = _best_match(_norm(s), tz.to_dict())
                if off == 3:
                    mapping[s] = "Kenya"
                elif off == 1:
                    mapping[s] = "Nigeria"
    return {s: (mapping.get(s) or "Unknown") for s in sites}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default="figures/fig_completeness")
    ap.add_argument("--include-imputed", action="store_true",
                    help="count profile/uniform-imputed slots as valid "
                         "(default: directly observed slots only)")
    args = ap.parse_args()

    files = find_site_files(args.data_dir)
    if not files:
        sys.exit(f"No sparkmeterreadings_clean files found under {args.data_dir}/")
    countries = resolve_countries(args.data_dir, list(files))

    monthly, first_slot, gap_frames = {}, {}, []
    TOTAL_SLOTS = [0]
    FIRST_LAST = [pd.Timestamp.max, pd.Timestamp.min]
    for site, path in sorted(files.items()):
        df = pd.read_parquet(path,
                             columns=["meter_customer_code", "meter_type",
                                      "slot_start", "imputation_method"])
        df = df[df.meter_type == "customer"]
        if not args.include_imputed:
            df = df[df.imputation_method == "observed"]
        if df.empty:
            continue
        slot = pd.to_datetime(df.slot_start, utc=True).dt.tz_localize(None)
        first_slot[site] = slot.min()

        slots = slot.drop_duplicates()
        TOTAL_SLOTS[0] += len(slots)
        FIRST_LAST[0] = min(FIRST_LAST[0], slots.min())
        FIRST_LAST[1] = max(FIRST_LAST[1], slots.max())
        per = slots.dt.to_period("M").value_counts().sort_index()
        pct = per / (per.index.days_in_month * 96) * 100
        monthly[site] = pct

        site_slots = slots.sort_values()
        gap = site_slots.diff().dt.total_seconds().div(60).dropna()
        gap = gap[gap > 15]
        gap_frames.append(pd.DataFrame({"gap": gap, "country": countries[site]}))

    order = sorted(monthly, key=lambda s: first_slot[s])
    months = pd.period_range(min(m.index.min() for m in monthly.values()),
                             max(m.index.max() for m in monthly.values()), freq="M")
    M = pd.DataFrame({s: monthly[s].reindex(months) for s in order}).T
    G = pd.concat(gap_frames)

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig = plt.figure(figsize=(8.6, 8.2))
    gs = fig.add_gridspec(2, 1, height_ratios=[1.7, 1], hspace=.42)

    ax = fig.add_subplot(gs[0])
    im = ax.imshow(M.values, aspect="auto", cmap="Blues", vmin=0, vmax=100,
                   interpolation="nearest")
    ax.set_yticks(range(len(M)))
    ax.set_yticklabels(M.index, fontsize=7.5)
    ticks = [i for i, m in enumerate(months) if m.month in (1, 7)]
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(months[i]) for i in ticks], fontsize=7,
                       rotation=45, ha="right")
    abbrev = {"Kenya": "KE", "Nigeria": "NG"}
    for i, s in enumerate(M.index):
        c = countries[s]
        ax.text(len(months) + 0.7, i, abbrev.get(c, "??"), fontsize=7, va="center",
                fontweight="bold", color=COUNTRY_COLORS.get(c, UNK_COLOR))
    fig.colorbar(im, ax=ax, shrink=.75, pad=.05).set_label(
        "monthly completeness (%)", fontsize=8)
    ax.set_title("a   Monthly reading completeness per site, ordered by first "
                 "operation\ncompleteness = directly observed 15-min slots / calendar "
                 "slots; white = pre-commissioning or no data",
                 loc="left", fontsize=9, fontweight="bold")

    ax = fig.add_subplot(gs[1])
    bins = np.logspace(np.log10(15), np.log10(60 * 24 * 60), 70)
    for country, color in COUNTRY_COLORS.items():
        sel = G[G.country == country].gap
        if len(sel):
            ax.hist(sel, bins=bins, histtype="step", lw=1.7, color=color,
                    label=country, density=True)
    if (G.country == "Unknown").any():
        ax.hist(G[G.country == "Unknown"].gap, bins=bins, histtype="step",
                lw=1.2, color=UNK_COLOR, label="Unknown", density=True)
    ax.set_xscale("log")
    ax.set_yscale("log")
    for x, lab in [(30, "30 min"), (1440, "1 day"), (10080, "1 week")]:
        ax.axvline(x, color="#999", lw=.8, ls=":")
        ax.text(x * 1.12, ax.get_ylim()[1] * 0.5, lab, fontsize=7, color="#666")
    ax.set_xlabel("gap between consecutive observed intervals (min)")
    ax.set_ylabel("density (log)")
    ax.legend(fontsize=8, frameon=False, loc="upper right")
    ax.set_title(f"b   Gap-length distribution (n = {len(G):,} gaps > 15 min) between "
                 "consecutive site-level observed slots", loc="left", fontsize=9, fontweight="bold", pad=10)

    fig.savefig(args.out + ".png", dpi=165, bbox_inches="tight")
    fig.savefig(args.out + ".pdf", bbox_inches="tight")
    print(f"wrote {args.out}.png and .pdf "
          f"({len(M)} sites, {len(months)} months, {len(G):,} gaps, "
          f"{TOTAL_SLOTS[0]:,} observed slots, "
          f"{FIRST_LAST[0]:%Y-%m-%d} to {FIRST_LAST[1]:%Y-%m-%d})")


if __name__ == "__main__":
    main()
