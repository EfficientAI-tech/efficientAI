"""CSV-driven call import routes.

Users upload a CSV plus a per-batch column mapping (CSV header -> system
field). The backend persists a CallImport batch + one CallImportRow per
line, then fans the rows out to the Celery ``imports`` queue where each
row is downloaded using the telephony credential pinned on the batch.
When a row has no recording URL, the worker resolves it via the chosen
provider's call detail endpoint (Exotel today; Plivo CSVs must include
the URL).
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from loguru import logger
from pydantic import ValidationError
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_api_key,
    get_organization_id,
    get_workspace_id,
    require_enterprise_feature,
)
from app.models.database import (
    CallImport,
    CallImportRow,
    CallImportTag,
    TelephonyIntegration,
)
from app.models.enums import (
    CallImportRowStatus,
    CallImportStatus,
)
from app.models.schemas import (
    CallImportColumnMapping,
    CallImportDetailResponse,
    CallImportInsightsMetric,
    CallImportInsightsResponse,
    CallImportInsightsRunPoint,
    CallImportListResponse,
    CallImportMetricAggregate,
    CallImportPreviewResponse,
    CallImportPreviewSheet,
    CallImportResponse,
    CallImportRowBulkDelete,
    CallImportRowBulkDeleteResponse,
    CallImportRowResponse,
    CallImportTranscribeRequest,
    CallImportTranscribeResponse,
    CallImportUpdate,
    CallImportUploadResponse,
)


router = APIRouter(
    prefix="/call-imports",
    tags=["Call Imports"],
    dependencies=[Depends(require_enterprise_feature("call_imports"))],
)


def _normalize_dataset(raw: Optional[str]) -> Optional[str]:
    """Trim and treat empty strings as 'no dataset' (NULL)."""
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None


def _resolve_tags(
    db: Session, organization_id: UUID, tag_ids: Optional[List[UUID]]
) -> List[CallImportTag]:
    """Look up tag rows by id, scoped to the organization.

    Raises HTTPException(400) if any id is unknown for the org.
    """
    if not tag_ids:
        return []
    rows = (
        db.query(CallImportTag)
        .filter(
            CallImportTag.organization_id == organization_id,
            CallImportTag.id.in_(tag_ids),
        )
        .all()
    )
    found_ids = {row.id for row in rows}
    missing = [str(tag_id) for tag_id in tag_ids if tag_id not in found_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown call_import_tag id(s): {missing}",
        )
    return rows


MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB upload cap (CSV or Excel)

# File extensions accepted by the upload + preview endpoints. Keep in
# lockstep with the frontend ``accept`` attribute on the file picker.
CSV_EXTENSIONS = (".csv",)
XLSX_EXTENSIONS = (".xlsx", ".xlsm")
ALLOWED_EXTENSIONS = CSV_EXTENSIONS + XLSX_EXTENSIONS


def _file_format(filename: Optional[str]) -> Optional[str]:
    """Classify ``filename`` as ``'csv'`` / ``'xlsx'`` or ``None`` if unsupported."""
    if not filename:
        return None
    name = filename.lower()
    if name.endswith(CSV_EXTENSIONS):
        return "csv"
    if name.endswith(XLSX_EXTENSIONS):
        return "xlsx"
    return None


def _normalize_header(name: str) -> str:
    return (name or "").strip().lower()


def _header_lookup(fieldnames: List[str]) -> Dict[str, str]:
    """Map normalized header -> original header for case-insensitive lookup."""
    return {_normalize_header(h): h for h in fieldnames or []}


def _resolve_mapped_header(
    mapping_value: Optional[str], header_lookup: Dict[str, str]
) -> Optional[str]:
    """Translate a user-supplied CSV header into the actual column key.

    The frontend sends headers exactly as they appear in the source file,
    but we still normalize on the server so trailing whitespace / casing
    doesn't break matching. Returns the canonical fieldname or ``None``
    if not present in the file.
    """
    if not mapping_value:
        return None
    return header_lookup.get(_normalize_header(mapping_value))


def _xlsx_cell_to_str(value: Any) -> str:
    """Coerce an openpyxl cell value to the string the rest of the
    pipeline expects.

    openpyxl returns native Python types (int, float, datetime, bool,
    None). The CSV path always works with strings, so we mirror that:
    integers stringify cleanly (no ``.0`` suffix on whole-number floats),
    datetimes use ISO-8601, booleans use SQL-style ``TRUE`` / ``FALSE``.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    return str(value)


def _apply_mapping(
    fieldnames: List[str],
    rows_iter: Iterable[Dict[str, str]],
    mapping: CallImportColumnMapping,
    extra_columns: List[str],
    custom_column_mapping: Optional[Dict[str, str]] = None,
    *,
    source_label: str = "CSV",
) -> List[Dict[str, Any]]:
    """Validate ``mapping`` against ``fieldnames`` and project each row.

    Shared between the CSV and XLSX parse paths. Each input row in
    ``rows_iter`` is a dict whose keys are the original (case-preserved)
    headers from ``fieldnames`` and whose values are strings (already
    coerced from native Excel types for the xlsx path).

    The returned list has one entry per non-empty row with:
      * ``external_call_id`` (str, required - row dropped with 400 if blank)
      * ``recording_url`` (Optional[str])
      * ``transcript`` (Optional[str])
      * ``raw_columns`` (Dict[str, str]) of the original row keyed by the
        uploader's headers, restricted to mapped + ``extra_columns``.
    """
    header_lookup = _header_lookup(list(fieldnames))
    callid_h = _resolve_mapped_header(mapping.external_call_id, header_lookup)
    if not callid_h:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{source_label} does not contain the column "
                f"'{mapping.external_call_id}' mapped to External Call ID."
            ),
        )
    transcript_h = _resolve_mapped_header(mapping.transcript, header_lookup)
    if mapping.transcript and transcript_h is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{source_label} does not contain the column "
                f"'{mapping.transcript}' mapped to Transcript."
            ),
        )
    url_h = _resolve_mapped_header(mapping.recording_url, header_lookup)
    if mapping.recording_url and url_h is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{source_label} does not contain the column "
                f"'{mapping.recording_url}' mapped to Recording URL."
            ),
        )

    # Headers we must capture in raw_columns (mapped + extras + custom),
    # keyed by the canonical fieldname so reads always work regardless
    # of case. Custom-mapped headers are validated the same way as the
    # system fields so a typo surfaces as a 400 rather than a silent drop.
    custom_mapping = custom_column_mapping or {}
    for custom_name, custom_header in custom_mapping.items():
        canonical = _resolve_mapped_header(custom_header, header_lookup)
        if canonical is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{source_label} does not contain the column "
                    f"'{custom_header}' mapped to custom field '{custom_name}'."
                ),
            )

    keep_canonical: Dict[str, str] = {}
    for raw_header in [
        mapping.external_call_id,
        mapping.transcript,
        mapping.recording_url,
        *extra_columns,
        *custom_mapping.values(),
    ]:
        canonical = _resolve_mapped_header(raw_header, header_lookup)
        if canonical:
            # Preserve user-facing label (uploader's casing) as the key.
            keep_canonical[canonical] = raw_header  # type: ignore[assignment]

    parsed: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows_iter):
        call_id = (row.get(callid_h) or "").strip()
        url = (row.get(url_h) or "").strip() if url_h else ""
        transcript = (row.get(transcript_h) or "").strip() if transcript_h else ""
        # Fully blank line — skip silently to allow trailing newlines /
        # phantom empty rows that openpyxl sometimes yields.
        if not any((row.get(h) or "").strip() for h in (callid_h, url_h, transcript_h) if h):
            continue
        if not call_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Row {idx + 1} is missing the External Call ID column.",
            )

        raw_snapshot = {
            label: (row.get(canonical) or "").strip()
            for canonical, label in keep_canonical.items()
        }

        parsed.append(
            {
                "external_call_id": call_id,
                "recording_url": url or None,
                "transcript": transcript or None,
                "raw_columns": raw_snapshot,
            }
        )

    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{source_label} did not contain any data rows.",
        )

    return parsed


def _parse_csv(
    file_bytes: bytes,
    mapping: CallImportColumnMapping,
    extra_columns: List[str],
    custom_column_mapping: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Parse the CSV using ``mapping`` to find each system field.

    Thin wrapper that runs ``csv.DictReader`` and delegates the mapping /
    validation / row-projection logic to :func:`_apply_mapping`.
    """
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded CSV is empty.",
        )

    try:
        text_stream = io.StringIO(file_bytes.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV must be UTF-8 encoded.",
        )

    reader = csv.DictReader(text_stream)
    if not reader.fieldnames:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV is missing a header row.",
        )

    return _apply_mapping(
        list(reader.fieldnames),
        reader,
        mapping,
        extra_columns,
        custom_column_mapping,
        source_label="CSV",
    )


def _open_xlsx_workbook(file_bytes: bytes):
    """Open an xlsx/xlsm workbook from in-memory bytes (read-only stream).

    Imports openpyxl lazily so the module loads even in environments that
    haven't installed the optional dep yet (e.g. lightweight tooling
    images). Surfaces a clean 400 if openpyxl is missing or the file is
    not a valid Office Open XML workbook.
    """
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded Excel file is empty.",
        )
    try:
        from openpyxl import load_workbook  # type: ignore
        from openpyxl.utils.exceptions import InvalidFileException  # type: ignore
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Excel uploads require the 'openpyxl' package which is "
                "not installed in this environment."
            ),
        ) from exc

    try:
        return load_workbook(
            io.BytesIO(file_bytes),
            read_only=True,
            data_only=True,
        )
    except InvalidFileException as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File is not a valid .xlsx workbook: {exc}",
        ) from exc
    except Exception as exc:  # zipfile.BadZipFile etc.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not open Excel workbook: {exc}",
        ) from exc


def _xlsx_sheet_headers_and_rows(
    worksheet,
) -> Tuple[List[str], List[Dict[str, str]]]:
    """Read row 1 as headers and the rest as dicts of stringified cells.

    Empty trailing header cells are dropped. Duplicate headers preserve
    the first occurrence (matches ``csv.DictReader`` behavior, which
    silently drops duplicates).
    """
    iterator = worksheet.iter_rows(values_only=True)
    try:
        header_row = next(iterator)
    except StopIteration:
        return [], []

    headers: List[str] = []
    seen: set[str] = set()
    for cell in header_row:
        name = _xlsx_cell_to_str(cell).strip()
        if not name:
            # Stop at the first blank header — treats trailing empty
            # columns as not part of the table (matches typical Excel
            # workbook conventions).
            break
        norm = name.lower()
        if norm in seen:
            continue
        seen.add(norm)
        headers.append(name)

    rows: List[Dict[str, str]] = []
    for row in iterator:
        if row is None:
            continue
        # Pad / truncate to the header length so dict construction is
        # stable even when a row has fewer / extra cells than the header.
        cells = list(row[: len(headers)])
        if len(cells) < len(headers):
            cells.extend([None] * (len(headers) - len(cells)))
        if not any(_xlsx_cell_to_str(c).strip() for c in cells):
            # Skip fully-blank rows (openpyxl read_only routinely yields
            # trailing empties when the worksheet's used range exceeds
            # the actual data).
            continue
        rows.append(
            {
                header: _xlsx_cell_to_str(value)
                for header, value in zip(headers, cells)
            }
        )

    return headers, rows


def _parse_xlsx(
    file_bytes: bytes,
    sheet_name: Optional[str],
    mapping: CallImportColumnMapping,
    extra_columns: List[str],
    custom_column_mapping: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Parse a single worksheet from an xlsx/xlsm workbook.

    ``sheet_name`` must match one of the workbook's sheets (case
    insensitive whitespace-trimmed match). Returns the same shape as
    :func:`_parse_csv` so the upload handler can persist either format
    through the same code path.
    """
    if not sheet_name or not sheet_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sheet_name is required when uploading an Excel workbook.",
        )

    workbook = _open_xlsx_workbook(file_bytes)
    try:
        sheet_names = list(workbook.sheetnames)
        target_norm = sheet_name.strip().lower()
        match = next(
            (s for s in sheet_names if s.strip().lower() == target_norm),
            None,
        )
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Sheet '{sheet_name}' not found in workbook. "
                    f"Available sheets: {sheet_names}"
                ),
            )
        worksheet = workbook[match]
        headers, rows = _xlsx_sheet_headers_and_rows(worksheet)
    finally:
        workbook.close()

    if not headers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sheet '{sheet_name}' is missing a header row.",
        )

    return _apply_mapping(
        headers,
        rows,
        mapping,
        extra_columns,
        custom_column_mapping,
        source_label=f"Sheet '{sheet_name}'",
    )


def _csv_preview_sheets(
    file_bytes: bytes, filename: Optional[str]
) -> List[CallImportPreviewSheet]:
    """Build the synthetic single-sheet preview entry for a CSV upload."""
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded CSV is empty.",
        )
    try:
        text_stream = io.StringIO(file_bytes.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV must be UTF-8 encoded.",
        )
    reader = csv.DictReader(text_stream)
    if not reader.fieldnames:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV is missing a header row.",
        )
    headers = list(reader.fieldnames)
    row_count = 0
    for row in reader:
        # Match the parse-time skip: ignore fully blank rows so the
        # count the user sees lines up with what /upload will ingest.
        if any((v or "").strip() for v in row.values()):
            row_count += 1

    sheet_label = (filename or "sheet1").rsplit("/", 1)[-1] or "sheet1"
    return [
        CallImportPreviewSheet(
            name=sheet_label,
            headers=headers,
            row_count=row_count,
        )
    ]


def _xlsx_preview_sheets(file_bytes: bytes) -> List[CallImportPreviewSheet]:
    """List every worksheet in the workbook with its headers and row count."""
    workbook = _open_xlsx_workbook(file_bytes)
    sheets: List[CallImportPreviewSheet] = []
    try:
        for name in workbook.sheetnames:
            worksheet = workbook[name]
            headers, rows = _xlsx_sheet_headers_and_rows(worksheet)
            sheets.append(
                CallImportPreviewSheet(
                    name=name,
                    headers=headers,
                    row_count=len(rows),
                )
            )
    finally:
        workbook.close()
    return sheets


def _parse_json_form_field(name: str, raw: Optional[str], default):
    """Decode a JSON-encoded form field with a friendly 400 on bad JSON."""
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} must be valid JSON: {exc}",
        )


@router.post(
    "/preview",
    response_model=CallImportPreviewResponse,
    operation_id="previewCallImportFile",
)
async def preview_call_import_file(
    file: UploadFile = File(...),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> CallImportPreviewResponse:
    """Inspect an uploaded CSV / Excel file and return its sheets + headers.

    Drives the column-mapping UI without forcing the frontend to parse
    CSV / xlsx itself — keeps client and server in lockstep on quoted
    fields, encodings, and Excel cell coercion. CSVs return a single
    synthetic sheet named after the filename; Excel workbooks return one
    entry per worksheet (in workbook order).
    """
    del api_key, organization_id, workspace_id, db  # auth only

    fmt = _file_format(file.filename)
    if fmt is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported file format. Allowed extensions: "
                f"{', '.join(ALLOWED_EXTENSIONS)}."
            ),
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_UPLOAD_BYTES} bytes",
        )

    if fmt == "csv":
        sheets = _csv_preview_sheets(file_bytes, file.filename)
    else:
        sheets = _xlsx_preview_sheets(file_bytes)

    return CallImportPreviewResponse(format=fmt, sheets=sheets)


@router.post(
    "/upload",
    response_model=CallImportUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="uploadCallImportCsv",
)
async def upload_call_import_csv(
    file: UploadFile = File(...),
    provider: str = Form(
        ...,
        description=(
            "Telephony provider key (e.g. 'exotel', 'plivo'). Must match the "
            "selected telephony_integration_id's provider."
        ),
    ),
    telephony_integration_id: UUID = Form(
        ...,
        description=(
            "Specific TelephonyIntegration credential row to use when "
            "downloading recordings for this batch."
        ),
    ),
    column_mapping: str = Form(
        ...,
        description=(
            "JSON-encoded mapping from system fields to source header strings. "
            "Required key: external_call_id. Optional: transcript, recording_url."
        ),
    ),
    extra_columns: Optional[str] = Form(
        None,
        description=(
            "JSON-encoded list of additional source header strings to preserve "
            "verbatim into raw_columns for export."
        ),
    ),
    custom_column_mapping: Optional[str] = Form(
        None,
        description=(
            "JSON-encoded ``{custom_field_name: source_header}`` map for "
            "uploader-defined columns. The source cells under each mapped "
            "header are preserved per row and surface under the chosen "
            "custom name in the evaluation export."
        ),
    ),
    dataset: Optional[str] = Form(
        None,
        description=(
            "Optional free-text dataset label for high-level segregation. "
            "Empty strings are stored as NULL."
        ),
    ),
    tag_ids: Optional[List[UUID]] = Form(
        None,
        description="Optional list of CallImportTag ids to attach to the new batch.",
    ),
    sheet_name: Optional[str] = Form(
        None,
        description=(
            "Worksheet to import when the file is an Excel workbook "
            "(.xlsx / .xlsm). REQUIRED for Excel uploads. Ignored for CSV "
            "uploads (rejected with 400 if non-empty so typos surface "
            "instead of silently importing the wrong source)."
        ),
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> CallImportUploadResponse:
    """Accept a CSV / Excel file + column mapping and queue per-row jobs.

    The caller selects a specific telephony credential (so the worker uses
    *that* row to fetch recordings) and provides a column mapping so any
    layout works. Unmapped headers can be preserved via ``extra_columns``
    so they ride along into the eventual evaluation export.

    For multi-sheet Excel workbooks, the caller picks one sheet per upload
    via ``sheet_name`` — to import N sheets, send N separate uploads (one
    CallImport batch is created per sheet).

    The new batch is stamped with the active workspace (from the
    ``X-Workspace-Id`` header, falling back to the org's Default).
    """
    del api_key

    fmt = _file_format(file.filename)
    if fmt is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported file format. Allowed extensions: "
                f"{', '.join(ALLOWED_EXTENSIONS)}."
            ),
        )

    sheet_name_clean = (sheet_name or "").strip() or None
    if fmt == "csv" and sheet_name_clean is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sheet_name is not applicable to CSV uploads.",
        )
    if fmt == "xlsx" and sheet_name_clean is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sheet_name is required when uploading an Excel workbook.",
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_UPLOAD_BYTES} bytes",
        )

    mapping_payload = _parse_json_form_field("column_mapping", column_mapping, {})
    try:
        mapping = CallImportColumnMapping.model_validate(mapping_payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid column_mapping: {exc.errors()}",
        )

    extras_payload = _parse_json_form_field("extra_columns", extra_columns, [])
    if not isinstance(extras_payload, list) or not all(
        isinstance(item, str) for item in extras_payload
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="extra_columns must be a JSON array of header strings.",
        )
    # Strip blanks and de-duplicate (case-insensitive) while preserving order.
    seen = set()
    extras_clean: List[str] = []
    for item in extras_payload:
        norm = _normalize_header(item)
        if not norm or norm in seen:
            continue
        # Skip extras that collide with mapped fields - already captured.
        if norm in {
            _normalize_header(mapping.external_call_id),
            _normalize_header(mapping.transcript or ""),
            _normalize_header(mapping.recording_url or ""),
        }:
            continue
        seen.add(norm)
        extras_clean.append(item)

    custom_payload = _parse_json_form_field(
        "custom_column_mapping", custom_column_mapping, {}
    )
    if not isinstance(custom_payload, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in custom_payload.items()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="custom_column_mapping must be a JSON object of {name: csv_header}.",
        )
    system_field_names = {"external_call_id", "transcript", "recording_url"}
    custom_clean: Dict[str, str] = {}
    seen_custom_names: set[str] = set()
    for raw_name, raw_header in custom_payload.items():
        name = raw_name.strip()
        header = raw_header.strip()
        if not name or not header:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "custom_column_mapping entries must have non-empty "
                    "name and CSV header values."
                ),
            )
        if name in system_field_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Custom column name '{name}' collides with a built-in "
                    "system field. Use a different name."
                ),
            )
        if name.lower() in seen_custom_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate custom column name '{name}'.",
            )
        seen_custom_names.add(name.lower())
        custom_clean[name] = header

    integration = (
        db.query(TelephonyIntegration)
        .filter(
            TelephonyIntegration.id == telephony_integration_id,
            TelephonyIntegration.organization_id == organization_id,
        )
        .first()
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telephony credential not found for this organization.",
        )
    if (integration.provider or "").lower() != provider.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Selected credential is for provider '{integration.provider}', "
                f"but request specified '{provider}'."
            ),
        )
    if not integration.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected telephony credential is inactive.",
        )

    if fmt == "csv":
        rows = _parse_csv(file_bytes, mapping, extras_clean, custom_clean)
    else:
        rows = _parse_xlsx(
            file_bytes, sheet_name_clean, mapping, extras_clean, custom_clean
        )

    tag_rows = _resolve_tags(db, organization_id, tag_ids)

    stored_mapping = {
        "external_call_id": mapping.external_call_id,
        "transcript": mapping.transcript,
        "recording_url": mapping.recording_url,
    }

    call_import = CallImport(
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider=integration.provider,
        telephony_integration_id=integration.id,
        original_filename=file.filename,
        sheet_name=sheet_name_clean,
        dataset=_normalize_dataset(dataset),
        column_mapping=stored_mapping,
        extra_columns=extras_clean,
        custom_column_mapping=custom_clean,
        total_rows=len(rows),
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.PENDING,
    )
    if tag_rows:
        call_import.tags = tag_rows
    db.add(call_import)
    db.flush()  # populate call_import.id

    row_models: List[CallImportRow] = []
    for idx, row in enumerate(rows):
        # Stamp ``transcript_source='csv'`` when the upload actually
        # provided a transcript so the UI badge ("From CSV") works
        # from day one. Blank cells stay NULL so the row reads as
        # "no production transcript yet".
        csv_transcript = row["transcript"]
        row_model = CallImportRow(
            call_import_id=call_import.id,
            organization_id=organization_id,
            row_index=idx,
            external_call_id=row["external_call_id"],
            recording_url=row["recording_url"],
            transcript=csv_transcript,
            transcript_source=(
                "csv" if csv_transcript and csv_transcript.strip() else None
            ),
            raw_columns=row["raw_columns"] or None,
            status=CallImportRowStatus.PENDING,
        )
        db.add(row_model)
        row_models.append(row_model)

    call_import.status = CallImportStatus.PROCESSING
    db.commit()
    db.refresh(call_import)

    from app.workers.tasks.process_call_import_row import process_call_import_row_task

    for row_model in row_models:
        try:
            process_call_import_row_task.delay(str(row_model.id))
        except Exception as exc:
            logger.exception(
                "Failed to enqueue call import row {} for import {}",
                row_model.id,
                call_import.id,
            )
            row_model.status = CallImportRowStatus.FAILED
            row_model.error_message = f"Failed to enqueue: {exc}"
    db.commit()

    return CallImportUploadResponse(
        id=call_import.id,
        total_rows=call_import.total_rows,
        status=call_import.status,
        dataset=call_import.dataset,
        tags=[
            {
                "id": tag.id,
                "name": tag.name,
                "color": tag.color,
                "created_at": tag.created_at,
                "updated_at": tag.updated_at,
            }
            for tag in (call_import.tags or [])
        ],
        message=(
            f"Accepted {call_import.total_rows} rows for import. "
            "Recordings will be fetched asynchronously."
        ),
    )


@router.get(
    "",
    response_model=CallImportListResponse,
    operation_id="listCallImports",
)
async def list_call_imports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[CallImportStatus] = Query(None, alias="status"),
    dataset: Optional[str] = Query(
        None,
        description=(
            "Filter by exact dataset string (case-insensitive). Pass the "
            "literal value '__none__' to filter to imports with no dataset."
        ),
    ),
    tag_id: Optional[List[UUID]] = Query(
        None,
        description="Filter to imports tagged with ALL of the given tag ids.",
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> CallImportListResponse:
    """List call-import batches for the active workspace, newest first.

    Scoped to (organization_id, workspace_id) so users only see imports
    for the workspace they're currently in. Supports a high-level
    ``dataset`` filter (powers the segregation dropdown at the top of
    the imports page) plus an AND-style multi-tag filter via repeated
    ``tag_id`` parameters.
    """

    query = (
        db.query(CallImport)
        .filter(
            CallImport.organization_id == organization_id,
            CallImport.workspace_id == workspace_id,
        )
    )
    if status_filter is not None:
        query = query.filter(CallImport.status == status_filter)

    if dataset is not None:
        if dataset == "__none__":
            query = query.filter(CallImport.dataset.is_(None))
        elif dataset.strip():
            query = query.filter(
                func.lower(CallImport.dataset) == dataset.strip().lower()
            )

    if tag_id:
        from app.models.database import CallImportTagAssignment

        for single_tag_id in tag_id:
            sub = (
                db.query(CallImportTagAssignment.call_import_id)
                .filter(CallImportTagAssignment.tag_id == single_tag_id)
                .subquery()
            )
            query = query.filter(CallImport.id.in_(sub))

    total = query.count()
    items = (
        query.order_by(desc(CallImport.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return CallImportListResponse(
        items=[CallImportResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/datasets",
    response_model=List[str],
    operation_id="listCallImportDatasets",
)
async def list_call_import_datasets(
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> List[str]:
    """Return the distinct, non-null dataset labels in use for the active
    workspace.

    Scoped per-workspace so each workspace's Dataset dropdown only shows
    its own segregation labels.
    """
    rows = (
        db.query(CallImport.dataset)
        .filter(
            CallImport.organization_id == organization_id,
            CallImport.workspace_id == workspace_id,
            CallImport.dataset.isnot(None),
            CallImport.dataset != "",
        )
        .distinct()
        .order_by(CallImport.dataset.asc())
        .all()
    )
    return [row[0] for row in rows if row[0]]


@router.patch(
    "/{call_import_id}",
    response_model=CallImportResponse,
    operation_id="updateCallImport",
)
async def update_call_import(
    call_import_id: UUID,
    payload: CallImportUpdate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportResponse:
    """Edit dataset / tag assignments on an existing call-import batch.

    ``dataset = ""`` clears the label; ``tag_ids = []`` removes all tag
    assignments. Fields omitted from the body are left untouched.
    """
    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )

    body = payload.model_dump(exclude_unset=True)
    if "dataset" in body:
        call_import.dataset = _normalize_dataset(body["dataset"])

    if "tag_ids" in body:
        tag_ids = body["tag_ids"] or []
        call_import.tags = _resolve_tags(db, organization_id, tag_ids)

    db.commit()
    db.refresh(call_import)
    return CallImportResponse.model_validate(call_import)


@router.get(
    "/{call_import_id}",
    response_model=CallImportDetailResponse,
    operation_id="getCallImportDetail",
)
async def get_call_import_detail(
    call_import_id: UUID,
    row_limit: int = Query(500, ge=0, le=5000),
    row_offset: int = Query(0, ge=0),
    q: Optional[str] = Query(
        None,
        description=(
            "Optional case-insensitive substring filter on "
            "``external_call_id``. When set, ``filtered_total_rows`` in "
            "the response reflects the post-filter row count so the UI "
            "can paginate against the filtered slice."
        ),
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportDetailResponse:
    """Fetch a single import batch with a slice of its rows.

    ``row_limit=0`` is intentionally allowed so callers that only need the
    batch metadata (e.g. the evaluation-detail page rendering the parent's
    column mapping) can skip the rows payload entirely.
    """

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )

    rows_query = db.query(CallImportRow).filter(
        CallImportRow.call_import_id == call_import.id
    )

    search_term = (q or "").strip()
    filtered_total_rows: Optional[int] = None
    if search_term:
        rows_query = rows_query.filter(
            CallImportRow.external_call_id.ilike(f"%{search_term}%")
        )
        filtered_total_rows = rows_query.count()

    if row_limit == 0:
        rows: List[CallImportRow] = []
    else:
        rows = (
            rows_query.order_by(CallImportRow.row_index)
            .offset(row_offset)
            .limit(row_limit)
            .all()
        )

    detail = CallImportDetailResponse.model_validate(call_import)
    detail.rows = [CallImportRowResponse.model_validate(r) for r in rows]
    detail.filtered_total_rows = filtered_total_rows
    return detail


def _revoke_pending_tasks(rows: List[CallImportRow]) -> None:
    """Best-effort revoke of in-flight Celery tasks for the given rows.

    Failures are logged and swallowed — Celery's control plane is async and
    best-effort by design, and we always do an idempotent S3 cleanup
    afterwards so a missed revoke can't leak storage.
    """
    task_ids = [
        r.celery_task_id
        for r in rows
        if r.celery_task_id
        and r.status in (CallImportRowStatus.PENDING, CallImportRowStatus.PROCESSING)
    ]
    if not task_ids:
        return

    try:
        from app.workers.celery_app import celery_app

        celery_app.control.revoke(task_ids, terminate=False)
        logger.info("Revoked {} pending call-import tasks", len(task_ids))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to revoke pending call-import tasks: {}", exc)


def _delete_s3_objects(
    organization_id: UUID,
    call_import_id: UUID,
    rows: List[CallImportRow],
) -> tuple[int, int]:
    """Delete every recording associated with ``rows`` plus a prefix sweep.

    Returns ``(deleted_count, error_count)``. Never raises — callers proceed
    with the DB delete regardless; orphans, if any, can be cleaned up by
    re-running the same delete (it's idempotent).
    """
    from app.services.storage.s3_service import s3_service

    if not s3_service.is_enabled():
        return 0, 0

    keys = [r.recording_s3_key for r in rows if r.recording_s3_key]
    deleted = 0
    errors = 0

    if keys:
        try:
            d, errs = s3_service.delete_keys(keys)
            deleted += d
            errors += len(errs)
            if errs:
                logger.warning(
                    "S3 bulk-delete reported {} errors for call_import {}",
                    len(errs),
                    call_import_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Bulk S3 delete failed for call_import {}: {}", call_import_id, exc
            )
            errors += len(keys)

    # Belt-and-braces sweep: catch anything that landed under the import's
    # prefix but never made it into a row's recording_s3_key (narrow
    # window where the S3 upload succeeded but the DB commit didn't).
    sweep_prefix = (
        f"{s3_service.prefix}organizations/{organization_id}/"
        f"call_imports/{call_import_id}/"
    )
    try:
        d, errs = s3_service.delete_keys_by_prefix(sweep_prefix)
        deleted += d
        errors += len(errs)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "S3 prefix sweep failed for {}: {}", sweep_prefix, exc
        )

    return deleted, errors


@router.delete(
    "/{call_import_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCallImport",
)
async def delete_call_import(
    call_import_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a call-import batch, its rows, and every associated S3 recording.

    Idempotent and safe to retry. If the batch is still in flight we revoke
    pending Celery tasks before tearing down the rows so workers can't
    write back to deleted records.
    """

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )

    rows = (
        db.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import.id)
        .all()
    )

    _revoke_pending_tasks(rows)

    deleted_objects, s3_errors = _delete_s3_objects(
        organization_id=organization_id,
        call_import_id=call_import.id,
        rows=rows,
    )

    db.delete(call_import)  # cascades to call_import_rows
    db.commit()

    logger.info(
        "Deleted call_import {} (org={}, rows={}, s3_objects_deleted={}, s3_errors={})",
        call_import.id,
        organization_id,
        len(rows),
        deleted_objects,
        s3_errors,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{call_import_id}/rows/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCallImportRow",
)
async def delete_call_import_row(
    call_import_id: UUID,
    row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a single CallImportRow and its S3 recording.

    The parent ``CallImport`` is left in place. After deletion we recompute
    its ``total_rows`` / ``completed_rows`` / ``failed_rows`` / ``status``
    so the UI's progress bar stays consistent with reality.
    """
    from app.services.storage.s3_service import s3_service

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )

    row = (
        db.query(CallImportRow)
        .filter(
            CallImportRow.id == row_id,
            CallImportRow.call_import_id == call_import.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import row not found",
        )

    _revoke_pending_tasks([row])

    if row.recording_s3_key and s3_service.is_enabled():
        try:
            s3_service.delete_file_by_key(row.recording_s3_key)
        except Exception as exc:  # noqa: BLE001 — best-effort, DB is source of truth
            logger.warning(
                "Failed to delete S3 object {} for row {}: {}",
                row.recording_s3_key,
                row.id,
                exc,
            )

    db.delete(row)
    db.flush()

    _recompute_call_import_counters(db, call_import)
    db.commit()

    logger.info(
        "Deleted call_import_row {} (call_import={}, org={})",
        row_id,
        call_import.id,
        organization_id,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _recompute_call_import_counters(
    db: Session, call_import: CallImport
) -> None:
    """Resync ``total/completed/failed_rows`` + status on the parent batch.

    Called after row-level mutations (single delete, bulk delete) so the
    UI's progress bar stays consistent with the actual row set. The
    rules mirror :func:`delete_call_import_row` so behavior doesn't
    diverge between the per-row and bulk paths.
    """

    remaining = (
        db.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import.id)
        .all()
    )
    completed = sum(
        1 for r in remaining if r.status == CallImportRowStatus.COMPLETED
    )
    failed = sum(
        1 for r in remaining if r.status == CallImportRowStatus.FAILED
    )
    pending_or_processing = sum(
        1
        for r in remaining
        if r.status in (CallImportRowStatus.PENDING, CallImportRowStatus.PROCESSING)
    )

    call_import.total_rows = len(remaining)
    call_import.completed_rows = completed
    call_import.failed_rows = failed
    if pending_or_processing > 0:
        call_import.status = CallImportStatus.PROCESSING
    elif len(remaining) == 0:
        # No rows left — leave the batch in its current terminal status
        # rather than synthesizing a misleading "completed". The user can
        # delete the empty batch from the UI if they want it gone.
        pass
    elif failed == 0:
        call_import.status = CallImportStatus.COMPLETED
    elif completed == 0:
        call_import.status = CallImportStatus.FAILED
    else:
        call_import.status = CallImportStatus.PARTIAL


@router.post(
    "/{call_import_id}/rows/bulk-delete",
    response_model=CallImportRowBulkDeleteResponse,
    operation_id="bulkDeleteCallImportRows",
)
async def bulk_delete_call_import_rows(
    call_import_id: UUID,
    payload: CallImportRowBulkDelete,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportRowBulkDeleteResponse:
    """Delete multiple ``CallImportRow`` rows in one request.

    Unknown / cross-tenant row ids are silently skipped — the response
    reports how many actually went away so a UI that holds onto stale
    ids (e.g. after another tab already deleted a row) doesn't 404
    the entire bulk action.
    """
    del api_key

    from app.services.storage.s3_service import s3_service

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )

    rows = (
        db.query(CallImportRow)
        .filter(
            CallImportRow.id.in_(payload.row_ids),
            CallImportRow.call_import_id == call_import.id,
        )
        .all()
    )
    if not rows:
        return CallImportRowBulkDeleteResponse(deleted=0)

    _revoke_pending_tasks(rows)

    if s3_service.is_enabled():
        for row in rows:
            if not row.recording_s3_key:
                continue
            try:
                s3_service.delete_file_by_key(row.recording_s3_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to delete S3 object {} for row {}: {}",
                    row.recording_s3_key,
                    row.id,
                    exc,
                )

    deleted = 0
    for row in rows:
        db.delete(row)
        deleted += 1
    db.flush()

    _recompute_call_import_counters(db, call_import)
    db.commit()

    logger.info(
        "Bulk-deleted {} call_import_rows (call_import={}, org={})",
        deleted,
        call_import.id,
        organization_id,
    )

    return CallImportRowBulkDeleteResponse(deleted=deleted)


# ---------------------------------------------------------------------------
# Diarization / transcription endpoints
# ---------------------------------------------------------------------------


def _select_rows_for_transcription(
    db: Session,
    call_import: CallImport,
    payload: CallImportTranscribeRequest,
    requested_row_ids: Optional[List[UUID]] = None,
) -> tuple[List[CallImportRow], Dict[str, int]]:
    """Pick which rows to enqueue for diarisation.

    Centralises the "should this row be touched?" decision so both the
    batch endpoint and the per-row endpoint apply the same rules:

    * row must exist on the import,
    * row must have an S3 recording (otherwise nothing to transcribe),
    * if ``only_missing`` is set and ``overwrite_existing`` is not, rows
      with a non-empty ``diarised_transcript`` are skipped (the
      production ``transcript`` is intentionally ignored here — it
      lives in a separate column and is never overwritten by this
      worker).

    Returns the list of rows to enqueue plus a per-reason skip count
    that the response can surface so the user knows why a "no-op"
    happened.
    """

    query = db.query(CallImportRow).filter(
        CallImportRow.call_import_id == call_import.id
    )
    if requested_row_ids:
        query = query.filter(CallImportRow.id.in_(requested_row_ids))
    rows = query.order_by(CallImportRow.row_index.asc()).all()

    if requested_row_ids:
        found_ids = {r.id for r in rows}
        missing = [rid for rid in requested_row_ids if rid not in found_ids]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Some row ids were not found on this import: "
                    f"{[str(m) for m in missing]}"
                ),
            )

    selected: List[CallImportRow] = []
    skip_counts: Dict[str, int] = {}

    for row in rows:
        recording = (row.recording_s3_key or "").strip()
        if not recording:
            skip_counts["no_recording"] = skip_counts.get("no_recording", 0) + 1
            continue
        existing = (row.diarised_transcript or "").strip()
        if existing and payload.only_missing and not payload.overwrite_existing:
            skip_counts["transcript_present"] = (
                skip_counts.get("transcript_present", 0) + 1
            )
            continue
        selected.append(row)

    return selected, skip_counts


@router.post(
    "/{call_import_id}/transcribe",
    response_model=CallImportTranscribeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="transcribeCallImport",
)
async def transcribe_call_import(
    call_import_id: UUID,
    payload: CallImportTranscribeRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportTranscribeResponse:
    """Fan out diarization tasks for many rows in a single call.

    Returns a summary with how many rows were queued and how many were
    skipped (broken down by reason) so the UI can show a meaningful
    toast even when nothing actually got enqueued (e.g. "All 12 rows
    already have transcripts").
    """

    del api_key

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )

    rows, skip_counts = _select_rows_for_transcription(
        db, call_import, payload, requested_row_ids=payload.row_ids
    )

    # Mark the about-to-be-enqueued rows as ``pending`` so the UI can
    # show a "Queued for diarisation" badge immediately, even before
    # the worker picks the row up. The worker flips it to ``running``
    # on entry.
    for row in rows:
        row.diarised_transcript_status = "pending"
        row.diarised_transcript_error = None
    db.commit()

    if not rows:
        return CallImportTranscribeResponse(
            queued=0,
            skipped_rows=sum(skip_counts.values()),
            skipped_reason_counts=skip_counts,
        )

    from app.workers.tasks.transcribe_call_import_row import (
        transcribe_call_import_row_task,
    )

    enqueued = 0
    for row in rows:
        try:
            transcribe_call_import_row_task.delay(
                str(row.id),
                payload.stt_provider,
                payload.stt_model,
                str(payload.credential_id) if payload.credential_id else None,
                payload.language,
                payload.overwrite_existing,
            )
            enqueued += 1
        except Exception as exc:
            logger.exception(
                "Failed to enqueue transcribe for row {}: {}", row.id, exc
            )
            row.diarised_transcript_status = "failed"
            row.diarised_transcript_error = f"Failed to enqueue: {exc}"
    db.commit()

    return CallImportTranscribeResponse(
        queued=enqueued,
        skipped_rows=sum(skip_counts.values()),
        skipped_reason_counts=skip_counts,
    )


@router.post(
    "/{call_import_id}/rows/{row_id}/transcribe",
    response_model=CallImportTranscribeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="transcribeCallImportRow",
)
async def transcribe_call_import_row(
    call_import_id: UUID,
    row_id: UUID,
    payload: CallImportTranscribeRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportTranscribeResponse:
    """Diarize / transcribe a single row.

    Thin wrapper over the batch endpoint that hard-codes a single
    ``row_ids`` filter. Skip counts still surface so the UI can render
    "Skipped — transcript present" diagnostics consistently.
    """

    del api_key

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )

    rows, skip_counts = _select_rows_for_transcription(
        db, call_import, payload, requested_row_ids=[row_id]
    )

    for row in rows:
        row.diarised_transcript_status = "pending"
        row.diarised_transcript_error = None
    db.commit()

    if not rows:
        return CallImportTranscribeResponse(
            queued=0,
            skipped_rows=sum(skip_counts.values()),
            skipped_reason_counts=skip_counts,
        )

    from app.workers.tasks.transcribe_call_import_row import (
        transcribe_call_import_row_task,
    )

    target = rows[0]
    try:
        transcribe_call_import_row_task.delay(
            str(target.id),
            payload.stt_provider,
            payload.stt_model,
            str(payload.credential_id) if payload.credential_id else None,
            payload.language,
            payload.overwrite_existing,
        )
        return CallImportTranscribeResponse(
            queued=1,
            skipped_rows=sum(skip_counts.values()),
            skipped_reason_counts=skip_counts,
        )
    except Exception as exc:
        logger.exception(
            "Failed to enqueue transcribe for row {}: {}", target.id, exc
        )
        target.diarised_transcript_status = "failed"
        target.diarised_transcript_error = f"Failed to enqueue: {exc}"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue transcription: {exc}",
        )


# ---------------------------------------------------------------------------
# Cross-run insights for the import detail page
# ---------------------------------------------------------------------------


@router.get(
    "/{call_import_id}/insights",
    response_model=CallImportInsightsResponse,
    operation_id="getCallImportInsights",
)
async def get_call_import_insights(
    call_import_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportInsightsResponse:
    """Aggregate signals across every evaluation run on this import.

    Powers the Insights tab on the call-import detail page: returns
    per-metric "latest run" summaries plus a trend series of mean values
    across runs so the UI can render a small line chart per metric. Also
    bundles transcript coverage stats since those are the cheapest
    pre-eval health-check (e.g. "30 of 50 rows still missing
    transcripts").
    """

    del api_key

    from app.models.database import (
        CallImportEvaluation,
        CallImportEvaluationRow,
        Metric,
    )

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )

    rows = (
        db.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import_id)
        .all()
    )
    # A row "has a transcript" if EITHER the production (CSV) or the
    # diarised (worker) column is populated — the insights tile reports
    # the union so users see total coverage regardless of which source
    # produced the value.
    rows_with_transcript = sum(
        1
        for r in rows
        if (r.transcript or "").strip()
        or (r.diarised_transcript or "").strip()
    )
    rows_without_transcript = len(rows) - rows_with_transcript
    source_counts: Dict[str, int] = {}
    for r in rows:
        has_production = bool((r.transcript or "").strip())
        has_diarised = bool((r.diarised_transcript or "").strip())
        if has_production:
            key = r.transcript_source or "csv"
            source_counts[key] = source_counts.get(key, 0) + 1
        if has_diarised:
            source_counts["diarised"] = source_counts.get("diarised", 0) + 1

    evaluations = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .order_by(CallImportEvaluation.created_at.asc())
        .all()
    )

    # Defer heavy lifting to the aggregation helper so this endpoint and
    # the per-run aggregate endpoint share the exact same metric
    # bucketing math (no chance of "trend" disagreeing with "latest" on
    # the same data set).
    from app.api.v1.routes.call_import_evaluations import (
        _compute_metric_aggregates,
    )

    metric_history: Dict[str, List[CallImportInsightsRunPoint]] = {}
    metric_meta: Dict[str, Metric] = {}
    metric_latest: Dict[str, CallImportMetricAggregate] = {}

    for evaluation in evaluations:
        eval_rows = (
            db.query(CallImportEvaluationRow)
            .filter(CallImportEvaluationRow.evaluation_id == evaluation.id)
            .all()
        )
        aggregates = _compute_metric_aggregates(db, evaluation, eval_rows)
        for agg in aggregates:
            if agg.metric_id not in metric_meta:
                metric_obj = (
                    db.query(Metric)
                    .filter(
                        Metric.id == UUID(agg.metric_id),
                        Metric.organization_id == organization_id,
                    )
                    .first()
                )
                if metric_obj is not None:
                    metric_meta[agg.metric_id] = metric_obj
            history = metric_history.setdefault(agg.metric_id, [])
            history.append(
                CallImportInsightsRunPoint(
                    evaluation_id=evaluation.id,
                    name=evaluation.name,
                    created_at=evaluation.created_at,
                    mean=agg.mean,
                    completed_rows=agg.count,
                )
            )
            metric_latest[agg.metric_id] = agg

    metrics_payload: List[CallImportInsightsMetric] = []
    for metric_id, latest in metric_latest.items():
        meta = metric_meta.get(metric_id)
        metrics_payload.append(
            CallImportInsightsMetric(
                metric_id=metric_id,
                metric_name=(meta.name if meta else latest.metric_name),
                metric_type=(meta.metric_type if meta else latest.metric_type),
                latest=latest,
                trend=metric_history.get(metric_id, []),
            )
        )

    return CallImportInsightsResponse(
        call_import_id=call_import_id,
        total_rows=len(rows),
        rows_with_transcript=rows_with_transcript,
        rows_without_transcript=rows_without_transcript,
        transcript_source_counts=source_counts,
        evaluation_count=len(evaluations),
        metrics=metrics_payload,
    )
