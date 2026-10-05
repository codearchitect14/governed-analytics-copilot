"""Structured LLM calls: plan, SQL fallback and one repair attempt. All outputs are validated."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError

from app.llm.gateway import LLMGateway
from app.llm.prompts import (
    CURRENT_VERSION,
    PLAN_PROMPT_NAME,
    REPAIR_PROMPT_NAME,
    SQL_PROMPT_NAME,
    Prompt,
    load_prompt,
)
from app.llm.providers import LLMRequest, LLMResponse
from app.llm.schemas import PlanOutput, SqlOutput

PLAN_MAX_OUTPUT_TOKENS = 300
SQL_MAX_OUTPUT_TOKENS = 500
JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class StructuredOutputError(Exception):
    """The model did not return valid structured output, even after one repair attempt."""


@dataclass(frozen=True)
class ModelCall:
    """One completed model call with the prompt that produced it, for the audit record."""

    response: LLMResponse
    prompt: Prompt


def _parse_json(text_output: str) -> dict[str, object]:
    candidate = text_output.strip()
    try:
        value: object = json.loads(candidate)
    except json.JSONDecodeError:
        match = JSON_OBJECT.search(candidate)
        if match is None:
            raise StructuredOutputError("no JSON object in the model output") from None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as error:
            raise StructuredOutputError("the model output is not valid JSON") from error
    if not isinstance(value, dict):
        raise StructuredOutputError("the model output is not a JSON object")
    return value


def _call(gateway: LLMGateway, prompt: Prompt, user: str, max_tokens: int) -> ModelCall:
    response = gateway.complete(
        LLMRequest(system=prompt.text, user=user, max_output_tokens=max_tokens)
    )
    return ModelCall(response=response, prompt=prompt)


def plan_question(
    gateway: LLMGateway,
    question: str,
    catalog_context: str,
    data_as_of: date,
) -> tuple[PlanOutput, list[ModelCall]]:
    """Ask for a plan. One repair call is made when the output does not validate."""
    prompt = load_prompt(PLAN_PROMPT_NAME, CURRENT_VERSION)
    user = (
        f"Reference date (data_as_of): {data_as_of.isoformat()}\n"
        f"Catalog:\n{catalog_context}\n"
        f"<question>\n{question}\n</question>"
    )
    first = _call(gateway, prompt, user, PLAN_MAX_OUTPUT_TOKENS)
    try:
        return PlanOutput.model_validate(_parse_json(first.response.text)), [first]
    except (StructuredOutputError, ValidationError) as error:
        repair_user = (
            f"Output that failed: {first.response.text[:1500]}\n"
            f"Error: {_short_error(error)}\n"
            "Return the corrected JSON plan for the same question.\n"
            f"Catalog:\n{catalog_context}\n"
            f"<question>\n{question}\n</question>"
        )
    second = _call(gateway, prompt, repair_user, PLAN_MAX_OUTPUT_TOKENS)
    try:
        return PlanOutput.model_validate(_parse_json(second.response.text)), [first, second]
    except (StructuredOutputError, ValidationError) as final_error:
        raise StructuredOutputError(_short_error(final_error)) from final_error


def generate_sql(gateway: LLMGateway, question: str, schema_text: str) -> tuple[str, ModelCall]:
    prompt = load_prompt(SQL_PROMPT_NAME, CURRENT_VERSION)
    user = f"Tables and columns:\n{schema_text}\n<question>\n{question}\n</question>"
    call = _call(gateway, prompt, user, SQL_MAX_OUTPUT_TOKENS)
    return _sql_from(call), call


def repair_sql(
    gateway: LLMGateway, question: str, schema_text: str, previous_sql: str, error: str
) -> tuple[str, ModelCall]:
    prompt = load_prompt(REPAIR_PROMPT_NAME, CURRENT_VERSION)
    user = (
        f"Tables and columns:\n{schema_text}\n"
        f"Previous SQL:\n{previous_sql[:2000]}\n"
        f"Error: {error[:500]}\n"
        f"<question>\n{question}\n</question>"
    )
    call = _call(gateway, prompt, user, SQL_MAX_OUTPUT_TOKENS)
    return _sql_from(call), call


def _sql_from(call: ModelCall) -> str:
    try:
        parsed = SqlOutput.model_validate(_parse_json(call.response.text))
    except (StructuredOutputError, ValidationError) as error:
        raise StructuredOutputError(_short_error(error)) from error
    return parsed.sql.strip()


def _short_error(error: Exception) -> str:
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        return f"{location}: {first.get('msg', 'invalid')}"[:300]
    return str(error)[:300]
