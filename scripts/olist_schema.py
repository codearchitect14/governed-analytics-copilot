"""Expected layout of the Olist Brazilian E-Commerce CSV files.

Shared by the download, load and sample scripts so the column contract lives in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = REPO_ROOT / "dataset"
RAW_DIR = DATASET_ROOT / "raw" / "olist"
SAMPLE_DIR = DATASET_ROOT / "sample" / "olist"
CHECKSUM_FILE = DATASET_ROOT / "checksums.sha256"

KAGGLE_DATASET = "olistbr/brazilian-ecommerce"
KAGGLE_DOWNLOAD_URL = f"https://www.kaggle.com/api/v1/datasets/download/{KAGGLE_DATASET}"

RAW_SCHEMA = "raw"
MANIFEST_TABLE = "load_manifest"


@dataclass(frozen=True)
class OlistTable:
    """One source CSV file and the columns it must contain, in file order."""

    name: str
    columns: tuple[str, ...]
    expected_rows: int | None  # Published row count of the full Olist release, None if not checked

    @property
    def file_name(self) -> str:
        if self.name == "product_category_name_translation":
            return f"{self.name}.csv"
        return f"olist_{self.name}_dataset.csv"


OLIST_TABLES: tuple[OlistTable, ...] = (
    OlistTable(
        "customers",
        (
            "customer_id",
            "customer_unique_id",
            "customer_zip_code_prefix",
            "customer_city",
            "customer_state",
        ),
        99_441,
    ),
    OlistTable(
        "geolocation",
        (
            "geolocation_zip_code_prefix",
            "geolocation_lat",
            "geolocation_lng",
            "geolocation_city",
            "geolocation_state",
        ),
        1_000_163,
    ),
    OlistTable(
        "order_items",
        (
            "order_id",
            "order_item_id",
            "product_id",
            "seller_id",
            "shipping_limit_date",
            "price",
            "freight_value",
        ),
        112_650,
    ),
    OlistTable(
        "order_payments",
        (
            "order_id",
            "payment_sequential",
            "payment_type",
            "payment_installments",
            "payment_value",
        ),
        103_886,
    ),
    OlistTable(
        "order_reviews",
        (
            "review_id",
            "order_id",
            "review_score",
            "review_comment_title",
            "review_comment_message",
            "review_creation_date",
            "review_answer_timestamp",
        ),
        99_224,
    ),
    OlistTable(
        "orders",
        (
            "order_id",
            "customer_id",
            "order_status",
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ),
        99_441,
    ),
    OlistTable(
        "products",
        (
            "product_id",
            "product_category_name",
            "product_name_lenght",
            "product_description_lenght",
            "product_photos_qty",
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm",
        ),
        32_951,
    ),
    OlistTable(
        "sellers",
        (
            "seller_id",
            "seller_zip_code_prefix",
            "seller_city",
            "seller_state",
        ),
        3_095,
    ),
    OlistTable(
        "product_category_name_translation",
        (
            "product_category_name",
            "product_category_name_english",
        ),
        71,
    ),
)

# Source file name for each table, for example "orders" -> "olist_orders_dataset.csv".
SOURCE_FILE_NAMES: dict[str, str] = {table.name: table.file_name for table in OLIST_TABLES}
