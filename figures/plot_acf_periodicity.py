#!/usr/bin/env python3
"""
Load periodicity: the autocorrelation of 15-minute site load.

Reads the CSVs produced by acf_periodicity.py and saves:

  paper/graphics/acf_mean_across_sites.png / .pdf
      Mean autocorrelation across the retained sites against lag in hours, with
      the hourly-resampled series overlaid as a robustness check and a ±1 SD
      band across sites. Peaks at 24, 48, 72 and 96 h with troughs at 12 and
      36 h are the daily cycle; the band is the spread between sites, not a
      confidence interval.

  paper/graphics/acf_by_site_panels.png / .pdf
      One panel per site, ordered by the prominence of that site's 24-hour
      peak, so a reader can check that the cycle in the mean is universal
      rather than driven by a subset. Sites too gappy for a stable estimate are
      drawn in grey and labelled: the estimator attenuates rho toward zero
      under missingness, so a flat grey curve reflects coverage rather than an
      absent daily cycle.

  paper/graphics/acf_load_periodicity.png / .pdf
      Both panels on one sheet.

Neither panel carries a title, subtitle or footnote inside the artwork: the
manuscript carries the caption, and a second copy inside the figure would
contradict it the first time either is edited.

Lag runs from zero and INCREASES left to right, as an autocorrelation
conventionally does. The reference lines at 12, 24, 48, 72 and 96 h are the
anchor common to both panels.

Nothing here estimates anything -- the CSV column names and the estimator live
in acf_periodicity.py, which must be run first.

Usage:
  python figures/acf_periodicity.py       # first: builds the CSVs
  python figures/plot_acf_periodicity.py  # then: draws the figures
"""

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

OUT_DIR = Path("paper/graphics")
NATIVE_CSV = OUT_DIR / "acf_by_site_15min.csv"
HOURLY_CSV = OUT_DIR / "acf_by_site_hourly.csv"
COVERAGE_CSV = OUT_DIR / "acf_site_coverage.csv"
PEAKS_CSV = OUT_DIR / "acf_periodicity_by_site.csv"

FORMATS = ("png", "pdf")
REFERENCE_HOURS = (12, 24, 48, 72, 96)
LABELLED_PEAKS = (24, 48, 72, 96)
NCOL = 3  # panels per row in the small multiples

# Palette. INK/MUTED carry the in-mean vs excluded distinction in panel (b), so
# they must stay distinguishable in greyscale as well as in colour.
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
WHITE = "#FFFFFF"
PRIMARY = "#2a78d6"
ROBUST = "#eb6834"  # hourly-resampled overlay; distinct from PRIMARY when printed grey

# DejaVu Sans first: it ships with matplotlib, so the figure renders identically
# on any machine. A platform font here would silently change metrics elsewhere.
FONT_STACK = ["DejaVu Sans", "Arial", "Helvetica"]


def apply_style() -> None:
    plt.rcParams.update({
        "figure.facecolor": WHITE,
        "axes.facecolor": WHITE,
        "savefig.facecolor": WHITE,
        "font.family": "sans-serif",
        "font.sans-serif": FONT_STACK,
        "font.size": 9,
        "axes.titlesize": 10.5,
        "axes.labelsize": 9,
        "axes.labelcolor": INK_2,
        "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "grid.linestyle": "-",          # solid hairlines; dashing reads as "threshold"
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.frameon": False,
        "legend.fontsize": 8,
        "figure.dpi": 140,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
    })


def despine(ax, keep=("left", "bottom")) -> None:
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(side in keep)


def save(fig, name: str) -> None:
    for fmt in FORMATS:
        out = OUT_DIR / f"{name}.{fmt}"
        fig.savefig(out, format=fmt)
        print(f"Saved {out}")
    plt.close(fig)


def site_label(site: str) -> str:
    """Published file names are long; panel titles are 2.6 inches wide.

    Case-insensitive: a title that keeps the full settlement name is wide enough
    to run into the next panel's, so this must not depend on how the file name
    happens to be capitalised.
    """
    short = re.sub(r"kalobeyei[_ ]settlement[_ ]village[_ ]", "K.S.V. ", site,
                   flags=re.IGNORECASE)
    return short.replace("_", " ").replace("-", " ")


def mark_reference_lags(ax, xmax: float, label: bool = True) -> None:
    top = ax.get_ylim()[1]
    for h in REFERENCE_HOURS:
        if h > xmax:
            continue
        ax.axvline(h, color=AXIS, linewidth=0.9, zorder=0)
        if label:
            ax.text(h, top, f" {h}h", fontsize=7.5, color=INK_2, va="top", ha="left")


# -- Panel (a): the cross-site mean ------------------------------------------

def panel_mean(ax, acf_native: pd.DataFrame, acf_hourly: pd.DataFrame,
               in_mean: list[str], n_obs: int) -> None:
    mean = acf_native[in_mean].mean(axis=1)
    sd = acf_native[in_mean].std(axis=1)

    ax.axhline(0, color=AXIS, linewidth=0.8, zorder=1)
    ax.fill_between(mean.index, mean - sd, mean + sd, color=PRIMARY, alpha=0.16,
                    linewidth=0, zorder=2)
    ax.plot(mean.index, mean.values, color=PRIMARY, linewidth=1.8,
            solid_capstyle="round", zorder=4, label="15-min series")

    if not acf_hourly.empty:
        hu = [c for c in in_mean if c in acf_hourly.columns]
        hm = acf_hourly[hu].mean(axis=1)
        ax.plot(hm.index, hm.values, color=ROBUST, linewidth=1.2, linestyle=(0, (4, 2)),
                zorder=3, label="hourly-resampled")

    # White-noise bound. At n ~ 8.7k it is ±0.02 -- drawn so the reader can see
    # it is far below every peak, not because it is a meaningful test for a
    # series this autocorrelated.
    wn = 1.96 / np.sqrt(n_obs)
    ax.fill_between(mean.index, -wn, wn, color=MUTED, alpha=0.22, linewidth=0, zorder=1)

    xmax = float(mean.index.max())
    ax.set_xlim(0, xmax)
    ax.set_xticks([0, 12, 24, 48, 72, 96])
    ax.set_xlabel("Lag (hours)")
    ax.set_ylabel("Mean autocorrelation across sites")
    mark_reference_lags(ax, xmax)
    despine(ax)

    # Every daily peak the caption names carries its own marker and value. The
    # first three labels sit to the right of their marker; at 96 h that offset
    # would run past the right spine, so the last is mirrored to the left of its
    # dot rather than dropped -- which would leave a peak marked by a reference
    # line but unlabelled, contradicting the caption.
    for h in LABELLED_PEAKS:
        if float(h) not in mean.index:
            continue
        v = float(mean.loc[float(h)])
        ax.plot([h], [v], marker="o", markersize=4.5, color=PRIMARY,
                markeredgecolor=WHITE, markeredgewidth=1.1, zorder=5)
        flip = (h + 1.4) > xmax - 4.0
        ax.text(h - 1.4 if flip else h + 1.4, v + 0.035, f"{v:.2f}",
                fontsize=8, color=INK_2, ha="right" if flip else "left")

    # Legend below the axes, in one row. Every in-axes corner is occupied: the
    # curve fills the lower half between peaks, and the top edge carries the
    # 12/24/48/72/96 h reference labels, so anything placed inside would sit on
    # either the data or those labels.
    handles, labels = ax.get_legend_handles_labels()
    handles.append(Patch(facecolor=PRIMARY, alpha=0.16, linewidth=0))
    labels.append("±1 SD across sites")
    ax.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, -0.155),
              ncol=3, fontsize=7.6, handlelength=2.2, columnspacing=1.8, frameon=False)


# -- Panel (b): one small multiple per site ----------------------------------

def panel_small_multiples(fig, gs, acf_native: pd.DataFrame, peaks: pd.DataFrame,
                          coverage: pd.DataFrame) -> None:
    missing_by_site = dict(zip(coverage["site"], coverage["missing_fraction"]))
    in_mean_by_site = dict(zip(coverage["site"], coverage["in_mean"]))
    order = [s for s in peaks.index if s in acf_native.columns]
    n = len(order)
    nrow = int(np.ceil(n / NCOL))

    # The bottom edge of the grid is "has no panel below it", which is not the same
    # as "is in the last row" whenever the site count is not a multiple of NCOL --
    # a partial last row would otherwise leave the panels above it unlabelled, and
    # the axis label on a column that does not exist.
    bottom = [i for i in range(n) if i + NCOL >= n]
    label_at = next((i for i in bottom if i % NCOL == 1), bottom[len(bottom) // 2])

    for i in range(nrow * NCOL):
        ax = fig.add_subplot(gs[i // NCOL, i % NCOL])
        if i >= n:
            ax.axis("off")
            continue
        site = order[i]
        keep = bool(in_mean_by_site.get(site, False))
        y = acf_native[site]

        ax.axhline(0, color=GRID, linewidth=0.7, zorder=1)
        for h in REFERENCE_HOURS:
            ax.axvline(h, color=GRID, linewidth=0.7, zorder=0)
        ax.plot(y.index, y.values, color=PRIMARY if keep else MUTED,
                linewidth=1.2 if keep else 1.0, alpha=1.0 if keep else 0.75, zorder=3)

        ax.set_ylim(-0.75, 1.02)
        ax.set_xlim(0, float(y.index.max()))
        ax.set_xticks([24, 48, 72, 96])
        ax.set_yticks([0, 0.5, 1.0])
        ax.tick_params(labelsize=6.5)
        if i % NCOL != 0:
            ax.set_yticklabels([])
        if i not in bottom:
            ax.set_xticklabels([])
        if i == label_at:
            ax.set_xlabel("Lag (hours)", fontsize=8)

        rho24 = float(y.loc[24.0]) if 24.0 in y.index else np.nan
        ax.set_title(f"{site_label(site)}  $\\rho_{{24}}$={rho24:.2f}", loc="left",
                     fontsize=7.6, color=INK if keep else MUTED, pad=3)
        if not keep:
            ax.text(0.97, 0.92, f"{missing_by_site[site]:.0%} missing — not in mean",
                    transform=ax.transAxes, fontsize=6.2, color=MUTED, ha="right", va="top")
        ax.grid(False)
        despine(ax)


# -- Driver ------------------------------------------------------------------

def lag_indexed(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0)
    df.index = df.index.astype(float)
    df.index.name = "lag_hours"
    return df


def as_bool(s: pd.Series) -> pd.Series:
    """A CSV round-trip can hand back the strings "True"/"False".

    astype(bool) on those is True for both, which would silently pull the
    excluded sites back into the mean.
    """
    if s.dtype == object:
        return s.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
    return s.astype(bool)


def main() -> None:
    missing = [p.name for p in (NATIVE_CSV, HOURLY_CSV, COVERAGE_CSV, PEAKS_CSV)
               if not p.exists()]
    if missing:
        raise SystemExit(f"Missing {', '.join(missing)} in {OUT_DIR}/ -- "
                         "run `python figures/acf_periodicity.py` first.")

    acf_native = lag_indexed(NATIVE_CSV)
    acf_hourly = lag_indexed(HOURLY_CSV)
    coverage = pd.read_csv(COVERAGE_CSV)
    coverage["in_mean"] = as_bool(coverage["in_mean"])
    coverage["selected"] = as_bool(coverage["selected"])
    peaks = pd.read_csv(PEAKS_CSV, index_col=0)

    in_mean = [s for s in acf_native.columns
               if s in set(coverage.loc[coverage.in_mean, "site"])]
    if not in_mean:
        raise SystemExit("No site passed the missing-fraction gate; nothing to average.")
    # The white-noise bound is drawn for the *worst* covered site in the mean,
    # so it is never narrower than the data supports. Taking the min of n_slots
    # and the max of n_missing separately could pair two different sites and
    # give a negative count.
    obs_per_site = (coverage.loc[coverage.in_mean, "n_slots"]
                    - coverage.loc[coverage.in_mean, "n_missing"])
    n_obs = max(int(obs_per_site.min()), 1)

    print(f"Sites plotted: {acf_native.shape[1]}   in the cross-site mean: {len(in_mean)}")
    for _, r in coverage[coverage.selected & ~coverage.in_mean].iterrows():
        print(f"  excluded from the mean: {r['site']} (missing {r.missing_fraction:.1%})")
    print("Mean autocorrelation at the reference lags:")
    for h in REFERENCE_HOURS:
        if float(h) in acf_native.index:
            print(f"  {h:>3} h  rho={acf_native.loc[float(h), in_mean].mean():+.3f}")

    apply_style()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nrow = int(np.ceil(len([s for s in peaks.index if s in acf_native.columns]) / NCOL))

    # (a) the cross-site mean, standalone
    fig_a, ax_a = plt.subplots(figsize=(7.6, 4.0))
    panel_mean(ax_a, acf_native, acf_hourly, in_mean, n_obs)
    save(fig_a, "acf_mean_across_sites")

    # (b) the per-site small multiples, standalone. Emitted as its own file
    # because the manuscript places (a) and (b) as separate figures; cropping
    # them out of the combined sheet would resample the type.
    fig_b = plt.figure(figsize=(7.8, 0.92 + 1.05 * nrow))
    gs_b = fig_b.add_gridspec(nrows=nrow, ncols=NCOL, top=0.955, bottom=0.075,
                              hspace=0.62, wspace=0.12)
    panel_small_multiples(fig_b, gs_b, acf_native, peaks, coverage)
    save(fig_b, "acf_by_site_panels")

    # both panels on one sheet
    height = 4.9 + 1.05 * nrow
    fig = plt.figure(figsize=(7.8, height))
    gs_top = fig.add_gridspec(nrows=1, ncols=1, top=0.975, bottom=1 - 3.5 / height)
    panel_mean(fig.add_subplot(gs_top[0, 0]), acf_native, acf_hourly, in_mean, n_obs)
    gs_bot = fig.add_gridspec(nrows=nrow, ncols=NCOL, top=1 - 4.5 / height, bottom=0.045,
                              hspace=0.62, wspace=0.12)
    panel_small_multiples(fig, gs_bot, acf_native, peaks, coverage)
    save(fig, "acf_load_periodicity")


if __name__ == "__main__":
    main()
