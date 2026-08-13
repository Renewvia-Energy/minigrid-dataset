"""
Flatten the data/ directory from its hierarchical layout to a single level
suitable for Zenodo upload.

Current layout:
  data/{table}/data.parquet
  data/sparkmeterreadings/{site}/{year}.parquet
  data/sparkmeterreadings_clean/{site}.parquet

Flat layout produced:
  data/{table}.parquet
  data/sparkmeterreadings_{site}.parquet         (years merged per site)
  data/sparkmeterreadings_clean_{site}.parquet

Run with:
    python scripts/flatten.py [--data-dir data] [--dry-run] [--remove-source] [--table TABLE]
"""

import argparse
import shutil
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


SIMPLE_TABLES = [
    "customers",
    "meteringbasestations",
    "meteringplatformtariffs",
    "minigridprojects",
    "paymentconfirmations",
    "paymentvalidations",
    "sparkmetercustomers",
    "sparkmetertransactions",
    "tariffs",
    "vrmgeneration",
]


def _normalize_schema(schema: pa.Schema) -> pa.Schema:
    """Promote null-typed fields to string and decimal to float64.

    Mirrors normalize_arrow_table in export.py: a column that is entirely NULL
    in the first year file gets type `null`, which PyArrow cannot cast *to* from
    a concrete type in a later year's batch.
    """
    return pa.schema([
        f.with_type(pa.string()) if f.type == pa.null()
        else f.with_type(pa.float64()) if pa.types.is_decimal(f.type)
        else f
        for f in schema
    ])


def merge_parquet_files(input_paths: list[Path], output_path: Path) -> int:
    """Stream-merge parquet files into one, casting to a normalized schema. Returns row count."""
    tmp = output_path.with_suffix(".tmp")
    try:
        schema = _normalize_schema(pq.read_schema(input_paths[0]))
        total_rows = 0
        with pq.ParquetWriter(tmp, schema) as writer:
            for path in input_paths:
                for batch in pq.ParquetFile(path).iter_batches():
                    tbl = pa.Table.from_batches([batch]).cast(schema, safe=False)
                    writer.write_table(tbl)
                    total_rows += len(tbl)
        tmp.rename(output_path)
        return total_rows
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def flatten_simple(data_dir: Path, table: str, dry_run: bool, remove_source: bool) -> None:
    src = data_dir / table / "data.parquet"
    dst = data_dir / f"{table}.parquet"

    if not src.exists():
        print(f"  {table}: source not found — skipping")
        return
    if dst.exists():
        print(f"  {table}: already done — skipping")
        return

    mb = src.stat().st_size / 1024 / 1024
    print(f"  {table}: {mb:.1f} MB", end="")

    if dry_run:
        print(" (dry run)")
        return

    shutil.copy2(src, dst)
    print(f" → {dst.name}")

    if remove_source:
        shutil.rmtree(data_dir / table)
        print(f"    removed {data_dir / table}/")


def flatten_readings_clean(data_dir: Path, dry_run: bool, remove_source: bool) -> None:
    print("\n[sparkmeterreadings_clean]")
    src_dir = data_dir / "sparkmeterreadings_clean"
    if not src_dir.exists():
        print("  source directory not found — skipping")
        return

    site_files = sorted(src_dir.glob("*.parquet"))
    all_done = True
    for src in site_files:
        site = src.stem
        dst = data_dir / f"sparkmeterreadings_clean_{site}.parquet"
        if dst.exists():
            print(f"  {site}: already done — skipping")
            continue
        all_done = False
        mb = src.stat().st_size / 1024 / 1024
        print(f"  {site}: {mb:.1f} MB", end="")
        if dry_run:
            print(" (dry run)")
            continue
        shutil.copy2(src, dst)
        print(f" → {dst.name}")

    if remove_source and not dry_run and all_done:
        shutil.rmtree(src_dir)
        print(f"  removed {src_dir}/")


def flatten_readings(data_dir: Path, dry_run: bool, remove_source: bool) -> None:
    print("\n[sparkmeterreadings]")
    src_dir = data_dir / "sparkmeterreadings"
    if not src_dir.exists():
        print("  source directory not found — skipping")
        return

    site_dirs = sorted(d for d in src_dir.iterdir() if d.is_dir())
    for site_dir in site_dirs:
        site = site_dir.name
        year_files = sorted(site_dir.glob("*.parquet"))
        if not year_files:
            continue

        dst = data_dir / f"sparkmeterreadings_{site}.parquet"
        if dst.exists():
            rows = pq.read_metadata(dst).num_rows
            print(f"  {site}: already done ({rows:,} rows) — skipping")
            continue

        total_mb = sum(f.stat().st_size for f in year_files) / 1024 / 1024
        years = [f.stem for f in year_files]
        print(f"  {site} [{', '.join(years)}]: {total_mb:.1f} MB", end="")

        if dry_run:
            print(" (dry run)")
            continue

        print(" merging...", end="", flush=True)
        n_rows = merge_parquet_files(year_files, dst)
        out_mb = dst.stat().st_size / 1024 / 1024
        print(f" {n_rows:,} rows → {out_mb:.1f} MB")

        if remove_source:
            shutil.rmtree(site_dir)
            print(f"    removed {site_dir}/")

    if remove_source and not dry_run:
        remaining = [f for f in src_dir.iterdir() if not f.name.startswith(".done_")]
        if not remaining:
            shutil.rmtree(src_dir)
            print(f"  removed {src_dir}/")


def main():
    parser = argparse.ArgumentParser(
        description="Flatten data/ hierarchy to a single level for Zenodo upload."
    )
    parser.add_argument("--data-dir", default="data", help="Root data directory (default: data)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing or deleting")
    parser.add_argument(
        "--remove-source", action="store_true",
        help="Delete source files/dirs after successful flattening",
    )
    parser.add_argument("--table", help="Process only this table (e.g. customers, sparkmeterreadings)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        sys.exit(f"Data directory not found: {data_dir}")

    if args.remove_source and not args.dry_run:
        print("WARNING: --remove-source will delete original source files/dirs after flattening.")
        resp = input("Continue? [y/N] ")
        if resp.strip().lower() != "y":
            sys.exit("Aborted.")

    want = args.table

    simple_targets = [t for t in SIMPLE_TABLES if not want or want == t]
    if simple_targets:
        print("\n[simple tables]")
        for table in simple_targets:
            flatten_simple(data_dir, table, args.dry_run, args.remove_source)

    if not want or want == "sparkmeterreadings_clean":
        flatten_readings_clean(data_dir, args.dry_run, args.remove_source)

    if not want or want == "sparkmeterreadings":
        flatten_readings(data_dir, args.dry_run, args.remove_source)

    print("\nDone.")


if __name__ == "__main__":
    main()
