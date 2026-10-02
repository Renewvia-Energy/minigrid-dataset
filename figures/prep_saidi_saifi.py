#!/usr/bin/env python3
"""
Compute SAIDI/SAIFI from VRM generation telemetry (vrmgeneration.parquet).

A gap in VRM reporting is classified as a confirmed outage when the system does
not resume with positive AC load or battery voltage after the gap — indicating
the grid was down, not just VRM connectivity lost. Only the 16 VRM-instrumented
projects are included; sites without VRM are excluded.

VRM timestamps are UTC despite the column name "timestamp_local".

Run this before plot_saidi_saifi.py

Outputs:
    saidi_saifi_monthly.csv
    saidi_saifi_durations.csv
    saidi_saifi_site_hourly.csv
    saidi_saifi_events.csv

Usage:
    python figures/prep_saidi_saifi.py
    python figures/prep_saidi_saifi.py --data-dir data --out-dir paper/graphics
    python figures/prep_saidi_saifi.py --overwrite
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

SLOT_S = 900                    # classification resolution (seconds)
SLOT_NS = SLOT_S * 10**9
MIN_VALID_TS = pd.Timestamp("2018-01-01").value
MAX_VALID_TS = pd.Timestamp("2027-01-01").value
T0_NS = pd.Timestamp("2018-01-01").value
N_SLOTS = int((MAX_VALID_TS - T0_NS) // SLOT_NS)
VOLT_MIN = 10.0                 # V: below this, inverter considered off

VRM_COLS = [
    "timestamp_local", "Project_Name",
    "System_overview_AC_Consumption_L1",
    "System_overview_AC_Consumption_L2",
    "System_overview_AC_Consumption_L3",
    "System_overview_Voltage",
]

# VRM Project_Name → (site_key, country)
VRM_MAP = {
    "Balep":            ("Balep",          "Nigeria"),
    "Bendeghe-Afi":     ("Bendeghe-Afi",   "Nigeria"),
    "Ekong Anaku":      ("Ekong_Anaku",    "Nigeria"),
    "Emereoke":         ("Emereoke",       "Nigeria"),
    "Kakuma 3 - Okapi": ("Kakuma_3A",      "Kenya"),
    "Kangitan Kori":    ("Kangitan_Kori",  "Kenya"),
    "Kapelbok":         ("Kapelbok",       "Kenya"),
    "Locheremoit":      ("Locheremoit",    "Kenya"),
    "Lomekwi":          ("Lomekwi",        "Kenya"),
    "Lorengelup":       ("Lorengelup",     "Kenya"),
    "Nakukulas":        ("Nakukulas",      "Kenya"),
    "Ndeda":            ("Ndeda",          "Kenya"),
    "Olkiramatian":     ("Olkiramatian",   "Kenya"),
    "Opu":              ("Opu",            "Nigeria"),
    "Oyamo":            ("Oyamo",          "Kenya"),
    "Ozuzu":            ("Ozuzu",          "Nigeria"),
}


def _month_index(ts_ns: np.ndarray) -> np.ndarray:
    return ts_ns.view("datetime64[ns]").astype("datetime64[M]").astype(np.int64)

def _month_start_ns(month_idx: np.ndarray) -> np.ndarray:
    return month_idx.astype("datetime64[M]").astype("datetime64[ns]").astype(np.int64)

def _ym_label(month_idx: np.ndarray) -> np.ndarray:
    lo, hi = int(month_idx.min()), int(month_idx.max())
    labels = np.array([f"{1970 + m // 12}-{m % 12 + 1:02d}" for m in range(lo, hi + 1)])
    return labels[month_idx - lo]

def _split_by_month(start_ns: np.ndarray, end_ns: np.ndarray):
    """Returns (event_index, month_index, hours) with one row per event-month."""
    m0 = _month_index(start_ns)
    m1 = _month_index(end_ns - 1)
    n_span = m1 - m0 + 1
    ev_idx = np.repeat(np.arange(len(start_ns)), n_span)
    offs = np.arange(int(n_span.sum())) - np.repeat(np.cumsum(n_span) - n_span, n_span)
    month = m0[ev_idx] + offs
    lo = np.maximum(start_ns[ev_idx], _month_start_ns(month))
    hi = np.minimum(end_ns[ev_idx], _month_start_ns(month + 1))
    return ev_idx, month, (hi - lo) / 3.6e12


def load_vrm(vrm_path: str) -> dict:
    """Returns {project_name: sorted DataFrame} with load_w and volt columns."""
    df = pd.read_parquet(vrm_path, columns=VRM_COLS)
    for c in VRM_COLS[2:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["load_w"] = df[["System_overview_AC_Consumption_L1",
                        "System_overview_AC_Consumption_L2",
                        "System_overview_AC_Consumption_L3"]].sum(axis=1, min_count=1)
    df = df.rename(columns={"System_overview_Voltage": "volt"})
    df = df[df["Project_Name"].isin(VRM_MAP)].copy()
    df["ts_ns"] = df["timestamp_local"].to_numpy(dtype="datetime64[ns]").view(np.int64)
    df = df[(df["ts_ns"] >= MIN_VALID_TS) & (df["ts_ns"] < MAX_VALID_TS)]
    return {
        proj: g.sort_values("ts_ns").reset_index(drop=True)
        for proj, g in df.groupby("Project_Name")
    }


POST_GAP_LOOK = 5    # number of readings after gap to check for grid-up evidence

def classify_gaps(ts_ns: np.ndarray, load_w: np.ndarray, volt: np.ndarray,
                  max_gap_s: float):
    """
    Find gaps > SLOT_S and classify each as 'confirmed', 'comms', or 'long'.

    Confirmed: grid was likely down during the gap.
    Comms:     grid ran through the gap; VRM lost connectivity.
    Long:      gap exceeds max_gap_s — excluded from analysis.

    A gap is classified as comms if any of the POST_GAP_LOOK readings immediately
    after the gap shows volt > VOLT_MIN or load > 0. Some VRM devices (e.g. Kakuma)
    return null voltage on the first reading after reconnection even when the system
    ran continuously, so checking only the first reading produces false outages.
    """
    gaps_ns = np.diff(ts_ns)
    gap_idx = np.flatnonzero(gaps_ns > SLOT_NS)
    if len(gap_idx) == 0:
        empty_i = np.array([], dtype=np.int64)
        return empty_i, empty_i, np.array([], dtype=float), np.array([], dtype=object)

    starts = ts_ns[gap_idx]
    ends   = ts_ns[gap_idx + 1]
    dur_s  = gaps_ns[gap_idx].astype(float) / 1e9
    n      = len(ts_ns)

    # For each gap, check up to POST_GAP_LOOK readings after it for grid-up signal
    grid_up = np.zeros(len(gap_idx), dtype=bool)
    for k in range(POST_GAP_LOOK):
        idx_k = np.minimum(gap_idx + 1 + k, n - 1)
        nv = np.nan_to_num(volt[idx_k],   nan=-1.0)
        nl = np.nan_to_num(load_w[idx_k], nan=-1.0)
        grid_up |= (nv > VOLT_MIN) | (nl > 0)

    cls = np.where(
        dur_s > max_gap_s, "long",
        np.where(grid_up, "comms", "confirmed")
    )
    return starts, ends, dur_s, cls


def process_site(project: str, df: pd.DataFrame, max_gap_days: float):
    site_key, country = VRM_MAP[project]
    ts_ns  = df["ts_ns"].to_numpy()
    load_w = df["load_w"].to_numpy()
    volt   = df["volt"].to_numpy()

    starts, ends, dur_s, cls = classify_gaps(ts_ns, load_w, volt, max_gap_days * 86400)

    monthly_parts = []
    duration_parts = []
    slot_out = {c: np.zeros(N_SLOTS + 1, dtype=np.int64) for c in ("confirmed", "comms")}

    for label in ("confirmed", "comms"):
        sel = cls == label
        if not sel.any():
            continue
        s0, s1, dk = starts[sel], ends[sel], dur_s[sel]

        ei, em, eh = _split_by_month(s0, s1)
        monthly_parts.append(
            pd.DataFrame({"month": em, "classification": label, "n": 1, "hours": eh})
            .groupby(["month", "classification"])[["n", "hours"]].sum().reset_index()
        )

        slots_k = np.maximum(np.rint(dk / SLOT_S).astype(np.int64), 1)
        start_h = ((s0 // 10**9) % 86400) // 3600
        duration_parts.append(
            pd.DataFrame({"classification": label, "start_hour": start_h,
                          "duration_slots": slots_k})
            .groupby(["classification", "start_hour", "duration_slots"]).size()
            .rename("count").reset_index()
        )

        lo = np.clip((s0 - T0_NS) // SLOT_NS, 0, N_SLOTS)
        hi = np.clip((s1 - T0_NS) // SLOT_NS, 0, N_SLOTS)
        slot_out[label] += np.bincount(lo, minlength=N_SLOTS + 1)
        slot_out[label] -= np.bincount(hi, minlength=N_SLOTS + 1)

    all_months = np.unique(_month_index(ts_ns))

    agg = (
        pd.concat(monthly_parts, ignore_index=True)
        .groupby(["month", "classification"])[["n", "hours"]].sum()
        if monthly_parts else None
    )

    def col(label, field):
        if agg is not None and label in agg.index.get_level_values("classification"):
            return agg.xs(label, level="classification")[field].reindex(
                all_months, fill_value=0.0)
        return pd.Series(0.0, index=pd.Index(all_months, name="month"))

    # n_meters_served = 1 throughout: SAIDI = outage-h/year and SAIFI = events/year
    # because n_confirmed/n_meters_served = events and hours_confirmed/n_meters_served = outage-h.
    monthly = pd.DataFrame({
        "site":             site_key,
        "project":          project,
        "country":          country,
        "cust_class":       "All",
        "ym":               _ym_label(all_months),
        "n_meters_served":  1,
        "n_confirmed":      col("confirmed", "n").astype(int).values,
        "hours_confirmed":  col("confirmed", "hours").values,
        "hours_presilence": 0.0,
        "hours_reassoc":    0.0,
        "n_comms":          col("comms", "n").astype(int).values,
        "hours_comms":      col("comms", "hours").values,
        "n_long":           0,
        "hours_long":       0.0,
        "n_short":          0,
    })

    if duration_parts:
        durations = (
            pd.concat(duration_parts, ignore_index=True)
            .groupby(["classification", "start_hour", "duration_slots"], as_index=False)
            ["count"].sum()
        )
    else:
        durations = pd.DataFrame(
            columns=["classification", "start_hour", "duration_slots", "count"])

    slot_report = np.bincount((ts_ns - T0_NS) // SLOT_NS, minlength=N_SLOTS)
    per_hour = 3600 // SLOT_S
    hourly_ts = pd.to_datetime(
        T0_NS + np.arange(N_SLOTS // per_hour) * 3600 * 10**9, unit="ns")
    hourly = pd.DataFrame({
        "hour_utc":             hourly_ts,
        "meters_reporting":     slot_report.reshape(-1, per_hour).mean(axis=1),
        "meters_out_confirmed": np.cumsum(slot_out["confirmed"])[:N_SLOTS]
                                    .reshape(-1, per_hour).mean(axis=1),
        "meters_out_comms":     np.cumsum(slot_out["comms"])[:N_SLOTS]
                                    .reshape(-1, per_hour).mean(axis=1),
    })
    num_cols = ["meters_reporting", "meters_out_confirmed", "meters_out_comms"]
    hourly = hourly[hourly[num_cols].sum(axis=1) > 0]
    hourly[num_cols] = hourly[num_cols].round(3)

    conf = cls == "confirmed"
    if conf.any():
        events = pd.DataFrame({
            "outage_start_utc": pd.to_datetime(starts[conf], unit="ns"),
            "restoration_utc":  pd.to_datetime(ends[conf],   unit="ns"),
            "duration_h":       (dur_s[conf] / 3600).round(3),
        }).sort_values("outage_start_utc").reset_index(drop=True)
    else:
        events = pd.DataFrame(columns=["outage_start_utc", "restoration_utc", "duration_h"])

    for frame in (durations, hourly, events):
        frame.insert(0, "country", country)
        frame.insert(0, "project", project)
        frame.insert(0, "site",    site_key)

    n_conf  = int((cls == "confirmed").sum())
    n_comms = int((cls == "comms").sum())
    n_total = n_conf + n_comms
    share   = f"{100 * n_conf / n_total:.1f}%" if n_total else "n/a"
    conf_h  = float(monthly["hours_confirmed"].sum())
    print(f"  {project}: {len(ts_ns):,} readings, {len(all_months)} months | "
          f"gaps: confirmed {n_conf:,}  comms {n_comms:,}  "
          f"long {int((cls == 'long').sum()):,} | "
          f"confirmed share {share} | {conf_h:,.1f} outage-h")

    return monthly, durations, hourly, events


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir",     default="data")
    ap.add_argument("--out-dir",      default="paper/graphics")
    ap.add_argument("--max-gap-days", type=float, default=30.0)
    ap.add_argument("--overwrite",    action="store_true",
                    help="recompute even if outputs already exist")
    a = ap.parse_args()

    vrm_path = os.path.join(a.data_dir, "vrmgeneration.parquet")
    if not os.path.exists(vrm_path):
        sys.exit(f"{vrm_path} not found")

    out_monthly   = os.path.join(a.out_dir, "saidi_saifi_monthly.csv")
    out_durations = os.path.join(a.out_dir, "saidi_saifi_durations.csv")
    out_hourly    = os.path.join(a.out_dir, "saidi_saifi_site_hourly.csv")
    out_events    = os.path.join(a.out_dir, "saidi_saifi_events.csv")

    if not a.overwrite and all(
            os.path.exists(p) for p in (out_monthly, out_durations, out_hourly, out_events)):
        print("All outputs exist; use --overwrite to recompute.")
        return

    os.makedirs(a.out_dir, exist_ok=True)

    print("Loading VRM data …")
    vrm = load_vrm(vrm_path)
    print(f"  {len(vrm)} projects loaded")

    print(f"Processing {len(vrm)} projects; max gap {a.max_gap_days:g} days …")
    all_monthly, all_durations, all_hourly, all_events = [], [], [], []
    for project in sorted(vrm):
        m, d, h, e = process_site(project, vrm[project], a.max_gap_days)
        all_monthly.append(m)
        all_durations.append(d)
        all_hourly.append(h)
        all_events.append(e)

    monthly   = pd.concat(all_monthly,   ignore_index=True).sort_values(["site", "ym"])
    durations = pd.concat(all_durations, ignore_index=True).sort_values(
        ["site", "classification", "start_hour", "duration_slots"])
    hourly    = pd.concat(all_hourly,    ignore_index=True)
    events    = pd.concat(all_events,    ignore_index=True)

    monthly.to_csv(out_monthly,     index=False)
    durations.to_csv(out_durations, index=False)
    hourly.to_csv(out_hourly,       index=False)
    events.to_csv(out_events,       index=False)

    print(f"\nSaved {out_monthly}  ({len(monthly):,} rows)")
    print(f"Saved {out_durations}  ({len(durations):,} rows)")
    print(f"Saved {out_hourly}  ({len(hourly):,} rows)")
    print(f"Saved {out_events}  ({len(events):,} rows)")

    tot = monthly[["n_confirmed", "hours_confirmed", "n_comms"]].sum()
    print(f"\nFleet totals: {int(tot.n_confirmed):,} confirmed interruptions "
          f"({tot.hours_confirmed:,.0f} outage-hours), {int(tot.n_comms):,} comms gaps")


if __name__ == "__main__":
    main()
