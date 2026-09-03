"""What the executor returns: measured numbers, with their provenance.

Commit 24 produces evidence, not prose. Nothing here writes a sentence, ranks
an insight or calls a movement good — the answer generator in Commit 25 does
that, and it can only do it honestly if the evidence tells it what kind of
number it is holding.

Three invariants the whole design turns on:

* **Money stays integer pence.** Row values are carried as-is from the services
  that produced them, so nothing rounds to a float on the way out.
* **Null means undefined, never zero.** A share of an empty period, a lift with
  no denominator and an average selling price for a product with no net units
  are all null. A generator that renders null as "0%" is stating a fact that was
  never measured, so nulls survive to the boundary intact.
* **A forecast is never a fact.** Predicted rows are tagged `forecast`, carry
  the method and the error that method actually made on unseen days, and say
  which day real data stopped.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.nlq.operations import Operation

#: Reused verbatim from the analytics schemas so the boundary rule is stated
#: identically wherever money appears.
PENCE = "Integer minor units (pence). Never a float."


class EvidenceKind(str, Enum):
    """Where a number came from. Three values, on purpose.

    A richer taxonomy was considered and rejected: the only distinction that
    changes how a sentence may be written is whether the number was recorded,
    computed from recorded numbers, or predicted. Anything finer would be
    metadata nobody acts on.
    """

    #: Aggregated from orders that actually happened. A historical fact.
    MEASURED = "measured"
    #: Arithmetic over measured quantities — a difference, a share, a rate, a
    #: percentage change. True given the inputs, but not itself a record.
    DERIVED = "derived"
    #: Model output for days that have not happened. Not a fact, and must never
    #: be described as one.
    FORECAST = "forecast"


class EvidenceStatus(str, Enum):
    """Whether the request could be answered, and if not, why.

    Unresolvable product references are outcomes, not errors: a model that
    asked about "Latte" when the catalogue holds three of them needs the
    candidate list back so it can ask again. Raising an exception would throw
    that information away.
    """

    OK = "ok"
    #: The product name matched more than one catalogue entry. `candidates` is
    #: populated; no analytics query was executed.
    AMBIGUOUS_PRODUCT = "ambiguous_product"
    #: The product name or id matched nothing. No analytics query was executed.
    UNKNOWN_PRODUCT = "unknown_product"
    #: Too little imported history to forecast. No prediction was produced.
    INSUFFICIENT_HISTORY = "insufficient_history"


class Period(BaseModel):
    """An inclusive local calendar range."""

    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date
    days: int = Field(description="Inclusive length in local calendar days.")


class ResolvedProduct(BaseModel):
    """A catalogue entry, identified canonically.

    `product_id` is the identifier every downstream query uses. Name and
    variation ride along so an answer can name the product without a second
    lookup.
    """

    model_config = ConfigDict(frozen=True)

    product_id: int
    name: str
    variation: str = Field(description='Price point; "" when the item has none.')
    kind: str


class ProductResolutionEvidence(BaseModel):
    """How a product reference in the request became a product id."""

    model_config = ConfigDict(frozen=True)

    requested_name: str | None = Field(
        default=None, description="Echo of the name asked for, as data."
    )
    requested_variation: str | None = None
    requested_product_id: int | None = None
    resolved: ResolvedProduct | None = None
    candidates: list[ResolvedProduct] = Field(
        default_factory=list,
        description=(
            "Populated only when the reference was ambiguous. Every catalogue "
            "entry that matched, so the caller can choose explicitly rather "
            "than having one guessed for it."
        ),
    )


class ForecastProvenance(BaseModel):
    """Everything needed to state a prediction honestly.

    Present only on forecast evidence, and its presence is itself the signal
    that the rows are predictions.
    """

    model_config = ConfigDict(frozen=True)

    method: str = Field(description="The forecasting method that produced the rows.")
    trained_through: date = Field(
        description=(
            "Last day of OBSERVED data. Every row is dated after this, and "
            "none of them is a record of anything."
        )
    )
    forecast_start: date
    forecast_end: date
    horizon_days: int
    unit: str = Field(description="What the predicted values count.")
    historical_wape_percent: float | None = Field(
        default=None,
        description=(
            "Error this method made on days it had never seen, under "
            "rolling-origin backtesting. Measured error, NOT a confidence "
            "interval for these particular predictions. Null when the "
            "evaluated period contained no trade."
        ),
    )
    historical_mae: float | None = Field(
        default=None, description="Mean absolute error over the same backtest."
    )
    backtest_folds: int = Field(
        description="Independent forecast origins the metrics were pooled over."
    )
    backtest_horizon_days: int


class ResultLimits(BaseModel):
    """What was capped, and by how much. Never silent.

    `available_rows` is the number that qualified before the limit, when the
    operation can know it. When `truncated` is true the caller is holding a
    top-N, not a complete set, and any statement it makes about "all products"
    would be false.
    """

    model_config = ConfigDict(frozen=True)

    returned_rows: int
    applied_limit: int | None = Field(
        default=None, description="The limit actually used for this request."
    )
    maximum_rows: int | None = Field(
        default=None,
        description="Hard ceiling for this operation, regardless of what was asked.",
    )
    available_rows: int | None = Field(
        default=None,
        description="Rows that qualified before limiting. Null when not knowable.",
    )
    truncated: bool = Field(
        default=False, description="True when rows were withheld by the limit."
    )


class EvidenceBundle(BaseModel):
    """The deterministic result of one structured request.

    Rows are plain JSON-ready mappings rather than twelve bespoke row models.
    Twelve operations produce twelve genuinely different shapes, and the thing
    a consumer needs is not a Python type but the answer to "what is this
    number and where did it come from" — which `field_provenance` and `units`
    give for every field, uniformly.
    """

    model_config = ConfigDict(frozen=True)

    operation: Operation
    status: EvidenceStatus = EvidenceStatus.OK

    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "The request as executed, after defaults and product resolution. "
            "What the numbers below are actually about."
        ),
    )

    period: Period | None = Field(
        default=None, description="Measured period. Null for forecasts."
    )
    comparison_period: Period | None = Field(
        default=None,
        description=(
            "The equal-length period immediately preceding `period`, when the "
            "operation compares. Any `previous_*` field is measured over this."
        ),
    )

    rows: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "The evidence. Money is integer pence; undefined ratios are null "
            "rather than zero."
        ),
    )
    totals: dict[str, Any] = Field(
        default_factory=dict,
        description="Period-level figures the rows are a breakdown of.",
    )

    field_provenance: dict[str, EvidenceKind] = Field(
        default_factory=dict,
        description=(
            "Per-field: measured, derived or forecast. Covers keys in both "
            "`rows` and `totals`."
        ),
    )
    units: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Per-field unit, so a consumer never has to infer pence from a "
            "field name."
        ),
    )

    limits: ResultLimits | None = None
    forecast: ForecastProvenance | None = Field(
        default=None,
        description="Present only on forecast evidence. Its presence means the "
        "rows are predictions.",
    )
    product_resolution: ProductResolutionEvidence | None = Field(
        default=None,
        description="Present when the request named a product.",
    )

    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Limitations that materially affect how the evidence may be "
            "described: truncation, undefined ratios, an empty period, or the "
            "fact that rows are predictions."
        ),
    )
