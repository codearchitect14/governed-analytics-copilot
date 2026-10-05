"""Business vocabulary and metric definitions loaded from the seed files and the dbt project."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    label: str
    description: str
    synonyms: tuple[str, ...]


@dataclass(frozen=True)
class ValueMapping:
    dimension: str
    value: str
    synonyms: tuple[str, ...]


@dataclass(frozen=True)
class Vocabulary:
    metrics: dict[str, MetricDefinition]
    dimension_synonyms: dict[str, tuple[str, ...]]
    values: list[ValueMapping] = field(default_factory=list)

    def metric_names(self) -> set[str]:
        return set(self.metrics)

    def dimension_names(self) -> set[str]:
        return set(self.dimension_synonyms)


def _as_tuple(items: Any) -> tuple[str, ...]:
    return tuple(str(item).strip().lower() for item in (items or []) if str(item).strip())


def load_metric_definitions(metrics_yml: Path) -> dict[str, MetricDefinition]:
    """Read label, description and synonyms for every metric in the dbt metrics file."""
    document = yaml.safe_load(metrics_yml.read_text(encoding="utf-8")) or {}
    definitions: dict[str, MetricDefinition] = {}
    for entry in document.get("metrics", []):
        name = str(entry["name"])
        meta = entry.get("meta") or {}
        definitions[name] = MetricDefinition(
            name=name,
            label=str(entry.get("label", name)),
            description=str(entry.get("description", "")).strip(),
            synonyms=_as_tuple(meta.get("synonyms")),
        )
    return definitions


def load_vocabulary(synonyms_yml: Path, metrics_yml: Path) -> Vocabulary:
    """Combine the seed synonyms with the metric definitions from the semantic layer.

    Metric synonyms from the seed file are merged with the synonyms declared in dbt `meta`.
    """
    seed = yaml.safe_load(synonyms_yml.read_text(encoding="utf-8")) or {}
    metrics = load_metric_definitions(metrics_yml)

    for metric_name, terms in (seed.get("metrics") or {}).items():
        if metric_name not in metrics:
            raise ValueError(f"synonyms reference unknown metric {metric_name!r}")
        existing = metrics[metric_name]
        merged = tuple(dict.fromkeys((*existing.synonyms, *_as_tuple(terms))))
        metrics[metric_name] = MetricDefinition(
            name=existing.name,
            label=existing.label,
            description=existing.description,
            synonyms=merged,
        )

    dimension_synonyms = {
        str(name): _as_tuple(terms) for name, terms in (seed.get("dimensions") or {}).items()
    }

    values: list[ValueMapping] = []
    for dimension, mapping in (seed.get("values") or {}).items():
        for value, terms in mapping.items():
            values.append(
                ValueMapping(
                    dimension=str(dimension),
                    value=str(value),
                    synonyms=(*_as_tuple(terms), str(value).lower()),
                )
            )
    return Vocabulary(metrics=metrics, dimension_synonyms=dimension_synonyms, values=values)
