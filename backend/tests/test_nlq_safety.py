"""The safety boundary, asserted against the source itself.

The other M7 tests show that a bad request is rejected. These show something
stronger and more durable: that the capability to execute caller-supplied SQL
does not exist in this layer at all, so there is nothing for a future change to
accidentally re-expose.

Source inspection is used deliberately. A behavioural test can only prove that
the paths it thought to try are closed; reading the module tells you whether a
path exists.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app import nlq
from app.api import nlq as nlq_api
from app.nlq import evidence, executor, fields, operations, requests, resolution
from app.nlq.operations import Operation

MODULES = [nlq, evidence, executor, fields, operations, requests, resolution, nlq_api]
SOURCES = {module.__name__: Path(inspect.getfile(module)) for module in MODULES}


def trees():
    for name, path in SOURCES.items():
        yield name, ast.parse(path.read_text())


# --- no raw SQL execution path -----------------------------------------------


def test_no_module_can_execute_a_text_query():
    """`sqlalchemy.text` is the only way to turn a string into SQL, and nothing
    here imports it."""
    for name, tree in trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy":
                imported = {alias.name for alias in node.names}
                assert "text" not in imported, name
                assert "literal_column" not in imported, name
            if isinstance(node, ast.Attribute) and node.attr in (
                "text", "literal_column", "exec_driver_sql",
            ):
                pytest.fail(f"{name} references {node.attr}")


def test_no_module_calls_a_dynamic_evaluator():
    """eval/exec/compile/__import__ would let a validated string become code."""
    forbidden = {"eval", "exec", "compile", "__import__", "globals", "locals"}
    for name, tree in trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden, f"{name} calls {node.func.id}"


def test_no_module_selects_code_by_attribute_name():
    """`getattr(self, request.something)` would make the dispatch table
    decorative."""
    for name, tree in trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"getattr", "setattr"}, name


def test_no_sql_is_built_by_string_formatting():
    """No f-string, %-format or concatenation anywhere near a SQL keyword."""
    keywords = ("select ", "insert ", "update ", "delete ", "drop ", "truncate ",
                "union ", " from ", " where ")
    for name, path in SOURCES.items():
        for line in path.read_text().splitlines():
            stripped = line.strip()
            # Prose in docstrings and comments legitimately names SQL; only
            # executable lines are of interest.
            if stripped.startswith("#") or stripped.startswith(('"', "'")):
                continue
            lowered = line.lower()
            if any(keyword in lowered for keyword in keywords):
                assert "f'" not in line and 'f"' not in line, f"{name}: {line}"
                assert "%" not in line, f"{name}: {line}"
                assert ".format(" not in line, f"{name}: {line}"


def test_the_public_surface_offers_no_sql_entry_point():
    """The names a future integrator might reach for do not exist."""
    for forbidden in ("execute_sql", "run_query", "raw_query", "sql", "query_text"):
        assert not hasattr(nlq, forbidden)
        assert not hasattr(executor.AnalyticsExecutor, forbidden)


def test_the_executor_exposes_exactly_one_entry_point():
    public = [
        name
        for name in vars(executor.AnalyticsExecutor)
        if not name.startswith("_")
    ]
    assert public == ["execute"]


def test_no_request_field_accepts_a_table_or_column_name():
    """Nothing in the contract lets a caller name a relation."""
    forbidden = {"table", "tables", "column", "columns", "select", "where",
                 "group_by", "order_by", "sql", "expression", "filter", "having"}
    for model in requests.AnalyticsRequest.__origin__.__args__:
        assert not (set(model.model_fields) & forbidden), model.__name__


def test_every_request_model_forbids_extra_fields():
    for model in requests.AnalyticsRequest.__origin__.__args__:
        assert model.model_config.get("extra") == "forbid", model.__name__
        assert model.model_config.get("frozen") is True, model.__name__


# --- the whitelist is closed -------------------------------------------------


def test_the_operation_enum_has_no_escape_hatch():
    values = {o.value for o in Operation}
    assert not (values & {"custom", "raw", "sql", "arbitrary", "passthrough"})
    # Every member is a plain lower_snake identifier, not something that could
    # be mistaken for an expression.
    assert all(value.replace("_", "").isalnum() for value in values)


def test_every_operation_has_exactly_one_request_model():
    models = requests.AnalyticsRequest.__origin__.__args__
    tagged = [m.model_fields["operation"].annotation for m in models]
    assert len(tagged) == len(Operation)
    assert len(set(tagged)) == len(Operation)


def test_the_executor_handles_every_operation_and_nothing_else(session_factory):
    from app.analytics.service import AnalyticsService
    from app.forecasting.service import ForecastService
    from app.nlq.resolution import ProductResolver

    instance = executor.AnalyticsExecutor(
        analytics=AnalyticsService(session_factory),
        forecasts=ForecastService(session_factory),
        resolver=ProductResolver(session_factory),
    )
    assert set(instance._dispatch) == set(Operation)


def test_the_ai_layer_owns_no_metric_definition():
    """M7 consumes M3-M6; it does not reimplement it.

    The resolver is the single exception, and what it selects is a catalogue
    row by name — no measure, no aggregate, nothing that could become a second
    definition of net sales. Every number in an evidence bundle therefore comes
    from the same services the HTTP API and the dashboard read.
    """
    for name, tree in trees():
        if name == "app.nlq.resolution":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "select", f"{name} builds its own query"


def test_the_resolver_computes_no_business_measure():
    """It reads catalogue identity, and counts catalogue rows. Nothing more.

    `count()` over `products` is permitted and is the one aggregate here: M7
    needs the catalogue size to tell a planner when the list it was shown is
    truncated. It touches no order, no money and no quantity, so it cannot
    become a second definition of anything.

    `sum`, `avg`, `min` and `max` stay banned — those are how a measure gets
    computed, and every measure in this system is defined once, in M3-M6.
    """
    tree = ast.parse(SOURCES["app.nlq.resolution"].read_text())
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not (called & {"sum", "avg", "min", "max"})


def test_the_resolver_reads_only_the_product_catalogue():
    """The catalogue listing widened what the resolver RETURNS, not which
    tables it can reach.

    Checked on the imported models rather than by scanning the text: `order_by`
    contains "order", and the module's docstring legitimately discusses orders.
    A module can only query a table whose model it imports.
    """
    tree = ast.parse(SOURCES["app.nlq.resolution"].read_text())
    models = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "app.models"
        )
        for alias in node.names
    }
    assert models == {"Product"}


def test_only_the_resolver_touches_the_database_directly():
    """And it does one thing: look a product name up in the catalogue."""
    querying = [
        name for name, tree in trees()
        if any(
            isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy"
            for node in ast.walk(tree)
        )
    ]
    assert querying == ["app.nlq.resolution"]
