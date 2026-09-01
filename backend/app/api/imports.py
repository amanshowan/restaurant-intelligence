"""Import endpoints.

The route's only jobs are transport concerns: spool uploads to disk safely,
hand them to the import service, and translate its outcomes into HTTP. All
parsing, normalisation, persistence and reconciliation live in the service
layer (ARCHITECTURE.md §2) and are not duplicated here.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.adapters.base import SourceFormatError, SourceSchemaError
from app.api.deps import get_import_service
from app.schemas.imports import ErrorResponse, ImportSummary, ReconciliationResult
from app.services.importer import (
    ConflictingOrderError,
    ImportError_,
    ImportOutcome,
    ImportRejected,
    ImportRequest,
    ReconciliationError,
    SquareImportService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["imports"])

#: Per-file ceiling. The largest real monthly export observed is ~10 MB
#: (7,887 item rows in UTF-16, which doubles the byte size of plain ASCII);
#: 64 MB leaves generous headroom for a busier site or a longer period while
#: still bounding what one request can spool to disk.
MAX_FILE_BYTES = 64 * 1024 * 1024
#: Ceiling across all files in one request.
MAX_REQUEST_BYTES = 160 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024

#: Starlette renamed this constant; resolve whichever the installed version has.
UNPROCESSABLE = (
    status.HTTP_422_UNPROCESSABLE_CONTENT
    if hasattr(status, "HTTP_422_UNPROCESSABLE_CONTENT")
    else status.HTTP_422_UNPROCESSABLE_ENTITY  # older starlette
)

MAX_LABEL_LENGTH = 255
#: import_files.filename is VARCHAR(255).
MAX_FILENAME_LENGTH = 255


def _safe_filename(raw: str | None, fallback: str) -> str:
    """Reduce a client-supplied filename to a bare, bounded basename.

    Client filenames are untrusted input: they may contain directory
    separators, traversal sequences, or be long enough to overflow the column
    they are stored in. Only the basename is kept, and only for display and
    audit — never for deriving coverage dates.
    """
    candidate = Path(raw or "").name.strip()
    if not candidate or candidate in {".", ".."}:
        return fallback
    return candidate[:MAX_FILENAME_LENGTH]


def _spool(upload: UploadFile, destination: Path, budget: list[int]) -> None:
    """Stream an upload to disk, enforcing size limits as we go.

    Counting during the copy is what makes the limit real: checking a declared
    Content-Length would trust the client, and reading the whole file into
    memory first would defeat the purpose of having a limit at all.
    """
    written = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as out:
        while chunk := upload.file.read(CHUNK_BYTES):
            written += len(chunk)
            budget[0] += len(chunk)
            if written > MAX_FILE_BYTES:
                raise _error(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    "file_too_large",
                    f"file exceeds the {MAX_FILE_BYTES // (1024 * 1024)} MB "
                    "per-file limit",
                )
            if budget[0] > MAX_REQUEST_BYTES:
                raise _error(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    "request_too_large",
                    f"request exceeds the {MAX_REQUEST_BYTES // (1024 * 1024)} MB "
                    "total upload limit",
                )
            out.write(chunk)


def _to_summary(outcome: ImportOutcome) -> ImportSummary:
    r = outcome.reconciliation
    return ImportSummary(
        batch_id=outcome.batch_id,
        status=outcome.status,
        label=outcome.label,
        period_start=outcome.period_start,
        period_end=outcome.period_end,
        orders_imported=outcome.orders_created,
        order_items_imported=outcome.order_items_created,
        products_created=outcome.products_created,
        products_reused=outcome.products_reused,
        rows_skipped=outcome.rows_skipped,
        issue_counts=outcome.issue_counts(),
        net_sales_pence=outcome.net_sales_pence,
        reconciliation=ReconciliationResult(
            performed=r.performed,
            matches=r.matches,
            net_sales_pence_ours=r.net_sales_ours,
            net_sales_pence_theirs=r.net_sales_theirs,
            line_totals_pence_ours=r.line_totals_ours,
            line_totals_pence_theirs=r.line_totals_theirs,
            units_ours=r.units_ours,
            units_theirs=r.units_theirs,
        ),
    )


@router.post(
    "/square",
    response_model=ImportSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Import a Square export set",
    description=(
        "Accepts one logical Square import: a Transactions export, an Items "
        "Detail export, and optionally an Items Summary used only to reconcile "
        "the result. Files must be Square's native format — UTF-16, "
        "tab-delimited, despite the .csv extension.\n\n"
        "The coverage period is derived from the file contents; client "
        "filenames are never trusted for dates. The whole import is atomic: if "
        "any part fails, no sales data is written."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Malformed request"},
        409: {
            "model": ErrorResponse,
            "description": (
                "A supplied file was already ingested, or an order exists with "
                "conflicting content"
            ),
        },
        413: {"model": ErrorResponse, "description": "Upload too large"},
        422: {
            "model": ErrorResponse,
            "description": "Not a valid Square export, or reconciliation failed",
        },
        500: {"model": ErrorResponse, "description": "Unexpected server error"},
    },
)
def import_square_export(
    transactions: UploadFile = File(..., description="Square Transactions export"),
    items: UploadFile = File(..., description="Square Items Detail export"),
    summary: UploadFile | None = File(
        None, description="Square Items Summary export (reconciliation only)"
    ),
    label: str | None = Form(
        None, description='Human-readable name for the batch, e.g. "august-2026"'
    ),
    service: SquareImportService = Depends(get_import_service),
) -> ImportSummary:
    if label is not None and len(label) > MAX_LABEL_LENGTH:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "invalid_request",
            f"label exceeds {MAX_LABEL_LENGTH} characters",
        )

    # TemporaryDirectory removes the spooled uploads on every exit path,
    # including the error paths below.
    with tempfile.TemporaryDirectory(prefix="square-import-") as workspace:
        root = Path(workspace)
        budget = [0]

        # Each file goes in its own subdirectory so that the client's original
        # basename is preserved for audit without two uploads colliding.
        tx_path = root / "transactions" / _safe_filename(
            transactions.filename, "transactions.csv"
        )
        items_path = root / "items" / _safe_filename(items.filename, "items.csv")
        _spool(transactions, tx_path, budget)
        _spool(items, items_path, budget)

        summary_path = None
        if summary is not None and summary.filename:
            summary_path = root / "summary" / _safe_filename(
                summary.filename, "summary.csv"
            )
            _spool(summary, summary_path, budget)

        request = ImportRequest(
            transactions=tx_path,
            items=items_path,
            summary=summary_path,
            label=(label or None),
        )

        try:
            return _to_summary(service.run(request))

        except ImportRejected as exc:
            raise _error(status.HTTP_409_CONFLICT, "duplicate_file", str(exc)) from exc

        except ConflictingOrderError as exc:
            raise _error(
                status.HTTP_409_CONFLICT, "conflicting_order", str(exc)
            ) from exc

        except ReconciliationError as exc:
            raise _error(
                UNPROCESSABLE, "reconciliation_failed", str(exc)
            ) from exc

        except (SourceFormatError, SourceSchemaError) as exc:
            raise _error(
                UNPROCESSABLE, "invalid_source_file", str(exc)
            ) from exc

        except ImportError_ as exc:
            # A wrapped adapter failure. The service records the cause; the
            # client gets the message, never a traceback.
            raise _error(
                UNPROCESSABLE, "import_failed", str(exc)
            ) from exc

        except Exception:
            # Anything unanticipated — a database outage, a bug. Logged in full
            # server-side; the client is told nothing about internals.
            logger.exception("unexpected failure during Square import")
            raise _error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "internal_error",
                "An internal error occurred while processing the import.",
            ) from None


def _error(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"detail": detail, "code": code})
