"""Turning a product name from a question into a canonical product id.

A question says "Big Breakfast". The database says 142. Everything between
those two is this module, and the whole of it is built on one refusal: it will
not guess.

WHAT IT DOES MATCH
    Case: "big breakfast" and "BIG BREAKFAST" both find "Big Breakfast".
    Surrounding and repeated whitespace: " Big  Breakfast " finds it too.
    A variation when one is given: name + "Large" narrows to that price point.

WHAT IT DELIBERATELY DOES NOT MATCH
    Prefixes, substrings, wildcards, edit distance, phonetics, embeddings.
    Every one of them can quietly return the wrong product, and a wrong product
    produces a confident, fluent, wrong answer — which is worse than no answer.
    "Latte" therefore does not match "Caffe Latte", and is reported as unknown.

AMBIGUITY IS AN ANSWER
    "Caffe Latte" with no variation matches Regular and Large. That is not an
    error and it is not a coin toss: it comes back as a candidate list, so the
    caller asks again with the variation it meant. Choosing the bigger seller,
    or the lower id, would be a silent decision about what the user asked.

SAFETY
    The name is a VALUE. It is compared inside a SQLAlchemy expression, which
    sends it as a bound parameter; it is never concatenated, formatted or
    interpolated into SQL. A name of "'; DROP TABLE orders; --" is looked up,
    matches nothing, and is reported as unknown — exactly like any other
    product the café does not sell.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Product
from app.nlq.operations import MAX_CANDIDATE_PRODUCTS, MAX_CATALOGUE_PRODUCTS

#: Runs of whitespace, for the conservative normalisation below.
_WHITESPACE = re.compile(r"\s+")

#: The same normalisation, expressed for PostgreSQL. The pattern is a literal
#: owned by this module; only the comparison value is bound.
_SQL_WHITESPACE = r"\s+"


def normalise(value: str) -> str:
    """Trim, collapse internal whitespace, lower-case.

    Conservative by design: it changes only things that cannot alter which
    product a human meant. It does not strip punctuation, drop articles or
    singularise, because "Coffee Bean" and "Coffee Beans" may well be two
    different products at two different prices.
    """
    return _WHITESPACE.sub(" ", value.strip()).lower()


def _normalised(column):
    """`normalise()` as a SQL expression over a column."""
    return func.lower(func.regexp_replace(func.btrim(column), _SQL_WHITESPACE, " ", "g"))


@dataclass(frozen=True)
class ProductMatch:
    product_id: int
    name: str
    variation: str
    kind: str


@dataclass(frozen=True)
class ProductResolution:
    """The outcome. Exactly one of `match` or `candidates` is meaningful."""

    #: "resolved" | "ambiguous" | "not_found"
    status: str
    match: ProductMatch | None = None
    candidates: list[ProductMatch] = field(default_factory=list)

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"


class ProductResolver:
    """Deterministic name -> product id lookup over the existing catalogue.

    One bounded query per resolution. Results are ordered by (name, variation,
    id) so a candidate list is identical across calls.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def by_id(self, product_id: int) -> ProductResolution:
        """The canonical path. An id either exists or it does not."""
        with self._session_factory() as session:
            product = session.get(Product, product_id)
        if product is None:
            return ProductResolution(status="not_found")
        return ProductResolution(status="resolved", match=_match(product))

    def by_name(self, name: str, variation: str | None = None) -> ProductResolution:
        """Case- and whitespace-insensitive exact match on the catalogue.

        `variation` narrows to one price point when given. Omitting it is the
        common case for a natural-language question and is the usual source of
        an ambiguous result.
        """
        target = normalise(name)
        # PostgreSQL text cannot hold a NUL byte, so no catalogue row can
        # contain one and nothing can match. Answering "not found" here rather
        # than sending it is the difference between an answer and a DataError
        # from the driver. `ProductSelector` already rejects control characters
        # at the request boundary; this guards the direct caller too.
        if not target or "\x00" in target:
            return ProductResolution(status="not_found")

        criteria = [_normalised(Product.name) == target]
        if variation is not None:
            criteria.append(_normalised(Product.variation) == normalise(variation))

        with self._session_factory() as session:
            rows = session.execute(
                select(Product)
                .where(*criteria)
                .order_by(Product.name, Product.variation, Product.id)
                # One more than the cap, so "were there more than we show" is
                # answerable without a second count query.
                .limit(MAX_CANDIDATE_PRODUCTS + 1)
            ).scalars().all()

        matches = [_match(p) for p in rows]
        if not matches:
            return ProductResolution(status="not_found")
        if len(matches) == 1:
            return ProductResolution(status="resolved", match=matches[0])
        return ProductResolution(
            status="ambiguous", candidates=matches[:MAX_CANDIDATE_PRODUCTS]
        )


    def catalogue(self, limit: int = MAX_CATALOGUE_PRODUCTS) -> list[ProductMatch]:
        """Every product variation the catalogue holds, bounded and ordered.

        Lives here, on the module that already owns catalogue access, so the
        AI layer still reaches the database through exactly one door.

        This is what lets a planner name "The Big Breakfast" instead of
        guessing "Big Breakfast" — and it strengthens the resolver's refusal
        to guess rather than weakening it. The caller is shown the real names
        up front; matching itself stays exact. Nothing here is a fuzzy
        fallback for a name that was not on the list.

        Names and price points only. No order, customer or financial data.
        """
        with self._session_factory() as session:
            rows = session.execute(
                select(Product)
                .order_by(Product.name, Product.variation, Product.id)
                .limit(limit)
            ).scalars().all()
        return [_match(p) for p in rows]

    def count(self) -> int:
        """How many variations the catalogue holds, for truncation reporting."""
        with self._session_factory() as session:
            return session.execute(
                select(func.count()).select_from(Product)
            ).scalar_one()


def _match(product: Product) -> ProductMatch:
    return ProductMatch(
        product_id=product.id,
        name=product.name,
        variation=product.variation,
        kind=product.kind.value,
    )
