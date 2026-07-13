#!/usr/bin/env python3
"""
Average Consumption Per User (ACPU) analysis for Renewvia mini-grid customers.

Reads data/acpu_monthly.csv (produced by prep_acpu.py) and saves four figures
to paper/graphics/:
  acpu_histograms.png       — ACPU distribution by customer type and country
  acpu_by_site.png          — ACPU box plots by site
  acpu_tenure_scatter.png   — Monthly consumption vs. months since first reading
  acpu_slope_histogram.png  — Per-customer consumption trend slopes + one-sample t-test

Usage:
  python figures/prep_acpu.py          # once, to build the CSV
  python figures/plot_acpu.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.nonparametric.smoothers_lowess import lowess

OUT_DIR = Path("paper/graphics")
OUT_DIR.mkdir(parents=True, exist_ok=True)

COUNTRIES = ["Kenya", "Nigeria"]

# ── 1. Load monthly aggregates ────────────────────────────────────────────────

CSV = Path("data/acpu_monthly.csv")
if not CSV.exists():
    raise FileNotFoundError(f"{CSV} not found — run figures/prep_acpu.py first.")

print(f"Loading {CSV} …")
monthly = pd.read_csv(CSV, dtype={"ym": str})
monthly["ym"] = pd.PeriodIndex(monthly["ym"], freq="M")
monthly["monthly_wh"] = monthly["monthly_kwh"] * 1000
monthly = monthly[monthly["monthly_wh"] > 0].copy()

print(f"  {len(monthly):,} user-months, {monthly['meter_customer_code'].nunique():,} customers")

# ── 2. Per-customer ACPU summary ──────────────────────────────────────────────

acpu = (
    monthly.groupby(
        ["meter_customer_code", "country", "cust_class", "projectName"],
        observed=True,
    )
    .agg(
        total_wh=("monthly_wh", "sum"),
        active_months=("monthly_wh", "count"),
        first_month=("ym", "min"),
        last_month=("ym", "max"),
        acpu=("monthly_wh", "mean"),
    )
    .reset_index()
)
acpu["date_range_months"] = (
    acpu["last_month"].array.asi8 - acpu["first_month"].array.asi8 + 1
)

MIN_SITE_N = 30
site_counts = acpu.groupby(["country", "projectName"])["meter_customer_code"].nunique()
valid = site_counts[site_counts >= MIN_SITE_N].reset_index()[["country", "projectName"]]
acpu = acpu.merge(valid, on=["country", "projectName"], how="inner")

print(f"  {len(acpu):,} unique customers (sites with n<{MIN_SITE_N} excluded)")
for country in COUNTRIES:
    sub = acpu[acpu["country"] == country]
    print(f"  {country}: {len(sub):,} customers, "
          f"median ACPU = {sub['acpu'].median():.1f} Wh/mo")

# ── 3. Figure 1: ACPU histograms by customer type and country ─────────────────

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
fig.suptitle(
    "Average Consumption Per User (ACPU) — Distribution by Customer Type",
    fontsize=13,
)

for ax, country in zip(axes, COUNTRIES):
    sub = acpu[acpu["country"] == country]

    lo = max(sub["acpu"].quantile(0.01), 1e-3)
    hi = sub["acpu"].quantile(0.99)
    bins = np.logspace(np.log10(lo), np.log10(hi), 50)

    for cls, color, zorder in [("Residential", "#2563eb", 2), ("Commercial", "#dc2626", 3)]:
        d = sub.loc[sub["cust_class"] == cls, "acpu"].dropna()
        if d.empty:
            continue
        ax.hist(d, bins=bins, alpha=0.45, color=color,
                label=f"{cls} (n={len(d):,})", density=True, zorder=zorder)
        ax.axvline(d.mean(), color=color, linewidth=1.5, linestyle="--",
                   label=f"{cls} mean: {d.mean():.2f}", zorder=zorder + 1)

    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}" if x >= 1 else f"{x:g}"))
    ax.set_xlabel("ACPU (Wh/month, log scale)", fontsize=10)
    ax.set_ylabel("Density", fontsize=10)
    ax.set_title(country, fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(axis="both", linewidth=0.4, alpha=0.5)

plt.tight_layout()
out = OUT_DIR / "acpu_histograms.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved {out.name}")
plt.close(fig)

# ── 4. Figure 2: ACPU by site (horizontal box plots) ─────────────────────────

n_sites = {c: acpu[acpu["country"] == c]["projectName"].nunique() for c in COUNTRIES}
height_ratios = [n_sites[c] for c in COUNTRIES]
total_height = max(sum(height_ratios) * 0.45, 8)

fig, axes = plt.subplots(
    2, 1, figsize=(10, total_height),
    gridspec_kw={"height_ratios": height_ratios},
)
fig.suptitle("ACPU Distribution by Mini-Grid Site", fontsize=13)

for ax, country in zip(axes, COUNTRIES):
    sub = acpu[acpu["country"] == country]

    site_order = (
        sub.groupby("projectName")["acpu"]
        .median()
        .sort_values(ascending=True)
        .index.tolist()
    )

    data = [sub.loc[sub["projectName"] == s, "acpu"].dropna().values for s in site_order]
    n_counts = [len(d) for d in data]

    ax.boxplot(
        data,
        vert=False,
        patch_artist=True,
        notch=False,
        showfliers=True,
        flierprops=dict(marker=".", markersize=2, alpha=0.25, color="#2563eb"),
        medianprops=dict(color="#1e3a8a", linewidth=1.8),
        boxprops=dict(facecolor="#bfdbfe", linewidth=0.8),
        whiskerprops=dict(linewidth=0.8),
        capprops=dict(linewidth=0.8),
    )

    labels = [f"{s}  (n={n})" for s, n in zip(site_order, n_counts)]
    ax.set_yticks(range(1, len(site_order) + 1))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("ACPU (Wh/month)", fontsize=10)
    ax.set_title(country, fontsize=11)
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}" if x >= 1 else f"{x:g}"))
    ax.grid(axis="x", linewidth=0.4, alpha=0.5)

plt.tight_layout()
out = OUT_DIR / "acpu_by_site.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved {out.name}")
plt.close(fig)

# ── 5. Figure 3: Consumption vs. months since first reading ───────────────────

first_month = (
    monthly.groupby("meter_customer_code")["ym"]
    .min()
    .rename("first_ym")
)
monthly2 = monthly.join(first_month, on="meter_customer_code")
monthly2 = monthly2.dropna(subset=["first_ym"])
monthly2["months_since_first"] = (
    monthly2["ym"].array.asi8 - monthly2["first_ym"].array.asi8
)

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle(
    "Monthly Consumption vs. Months Since First Reading\n(each dot = one user-month)",
    fontsize=12,
)

for ax, country in zip(axes, COUNTRIES):
    sub = monthly2[monthly2["country"] == country].copy()

    y_cap = sub["monthly_wh"].quantile(0.99)
    sub_plot = sub[sub["monthly_wh"] <= y_cap]

    ax.scatter(
        sub_plot["months_since_first"],
        sub_plot["monthly_wh"],
        alpha=0.04,
        s=3,
        color="#2563eb",
        rasterized=True,
    )

    by_tenure = (
        sub.groupby("months_since_first")["monthly_wh"]
        .agg(mean="mean", count="count")
        .query("count >= 10")
        .reset_index()
    )
    if len(by_tenure) > 10:
        sm = lowess(
            by_tenure["mean"].values,
            by_tenure["months_since_first"].values,
            frac=0.2,
            return_sorted=True,
        )
        ax.plot(sm[:, 0], sm[:, 1], color="#dc2626", linewidth=2, label="LOESS mean", zorder=5)

    x_max = by_tenure["months_since_first"].max() if len(by_tenure) else sub["months_since_first"].max()
    ax.set_xlim(left=-0.5, right=x_max + 0.5)
    ax.set_ylim(bottom=0, top=y_cap * 1.05)
    ax.set_xlabel("Months since first reading", fontsize=10)
    ax.set_ylabel("Monthly consumption (Wh)", fontsize=10)
    ax.set_title(country, fontsize=11)
    ax.grid(axis="both", linewidth=0.4, alpha=0.4)

    n_cust = sub["meter_customer_code"].nunique()
    n_obs  = len(sub)
    ax.text(0.02, 0.97,
            f"{n_cust:,} customers · {n_obs:,} user-months\n"
            f"(y capped at 99th pct: {y_cap:,.0f} Wh)",
            transform=ax.transAxes, va="top", fontsize=8, color="gray")
    ax.legend(fontsize=9, loc="upper right")

plt.tight_layout()
out = OUT_DIR / "acpu_tenure_scatter.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved {out.name}")
plt.close(fig)

# ── 6. Per-customer slopes → slope histogram + one-sample t-test ─────────────

MIN_ACTIVE_MONTHS = 3

slopes_df = (
    monthly2[["meter_customer_code", "country", "months_since_first", "monthly_wh"]]
    .groupby(["meter_customer_code", "country"], observed=True)
    .apply(
        lambda g: (
            stats.linregress(g["months_since_first"], g["monthly_wh"]).slope
            if len(g) >= MIN_ACTIVE_MONTHS else np.nan
        ),
        include_groups=False,
    )
    .reset_index()
    .rename(columns={0: "slope"})
)

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
fig.suptitle(
    f"Per-Customer Consumption Trend — One-Sample t-test of Slope vs. Zero\n"
    f"(customers with ≥ {MIN_ACTIVE_MONTHS} active months; "
    f"histogram clipped to 1st–99th pct for display)",
    fontsize=11,
)

for ax, country in zip(axes, COUNTRIES):
    slopes = slopes_df.loc[slopes_df["country"] == country, "slope"].dropna()

    t_stat, p_val = stats.ttest_1samp(slopes, 0)

    lo, hi = slopes.quantile(0.01), slopes.quantile(0.99)
    ax.hist(slopes.clip(lo, hi), bins=60, color="#2563eb", alpha=0.7, edgecolor="none")
    ax.axvline(0, color="black", linewidth=1.2, linestyle="--", label="zero (H₀)")
    ax.axvline(slopes.mean(), color="#dc2626", linewidth=1.5,
               label=f"mean slope: {slopes.mean():.2f}")

    p_str = f"{p_val:.2e}" if p_val < 0.001 else f"{p_val:.4f}"
    ax.text(
        0.97, 0.97,
        f"n = {len(slopes):,}\n"
        f"mean = {slopes.mean():.2f} Wh/mo²\n"
        f"t = {t_stat:.2f}\n"
        f"p = {p_str}",
        transform=ax.transAxes, va="top", ha="right", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="#9ca3af", alpha=0.9),
    )

    ax.set_xlabel("Slope (Wh/month per month of tenure)", fontsize=10)
    ax.set_ylabel("Number of customers", fontsize=10)
    ax.set_title(country, fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(axis="y", linewidth=0.4, alpha=0.5)

plt.tight_layout()
out = OUT_DIR / "acpu_slope_histogram.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved {out.name}")
plt.close(fig)

# ── 7. Summary statistics ─────────────────────────────────────────────────────

print("\n=== ACPU Summary ===")
for country in COUNTRIES:
    sub = acpu[acpu["country"] == country]
    print(f"\n{country} (Wh/month):")
    print(sub.groupby("cust_class")["acpu"].describe(
        percentiles=[0.25, 0.5, 0.75, 0.95]
    ).round(1).to_string())
