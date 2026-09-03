# Restaurant Intelligence

Analytics for independent hospitality businesses running Square EPOS.

Square's own reporting answers *what happened*. This project ingests raw Square
exports into a vendor-neutral data model so you can ask *why* — how revenue
splits across in-store, delivery and online, which products actually earn, and
when the real peaks are.

Built from a real problem: after rolling out Square across a three-floor café,
the operational data existed but was effectively unusable.

> **Status:** complete and covered by tests — the ingestion pipeline, the
> analytics API, a validated short-horizon demand forecast, and a Next.js
> dashboard whose six sections all read live data: headline KPIs, trading
> analytics, product intelligence, basket analysis, the forecast, and the
> Square import workflow. Natural-language query is the next milestone and does
> not exist yet. This README describes only what runs today.

---

## What it does

**Reads Square's real export format.** Square names its exports `.csv`, but they
are UTF-16, tab-delimited files. Opening one with a normal CSV reader yields a
single column of garbage rather than an error, so the format is asserted and a
wrong file is rejected with a message that says why.

**Maps to a canonical model.** Square's columns are an external contract we
don't control. A thin adapter maps them onto our own schema, so adding a second
EPOS provider later means writing one adapter and changing nothing downstream.

**Persists to PostgreSQL** with versioned Alembic migrations. Money is stored as
integer pence — never floats — and timestamps are converted from the business's
local time to UTC, so British Summer Time doesn't silently shift the trading day.

**Is idempotent.** Every uploaded file is checksummed. Re-uploading one is
rejected before anything is written, so revenue can't be double-counted.

**Handles overlapping exports.** If two extractions share an order, the incoming
version is compared field-by-field with the stored one. Identical, it's skipped;
different, the whole import is rolled back rather than leaving data that matches
no source file.

**Reconciles against Square's own totals.** When the Items Summary export is
supplied, imported net sales, line totals and unit counts must match it exactly
or the import fails. It's an independent check on our arithmetic, not decoration.

**Forecasts the next fortnight, and reports how wrong it usually is.** A ridge
regression on weekday, lag and holiday features predicts daily net sales,
orders and units 1–14 days out. It is validated by rolling-origin backtesting
against a baseline an experienced operator would actually use, and every
forecast the API returns carries the error that method made on days it had
never seen. The improvement over the baseline is real but modest, and the
[Forecasting](#forecasting) section below says so with the numbers.

**Doesn't store personal data.** Customer, card and staff columns are dropped at
the parsing boundary — the canonical schema has no column to put them in.

```
$ SELECT count(*) FROM information_schema.columns
    WHERE column_name ~* 'customer|card|staff|employee|pan';
  0
```

---

## Architecture

```
  Square exports (UTF-16, tab-delimited)
    transactions.csv    items-detail.csv    items-summary.csv
            │                  │                    │
            ▼                  ▼                    │
  ┌───────────────────────────────────┐             │
  │  Square adapter                   │             │
  │   • format + schema assertions    │             │
  │   • decimal-safe money → pence    │             │
  │   • Europe/London → UTC           │             │
  │   • channel derivation            │             │
  │   • PII dropped here              │             │
  └───────────────┬───────────────────┘             │
                  ▼                                 │
       Canonical records  (vendor-neutral)          │
                  │                                 │
                  ▼                                 ▼
  ┌───────────────────────────────────────────────────────┐
  │  Import service        (one database transaction)     │
  │   1. checksum preflight  → reject duplicates          │
  │   2. compare overlapping orders → skip or fail        │
  │   3. persist batch, files, products, orders, items    │
  │   4. reconcile ◄──────────────────────────────────────┘
  │   …any failure rolls back every sales-data change      │
  └───────────────┬───────────────────────────────────────┘
                  ▼
             PostgreSQL
     products · orders · order_items
     import_batches · import_files
                  ▲
                  │
        FastAPI   POST /imports/square
```

Design decisions, alternatives and trade-offs are documented in
[ARCHITECTURE.md](ARCHITECTURE.md).

---

## Prerequisites

- **Docker Desktop** (or Docker Engine + Compose v2)
- **curl** and **Python 3** for the demo script

Nothing else — and deliberately so. **Node.js is not a prerequisite.**
Postgres, the Python toolchain and the Node toolchain each run in their own
container, so nothing needs installing on the host to build, test or lint any
part of this project.

## Setup

```bash
git clone https://github.com/amanshowan/restaurant-intelligence.git
cd restaurant-intelligence
cp .env.example .env          # local dev values; .env is gitignored
docker compose up -d --wait
```

`--wait` blocks until every service passes its health check — Postgres ready,
the API up, and the dashboard actually serving a page rather than merely
started. First run pulls images and builds, so allow a few minutes; subsequent
starts are seconds.

| | |
|---|---|
| **Dashboard** | **<http://localhost:3000>** |
| API docs | <http://localhost:8000/docs> |

```bash
docker compose down       # stop, keeping the database
docker compose down -v    # stop and DELETE the database volume
```

## Database migrations

The schema is managed by Alembic; migrations run inside the API container.

```bash
docker compose exec api alembic upgrade head   # apply
docker compose exec api alembic current        # show current revision
docker compose exec api alembic history        # list revisions
docker compose exec api alembic check          # models and migrations agree?
```

## Tests

```bash
docker compose exec api python -m pytest
```

The backend suite runs against the real PostgreSQL service — testing against SQLite
would not exercise the foreign-key policies, composite constraints and
NULL-distinctness rules the design depends on. It builds its schema by running
the migrations, so a migration that drifts from the models fails the suite.

It runs against **`restaurant_intelligence_test`**, a separate database on the
same PostgreSQL server, and never touches the development database:

| Database | Used by |
|---|---|
| `restaurant_intelligence` | the API and the dashboard — `DATABASE_URL` |
| `restaurant_intelligence_test` | pytest, and nothing else — `TEST_DATABASE_URL` |

This is not a convention to remember, it is enforced. The suite truncates every
sales table and downgrades the schema to base, so
[`backend/tests/conftest.py`](backend/tests/conftest.py) refuses to start if
`TEST_DATABASE_URL` is unset, if it names the development database, or if the
database name does not end in `_test` — it never falls back to `DATABASE_URL`.
The test database is created automatically on the first run, so there is no
setup step.

The frontend's checks run in its own container, so they need no host Node:

```bash
docker compose run --rm --no-deps web npm test        # vitest
docker compose run --rm --no-deps web npm run typecheck
docker compose run --rm --no-deps web npm run lint
```

Most frontend tests run in Node against `src/lib` — formatting, query
serialisation, the API client, the forecast presentation rules — because that
is where a mistake produces a wrong number or a silently malformed request. The
Forecast page is the exception: what it must never do — present a prediction as
a record, or a measured error as an accuracy — is a property of the *rendered*
output, so those tests opt into a DOM.

`next build` no longer runs linting as of Next.js 16, so `lint` is a separate
step rather than something a build would catch. To verify a full production
build, build the image's production stage — which compiles with
`NODE_ENV=production` and fails on a type error:

```bash
docker build --target runner ./frontend
```

## API docs

With the stack running, interactive OpenAPI docs are at
**<http://localhost:8000/docs>**.

Health endpoints are deliberately split: `/health` reports whether the process
is alive, `/health/ready` whether it can reach the database. A dependency blip
should stop traffic being routed to a container, not trigger a restart loop.

---

## Try it: import the synthetic dataset

The repository ships a small **fake** Square export set in
[`demo/square-sample/`](demo/square-sample) — an invented coffee shop with
invented products and transactions. No real business data is in this repository.

```bash
docker compose up -d --wait
./scripts/demo_import.sh
```

Actual response:

```json
{
  "batch_id": 1,
  "status": "completed",
  "label": "demo-august-2026",
  "period_start": "2026-08-03",
  "period_end": "2026-08-05",
  "orders_imported": 10,
  "order_items_imported": 12,
  "products_created": 5,
  "products_reused": 0,
  "rows_skipped": 1,
  "issue_counts": {
    "zero_value_transaction": 1,
    "refund_channel_inherited": 1
  },
  "net_sales_pence": 4500,
  "reconciliation": {
    "performed": true,
    "matches": true,
    "net_sales_pence_ours": 4500,
    "net_sales_pence_theirs": 4500,
    "line_totals_pence_ours": 4600,
    "line_totals_pence_theirs": 4600,
    "units_ours": 13,
    "units_theirs": 13
  }
}
```

Or with plain `curl`:

```bash
curl -X POST http://localhost:8000/imports/square \
  -F "transactions=@demo/square-sample/transactions-demo-2026-08.csv" \
  -F "items=@demo/square-sample/items-demo-2026-08.csv" \
  -F "summary=@demo/square-sample/item-sales-summary-demo-2026-08.csv" \
  -F "label=demo-august-2026"
```

The demo set is deliberately small but covers every branch of the importer:

| It contains | Which exercises |
|---|---|
| Counter, delivery, online, pick-up and mixed orders | all five channel values |
| A sale and its full refund, linked by payment id | refunds as negative events that don't inflate order counts |
| A staff discount | Square's "Gross Sales" already being net of discounts |
| A gift voucher and an open-price line | product kinds excluded from menu revenue |
| A zero-value no-sale row | exclusions that are counted, not silently dropped |
| Two price points of one product | products keyed on `(name, variation)` |

**Run it twice** to see idempotency: the second attempt returns `409` with
`"code": "duplicate_file"` and writes nothing.

The files are generated from a single source-of-truth script, so the three
exports reconcile by construction rather than by hand-editing. Regenerate them
with (standard library only, no dependencies needed):

```bash
python3 backend/scripts/generate_demo_data.py
```

---

## Analytics

Read-only endpoints over the imported data. All are documented in `/docs`.

| Endpoint | Returns |
|---|---|
| `GET /analytics/overview` | Net sales, gross, discounts, order counts, net units, AOV |
| `GET /analytics/revenue` | Time series, `granularity=day\|week` |
| `GET /analytics/day-of-week` | Monday–Sunday totals |
| `GET /analytics/peak-hours` | 7×24 heatmap grid, plus the busiest cells |
| `GET /analytics/channels` | In-store vs collection vs delivery vs online mix |
| `GET /analytics/products` | Performance per product variation |
| `GET /analytics/products/{id}/trend` | One product over time |
| `GET /analytics/products/movers` | Movement against the previous comparable period |
| `GET /analytics/products/{id}/attachments` | What else is in the basket with it |
| `GET /analytics/baskets/pairs` | Products bought together, with support and lift |
| `GET /analytics/menu/evidence` | All of the above per product, in one row |
| `GET /analytics/forecast` | Predicted daily net sales, orders or units, 1-14 days ahead |

```bash
curl "http://localhost:8000/analytics/overview?start_date=2026-08-03&end_date=2026-08-05"
```

Five things worth knowing before reading the numbers:

- **Dates are inclusive `Europe/London` calendar dates.** All grouping is in
  business-local time, so a "day" is the trading day, not 00:00–00:00 UTC.
- **Refunds reduce net sales but are not counted as orders.** That keeps average
  order value honest.
- **Day-of-week and peak-hour figures aggregate across the period** — "Sunday
  11:00" means every Sunday in the range, not one date.
- **Weekly buckets start on Monday**, so the first may be labelled before your
  `start_date` when the range opens mid-week.
- **Product analytics cover the menu only** by default. Gift vouchers and
  open-price lines stay in the database so imports reconcile against Square, but
  they are not menu revenue.

`/analytics/menu/evidence` is a **decision-evidence view, not a recommendation
engine**: it reports sales, units, exact per-line discounts, movement against
the previous comparable period, and the strongest co-purchase association. It
says nothing about pricing or profitability, because the system holds no cost,
margin or price-elasticity data.

Full metric definitions are in [ARCHITECTURE.md §5a](ARCHITECTURE.md).

## Forecasting

`GET /analytics/forecast?target=net_sales&horizon_days=14` predicts the next
1–14 local trading days from the most recent imported one.

The requirement was never "produce a forecast chart". It was **produce a
forecast whose quality is honestly measured** — which means a baseline worth
beating, a validation scheme a live forecast could actually reproduce, and a
published result even where that result is unflattering.

### The daily series

Forecasting reads the same SQL aggregation the analytics API already uses
(`analytics.queries.fetch_revenue_series`), so "daily net sales" means exactly
one thing across the codebase. It inherits grouping on the local
`Europe/London` trading day, refunds reducing net sales and units, and payment
orders counted only from payment events. The series is **zero-filled**: a day
with no trade is an observed zero, not a gap, because a forecaster that treats
a closure as missing data will cheerfully predict trade on Christmas Day.

### Validation: rolling-origin, and leakage-safe by construction

A random train/test split trains on next Tuesday to predict last Tuesday and
reports an accuracy the business can never experience. Every fold here trains
only on the past and is scored only on the future:

```
|<-------- train ------->|<- test ->|
|<----------- train ---------->|<- test ->|
|<--------------- train -------------->|<- test ->|
```

Over one year of trade that gives **17 folds × a 14-day horizon = 238
previously unseen forecast days**, pooled into one figure per target.

Two properties are enforced by the code's shape rather than by discipline:

- a forecaster is handed only the training observations and a horizon. It is
  never given the days it is being scored on, so it cannot consult them;
- multi-step forecasting is **recursive**. Day 8's `lag_7` feature points at
  day 1, which is inside the horizon and unknown at forecast time, so it uses
  the model's own day-1 *prediction*. Reading the actual would produce a
  backtest score no live forecast could reproduce, and is the single easiest
  way to fake a good result.

### The baseline is not a strawman

A café's trade is dominated by day of week, and "the same as last week" is what
an experienced operator actually predicts. Three transparent baselines were
measured before any model was written; the strongest is the **four-week
same-weekday mean**.

### Result

Ridge regression on 13 features — six weekday dummies, lags at 7/14/21/28 days,
trailing 7- and 28-day means, and a fixed-date holiday flag — is the production
method. Pooled WAPE over all 238 unseen days:

| Method | Net sales | Payment orders | Net units |
|---|---|---|---|
| Seasonal naive (last week) | 16.35% | 15.11% | 16.55% |
| 28-day trailing mean | 20.21% | 14.19% | 18.45% |
| **Four-week same-weekday mean** (baseline) | 13.22% | 12.47% | 13.02% |
| **Ridge + holiday flag** (production) | **12.69%** | **11.29%** | **12.35%** |
| Histogram gradient boosting (rejected) | 14.33% | 13.55% | 14.00% |

**The honest reading:** Ridge beats the strongest baseline on all three
targets, and the margin is small — 0.53 points on revenue, 1.18 on orders, 0.67
on units. In money that is a mean absolute error of £179.70 per day against the
baseline's £187.18. It is a real improvement, consistent across targets and not
merely an artefact of the festive fortnight, but it is not a transformation,
and presenting it as one would be the dishonest part.

**The rejected challenger is reported too.** Histogram gradient boosting was
tested under the identical harness and was worse than Ridge on all three
targets — and worse than the same-weekday baseline as well. With ~365
observations and a signal that is close to linear in the features given, a
model that can carve arbitrary interactions mostly finds noise. A documented
negative result is worth more than a quietly dropped experiment.

### How error is reported, and what is deliberately absent

Every forecast response carries `historical_wape_percent` and `historical_mae`
alongside the fold count and horizon they were measured over. Both are
**errors**, and the dashboard presents them as errors:

```
Historical WAPE   12.69%
Across 238 previously unseen forecast days, pooled from 17 rolling-origin
backtest folds of 14 days each.
```

Nothing subtracts that from 100. "87.31% accurate" would be a claim about the
predictions on screen, and the backtest measures something else entirely — how
wrong this *method* has been on *other* days.

MAPE is absent on purpose: it divides by each day's actual, so one closed day
makes it undefined and one very quiet day makes it enormous. A café has both.

**There are no prediction intervals.** Producing one would mean validating that
it contains the outcome as often as it claims, which has not been done — and an
unchecked range invites more confidence than an honest number. The API returns
no bounds, and the dashboard invents none.

### Current limitations

- **One year of data.** Twelve months means every seasonal pattern is observed
  exactly once, so annual seasonality cannot be separated from trend. Month
  dummies were measured rather than argued about, and left out because they
  made things worse (13.07% / 11.94% / 12.32% against 12.69% / 11.29% /
  12.35%): eleven columns describing twelve months seen once each is
  memorisation. The model choice should be re-evaluated once a second year
  exists.
- **Fixed-date holidays only.** 25 December, 26 December and 1 January. Easter
  and the moveable bank holidays would need a calendar library.
- **No external features.** No weather, no local events, no school terms — all
  of which plausibly move a café's covers, and none of which the system holds.
- **No prediction intervals**, for the reason above.
- **Fitted per request, not persisted.** There is no model registry and no
  scheduled retraining; the backtest metrics are memoised per process, which is
  a cache, not a store.
- **14 days is the ceiling.** Beyond a fortnight the recursive forecast is
  predicting almost entirely from its own output, and nothing in the backtest
  supports it.


## Dashboard

The Next.js app at **<http://localhost:3000>** opens on **Overview**: net sales,
payment orders, average order value, net units, gross sales and discounts for a
date range, read live from `/analytics/overview`.

**Imports** is the Square upload workflow: choose a Transactions export and an
Items Detail export (an Items Summary is optional and turns reconciliation on),
and the API validates the format, derives the coverage period from the file
contents and reconciles the result. The page reports what was written — batch,
period, orders, items, products, skipped rows and the reconciliation table —
and refuses a duplicate rather than counting an export twice. Nothing is parsed
in the browser.

**Trading** covers overall trading performance over the same date range —
revenue over time (daily or weekly), day-of-week totals, a weekday x hour
heatmap of local trading hours, and the channel mix. Its four sections load
independently and fail independently: one endpoint falling over leaves the
other three readable rather than blanking the page.

**Products** ranks every menu variation by sales, units, discounting and
movement against the previous comparable period, from a single
`/analytics/menu/evidence` request. Selecting a product opens a detail panel
with its trend over time and what it is bought with — two further requests, for
that product only, so the page issues a small constant number regardless of
catalogue size.

**Basket Analysis** reports which products are bought together, with support,
both directional confidences and lift, plus a scatter of co-occurrence count
against lift. It opens at a minimum of 20 shared orders rather than the API's
own default of 1: at 1, a lift-sorted list is led by pairs seen once. The
threshold is an on-screen control and the response echoes the value applied.

**Forecast** is the one page that shows numbers for days that have not
happened, and it is built to be impossible to mistake for the others. A single
request returns the whole horizon; the measure switcher (net sales, payment
orders, net units) and the 1–14 day horizon each re-issue exactly one request.
The line is dashed, every caption reads "predicted", the last day of real data
is stated at the top, and the historical error sits on the page beside the
prediction rather than in a footnote — as an error, in £ per day or units per
day, with the count of unseen days it was measured over. No confidence figure
and no interval band appear anywhere, because neither has been validated.

Both the Products and Basket pages are **evidence, not recommendation**. Movement is reported
mechanically — increasing, decreasing, unchanged, new in period, not comparable
— and a percentage change the backend calls undefined stays undefined. Nothing
suggests repricing, promoting or removing a product; that would need cost,
margin and elasticity data the system does not hold.

Zero-revenue menu items are shown truthfully. `Tap Water / Regular` sells
hundreds of units at £0.00 and appears throughout the basket data; a filter to
set such items aside exists, is labelled, and is off by default.

Charts are drawn with Recharts, in a single hue. Weekdays, channels and time
buckets are each a single series with the category on the axis, so colour is
left free to carry intensity in the heatmap — where it is the one thing the
chart does not otherwise show. There are deliberately no dual-axis charts:
money and order counts are plotted separately rather than against two scales
whose alignment would be arbitrary.

It opens on the **last complete calendar month**, computed from the clock in
`Europe/London`. The current month is always partial, and a rolling 30 days
straddles two months — neither is the unit a business reconciles in. Nothing
about the range is hard-coded to a month that happens to hold data.

> The backend exposes no "what period do you actually hold data for?" endpoint,
> so the dashboard cannot open on the imported range. A range with no data
> renders as a legitimate zero period, which currently looks the same as a
> month the business was closed. A dataset-aware range selector needs that
> endpoint first.

### The browser never talks to the API directly

```
browser  →  localhost:3000/api/analytics/overview     same origin
         →  Next.js server  (rewrite, server-side)
         →  http://api:8000/analytics/overview        Compose network
         →  FastAPI
```

Every browser request is same-origin, so no preflight happens, no
`Access-Control-Allow-Origin` list has to be kept in step with each
environment, and **the backend carries no CORS configuration at all**.

Two environment variables, set in `docker-compose.yml`:

| Variable | Value | Visibility |
|---|---|---|
| `API_UPSTREAM_URL` | `http://api:8000` | **Server only.** Read by `next.config.ts` to target the rewrite. |
| `NEXT_PUBLIC_API_BASE_URL` | `/api` | Public — inlined into the client bundle. A path, nothing more. |

`api` is a Compose service name that resolves only inside the Compose network.
It is deliberately *not* a `NEXT_PUBLIC_*` variable: that would inline an
internal hostname into every visitor's JavaScript, where it is both a leak and
an address no browser could resolve.

One consequence worth knowing: when the API is unreachable, the Next.js rewrite
answers with a plain-text `HTTP 500`, not a gateway status. The client
therefore identifies an unreachable backend by the *absence of the API's error
envelope* rather than by status code, and says "Cannot reach the API" instead
of blaming the request.

## Project layout

```
backend/
  app/
    adapters/     Square file reading and normalisation
    services/     import orchestration, persistence, reconciliation
    analytics/    SQL aggregations behind the analytics endpoints
    forecasting/  daily series, baselines, features, models, backtest harness
    models/       SQLAlchemy models
    schemas/      Pydantic — external Square shapes vs canonical records
    api/          FastAPI routes
  alembic/        migrations
  tests/          pytest suite
frontend/
  src/
    app/          App Router pages — one per dashboard section
    components/   shell, page furniture, one directory per dashboard
    lib/          typed API client, formatting, date-range and forecast
                  presentation rules (+ tests)
demo/square-sample/   synthetic Square exports (safe, committed)
data/                 real exports go here — gitignored, never committed
```

## Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs two independent
jobs in parallel on every push and pull request, so a red tick says which half
broke without opening the log:

| Job | Does |
|---|---|
| **Backend** | starts PostgreSQL, runs the migrations, checks the models and migrations agree, runs pytest against the isolated `_test` database |
| **Frontend** | `npm ci` from the lockfile, Vitest, `tsc --noEmit`, ESLint, production build |

The frontend job uses the runner's own Node rather than the Compose stack.
Docker is the only prerequisite for *local* development — the point of that
promise is that a contributor installs nothing — but a CI runner already has a
Node toolchain, and building an image to reach it would add minutes for no
extra confidence.

## Not built yet

The natural-language query interface is planned. Its design is in
[ARCHITECTURE.md §7](ARCHITECTURE.md); it does not exist in the code today, and
nothing in the dashboard interprets a question or generates a recommendation.

Every section of the dashboard is built and reads live data. There are no
placeholder pages.

The forecast is deliberately limited: no prediction intervals, no external
features, no persisted model or scheduled retraining, and a 14-day ceiling.
Those limits, and why each is there, are listed under
[Forecasting](#current-limitations).

Deliberately absent, and not planned without the data to support them: product
costs, margins, price recommendations and elasticity modelling. The system
records what was sold, not what it cost.
