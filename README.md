# Restaurant Intelligence

Analytics for independent hospitality businesses running Square EPOS.

Square's own reporting answers *what happened*. This project ingests raw Square
exports into a vendor-neutral data model so you can ask *why* — how revenue
splits across in-store, delivery and online, which products actually earn, and
when the real peaks are.

Built from a real problem: after rolling out Square across a three-floor café,
the operational data existed but was effectively unusable.

> **Status:** the ingestion pipeline and the analytics API — revenue, timing,
> channel, product and basket — are complete and covered by tests. The
> dashboard, forecasting and natural-language query are the next milestones.
> This README describes only what runs today.

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

Nothing else. Postgres and the Python toolchain run in containers.

## Setup

```bash
git clone https://github.com/amanshowan/restaurant-intelligence.git
cd restaurant-intelligence
cp .env.example .env          # local dev values; .env is gitignored
docker compose up -d --wait
```

`--wait` blocks until Postgres passes its health check and the API is up. First
run pulls images and builds, so allow a few minutes; subsequent starts are
seconds.

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

The suite runs against the real PostgreSQL service — testing against SQLite
would not exercise the foreign-key policies, composite constraints and
NULL-distinctness rules the design depends on. It builds its schema by running
the migrations, so a migration that drifts from the models fails the suite.

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

Five read-only endpoints over the imported data. All are documented in `/docs`.

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

## Project layout

```
backend/
  app/
    adapters/     Square file reading and normalisation
    services/     import orchestration, persistence, reconciliation
    models/       SQLAlchemy models
    schemas/      Pydantic — external Square shapes vs canonical records
    api/          FastAPI routes
  alembic/        migrations
  tests/          pytest suite
demo/square-sample/   synthetic Square exports (safe, committed)
data/                 real exports go here — gitignored, never committed
```

## Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) starts PostgreSQL, runs
the migrations, checks the models and migrations agree, and runs the test suite
on every push and pull request.

## Not built yet

The Next.js dashboard, demand forecasting and the natural-language query
interface are planned. Their designs are in [ARCHITECTURE.md](ARCHITECTURE.md);
none of them exist in the code today.

Deliberately absent, and not planned without the data to support them: product
costs, margins, price recommendations and elasticity modelling. The system
records what was sold, not what it cost.
