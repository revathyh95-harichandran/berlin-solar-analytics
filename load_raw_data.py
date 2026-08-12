"""
Extract + Load: Marktstammdatenregister (MaStR) solar units -> DuckDB raw layer.

Reads the raw MaStR export (CSV or XLSX), maps the German source columns onto
clean English names, normalises German-formatted numbers and dates, and lands
the result in `solar_berlin.duckdb` as `raw.raw_solar_installations`.

This is the "EL" of the ELT pipeline: types are cleaned so the data is
queryable, but no business logic is applied. That belongs in dbt.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent

# The MaStR export has shipped under a few different names/extensions.
# Try the canonical name first, then fall back to a glob.
SOURCE_CANDIDATES = ["raw_mastr_solar.csv", "raw_master_solar.csv.xlsx"]
SOURCE_GLOBS = ["raw_m*solar*.csv", "raw_m*solar*.xlsx", "raw_m*solar*.csv.xlsx"]

DUCKDB_PATH = Path(os.getenv("DUCKDB_PATH", PROJECT_ROOT / "solar_berlin.duckdb"))
TARGET_SCHEMA = os.getenv("RAW_SCHEMA", "raw")
TARGET_TABLE = os.getenv("RAW_TABLE", "raw_solar_installations")

ENCODINGS = ["utf-8-sig", "utf-8", "latin1"]

# Target column -> accepted German source headers, in priority order.
# MaStR is inconsistent about "MaStR-Nr." vs "MaStR-Nummer" and about which
# capacity field it populates, so every target accepts several spellings.
COLUMN_ALIASES: dict[str, list[str]] = {
    "installation_id": [
        "MaStR-Nummer der Einheit",
        "MaStR-Nr. der Einheit",
        "MaStR-Nr der Einheit",
    ],
    "state": ["Bundesland"],
    "city": ["Ort"],
    "postal_code": ["Postleitzahl", "PLZ"],
    "capacity_kw": [
        "Bruttoleistung der Einheit",
        "Nettonennleistung der Einheit",
        "Bruttoleistung",
        "Nettonennleistung",
    ],
    "install_date": [
        "Inbetriebnahmedatum der Einheit",
        "Inbetriebnahmedatum",
    ],
    "status": ["Betriebs-Status", "Betriebsstatus"],
}

COLUMN_ORDER = list(COLUMN_ALIASES)

# Order matters: the unambiguous ISO form first, then the US form this export
# actually uses, then the native German form.
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"]


# --------------------------------------------------------------------------
# Source discovery
# --------------------------------------------------------------------------

def find_source_file() -> Path:
    for name in SOURCE_CANDIDATES:
        candidate = PROJECT_ROOT / name
        if candidate.exists():
            return candidate
    for pattern in SOURCE_GLOBS:
        matches = sorted(PROJECT_ROOT.glob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError(
        f"No MaStR export found in {PROJECT_ROOT}. "
        f"Looked for {SOURCE_CANDIDATES} and {SOURCE_GLOBS}."
    )


def is_xlsx(path: Path) -> bool:
    """Detect a real XLSX by its ZIP magic bytes, not by file extension.

    The shipped export is named `.csv.xlsx`, so the extension alone lies.
    """
    with path.open("rb") as fh:
        return fh.read(2) == b"PK"


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def sniff_csv_dialect(path: Path) -> tuple[str, str]:
    """Return (encoding, delimiter) for a German CSV export."""
    for encoding in ENCODINGS:
        try:
            with path.open("r", encoding=encoding, newline="") as fh:
                sample = fh.read(64 * 1024)
        except UnicodeDecodeError:
            continue

        header = sample.splitlines()[0] if sample else ""
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
        except csv.Error:
            # Fall back to whichever candidate appears most in the header line.
            delimiter = max(";,\t|", key=header.count)
        return encoding, delimiter

    raise UnicodeDecodeError(
        "mastr", b"", 0, 1, f"Could not decode {path.name} with any of {ENCODINGS}"
    )


def read_source(path: Path) -> pd.DataFrame:
    if is_xlsx(path):
        print(f"  format   : XLSX (detected via ZIP magic bytes)")
        # dtype=object keeps Excel's native datetimes/floats intact; the
        # per-column converters below handle every type uniformly.
        frame = pd.read_excel(path, dtype=object, engine="openpyxl")
    else:
        encoding, delimiter = sniff_csv_dialect(path)
        printable = {"\t": "\\t"}.get(delimiter, delimiter)
        print(f"  format   : CSV (encoding={encoding}, delimiter='{printable}')")
        # dtype=str preserves German decimal commas for explicit conversion.
        frame = pd.read_csv(
            path,
            sep=delimiter,
            encoding=encoding,
            dtype=str,
            keep_default_na=True,
        )

    frame.columns = [str(c).strip() for c in frame.columns]
    return frame


# --------------------------------------------------------------------------
# Column mapping
# --------------------------------------------------------------------------

def normalise(name: str) -> str:
    """Fold a header to a comparison key: lowercase, no punctuation/whitespace."""
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def resolve_columns(frame: pd.DataFrame) -> dict[str, str]:
    """Map each target column to the best-matching source header."""
    lookup = {normalise(c): c for c in frame.columns}
    resolved: dict[str, str] = {}
    missing: list[str] = []

    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            source = lookup.get(normalise(alias))
            if source is not None:
                resolved[target] = source
                note = "" if alias == aliases[0] else "  (alias)"
                print(f"  {target:<16} <- {source!r}{note}")
                break
        else:
            missing.append(target)
            print(f"  {target:<16} <- MISSING (tried: {', '.join(aliases)})")

    if missing:
        raise KeyError(f"Source file is missing required columns: {missing}")
    return resolved


# --------------------------------------------------------------------------
# Value conversion
# --------------------------------------------------------------------------

def to_text(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def to_postal_code(value) -> str | None:
    """Postal codes are identifiers, not numbers - keep leading zeros."""
    text = to_text(value)
    if text is None:
        return None
    # Excel reads PLZ as a number, so "01067" arrives as 1067 or 1067.0.
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".")[0]
    return text.zfill(5) if text.isdigit() else text


def to_float(value) -> float | None:
    """Parse a number that may use German formatting ('1.234,5' -> 1234.5)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else float(value)

    text = to_text(value)
    if text is None:
        return None

    text = text.replace("\xa0", "").replace(" ", "")
    if "," in text:
        # Comma is the decimal separator; any dots are thousands separators.
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def to_date(value) -> dt.date | None:
    """Parse a date to a real date object.

    The XLSX export is genuinely mixed: Excel converted some cells to real
    datetimes and left the rest as 'M/D/YYYY' text, so both are handled.
    """
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.date()

    text = to_text(value)
    if text is None:
        return None

    text = text.split("T")[0].split(" ")[0]
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def transform(frame: pd.DataFrame, resolved: dict[str, str]) -> pd.DataFrame:
    out = pd.DataFrame()
    out["installation_id"] = frame[resolved["installation_id"]].map(to_text)
    out["state"] = frame[resolved["state"]].map(to_text)
    out["city"] = frame[resolved["city"]].map(to_text)
    out["postal_code"] = frame[resolved["postal_code"]].map(to_postal_code)
    out["capacity_kw"] = frame[resolved["capacity_kw"]].map(to_float).astype("float64")
    out["install_date"] = pd.to_datetime(
        frame[resolved["install_date"]].map(to_date), errors="coerce"
    )
    out["status"] = frame[resolved["status"]].map(to_text)
    return out[COLUMN_ORDER]


def report_quality(frame: pd.DataFrame) -> None:
    print("\n[4/5] Data quality")
    total = len(frame)
    for column in COLUMN_ORDER:
        nulls = int(frame[column].isna().sum())
        pct = (nulls / total * 100) if total else 0.0
        print(f"  {column:<16} nulls: {nulls:>6} ({pct:5.2f}%)")

    dupes = int(frame["installation_id"].duplicated().sum())
    print(f"  duplicate installation_id : {dupes}")
    if frame["capacity_kw"].notna().any():
        print(
            f"  capacity_kw range         : "
            f"{frame['capacity_kw'].min():.3f} .. {frame['capacity_kw'].max():.3f} kW"
        )
    if frame["install_date"].notna().any():
        lo = frame["install_date"].min().date()
        hi = frame["install_date"].max().date()
        print(f"  install_date range        : {lo} .. {hi}")


# --------------------------------------------------------------------------
# Load
# --------------------------------------------------------------------------

def load_to_duckdb(frame: pd.DataFrame) -> None:
    print(f"\n[5/5] Loading into DuckDB -> {DUCKDB_PATH.name}")
    con = duckdb.connect(str(DUCKDB_PATH))
    try:
        con.register("staged_solar", frame)
        con.execute(f'CREATE SCHEMA IF NOT EXISTS "{TARGET_SCHEMA}"')
        # pandas only has a datetime64 type, so install_date arrives as a
        # timestamp; cast it back down to a true DATE in the warehouse.
        projection = ", ".join(
            f"CAST({c} AS DATE) AS {c}" if c == "install_date" else c
            for c in COLUMN_ORDER
        )
        # Full refresh: the raw layer mirrors the current export exactly.
        con.execute(
            f'CREATE OR REPLACE TABLE "{TARGET_SCHEMA}"."{TARGET_TABLE}" AS '
            f"SELECT {projection} FROM staged_solar"
        )
        con.unregister("staged_solar")

        fqn = f'"{TARGET_SCHEMA}"."{TARGET_TABLE}"'
        print(f"  loaded {fqn}")

        print("\n" + "=" * 78)
        print("VERIFICATION (read back from DuckDB)")
        print("=" * 78)

        schema = con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            [TARGET_SCHEMA, TARGET_TABLE],
        ).fetchall()
        print("\nTable schema:")
        for name, dtype in schema:
            print(f"  {name:<16} {dtype}")

        total = con.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()[0]
        print(f"\nTOTAL ROW COUNT: {total:,}")

        print("\nFIRST 5 RECORDS:")
        preview = con.execute(f"SELECT * FROM {fqn} LIMIT 5").df()
        with pd.option_context("display.max_columns", None, "display.width", 200):
            print(preview.to_string(index=False))
        print("=" * 78)
    finally:
        con.close()


def main() -> int:
    print("=" * 78)
    print("MaStR Solar -> DuckDB raw layer")
    print("=" * 78)

    source = find_source_file()
    size_mb = source.stat().st_size / 1024 / 1024
    print(f"\n[1/5] Source file")
    print(f"  path     : {source.name} ({size_mb:.2f} MB)")

    frame = read_source(source)
    print(f"  read     : {len(frame):,} rows x {len(frame.columns)} columns")

    print("\n[2/5] Column mapping (German -> English)")
    resolved = resolve_columns(frame)

    print("\n[3/5] Transforming values")
    clean = transform(frame, resolved)
    print(f"  produced : {len(clean):,} rows x {len(clean.columns)} columns")

    report_quality(clean)
    load_to_duckdb(clean)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
