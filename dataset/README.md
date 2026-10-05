# Dataset

This folder holds the data used by the warehouse, the semantic layer and the evaluation harness.

## Sources and licenses

| Dataset | Used for | Source | License |
|---|---|---|---|
| Olist Brazilian E-Commerce | Main warehouse (about 99,441 orders, 2016 to 2018) | Kaggle `olistbr/brazilian-ecommerce` | CC BY-NC-SA 4.0 (verify on the Kaggle page before publishing) |

Attribution: Olist, Brazilian E-Commerce Public Dataset (Kaggle, `olistbr/brazilian-ecommerce`).
Non commercial use and share alike terms apply to the data. The license must be verified before any public release.

Benchmark datasets (BIRD Mini-Dev, Spider) and the Brazil states GeoJSON are added in later phases.

## Layout

```
dataset/
  README.md                 this file
  checksums.sha256          SHA-256 of the downloaded archive (created on first download)
  downloads/                archive from Kaggle (git ignored)
  raw/olist/                extracted CSV files (git ignored)
  sample/olist/             committed 5,000 order sample used by CI and the quick start (Phase 1)
```

## Commands

| Command | What it does |
|---|---|
| `make data` | Download Olist, load the raw schema, build dbt models and run tests |
| `make data-sample` | Load the committed sample only, then build dbt (no Kaggle account needed) |
| `uv run --package governed-analytics-scripts python scripts/build_sample.py` | Rebuild the sample from `raw/olist` |

### Getting the full dataset

1. Create a free Kaggle account and an API token at https://www.kaggle.com/settings.
2. Set `KAGGLE_USERNAME` and `KAGGLE_KEY` in `.env`, or place `kaggle.json` in `~/.kaggle/`.
3. Run `make data`.

Without credentials the download script exits with instructions. You can also download the archive in the browser,
place it at `dataset/downloads/brazilian-ecommerce.zip`, and run `make data` again.

### Integrity

The archive checksum is recorded on the first download and verified on every later run. A mismatch stops the
pipeline. Update `checksums.sha256` only after you have verified a new dataset release.

## Known data quirks (handled in dbt staging)

- `customer_id` changes per order. `customer_unique_id` identifies the real customer.
- `product_name_lenght` and `product_description_lenght` are misspelled in the source and renamed in staging.
- Some product categories have no English translation. They fall back to Portuguese and are flagged `untranslated`.
- Products without a category are labelled `unknown` and flagged `missing`.
- Geolocation has many rows per zip prefix. The median coordinates per prefix are used.
- Orders can have several reviews. The latest answered review is kept.
- Orders can have several payments. Totals are kept per order and the primary payment type is the largest payment.
- Delivery measures exist only for delivered orders.
- Currency is Brazilian Real (BRL).
