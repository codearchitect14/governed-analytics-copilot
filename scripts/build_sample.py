"""Build the committed 5,000 order sample from the full raw Olist files.

The sample keeps referential integrity: every retained item, payment and review points to a
retained order, every retained order points to a retained customer, and every retained item
points to a retained product and seller. Geolocation rows are kept for the zip prefixes that
the retained customers and sellers reference.

Run once when the raw files change. The output is committed so CI and the quick start work
without a Kaggle account.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path

from olist_schema import OLIST_TABLES, RAW_DIR, SAMPLE_DIR, OlistTable

DEFAULT_ORDER_COUNT = 5_000
DEFAULT_SEED = 20180101


def read_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def write_rows(path: Path, columns: Sequence[str], rows: Iterable[dict[str, str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def select_orders(orders_path: Path, count: int, seed: int) -> set[str]:
    order_ids = sorted(row["order_id"] for row in read_rows(orders_path))
    if count > len(order_ids):
        raise SystemExit(f"Requested {count} orders but only {len(order_ids)} exist")
    return set(random.Random(seed).sample(order_ids, count))  # noqa: S311 - reproducible sampling


def filter_file(
    table: OlistTable,
    source: Path,
    target: Path,
    keep: Callable[[dict[str, str]], bool],
) -> tuple[int, list[dict[str, str]]]:
    kept = [row for row in read_rows(source) if keep(row)]
    write_rows(target, table.columns, kept)
    return len(kept), kept


def build(raw_dir: Path, sample_dir: Path, order_count: int, seed: int) -> dict[str, int]:
    tables = {table.name: table for table in OLIST_TABLES}
    file_for = {table.name: raw_dir / table.file_name for table in OLIST_TABLES}
    sample_dir.mkdir(parents=True, exist_ok=True)

    order_ids = select_orders(file_for["orders"], order_count, seed)
    counts: dict[str, int] = {}

    orders_count, orders = filter_file(
        tables["orders"],
        file_for["orders"],
        sample_dir / tables["orders"].file_name,
        lambda row: row["order_id"] in order_ids,
    )
    counts["orders"] = orders_count
    customer_ids = {row["customer_id"] for row in orders}

    customers_count, customers = filter_file(
        tables["customers"],
        file_for["customers"],
        sample_dir / tables["customers"].file_name,
        lambda row: row["customer_id"] in customer_ids,
    )
    counts["customers"] = customers_count

    items_count, items = filter_file(
        tables["order_items"],
        file_for["order_items"],
        sample_dir / tables["order_items"].file_name,
        lambda row: row["order_id"] in order_ids,
    )
    counts["order_items"] = items_count
    product_ids = {row["product_id"] for row in items}
    seller_ids = {row["seller_id"] for row in items}

    counts["order_payments"], _ = filter_file(
        tables["order_payments"],
        file_for["order_payments"],
        sample_dir / tables["order_payments"].file_name,
        lambda row: row["order_id"] in order_ids,
    )
    counts["order_reviews"], _ = filter_file(
        tables["order_reviews"],
        file_for["order_reviews"],
        sample_dir / tables["order_reviews"].file_name,
        lambda row: row["order_id"] in order_ids,
    )

    counts["products"], _ = filter_file(
        tables["products"],
        file_for["products"],
        sample_dir / tables["products"].file_name,
        lambda row: row["product_id"] in product_ids,
    )

    sellers_count, sellers = filter_file(
        tables["sellers"],
        file_for["sellers"],
        sample_dir / tables["sellers"].file_name,
        lambda row: row["seller_id"] in seller_ids,
    )
    counts["sellers"] = sellers_count

    zip_prefixes = {row["customer_zip_code_prefix"] for row in customers} | {
        row["seller_zip_code_prefix"] for row in sellers
    }
    counts["geolocation"], _ = filter_file(
        tables["geolocation"],
        file_for["geolocation"],
        sample_dir / tables["geolocation"].file_name,
        lambda row: row["geolocation_zip_code_prefix"] in zip_prefixes,
    )

    translation = tables["product_category_name_translation"]
    counts[translation.name] = write_rows(
        sample_dir / translation.file_name,
        translation.columns,
        read_rows(file_for[translation.name]),
    )
    return counts


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--sample-dir", type=Path, default=SAMPLE_DIR)
    parser.add_argument("--orders", type=int, default=DEFAULT_ORDER_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    counts = build(args.raw_dir, args.sample_dir, args.orders, args.seed)
    for name, count in counts.items():
        print(f"  {name:<38} {count:>8,} rows")
    print(f"Sample written to {args.sample_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
