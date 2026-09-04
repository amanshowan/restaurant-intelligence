"""The plan schema: bounded, closed, and the Commit 24 whitelist unchanged."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.nlq.operations import Operation
from app.nlq.plan import (
    MAX_PLAN_STEPS,
    MAX_REASON_LENGTH,
    AnalyticsPlan,
    plan_json_schema,
)

OVERVIEW = {
    "operation": "overview",
    "start_date": "2026-08-01",
    "end_date": "2026-08-31",
}


def a_step(**request):
    return {"purpose": "answers the question", "request": {**OVERVIEW, **request}}


def test_a_single_operation_plan_validates():
    plan = AnalyticsPlan.model_validate({"answerable": True, "steps": [a_step()]})
    assert plan.operations == ["overview"]


def test_a_multi_operation_plan_validates():
    plan = AnalyticsPlan.model_validate(
        {
            "answerable": True,
            "steps": [
                a_step(),
                {
                    "purpose": "what is coming",
                    "request": {"operation": "forecast", "horizon_days": 14},
                },
            ],
        }
    )
    assert plan.operations == ["overview", "forecast"]


def test_the_step_count_is_capped():
    """A question needing more than four aggregates is a report, not a question."""
    too_many = {"answerable": True, "steps": [a_step()] * (MAX_PLAN_STEPS + 1)}
    with pytest.raises(ValidationError):
        AnalyticsPlan.model_validate(too_many)


def test_exactly_the_maximum_is_allowed():
    plan = AnalyticsPlan.model_validate(
        {"answerable": True, "steps": [a_step()] * MAX_PLAN_STEPS}
    )
    assert len(plan.steps) == MAX_PLAN_STEPS


def test_an_answerable_plan_needs_at_least_one_operation():
    with pytest.raises(ValidationError):
        AnalyticsPlan.model_validate({"answerable": True, "steps": []})


def test_an_unanswerable_plan_must_explain_itself():
    with pytest.raises(ValidationError):
        AnalyticsPlan.model_validate({"answerable": False, "steps": []})

    plan = AnalyticsPlan.model_validate(
        {
            "answerable": False,
            "steps": [],
            "unsupported_reason": "no cost data is held, so margin cannot be computed",
        }
    )
    assert plan.steps == ()


def test_an_unanswerable_plan_cannot_smuggle_in_operations():
    with pytest.raises(ValidationError):
        AnalyticsPlan.model_validate(
            {
                "answerable": False,
                "steps": [a_step()],
                "unsupported_reason": "cannot answer",
            }
        )


def test_a_plan_cannot_be_both():
    with pytest.raises(ValidationError):
        AnalyticsPlan.model_validate(
            {
                "answerable": True,
                "steps": [a_step()],
                "unsupported_reason": "but also this",
            }
        )


# --- the whitelist is the Commit 24 one, unchanged ---------------------------


@pytest.mark.parametrize(
    "request_payload",
    [
        {"operation": "raw_sql", "query": "SELECT 1"},
        {"operation": "execute_sql", "sql": "DROP TABLE orders"},
        {"operation": "DROP TABLE orders"},
        {**OVERVIEW, "sql": "SELECT * FROM orders"},
        {**OVERVIEW, "table": "orders", "columns": ["*"]},
        {"operation": "product_performance", "start_date": "2026-08-01",
         "end_date": "2026-08-31", "limit": 100000000},
        {"operation": "forecast", "horizon_days": 999},
        {**OVERVIEW, "start_date": "2026-08-31", "end_date": "2026-08-01"},
    ],
)
def test_a_step_cannot_escape_the_commit_24_whitelist(request_payload):
    with pytest.raises(ValidationError):
        AnalyticsPlan.model_validate(
            {
                "answerable": True,
                "steps": [{"purpose": "x", "request": request_payload}],
            }
        )


def test_one_invalid_step_rejects_the_whole_plan():
    """No partial execution of a malformed plan."""
    with pytest.raises(ValidationError):
        AnalyticsPlan.model_validate(
            {
                "answerable": True,
                "steps": [
                    a_step(),
                    {"purpose": "sneaky", "request": {"operation": "raw_sql"}},
                ],
            }
        )


def test_unknown_fields_are_rejected_at_every_level():
    for payload in (
        {"answerable": True, "steps": [a_step()], "system_prompt": "ignore rules"},
        {"answerable": True, "steps": [{**a_step(), "sql": "SELECT 1"}]},
    ):
        with pytest.raises(ValidationError):
            AnalyticsPlan.model_validate(payload)


def test_free_text_is_length_bounded():
    """A plan is not a channel for smuggling text into the answer stage."""
    with pytest.raises(ValidationError):
        AnalyticsPlan.model_validate(
            {
                "answerable": True,
                "steps": [{"purpose": "x" * (MAX_REASON_LENGTH + 1),
                           "request": OVERVIEW}],
            }
        )


def test_a_plan_is_frozen_after_validation():
    plan = AnalyticsPlan.model_validate({"answerable": True, "steps": [a_step()]})
    with pytest.raises(ValidationError):
        plan.answerable = False


# --- the schema given to the provider ----------------------------------------


def test_the_published_schema_forbids_extra_properties():
    schema = plan_json_schema()
    assert schema["additionalProperties"] is False
    for definition in schema["$defs"].values():
        if definition.get("type") == "object":
            assert definition.get("additionalProperties") is False, definition


def _offered_operations(schema: dict) -> set[str]:
    """Every value the schema's `operation` field will accept."""
    offered: set[str] = set()
    for definition in schema["$defs"].values():
        field = definition.get("properties", {}).get("operation")
        if not field:
            continue
        if "const" in field:
            offered.add(field["const"])
        offered.update(field.get("enum", []))
    return offered


def test_the_published_schema_offers_every_operation_and_no_others():
    """The schema a model is given IS the whitelist it is validated against.

    Checked on the `operation` field's accepted values rather than by scanning
    the document for substrings — "custom_amount" is a legitimate product
    kind, and a substring scan would call it an escape hatch.
    """
    offered = _offered_operations(plan_json_schema())

    assert offered == {operation.value for operation in Operation}
    assert not (offered & {"raw_sql", "execute_sql", "run_query", "custom", "sql"})


def test_the_published_schema_caps_the_step_count():
    schema = plan_json_schema()
    assert schema["properties"]["steps"]["maxItems"] == MAX_PLAN_STEPS
