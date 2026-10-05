"""Rule based resolver. Answers without an LLM call when the question is clear.

The resolver matches business vocabulary (metrics, dimensions and filter values) as whole words,
longest term first, and parses time phrases against the dataset reference date. It resolves a
question only when exactly one governed metric is recognised. Anything else is returned as
unresolved so that the LLM plan step can handle it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import ValidationError

from app.semantic.plan import TIME_DIMENSION, Filter, MetricPlan
from app.semantic.time_parser import parse_time_phrase
from app.semantic.vocabulary import Vocabulary

Status = Literal["resolved", "multi_metric", "no_match", "invalid"]

GRAIN_WORDS: dict[str, str] = {
    "daily": "day",
    "day": "day",
    "weekly": "week",
    "week": "week",
    "monthly": "month",
    "month": "month",
    "quarterly": "quarter",
    "quarter": "quarter",
    "yearly": "year",
    "year": "year",
}
GRAIN_ADJECTIVES = frozenset({"daily", "weekly", "monthly", "quarterly", "yearly"})
TREND_WORDS = ("over time", "trend", "trends")
GROUP_PREFIX = re.compile(r"\b(by|per|across|each)$")
WORD = re.compile(r"[a-z]+")

CONFIDENCE_THRESHOLD = 0.8
HIGH_CONFIDENCE = 0.95
LOW_CONFIDENCE = 0.7
MULTI_METRIC_CONFIDENCE = 0.5
MIN_CONFIDENT_TERM_LENGTH = 4


@dataclass(frozen=True)
class _Term:
    text: str
    kind: Literal["metric", "dimension", "value"]
    target: str
    value: str | None = None


@dataclass(frozen=True)
class _Match:
    start: int
    end: int
    term: _Term


@dataclass(frozen=True)
class Resolution:
    status: Status
    plan: MetricPlan | None = None
    matched_terms: tuple[str, ...] = ()
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"


def normalize(question: str) -> str:
    cleaned = re.sub(r"[^\w\s%'-]", " ", question.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _build_terms(vocabulary: Vocabulary) -> list[_Term]:
    terms: list[_Term] = []
    for definition in vocabulary.metrics.values():
        names = (definition.name.replace("_", " "), definition.label, *definition.synonyms)
        for synonym in names:
            terms.append(_Term(text=normalize(synonym), kind="metric", target=definition.name))
    for dimension, synonyms in vocabulary.dimension_synonyms.items():
        for synonym in synonyms:
            terms.append(_Term(text=normalize(synonym), kind="dimension", target=dimension))
    for mapping in vocabulary.values:
        for synonym in mapping.synonyms:
            terms.append(
                _Term(
                    text=normalize(synonym),
                    kind="value",
                    target=mapping.dimension,
                    value=mapping.value,
                )
            )
    unique: dict[tuple[str, str, str, str | None], _Term] = {}
    for term in terms:
        if term.text:
            unique.setdefault((term.text, term.kind, term.target, term.value), term)
    return sorted(unique.values(), key=lambda term: len(term.text), reverse=True)


def _find_matches(text: str, terms: list[_Term]) -> list[_Match]:
    """Longest term first. A character of the question can belong to one match only."""
    taken = [False] * len(text)
    matches: list[_Match] = []
    for term in terms:
        pattern = re.compile(rf"(?<!\w){re.escape(term.text)}(?!\w)")
        for found in pattern.finditer(text):
            start, end = found.span()
            if any(taken[start:end]):
                continue
            for index in range(start, end):
                taken[index] = True
            matches.append(_Match(start=start, end=end, term=term))
    return sorted(matches, key=lambda match: match.start)


def _is_grouped(text: str, start: int) -> bool:
    """True when the term follows a grouping word such as "by", "per" or "across"."""
    return GROUP_PREFIX.search(text[:start].rstrip()) is not None


def _time_grain(text: str, match: _Match) -> str:
    """Grain named by the matched word, or by the first grain word in the question."""
    candidates = [
        match.term.text,
        *WORD.findall(text[match.start : match.end]),
        *WORD.findall(text),
    ]
    for word in candidates:
        if word in GRAIN_WORDS:
            return GRAIN_WORDS[word]
    return "month"


def resolve(question: str, vocabulary: Vocabulary, data_as_of: date) -> Resolution:
    text = normalize(question)
    if not text:
        return Resolution(status="no_match", reasons=["empty question"])

    matches = _find_matches(text, _build_terms(vocabulary))
    metric_matches = [match for match in matches if match.term.kind == "metric"]
    metric_names = list(dict.fromkeys(match.term.target for match in metric_matches))
    matched_terms = tuple(match.term.text for match in matches)

    if not metric_names:
        return Resolution(
            status="no_match", matched_terms=matched_terms, reasons=["no metric term"]
        )
    if len(metric_names) > 1:
        return Resolution(
            status="multi_metric",
            matched_terms=matched_terms,
            confidence=MULTI_METRIC_CONFIDENCE,
            reasons=[f"several metrics matched: {', '.join(metric_names)}"],
        )

    metric_term = metric_matches[0].term.text
    confidence = (
        HIGH_CONFIDENCE if len(metric_term) >= MIN_CONFIDENT_TERM_LENGTH else LOW_CONFIDENCE
    )
    group_by: list[str] = []
    filters: list[Filter] = []

    for match in matches:
        if match.term.kind == "dimension":
            if match.term.target == TIME_DIMENSION:
                if _is_grouped(text, match.start) or match.term.text in GRAIN_ADJECTIVES:
                    group_by.append(f"{TIME_DIMENSION}__{_time_grain(text, match)}")
            elif _is_grouped(text, match.start):
                group_by.append(match.term.target)
        elif match.term.kind == "value" and match.term.value is not None:
            filters.append(
                Filter(dimension=match.term.target, operator="=", value=match.term.value)
            )

    has_time_group = any(name.startswith(f"{TIME_DIMENSION}__") for name in group_by)
    if any(marker in text for marker in TREND_WORDS) and not has_time_group:
        group_by.append(f"{TIME_DIMENSION}__month")

    parsed_time = parse_time_phrase(text, data_as_of)
    if confidence < CONFIDENCE_THRESHOLD:
        return Resolution(
            status="no_match",
            matched_terms=matched_terms,
            confidence=confidence,
            reasons=["metric term too short to resolve with confidence"],
        )
    try:
        plan = MetricPlan(
            metrics=[metric_names[0]],
            group_by=list(dict.fromkeys(group_by)),
            filters=filters,
            time_window=parsed_time.window if parsed_time else None,
        )
    except ValidationError as error:
        return Resolution(
            status="invalid",
            matched_terms=matched_terms,
            confidence=confidence,
            reasons=[str(error.errors()[0]["msg"])],
        )
    return Resolution(
        status="resolved",
        plan=plan,
        matched_terms=matched_terms,
        confidence=confidence,
        reasons=[f"metric {metric_names[0]} matched on '{metric_term}'"],
    )
