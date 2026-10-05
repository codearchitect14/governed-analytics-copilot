"""Load the Olist CSV files into the raw schema of PostgreSQL.

Every source column is stored as text. Typing, renames and quirk fixes happen in the dbt
staging models. The load is idempotent: each table is truncated and reloaded inside a single
transaction, so a failed run leaves the previous data in place.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import psycopg
from psycopg import sql

from olist_schema import (
    MANIFEST_TABLE,
    OLIST_TABLES,
    RAW_DIR,
    RAW_SCHEMA,
    SAMPLE_DIR,
    OlistTable,
)

CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class LoadResult:
    table: str
    row_count: int
    source_sha256: str


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle))


def validate_source(path: Path, table: OlistTable) -> None:
    """Fail fast when a file is missing or its columns differ from the contract."""
    if not path.is_file():
        raise FileNotFoundError(f"Missing source file for {table.name}: {path}")
    header = read_header(path)
    if tuple(header) != table.columns:
        raise ValueError(
            f"Unexpected columns in {path.name}.\n"
            f"  expected: {list(table.columns)}\n"
            f"  found:    {header}"
        )


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def create_table_statement(table: OlistTable) -> sql.Composed:
    columns = [sql.SQL("{} TEXT").format(sql.Identifier(column)) for column in table.columns]
    return sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} ({})").format(
        sql.Identifier(RAW_SCHEMA),
        sql.Identifier(table.name),
        sql.SQL(", ").join(columns),
    )


def copy_statement(table: OlistTable) -> sql.Composed:
    columns = sql.SQL(", ").join(sql.Identifier(column) for column in table.columns)
    return sql.SQL("COPY {}.{} ({}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')").format(
        sql.Identifier(RAW_SCHEMA),
        sql.Identifier(table.name),
        columns,
    )


def ensure_manifest(cursor: psycopg.Cursor[tuple[object, ...]]) -> None:
    cursor.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {} (
                table_name TEXT PRIMARY KEY,
                source_file TEXT NOT NULL,
                row_count BIGINT NOT NULL,
                source_sha256 TEXT NOT NULL,
                loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        ).format(sql.Identifier(RAW_SCHEMA, MANIFEST_TABLE))
    )


def load_table(
    cursor: psycopg.Cursor[tuple[object, ...]], table: OlistTable, source_dir: Path
) -> LoadResult:
    path = source_dir / table.file_name
    validate_source(path, table)

    cursor.execute(create_table_statement(table))
    cursor.execute(
        sql.SQL("TRUNCATE {}.{}").format(sql.Identifier(RAW_SCHEMA), sql.Identifier(table.name))
    )
    with cursor.copy(copy_statement(table)) as copy, path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            copy.write(chunk)

    cursor.execute(
        sql.SQL("SELECT count(*) FROM {}.{}").format(
            sql.Identifier(RAW_SCHEMA), sql.Identifier(table.name)
        )
    )
    count_row = cast("tuple[int] | None", cursor.fetchone())
    row_count = count_row[0] if count_row is not None else 0
    digest = sha256_of(path)

    cursor.execute(
        sql.SQL(
            """
            INSERT INTO {} (table_name, source_file, row_count, source_sha256, loaded_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (table_name) DO UPDATE SET
                source_file = EXCLUDED.source_file,
                row_count = EXCLUDED.row_count,
                source_sha256 = EXCLUDED.source_sha256,
                loaded_at = EXCLUDED.loaded_at
            """
        ).format(sql.Identifier(RAW_SCHEMA, MANIFEST_TABLE)),
        (table.name, path.name, row_count, digest),
    )
    return LoadResult(table=table.name, row_count=row_count, source_sha256=digest)


def check_expected_counts(results: Sequence[LoadResult]) -> list[str]:
    """Compare loaded counts with the published Olist release. Returns mismatch messages."""
    expected = {table.name: table.expected_rows for table in OLIST_TABLES}
    problems: list[str] = []
    for result in results:
        target = expected.get(result.table)
        if target is not None and result.row_count != target:
            problems.append(f"{result.table}: loaded {result.row_count}, expected {target}")
    return problems


def run_load(database_url: str, source_dir: Path, verify_counts: bool) -> list[LoadResult]:
    results: list[LoadResult] = []
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        ensure_manifest(cursor)
        for table in OLIST_TABLES:
            result = load_table(cursor, table, source_dir)
            results.append(result)
            print(f"  loaded {result.table:<38} {result.row_count:>10,} rows")

        problems = check_expected_counts(results) if verify_counts else []
        if problems:
            connection.rollback()
            raise SystemExit("Row count check failed:\n  " + "\n  ".join(problems))
    return results


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Load the committed 5,000 order sample instead of the full raw download",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help="Directory with the CSV files (defaults to dataset/raw/olist or dataset/sample/olist)",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("LOADER_DATABASE_URL", ""),
        help="PostgreSQL URL for the loader role (defaults to LOADER_DATABASE_URL)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.database_url:
        print("LOADER_DATABASE_URL is not set. Copy .env.example to .env first.", file=sys.stderr)
        return 2

    source_dir: Path = args.source_dir or (SAMPLE_DIR if args.sample else RAW_DIR)
    print(f"Loading Olist CSV files from {source_dir} into schema {RAW_SCHEMA}")
    results = run_load(args.database_url, source_dir, verify_counts=not args.sample)
    total = sum(result.row_count for result in results)
    print(f"Done: {len(results)} tables, {total:,} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
