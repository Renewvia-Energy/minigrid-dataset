#!/usr/bin/env python3
"""
Pull interruption data from sparkmeterreadings for the SAIDI and SAIFI reliability metrics

Run this before plot_saidi_saifi.py

Outputs:
    saidi_saifi_monthly.csv
    saidi_saifi_durations.csv
    saidi_saifi_site_hourly.csv
    saidi_saifi_events.csv

Usage:
    python figures/prep_saidi_saifi.py
    python figures/prep_saidi_saifi.py Akipelai Ndeda
    python figures/prep_saidi_saifi.py --data-dir data --out-dir paper/graphics --max-gap-days 30
    python figures/prep_saidi_saifi.py --overwrite
"""

import argparse
import glob
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SLOT_S = 900                     # heartbeat period (seconds)
UPTIME_TOL_S = 60                # tolerance on uptime vs gap comparison
DUP_S = SLOT_S / 2               # gaps shorter than this are assumed to be duplicate readings
CLUSTER_GAP_S = 300              # reboot clusters
SITEWIDE_FRAC = 0.30             # cluster >= this share of meters served that month = site-wide outage
SLOT_NS = SLOT_S * 10**9
MIN_VALID_TS = pd.Timestamp("2018-01-01").value
MAX_VALID_TS = pd.Timestamp("2027-01-01").value
T0_NS = pd.Timestamp("2018-01-01").value
N_SLOTS = int((MAX_VALID_TS - T0_NS) // SLOT_NS)
BATCH_SIZE = 2_000_000

READ_COLUMNS = ["meter_customer_code", "meter_type", "heartbeatStart", "uptime", "meter_tariff_name"]

#pulled from prep_acpu.py
FILENAME_MAP: dict[str, tuple[str, str]] = {
    "Akipelai":                            ("Akipelai",              "Nigeria"),
    "Balep":                               ("Balep",                 "Nigeria"),
    "Bendeghe-Afi":                        ("Bendeghe-Afi",          "Nigeria"),
    "Ekong_Anaku":                         ("Ekong Anaku",           "Nigeria"),
    "Emereoke":                            ("Emereoke",              "Nigeria"),
    "Kakuma_3A":                           ("Kakuma 3 - Okapi",      "Kenya"),
    "Kalobeyei_Settlement_Village_1A":     ("Kalobeyei Settlement",  "Kenya"),
    "Kalobeyei_Settlement_Village_1B":     ("Kalobeyei Settlement",  "Kenya"),
    "Kalobeyei_Settlement_Village_2A":     ("Kalobeyei Settlement",  "Kenya"),
    "Kalobeyei_Settlement_Village_2B":     ("Kalobeyei Settlement",  "Kenya"),
    "Kalobeyei_Settlement_Village_3A":     ("Kalobeyei Settlement",  "Kenya"),
    "Kalobeyei_Town":                      ("Kalobeyei Town",        "Kenya"),
    "Kangitan_Kori":                       ("Kangitan Kori",         "Kenya"),
    "Kapelbok":                            ("Kapelbok",              "Kenya"),
    "Katiko":                              ("Katiko",                "Kenya"),
    "Locheremoit":                         ("Locheremoit",           "Kenya"),
    "Lomekwi":                             ("Lomekwi",               "Kenya"),
    "Lorengelup":                          ("Lorengelup",            "Kenya"),
    "Nakukulas":                           ("Nakukulas",             "Kenya"),
    "Ndeda":                               ("Ndeda",                 "Kenya"),
    "Ngurunit":                            ("Ngurunit",              "Kenya"),
    "Olkiramatian":                        ("Olkiramatian",          "Kenya"),
    "Oloibiri":                            ("Oloibiri",              "Nigeria"),
    "Opu":                                 ("Opu",                   "Nigeria"),
    "Oyamo":                               ("Oyamo",                 "Kenya"),
    "Ozuzu":                               ("Ozuzu",                 "Nigeria"),
    "Ringiti":                             ("Ringiti",               "Kenya"),
}

def find_site_files(data_dir: str) -> dict[str, list[str]]:
    files: dict[str, list[str]] = defaultdict(list)
    for p in sorted(glob.glob(os.path.join(data_dir, "sparkmeterreadings_*.parquet"))):
        stem = os.path.basename(p)[len("sparkmeterreadings_"):-len(".parquet")]
        if not stem.startswith("clean_"):
            files[stem].append(p)
    for d in sorted(glob.glob(os.path.join(data_dir, "sparkmeterreadings", "*"))):
        if os.path.isdir(d):
            files[os.path.basename(d)].extend(sorted(glob.glob(os.path.join(d, "*.parquet"))))
    return dict(files)

def _month_index(ts_ns: np.ndarray) -> np.ndarray:
    return ts_ns.view("datetime64[ns]").astype("datetime64[M]").astype(np.int64)

def _month_start_ns(month_idx: np.ndarray) -> np.ndarray:
    return month_idx.astype("datetime64[M]").astype("datetime64[ns]").astype(np.int64)

def _ym_label(month_idx: np.ndarray) -> np.ndarray:
    lo, hi = int(month_idx.min()), int(month_idx.max())
    labels = np.array([f"{1970 + m // 12}-{m % 12 + 1:02d}" for m in range(lo, hi + 1)])
    return labels[month_idx - lo]

def _split_by_month(start_ns: np.ndarray, end_ns: np.ndarray):
    """
    Returns (event_index, month_index, hours) with one row per event-month
    """
    m0 = _month_index(start_ns)
    m1 = _month_index(end_ns - 1)          # last month touched (end exclusive)
    n_span = m1 - m0 + 1
    ev_idx = np.repeat(np.arange(len(start_ns)), n_span)
    offs = np.arange(int(n_span.sum())) - np.repeat(np.cumsum(n_span) - n_span, n_span)
    month = m0[ev_idx] + offs
    lo = np.maximum(start_ns[ev_idx], _month_start_ns(month))
    hi = np.minimum(end_ns[ev_idx], _month_start_ns(month + 1))
    return ev_idx, month, (hi - lo) / 3.6e12

class SiteAccumulator:
    """Carry state and running aggregates for one site"""

    def __init__(self, max_gap_s: float):
        self.max_gap_s = max_gap_s
        self.carry: dict[str, tuple[int, int]] = {}      # code -> (last_ts_ns, last_uptime)
        self.served: set[tuple[str, str, int]] = set()   # (code, cust_class, month_idx)
        self.monthly_parts: list[pd.DataFrame] = []      # cust_class, month, cls, n, hours
        self.duration_parts: list[pd.DataFrame] = []     # cust_class, cls, start_hour, k, count
        self.conf_parts: list[pd.DataFrame] = []         # raw confirmed events, resolved in finalize
        self.n_rows = 0
        self.n_out_of_order = 0
        self.n_dup = 0
        self.n_events: dict[str, int] = {"confirmed": 0, "comms": 0, "long": 0, "short": 0}
        self.slot_report = np.zeros(N_SLOTS, dtype=np.int64)
        self.slot_out = {c: np.zeros(N_SLOTS + 1, dtype=np.int64)
                         for c in ("confirmed", "presilence", "reassoc", "comms")}

    def _add_series(self, cls: str, lo_ns: np.ndarray, hi_ns: np.ndarray) -> None:
        lo = np.clip((lo_ns - T0_NS) // SLOT_NS, 0, N_SLOTS)
        hi = np.clip((hi_ns - T0_NS) // SLOT_NS, 0, N_SLOTS)
        self.slot_out[cls] += np.bincount(lo, minlength=N_SLOTS + 1)
        self.slot_out[cls] -= np.bincount(hi, minlength=N_SLOTS + 1)

    def _add_hours(self, cust_class, cls: str, lo_ns, hi_ns, n_month=None) -> None:
        parts = []
        if n_month is not None:
            parts.append(pd.DataFrame({"cust_class": cust_class, "month": n_month,
                                       "classification": cls, "n": 1, "hours": 0.0}))
        keep = hi_ns > lo_ns
        if keep.any():
            ei, em, eh = _split_by_month(lo_ns[keep], hi_ns[keep])
            parts.append(pd.DataFrame({"cust_class": np.asarray(cust_class)[keep][ei], "month": em,
                                       "classification": cls, "n": 0, "hours": eh}))
        if parts:
            self.monthly_parts.append(
                pd.concat(parts, ignore_index=True)
                .groupby(["cust_class", "month", "classification"], as_index=False)[["n", "hours"]].sum())

    def _add_durations(self, cust_class, cls: str, start_ns, slots) -> None:
        dur = pd.DataFrame({"cust_class": cust_class, "classification": cls,
                            "start_hour": ((start_ns // 10**9) % 86400) // 3600, "duration_slots": slots})
        self.duration_parts.append(
            dur.groupby(["cust_class", "classification", "start_hour", "duration_slots"]).size()
            .rename("count").reset_index())

    def process_batch(self, bdf: pd.DataFrame) -> None:
        bdf = bdf[bdf["meter_type"] == "customer"].dropna(subset=["meter_customer_code"])
        if bdf.empty:
            return
        ts_all = pd.to_datetime(bdf["heartbeatStart"], errors="coerce")
        bdf = bdf.assign(
            ts=ts_all.to_numpy(dtype="datetime64[ns]").view(np.int64),
            up=pd.to_numeric(bdf["uptime"], errors="coerce"),
        )
        bdf = bdf[ts_all.notna().to_numpy() & (bdf["ts"] >= MIN_VALID_TS) & (bdf["ts"] < MAX_VALID_TS)
                  & bdf["up"].notna()]
        if bdf.empty:
            return
        code_id, code_uniq = pd.factorize(bdf["meter_customer_code"].astype(str))
        order = np.lexsort((bdf["ts"].to_numpy(), code_id))
        bdf = bdf.iloc[order]
        code_id = code_id[order]
        self.n_rows += len(bdf)

        codes = code_uniq.to_numpy()[code_id]
        ts = bdf["ts"].to_numpy()
        up = bdf["up"].to_numpy(dtype=np.int64)
        tar_id, tar_uniq = pd.factorize(bdf["meter_tariff_name"].astype(str))
        tar_is_res = pd.Series(tar_uniq).str.contains("Residential", case=False, na=False).to_numpy()
        cust_class = np.where(tar_is_res[tar_id], "Residential", "Commercial")
        month = _month_index(ts)

        # Meters served
        srv = pd.DataFrame({"c": codes, "k": cust_class, "m": month}).drop_duplicates()
        self.served.update(zip(srv["c"], srv["k"], srv["m"]))

        # Heartbeats per slot
        self.slot_report += np.bincount((ts - T0_NS) // SLOT_NS, minlength=N_SLOTS)

        n = len(ts)
        same = np.r_[False, codes[1:] == codes[:-1]]
        prev_ts = np.full(n, -1, dtype=np.int64)
        prev_ts[same] = ts[np.flatnonzero(same) - 1]
        first_idx = np.flatnonzero(~same)
        for i in first_idx:
            c = self.carry.get(codes[i])
            if c is not None:
                prev_ts[i] = c[0]

        last_idx = np.r_[first_idx[1:] - 1, n - 1]
        self.carry.update(zip(codes[last_idx], zip(ts[last_idx].tolist(), up[last_idx].tolist())))

        has_prev = prev_ts >= 0
        gap_s = (ts - prev_ts) / 1e9
        ooo = has_prev & (gap_s < 0)
        self.n_out_of_order += int(ooo.sum())
        dup = has_prev & ~ooo & (gap_s < DUP_S)
        self.n_dup += int(dup.sum())
        valid = has_prev & ~ooo & ~dup

        k = np.rint(gap_s / SLOT_S).astype(np.int64) - 1
        rebooted = up < (gap_s - UPTIME_TOL_S)
        long_gap = gap_s > self.max_gap_s

        cls = np.full(n, "", dtype=object)
        cls[valid & (k >= 1) & long_gap] = "long"
        cls[valid & (k >= 1) & ~long_gap & rebooted] = "confirmed"
        cls[valid & (k >= 1) & ~long_gap & ~rebooted] = "comms"
        cls[valid & (k == 0) & rebooted] = "short"

        ev = cls != ""
        if not ev.any():
            return
        e_cls, e_k, e_class, e_code = cls[ev], k[ev], cust_class[ev], codes[ev]
        # Gap = [end of last received heartbeat period, start of next received one)
        start_ns = prev_ts[ev] + SLOT_NS
        end_ns = start_ns + e_k * SLOT_NS
        for c in self.n_events:
            self.n_events[c] += int((e_cls == c).sum())

        gap = e_cls != "short"
        if gap.any():
            ei, em, _ = _split_by_month(start_ns[gap], end_ns[gap])
            srv = pd.DataFrame({"c": e_code[gap][ei], "k": e_class[gap][ei], "m": em}).drop_duplicates()
            self.served.update(zip(srv["c"], srv["k"], srv["m"]))
        
        for c in ("comms", "long"):
            sel = e_cls == c
            if sel.any():
                self._add_hours(e_class[sel], c, start_ns[sel], end_ns[sel], n_month=_month_index(start_ns[sel]))
                self._add_durations(e_class[sel], c, start_ns[sel], e_k[sel])
                if c == "comms":
                    self._add_series("comms", start_ns[sel], end_ns[sel])
        sel = e_cls == "short"
        if sel.any():
            self._add_hours(e_class[sel], "short", start_ns[sel], start_ns[sel], n_month=_month_index(start_ns[sel]))

        sel = e_cls == "confirmed"
        if sel.any():
            reboot_ns = np.clip(ts[ev][sel] - up[ev][sel] * 10**9, start_ns[sel], end_ns[sel])
            self.conf_parts.append(pd.DataFrame({
                "start_ns": start_ns[sel], "reboot_ns": reboot_ns, "end_ns": end_ns[sel],
                "cust_class": e_class[sel]}))

    def _resolve_confirmed(self):
        """
        Cluster confirmed interruptions by reboot instant and bound each
        member's outage start by the cluster's latest last-heartbeat

        Returns (events frame with off_start_ns, clusters frame)
        """
        if not self.conf_parts:
            return None, None
        ev = pd.concat(self.conf_parts, ignore_index=True).sort_values("reboot_ns", kind="stable")
        rb = ev["reboot_ns"].to_numpy()
        new_cluster = np.r_[True, np.diff(rb) > CLUSTER_GAP_S * 10**9]
        cid = np.cumsum(new_cluster) - 1
        ev["cluster"] = cid

        cl_start = ev.groupby("cluster")["start_ns"].max()
        off_start = cl_start.to_numpy()[cid]
        flagged = off_start > rb
        off_start = np.where(flagged, ev["start_ns"].to_numpy(), off_start)
        ev["off_start_ns"] = off_start
        ev["flagged"] = flagged

        clusters = ev.groupby("cluster").agg(
            outage_start_ns=("off_start_ns", "min"), restoration_ns=("reboot_ns", "median"),
            n_meters=("reboot_ns", "size"), n_flagged=("flagged", "sum"),
            first_reboot=("reboot_ns", "min"), last_reboot=("reboot_ns", "max"))
        clusters["reboot_spread_s"] = (clusters["last_reboot"] - clusters["first_reboot"]) / 1e9
        return ev, clusters

    def _attribute_sitewide(self, ev, clusters):
        """
        Returns (cust_class, win_start_ns, win_end_ns) arrays of attributions
        and adds n_attributed to clusters
        """
        served = (pd.DataFrame(list(self.served), columns=["code", "cust_class", "month"])
                  .groupby("month").size())
        c_start = clusters["outage_start_ns"].to_numpy().astype(np.int64)
        c_end = clusters["restoration_ns"].to_numpy().astype(np.int64)
        c_month = _month_index(c_start)
        n_served = served.reindex(c_month).fillna(0).to_numpy()
        sitewide = np.flatnonzero((clusters["n_meters"].to_numpy() >= SITEWIDE_FRAC * n_served) & (n_served > 0))
        clusters["n_attributed"] = 0
        if len(sitewide) == 0:
            return None

        s0 = ev["start_ns"].to_numpy(); s1 = ev["off_start_ns"].to_numpy()
        e_cl = ev["cluster"].to_numpy(); cc = ev["cust_class"].to_numpy()
        min_win = (c_end[sitewide] - c_start[sitewide]).min()
        cand = np.flatnonzero((s1 - s0) >= max(min_win, SLOT_NS))
        if len(cand) == 0:
            return None
        cs0, cs1, ccl, ccc = s0[cand], s1[cand], e_cl[cand], cc[cand]
        order = np.argsort(cs0); cs0, cs1, ccl, ccc = cs0[order], cs1[order], ccl[order], ccc[order]

        out_c, out_a, out_b = [], [], []
        n_attr = np.zeros(len(clusters), dtype=np.int64)
        for c in sitewide:
            a, b = c_start[c], c_end[c]
            hi = np.searchsorted(cs0, a, side="right")
            m = (cs1[:hi] >= b) & (ccl[:hi] != c)
            if m.any():
                k = int(m.sum()); n_attr[c] = k
                out_c.append(ccc[:hi][m]); out_a.append(np.full(k, a)); out_b.append(np.full(k, b))
        clusters["n_attributed"] = n_attr
        if not out_c:
            return None
        return np.concatenate(out_c), np.concatenate(out_a), np.concatenate(out_b)

    def finalize(self, site: str, project: str, country: str):
        ev, clusters = self._resolve_confirmed()
        diag = {}
        if ev is not None:
            cc = ev["cust_class"].to_numpy()
            s0, s1, s2, s3 = (ev[c].to_numpy() for c in ("start_ns", "off_start_ns", "reboot_ns", "end_ns"))
            self._add_hours(cc, "confirmed", s1, s2, n_month=_month_index(s1))
            self._add_hours(cc, "presilence", s0, s1)
            self._add_hours(cc, "reassoc", s2, s3)
            self._add_durations(cc, "confirmed", s1, np.rint((s2 - s1) / SLOT_NS).astype(np.int64))
            self._add_series("confirmed", s1, s2)
            self._add_series("presilence", s0, s1)
            self._add_series("reassoc", s2, s3)

            attr = self._attribute_sitewide(ev, clusters)
            attr_hours = 0.0
            if attr is not None:
                ac, aa, ab = attr
                self.n_events["confirmed"] += len(ac)
                self._add_hours(ac, "confirmed", aa, ab, n_month=_month_index(aa))
                self._add_hours(ac, "presilence_attributed", aa, ab)   # negative below
                self._add_durations(ac, "confirmed", aa, np.rint((ab - aa) / SLOT_NS).astype(np.int64))
                self._add_series("confirmed", aa, ab)
                self._add_series("presilence", ab, aa)
                attr_hours = float(((ab - aa) / 3.6e12).sum())

            size = clusters["n_meters"].to_numpy()[ev["cluster"].to_numpy()]
            pres_h = float(((s1 - s0) / 3.6e12).sum())
            conf_h = float(((s2 - s1) / 3.6e12).sum())
            diag = dict(
                share_in_clusters_ge5=float((size >= 5).mean()),
                share_flagged=float(ev["flagged"].mean()),
                median_cluster_size=float(np.median(size)),
                presilence_share=(pres_h - attr_hours) / max(pres_h + conf_h, 1e-9),
                n_attributed=int(len(attr[0])) if attr is not None else 0,
                attributed_hours=attr_hours,
                n_sitewide=int((clusters["n_attributed"] >= 0).sum()) if "n_attributed" in clusters else 0,
            )

        served = (pd.DataFrame(list(self.served), columns=["code", "cust_class", "month"])
                  .groupby(["cust_class", "month"]).size().rename("n_meters_served"))
        monthly = served.to_frame()
        agg = (pd.concat(self.monthly_parts, ignore_index=True)
               .groupby(["cust_class", "month", "classification"])[["n", "hours"]].sum()
               if self.monthly_parts else None)

        def col(cls, field, default):
            if agg is not None and cls in agg.index.get_level_values(2):
                return agg.xs(cls, level="classification")[field]
            return default

        monthly["n_confirmed"] = col("confirmed", "n", 0)
        monthly["hours_confirmed"] = col("confirmed", "hours", 0.0)
        monthly["hours_presilence"] = col("presilence", "hours", 0.0) - col("presilence_attributed", "hours", 0.0)
        monthly["hours_reassoc"] = col("reassoc", "hours", 0.0)
        monthly["n_comms"] = col("comms", "n", 0)
        monthly["hours_comms"] = col("comms", "hours", 0.0)
        monthly["n_long"] = col("long", "n", 0)
        monthly["hours_long"] = col("long", "hours", 0.0)
        monthly["n_short"] = col("short", "n", 0)
        monthly = monthly.fillna(0).reset_index()
        monthly["ym"] = _ym_label(monthly["month"].to_numpy())
        monthly = monthly[["cust_class", "ym", "n_meters_served", "n_confirmed", "hours_confirmed",
                           "hours_presilence", "hours_reassoc", "n_comms", "hours_comms",
                           "n_long", "hours_long", "n_short"]]
        for c in monthly.columns:
            if c.startswith("n_"):
                monthly[c] = monthly[c].astype(int)

        if self.duration_parts:
            durations = (pd.concat(self.duration_parts, ignore_index=True)
                         .groupby(["cust_class", "classification", "start_hour", "duration_slots"], as_index=False)
                         ["count"].sum())
        else:
            durations = pd.DataFrame(columns=["cust_class", "classification", "start_hour", "duration_slots", "count"])

        if clusters is not None:
            events = pd.DataFrame({
                "outage_start_utc": pd.to_datetime(clusters["outage_start_ns"], unit="ns"),
                "restoration_utc": pd.to_datetime(clusters["restoration_ns"], unit="ns"),
                "n_meters": clusters["n_meters"].astype(int),
                "n_flagged": clusters["n_flagged"].astype(int),
                "n_attributed": clusters["n_attributed"].astype(int),
                "reboot_spread_s": clusters["reboot_spread_s"].round(0),
            }).sort_values("outage_start_utc").reset_index(drop=True)
        else:
            events = pd.DataFrame(columns=["outage_start_utc", "restoration_utc", "n_meters", "n_flagged", "n_attributed", "reboot_spread_s"])

        # Hourly site series
        per_hour = 3600 // SLOT_S
        series = {c: np.cumsum(self.slot_out[c])[:N_SLOTS].reshape(-1, per_hour).mean(axis=1)
                  for c in self.slot_out}
        hourly = pd.DataFrame({
            "hour_utc": pd.to_datetime(T0_NS + np.arange(N_SLOTS // per_hour) * 3600 * 10**9, unit="ns"),
            "meters_reporting": self.slot_report.reshape(-1, per_hour).mean(axis=1),
            "meters_out_confirmed": series["confirmed"],
            "meters_presilence": series["presilence"],
            "meters_reassoc": series["reassoc"],
            "meters_out_comms": series["comms"],
        })
        num = ["meters_reporting", "meters_out_confirmed", "meters_presilence", "meters_reassoc", "meters_out_comms"]
        hourly = hourly[hourly[num].sum(axis=1) > 0]
        hourly[num] = hourly[num].round(3)

        for df in (monthly, durations, hourly, events):
            df.insert(0, "country", country)
            df.insert(0, "project", project)
            df.insert(0, "site", site)
        return monthly, durations, hourly, events, diag

def _stream_batches(paths: list[str], batch_size: int):
    """Streaming pass in file order (assumes files are globally time-ordered)."""
    for p in paths:
        pf = pq.ParquetFile(p)
        missing = set(READ_COLUMNS) - set(pf.schema_arrow.names)
        if missing:
            sys.exit(f"{p}: missing columns {sorted(missing)}")
        for batch in pf.iter_batches(batch_size=batch_size, columns=READ_COLUMNS):
            yield batch.to_pandas()

def _sorted_batches(paths: list[str], batch_size: int):
    dict_cols = ["meter_customer_code", "meter_type", "meter_tariff_name"]
    tbl = pa.concat_tables(
        [pq.read_table(p, columns=READ_COLUMNS, read_dictionary=dict_cols) for p in paths]
    ).unify_dictionaries().combine_chunks()
    code_idx = tbl.column("meter_customer_code").chunk(0).indices.fill_null(-1).to_numpy()
    ts = pd.to_datetime(tbl.column("heartbeatStart").to_pandas(), errors="coerce")
    ts = ts.to_numpy(dtype="datetime64[ns]").view(np.int64)
    order = np.lexsort((ts, code_idx))
    del ts, code_idx
    tbl = tbl.take(pa.array(order))
    del order
    for batch in tbl.to_batches(max_chunksize=batch_size):
        yield batch.to_pandas()

def process_site(site: str, paths: list[str], project: str, country: str,
                 max_gap_days: float, batch_size: int):
    acc = SiteAccumulator(max_gap_s=max_gap_days * 86400)
    for bdf in _stream_batches(paths, batch_size):
        acc.process_batch(bdf)
    if acc.n_out_of_order:
        print(f"  [{site}] {acc.n_out_of_order:,} rows out of time order; "
              "re-reading site with a full (meter, time) sort …", file=sys.stderr)
        acc = SiteAccumulator(max_gap_s=max_gap_days * 86400)
        for bdf in _sorted_batches(paths, batch_size):
            acc.process_batch(bdf)
        assert acc.n_out_of_order == 0
    monthly, durations, hourly, events, diag = acc.finalize(site, project, country)

    counts = acc.n_events
    n_conf, n_comms = counts["confirmed"], counts["comms"]
    n_gap = n_conf + n_comms
    share = f"{100 * n_conf / n_gap:.1f}%" if n_gap else "n/a"
    print(f"  {site}: {acc.n_rows:,} rows, {len(acc.carry):,} meters, {acc.n_dup:,} duplicates | "
          f"gaps: confirmed {n_conf:,}  comms {n_comms:,}  long {int(counts.get('long', 0)):,}  "
          f"short-reboot {int(counts.get('short', 0)):,} | reboot share of bounded gaps {share}")
    if diag:
        print(f"    clusters: {len(events):,} outages; {100 * diag['share_in_clusters_ge5']:.0f}% of confirmed "
              f"interruptions in clusters of >= 5 meters (median cluster {diag['median_cluster_size']:.0f}); "
              f"{100 * diag['presilence_share']:.0f}% of former de-energized time reclassified as pre-silence; "
              f"{100 * diag['share_flagged']:.1f}% of members flagged; "
              f"{diag['n_attributed']:,} interruptions ({diag['attributed_hours']:,.0f} h) attributed to "
              f"silent meters spanning site-wide windows")
    return monthly, durations, hourly, events


# To save on reprocessing as edits are made
CACHE_SCHEMA = {
    "_monthly.csv":   ["hours_presilence", "hours_reassoc", "n_short"],
    "_durations.csv": ["duration_slots"],
    "_hourly.csv":    ["meters_presilence", "meters_reassoc"],
    "_events.csv":    ["outage_start_utc", "n_attributed"],
}

def _cache_current(*paths: str) -> bool:
    for p in paths:
        if not os.path.exists(p):
            return False
        suffix = next(k for k in CACHE_SCHEMA if p.endswith(k))
        with open(p) as f:
            header = f.readline().rstrip("\n").split(",")
        if any(c not in header for c in CACHE_SCHEMA[suffix]):
            return False
    return True

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sites", nargs="*", help="site file stems to process (default: all)")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out-dir", default="paper/graphics")
    ap.add_argument("--max-gap-days", type=float, default=30.0)
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    ap.add_argument("--overwrite", action="store_true", help="reprocess sites with cached results")
    a = ap.parse_args()

    files = find_site_files(a.data_dir)
    if not files:
        sys.exit(f"No raw sparkmeterreadings files found under {a.data_dir}/")
    sites = a.sites or sorted(files)
    cache_dir = os.path.join(a.out_dir, "saidi_saifi_cache")
    os.makedirs(cache_dir, exist_ok=True)

    print(f"Processing {len(sites)} site(s); max gap {a.max_gap_days:g} days …")
    for site in sites:
        if site not in files:
            print(f"  [skip] unknown site {site}", file=sys.stderr)
            continue
        cm = os.path.join(cache_dir, f"{site}_monthly.csv")
        cd = os.path.join(cache_dir, f"{site}_durations.csv")
        ch = os.path.join(cache_dir, f"{site}_hourly.csv")
        ce = os.path.join(cache_dir, f"{site}_events.csv")
        if not a.overwrite and _cache_current(cm, cd, ch, ce):
            print(f"  [cached] {site}")
            continue
        project, country = FILENAME_MAP.get(site, (site.replace("_", " "), "Unknown"))
        if site not in FILENAME_MAP:
            print(f"  [warn] {site} not in FILENAME_MAP; country set to Unknown", file=sys.stderr)
        m, d, h, e = process_site(site, files[site], project, country, a.max_gap_days, a.batch_size)
        m.to_csv(cm, index=False)
        d.to_csv(cd, index=False)
        h.to_csv(ch, index=False)
        e.to_csv(ce, index=False)

    cached = sorted(
        f[:-len("_monthly.csv")] for f in os.listdir(cache_dir) if f.endswith("_monthly.csv")
        and _cache_current(*(os.path.join(cache_dir, f[:-len("_monthly.csv")] + k) for k in CACHE_SCHEMA))
    )
    monthly = pd.concat([pd.read_csv(os.path.join(cache_dir, f"{s}_monthly.csv")) for s in cached],
                        ignore_index=True).sort_values(["site", "cust_class", "ym"])
    durations = pd.concat([pd.read_csv(os.path.join(cache_dir, f"{s}_durations.csv")) for s in cached],
                          ignore_index=True).sort_values(
        ["site", "cust_class", "classification", "start_hour", "duration_slots"])

    out = os.path.join(a.out_dir, "saidi_saifi_monthly.csv")
    monthly.to_csv(out, index=False)
    print(f"\nSaved {out}  ({len(monthly):,} site-class-months)")
    out = os.path.join(a.out_dir, "saidi_saifi_durations.csv")
    durations.to_csv(out, index=False)
    print(f"Saved {out}  ({len(durations):,} rows)")
    hourly = pd.concat([pd.read_csv(os.path.join(cache_dir, f"{s}_hourly.csv")) for s in cached],
                       ignore_index=True)
    out = os.path.join(a.out_dir, "saidi_saifi_site_hourly.csv")
    hourly.to_csv(out, index=False)
    print(f"Saved {out}  ({len(hourly):,} site-hours)")
    events = pd.concat([pd.read_csv(os.path.join(cache_dir, f"{s}_events.csv")) for s in cached],
                       ignore_index=True)
    out = os.path.join(a.out_dir, "saidi_saifi_events.csv")
    events.to_csv(out, index=False)
    print(f"Saved {out}  ({len(events):,} site-level outages)")

    tot = monthly[["n_confirmed", "hours_confirmed", "hours_presilence", "hours_reassoc",
                   "n_comms", "n_long", "n_short"]].sum()
    print(f"\nFleet totals: {int(tot.n_confirmed):,} confirmed interruptions "
          f"({tot.hours_confirmed:,.0f} de-energized customer-hours; {tot.hours_presilence:,.0f} pre-silence, "
          f"{tot.hours_reassoc:,.0f} re-association), {int(tot.n_comms):,} comms gaps, "
          f"{int(tot.n_long):,} long gaps, {int(tot.n_short):,} short reboots")

if __name__ == "__main__":
    main()
