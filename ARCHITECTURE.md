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

This decision was vindicated within a week of being made. The first real Square
export contained 71 orders with a combined "Eat in, Takeaway" dining option,
requiring a new `mixed` channel value. Adding it cost one line of Python and
zero migrations. The same export also required two further varchar-backed
enums (`orders.event_type`, `products.kind`) and one more (`import_files.role`),
all following the same pattern.

**No authentication in the MVP.** Deliberate scoping decision, not an
oversight: this is a single-tenant tool, and a generic JWT implementation
would consume a day of build time while adding little differentiated value.
Documented under Future Work.

---

## 4. Data model

```
products
  id, name, variation, category, kind, created_at
  UNIQUE (name, variation)

orders
  id, source_order_id, source, occurred_at, channel, event_type,
  source_payment_id, gross_amount, discount_amount, net_amount,
  item_count, import_batch_id → import_batches (nullable)
  UNIQUE (source, source_order_id)
  INDEX (source, source_payment_id)      -- non-unique, see below

order_items
  id, order_id → orders, product_id → products,
  quantity, unit_price, line_total

import_batches
  id, label, period_start (date), period_end (date),
  status, imported_at, error_log

import_files
  id, import_batch_id → import_batches, role, filename,
  file_checksum, row_count, rows_imported, rows_skipped
  UNIQUE (file_checksum)
  UNIQUE (import_batch_id, role)
```

### Design notes

**`import_files.file_checksum`** makes imports idempotent at the file level.
Re-uploading the same export does not double-count revenue. Duplicate ingestion
is one of the most common real-world data pipeline failures.

**A batch is several files.** A logical Square import is Transactions + Items
Detail + an optional Items Summary, so file identity was split out of
`import_batches` into `import_files`. The two tables hold two different
concerns that were originally conflated: *idempotency is a property of a file;
reconciliation is a property of a batch.* `UNIQUE (import_batch_id, role)`
enforces at most one file per role per batch.

The importer **preflights every supplied checksum before creating a batch or
touching sales data.** If any file has already been ingested, the whole
operation is rejected up front — so a rejected import cannot leave an orphaned
batch or a half-written set of orders behind.

**`import_batches.period_start` / `period_end`** state the batch's actual data
coverage, derived from parsed rows rather than filenames. The first real export
proved filenames unreliable: the Items Summary was named for a period ending
2 September while covering the same 1–31 August as its siblings. `label` is a
human-readable name only, never a source of truth.

They are `DATE` and **inclusive** at both ends — calendar coverage ("1–31
August"), not instants in time. A coverage period has no meaningful moment or
UTC offset, so storing it as `TIMESTAMPTZ` would imply a precision it does not
have and invite pointless timezone conversion. This is a deliberate contrast
with `orders.occurred_at`, which *is* an instant and is therefore `TIMESTAMPTZ`:
the distinction is between *when something happened* and *which days a dataset
covers*.

The bounds are business-local (Europe/London) calendar dates taken from the
export's own date column, not from UTC-converted timestamps. An order at 00:30
on 1 August BST is 23:30 on 31 July UTC, so deriving bounds from instants would
report coverage beginning a day early.

**Querying `orders.occurred_at` for a batch's period.** The period is inclusive
calendar dates; `occurred_at` is a UTC instant. Bridging the two requires a
**half-open interval** whose boundaries are interpreted in `Europe/London`
first and only then converted to UTC:

```
occurred_at >= local_midnight(period_start)              -- inclusive
occurred_at <  local_midnight(period_end + 1 day)        -- exclusive
```

Both properties matter:

*Half-open, not closed.* Comparing `occurred_at <= period_end` coerces the date
to midnight and silently discards almost the whole final day — a full day of
revenue lost to an off-by-one that no error message reports.

*Local-then-convert, not a fixed offset.* The UK is UTC+1 in summer and UTC+0 in
winter, so the same calendar range maps to different instants by season, and a
range spanning the switch has boundaries with **different** offsets:

| Period | Resolves to |
|---|---|
| 1–31 Aug 2026 (BST) | `>= 2026-07-31 23:00Z` … `< 2026-08-31 23:00Z` |
| 1–31 Jan 2026 (GMT) | `>= 2026-01-01 00:00Z` … `< 2026-02-01 00:00Z` |
| 1–31 Oct 2026 (BST→GMT) | `>= 2026-09-30 23:00Z` … `< 2026-11-01 00:00Z` |

The October range is 31 days *and one hour* in absolute terms. Any approach
that adds a constant offset, or treats local dates as if they were UTC, is
wrong for two of these three cases.

The same rule governs daily and hourly aggregation in §5: grouping must happen
in `Europe/London`, not UTC, or the peak-hour heatmap shifts by an hour for
seven months of the year.

**`import_files.rows_imported` / `rows_skipped`** record row accounting.
Zero-value transactions are excluded from analytical orders, but the exclusion
is counted rather than silently dropped, with reasons in `error_log`.

**`UNIQUE (source, source_order_id)`** enforces row-level deduplication at the
database layer rather than in application code — the constraint holds even if
the importer has a bug.

**Money is stored in integer minor units (pence), not floats.** Floating-point
arithmetic on currency accumulates rounding errors.

The columns are `INTEGER`, not `BIGINT`, and this is deliberate. A signed
32-bit integer holds up to ~£21.4m *per row*, against a domain where a single
order is tens of pounds — several orders of magnitude of headroom. Aggregation
is unaffected: PostgreSQL's `SUM()` over an `INTEGER` column returns `BIGINT`,
so totals across years of trade cannot overflow either. `BIGINT` would double
the storage of every monetary column to buy range that this domain cannot use.

**`products` are keyed on `(name, variation)`, not name alone.** Square sells the
same item at multiple price points — the first export has 133 distinct item
names but 141 distinct (item, price point) pairs. Keying on name alone would
merge "Caffe Latte" Regular and Large into a single product at a blended price.
`variation` is `NOT NULL DEFAULT ''` rather than nullable because PostgreSQL
treats NULLs as *distinct* under a unique constraint, so a nullable column
would silently fail to deduplicate the majority of rows, which have no price
point at all. Category is deliberately excluded from the key: it is
functionally determined by (name, variation), and including it would fracture a
product into duplicates if Square recategorised it.

**`products.kind`** separates what is sold from what is operating revenue. Gift
vouchers are a liability at issuance and become revenue on redemption; counting
them as menu sales inflates the month and double-counts on redemption. They are
still ingested so reconciliation against Square's own totals stays exact — this
field is how analytics excludes them. It also types Square's open-price
"Custom Amount" line, which is real revenue with no catalogue product.

**`orders.event_type`** distinguishes sales from refunds. Square emits refunds
as separate rows with their own transaction id and negative amounts. Storing
them as orders keeps revenue arithmetic correct automatically — sums include
the negative — while this discriminator keeps order *counts* correct, since
counts and averages filter on `payment`. A dedicated `refunds` table is
deferred; `source_payment_id` means it can be built later from data already
captured rather than re-imported.

**`INDEX (source, source_payment_id)` is composite and deliberately not
unique.** A payment id is an external identifier scoped to its source system,
so it is only meaningful alongside `source`; and a refund shares its payment id
with the payment it reverses, so a unique constraint would reject valid data.
It is the only link between a refund and its original, which carry *different*
transaction ids.

**`channel`** distinguishes in-store / collection / delivery, enabling the
channel-mix analysis that reflects the real business question of whether
third-party delivery is worth its commission. Two further values exist because
the real export required them: `online` for Square Online orders, which carry no
fulfilment detail and must not be guessed into collection or delivery; and
`unknown`, used only for a refund whose original payment falls outside the
extraction window. Preserving such a refund with an honest `unknown` keeps the
ledger complete; dropping it would lose money from the totals.

**Refunds are normalised in a second pass.** Payments are processed first to
build a `(source, payment_id) → channel` lookup. A refund's channel is then
resolved in descending order of evidence:

1. **Inherit** from the payment being reversed, when that payment is in this
   extraction — the same commercial event, and the payment row carries the real
   fulfilment detail.
2. **Derive** from the refund's own `Source` + `Dining Option` via the ordinary
   mapping. Weaker, because refunds are often rung through the till rather than
   the original channel, but a refund whose `Source` really is "Deliveroo" *is*
   delivery, and discarding that evidence would be worse than using it.
3. **`unknown`** only when neither applies — still preserved, never dropped.

Refunds also bypass the zero-value and unresolved-channel exclusions that apply
to payments: a refund is a real financial event however its columns read. Square
reports one August refund with `Net Sales £0.00` and `Total Collected −£50.58`,
so a value test on net sales alone would silently discard it.

**Deletion semantics are chosen per relationship, not applied uniformly.**
Each foreign key encodes what the data *means*, so the database refuses
operations that would silently destroy history:

| Relationship | On delete | Rationale |
|---|---|---|
| `order_items.order_id` → `orders` | `CASCADE` | A line item has no meaning without its order. |
| `order_items.product_id` → `products` | `RESTRICT` | Order items are historical financial records. A product with sales history cannot be deleted; retiring it from the catalogue is a soft-delete. |
| `orders.import_batch_id` → `import_batches` | `RESTRICT` | An import batch is a lineage/audit record and cannot be removed while orders reference it. |

Rolling back an import is therefore an explicit, ordered operation — delete the
imported orders, then the batch — rather than an implicit side effect of a
foreign key. Destructive intent has to be stated.

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

## 5a. Analytics — metric definitions

Every analytics endpoint slices the same `orders` rows a different way, so the
definitions below are shared. All five views must reconcile to identical totals
for a given window; a permanent test asserts exactly that.

| Metric | Definition |
|---|---|
| **Net sales** | `SUM(net_amount)` over **all** orders, refunds included as negative amounts. The revenue actually taken. |
| **Gross sales** | `SUM(gross_amount)` — before discounts. |
| **Discounts** | `SUM(discount_amount)`, stored positive. `gross − discounts = net` holds at every level of aggregation. |
| **Payment order count** | Orders with `event_type = 'payment'`. Refunds are excluded. |
| **Refund event count** | Orders with `event_type = 'refund'`. |
| **Net units** | `SUM(item_count)`, which is signed — a refunded unit cancels its sale rather than counting twice. |
| **AOV** | Net sales ÷ payment order count, rounded half away from zero. **0** when there are no paid orders. |
| **Channel share** | A channel's percentage of paid orders, and of net sales. |

### Semantics that are easy to get wrong

**Refunds reduce financial metrics but are never counted as orders.** A refund
lowers net sales and net units while leaving the payment order count untouched.
This is what makes AOV meaningful: dividing revenue that includes refunds by a
count that includes them too would flatter a bad month twice over. The
`event_type` discriminator is what allows both to be true at once.

**Business time is `Europe/London`, not UTC.** Every bucket — day, week,
weekday, hour — is derived from `occurred_at AT TIME ZONE 'Europe/London'`.
Grouping on UTC would file every order between midnight and 01:00 BST into the
previous day and shift the whole trading profile an hour for seven months of the
year. That produces a plausible-looking peak-hour chart that is simply wrong,
which is worse than an error.

**Inclusive API dates become a half-open UTC window.** `start_date` and
`end_date` are inclusive local calendar dates. They are converted once, in
`app/analytics/windows.py`, to:

```
occurred_at >= local_midnight(start_date)
occurred_at <  local_midnight(end_date + 1 day)
```

The filter is applied to the raw `occurred_at` column so it stays sargable and
can use `ix_orders_occurred_at`; only the *grouping* expression converts to
local time. Writing the filter itself against a converted column would be
equivalent in meaning but would force every row to be examined.

**Weekly buckets are Monday-based and may be labelled before `start_date`.**
Requesting 1–31 August weekly returns a first bucket of 27 July — the Monday of
the week 1 August falls in, carrying only 1–2 August. A partial week is reported
under the Monday it belongs to rather than being split or dropped. This matches
PostgreSQL's `date_trunc('week', …)`, so Python-side scaffolding and SQL-side
grouping agree.

**Day-of-week and peak-hour results aggregate occurrences, not dates.** A
weekday row sums *every* Monday in the range into one figure; a peak-hour cell
is `(weekday, hour)` across the whole window. Neither represents an individual
calendar date — "Sunday 11:00 = 96 orders" means 96 orders across all the
Sundays requested.

**Channel percentages are rounded independently and may not total exactly 100.**
Each share is rounded to two decimal places on its own, so a five-channel month
can display 100.01% of orders and 99.99% of sales. The underlying values sum
exactly; a consumer needing a guaranteed 100 should derive the final slice as
the remainder. A share of net sales is `null` when the period's total is not
positive — a share of zero is undefined, and a share of a negative total is
computable but meaningless.

**Empty periods are explicit, not missing.** Daily and weekly series are padded
so a closed day appears as a zero bucket; day-of-week always returns seven rows;
peak-hours always returns all 168 cells. A gap and a zero mean different things
to a chart, and "the shop was shut" should be visible.

**Requests are capped at 366 days**, which bounds both the work a single query
can ask for and the size of the response.

---

## 5b. Product and basket analytics — M4 semantics

**Grain is `(name, variation)`.** "Caffe Latte / Regular" and "Caffe Latte /
Large" are different products at different prices and are never merged. The
first real export had 133 item names but 141 (item, price point) pairs; keying
on name alone would blend two prices into one meaningless average.

**Discounts are exact, not apportioned.** `order_items.discount_amount` stores
the per-line value Square reports, so a staff discount on one item of a basket
stays on that item. An earlier draft apportioned the order total pro-rata by
line value; measured against August that was exact for only 30% of discount
value (£231.40 of £767.31), because 26 of 73 discounted orders held more than
one product. `discount_rate = discount_amount / gross_sales`, null when gross
is not positive.

**Menu vs non-menu.** Product analytics default to `kind = menu_item`. Gift
vouchers are a liability at issuance rather than menu revenue, and Square's
open-price "Custom Amount" line has no menu identity. Both stay in the database
so imports reconcile against the source, and both are filtered — never deleted.
August: menu £46,915.91 + vouchers £40.00 + custom £238.17 = £47,194.08 exactly.

**Comparable-period movement** compares a window against the equal-length local
date range immediately preceding it. A percentage change is reported only when
the previous period's net sales was positive; growth from zero is undefined,
not infinite, and is reported as `new_in_period`. A fall to zero from a positive
base is a well-defined −100% and stays `comparable`.

**Basket association.** Co-occurrence is over DISTINCT `(payment order,
product)` pairs, so quantity and repeated lines never inflate a count, and
refunds are excluded — a refund neither creates nor cancels the fact that two
items were bought together.

```
support(A,B)    = orders containing both / eligible payment orders
confidence(A→B) = orders containing both / orders containing A
lift(A,B)       = support(A,B) / (support(A) × support(B))
```

Each unordered pair appears once, enforced by a `product_id <` self-join, which
also makes (A,A) impossible.

**Minimum-pair caution.** Lift is reported alongside the raw pair count because
a pair seen once can show a lift above 100 — August's unthresholded ranking is
led by two single-occurrence pairs at lift 100.1 and 90.1. Endpoints take a
`min_pair_orders` threshold, and no significance testing is claimed.

**Evidence, not recommendations.** `/analytics/menu/evidence` reports what was
measured. It deliberately contains nothing that says a product should be
repriced, promoted or removed: those claims need cost, margin and elasticity
data this system does not hold. Status fields describe arithmetic only
(`comparable`, `new_in_period`, `increasing`), never a verdict.

**Planner statistics are refreshed after a successful import.** A bulk import
leaves PostgreSQL with no statistics for the affected tables until autovacuum
catches up, and in that window the planner falls back to nested loops — the
basket pair query measured 1,630 ms before `ANALYZE` against 7 ms after. The
importer therefore runs `ANALYZE` on `orders`, `order_items` and `products`
once its transaction has committed.

This is housekeeping, not correctness: every figure is identical either way,
only the plan changes. It runs on the success path only, so a rejected or failed
import never triggers it, and a failure is logged and swallowed — nothing
maintenance does may turn a committed business import into a failed one, or
surface a database error to an API caller.

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
