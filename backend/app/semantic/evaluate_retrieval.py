"""Measure top k retrieval recall of the catalog index on paraphrased metric and dimension mentions.

Mentions are paraphrases that are deliberately not in the synonym list, so a hit shows that the
embedding index generalises beyond the vocabulary.

Usage (after index_catalog has run):
    uv run --package governed-analytics-backend python -m app.semantic.evaluate_retrieval
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine

from app.semantic import catalog
from app.semantic.embeddings import Embedder

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MENTIONS = REPO_ROOT / "dataset" / "semantic_seed" / "retrieval_mentions.jsonl"
TARGET_RECALL = 0.95


@dataclass(frozen=True)
class Mention:
    text: str
    kind: str
    name: str


def load_mentions(path: Path) -> list[Mention]:
    mentions: list[Mention] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            mentions.append(
                Mention(text=record["mention"], kind=record["kind"], name=record["name"])
            )
    return mentions


def recall_at_k(
    mentions: Sequence[Mention], hits_by_mention: dict[str, list[catalog.SearchHit]]
) -> dict[str, float]:
    found: dict[str, list[bool]] = defaultdict(list)
    for mention in mentions:
        hits = hits_by_mention[mention.text]
        matched = any(hit.kind == mention.kind and hit.name == mention.name for hit in hits)
        found[mention.kind].append(matched)
        found["overall"].append(matched)
    return {kind: sum(values) / len(values) for kind, values in found.items()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", default=os.environ.get("APP_DATABASE_URL", ""))
    parser.add_argument("--mentions", type=Path, default=DEFAULT_MENTIONS)
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args(argv)
    if not args.database_url:
        print("APP_DATABASE_URL is not set.", file=sys.stderr)
        return 2

    mentions = load_mentions(args.mentions)
    embedder = Embedder()
    hits_by_mention: dict[str, list[catalog.SearchHit]] = {}
    engine = create_engine(args.database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.connect() as connection:
        for mention in mentions:
            vector = embedder.embed_query(mention.text)
            hits_by_mention[mention.text] = catalog.search(
                connection, vector, limit=args.k, kinds=("metric", "dimension")
            )
    engine.dispose()

    recall = recall_at_k(mentions, hits_by_mention)
    for mention in mentions:
        hits = hits_by_mention[mention.text]
        matched = any(hit.kind == mention.kind and hit.name == mention.name for hit in hits)
        if not matched:
            top = ", ".join(f"{hit.kind}:{hit.name}" for hit in hits)
            print(f"MISS  {mention.kind}:{mention.name}  <- '{mention.text}'  top{args.k}: {top}")

    for kind in ("metric", "dimension", "overall"):
        if kind in recall:
            print(
                f"recall@{args.k} {kind:<10} {recall[kind]:.3f}  ({len(mentions)} mentions total)"
            )
    return 0 if recall["overall"] >= TARGET_RECALL else 1


if __name__ == "__main__":
    sys.exit(main())
