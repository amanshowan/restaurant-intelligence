"""One router, twelve operations, no SQL.

`AnalyticsExecutor.execute` is the only entry point, and it does exactly three
things: resolve any product reference, call the M3-M6 service that owns the
requested metric, and describe what came back.

It is a CONSUMER of the existing analytics and forecasting code, never a second
implementation of it. Revenue, refund handling, channel identity, basket
association and the forecast model are defined once, in the services the HTTP
API already uses, and this module reaches them through the same public methods.
If a definition changes there, it changes here at the same instant — which is
the point. Two implementations of "net sales" would eventually disagree, and
the one an AI quoted would be the one nobody was reading.

Query cost is bounded and set-based: every operation issues a fixed number of
aggregate statements independent of how many products or days it covers,
because the services it calls were built that way.

Determinism: no clock, no randomness, no sampling. The same request against the
same database state produces byte-identical evidence, which is what lets Commit
25's language layer be tested against fixed evidence.
"""

from __future__ import annotations

from typing import Any, Callable

from app.analytics.products import DEFAULT_KINDS
from app.analytics.baskets import DEFAULT_KINDS as BASKET_DEFAULT_KINDS
from app.analytics.service import (
    AnalyticsService,
    MovementStatus,
    WEEKDAY_NAMES,
    previous_window,
)
from app.analytics.windows import QueryWindow
from app.forecasting.series import SeriesIntegrityError
from app.forecasting.service import ForecastService
from app.models.enums import ProductKind
from app.nlq import fields
from app.nlq.evidence import (
    EvidenceBundle,
    EvidenceStatus,
    ForecastProvenance,
    Period,
    ProductResolutionEvidence,
    ResolvedProduct,
    ResultLimits,
)
from app.nlq.operations import MAX_SERIES_BUCKETS, Operation
from app.nlq.requests import (
    AnalyticsRequest,
    BasketPairsRequest,
    ChannelMixRequest,
    DayOfWeekRequest,
    ForecastRequest,
    MenuEvidenceRequest,
    OverviewRequest,
    PeakHoursRequest,
    ProductAttachmentsRequest,
    ProductMoversRequest,
    ProductPerformanceRequest,
    ProductSelector,
    ProductTrendRequest,
    RevenueOverTimeRequest,
)
from app.nlq.resolution import ProductMatch, ProductResolution, ProductResolver

#: The forecast service speaks internal target names; the request speaks
#: business ones. The same mapping the HTTP endpoint uses.
_TARGETS = {
    "net_sales": "net_sales_pence",
    "payment_orders": "payment_order_count",
    "net_units": "net_units",
}


class AnalyticsExecutor:
    """Executes a validated request against the existing services."""

    def __init__(
        self,
        analytics: AnalyticsService,
        forecasts: ForecastService,
        resolver: ProductResolver,
    ) -> None:
        self._analytics = analytics
        self._forecasts = forecasts
        self._resolver = resolver

        # An explicit table, not attribute lookup by name. Nothing derived from
        # request content is ever used to select code to run: the key is an
        # enum member Pydantic has already validated against the whitelist.
        self._dispatch: dict[Operation, Callable[[Any], EvidenceBundle]] = {
            Operation.OVERVIEW: self._overview,
            Operation.REVENUE_OVER_TIME: self._revenue_over_time,
            Operation.DAY_OF_WEEK: self._day_of_week,
            Operation.PEAK_HOURS: self._peak_hours,
            Operation.CHANNEL_MIX: self._channel_mix,
            Operation.PRODUCT_PERFORMANCE: self._product_performance,
            Operation.PRODUCT_MOVERS: self._product_movers,
            Operation.PRODUCT_TREND: self._product_trend,
            Operation.PRODUCT_ATTACHMENTS: self._product_attachments,
            Operation.BASKET_PAIRS: self._basket_pairs,
            Operation.MENU_EVIDENCE: self._menu_evidence,
            Operation.FORECAST: self._forecast,
        }

    def execute(self, request: AnalyticsRequest) -> EvidenceBundle:
        return self._dispatch[request.operation](request)

    # -- period operations ----------------------------------------------------

    def _overview(self, request: OverviewRequest) -> EvidenceBundle:
        window, totals = self._analytics.overview(request.start_date, request.end_date)

        measured: dict[str, Any] = {
            "net_sales_pence": totals.net_sales_pence,
            "gross_sales_pence": totals.gross_sales_pence,
            "discounts_pence": totals.discounts_pence,
            "payment_order_count": totals.payment_order_count,
            "refund_event_count": totals.refund_event_count,
            "net_units": totals.net_units,
            "average_order_value_pence": totals.average_order_value_pence,
        }

        comparison: Period | None = None
        warnings: list[str] = []
        if request.compare_to_previous_period:
            # The ONLY comparison this layer performs, and it reuses the
            # existing `previous_window` rule rather than inventing period
            # arithmetic: an equal-length range ending the day before this one.
            prior = previous_window(window)
            _, before = self._analytics.overview(prior.start_date, prior.end_date)
            comparison = _period(prior)
            measured.update(_comparison_fields(totals, before))
            if measured["net_sales_percent_change"] is None:
                warnings.append(
                    "The previous period's net sales were not positive, so a "
                    "percentage change is undefined rather than zero."
                )

        return self._bundle(
            request,
            window=window,
            comparison_period=comparison,
            totals=measured,
            warnings=warnings,
        )

    def _revenue_over_time(self, request: RevenueOverTimeRequest) -> EvidenceBundle:
        series = self._analytics.revenue(
            request.start_date, request.end_date, request.granularity
        )
        rows = [
            {
                "period_start": b.period_start,
                "net_sales_pence": b.net_sales_pence,
                "gross_sales_pence": b.gross_sales_pence,
                "discounts_pence": b.discounts_pence,
                "payment_order_count": b.payment_order_count,
                "net_units": b.net_units,
            }
            for b in series.buckets
        ]
        return self._bundle(
            request,
            window=series.window,
            rows=rows,
            limits=_series_limits(len(rows)),
            warnings=[
                "Periods with no trade are explicit zero buckets, not missing "
                "data. A zero bucket means the business recorded nothing that "
                "day."
            ],
        )

    def _day_of_week(self, request: DayOfWeekRequest) -> EvidenceBundle:
        window, weekdays = self._analytics.day_of_week(
            request.start_date, request.end_date
        )
        rows = [
            {
                "iso_weekday": w.iso_weekday,
                "weekday": WEEKDAY_NAMES[w.iso_weekday],
                "net_sales_pence": w.net_sales_pence,
                "payment_order_count": w.payment_order_count,
                "net_units": w.net_units,
                "average_order_value_pence": w.average_order_value_pence,
            }
            for w in weekdays
        ]
        return self._bundle(
            request,
            window=window,
            rows=rows,
            limits=ResultLimits(returned_rows=len(rows), available_rows=len(rows)),
            warnings=[
                "Each row sums every occurrence of that weekday in the period, "
                "not one date."
            ],
        )

    def _peak_hours(self, request: PeakHoursRequest) -> EvidenceBundle:
        window, grid = self._analytics.peak_hours(
            request.start_date, request.end_date, busiest_limit=request.limit
        )
        trading_cells = sum(1 for c in grid.cells if c.payment_order_count > 0)
        rows = [
            {
                "iso_weekday": c.iso_weekday,
                "weekday": WEEKDAY_NAMES[c.iso_weekday],
                "hour": c.hour,
                "payment_order_count": c.payment_order_count,
                "net_sales_pence": c.net_sales_pence,
                "net_units": c.net_units,
            }
            for c in grid.busiest
        ]
        return self._bundle(
            request,
            window=window,
            rows=rows,
            totals={
                "peak_payment_order_count": grid.peak_payment_order_count,
                "trading_hour_cell_count": trading_cells,
            },
            limits=_limits(request.limit, len(rows), trading_cells, Operation.PEAK_HOURS),
            warnings=[
                "Hours are local (Europe/London). Only the busiest cells of the "
                "168-cell weekday/hour grid are returned; the rest are quieter, "
                "not absent."
            ],
        )

    def _channel_mix(self, request: ChannelMixRequest) -> EvidenceBundle:
        window, shares = self._analytics.channel_mix(
            request.start_date, request.end_date
        )
        rows = [
            {
                "channel": s.totals.channel.value,
                "net_sales_pence": s.totals.net_sales_pence,
                "payment_order_count": s.totals.payment_order_count,
                "net_units": s.totals.net_units,
                "average_order_value_pence": s.totals.average_order_value_pence,
                "share_of_payment_orders_percent": s.share_of_payment_orders_percent,
                "share_of_net_sales_percent": s.share_of_net_sales_percent,
            }
            for s in shares
        ]
        return self._bundle(
            request,
            window=window,
            rows=rows,
            limits=ResultLimits(returned_rows=len(rows), available_rows=len(rows)),
            warnings=[
                '"online", "mixed" and "unknown" are distinct channels, not '
                "sub-cases of the others. Folding them in would move revenue "
                "into a bucket the source data does not support."
            ],
        )

    # -- product operations ---------------------------------------------------

    def _product_performance(
        self, request: ProductPerformanceRequest
    ) -> EvidenceBundle:
        kinds = _kinds(request.kinds, DEFAULT_KINDS)
        # limit=None deliberately: the service already aggregates every product
        # in one statement and slices in Python, so asking for all of them costs
        # nothing extra and lets the bundle report how many qualified.
        ranking = self._analytics.products(
            request.start_date, request.end_date, kinds=kinds,
            sort=request.sort, limit=None,
        )
        available = len(ranking.products)
        rows = [
            {
                **_identity(p.totals.product_id, p.totals.name, p.totals.variation,
                            p.totals.kind),
                "gross_sales_pence": p.totals.gross_sales_pence,
                "discounts_pence": p.totals.discounts_pence,
                "net_sales_pence": p.totals.net_sales_pence,
                "net_units": p.totals.net_units,
                "payment_order_count": p.totals.payment_order_count,
                "average_selling_price_pence": p.totals.average_selling_price_pence,
                "share_of_net_sales_percent": p.share_of_net_sales_percent,
                "share_of_units_percent": p.share_of_units_percent,
            }
            for p in ranking.products[: request.limit]
        ]
        return self._bundle(
            request,
            window=ranking.window,
            kinds=kinds,
            rows=rows,
            totals={
                "total_net_sales_pence": ranking.total_net_sales_pence,
                "total_net_units": ranking.total_net_units,
            },
            limits=_limits(
                request.limit, len(rows), available, Operation.PRODUCT_PERFORMANCE
            ),
            warnings=[
                "Shares are of the whole filtered menu, not of the rows "
                "returned. Variations are separate products and are never "
                "merged."
            ],
        )

    def _product_movers(self, request: ProductMoversRequest) -> EvidenceBundle:
        kinds = _kinds(request.kinds, DEFAULT_KINDS)
        movers = self._analytics.product_movers(
            request.start_date, request.end_date, kinds=kinds, limit=None
        )
        available = len(movers.movements)
        rows = [
            {
                **_identity(m.product_id, m.name, m.variation, m.kind),
                "current_net_sales_pence": m.current_net_sales_pence,
                "previous_net_sales_pence": m.previous_net_sales_pence,
                "net_sales_change_pence": m.net_sales_change_pence,
                "net_sales_percent_change": m.net_sales_percent_change,
                "current_net_units": m.current_net_units,
                "previous_net_units": m.previous_net_units,
                "net_units_change": m.net_units_change,
                "movement_status": m.status.value,
            }
            for m in movers.movements[: request.limit]
        ]
        return self._bundle(
            request,
            window=movers.window,
            comparison_period=_period(movers.previous_window),
            kinds=kinds,
            rows=rows,
            limits=_limits(
                request.limit, len(rows), available, Operation.PRODUCT_MOVERS
            ),
            warnings=[
                "Movement is measured, not judged: nothing here says a product "
                "is performing well or badly, which would need cost data this "
                "system does not hold.",
                'A null percentage change is undefined, not zero — see '
                "movement_status for which case applies.",
            ],
        )

    def _product_trend(self, request: ProductTrendRequest) -> EvidenceBundle:
        resolution = self._resolve(request.product)
        if not resolution.is_resolved:
            return self._unresolved(request, request.product, resolution)

        trend = self._analytics.product_trend(
            resolution.match.product_id,
            request.start_date,
            request.end_date,
            request.granularity,
        )
        rows = [
            {
                "period_start": b.period_start,
                "gross_sales_pence": b.gross_sales_pence,
                "discounts_pence": b.discounts_pence,
                "net_sales_pence": b.net_sales_pence,
                "net_units": b.net_units,
                "payment_order_count": b.payment_order_count,
            }
            for b in trend.buckets
        ]
        t = trend.product
        return self._bundle(
            request,
            window=trend.window,
            rows=rows,
            totals={
                **_identity(t.product_id, t.name, t.variation, t.kind),
                "gross_sales_pence": t.gross_sales_pence,
                "discounts_pence": t.discounts_pence,
                "net_sales_pence": t.net_sales_pence,
                "net_units": t.net_units,
                "payment_order_count": t.payment_order_count,
                "average_selling_price_pence": t.average_selling_price_pence,
            },
            limits=_series_limits(len(rows)),
            resolution=resolution,
            selector=request.product,
        )

    def _product_attachments(
        self, request: ProductAttachmentsRequest
    ) -> EvidenceBundle:
        resolution = self._resolve(request.product)
        if not resolution.is_resolved:
            return self._unresolved(request, request.product, resolution)

        kinds = _kinds(request.kinds, BASKET_DEFAULT_KINDS)
        analysis = self._analytics.product_attachments(
            resolution.match.product_id,
            request.start_date,
            request.end_date,
            kinds=kinds,
            min_pair_orders=request.min_pair_orders,
            limit=None,
        )
        available = len(analysis.attachments)
        rows = [
            {
                **_identity(a.product.product_id, a.product.name, a.product.variation),
                "pair_orders": a.pair_orders,
                "product_orders": a.product_orders,
                "attachment_rate_percent": a.attachment_rate_percent,
                "reverse_attachment_rate_percent": a.reverse_attachment_rate_percent,
                "support_percent": a.support_percent,
                "lift": a.lift,
            }
            for a in analysis.attachments[: request.limit]
        ]
        anchor = analysis.anchor
        return self._bundle(
            request,
            window=analysis.window,
            kinds=kinds,
            rows=rows,
            totals={
                **_identity(anchor.product_id, anchor.name, anchor.variation),
                "anchor_order_count": analysis.anchor_order_count,
                "eligible_order_count": analysis.eligible_order_count,
            },
            limits=_limits(
                request.limit, len(rows), available, Operation.PRODUCT_ATTACHMENTS
            ),
            resolution=resolution,
            selector=request.product,
            warnings=[
                "Co-occurrence counts distinct payment orders, not quantities. "
                "Association is evidence, not a recommendation, and lift on a "
                "small pair count means very little."
            ],
        )

    def _basket_pairs(self, request: BasketPairsRequest) -> EvidenceBundle:
        kinds = _kinds(request.kinds, BASKET_DEFAULT_KINDS)
        analysis = self._analytics.product_pairs(
            request.start_date, request.end_date, kinds=kinds,
            min_pair_orders=request.min_pair_orders, sort=request.sort,
            limit=request.limit,
        )
        rows = [
            {
                "product_a_id": p.counts.a.product_id,
                "product_a_name": p.counts.a.name,
                "product_a_variation": p.counts.a.variation,
                "product_b_id": p.counts.b.product_id,
                "product_b_name": p.counts.b.name,
                "product_b_variation": p.counts.b.variation,
                "pair_orders": p.counts.pair_orders,
                "product_a_orders": p.counts.a_orders,
                "product_b_orders": p.counts.b_orders,
                "support_percent": p.metrics.support_percent,
                "confidence_a_to_b_percent": p.metrics.confidence_a_to_b_percent,
                "confidence_b_to_a_percent": p.metrics.confidence_b_to_a_percent,
                "lift": p.metrics.lift,
            }
            for p in analysis.pairs
        ]
        return self._bundle(
            request,
            window=analysis.window,
            kinds=kinds,
            rows=rows,
            totals={
                "eligible_order_count": analysis.eligible_order_count,
                "distinct_product_count": analysis.distinct_product_count,
                "qualifying_pair_count": analysis.qualifying_pair_count,
            },
            limits=_limits(
                request.limit, len(rows), analysis.qualifying_pair_count,
                Operation.BASKET_PAIRS,
            ),
            warnings=[
                "Pairs are unordered and counted over distinct payment orders. "
                "No significance testing is implied by lift."
            ],
        )

    def _menu_evidence(self, request: MenuEvidenceRequest) -> EvidenceBundle:
        kinds = _kinds(request.kinds, DEFAULT_KINDS)
        evidence = self._analytics.menu_evidence(
            request.start_date, request.end_date, kinds=kinds,
            min_pair_orders=request.min_pair_orders, limit=None,
        )
        available = len(evidence.rows)
        rows = []
        for r in evidence.rows[: request.limit]:
            a = r.strongest_attachment
            rows.append(
                {
                    **_identity(r.product.product_id, r.product.name,
                                r.product.variation, r.kind),
                    "gross_sales_pence": r.gross_sales_pence,
                    "discounts_pence": r.discounts_pence,
                    "net_sales_pence": r.net_sales_pence,
                    "net_units": r.net_units,
                    "payment_order_count": r.payment_order_count,
                    "average_selling_price_pence": r.average_selling_price_pence,
                    "discount_rate_percent": r.discount_rate_percent,
                    "share_of_menu_net_sales_percent": (
                        r.share_of_menu_net_sales_percent
                    ),
                    "share_of_menu_units_percent": r.share_of_menu_units_percent,
                    "previous_net_sales_pence": r.previous_net_sales_pence,
                    "previous_net_units": r.previous_net_units,
                    "net_sales_change_pence": r.net_sales_change_pence,
                    "net_units_change": r.net_units_change,
                    "net_sales_percent_change": r.net_sales_percent_change,
                    "movement_status": r.movement_status.value,
                    "revenue_direction": r.revenue_direction.value,
                    "attachment_product_id": a.product.product_id if a else None,
                    "attachment_product_name": a.product.name if a else None,
                    "attachment_product_variation": (
                        a.product.variation if a else None
                    ),
                    "attachment_pair_orders": a.pair_orders if a else None,
                    "attachment_rate_percent": (
                        a.attachment_rate_percent if a else None
                    ),
                    "attachment_lift": a.lift if a else None,
                }
            )
        return self._bundle(
            request,
            window=evidence.window,
            comparison_period=_period(evidence.previous_window),
            kinds=kinds,
            rows=rows,
            totals={
                "eligible_order_count": evidence.eligible_order_count,
                "total_net_sales_pence": evidence.total_net_sales_pence,
                "total_net_units": evidence.total_net_units,
            },
            limits=_limits(
                request.limit, len(rows), available, Operation.MENU_EVIDENCE
            ),
            warnings=[
                "An evidence view, not a recommendation engine. Whether a "
                "product should be repriced, promoted or removed needs cost, "
                "margin and elasticity data this system does not hold.",
                "A null attachment field means no co-purchase met the "
                "min_pair_orders threshold, not that the product is never "
                "bought with anything.",
            ],
        )

    # -- forecast -------------------------------------------------------------

    def _forecast(self, request: ForecastRequest) -> EvidenceBundle:
        try:
            result = self._forecasts.forecast(
                _TARGETS[request.target], request.horizon_days
            )
        except SeriesIntegrityError as exc:
            return EvidenceBundle(
                operation=request.operation,
                status=EvidenceStatus.INSUFFICIENT_HISTORY,
                parameters=request.model_dump(mode="json"),
                warnings=[str(exc)],
            )

        rows = [
            {"date": p.day, "predicted_value": p.predicted_value}
            for p in result.points
        ]
        provenance = ForecastProvenance(
            method=result.method,
            trained_through=result.trained_through,
            forecast_start=result.forecast_start,
            forecast_end=result.forecast_end,
            horizon_days=result.horizon_days,
            unit=result.unit,
            historical_wape_percent=result.historical_wape_percent,
            historical_mae=result.historical_mae,
            backtest_folds=result.backtest_folds,
            backtest_horizon_days=result.backtest_horizon_days,
        )
        return EvidenceBundle(
            operation=request.operation,
            parameters=request.model_dump(mode="json"),
            rows=rows,
            field_provenance=fields.provenance_for(rows, {}),
            units={"predicted_value": result.unit, "date": "local calendar date"},
            limits=ResultLimits(
                returned_rows=len(rows),
                applied_limit=request.horizon_days,
                maximum_rows=fields.MAX_ROWS[Operation.FORECAST],
                available_rows=len(rows),
            ),
            forecast=provenance,
            warnings=[
                f"These are PREDICTIONS. Real data ends on "
                f"{result.trained_through.isoformat()}; every row is dated "
                "after it and records nothing that has happened.",
                "historical_wape_percent is the error this method made on "
                "unseen days in backtesting. It is not a confidence interval "
                "for these predictions, and no interval is provided.",
            ],
        )

    # -- shared -------------------------------------------------------------

    def _resolve(self, selector: ProductSelector) -> ProductResolution:
        if selector.product_id is not None:
            return self._resolver.by_id(selector.product_id)
        return self._resolver.by_name(selector.name, selector.variation)

    def _unresolved(
        self,
        request: AnalyticsRequest,
        selector: ProductSelector,
        resolution: ProductResolution,
    ) -> EvidenceBundle:
        """A product reference that did not resolve. No analytics query ran.

        Returned as evidence rather than raised, because the candidate list is
        the useful part: a caller that asked about "Caffe Latte" needs to see
        that Regular and Large both exist so it can ask again.
        """
        ambiguous = resolution.status == "ambiguous"
        return EvidenceBundle(
            operation=request.operation,
            status=(
                EvidenceStatus.AMBIGUOUS_PRODUCT
                if ambiguous
                else EvidenceStatus.UNKNOWN_PRODUCT
            ),
            parameters=request.model_dump(mode="json"),
            product_resolution=_resolution_evidence(selector, resolution),
            warnings=[
                (
                    "The product reference matched more than one catalogue "
                    "entry. No analytics were run; choose one of the "
                    "candidates by product_id and ask again."
                )
                if ambiguous
                else (
                    "The product reference matched nothing in the catalogue. "
                    "No analytics were run, and no similar product was "
                    "substituted."
                )
            ],
        )

    def _bundle(
        self,
        request: AnalyticsRequest,
        *,
        window: QueryWindow,
        rows: list[dict[str, Any]] | None = None,
        totals: dict[str, Any] | None = None,
        comparison_period: Period | None = None,
        kinds: tuple[ProductKind, ...] | None = None,
        limits: ResultLimits | None = None,
        resolution: ProductResolution | None = None,
        selector: ProductSelector | None = None,
        warnings: list[str] | None = None,
    ) -> EvidenceBundle:
        rows = rows or []
        totals = totals or {}
        parameters = request.model_dump(mode="json")
        if kinds is not None:
            parameters["kinds"] = [k.value for k in kinds]
        if resolution is not None and resolution.match is not None:
            parameters["product_id"] = resolution.match.product_id

        notes = list(warnings or [])
        if limits is not None and limits.truncated:
            notes.insert(
                0,
                f"Truncated: {limits.returned_rows} of "
                f"{limits.available_rows} qualifying rows are included, "
                f"ordered by the requested measure. Statements about the full "
                f"set are not supported by this evidence.",
            )
        if fields.has_undefined(rows, totals):
            notes.append(
                "Null values are UNDEFINED quantities, not zero — typically a "
                "ratio whose denominator was zero. Do not render them as 0."
            )
        if _is_empty_period(totals, rows):
            notes.append(
                "No trade was recorded in this period, so every ratio over it "
                "is undefined."
            )

        return EvidenceBundle(
            operation=request.operation,
            parameters=parameters,
            period=_period(window),
            comparison_period=comparison_period,
            rows=rows,
            totals=totals,
            field_provenance=fields.provenance_for(rows, totals),
            units=fields.units_for(rows, totals),
            limits=limits,
            product_resolution=(
                _resolution_evidence(selector, resolution)
                if resolution is not None and selector is not None
                else None
            ),
            warnings=notes,
        )


# --- helpers -----------------------------------------------------------------


def _kinds(
    selected: tuple[ProductKind, ...] | None, default: tuple[ProductKind, ...]
) -> tuple[ProductKind, ...]:
    """De-duplicated, order-preserving; falls back to the caller's default.

    Mirrors `app.api.products._kinds` so the AI layer and the HTTP API filter
    the catalogue identically.
    """
    return tuple(dict.fromkeys(selected)) if selected else default


def _identity(
    product_id: int, name: str, variation: str, kind: ProductKind | None = None
) -> dict[str, Any]:
    """Product identity flattened into a row.

    Flat rather than nested, so every key in a row maps to exactly one
    provenance entry and one unit.
    """
    row: dict[str, Any] = {
        "product_id": product_id,
        "product_name": name,
        "product_variation": variation,
    }
    if kind is not None:
        row["kind"] = kind.value
    return row


def _period(window: QueryWindow) -> Period:
    return Period(
        start_date=window.start_date, end_date=window.end_date, days=window.days
    )


def _series_limits(count: int) -> ResultLimits:
    """Date-series operations return the requested range, one bucket per period."""
    return ResultLimits(
        returned_rows=count,
        available_rows=count,
        maximum_rows=MAX_SERIES_BUCKETS,
        truncated=False,
    )


def _limits(
    requested: int, returned: int, available: int, operation: Operation
) -> ResultLimits:
    return ResultLimits(
        returned_rows=returned,
        applied_limit=requested,
        maximum_rows=fields.MAX_ROWS[operation],
        available_rows=available,
        truncated=available > returned,
    )


def _comparison_fields(current, before) -> dict[str, Any]:
    """Overview against the comparable previous period.

    Percentage change follows the same rule product movers already uses: it
    exists only when the previous period was positive. Growth from zero is
    undefined, not infinite, and `comparison_status` says which case applies.
    """
    change = current.net_sales_pence - before.net_sales_pence
    if before.net_sales_pence > 0:
        status = MovementStatus.COMPARABLE
        percent = round(change * 100 / before.net_sales_pence, 2)
    elif before.net_sales_pence == 0 and current.net_sales_pence != 0:
        status = MovementStatus.NEW_IN_PERIOD
        percent = None
    else:
        status = MovementStatus.NOT_COMPARABLE
        percent = None

    return {
        "previous_net_sales_pence": before.net_sales_pence,
        "previous_payment_order_count": before.payment_order_count,
        "previous_net_units": before.net_units,
        "previous_average_order_value_pence": before.average_order_value_pence,
        "net_sales_change_pence": change,
        "net_sales_percent_change": percent,
        "payment_order_count_change": (
            current.payment_order_count - before.payment_order_count
        ),
        "net_units_change": current.net_units - before.net_units,
        "comparison_status": status.value,
    }


def _resolution_evidence(
    selector: ProductSelector | None, resolution: ProductResolution
) -> ProductResolutionEvidence:
    return ProductResolutionEvidence(
        requested_name=selector.name if selector else None,
        requested_variation=selector.variation if selector else None,
        requested_product_id=selector.product_id if selector else None,
        resolved=_resolved(resolution.match) if resolution.match else None,
        candidates=[_resolved(c) for c in resolution.candidates],
    )


def _resolved(match: ProductMatch) -> ResolvedProduct:
    return ResolvedProduct(
        product_id=match.product_id,
        name=match.name,
        variation=match.variation,
        kind=match.kind,
    )


def _is_empty_period(totals: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    """True when nothing was sold, so shares and averages are all undefined."""
    counted = totals.get("payment_order_count")
    if counted is not None:
        return counted == 0
    if not rows:
        return False
    if "payment_order_count" in rows[0]:
        return all(r.get("payment_order_count", 0) == 0 for r in rows)
    return False
