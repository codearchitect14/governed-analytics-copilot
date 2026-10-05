"""Parse relative time phrases against the dataset reference date (data_as_of).

Olist data ends in 2018, so "last month" must mean the month before the last month of data,
not the month before the system clock. Every window is half open: start <= t < end.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from app.semantic.plan import TimeWindow


@dataclass(frozen=True)
class ParsedTime:
    window: TimeWindow
    phrase: str


def first_of_month(day: date) -> date:
    return day.replace(day=1)


def add_months(day: date, months: int) -> date:
    """First day of the month that is `months` away from the month of `day`."""
    month_index = day.year * 12 + (day.month - 1) + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _quarter_start(day: date) -> date:
    return add_months(day, -((day.month - 1) % 3))


def _window(start: date, end: date, grain: str, phrase: str) -> ParsedTime:
    return ParsedTime(TimeWindow(start=start, end=end, grain=grain), phrase)  # type: ignore[arg-type]


# A rule takes the lowercased question and the reference date. It returns a window when it matches.
Rule = Callable[[str, date], ParsedTime | None]


def _last_n_days(text: str, as_of: date) -> ParsedTime | None:
    match = re.search(r"\blast (\d{1,3}) days?\b", text)
    if not match:
        return None
    end = as_of + timedelta(days=1)
    return _window(end - timedelta(days=int(match.group(1))), end, "day", match.group(0))


def _last_n_months(text: str, as_of: date) -> ParsedTime | None:
    match = re.search(r"\blast (\d{1,2}) months?\b", text)
    if not match:
        return None
    start = add_months(first_of_month(as_of), -(int(match.group(1)) - 1))
    return _window(start, add_months(as_of, 1), "month", match.group(0))


def _this_month(text: str, as_of: date) -> ParsedTime | None:
    if not re.search(r"\b(this|current) month\b", text):
        return None
    start = first_of_month(as_of)
    return _window(start, add_months(as_of, 1), "month", "this month")


def _last_month(text: str, as_of: date) -> ParsedTime | None:
    if not re.search(r"\b(last|previous|prior) month\b", text):
        return None
    end = first_of_month(as_of)
    return _window(add_months(end, -1), end, "month", "last month")


def _this_quarter(text: str, as_of: date) -> ParsedTime | None:
    if not re.search(r"\b(this|current) quarter\b", text):
        return None
    start = _quarter_start(as_of)
    return _window(start, add_months(start, 3), "quarter", "this quarter")


def _last_quarter(text: str, as_of: date) -> ParsedTime | None:
    if not re.search(r"\b(last|previous|prior) quarter\b", text):
        return None
    start = add_months(_quarter_start(as_of), -3)
    return _window(start, add_months(start, 3), "quarter", "last quarter")


def _year_to_date(text: str, as_of: date) -> ParsedTime | None:
    if not re.search(r"\b(this|current) year\b|\byear to date\b|\bytd\b", text):
        return None
    start = date(as_of.year, 1, 1)
    return _window(start, as_of + timedelta(days=1), "month", "year to date")


def _last_year(text: str, as_of: date) -> ParsedTime | None:
    if not re.search(r"\b(last|previous|prior) year\b", text):
        return None
    return _window(date(as_of.year - 1, 1, 1), date(as_of.year, 1, 1), "month", "last year")


def _since_month(text: str, as_of: date) -> ParsedTime | None:
    match = re.search(r"\bsince (20\d{2})-(\d{2})\b", text)
    if not match:
        return None
    start = date(int(match.group(1)), int(match.group(2)), 1)
    return _window(start, add_months(as_of, 1), "month", match.group(0))


def _in_year(text: str, as_of: date) -> ParsedTime | None:
    match = re.search(r"\b(?:in|during|for) (20\d{2})\b", text)
    if not match:
        return None
    year = int(match.group(1))
    return _window(date(year, 1, 1), date(year + 1, 1, 1), "month", match.group(0))


RULES: tuple[Rule, ...] = (
    _last_n_days,
    _last_n_months,
    _this_month,
    _last_month,
    _this_quarter,
    _last_quarter,
    _year_to_date,
    _last_year,
    _since_month,
    _in_year,
)


def parse_time_phrase(text: str, data_as_of: date) -> ParsedTime | None:
    """Return the first recognised time window in `text`, or None when there is none."""
    lowered = text.lower()
    for rule in RULES:
        parsed = rule(lowered, data_as_of)
        if parsed is not None:
            return parsed
    return None
