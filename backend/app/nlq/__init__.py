"""Natural-language query foundation (M7).

This package is the *safe substrate* an LLM will be given in Commit 25. It
contains no model call, no prompt and no natural-language parsing.

The single architectural rule, stated once here and enforced everywhere below:

    THE LANGUAGE MODEL DOES NOT QUERY THE DATABASE.

What a model may produce is a `AnalyticsRequest` — a strict, closed,
discriminated union of validated parameter objects. What it gets back is an
`EvidenceBundle` of measured numbers with their provenance. Between the two
sits `AnalyticsExecutor`, which dispatches to the M3-M6 services that already
own every metric definition in this system.

There is deliberately no `execute_sql`, no `run_query`, no table or column
selector, and no generic fallback operation. A request naming an operation
outside the enum, or carrying a field outside its schema, fails Pydantic
validation before a session is ever opened.
"""

from app.nlq.evidence import EvidenceBundle, EvidenceKind, EvidenceStatus
from app.nlq.executor import AnalyticsExecutor
from app.nlq.operations import Operation
from app.nlq.requests import AnalyticsRequest
from app.nlq.resolution import ProductResolver

__all__ = [
    "AnalyticsExecutor",
    "AnalyticsRequest",
    "EvidenceBundle",
    "EvidenceKind",
    "EvidenceStatus",
    "Operation",
    "ProductResolver",
]
