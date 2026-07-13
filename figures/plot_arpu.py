#!/usr/bin/env python3
"""
Average Revenue Per User (ARPU) analysis for Renewvia mini-grid customers.

Saves four figures to paper/graphics/:
  arpu_histograms.png       — ARPU distribution by customer type and country
  arpu_by_site.png          — ARPU box plots by site
  arpu_tenure_scatter.png   — Monthly revenue vs. months since first payment
  arpu_slope_histogram.png  — Per-customer revenue trend slopes + one-sample t-test

With --convert-usd, amounts are converted to USD using World Bank annual average
official exchange rates (indicator PA.NUS.FCRF, LCU per US$). Output filenames
gain a '_usd' suffix so local-currency figures are not overwritten.

Usage:
  python figures/plot_arpu.py
  python figures/plot_arpu.py --convert-usd
"""

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import requests
from scipy import stats
from statsmodels.nonparametric.smoothers_lowess import lowess

# ── CLI ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(
    description="Plot ARPU figures from Renewvia paymentconfirmations data."
)
parser.add_argument(
    "--convert-usd",
    action="store_true",
    help=(
        "Convert amounts to USD using World Bank annual average exchange rates "
        "(PA.NUS.FCRF, LCU per US$, period average). "
        "Appends '_usd' to all output filenames."
    ),
)
args = parser.parse_args()

OUT_DIR = Path("paper/graphics")
OUT_DIR.mkdir(parents=True, exist_ok=True)

COUNTRIES  = ["Kenya", "Nigeria"]
CURRENCIES = {"Kenya": "KES", "Nigeria": "NGN"}
WB_ISO2    = {"Kenya": "KE",  "Nigeria": "NG"}

CURR_LABEL = {c: ("USD" if args.convert_usd else CURRENCIES[c]) for c in COUNTRIES}
OUT_SUFFIX = "_usd" if args.convert_usd else ""

# ── Exchange rate helpers ─────────────────────────────────────────────────────

def fetch_wb_rates(iso2: str) -> dict[int, float]:
    """
    Fetch annual average LCU-per-USD rates from the World Bank
    (indicator PA.NUS.FCRF). Returns {year: rate}.
    """
    url = (
        f"https://api.worldbank.org/v2/country/{iso2}/indicator/PA.NUS.FCRF"
        "?format=json&per_page=30"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"Error fetching World Bank rates for {iso2}: {exc}", file=sys.stderr)
        sys.exit(1)

    records = resp.json()[1]
    rates = {int(r["date"]): r["value"] for r in records if r["value"] is not None}
    if not rates:
        print(f"No exchange rate data returned for {iso2}.", file=sys.stderr)
        sys.exit(1)
    return rates


def map_rates(years: pd.Series, rates: dict[int, float]) -> pd.Series:
    """
    Map a Series of integer years to LCU-per-USD rates.
    Years with no data are filled using the nearest available year.
    """
    mapped = years.map(rates)
    missing_years = years[mapped.isna()].unique()
    if len(missing_years):
        sorted_yrs = sorted(rates)
        for y in missing_years:
            nearest = min(sorted_yrs, key=lambda yr: abs(yr - y))
            mapped[years == y] = rates[nearest]
    return mapped


# ── 1. Load and filter payments ───────────────────────────────────────────────

print("Loading paymentconfirmations …")
pc = pd.read_parquet("data/paymentconfirmations/data.parquet")

pc["country"] = pc["country"].str.strip().str.title()

mask = (
    (pc["isTest"]          != 1)
    & (pc["isReversed"]    != 1)
    & (pc["isSignup"]      != 1)   # one-time connection fee, not recurring revenue
    & (pc["isBalanceTransfer"] != 1)
    & (pc["amount"]        >  0)
    & (pc["transactionDatetime"].notna())
    & (pc["transactionDatetime"].dt.year >= 2015)
    & (pc["country"].isin(COUNTRIES))
)
pay = pc.loc[mask, [
    "customerAccountNumber", "amount", "currency",
    "country", "projectName", "transactionDatetime",
]].copy()

print(f"  {len(pay):,} payments after filtering (of {len(pc):,} total)")

# ── 2. Optionally convert to USD ──────────────────────────────────────────────

if args.convert_usd:
    print("Fetching exchange rates from World Bank (PA.NUS.FCRF) …")
    wb_rates = {c: fetch_wb_rates(WB_ISO2[c]) for c in COUNTRIES}
    for c in COUNTRIES:
        yrs = sorted(wb_rates[c])
        print(f"  {c}: years {yrs[0]}–{yrs[-1]}, "
              f"e.g. {yrs[-1]} = {wb_rates[c][yrs[-1]]:.2f} {CURRENCIES[c]}/USD")

    pay["tx_year"] = pay["transactionDatetime"].dt.year
    frames = []
    for country in COUNTRIES:
        sub = pay[pay["country"] == country].copy()
        rate = map_rates(sub["tx_year"], wb_rates[country])
        sub["amount"] = sub["amount"] / rate
        frames.append(sub)
    pay = pd.concat(frames, ignore_index=True).drop(columns=["tx_year"])

    n_bad = pay["amount"].isna().sum()
    if n_bad:
        print(f"  Warning: dropping {n_bad} rows with unmappable exchange rates.")
        pay = pay.dropna(subset=["amount"])

# ── 3. Join customer types ────────────────────────────────────────────────────

cust = pd.read_parquet(
    "data/customers/data.parquet",
    columns=["customerAccountNumber", "customerType"],
)
pay = pay.merge(cust, on="customerAccountNumber", how="left")

pay["cust_class"] = np.where(
    pay["customerType"] == "Residential", "Residential", "Commercial"
)
pay.loc[pay["customerType"].isna(), "cust_class"] = "Unknown"

# ── 4. Per-customer monthly revenue ──────────────────────────────────────────

pay["ym"] = pay["transactionDatetime"].dt.to_period("M")

monthly = (
    pay.groupby(
        ["customerAccountNumber", "country", "cust_class", "projectName", "ym"],
        observed=True,
    )["amount"]
    .sum()
    .reset_index()
    .rename(columns={"amount": "monthly_revenue"})
)

# ── 5. Per-customer ARPU summary ──────────────────────────────────────────────

arpu = (
    monthly.groupby(
        ["customerAccountNumber", "country", "cust_class", "projectName"],
        observed=True,
    )
    .agg(
        total_revenue=("monthly_revenue", "sum"),
        active_months=("monthly_revenue", "count"),
        first_month=("ym", "min"),
        last_month=("ym", "max"),
        arpu=("monthly_revenue", "mean"),
    )
    .reset_index()
)
arpu["date_range_months"] = (
    arpu["last_month"].apply(lambda p: p.ordinal)
    - arpu["first_month"].apply(lambda p: p.ordinal)
    + 1
)

MIN_SITE_N = 30
site_counts = arpu.groupby(["country", "projectName"])["customerAccountNumber"].nunique()
valid = site_counts[site_counts >= MIN_SITE_N].reset_index()[["country", "projectName"]]
arpu = arpu.merge(valid, on=["country", "projectName"], how="inner")

print(f"  {len(arpu):,} unique customers (sites with n<{MIN_SITE_N} excluded)")
for country in COUNTRIES:
    sub = arpu[arpu["country"] == country]
    print(f"  {country}: {len(sub):,} customers, "
          f"median ARPU = {sub['arpu'].median():.2f} {CURR_LABEL[country]}/mo")

# ── 6. Figure 1: ARPU histograms by customer type and country ─────────────────

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
fig.suptitle("Average Revenue Per User (ARPU) — Distribution by Customer Type", fontsize=13)

for ax, country in zip(axes, COUNTRIES):
    sub = arpu[(arpu["country"] == country) & (arpu["cust_class"] != "Unknown")]
    curr = CURR_LABEL[country]

    lo = max(sub["arpu"].quantile(0.01), 1e-3)
    hi = sub["arpu"].quantile(0.99)
    bins = np.logspace(np.log10(lo), np.log10(hi), 50)

    for cls, color, zorder in [("Residential", "#2563eb", 2), ("Commercial", "#dc2626", 3)]:
        d = sub.loc[sub["cust_class"] == cls, "arpu"].dropna()
        if d.empty:
            continue
        ax.hist(d, bins=bins, alpha=0.45, color=color,
                label=f"{cls} (n={len(d):,})", density=True, zorder=zorder)
        ax.axvline(d.mean(), color=color, linewidth=1.5, linestyle="--",
                   label=f"{cls} mean: {d.mean():.2f}", zorder=zorder + 1)

    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}" if x >= 1 else f"{x:g}"))
    ax.set_xlabel(f"ARPU ({curr}/month, log scale)", fontsize=10)
    ax.set_ylabel("Density", fontsize=10)
    ax.set_title(country, fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(axis="both", linewidth=0.4, alpha=0.5)

if args.convert_usd:
    fig.text(0.5, -0.02,
             "Exchange rates: World Bank PA.NUS.FCRF (official rate, LCU per US$, annual average)",
             ha="center", fontsize=7, color="gray")

plt.tight_layout()
out = OUT_DIR / f"arpu_histograms{OUT_SUFFIX}.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved {out.name}")
plt.close(fig)

# ── 7. Figure 2: ARPU by site (horizontal box plots) ─────────────────────────

n_sites = {c: arpu[arpu["country"] == c]["projectName"].nunique() for c in COUNTRIES}
height_ratios = [n_sites[c] for c in COUNTRIES]
total_height = max(sum(height_ratios) * 0.45, 8)

fig, axes = plt.subplots(
    2, 1, figsize=(10, total_height),
    gridspec_kw={"height_ratios": height_ratios},
)
fig.suptitle("ARPU Distribution by Mini-Grid Site", fontsize=13)

for ax, country in zip(axes, COUNTRIES):
    sub = arpu[arpu["country"] == country]
    curr = CURR_LABEL[country]

    site_order = (
        sub.groupby("projectName")["arpu"]
        .median()
        .sort_values(ascending=True)
        .index.tolist()
    )

    data = [sub.loc[sub["projectName"] == s, "arpu"].dropna().values for s in site_order]
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
    ax.set_xlabel(f"ARPU ({curr}/month)", fontsize=10)
    ax.set_title(country, fontsize=11)
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}" if x >= 1 else f"{x:g}"))
    ax.grid(axis="x", linewidth=0.4, alpha=0.5)

if args.convert_usd:
    fig.text(0.5, -0.01,
             "Exchange rates: World Bank PA.NUS.FCRF (official rate, LCU per US$, annual average)",
             ha="center", fontsize=7, color="gray")

plt.tight_layout()
out = OUT_DIR / f"arpu_by_site{OUT_SUFFIX}.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved {out.name}")
plt.close(fig)

# ── 8. Figure 3: Revenue vs. months since first payment ───────────────────────

first_month = (
    monthly.groupby("customerAccountNumber")["ym"]
    .min()
    .rename("first_ym")
)
monthly2 = monthly.join(first_month, on="customerAccountNumber")
monthly2["months_since_first"] = (
    monthly2["ym"].apply(lambda p: p.ordinal)
    - monthly2["first_ym"].apply(lambda p: p.ordinal)
)

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle(
    "Monthly Revenue vs. Months Since First Payment\n(each dot = one user-month)",
    fontsize=12,
)

for ax, country in zip(axes, COUNTRIES):
    sub = monthly2[monthly2["country"] == country].copy()
    curr = CURR_LABEL[country]

    y_cap = sub["monthly_revenue"].quantile(0.99)
    sub_plot = sub[sub["monthly_revenue"] <= y_cap]

    ax.scatter(
        sub_plot["months_since_first"],
        sub_plot["monthly_revenue"],
        alpha=0.04,
        s=3,
        color="#2563eb",
        rasterized=True,
    )

    by_tenure = (
        sub.groupby("months_since_first")["monthly_revenue"]
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

    ax.set_xlim(left=-0.5)
    ax.set_ylim(bottom=0, top=y_cap * 1.05)
    ax.set_xlabel("Months since first payment", fontsize=10)
    ax.set_ylabel(f"Monthly revenue ({curr})", fontsize=10)
    ax.set_title(country, fontsize=11)
    ax.grid(axis="both", linewidth=0.4, alpha=0.4)

    n_cust = sub["customerAccountNumber"].nunique()
    n_obs  = len(sub)
    ax.text(0.02, 0.97,
            f"{n_cust:,} customers · {n_obs:,} user-months\n"
            f"(y capped at 99th pct: {y_cap:,.2f} {curr})",
            transform=ax.transAxes, va="top", fontsize=8, color="gray")
    ax.legend(fontsize=9, loc="upper right")

if args.convert_usd:
    fig.text(0.5, -0.02,
             "Exchange rates: World Bank PA.NUS.FCRF (official rate, LCU per US$, annual average)",
             ha="center", fontsize=7, color="gray")

plt.tight_layout()
out = OUT_DIR / f"arpu_tenure_scatter{OUT_SUFFIX}.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved {out.name}")
plt.close(fig)

# ── 9. Per-customer slopes → slope histogram + one-sample t-test ─────────────

MIN_ACTIVE_MONTHS = 3  # minimum active months to fit a meaningful slope

slope_input = monthly2[
    ["customerAccountNumber", "country", "months_since_first", "monthly_revenue"]
]
slopes_df = (
    slope_input
    .groupby(["customerAccountNumber", "country"], observed=True)
    .apply(
        lambda g: (
            stats.linregress(g["months_since_first"], g["monthly_revenue"]).slope
            if len(g) >= MIN_ACTIVE_MONTHS else np.nan
        ),
        include_groups=False,
    )
    .reset_index()
    .rename(columns={0: "slope"})
)

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
fig.suptitle(
    f"Per-Customer Revenue Trend — One-Sample t-test of Slope vs. Zero\n"
    f"(customers with ≥ {MIN_ACTIVE_MONTHS} active payment months; "
    f"histogram clipped to 1st–99th pct for display)",
    fontsize=11,
)

for ax, country in zip(axes, COUNTRIES):
    curr = CURR_LABEL[country]
    slopes = slopes_df.loc[slopes_df["country"] == country, "slope"].dropna()

    t_stat, p_val = stats.ttest_1samp(slopes, 0)

    # Clip for display only; t-test uses full distribution
    lo, hi = slopes.quantile(0.01), slopes.quantile(0.99)
    ax.hist(slopes.clip(lo, hi), bins=60, color="#2563eb", alpha=0.7, edgecolor="none")
    ax.axvline(0, color="black", linewidth=1.2, linestyle="--", label="zero (H₀)")
    ax.axvline(slopes.mean(), color="#dc2626", linewidth=1.5,
               label=f"mean slope: {slopes.mean():.3f}")

    p_str = f"{p_val:.2e}" if p_val < 0.001 else f"{p_val:.4f}"
    ax.text(
        0.97, 0.97,
        f"n = {len(slopes):,}\n"
        f"mean = {slopes.mean():.3f} {curr}/mo²\n"
        f"t = {t_stat:.2f}\n"
        f"p = {p_str}",
        transform=ax.transAxes, va="top", ha="right", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="#9ca3af", alpha=0.9),
    )

    ax.set_xlabel(f"Slope ({curr}/month per month of tenure)", fontsize=10)
    ax.set_ylabel("Number of customers", fontsize=10)
    ax.set_title(country, fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(axis="y", linewidth=0.4, alpha=0.5)

if args.convert_usd:
    fig.text(0.5, -0.03,
             "Exchange rates: World Bank PA.NUS.FCRF (official rate, LCU per US$, annual average)",
             ha="center", fontsize=7, color="gray")

plt.tight_layout()
out = OUT_DIR / f"arpu_slope_histogram{OUT_SUFFIX}.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved {out.name}")
plt.close(fig)

# ── 10. Summary statistics ────────────────────────────────────────────────────

print("\n=== ARPU Summary ===")
for country in COUNTRIES:
    sub = arpu[arpu["country"] == country]
    curr = CURR_LABEL[country]
    print(f"\n{country} ({curr}/month):")
    print(sub.groupby("cust_class")["arpu"].describe(
        percentiles=[0.25, 0.5, 0.75, 0.95]
    ).round(2 if args.convert_usd else 1).to_string())
