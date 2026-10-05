"""Unit tests for the Olist download, load and sample scripts.

The fixture under scripts/tests/fixtures/olist_mini is a hand written miniature with the real
Olist headers. It is not the Olist dataset and is never used for published numbers.
"""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path

import pytest

import build_sample
import download_data
import load_olist
from olist_schema import OLIST_TABLES, SOURCE_FILE_NAMES

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "olist_mini"
TABLES_BY_NAME = {table.name: table for table in OLIST_TABLES}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_fixture_contains_every_expected_file() -> None:
    for file_name in SOURCE_FILE_NAMES.values():
        assert (FIXTURE_DIR / file_name).is_file(), file_name


def test_fixture_headers_match_the_contract() -> None:
    for table in OLIST_TABLES:
        load_olist.validate_source(FIXTURE_DIR / table.file_name, table)


def test_validate_source_rejects_renamed_column(tmp_path: Path) -> None:
    table = TABLES_BY_NAME["orders"]
    broken = tmp_path / table.file_name
    broken.write_text(
        "order_id,customer_id,status\nO1,C1,delivered\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unexpected columns"):
        load_olist.validate_source(broken, table)


def test_validate_source_rejects_missing_file(tmp_path: Path) -> None:
    table = TABLES_BY_NAME["sellers"]

    with pytest.raises(FileNotFoundError):
        load_olist.validate_source(tmp_path / table.file_name, table)


def test_copy_statement_uses_csv_format_with_header() -> None:
    statement = load_olist.copy_statement(TABLES_BY_NAME["orders"]).as_string(None)

    assert "COPY" in statement
    assert "FORMAT csv" in statement
    assert "HEADER true" in statement


def test_check_expected_counts_reports_only_mismatches() -> None:
    results = [
        load_olist.LoadResult("orders", 99_441, "a"),
        load_olist.LoadResult("sellers", 3_000, "b"),
        load_olist.LoadResult("unknown_table", 1, "c"),
    ]

    problems = load_olist.check_expected_counts(results)

    assert problems == ["sellers: loaded 3000, expected 3095"]


def test_sample_builder_keeps_referential_integrity(tmp_path: Path) -> None:
    counts = build_sample.build(FIXTURE_DIR, tmp_path, order_count=4, seed=7)

    orders = read_csv(tmp_path / TABLES_BY_NAME["orders"].file_name)
    order_ids = {row["order_id"] for row in orders}
    customer_ids = {row["customer_id"] for row in orders}
    items = read_csv(tmp_path / TABLES_BY_NAME["order_items"].file_name)
    payments = read_csv(tmp_path / TABLES_BY_NAME["order_payments"].file_name)
    reviews = read_csv(tmp_path / TABLES_BY_NAME["order_reviews"].file_name)
    customers = read_csv(tmp_path / TABLES_BY_NAME["customers"].file_name)
    products = read_csv(tmp_path / TABLES_BY_NAME["products"].file_name)
    sellers = read_csv(tmp_path / TABLES_BY_NAME["sellers"].file_name)

    assert counts["orders"] == 4
    assert len(order_ids) == 4
    assert {row["order_id"] for row in items} <= order_ids
    assert {row["order_id"] for row in payments} <= order_ids
    assert {row["order_id"] for row in reviews} <= order_ids
    assert {row["customer_id"] for row in customers} <= customer_ids
    assert {row["product_id"] for row in items} <= {row["product_id"] for row in products}
    assert {row["seller_id"] for row in items} <= {row["seller_id"] for row in sellers}


def test_sample_builder_is_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    build_sample.build(FIXTURE_DIR, first, order_count=3, seed=11)
    build_sample.build(FIXTURE_DIR, second, order_count=3, seed=11)

    assert read_csv(first / TABLES_BY_NAME["orders"].file_name) == read_csv(
        second / TABLES_BY_NAME["orders"].file_name
    )


def test_download_without_credentials_returns_exit_code_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    monkeypatch.setattr(download_data.Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.setattr(download_data, "DOWNLOAD_DIR", tmp_path / "downloads")
    monkeypatch.setattr(download_data, "RAW_DIR", tmp_path / "raw")

    assert download_data.main([]) == 2


def test_checksum_mismatch_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "brazilian-ecommerce.zip"
    archive.write_bytes(b"first release")
    checksum_file = tmp_path / "checksums.sha256"
    monkeypatch.setattr(download_data, "CHECKSUM_FILE", checksum_file)

    download_data.verify_or_record(archive)
    archive.write_bytes(b"tampered release")

    with pytest.raises(SystemExit, match="Checksum mismatch"):
        download_data.verify_or_record(archive)


def test_extract_fails_when_archive_lacks_expected_files(tmp_path: Path) -> None:
    archive = tmp_path / "partial.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("olist_orders_dataset.csv", "order_id\n")

    with pytest.raises(SystemExit, match="missing expected files"):
        download_data.extract_tables(archive, tmp_path / "out")
