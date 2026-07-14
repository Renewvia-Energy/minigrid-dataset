"""
Export Renewvia mini-grid database to anonymized Parquet files.

For each included table:
  - Drops PII and internal-use columns
  - Pseudonymizes customer identifiers with SHA-256(value + ANON_SALT)
  - Applies data cleaning (drops epoch-zero timestamps, zero-date payments,
    normalizes paymentProcessor casing)
  - Writes Parquet to output/<table>/ (sparkmeterreadings split by site+year)

Run with:
    conda run -n base python3 scripts/export.py [--output-dir output] [--dry-run]
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import sqlalchemy
from dotenv import load_dotenv

load_dotenv()

DB_URL = (
    f"mysql+pymysql://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
    f"@{os.environ['DB_HOST']}:{os.environ.get('DB_PORT', 3306)}/{os.environ['DB_DATABASE']}"
)
SALT = os.environ["ANON_SALT"].encode()

# ── arrow helpers ─────────────────────────────────────────────────────────────

def normalize_arrow_table(tbl: pa.Table) -> pa.Table:
    """Normalize column types for consistent Parquet schema across batches.

    Two MySQL quirks cause PyArrow schema mismatches between batches:
    - DECIMAL columns arrive with varying precision (decimal128(6,5) vs (7,5))
      → cast to float64
    - Columns that are entirely NULL in the first batch get type `null`
      → cast to string (all such columns in this table are string fields)
    """
    new_schema = pa.schema([
        f.with_type(pa.float64()) if pa.types.is_decimal(f.type)
        else f.with_type(pa.string()) if f.type == pa.null()
        else f
        for f in tbl.schema
    ])
    return tbl.cast(new_schema)


# ── pseudonymization ──────────────────────────────────────────────────────────

def pseudonymize(value: str) -> str:
    """SHA-256(value + SALT), hex-encoded. Returns empty string for null/empty."""
    if not value:
        return value
    return hashlib.sha256(value.encode() + SALT).hexdigest()


def pseudonymize_series(s: pd.Series) -> pd.Series:
    return s.apply(lambda v: pseudonymize(str(v)) if pd.notna(v) and str(v).strip() else v)


# ── column specs ──────────────────────────────────────────────────────────────
# Each entry: (columns_to_drop, columns_to_pseudonymize, extra_clean_fn)

def clean_payments(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize paymentProcessor casing; drop zero-date rows."""
    df = df[df["transactionDatetime"].notna()].copy()
    df = df[pd.to_datetime(df["transactionDatetime"], errors="coerce").dt.year >= 2015].copy()
    df["paymentProcessor"] = df["paymentProcessor"].str.lower().str.strip()
    return df


# columns to drop per table
DROP_COLS = {
    "customers": [
        "name1", "name2", "name3", "name", "phoneNumber",
        "customerStatus", "formFiller", "tags", "latestReading", "status",
    ],
    "meteringplatformtariffs": [],
    "minigridprojects": [
        "pvwattsDataSource", "pvwattsProductionAnnual", "pvwattsMonthlyAveragekWhProduced",
        "investors", "donors",
        "remoteMonitoringPlatform", "remoteMonitoringSiteId",
        "remoteMonitoringUrl", "remoteMonitoringAPIToken",
    ],
    "paymentconfirmations": [
        "businessShortCode", "transactionID", "invoiceNumber", "thirdPartyTransactionID",
        "phoneNumber", "firstName", "middleName", "lastName",
    ],
    "paymentvalidations": [
        "businessShortCode", "transactionID", "invoiceNumber", "thirdPartyTransactionID",
        "phoneNumber", "firstName", "middleName", "lastName",
    ],
    "sparkmetercustomers": [
        "meters_address", "meters_city", "meters_coords", "meters_country",
        "meters_street1", "meters_street2", "meters_tags",
        "name", "phoneNumber",
    ],
    "sparkmeterreadings": [
        "UncertainMetadata", "kilowattHoursPeriod", "organization",
        "meter_address_street1", "meter_address_street2", "meter_address_city",
        "meter_address_postalcode", "meter_address_state",
        "meter_customer_name", "meter_customer_phoneNumber",
    ],
    "sparkmetertransactions": [
        "UncertainMetadata", "referenceId", "externalId", "memo",
        "to_address_street1", "to_address_street2", "to_address_city",
        "to_address_state", "to_address_postalcode",
        "to_customer_name", "to_customer_phoneNumber", "to_name",
        "from_address_street1", "from_address_street2", "from_address_city",
        "from_address_state", "from_address_postalcode",
        "from_customer_name", "from_customer_phoneNumber", "from_name",
    ],
    "tariffs": [],
    "vrmgeneration": [],
}

# columns to pseudonymize per table
PSEUDO_COLS = {
    "customers": ["customerAccountNumber", "customerId"],
    "meteringplatformtariffs": [],
    "minigridprojects": [],
    "paymentconfirmations": ["customerAccountNumber"],
    "paymentvalidations": ["customerAccountNumber"],
    "sparkmetercustomers": ["id"],
    "sparkmeterreadings": [
        "meter_customer_id", "meter_customer_code", "meter_customer_code_backup",
    ],
    "sparkmetertransactions": [
        "to_customer_id", "to_customer_code", "to_customer_code_backup",
        "from_customer_id", "from_customer_code",
    ],
    "tariffs": [],
    "vrmgeneration": [],
}

# optional per-table cleaning functions (applied after drop/pseudo)
CLEAN_FNS = {
    "paymentconfirmations": clean_payments,
    "paymentvalidations": clean_payments,
}


# ── simple table export ───────────────────────────────────────────────────────

def export_simple(engine, table: str, out_dir: Path, dry_run: bool) -> int:
    """Export a non-sparkmeterreadings table to a single Parquet file."""
    dest = out_dir / table
    path = dest / "data.parquet"
    if not dry_run and path.exists():
        rows = pq.read_metadata(path).num_rows
        print(f"  {table}: already done ({rows:,} rows) — skipping")
        return rows

    print(f"  reading {table}...", end=" ", flush=True)
    df = pd.read_sql_table(table, engine)
    print(f"{len(df):,} rows", end=" ", flush=True)

    df = apply_transforms(df, table)

    if dry_run:
        print(f"(dry run — skipping write)")
        return len(df)

    dest.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow")
    mb = path.stat().st_size / 1024 / 1024
    print(f"→ {path.relative_to(out_dir.parent)} ({mb:.1f} MB)")
    return len(df)


# ── sparkmeterreadings: chunked by site+year ──────────────────────────────────

READINGS_CHUNK = 200_000   # rows per SQL fetch

def export_sparkmeterreadings(engine, out_dir: Path, dry_run: bool) -> int:
    """Export sparkmeterreadings in site+year partitions.

    There is no composite index on (site, heartbeatStart), so per-site queries
    are catastrophically slow regardless of which single-column index is forced.
    Instead, scan one year at a time using the heartbeatStart index (pure range
    scan, no site filter) and route each row to the correct per-site Parquet file
    using incremental PyArrow writes.  Memory usage is bounded to READINGS_CHUNK
    rows at a time.
    """
    tbl = "sparkmeterreadings"

    mbs = pd.read_sql(
        "SELECT meteringSiteId, meteringBaseStation, olderMeteringSiteIds FROM meteringbasestations", engine
    )
    site_map = dict(zip(mbs["meteringSiteId"], mbs["meteringBaseStation"]))
    for _, row in mbs.iterrows():
        if pd.notna(row["olderMeteringSiteIds"]) and row["olderMeteringSiteIds"].strip():
            for old_id in row["olderMeteringSiteIds"].split(","):
                old_id = old_id.strip()
                if old_id:
                    site_map[old_id] = row["meteringBaseStation"]

    YEAR_RANGE = range(2018, 2026)
    sentinel_dir = out_dir / tbl
    sentinel_dir.mkdir(parents=True, exist_ok=True)
    total = 0

    for year in YEAR_RANGE:
        y_start  = f"{year}-01-01"
        y_end    = f"{year + 1}-01-01"
        sentinel = sentinel_dir / f".done_{year}"

        if not dry_run and sentinel.exists():
            for site_uuid, site_name in site_map.items():
                safe = site_name.replace("/", "-").replace(" ", "_")
                path = out_dir / tbl / safe / f"{year}.parquet"
                if path.exists():
                    total += pq.read_metadata(path).num_rows
            print(f"  {year}: skipping (sentinel)")
            continue

        # Determine which sites already have a file for this year (partial resume)
        done_sites: set = set()
        for site_uuid, site_name in site_map.items():
            safe = site_name.replace("/", "-").replace(" ", "_")
            path = out_dir / tbl / safe / f"{year}.parquet"
            if not dry_run and path.exists():
                total += pq.read_metadata(path).num_rows
                done_sites.add(site_uuid)

        print(f"  {year}...", end=" ", flush=True)

        if dry_run:
            print("(dry run)")
            continue

        query = sqlalchemy.text("""
            SELECT * FROM sparkmeterreadings FORCE INDEX (sitesAndTimestampsIndex)
            WHERE heartbeatStart >= :y_start AND heartbeatStart < :y_end
        """)

        writers: dict = {}  # site_uuid -> [ParquetWriter, schema, path, row_count]

        try:
            with engine.connect().execution_options(stream_results=True) as conn:
                result = conn.execute(query, {"y_start": y_start, "y_end": y_end})
                cols = list(result.keys())

                while True:
                    batch = result.fetchmany(READINGS_CHUNK)
                    if not batch:
                        break

                    df = pd.DataFrame(batch, columns=cols)
                    df = df[~df["site"].isin(done_sites)]
                    if df.empty:
                        print(".", end="", flush=True)
                        continue

                    df = apply_transforms(df, tbl)
                    df.insert(
                        df.columns.get_loc("site") + 1,
                        "site_name",
                        df["site"].map(site_map).fillna("unknown"),
                    )

                    for site_uuid, site_df in df.groupby("site"):
                        arrow_tbl = normalize_arrow_table(
                            pa.Table.from_pandas(site_df, preserve_index=False)
                        )
                        if site_uuid not in writers:
                            sname = site_map.get(site_uuid, str(site_uuid))
                            safe  = sname.replace("/", "-").replace(" ", "_")
                            dest  = out_dir / tbl / safe
                            dest.mkdir(parents=True, exist_ok=True)
                            path  = dest / f"{year}.parquet"
                            writers[site_uuid] = [pq.ParquetWriter(path, arrow_tbl.schema), arrow_tbl.schema, path, 0]
                        else:
                            # Cast to the schema established by the first batch for
                            # this site — handles int64/double drift when NULLs appear
                            arrow_tbl = arrow_tbl.cast(writers[site_uuid][1], safe=False)

                        writers[site_uuid][0].write_table(arrow_tbl)
                        writers[site_uuid][3] += len(site_df)

                    print(".", end="", flush=True)

        finally:
            for w, _, _, _ in writers.values():
                w.close()

        # Year query completed without error — mark done regardless of whether
        # new files were written (all-done re-runs also land here)
        sentinel.touch()

        if not writers:
            print(" no new data")
        else:
            print()
            for site_uuid, (_, _, path, n_rows) in writers.items():
                sname = site_map.get(site_uuid, str(site_uuid))
                mb = path.stat().st_size / 1024 / 1024
                total += n_rows
                print(f"    {sname}/{year}: {n_rows:,} rows, {mb:.1f} MB")

    return total


# ── vrmgeneration: exclude commercial sites ───────────────────────────────────

EXCLUDE_VRM_SITES = {"UBA Acme, Ogba, Lagos, Nigeria", "Shell Oza 1"}

def export_vrmgeneration(engine, out_dir: Path, dry_run: bool) -> int:
    dest = out_dir / "vrmgeneration"
    path = dest / "data.parquet"
    if not dry_run and path.exists():
        rows = pq.read_metadata(path).num_rows
        print(f"  vrmgeneration: already done ({rows:,} rows) — skipping")
        return rows

    print(f"  reading vrmgeneration...", end=" ", flush=True)
    df = pd.read_sql_table("vrmgeneration", engine)
    df = df[~df["Project_Name"].isin(EXCLUDE_VRM_SITES)].copy()
    print(f"{len(df):,} rows (after excluding commercial sites)", end=" ", flush=True)

    df = apply_transforms(df, "vrmgeneration")

    if dry_run:
        print("(dry run)")
        return len(df)

    dest.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow")
    mb = path.stat().st_size / 1024 / 1024
    print(f"→ {path.relative_to(out_dir.parent)} ({mb:.1f} MB)")
    return len(df)


# ── meteringbasestations: allowlist columns to exclude credentials ────────────

METERINGBASESTATIONS_SAFE_COLS = [
    "meteringSiteId", "meteringBaseStation", "projectName",
    "meteringPlatform", "meteringSiteStatus", "timezoneOffsetUtc",
    "olderMeteringSiteIds",
]

def export_meteringbasestations(engine, out_dir: Path, dry_run: bool) -> int:
    dest = out_dir / "meteringbasestations"
    path = dest / "data.parquet"
    if not dry_run and path.exists():
        rows = pq.read_metadata(path).num_rows
        print(f"  meteringbasestations: already done ({rows:,} rows) — skipping")
        return rows

    cols = ", ".join(METERINGBASESTATIONS_SAFE_COLS)
    print(f"  reading meteringbasestations...", end=" ", flush=True)
    df = pd.read_sql(f"SELECT {cols} FROM meteringbasestations", engine)
    print(f"{len(df):,} rows", end=" ", flush=True)

    if dry_run:
        print("(dry run)")
        return len(df)

    dest.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow")
    mb = path.stat().st_size / 1024 / 1024
    print(f"→ {path.relative_to(out_dir.parent)} ({mb:.1f} MB)")
    return len(df)


# ── minigridprojects: exclude test sites ──────────────────────────────────────

def export_minigridprojects(engine, out_dir: Path, dry_run: bool) -> int:
    dest = out_dir / "minigridprojects"
    path = dest / "data.parquet"
    if not dry_run and path.exists():
        rows = pq.read_metadata(path).num_rows
        print(f"  minigridprojects: already done ({rows:,} rows) — skipping")
        return rows

    print(f"  reading minigridprojects...", end=" ", flush=True)
    df = pd.read_sql_table("minigridprojects", engine)
    # Drop test placeholders (lat/long = 0)
    df = df[(df["lat"] != 0) | (df["long"] != 0)].copy()
    print(f"{len(df):,} rows (after excluding test sites)", end=" ", flush=True)

    df = apply_transforms(df, "minigridprojects")

    if dry_run:
        print("(dry run)")
        return len(df)

    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "data.parquet"
    df.to_parquet(path, index=False, engine="pyarrow")
    mb = path.stat().st_size / 1024 / 1024
    print(f"→ {path.relative_to(out_dir.parent)} ({mb:.1f} MB)")
    return len(df)


# ── shared transform logic ────────────────────────────────────────────────────

def apply_transforms(df: pd.DataFrame, table: str) -> pd.DataFrame:
    # Drop excluded columns (silently skip any that don't exist in this df)
    drop = [c for c in DROP_COLS.get(table, []) if c in df.columns]
    if drop:
        df = df.drop(columns=drop)

    # Pseudonymize
    for col in PSEUDO_COLS.get(table, []):
        if col in df.columns:
            df[col] = pseudonymize_series(df[col].astype(str).where(df[col].notna()))

    # Per-table cleaning
    if table in CLEAN_FNS:
        df = CLEAN_FNS[table](df)

    return df


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Export Renewvia DB to anonymized Parquet.")
    parser.add_argument("--output-dir", default="data", help="Root output directory")
    parser.add_argument("--dry-run", action="store_true", help="Skip writing files")
    parser.add_argument("--table", help="Export only this table (for testing)")
    args = parser.parse_args()

    if not SALT:
        sys.exit("ANON_SALT not set in .env")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Connecting to {os.environ['DB_HOST']}...")
    engine = sqlalchemy.create_engine(
        DB_URL,
        connect_args={"connect_timeout": 30, "read_timeout": 1800, "write_timeout": 1800},
    )

    # Tables handled by special-case exporters
    special = {"sparkmeterreadings", "vrmgeneration", "minigridprojects", "meteringbasestations"}

    simple_tables = [t for t in DROP_COLS if t not in special]

    total_rows = 0

    for table in simple_tables:
        if args.table and args.table != table:
            continue
        print(f"\n[{table}]")
        total_rows += export_simple(engine, table, out_dir, args.dry_run)

    if not args.table or args.table == "meteringbasestations":
        print("\n[meteringbasestations]")
        total_rows += export_meteringbasestations(engine, out_dir, args.dry_run)

    if not args.table or args.table == "minigridprojects":
        print("\n[minigridprojects]")
        total_rows += export_minigridprojects(engine, out_dir, args.dry_run)

    if not args.table or args.table == "vrmgeneration":
        print("\n[vrmgeneration]")
        total_rows += export_vrmgeneration(engine, out_dir, args.dry_run)

    if not args.table or args.table == "sparkmeterreadings":
        print("\n[sparkmeterreadings]")
        total_rows += export_sparkmeterreadings(engine, out_dir, args.dry_run)

    print(f"\nDone. Total rows exported: {total_rows:,}")


if __name__ == "__main__":
    main()
