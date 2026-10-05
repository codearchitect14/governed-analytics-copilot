"""Build the catalog embedding index from the semantic seed files and the dbt metrics file.

Usage (from the repository root):
    uv run --package governed-analytics-backend python -m app.semantic.index_catalog

The database URL is read from APP_DATABASE_URL (role app_rw) unless --database-url is given.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg

from app.semantic import catalog
from app.semantic.embeddings import MODEL_NAME, Embedder
from app.semantic.vocabulary import load_vocabulary

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = REPO_ROOT / "dataset" / "semantic_seed"
METRICS_YML = REPO_ROOT / "warehouse" / "dbt_project" / "models" / "semantic" / "metrics.yml"


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", default=os.environ.get("APP_DATABASE_URL", ""))
    parser.add_argument("--synonyms", type=Path, default=SEED_DIR / "synonyms.yml")
    parser.add_argument("--metrics", type=Path, default=METRICS_YML)
    parser.add_argument("--examples", type=Path, default=SEED_DIR / "few_shot_examples.jsonl")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.database_url:
        print("APP_DATABASE_URL is not set.", file=sys.stderr)
        return 2

    vocabulary = load_vocabulary(args.synonyms, args.metrics)
    examples = catalog.load_examples(args.examples)
    entries = catalog.build_entries(vocabulary, examples)

    embedder = Embedder()
    vectors = embedder.embed_documents([entry.content for entry in entries])

    with psycopg.connect(args.database_url) as connection:
        count = catalog.replace_index(connection, entries, vectors, MODEL_NAME)

    print(f"Indexed {count} catalog entries with {MODEL_NAME}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
