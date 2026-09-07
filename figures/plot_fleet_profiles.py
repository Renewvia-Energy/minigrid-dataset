#!/usr/bin/env python3
"""
Figure: plant telemetry anatomy and fleet operating profiles from vrmgeneration
(Data Overview candidate).

Panel (a): 48 hours of hourly-averaged telemetry at one site (default: the
best-covered window with genset activity at Ekong Anaku): PV output, genset
output, AC load, signed battery power, and battery state of charge.

Panels (b, c): median daily operating profile with interquartile shading across
energized site-hours (mean AC load > 200 W), split by plant architecture.
Architecture is derived from the data itself: a site is classed PV + diesel if
its System_overview_Genset_L* channels ever record positive power, else PV-only.

Schema notes (see Data Dictionary):
  * Several channels are stored as varchar where decimal is expected
    (e.g. PV_Inverter_32_L*_Power); all channels are numerically coerced here.
  * The genset channels record values only while the generator runs; absent
    values are treated as zero so all series share a common time basis.
  * Timestamps in `timestamp_local` are in UTC, not site-local time: read as
    local time, PV onset would precede astronomical sunrise at all sites,
    which is physically impossible. Axis labels therefore say UTC.

Usage:
  python figures/plot_fleet_profiles.py
  python figures/plot_fleet_profiles.py --data-dir data --site "Ekong Anaku" \
      --out figures/fig_fleet_profiles

Outputs <out>.png and <out>.pdf.
"""

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PV_C, LOAD_C, GEN_C, SOC_C, BAT_C = "#e6a817", "#333333", "#c0392b", "#2a9d8f", "#2a78d6"


def load_hourly(vrm_path):
    """Hourly per-site means of PV, load, genset, battery power and SOC."""
    import pyarrow.parquet as pq
    cols = pq.ParquetFile(vrm_path).schema_arrow.names
    pv_cols = [c for c in cols if ("Solar_Charger" in c and c.endswith("_PV_power"))
               or ("PV_Inverter" in c and c.endswith("_Power"))]
    use = (["timestamp_local", "Project_Name",
            "System_overview_AC_Consumption_L1", "System_overview_AC_Consumption_L2",
            "System_overview_AC_Consumption_L3", "System_overview_Genset_L1",
            "System_overview_Genset_L2", "System_overview_Genset_L3",
            "System_overview_Battery_Power", "System_overview_Battery_SOC"] + pv_cols)
    d = pd.read_parquet(vrm_path, columns=use)
    for c in use[2:]:
        d[c] = pd.to_numeric(d[c], errors="coerce")  # varchar channels, see docstring
    d = d.rename(columns={"timestamp_local": "ts", "Project_Name": "site"})
    d["pv_w"] = d[pv_cols].sum(axis=1, min_count=1)
    d["load_w"] = d[[f"System_overview_AC_Consumption_L{i}" for i in (1, 2, 3)]
                    ].sum(axis=1, min_count=1)
    d["gen_w"] = d[[f"System_overview_Genset_L{i}" for i in (1, 2, 3)]
                   ].sum(axis=1, min_count=1)
    d["hour_ts"] = d.ts.dt.floor("h")
    return (d.groupby(["site", "hour_ts"])
             .agg(pv=("pv_w", "mean"), load=("load_w", "mean"),
                  gen=("gen_w", "mean"), soc=("System_overview_Battery_SOC", "mean"),
                  batt=("System_overview_Battery_Power", "mean"), n=("ts", "size"))
             .reset_index())


def quartiles(g, col, div=1000.0):
    return g.groupby("hour")[col].agg(
        med=lambda x: np.nanmedian(x) / div,
        q1=lambda x: np.nanpercentile(x.dropna(), 25) / div,
        q3=lambda x: np.nanpercentile(x.dropna(), 75) / div)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--site", default="Ekong Anaku",
                    help="site for the 48 h anatomy panel")
    ap.add_argument("--out", default="figures/fig_fleet_profiles")
    args = ap.parse_args()

    vrm_path = os.path.join(args.data_dir, "vrmgeneration.parquet")
    if not os.path.exists(vrm_path):
        sys.exit(f"{vrm_path} not found")
    h = load_hourly(vrm_path)
    h["hour"] = h.hour_ts.dt.hour

    hybrid = sorted(h[h.gen.fillna(0) > 0].site.unique())
    pv_only = sorted(set(h.site.unique()) - set(hybrid))
    print(f"architecture from data: {len(pv_only)} PV-only, {len(hybrid)} PV+diesel")

    e = h[h.site == args.site]
    if e.empty:
        sys.exit(f"site {args.site!r} not present in vrmgeneration")
    days = (e.assign(date=e.hour_ts.dt.date)
             .groupby("date").agg(nh=("hour", "size"), gen=("gen", "max"),
                                  n=("n", "sum")))
    cand = days[(days.nh >= 22) & (days.gen.fillna(0) > 2000)]
    d0 = pd.to_datetime((cand if len(cand) else days[days.nh >= 22])
                        .sort_values("n").index[-1])
    win = e[(e.hour_ts >= d0) & (e.hour_ts < d0 + pd.Timedelta(days=2))
            ].sort_values("hour_ts")

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.5,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "figure.dpi": 300})
    fig = plt.figure(figsize=(7.1, 5.4))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.1, 1], hspace=.55, wspace=.32)

    ax = fig.add_subplot(gs[0, :])
    t = win.hour_ts
    ax.fill_between(t, 0, win.pv.fillna(0) / 1000, color=PV_C, alpha=.4,
                    label="PV output")
    ax.fill_between(t, 0, win.gen.fillna(0) / 1000, color=GEN_C, alpha=.4,
                    label="genset output")
    ax.plot(t, win.load.fillna(0) / 1000, color=LOAD_C, lw=1.2, label="AC load")
    ax.plot(t, -win.batt.fillna(0) / 1000, color=BAT_C, lw=1, alpha=.9,
            label="battery discharge (+) / charge (-)")
    ax.axhline(0, color="#999", lw=.5)
    ax2 = ax.twinx(); ax2.spines["top"].set_visible(False)
    ax2.plot(t, win.soc, color=SOC_C, lw=1.2, ls="--", label="battery SOC")
    ax2.set_ylabel("SOC (%)", color=SOC_C); ax2.set_ylim(0, 105)
    ax.set_ylabel("power (kW)")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=6, frameon=False, loc="upper left", ncol=2)
    ax.set_title(f"a   48 h of plant telemetry, {args.site} (hourly means)",
                 loc="left", fontweight="bold", fontsize=8)

    groups = [(pv_only, f"PV-only plants ({len(pv_only)} sites)"),
              (hybrid, f"PV + diesel plants ({len(hybrid)} sites)")]
    for i, (sites, label) in enumerate(groups):
        ax = fig.add_subplot(gs[1, i])
        g = h[h.site.isin(sites)].copy()
        g["gen"] = g.gen.fillna(0)
        g = g[g.load > 200]
        for col, color, name in [("pv", PV_C, "PV"), ("load", LOAD_C, "load"),
                                 ("gen", GEN_C, "genset")]:
            if col == "gen" and i == 0:
                continue
            st = quartiles(g, col)
            ax.plot(st.index, st.med, color=color, lw=1.4, label=name)
            ax.fill_between(st.index, st.q1, st.q3, color=color, alpha=.18,
                            linewidth=0)
        ax2 = ax.twinx(); ax2.spines["top"].set_visible(False)
        soc = quartiles(g, "soc", div=1.0)
        ax2.plot(soc.index, soc.med, color=SOC_C, lw=1.2, ls="--", label="SOC")
        ax2.fill_between(soc.index, soc.q1, soc.q3, color=SOC_C, alpha=.15,
                         linewidth=0)
        ax2.set_ylim(0, 105); ax2.set_xlim(0, 23)
        if i == 1:
            ax2.set_ylabel("SOC (%)", color=SOC_C, fontsize=6.5)
        ax.set_xlim(0, 23); ax.set_ylim(bottom=0); ax.margins(x=0, y=0)
        ax.set_xlabel("hour (UTC)"); ax.set_xticks(range(0, 24, 6))
        if i == 0:
            ax.set_ylabel("power (kW)")
        hA, lA = ax.get_legend_handles_labels()
        hB, lB = ax2.get_legend_handles_labels()
        ax.legend(hA + hB, lA + lB, fontsize=5.5, frameon=False, loc="upper left")
        ax.set_title(("b   " if i == 0 else "c   ") + label +
                     "\nmedian + IQR across energized site-hours",
                     loc="left", fontweight="bold", fontsize=8)

    fig.savefig(args.out + ".png", bbox_inches="tight")
    fig.savefig(args.out + ".pdf", bbox_inches="tight")
    print(f"wrote {args.out}.png and .pdf")


if __name__ == "__main__":
    main()
