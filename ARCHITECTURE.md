# Restaurant Intelligence Platform — Architecture

Analytics platform for independent hospitality businesses running EPOS systems.
Ingests point-of-sale transaction exports, models them into a vendor-neutral
schema, and exposes revenue, timing, product and channel analytics — plus
demand forecasting and a constrained natural-language query interface.

Built from a real problem: after implementing a Square EPOS system across a
three-floor café (which supported monthly revenue growth from ~£15k to ~£45k),
the operational data existed but was effectively unusable. Square's native
reporting answers "what happened", not "why" or "what next".

---

## 1. Context and constraints

- **Single developer, ~7 days** for the MVP.
- **Data source:** anonymised Square CSV exports. Real data is *optional* —
  the project must run end-to-end on synthetic seed data so a reviewer can
  clone and run it without access to any real business.
- **Audience:** placement recruiters and interviewers. Every architectural
  decision must be explainable and defensible.
- **Non-goal:** multi-tenant SaaS. This is a single-business analytics tool.

---

## 2. Core architectural decision — vendor-neutral internal model

The single most important design decision in this project:

**The internal schema is not Square's schema.**

```
CSV export ──► Source adapter ──► Canonical model ──► Analytics layer ──► API ──► UI
             (Square-specific)   (vendor-neutral)
```

Square's export format is an external contract we do not control. Storing
their columns directly would couple the entire analytics layer to one
vendor's CSV layout — meaning a change to that format, or the addition of a
second data source, would require rewriting every downstream query.

Instead, each data source gets a thin **adapter** whose only job is mapping
that source's shape into our canonical model. Adding a second EPOS provider,
or migrating from CSV to the Square API later, means writing one new adapter
and changing nothing downstream.

This mirrors the real integration problem behind the project: three delivery
platforms (Deliveroo, Just Eat, Uber Eats) each expose differently-shaped
order data for what is conceptually the same event.

**Interview question this answers:** *"Why did you structure it this way?"*

---

## 3. Technology choices

| Layer | Choice | Rationale |
|---|---|---|
| API framework | FastAPI | Async support, Pydantic validation built in, auto-generated OpenAPI docs |
| Database | PostgreSQL | Production parity, concurrency, strict timezone-aware date/time types, mature migration tooling |
| ORM / migrations | SQLAlchemy 2.0 + Alembic | Versioned migrations are the professional signal; ad-hoc schema edits are not |
| Validation | Pydantic v2 | Same model layer validates API I/O *and* LLM structured output |
| Ingestion | pandas | CSV parsing, cleaning, deduplication |
| Forecasting | statsmodels + scikit-learn | Explainable models whose maths can be defended in interview |
| Frontend | Next.js + TypeScript + Recharts | Builds on existing Next.js exposure; maintains TS/React signal |
| Testing | pytest | |
| Local infra | Docker Compose | One-command setup — reviewers who can actually run it are more likely to |

### Decisions to be ready to defend

**PostgreSQL over SQLite.** Not a capability argument — SQLite has window
functions and adequate date handling, and would cope with this data volume.
The reasons are production readiness: concurrent write handling, richer and
stricter date/time types (`TIMESTAMPTZ`, proper timezone conversion),
first-class migration tooling, and parity between the local development
environment and what would actually be deployed. Developing against the same
engine you deploy to removes an entire class of environment-specific bugs.

**PostgreSQL over a time-series database (InfluxDB/TimescaleDB).** The data is
relational first (orders → items → products) and time-series second. Relational
integrity matters more here than time-series write throughput.

**No ORM-free raw SQL.** SQLAlchemy is used for models and migrations, but
analytics queries are written as explicit SQL aggregations rather than Python
loops over ORM objects — pushing computation to the database rather than
pulling rows into application memory.

**Varchar columns with application-level enums, not native Postgres enums.**
`orders.channel` and `import_batches.status` are stored as `VARCHAR` and
validated by Python/Pydantic enums in the application layer. Native Postgres
enum types require a migration to add a single new value and are awkward to
reorder or remove from. During ingestion of real-world data, new channels are
likely to be discovered, and the schema should absorb that without a migration
per value. Validation strictness is preserved — it simply lives in the
application rather than the database.

Trade-off to acknowledge if asked: this moves the guarantee out of the
database, so a process writing directly to Postgres could insert an invalid
value. Accepted here because the application is the sole writer.

**No authentication in the MVP.** Deliberate scoping decision, not an
oversight: this is a single-tenant tool, and a generic JWT implementation
would consume a day of build time while adding little differentiated value.
Documented under Future Work.

---

## 4. Data model

```
products
  id, name, category, created_at

orders
  id, source_order_id, source, occurred_at, channel,
  gross_amount, discount_amount, net_amount, item_count
  UNIQUE (source, source_order_id)

order_items
  id, order_id → orders, product_id → products,
  quantity, unit_price, line_total

import_batches
  id, filename, file_checksum, row_count, status,
  imported_at, error_log
  UNIQUE (file_checksum)
```

### Design notes

**`import_batches.file_checksum`** makes imports idempotent at the file level.
Re-uploading the same export does not double-count revenue. Duplicate ingestion
is one of the most common real-world data pipeline failures.

**`UNIQUE (source, source_order_id)`** enforces row-level deduplication at the
database layer rather than in application code — the constraint holds even if
the importer has a bug.

**Money is stored in integer minor units (pence), not floats.** Floating-point
arithmetic on currency accumulates rounding errors.

**`channel`** distinguishes in-store / collection / delivery, enabling the
channel-mix analysis that reflects the real business question of whether
third-party delivery is worth its commission.

---

## 5. MVP scope

### In scope

1. **CSV ingestion** — upload, validate, import with dedup and row-level error reporting
2. **Revenue over time** — daily/weekly aggregation, date-range filtering
3. **Peak-hour analysis** — day-of-week × hour-of-day heatmap
4. **Product performance** — top/bottom performers by revenue and volume
5. **Channel mix** — in-store vs collection vs delivery
6. **Demand forecasting** — with baseline comparison and honest backtest evaluation
7. **Natural-language query** — constrained, non-SQL-generating (see §7)
8. **Synthetic seed data** — realistic generated dataset so the repo runs standalone

### Explicitly out of scope

Authentication · inventory management · staff/rota analytics · real-time
streaming · multi-tenancy · mobile app

Each is a deliberate cut, recorded in Future Work. Scope discipline is itself
a defensible engineering decision.

---

## 6. Forecasting — evaluation over presentation

The requirement is not "produce a forecast chart". It is **produce a forecast
whose quality is honestly measured**.

Required approach:

1. **Baseline first** — seasonal naive (this Tuesday ≈ last Tuesday). Any real
   model must beat this to justify its existence.
2. **Model** — regression with calendar features (day of week, hour of day,
   holiday flags), or SARIMA if the series is well-behaved.
3. **Backtest** — hold out a trailing period; evaluate with MAE and MAPE.
4. **Report the result honestly** — including if the model fails to beat the
   baseline. A documented negative result demonstrates more engineering
   maturity than an unvalidated chart.

Written up in the README as a short evaluation section with the actual numbers.

---

## 7. Natural-language query — constrained by design

**The LLM does not generate SQL.** This is the project's strongest security
discussion.

```
User question
   ↓
LLM  ──► structured JSON query spec (metric, dimension, filters, date range)
   ↓
Pydantic validation  ──► reject anything outside the allowed enums
   ↓
Whitelisted query builder  ──► parameterised SQL
   ↓
Database  ──► result set
   ↓
LLM  ──► natural-language interpretation of the numbers
```

The model selects from an **enumerated** set of metrics, dimensions and
filters. It never emits SQL, table names, or column names. An invalid or
adversarial spec is rejected by validation before reaching the database.

**Interview question this answers:** *"What happens if someone prompt-injects
your NL interface?"* — The attack surface is a validated JSON schema against a
closed enum, not a query string. The worst case is a rejected request, not
arbitrary SQL execution.

Additional handling: LLM API failures degrade gracefully (the dashboard remains
fully functional without the NL feature); requests are timed out and retried
with backoff.

---

## 8. Project structure

```
restaurant-intelligence/
├── docker-compose.yml
├── ARCHITECTURE.md
├── README.md
├── backend/
│   ├── alembic/                  # migrations
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── models/               # SQLAlchemy models
│   │   ├── schemas/              # Pydantic models
│   │   ├── adapters/             # source-specific importers
│   │   │   ├── base.py           # adapter interface
│   │   │   └── square.py
│   │   ├── analytics/            # SQL aggregation queries
│   │   ├── forecasting/          # baseline, model, backtest
│   │   ├── nlq/                  # spec schema, builder, LLM client
│   │   └── api/                  # route handlers
│   ├── scripts/seed.py
│   └── tests/
└── frontend/
    └── src/
        ├── app/
        ├── components/
        └── lib/
```

---

## 9. Build milestones

| # | Date | Deliverable |
|---|---|---|
| M1 | Fri 28 Aug | Repo, Docker Compose, SQLAlchemy models, first Alembic migration, health endpoint |
| M2 | Sat 29 Aug | CSV adapter, checksum dedup, validation + error reporting, upload endpoint, seed script, importer tests |
| M3 | Sun 30 Aug | Revenue time-series, peak-hour, channel-mix aggregations |
| M4 | Mon 31 Aug | Product analytics, pytest suite, error-handling pass |
| M5 | Tue 1 Sep | Next.js dashboard with Recharts and date filtering |
| M6 | Wed 2 Sep | Forecasting: baseline, model, backtest, evaluation writeup |
| M7 | Thu 3 Sep | NL query pipeline, README, screenshots, deployment |

Deployment target: Railway or Fly.io (both handle FastAPI + Postgres simply).

---

## 10. Working method

This project is built pair-programming style, feature by feature. For each
significant feature:

1. **Design** — what, why, alternatives, trade-offs — *before* code
2. **Implement**
3. **Teach** — file responsibilities, data flow, unfamiliar syntax, patterns used
4. **Challenge** — interviewer-style questions, answered before being told
5. **Review** — senior-engineer PR review: abstractions, security, naming,
   duplication, performance, edge cases, missing tests

Commits happen at logical feature boundaries, not in one final dump. The
commit history is itself part of the portfolio artefact.

**Standing instruction:** if an implementation choice would leave the developer
unable to explain the system in an interview, flag it rather than proceeding.

---

## 11. Future work

- Direct Square API integration (replacing manual CSV export)
- Authentication and multi-tenancy
- Inventory and cost-of-goods analysis → true margin rather than revenue
- Staff scheduling recommendations driven by the peak-hour model
- Additional source adapters (Toast, Lightspeed, delivery platform exports)
- CI pipeline running tests on push
