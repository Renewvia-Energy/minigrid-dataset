#!/usr/bin/env python3
"""
Autocorrelation of 15-minute site load, per site, for the load-periodicity figure.

Reads the released per-site readings in data/ and saves:

  paper/graphics/acf_by_site_15min.csv
      Autocorrelation of the native 15-minute site load. Rows are lag in hours
      (0, 0.25, ... 100), columns are sites. This is the primary series.

  paper/graphics/acf_by_site_hourly.csv
      The same, after resampling each site's load to hourly sums. Robustness
      check only: it exists to show the peak structure is not an artefact of
      the 15-minute resolution.

  paper/graphics/acf_site_coverage.csv
      Per site: slots in the window, missing fraction, live-day fraction, the
      share of rows that are direct meter readings rather than gap fill,
      the share kept by the clean path's gap rule (blank on the raw path,
      which drops long gaps instead of accepting rows), and the two
      inclusion flags. Columns: site, n_slots, n_missing, missing_fraction,
      live_day_fraction, observed_row_fraction, accepted_row_fraction,
      selected, in_mean

  paper/graphics/acf_periodicity_by_site.csv
      Per site: rho at 12, 24, 48, 72 and 96 h, plus the local prominence of
      the 24-hour peak. Sorted by prominence, which is the panel order used by
      plot_acf_periodicity.py.

The load target
  Site load is the sum of per-slot energy over that site's *customer* meters in
  each 15-minute slot. Totalizer and pue meters are excluded: totalizers are
  fragmented across the fleet and inconsistent with the customer sums where both
  exist, and pue meters are metered separately from the household supply. Every
  site in the release resolves to this customer sum; none has a whole-grid
  totalizer with adequate coverage, so there is one code path, not two.

  A slot in which no customer meter reported is missing, not zero -- an unlit
  grid and an unreported one are different things, and treating the second as
  zero load would manufacture a nightly trough. Missing slots are carried
  through to the estimator as NaN rather than filled.

Two sources, and which one to use (--source)
  raw (default) reconstructs the per-slot series from
  data/sparkmeterreadings_<site>.parquet, and reproduces the published figure
  exactly. clean reads data/sparkmeterreadings_clean_<site>.parquet, which is
  much faster to run but is built for energy accounting rather than for
  periodicity; see the gap-fill section below for why that distinction matters
  here. The two agree closely on well-covered sites and diverge on gappy ones.

Window
  A fixed calendar quarter, 1 January to 2 April 2025 (91 days, 8736 slots).
  It is the last complete quarter in the release and the window over which the
  largest number of sites are simultaneously live. Set with --start / --end.

Site selection, in two steps, both reported in acf_site_coverage.csv
  1. A site is plotted if at least MIN_LIVE_DAY_FRACTION of the days in the
     window carry at least one customer reading. This drops sites that are
     only partly commissioned inside the window rather than genuinely gappy.
  2. Of those, a site enters the cross-site mean if at most
     MAX_MISSING_FRACTION of its slots are missing and at least
     --min-observed of its rows are direct meter readings. Sites that fail
     either test are still computed and still plotted, faintly and labelled --
     an exclusion should be visible, not invisible.

  On the raw path over the default window this selects 21 sites of the 27 in
  the release and averages 17 of them, which is the cohort of the published
  figure, arrived at from the data rather than from a model's training split.

Gap fill, and why this figure has to be explicit about it
  A SparkMeter records a cumulative energy counter and misses heartbeats, so a
  per-slot series has to be reconstructed by differencing that counter and
  spreading each difference over the slots it spans. Spreading it using the
  meter's own daily load profile is the natural choice, and it is what both
  sources do -- but it writes a daily shape into the slots it fills, which is
  precisely the quantity this figure measures. Over a twenty-minute gap that is
  a fair reconstruction of what the meter was doing. Over three weeks it is a
  statement about the profile, not about the site.

  So on the raw path a transition spanning more than MAX_GAP_SLOTS (24 h) is
  dropped rather than redistributed, short internal holes up to
  MAX_INTERPOLATE_SLOTS (2 h) are interpolated, and runs of real data shorter
  than MIN_SEGMENT_SLOTS (5 days) are dropped so that a lag never spans a dead
  zone and treats "before the hole" as the neighbour of "after the hole". What
  is left missing stays missing, and the estimator attenuates it toward zero.

  sparkmeterreadings_clean applies no such bound -- correct for energy
  accounting, where the total must be conserved, and the reason the clean path
  is not the default here. On that path --max-gap-hours applies the bound after
  the fact using imputation_method, 24 h by default; 0 keeps direct readings
  only and inf keeps every filled slot. acf_site_coverage.csv records
  observed_row_fraction on both paths and accepted_row_fraction on the clean
  one, so how much of each site is direct measurement is always visible.

Estimator
  Biased autocorrelation via FFT (denominator = the observed count, matching
  statsmodels' default adjusted=False). Missing slots are demeaned to zero, so
  they contribute nothing to any lag product while the denominator stays the
  observed count. A gappy site is therefore pulled toward zero rather than
  credited with the correlation of whichever points happened to survive; this
  is statsmodels' missing="conservative" semantics.

  No deseasonalising and no detrending anywhere in this script. The daily
  cycle is the thing being measured, so removing it would answer a different
  question.

  Each site is estimated separately and the sites are averaged afterwards --
  never one concatenated series, which would manufacture correlation across
  site boundaries and weight the largest site most.

Runtime: the clean path is a few minutes, since the window and the meter type
are pushed down into the parquet scan. The raw path is slower -- it reads every
customer heartbeat a site ever recorded, because trimming, interpolation and
segmentation are properties of the whole history, not of the window -- but it
holds one site at a time and reduces each to a single slot-indexed series
before opening the next.

Usage:
  python figures/acf_periodicity.py
  python figures/acf_periodicity.py --source clean
  python figures/acf_periodicity.py --start 2024-10-01 --end 2025-01-01
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from tqdm import tqdm

OUT_DIR = Path("paper/graphics")
DATA_DIR = Path("data")

SLOT_MINUTES = 15
SLOTS_PER_HOUR = 60 // SLOT_MINUTES

WINDOW_START = "2025-01-01"
WINDOW_END = "2025-04-02"          # exclusive

MAX_LAG_HOURS = 100.0              # covers the 24/48/72/96 h reference lags
MIN_LIVE_DAY_FRACTION = 0.50       # step 1: is the site live across the window
MAX_MISSING_FRACTION = 0.05        # step 2: is it complete enough for the mean
MIN_OBSERVED_FRACTION = 0.0        # step 2: how much of it is direct measurement
                                   # (0 = report the share, gate nothing on it)
MAX_GAP_HOURS = 24.0               # longest gap whose reconstruction is accepted

REFERENCE_HOURS = (12, 24, 48, 72, 96)

SLOTS_PER_DAY = 24 * SLOTS_PER_HOUR
SLOT_NS = SLOT_MINUTES * 60 * 1_000_000_000

# Reconstruction bounds for --source raw. These are the values the published
# figure was built with; they are the only free parameters on that path.
MAX_GAP_SLOTS = 96                 # 24 h: longest gap redistributed, not dropped
MAX_INTERPOLATE_SLOTS = 8          # 2 h: longest internal gap filled linearly
MIN_SEGMENT_SLOTS = 480            # 5 days: shorter runs of data are dropped

RAW_COLS = ["meter_serial", "meter_type", "heartbeatStart", "energy", "state"]
CLEAN_COLS = ["meter_customer_code", "meter_type", "slot_start", "energy_kwh",
              "imputation_method"]


# -- Estimator ---------------------------------------------------------------

def acf_with_gaps(x: np.ndarray, nlags: int) -> np.ndarray:
    """Biased ACF of a series that may contain NaN, via FFT. Returns lags 0..nlags.

    Missing slots are demeaned to zero so they contribute nothing to any lag
    product; the denominator stays the observed count, so a gappy series is
    pulled toward zero rather than being credited with the correlation of
    whichever points survived.
    """
    x = np.asarray(x, dtype=float)
    obs = np.isfinite(x)
    n = int(obs.sum())
    if n <= nlags:
        raise ValueError(f"series has {n} observed points, needs > nlags={nlags}")

    centred = np.where(obs, x - np.nanmean(x), 0.0)

    # Linear (not circular) autocovariance: zero-pad to >= 2N-1 before the transform.
    size = int(2 ** np.ceil(np.log2(2 * len(centred) - 1)))
    f = np.fft.rfft(centred, size)
    acov = np.fft.irfft(f * np.conjugate(f), size)[: nlags + 1] / n
    if acov[0] <= 0:
        return np.full(nlags + 1, np.nan)
    return acov / acov[0]


# -- Site load, reconstructed from the raw heartbeats ------------------------
#
# This is the path that reproduces the published figure exactly. It differs from
# sparkmeterreadings_clean in three ways that all matter to an autocorrelation:
# it keys meters by meter_serial, it refuses to redistribute a gap longer than
# MAX_GAP_SLOTS instead of filling it, and it cuts the series at the holes that
# leaves rather than bridging them.

def _slot_of_day(ts_ns: np.ndarray) -> np.ndarray:
    seconds_of_day = (ts_ns // 1_000_000_000) % 86400
    return (seconds_of_day // (SLOT_MINUTES * 60)).astype(int)


def _build_load_profile(t_prev_ns: np.ndarray, energy_diffs: np.ndarray) -> np.ndarray:
    """A meter's own 96-slot mean daily shape, from its clean single-slot transitions.

    Slots of the day the meter never reported cleanly take the overall mean, so
    a gap covering them is still redistributed rather than zeroed.
    """
    idx = _slot_of_day(t_prev_ns)
    totals = np.zeros(SLOTS_PER_DAY)
    counts = np.zeros(SLOTS_PER_DAY, dtype=int)
    np.add.at(totals, idx, energy_diffs)
    np.add.at(counts, idx, 1)
    has_data = counts > 0
    profile = np.where(has_data, totals / np.maximum(counts, 1), 0.0)
    profile[~has_data] = profile[has_data].mean() if has_data.any() else 0.0
    return profile


def reconstruct_meter(times_ns: np.ndarray, energy: np.ndarray, state: np.ndarray,
                      max_gap_slots: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One meter's per-slot energy from its cumulative counter.

    Returns (slot_start_ns, kwh, is_observed), where is_observed marks the slots
    backed by a direct single-slot reading rather than redistributed over a gap.

    Transitions are dropped where the counter goes backwards (a meter reset),
    where either endpoint is not in state 1, or where the gap is longer than
    max_gap_slots. That last one is the important one: a meter that goes silent
    for months still reports a valid cumulative counter when it returns, and
    spreading that jump across the silence invents months of load nobody
    measured -- with a daily shape, at the exact lag this figure reads.
    """
    n = len(times_ns)
    empty = (np.array([], np.int64), np.array([], np.float64), np.array([], bool))
    if n < 2:
        return empty

    diffs = np.diff(energy)
    gap_slots = np.round(np.diff(times_ns) / SLOT_NS).astype(int)
    t_prev = times_ns[:-1]

    st = np.where(np.isnan(state), -1, state)
    usable = (diffs >= 0) & (st[:-1] == 1) & (st[1:] == 1) & (gap_slots > 0)
    valid = usable & (gap_slots <= max_gap_slots)
    if not valid.any():
        return empty

    single = valid & (gap_slots == 1)
    profile = (_build_load_profile(t_prev[single], diffs[single]) if single.any()
               else np.zeros(SLOTS_PER_DAY))

    vi = np.where(valid)[0]
    spans, starts, totals = gap_slots[vi], t_prev[vi], diffs[vi]

    # Ragged 0..k-1 per transition, without a Python loop: the large sites have
    # hundreds of meters with tens of thousands of transitions each.
    rep = np.repeat(np.arange(len(vi)), spans)
    run_start = np.zeros(len(spans), dtype=np.int64)
    np.cumsum(spans[:-1], out=run_start[1:])
    offset = np.arange(int(spans.sum()), dtype=np.int64) - np.repeat(run_start, spans)
    slot_ns = starts[rep] + offset * SLOT_NS

    weights = profile[_slot_of_day(slot_ns)]
    w_sum = np.zeros(len(vi))
    np.add.at(w_sum, rep, weights)
    w_sum = w_sum[rep]

    is_single = (spans == 1)[rep]
    kwh = np.where(
        is_single,
        totals[rep],
        np.where(w_sum > 0,
                 totals[rep] * weights / np.where(w_sum > 0, w_sum, 1.0),
                 totals[rep] / spans[rep]),
    )
    return slot_ns.astype(np.int64), kwh.astype(np.float64), is_single


def site_load_from_raw(path: Path, max_gap_slots: int, max_interpolate_slots: int,
                       min_segment_slots: int) -> tuple[pd.Series, float]:
    """(whole 15-minute load history, observed slot-row fraction) from raw readings.

    Trimming, short-gap interpolation and segmentation are applied to the FULL
    history, not to the analysis window, because that is what decides whether a
    given slot inside the window survives. Windowing happens afterwards.
    """
    df = pq.read_table(path, columns=RAW_COLS,
                       filters=[("meter_type", "=", "customer")]).to_pandas()
    df = df[df["meter_type"] == "customer"]
    # meter_serial, not meter_customer_code: one customer code can cover two
    # simultaneously live meters, and differencing a cumulative counter across
    # the pair alternates between unrelated counters, so the negative diffs are
    # filtered out but the spurious positive jumps survive as invented load.
    df = df.dropna(subset=["meter_serial", "heartbeatStart"])
    if df.empty:
        return pd.Series(dtype=float), np.nan

    df["energy"] = pd.to_numeric(df["energy"], errors="coerce")
    df["state"] = pd.to_numeric(df["state"], errors="coerce")

    per_meter = []
    for _, g in df.groupby("meter_serial", sort=False, observed=True):
        g = g.sort_values("heartbeatStart")
        slot_ns, kwh, is_obs = reconstruct_meter(
            g["heartbeatStart"].to_numpy(dtype="datetime64[ns]").view(np.int64),
            g["energy"].to_numpy(dtype=float),
            g["state"].to_numpy(dtype=float),
            max_gap_slots,
        )
        if len(slot_ns):
            per_meter.append((slot_ns, kwh, is_obs))
    if not per_meter:
        return pd.Series(dtype=float), np.nan

    n_rows = sum(len(k) for _, k, _ in per_meter)
    observed = float(sum(int(o.sum()) for _, _, o in per_meter) / n_rows) if n_rows else np.nan

    lo = min(int(t.min()) for t, _, _ in per_meter)
    hi = max(int(t.max()) for t, _, _ in per_meter)
    origin = lo - (lo % SLOT_NS)
    n_slots = int((hi - origin) // SLOT_NS) + 1

    total = np.zeros(n_slots)
    reported = np.zeros(n_slots, dtype=np.int64)
    for slot_ns, kwh, _ in per_meter:
        idx = ((slot_ns - origin) // SLOT_NS).astype(np.int64)
        np.add.at(total, idx, kwh)
        np.add.at(reported, idx, 1)

    # A slot no meter reported in is missing, not a site that consumed nothing.
    s = pd.Series(np.where(reported > 0, total, np.nan),
                  index=pd.to_datetime(origin + np.arange(n_slots) * SLOT_NS))

    # Trim the all-missing head and tail, then fill only short internal gaps.
    valid = s.notna().to_numpy()
    if not valid.any():
        return pd.Series(dtype=float), observed
    s = s.iloc[valid.argmax():len(valid) - valid[::-1].argmax()]
    s = s.interpolate(limit=max_interpolate_slots, limit_area="inside")

    # Segmentation: cut what is left into runs of real data and drop the runs too
    # short to be a series. This is what keeps a lag from spanning a dead zone
    # and treating "before the hole" as the neighbour of "after the hole".
    keep = s.notna().to_numpy()
    boundary = np.empty(len(keep), dtype=bool)
    boundary[0] = True
    boundary[1:] = keep[1:] != keep[:-1]
    run_id = np.cumsum(boundary) - 1
    run_len = np.bincount(run_id)[run_id]
    return s.where(keep & (run_len >= min_segment_slots)), observed


# -- Site load, read from the cleaned per-slot table --------------------------

def gap_run_slots(df: pd.DataFrame) -> np.ndarray:
    """Length, in slots, of the filled run each row belongs to (1 if observed).

    A meter's missed heartbeats appear in the clean table as a run of
    consecutive rows carrying imputation_method 'profile' or 'uniform' between
    two direct readings. That run *is* the gap, so its length is what decides
    whether the reconstruction over it is short enough to trust. Rows are
    sorted by meter and slot; a run ends at a meter change, a break in slot
    contiguity, or a direct reading.
    """
    imputed = (df["imputation_method"] != "observed").to_numpy()
    meter = df["meter_customer_code"].to_numpy()
    slots = df["slot_start"].to_numpy()

    starts = np.empty(len(df), dtype=bool)
    starts[0] = True
    starts[1:] = (
        (meter[1:] != meter[:-1])
        | (np.diff(slots) != np.timedelta64(SLOT_MINUTES, "m"))
        | (~imputed[:-1])
    )
    run_id = np.cumsum(starts)
    lengths = np.bincount(run_id)[run_id]
    return np.where(imputed, lengths, 1)


def site_load_series(path: Path, grid: pd.DatetimeIndex,
                     max_gap_slots: float) -> tuple[pd.Series, float, float]:
    """(customer load on the 15-minute grid, observed row fraction, accepted fraction).

    Slots with no accepted row are NaN. The window and the meter type are
    pushed into the parquet scan, so a site that spans seven years costs one
    quarter's worth of rows to read.
    """
    table = pq.read_table(
        path,
        columns=CLEAN_COLS,
        filters=[
            ("meter_type", "=", "customer"),
            ("slot_start", ">=", grid[0].to_pydatetime()),
            ("slot_start", "<=", grid[-1].to_pydatetime()),
        ],
    )
    df = table.to_pandas()
    if df.empty:
        return pd.Series(np.nan, index=grid), np.nan, np.nan

    # A parquet filter prunes row groups and is a coarse pre-filter, not a
    # guarantee on individual rows: re-apply both conditions in pandas.
    df = df[(df["meter_type"] == "customer")]
    df = df[(df["slot_start"] >= grid[0]) & (df["slot_start"] <= grid[-1])]
    if df.empty:
        return pd.Series(np.nan, index=grid), np.nan, np.nan

    # How much of this site's window is direct measurement rather than gap fill.
    # Measured on rows, not on energy: one meter-slot is one observation of the
    # load, whatever it consumed.
    observed = float((df["imputation_method"] == "observed").mean())

    df = df.sort_values(["meter_customer_code", "slot_start"], kind="stable")
    # copy=True: a Series can hand back a read-only view, and this is built up in place.
    keep = (df["imputation_method"] == "observed").to_numpy(copy=True)
    if np.isfinite(max_gap_slots):
        keep |= gap_run_slots(df) <= max_gap_slots
    df = df[keep]
    accepted = float(keep.mean())
    if df.empty:
        return pd.Series(np.nan, index=grid), observed, accepted

    # Sum across this site's customer meters. A slot in which no meter has an
    # accepted row has no rows at all, so reindexing onto the grid is what
    # makes it NaN; summing an empty group would have made it a fabricated zero.
    per_slot = df.groupby("slot_start", sort=True)["energy_kwh"].sum()
    per_slot.index = pd.to_datetime(per_slot.index)
    return per_slot.reindex(grid), observed, accepted


def live_day_fraction(s: pd.Series) -> float:
    """Fraction of calendar days in the window with at least one reporting slot."""
    by_day = s.notna().groupby(s.index.date).any()
    return float(by_day.mean()) if len(by_day) else 0.0


def peak_summary(acf_native: pd.DataFrame) -> pd.DataFrame:
    """Per-site rho at each reference lag, plus the local prominence of the 24 h peak.

    Prominence = rho(24h) - mean(rho(18h), rho(30h)). A series with a real daily
    cycle sits above its own neighbourhood at 24 h; one that is merely slowly
    decaying does not, so this separates periodicity from persistence.
    """
    out = {f"rho_{h}h": acf_native.loc[float(h)] for h in REFERENCE_HOURS
           if float(h) in acf_native.index}
    df = pd.DataFrame(out)
    if {18.0, 24.0, 30.0} <= set(acf_native.index):
        df["prominence_24h"] = (
            acf_native.loc[24.0] - 0.5 * (acf_native.loc[18.0] + acf_native.loc[30.0])
        )
        df = df.sort_values("prominence_24h", ascending=False)
    df.index.name = "site"
    return df


# -- Driver ------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Per-site ACF of 15-minute site load.")
    ap.add_argument("--start", default=WINDOW_START, help="window start (UTC, inclusive)")
    ap.add_argument("--end", default=WINDOW_END, help="window end (UTC, exclusive)")
    ap.add_argument("--max-lag-hours", type=float, default=MAX_LAG_HOURS)
    ap.add_argument("--max-missing", type=float, default=MAX_MISSING_FRACTION,
                    help="a site above this missing fraction is plotted but not averaged")
    ap.add_argument("--min-live-days", type=float, default=MIN_LIVE_DAY_FRACTION,
                    help="a site below this live-day fraction is not plotted at all")
    ap.add_argument("--min-observed", type=float, default=MIN_OBSERVED_FRACTION,
                    help="a site whose rows are less than this fraction direct meter "
                         "readings is plotted but not averaged")
    ap.add_argument("--source", choices=("raw", "clean"), default="raw",
                    help="raw: reconstruct site load from sparkmeterreadings_<site>.parquet, "
                         "which reproduces the published figure exactly. clean: read "
                         "sparkmeterreadings_clean_<site>.parquet, which is faster but "
                         "carries that table's unbounded gap fill (default: raw)")
    ap.add_argument("--max-gap-hours", type=float, default=MAX_GAP_HOURS,
                    help="--source clean only: accept reconstructed slots only where the "
                         "gap they fill is no longer than this; 0 keeps direct readings "
                         "only, inf keeps every reconstructed slot (default: 24)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    grid = pd.date_range(args.start, args.end, freq=f"{SLOT_MINUTES}min", inclusive="left")
    nlags = int(round(args.max_lag_hours * SLOTS_PER_HOUR))
    max_gap_slots = args.max_gap_hours * SLOTS_PER_HOUR
    if args.source == "raw":
        prefix = "sparkmeterreadings_"
        site_files = sorted(f for f in DATA_DIR.glob("sparkmeterreadings_*.parquet")
                            if not f.stem.startswith("sparkmeterreadings_clean_"))
    else:
        prefix = "sparkmeterreadings_clean_"
        site_files = sorted(DATA_DIR.glob("sparkmeterreadings_clean_*.parquet"))
    if not site_files:
        raise SystemExit(
            f"No {prefix}*.parquet in {DATA_DIR}/ -- see the README for how to obtain the "
            "dataset."
        )

    print(f"Window {args.start} .. {args.end}  ({len(grid)} slots of {SLOT_MINUTES} min)")
    if args.source == "raw":
        print(f"Reconstructing site load from raw readings: gaps over "
              f"{MAX_GAP_SLOTS / SLOTS_PER_HOUR:g} h dropped, internal gaps up to "
              f"{MAX_INTERPOLATE_SLOTS / SLOTS_PER_HOUR:g} h interpolated, runs shorter "
              f"than {MIN_SEGMENT_SLOTS / SLOTS_PER_HOUR / 24:g} days dropped")
    else:
        print(f"Reading the cleaned table: reconstructed slots accepted where the gap "
              f"is <= {args.max_gap_hours:g} h")
    print(f"Loading {len(site_files)} sites from {DATA_DIR}/ ...")

    native, hourly, coverage = {}, {}, []
    for path in tqdm(site_files, desc="sites", unit="site"):
        site = path.stem.replace(prefix, "")
        if args.source == "raw":
            full, observed = site_load_from_raw(path, MAX_GAP_SLOTS,
                                                MAX_INTERPOLATE_SLOTS, MIN_SEGMENT_SLOTS)
            s = full.reindex(grid) if len(full) else pd.Series(np.nan, index=grid)
            accepted = np.nan  # the raw path drops long gaps rather than accepting rows
        else:
            s, observed, accepted = site_load_series(path, grid, max_gap_slots)

        n_obs = int(s.notna().sum())
        row = {
            "site": site,
            "n_slots": int(len(s)),
            "n_missing": int(len(s) - n_obs),
            "missing_fraction": float(1 - n_obs / len(s)),
            "live_day_fraction": live_day_fraction(s),
            "observed_row_fraction": observed,
            "accepted_row_fraction": accepted,
        }
        # Two independent gates, both recorded: `selected` is "live enough to show",
        # `in_mean` is "complete enough to average". A site can be the first and not
        # the second, and the figure draws exactly that distinction.
        row["selected"] = bool(row["live_day_fraction"] >= args.min_live_days
                               and n_obs > nlags)
        row["in_mean"] = bool(row["selected"]
                              and row["missing_fraction"] <= args.max_missing
                              and observed >= args.min_observed)
        coverage.append(row)
        if not row["selected"]:
            continue

        native[site] = acf_with_gaps(s.to_numpy(), nlags)
        # energy per slot, so the hourly series is a SUM; min_count keeps an hour
        # that is only partly reported missing rather than quietly short.
        h = s.resample("1h").sum(min_count=SLOTS_PER_HOUR)
        hourly[site] = acf_with_gaps(h.to_numpy(), int(round(args.max_lag_hours)))

    if not native:
        raise SystemExit("No site met the live-day threshold; nothing to write.")

    lag_h = np.arange(nlags + 1) / SLOTS_PER_HOUR
    acf_native = pd.DataFrame(native, index=pd.Index(lag_h, name="lag_hours")).sort_index(axis=1)
    acf_hourly = pd.DataFrame(
        hourly,
        index=pd.Index(np.arange(int(round(args.max_lag_hours)) + 1, dtype=float),
                       name="lag_hours"),
    ).sort_index(axis=1)
    coverage = pd.DataFrame(coverage)
    peaks = peak_summary(acf_native)

    for name, df, kw in [
        ("acf_by_site_15min.csv", acf_native, {}),
        ("acf_by_site_hourly.csv", acf_hourly, {}),
        ("acf_site_coverage.csv", coverage, {"index": False}),
        ("acf_periodicity_by_site.csv", peaks, {}),
    ]:
        out = OUT_DIR / name
        df.to_csv(out, **kw)
        print(f"Saved {out}")

    # -- Summary -------------------------------------------------------------

    in_mean = list(coverage.loc[coverage.in_mean, "site"])
    dropped = coverage[coverage.selected & ~coverage.in_mean]
    skipped = coverage[~coverage.selected]
    print(f"\n{len(coverage)} sites in {DATA_DIR}/, {int(coverage.selected.sum())} live enough "
          f"to plot, {len(in_mean)} in the cross-site mean")
    for _, r in skipped.iterrows():
        print(f"  not plotted: {r['site']} (live on {r.live_day_fraction:.0%} of days)")
    for _, r in dropped.iterrows():
        print(f"  plotted but not averaged: {r['site']} (missing {r.missing_fraction:.1%}, "
              f"{r.observed_row_fraction:.1%} of rows directly observed)")

    if not in_mean:
        # Reachable with a strict --max-gap-hours or --min-observed: the CSVs are
        # still written and still plottable per site, there is just no mean to take.
        print("\nNo site passed the missing-fraction gate, so there is no cross-site mean. "
              "Loosen --max-gap-hours or --max-missing, or read the per-site columns.")
        return

    print("\nMean autocorrelation across the retained sites:")
    for h in REFERENCE_HOURS:
        if float(h) in acf_native.index:
            print(f"  {h:>3} h  rho={acf_native.loc[float(h), in_mean].mean():+.3f}")
    p = peaks.loc[in_mean, "prominence_24h"]
    print(f"24 h prominence: median={p.median():+.3f}  min={p.min():+.3f}  max={p.max():+.3f}  "
          f"positive at {int((p > 0).sum())}/{len(p)} sites")
    o = coverage.loc[coverage.in_mean, "observed_row_fraction"].dropna()
    if len(o):
        print(f"Directly observed rows, across those sites: median={o.median():.1%}  "
              f"min={o.min():.1%}  max={o.max():.1%}")

    # A site with many meters can keep every slot occupied while most of its rows
    # are refused: one meter in a thousand is enough for the slot to exist, and
    # missing_fraction alone will not notice. Say so rather than gate on it --
    # the threshold to gate at is a judgement for whoever reads the coverage
    # table, and --min-observed is where it goes.
    thin = coverage[coverage.in_mean & (coverage.accepted_row_fraction.fillna(1.0) < 0.5)]
    for _, r in thin.iterrows():
        print(f"  NOTE: {r['site']} is in the mean on {r.missing_fraction:.1%} missing slots, "
              f"but only {r.accepted_row_fraction:.1%} of its rows survived the gap rule")


if __name__ == "__main__":
    main()
