#!/usr/bin/env python3
"""
Customer-experienced supply reliability (SAIDI / SAIFI) across all metered sites

Reads the outputs of prep_saidi_saifi.py and plots SAIDI and SAIFI (following IEEE 1366):
    SAIFI = sum(interruptions) / customers served
    SAIDI = sum(de-energized customer-hours) / customers served
    CAIDI = SAIDI / SAIFI

Saves: 
    paper/graphics/fig_saidi_saifi.png/.pdf
        (a) SAIDI vs SAIFI, one point per site-year
        (b) CDF of interruptions by country
        (c) Start hour of confirmed interruptions by country
        (d) Monthly share of customer-hours de-energized
    paper/graphics/fig_saidi_saifi_sites.png/.pdf
        SAIDI vs SAIFI with one labelled point per site over its full record
    paper/graphics/fig_saidi_saifi_class.png/.pdf
        SAIDI and SAIFI per site for residential vs commercial customers

Usage:
    python figures/plot_saidi_saifi.py
"""

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import NullLocator, LogFormatterSciNotation
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
import colorsys

KE_COLOR, NG_COLOR = "#0072B2","#D55E00"
COUNTRY_COLORS = {"Kenya": KE_COLOR, "Nigeria": NG_COLOR}
UTC_OFFSET_H = {"Kenya": 3, "Nigeria": 1}
RES_COLOR, COM_COLOR = "#009E73", "#E69F00"
MIN_CLASS_METERS = 10

# Label placement overrides for the per-site figure: (dx, dy) in points, ha
SITE_LABEL_OFFSETS = {
    "Bendeghe-Afi": (-7, 0, "right"), "Balep": (-7, 0, "right"), "Ekong Anaku": (0, 10, "center"),
    "Akipelai": (-7, 0, "right"), "Oloibiri": (-7, 0, "right"), "Kalobeyei Settlement": (-7, 0, "right"),
    "Nakukulas": (-7, 0, "right"), "Ngurunit": (-7, -6, "right"), "Lomekwi": (-7, 0, "right"),
    "Katiko": (0, 10, "center"),
}

# Projects with vrmgeneration telemetry (validated outages)
VRM_PROJECTS = {
    "Balep", "Bendeghe-Afi", "Ekong Anaku", "Emereoke", "Kakuma 3 - Okapi", "Kangitan Kori",
    "Kapelbok", "Locheremoit", "Lomekwi", "Lorengelup", "Nakukulas", "Ndeda", "Olkiramatian",
    "Opu", "Oyamo", "Ozuzu",
}

def load(graphics_dir, roll_up):
    m = pd.read_csv(os.path.join(graphics_dir, "saidi_saifi_monthly.csv"))
    d = pd.read_csv(os.path.join(graphics_dir, "saidi_saifi_durations.csv"))
    unit = "project" if roll_up else "site"
    m["unit"] = m[unit]
    d["unit"] = d[unit]
    m["year"] = m["ym"].str[:4].astype(int)
    return m, d

def indices(m, by):
    """calculate SAIDI and SAIFI over groups by (list of columns) and annualized"""
    g = m.groupby(by)
    out = pd.DataFrame({
        "n_months": g["ym"].nunique(),
        "meters": g["n_meters_served"].sum() / g["ym"].nunique(),
        "n_int": g["n_confirmed"].sum(),
        "hours": g["hours_confirmed"].sum(),
    })
    ann = 12 / out["n_months"]
    out["saifi"] = ann * out["n_int"] / out["meters"]
    out["saidi"] = ann * out["hours"] / out["meters"]
    return out.reset_index()

def site_colors(units_by_country):
    out = {}
    for country, units in units_by_country.items():
        h0, h1 = (0.47, 0.72) if country == "Kenya" else (0.92, 1.10)
        n = len(units)
        for i, u in enumerate(sorted(units)):
            h = (h0 + (h1 - h0) * i / max(n - 1, 1)) % 1.0
            l, sat = (0.36, 0.85) if i % 2 == 0 else (0.55, 0.80)
            out[u] = colorsys.hls_to_rgb(h, l, sat)
    return out

def _caidi_lines(ax, xlim, ylim):
    """Adds CAIDI markings to the plot"""
    x = np.array(xlim)
    for dur, lab in ((0.25, "CAIDI 15 min"), (1, "1 h"), (4, "4 h"), (16, "16 h")):
        ax.plot(x, dur * x, color="#cccccc", lw=0.8, zorder=1)
        if dur * xlim[1] <= ylim[1]:
            xl, yl, ha, va = xlim[1], dur * xlim[1], "right", "center"
        else:
            xl, yl, ha, va = ylim[1] / dur, ylim[1], "center", "top"
        ax.annotate(lab, (xl, yl), fontsize=7, color="#777777", ha=ha, va=va, zorder=2,
                    bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none"))

def site_years(m, min_months, min_meters):
    sy = indices(m, ["unit", "country", "project", "year"])
    return sy[(sy["n_months"] >= min_months) & (sy["meters"] >= min_meters) & (sy["saifi"] > 0) & (sy["saidi"] > 0)]

def panel_scatter(ax, m, min_months, min_meters, full_year_months=9):
    sy = indices(m, ["unit", "country", "project", "year"])
    sy = sy[(sy["n_months"] >= min_months) & (sy["meters"] >= min_meters) & (sy["saifi"] > 0) & (sy["saidi"] > 0)]
    full = sy["n_months"] >= full_year_months
    for country, col in COUNTRY_COLORS.items():
        for validated in (True, False):
            for is_full, size in ((True, 26), (False, 9)):
                s = sy[(sy["country"] == country) & (sy["project"].isin(VRM_PROJECTS) == validated) & (full == is_full)]
                ax.scatter(s["saifi"], s["saidi"], s=size, marker="o", lw=1.2 if is_full else 0.8,
                           facecolor=col if validated else "none", edgecolor=col, alpha=0.85, zorder=3)
    x = np.array([10, 2000])
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(10, 2000); ax.set_ylim(10, 20000)
    _caidi_lines(ax, (10,2000), (10, 20000))
    ax.set_xlabel("SAIFI (interruptions per customer per year)")
    ax.set_ylabel("SAIDI (hours per customer per year)")
    handles = [Line2D([], [], marker="o", ls="", color=KE_COLOR, label="Kenya"),
               Line2D([], [], marker="o", ls="", color=NG_COLOR, label="Nigeria"),
               Line2D([], [], marker="o", ls="", color="#777777", ms=3, label=f"< {full_year_months} months observed")]
    ax.legend(handles=handles, frameon=False, fontsize=8, loc="lower right")
    ax.set_title("(a) Site-year reliability indices", loc="left", fontsize=10)
    return sy

def panel_duration(ax, d):
    c = d[d["classification"] == "confirmed"]
    medians = []
    for country, col in COUNTRY_COLORS.items():
        k = c[c["country"] == country].groupby("duration_slots")["count"].sum().sort_index()
        k = k[k.index > 0]
        hours = k.index.to_numpy() * 0.25
        ccdf = 1 - np.cumsum(k.to_numpy()) / k.sum() + k.to_numpy() / k.sum()
        ax.step(hours, ccdf, where="post", color=col, lw=2, label=country)
        med = hours[np.searchsorted(-ccdf, -0.5)]
        ax.plot([med, med], [0, 0.5], color=col, lw=0.8, ls=":", zorder=1)
        medians.append((country, med, col))
    ax.set_xscale("log"); ax.set_xlim(0.25, 200); ax.set_ylim(0, 1)
    ax.set_xlabel("Interruption duration (h)")
    ax.set_ylabel("Share of interruptions lasting ≥ x")
    handles = [Line2D([], [], color=col, lw=2, label=f"{c} (median {med:g} h)") for c, med, col in medians]
    ax.legend(handles=handles, frameon=False, fontsize=8, loc="upper right")
    ax.set_title("(b) Duration of interruptions", loc="left", fontsize=10)

def panel_start_hour(ax, d):
    c = d[d["classification"] == "confirmed"]
    width = 0.42
    for i, (country, col) in enumerate(COUNTRY_COLORS.items()):
        h = c[c["country"] == country].groupby("start_hour")["count"].sum().reindex(range(24), fill_value=0)
        local = (np.arange(24) + UTC_OFFSET_H[country]) % 24
        share = pd.Series(h.to_numpy(), index=local).sort_index() / h.sum()
        ax.bar(share.index + (i - 0.5) * width, share.to_numpy(), width=width, color=col, label=country, lw=0)
    ax.set_xlim(-0.6, 23.6); ax.set_xticks([0, 6, 12, 18, 23])
    ax.set_xlabel("Interruption onset hour")
    ax.set_ylabel("Proportion of interruptions")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.set_title("(c) Timing of interruptions", loc="left", fontsize=10)

def panel_heatmap(ax, m, fig):
    mm = m.groupby(["unit", "country", "ym"], as_index=False)[["n_meters_served", "hours_confirmed"]].sum()
    mm = mm[mm["n_meters_served"] > 0]
    hours_in_month = pd.to_datetime(mm["ym"]).dt.days_in_month * 24
    mm["saidi_month"] = 100 * mm["hours_confirmed"] / mm["n_meters_served"] / hours_in_month   # % of time
    order = (indices(m, ["unit", "country"]).sort_values(["country", "saidi"], ascending=[True, False]))
    units = order["unit"].tolist()
    months = sorted(mm["ym"].unique())
    grid = mm.pivot(index="unit", columns="ym", values="saidi_month").reindex(index=units, columns=months)
    cmap = LinearSegmentedColormap.from_list("saidi", ["#f3f6fa", "#bdd1ea", "#6f9bd1", "#2f5f9e", "#0f2a52"])
    vals = grid.to_numpy(dtype=float)
    im = ax.imshow(np.ma.masked_invalid(vals), aspect="auto", cmap=cmap, vmin=0, vmax=100,
                   interpolation="nearest")
    ax.set_yticks(range(len(units)))
    ax.set_yticklabels([u.replace("_", " ").replace("Kalobeyei Settlement Village", "Kalobeyei V") for u in units], fontsize=7)
    for i, u in enumerate(units):
        ax.get_yticklabels()[i].set_color(COUNTRY_COLORS[order.loc[order["unit"] == u, "country"].iloc[0]])
    jan = [i for i, ym in enumerate(months) if ym.endswith("-01")]
    ax.set_xticks(jan); ax.set_xticklabels([months[i][:4] for i in jan], fontsize=8)
    ax.tick_params(axis="both", length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    cb.set_label("Share of customer-hours de-energized (%)", fontsize=8)
    cb.ax.tick_params(labelsize=7)
    ax.set_title("(d) Monthly de-energized share by site", loc="left", fontsize=10, pad=14)

def figure_siteyears(m, out_base, min_months, min_meters, full_year_months=9):
    sy = site_years(m, min_months, min_meters)
    full = sy["n_months"] >= full_year_months
    colors = site_colors({c: g["unit"].unique() for c, g in sy.groupby("country")})
    fig, ax = plt.subplots(figsize=(9.5, 6.2))
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(10, 2000); ax.set_ylim(10, 20000)
    _caidi_lines(ax, (10, 2000), (10, 20000))
    legends = {}
    for country in COUNTRY_COLORS:
        handles = []
        for unit in sorted(sy.loc[sy["country"] == country, "unit"].unique()):
            col = colors[unit]
            validated = sy.loc[sy["unit"] == unit, "project"].iloc[0] in VRM_PROJECTS
            for is_full, size in ((True, 30), (False, 10)):
                s = sy[(sy["unit"] == unit) & (full == is_full)]
                ax.scatter(s["saifi"], s["saidi"], s=size, marker="o", lw=1.2 if is_full else 0.8,
                           facecolor=col if validated else "none", edgecolor=col, alpha=0.9, zorder=3)
            handles.append(Line2D([], [], marker="o", ls="", ms=4.5, mfc=col if validated else "none", mec=col,
                                  label=unit.replace("_", " ")))
        legends[country] = handles
    ax.set_xlabel("SAIFI (interruptions per customer per year)")
    ax.set_ylabel("SAIDI (hours per customer per year)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title("Site-year reliability indices", loc="left", fontsize=10)
    fig.subplots_adjust(left=0.09, right=0.74, top=0.94, bottom=0.1)
    # two boxed legends outside the axes, one per country
    lk = ax.legend(handles=legends["Kenya"], title="Kenya", fontsize=7, title_fontsize=8, loc="upper left",
                   bbox_to_anchor=(1.02, 1.0), frameon=True, edgecolor=KE_COLOR, fancybox=False,
                   handletextpad=0.4, labelspacing=0.35, borderpad=0.7)
    lk.get_title().set_color(KE_COLOR)
    ax.add_artist(lk)
    ln = ax.legend(handles=legends["Nigeria"] + [Line2D([], [], marker="o", ls="", color="#777777", ms=2.5,
                                                          label=f"< {full_year_months} months")],
                   title="Nigeria", fontsize=7, title_fontsize=8, loc="lower left", bbox_to_anchor=(1.02, 0.0),
                   frameon=True, edgecolor=NG_COLOR, fancybox=False, handletextpad=0.4, labelspacing=0.35, borderpad=0.7)
    ln.get_title().set_color(NG_COLOR)
    fig.savefig(out_base + "_siteyears.png", dpi=200, bbox_inches="tight", bbox_extra_artists=[lk, ln])
    fig.savefig(out_base + "_siteyears.pdf", bbox_inches="tight", bbox_extra_artists=[lk, ln])
    print(f"Saved {out_base}_siteyears.png / .pdf")
    return colors

def figure_sites(m, out_base):
    st = indices(m, ["unit", "country", "project"])
    st = st[(st["saifi"] > 0) & (st["saidi"] > 0)]
    fig, ax = plt.subplots(figsize=(7, 6))
    x = np.array([10, 2000])
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(20, 1000); ax.set_ylim(80, 12000)
    ax.xaxis.set_minor_formatter(LogFormatterSciNotation(labelOnlyBase=False, minor_thresholds=(2, 0.5)))
    ax.tick_params(axis="x", which="minor", labelsize=7, rotation=45)
    for dur, lab in ((0.25, "CAIDI 15 min"), (1, "1 h"), (4, "4 h"), (16, "16 h")):
        ax.plot(x, dur * x, color="#dddddd", lw=0.8, zorder=1)
        if dur * 1000 <= 12000:
            xl, yl, ha, va = 1000, dur * 1000, "right", "center"
        else:
            xl, yl, ha, va = 12000 / dur, 12000, "center", "top"
        ax.annotate(lab, (xl, yl), fontsize=7, color="#777777", ha=ha, va=va, zorder=2,
                    bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none"))
    for country, col in COUNTRY_COLORS.items():
        for validated in (True, False):
            s = st[(st["country"] == country) & (st["project"].isin(VRM_PROJECTS) == validated)]
            ax.scatter(s["saifi"], s["saidi"], s=40, lw=1.3, facecolor=col if validated else "none",
                       edgecolor=col, zorder=3)
    for _, r in st.iterrows():
        name = r["unit"].replace("_", " ")
        dx, dy, ha = SITE_LABEL_OFFSETS.get(name, (7, 0, "left"))
        ax.annotate(name, (r["saifi"], r["saidi"]), fontsize=7, color=COUNTRY_COLORS[r["country"]],
                    xytext=(dx, dy), textcoords="offset points", va="center", ha=ha, zorder=4)
    ax.set_xlabel("SAIFI (interruptions per customer per year)")
    ax.set_ylabel("SAIDI (hours per customer per year)")
    ax.set_title("Reliability indices by site", loc="left", fontsize=10)
    fig.tight_layout()
    ax.spines[["top", "right"]].set_visible(False)
    handles = [Line2D([], [], marker="o", ls="", color=KE_COLOR, label="Kenya"),
               Line2D([], [], marker="o", ls="", color=NG_COLOR, label="Nigeria")]
    ax.legend(handles=handles, frameon=False, fontsize=8, loc="lower right")
    fig.savefig(out_base + "_sites.png", dpi=200); fig.savefig(out_base + "_sites.pdf")
    print(f"Saved {out_base}_sites.png / .pdf")

def figure_class(m, out_base, roll_up):
    cls = indices(m, ["unit", "country", "cust_class"])
    wide = cls.pivot(index="unit", columns="cust_class", values=["saidi", "saifi", "meters"])
    ok = (wide["meters"]["Residential"] >= MIN_CLASS_METERS) & (wide["meters"]["Commercial"] >= MIN_CLASS_METERS)
    wide = wide[ok]
    ctry = cls.drop_duplicates("unit").set_index("unit")["country"]
    order = wide.loc[wide.index].assign(c=ctry).sort_values(["c", ("saidi", "Residential")], ascending=[True, False]).index
    wide = wide.loc[order]
    y = np.arange(len(wide))
    fig, axes = plt.subplots(1, 2, figsize=(10, 0.28 * len(wide) + 1.6), sharey=True)
    for ax, metric, xlabel, ticks in (
            (axes[0], "saidi", "SAIDI (h per customer per year)", [100, 200, 500, 1000, 2000, 5000, 10000]),
            (axes[1], "saifi", "SAIFI (interruptions per customer per year)", [30, 50, 100, 200, 500, 1000])):
        r, c = wide[metric]["Residential"].to_numpy(), wide[metric]["Commercial"].to_numpy()
        ax.hlines(y, np.minimum(r, c), np.maximum(r, c), color="#cccccc", lw=1.5, zorder=1)
        ax.scatter(r, y, color=RES_COLOR, s=30, zorder=3, label="Residential")
        ax.scatter(c, y, color=COM_COLOR, s=30, zorder=3, label="Commercial")
        ax.set_xscale("log"); ax.set_xlabel(xlabel)
        lo, hi = min(r.min(), c.min()), max(r.max(), c.max())
        ticks = [t for t in ticks if lo / 1.6 <= t <= hi * 1.6]
        ax.set_xlim(lo / 1.3, hi * 1.3)
        ax.set_xticks(ticks); ax.set_xticklabels([f"{t:,}" for t in ticks])
        ax.xaxis.set_minor_locator(NullLocator())
        ax.tick_params(axis="x", labelsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="x", color="#eeeeee", lw=0.8)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([u.replace("_", " ").replace("Kalobeyei Settlement Village", "Kalobeyei V") for u in wide.index], fontsize=8)
    for i, u in enumerate(wide.index):
        axes[0].get_yticklabels()[i].set_color(COUNTRY_COLORS[ctry[u]])
    axes[0].invert_yaxis()
    axes[0].legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=2)
    fig.suptitle(f"Reliability by customer class, full period (label colour = country; "
                 f"sites with ≥ {MIN_CLASS_METERS} meters in each class)", fontsize=10, x=0.02, ha="left")
    fig.tight_layout()
    fig.savefig(out_base + "_class.png", dpi=200); fig.savefig(out_base + "_class.pdf")
    print(f"Saved {out_base}_class.png / .pdf")
    return wide

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graphics-dir", default="paper/graphics")
    ap.add_argument("--out", default="paper/graphics/fig_saidi_saifi")
    ap.add_argument("--keep-kalobeyei-villages", action="store_true",
                    help="keep the five Kalobeyei Settlement village files separate (default: one project)")
    ap.add_argument("--min-months", type=int, default=1, help="months observed for a site-year point")
    ap.add_argument("--full-year-months", type=int, default=9,
                    help="site-years with fewer observed months are drawn with a small marker")
    ap.add_argument("--min-meters", type=float, default=10, help="mean customers served for a site-year point")
    a = ap.parse_args()

    m, d = load(a.graphics_dir, not a.keep_kalobeyei_villages)

    fig = plt.figure(figsize=(12, 10.5))
    gs = fig.add_gridspec(2, 3, height_ratios=[1, 1.25], hspace=0.32, wspace=0.32)
    ax_a = fig.add_subplot(gs[0, 0]); ax_b = fig.add_subplot(gs[0, 1]); ax_c = fig.add_subplot(gs[0, 2])
    ax_d = fig.add_subplot(gs[1, :])
    sy = panel_scatter(ax_a, m, a.min_months, a.min_meters, a.full_year_months)
    panel_duration(ax_b, d)
    panel_start_hour(ax_c, d)
    for ax in (ax_a, ax_b, ax_c):
        ax.spines[["top", "right"]].set_visible(False)
    panel_heatmap(ax_d, m, fig)
    fig.savefig(a.out + ".png", dpi=200, bbox_inches="tight")
    fig.savefig(a.out + ".pdf", bbox_inches="tight")
    print(f"Saved {a.out}.png / .pdf")

    colors = figure_siteyears(m, a.out, a.min_months, a.min_meters, a.full_year_months)
    wide = figure_class(m, a.out, not a.keep_kalobeyei_villages)
    figure_sites(m, a.out)

    pd.set_option("display.width", 200)
    full = indices(m, ["unit", "country"]).sort_values(["country", "saidi"])
    print("\nFull-period indices per site:")
    print(full[["unit", "country", "n_months", "meters", "saifi", "saidi"]].round(1).to_string(index=False))
    print(f"\n{len(sy)} site-year points in panel (a)")

if __name__ == "__main__":
    main()
