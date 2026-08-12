"""
Export the star schema from DuckDB to BI-ready CSV and Parquet files.

Reads fct_installations, dim_geography and dim_date from the `main` schema and
writes both formats into ./exports.

Formatting is handled by DuckDB's native COPY rather than pandas, for two
reasons: COPY preserves the warehouse's declared types exactly (no float/int
coercion or datetime widening on the way through a DataFrame), and the Parquet
writer is built in, so the project needs no pyarrow dependency.

BI-compatibility choices, all deliberate:
  * Dates are written as ISO `YYYY-MM-DD` with no time component, so no tool
    has to guess between D/M and M/D ordering.
  * Decimals use '.' with no thousands separator - the raw MaStR export used
    German conventions, and re-introducing them here would break every
    downstream numeric parse.
  * Parquet carries a real schema (DATE, DOUBLE, VARCHAR), so it is the
    preferred source for Power BI and Tableau. CSV is the interchange fallback.
  * Parquet uses SNAPPY compression - universally supported by BI connectors,
    unlike newer codecs such as ZSTD.
  * NULLs are written as empty fields, which both Power BI and Tableau read as
    null rather than as the literal string "NULL".
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
DUCKDB_PATH = Path(os.getenv("DUCKDB_PATH", PROJECT_ROOT / "solar_berlin.duckdb"))
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", PROJECT_ROOT / "exports"))
MART_SCHEMA = os.getenv("MART_SCHEMA", "main")

# Exported in dimension-then-fact order so the output reads like the model.
TABLES = ["dim_geography", "dim_date", "fct_installations"]

# Columns that must stay text in a BI tool even though they look numeric.
# Postal codes are identifiers: inferred as an integer, '01067' loses its
# leading zero. Berlin's range (10115-14199) has none today, but the column is
# text in the warehouse and should stay text downstream.
TEXT_LIKE_COLUMNS = {"postal_code", "installation_id", "geo_id"}


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:,.1f} {unit}"
        size /= 1024
    return f"{size:,.1f} GB"


def as_posix(path: Path) -> str:
    """DuckDB's COPY wants forward slashes, even on Windows."""
    return path.as_posix()


def get_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[str, str]]:
    return con.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = ? and table_name = ? order by ordinal_position",
        [MART_SCHEMA, table],
    ).fetchall()


def export_table(
    con: duckdb.DuckDBPyConnection, table: str
) -> tuple[dict, int]:
    fqn = f'"{MART_SCHEMA}"."{table}"'
    csv_path = EXPORT_DIR / f"{table}.csv"
    parquet_path = EXPORT_DIR / f"{table}.parquet"

    rows = con.execute(f"select count(*) from {fqn}").fetchone()[0]
    columns = get_columns(con, table)

    # Quote the identifier-like text columns. CSV has no type system, so this
    # is the strongest hint the format allows that these are not numbers.
    # It does not fully prevent a reader from inferring numeric - see the
    # inference report below and prefer Parquet where types matter.
    quoted = [name for name, _ in columns if name in TEXT_LIKE_COLUMNS]
    force_quote = f", force_quote ({', '.join(quoted)})" if quoted else ""

    # CSV: explicit dialect so nothing is left to the reader's guesswork.
    con.execute(
        f"""
        copy {fqn} to '{as_posix(csv_path)}'
        (
            format csv,
            header true,
            delimiter ',',
            quote '"',
            escape '"',
            nullstr '',
            dateformat '%Y-%m-%d',
            timestampformat '%Y-%m-%dT%H:%M:%S'
            {force_quote}
        )
        """
    )

    # Parquet: carries the schema itself, so BI tools need no type hints.
    con.execute(
        f"""
        copy {fqn} to '{as_posix(parquet_path)}'
        (format parquet, compression snappy)
        """
    )

    manifest = {
        "table": table,
        "source": f"{MART_SCHEMA}.{table}",
        "rows": rows,
        "files": {"csv": csv_path.name, "parquet": parquet_path.name},
        "columns": [
            {
                "name": name,
                "duckdb_type": dtype,
                "bi_type": "text" if name in TEXT_LIKE_COLUMNS else _bi_type(dtype),
                "force_text_on_import": name in TEXT_LIKE_COLUMNS,
            }
            for name, dtype in columns
        ],
    }
    return manifest, rows


def _bi_type(duckdb_type: str) -> str:
    t = duckdb_type.upper()
    if t.startswith(("VARCHAR", "TEXT", "STRING")):
        return "text"
    if t.startswith("DATE"):
        return "date"
    if t.startswith("TIMESTAMP"):
        return "datetime"
    if t.startswith(("DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC")):
        return "decimal"
    if t.startswith(("INT", "BIGINT", "SMALLINT", "TINYINT", "HUGEINT", "UINT")):
        return "whole number"
    if t.startswith("BOOL"):
        return "boolean"
    return "text"


def verify(con: duckdb.DuckDBPyConnection, table: str, expected_rows: int) -> bool:
    """Read both files back and confirm rows and Parquet types round-trip."""
    csv_path = as_posix(EXPORT_DIR / f"{table}.csv")
    parquet_path = as_posix(EXPORT_DIR / f"{table}.parquet")

    csv_rows = con.execute(
        f"select count(*) from read_csv_auto('{csv_path}', header=true)"
    ).fetchone()[0]
    parquet_rows = con.execute(
        f"select count(*) from read_parquet('{parquet_path}')"
    ).fetchone()[0]

    warehouse_types = dict(get_columns(con, table))
    parquet_types = {
        r[0]: r[1]
        for r in con.execute(
            f"describe select * from read_parquet('{parquet_path}')"
        ).fetchall()
    }
    type_drift = [
        c for c, t in warehouse_types.items() if parquet_types.get(c) != t
    ]

    ok = csv_rows == expected_rows == parquet_rows and not type_drift
    flag = "OK " if ok else "FAIL"
    print(
        f"  [{flag}] {table:<20} warehouse={expected_rows:>6,}  "
        f"csv={csv_rows:>6,}  parquet={parquet_rows:>6,}  "
        f"parquet types={'exact' if not type_drift else 'DRIFT ' + str(type_drift)}"
    )
    return ok


def report_csv_inference(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Flag columns a CSV reader will type differently from the warehouse.

    CSV carries no schema, so this is reported rather than fixed. The
    practical answer is to load the Parquet file instead, or to override the
    column type on import using exports/_schema.json.
    """
    warnings: list[str] = []
    for table in TABLES:
        warehouse_types = dict(get_columns(con, table))
        csv_path = as_posix(EXPORT_DIR / f"{table}.csv")
        csv_types = {
            r[0]: r[1]
            for r in con.execute(
                f"describe select * from read_csv_auto('{csv_path}', header=true)"
            ).fetchall()
        }
        for column, warehouse_type in warehouse_types.items():
            inferred = csv_types.get(column, "?")
            # INTEGER widening to BIGINT is harmless; a text column becoming
            # numeric is not - that is where leading zeros get destroyed.
            if inferred == warehouse_type:
                continue
            if warehouse_type == "INTEGER" and inferred == "BIGINT":
                continue
            warnings.append(
                f"{table}.{column}: warehouse={warehouse_type} "
                f"-> csv inferred as {inferred}"
            )
    return warnings


def main() -> int:
    print("=" * 78)
    print("Star schema -> BI exports (CSV + Parquet)")
    print("=" * 78)

    if not DUCKDB_PATH.exists():
        print(f"ERROR: database not found at {DUCKDB_PATH}", file=sys.stderr)
        print("Run: python load_raw_data.py && python -m dbt.cli.main build", file=sys.stderr)
        return 1

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nSource   : {DUCKDB_PATH.name} (schema '{MART_SCHEMA}')")
    print(f"Target   : {EXPORT_DIR.name}{os.sep}")

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        present = {
            r[0]
            for r in con.execute(
                "select table_name from information_schema.tables where table_schema = ?",
                [MART_SCHEMA],
            ).fetchall()
        }
        missing = [t for t in TABLES if t not in present]
        if missing:
            print(f"\nERROR: missing tables in '{MART_SCHEMA}': {missing}", file=sys.stderr)
            print("Run: python -m dbt.cli.main build", file=sys.stderr)
            return 1

        print("\n[1/3] Exporting")
        manifests = []
        expected = {}
        for table in TABLES:
            manifest, rows = export_table(con, table)
            manifests.append(manifest)
            expected[table] = rows
            print(f"  exported {table:<20} {rows:>6,} rows x {len(manifest['columns'])} cols")

        print("\n[2/3] Verifying round-trip (re-read from disk)")
        all_ok = all(verify(con, t, expected[t]) for t in TABLES)

        print("\n[3/3] CSV type-inference check")
        csv_warnings = report_csv_inference(con)
        if csv_warnings:
            for warning in csv_warnings:
                print(f"  [WARN] {warning}")
            print(
                "\n  CSV has no schema, so these cannot be enforced in the file.\n"
                "  Load the .parquet instead (types are exact), or override the\n"
                "  column type on import using exports/_schema.json."
            )
        else:
            print("  No divergence: CSV re-reads with the warehouse types.")

        schema_path = EXPORT_DIR / "_schema.json"
        schema_path.write_text(
            json.dumps(
                {
                    "database": DUCKDB_PATH.name,
                    "schema": MART_SCHEMA,
                    "grain": "fct_installations: one row per solar unit",
                    "joins": [
                        "fct_installations.geo_id = dim_geography.geo_id",
                        "fct_installations.install_date = dim_date.install_date",
                    ],
                    "csv_conventions": {
                        "encoding": "UTF-8",
                        "delimiter": ",",
                        "quote": '"',
                        "date_format": "YYYY-MM-DD",
                        "decimal_separator": ".",
                        "null_representation": "empty field",
                    },
                    "tables": manifests,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        print("\n" + "=" * 78)
        print("FILES WRITTEN")
        print("=" * 78)
        for path in sorted(EXPORT_DIR.iterdir()):
            print(f"  {path.name:<32} {human_size(path.stat().st_size):>12}")

        print("\n" + ("All exports verified." if all_ok else "VERIFICATION FAILED."))
        return 0 if all_ok else 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
