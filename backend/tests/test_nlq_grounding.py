"""Grounding: what the answer stage is given, and what it is told about it.

Grounding is enforced by CONTROLLING THE INPUT, not by inspecting the output.
These tests assert the enforceable half: the answer stage receives the
evidence and nothing else, provenance and units travel with every number,
nulls arrive as nulls, and the meaning of WAPE is attached to the WAPE.

There is deliberately no test asserting that generated prose is truthful. A
checker that extracts numbers from English and matches them back is unreliable
in both directions, and one that is wrong either blocks correct answers or
confers false confidence. What the system offers instead is auditability: the
evidence is returned with the answer, so a reader can check it.
"""

from __future__ import annotations

import json
import warnings
from datetime import date, timedelta

import pytest

from app.nlq.evidence import EvidenceKind
from app.nlq.prompts import (
    ANSWER_SYSTEM,
    NULL_MEANING,
    PLANNER_SYSTEM,
    WAPE_MEANING,
    answer_user_message,
    evidence_payload,
)
from tests.conftest import FakeLLM, plan_json, step

warnings.filterwarnings("ignore")

AUGUST = {"start_date": "2026-08-01", "end_date": "2026-08-31"}


@pytest.fixture
def trading(make_sale):
    make_sale("2026-08-03T09:00", [("The Big Breakfast", "Regular", 1, 950),
                                   ("Caffe Latte", "Regular", 1, 365)])
    make_sale("2026-08-04T12:00", [("The Big Breakfast", "Regular", 2, 1900)])


def evidence_for(question_service, llm_steps, trading_fixture=None):
    llm = FakeLLM(structured=[plan_json(*llm_steps)], text=["answer"])
    question_service(llm).ask("A question")
    return llm.text_calls[0]


# --- what the answer stage receives ------------------------------------------


def test_the_answer_stage_receives_the_evidence(question_service, trading):
    call = evidence_for(question_service, [step("overview", "x", **AUGUST)])
    assert '"net_sales_pence": 3215' in call["user"]
    assert '"operation": "overview"' in call["user"]


def test_the_answer_stage_receives_no_catalogue_and_no_date_context(
    question_service, trading
):
    """Its factual world is the evidence. Anything else is a second source it
    could quote from without support."""
    call = evidence_for(question_service, [step("overview", "x", **AUGUST)])

    assert "PRODUCT CATALOGUE" not in call["user"]
    assert "latest_observed_date" not in call["user"]
    assert "today:" not in call["user"]


def test_the_planner_purpose_is_not_shown_to_the_answer_stage(
    question_service, trading
):
    """The planner's own words are an audit note, not a finding. Passing them
    on would let free text the model wrote earlier be read as evidence."""
    call = evidence_for(
        question_service,
        [step("overview", "REVENUE DOUBLED THIS MONTH", **AUGUST)],
    )
    assert "REVENUE DOUBLED" not in call["user"]


def test_the_answer_stage_receives_no_tools_and_no_schema(question_service, trading):
    llm = FakeLLM(
        structured=[plan_json(step("overview", "x", **AUGUST))], text=["ok"]
    )
    question_service(llm).ask("How did we do?")

    # complete_text takes no schema and no tool parameter: the port does not
    # have one to give.
    assert set(llm.text_calls[0]) == {"system", "user", "max_tokens", "effort"}


def test_the_question_reaches_the_answer_stage_delimited(question_service, trading):
    llm = FakeLLM(
        structured=[plan_json(step("overview", "x", **AUGUST))], text=["ok"]
    )
    question_service(llm).ask("How did we perform?")

    user = llm.text_calls[0]["user"]
    assert "<user_question>\nHow did we perform?\n</user_question>" in user
    # Evidence first, question after: facts are in view before the ask.
    assert user.index("EVIDENCE") < user.index("<user_question>")


# --- provenance and units travel with the numbers ----------------------------


def test_every_field_carries_its_provenance(question_service, trading):
    call = evidence_for(
        question_service, [step("product_performance", "x", **AUGUST)]
    )
    payload = _payload(call["user"])[0]

    assert payload["field_provenance"]["net_sales_pence"] == "measured"
    assert payload["field_provenance"]["share_of_net_sales_percent"] == "derived"
    assert payload["units"]["net_sales_pence"] == "pence"


def test_measured_and_derived_are_distinguishable_in_the_payload(
    question_service, trading
):
    call = evidence_for(question_service, [step("product_movers", "x", **AUGUST)])
    provenance = _payload(call["user"])[0]["field_provenance"]

    assert provenance["current_net_sales_pence"] == "measured"
    assert provenance["net_sales_percent_change"] == "derived"


# --- nulls stay undefined ----------------------------------------------------


def test_a_null_ratio_reaches_the_model_as_null_not_zero(question_service, make_sale):
    from app.models.enums import OrderEventType

    make_sale("2026-08-05T09:00", [("Flat White", "", 1, 300)])
    make_sale("2026-08-06T09:00", [("Flat White", "", -1, -300)],
              event_type=OrderEventType.REFUND)

    call = evidence_for(
        question_service, [step("product_performance", "x", **AUGUST)]
    )
    row = _payload(call["user"])[0]["rows"][0]

    assert row["average_selling_price_pence"] is None
    assert row["share_of_net_sales_percent"] is None
    assert '"average_selling_price_pence": 0' not in call["user"]


def test_the_null_rule_is_attached_to_every_bundle(question_service, trading):
    """Stated beside the data, not only once in a distant system prompt."""
    call = evidence_for(question_service, [step("overview", "x", **AUGUST)])
    assert _payload(call["user"])[0]["null_values_mean"] == NULL_MEANING
    assert "UNDEFINED quantity, not zero" in NULL_MEANING


def test_the_answer_prompt_forbids_rendering_null_as_zero():
    assert "NULLS ARE UNDEFINED, NOT ZERO" in ANSWER_SYSTEM
    assert 'never "0"' in ANSWER_SYSTEM


# --- money -------------------------------------------------------------------


def test_pence_reach_the_model_as_integers(question_service, trading):
    call = evidence_for(question_service, [step("overview", "x", **AUGUST)])
    totals = _payload(call["user"])[0]["totals"]

    assert totals["net_sales_pence"] == 3215
    assert isinstance(totals["net_sales_pence"], int)


# --- forecasts are never facts -----------------------------------------------


WEEK_SHAPE = [1000, 1100, 1200, 1300, 2000, 4000, 3800]


@pytest.fixture
def year_of_trade(make_order):
    start = date(2025, 9, 1)
    for index in range(200):
        day = start + timedelta(days=index)
        make_order(f"{day.isoformat()}T12:00", net=WEEK_SHAPE[index % 7], units=1)
    return start + timedelta(days=199)


def test_forecast_evidence_is_marked_as_entirely_predicted(
    question_service, year_of_trade
):
    call = evidence_for(
        question_service, [step("forecast", "what is coming", horizon_days=14)]
    )
    payload = _payload(call["user"])[0]

    assert payload["all_rows_are_predictions"] is True
    assert payload["field_provenance"]["predicted_value"] == "forecast"
    assert payload["forecast"]["trained_through"] == year_of_trade.isoformat()
    assert any("PREDICTIONS" in w for w in payload["warnings"])


def test_the_meaning_of_wape_travels_with_the_number(
    question_service, year_of_trade
):
    """Mechanical: the note is present whenever the field is, so it cannot be
    separated from it by a long prompt."""
    call = evidence_for(question_service, [step("forecast", "x", horizon_days=7)])
    forecast = _payload(call["user"])[0]["forecast"]

    assert "historical_wape_percent" in forecast
    assert forecast["historical_wape_percent_meaning"] == WAPE_MEANING
    assert "NOT accuracy" in WAPE_MEANING
    assert "NOT confidence" in WAPE_MEANING


def test_the_answer_prompt_forbids_converting_wape_into_accuracy():
    assert "historical_wape_percent is the error" in ANSWER_SYSTEM
    assert '"88% accurate"' in ANSWER_SYSTEM
    assert "do not invent a range" in ANSWER_SYSTEM


def test_a_forecast_is_flagged_from_the_evidence_not_the_prose(
    question_service, year_of_trade
):
    """So a consumer can mark a prediction even if the wording failed to."""
    llm = FakeLLM(
        structured=[plan_json(step("forecast", "x", horizon_days=7))],
        text=["Sales were £42 next week."],   # deliberately stated as fact
    )
    result = question_service(llm).ask("What is coming?")
    assert result.contains_forecast is True


def test_history_only_evidence_is_not_flagged_as_forecast(
    question_service, trading
):
    llm = FakeLLM(
        structured=[plan_json(step("overview", "x", **AUGUST))], text=["ok"]
    )
    assert question_service(llm).ask("How did we do?").contains_forecast is False


# --- limitations reach the reader --------------------------------------------


def test_truncation_warnings_are_passed_through_to_the_model_and_the_caller(
    question_service, make_sale
):
    for index in range(20):
        make_sale("2026-08-01T09:00", [(f"Item {index:02d}", "", 1, 100 + index)])

    llm = FakeLLM(
        structured=[plan_json(step("product_performance", "x", limit=3, **AUGUST))],
        text=["ok"],
    )
    result = question_service(llm).ask("Top products?")

    assert any("Truncated" in w for w in result.warnings)
    assert "Truncated" in llm.text_calls[0]["user"]
    assert _payload(llm.text_calls[0]["user"])[0]["limits"]["truncated"] is True


def test_the_answer_prompt_forbids_claims_beyond_the_evidence():
    for rule in (
        "GROUNDING",
        "Do not estimate, extrapolate",
        "CHANGE IS NOT CAUSE",
        "Do not recommend price changes",
        "state plainly which part it does not",
    ):
        assert rule in ANSWER_SYSTEM


def test_the_planner_prompt_permits_declining():
    assert "set answerable to false" in PLANNER_SYSTEM
    # Whitespace-normalised: the prompt is hard-wrapped, so a phrase spanning
    # a line break is not a literal substring of it.
    flat = " ".join(PLANNER_SYSTEM.split())
    assert "That is a correct outcome" in flat
    assert "Choosing a loosely related operation so that something comes back is not" in flat


# --- helper ------------------------------------------------------------------


def _payload(user_message: str) -> list[dict]:
    """Pull the evidence JSON back out of the message the model was given."""
    start = user_message.index("[")
    end = user_message.rindex("]") + 1
    return json.loads(user_message[start:end])
