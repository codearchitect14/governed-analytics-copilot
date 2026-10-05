"""Catalog index: metric, dimension and few shot example embeddings stored in pgvector.

The index lives in the `app` schema (owned by app_rw) and is rebuilt in one transaction, so a
failed rebuild leaves the previous index in place.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import psycopg
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.semantic.vocabulary import Vocabulary

EntryKind = Literal["metric", "dimension", "example"]


@dataclass(frozen=True)
class CatalogEntry:
    kind: EntryKind
    name: str
    content: str


@dataclass(frozen=True)
class SearchHit:
    kind: str
    name: str
    content: str
    score: float


def _readable(name: str) -> str:
    return name.replace("__", " ").replace("_", " ")


def build_entries(vocabulary: Vocabulary, examples: Sequence[dict[str, Any]]) -> list[CatalogEntry]:
    """Turn metric definitions, dimension vocabulary and examples into indexable text."""
    entries: list[CatalogEntry] = []
    for definition in vocabulary.metrics.values():
        also = ", ".join(definition.synonyms)
        text = f"{definition.label}. {definition.description} Also called: {also}."
        entries.append(CatalogEntry("metric", definition.name, text.strip()))

    for dimension, synonyms in vocabulary.dimension_synonyms.items():
        also = ", ".join(synonyms)
        entries.append(
            CatalogEntry("dimension", dimension, f"{_readable(dimension)}. Also called: {also}.")
        )

    for example in examples:
        entries.append(CatalogEntry("example", str(example["id"]), str(example["question"])))
    return entries


def load_examples(path: Path) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            examples.append(json.loads(line))
    return examples


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def replace_index(
    connection: psycopg.Connection[tuple[Any, ...]],
    entries: Sequence[CatalogEntry],
    vectors: Sequence[Sequence[float]],
    model: str,
) -> int:
    if len(entries) != len(vectors):
        raise ValueError("every catalog entry needs exactly one vector")
    with connection.transaction(), connection.cursor() as cursor:
        # The table and its HNSW index are created by the database migrations.
        cursor.execute("DELETE FROM app.catalog_embeddings")
        for entry, vector in zip(entries, vectors, strict=True):
            cursor.execute(
                """
                INSERT INTO app.catalog_embeddings (kind, name, content, model, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                """,
                (entry.kind, entry.name, entry.content, model, _vector_literal(vector)),
            )
    return len(entries)


def search(
    connection: Connection,
    query_vector: Sequence[float],
    limit: int = 3,
    kinds: Sequence[EntryKind] | None = None,
) -> list[SearchHit]:
    """Nearest catalog entries by cosine similarity. The filter on kind is bound, not concatenated."""
    literal = _vector_literal(query_vector)
    if kinds:
        rows = connection.execute(
            text(
                """
                SELECT kind, name, content, 1 - (embedding <=> CAST(:v AS vector)) AS score
                FROM app.catalog_embeddings
                WHERE kind = ANY(:kinds)
                ORDER BY embedding <=> CAST(:v AS vector)
                LIMIT :limit
                """
            ),
            {"v": literal, "kinds": list(kinds), "limit": limit},
        ).all()
    else:
        rows = connection.execute(
            text(
                """
                SELECT kind, name, content, 1 - (embedding <=> CAST(:v AS vector)) AS score
                FROM app.catalog_embeddings
                ORDER BY embedding <=> CAST(:v AS vector)
                LIMIT :limit
                """
            ),
            {"v": literal, "limit": limit},
        ).all()
    return [
        SearchHit(kind=str(kind), name=str(name), content=str(content), score=float(str(score)))
        for kind, name, content, score in rows
    ]
