"""CSV/Excel source parsing and staging helpers for call imports."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import Principal
from app.models.database import (
    CallImport,
    CallImportSchema,
    CallImportSchemaParameter,
    CallImportTag,
)
from app.models.enums import CallImportParameterType, CallImportStatus
from app.models.schemas import CallImportPreviewSheet
from app.services.call_imports.audit import stamp_call_import_actor

@dataclass(frozen=True)
class CallImportParseSkip:
    """One source row excluded during CSV/Excel parse (identity / recording URL)."""

    source_row: int
    reason: str
    message: str


@dataclass
class CallImportParseResult:
    rows: List[Dict[str, Any]] = field(default_factory=list)
    skipped: List[CallImportParseSkip] = field(default_factory=list)


def parse_skips_to_json(skips: List[CallImportParseSkip]) -> List[Dict[str, Any]]:
    """Persistable JSON shape for ``CallImport.source_row_skips``."""
    return [
        {
            "source_row": item.source_row,
            "reason": item.reason,
            "message": item.message,
        }
        for item in skips
    ]
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB upload cap (CSV or Excel)
MAX_AUDIO_FILES_PER_REQUEST = 100
MANUAL_AUDIO_BLOB_UPLOAD_WORKERS = 10

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


def _parse_recording_date_cell(cell: str) -> date:
    """Parse day-first dates with one/two digit day-month parts."""
    match = re.fullmatch(r"\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})\s*", cell)
    if match:
        day, month, year = (int(part) for part in match.groups())
        return date(year, month, day)

    # Native Excel date cells arrive from ``_xlsx_cell_to_str`` as ISO
    # datetimes (e.g. ``2026-01-04T00:00:00``). Accept that resolved date,
    # while keeping plain ISO dates rejected for hand-entered text/CSV cells.
    if "T" in cell:
        return datetime.fromisoformat(cell.replace("Z", "+00:00")).date()

    raise ValueError("expected D/M/YYYY or D-M-YYYY")


def _coerce_parameter_value(
    raw: str,
    param_type: CallImportParameterType,
    *,
    row_idx: int,
    param_name: str,
) -> Any:
    """Validate + coerce a single CSV cell against its declared type.

    Returns the typed Python value to surface in ``raw_columns``. Empty
    strings are returned as ``None`` regardless of the parameter type so
    optional cells stay null end-to-end. Coercion failures raise a
    400 with a row-anchored message.
    """
    cell = (raw or "").strip()
    if not cell:
        return None

    if param_type == CallImportParameterType.CONVERSATION_ID:
        return cell
    if param_type == CallImportParameterType.RECORDING_URL:
        # Recording URLs are exercised by the worker (which downloads
        # them); we only do a light "starts with http" check here so a
        # paste-error surfaces immediately at upload time.
        lower = cell.lower()
        if not (lower.startswith("http://") or lower.startswith("https://")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Row {row_idx + 1}: value for '{param_name}' is not a "
                    "valid recording URL (must start with http:// or https://)."
                ),
            )
        return cell
    if param_type == CallImportParameterType.RECORDING_DATE:
        try:
            parsed_date = _parse_recording_date_cell(cell)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Row {row_idx + 1}: value for '{param_name}' is not a "
                    f"valid recording date ({cell!r}); expected day-first "
                    "D/M/YYYY or D-M-YYYY."
                ),
            )
        return parsed_date.strftime("%d/%m/%Y")
    if param_type == CallImportParameterType.TRANSCRIPT:
        return cell
    if param_type == CallImportParameterType.TEXT:
        return cell
    if param_type == CallImportParameterType.NUMBER:
        try:
            value = float(cell)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Row {row_idx + 1}: value for '{param_name}' is not a "
                    f"valid number ({cell!r})."
                ),
            )
        if value.is_integer():
            return int(value)
        return value
    if param_type == CallImportParameterType.BOOLEAN:
        truthy = {"true", "yes", "y", "1", "t"}
        falsy = {"false", "no", "n", "0", "f"}
        norm = cell.lower()
        if norm in truthy:
            return True
        if norm in falsy:
            return False
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Row {row_idx + 1}: value for '{param_name}' is not a "
                f"valid boolean ({cell!r})."
            ),
        )
    if param_type == CallImportParameterType.DATETIME:
        try:
            parsed = datetime.fromisoformat(cell.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Row {row_idx + 1}: value for '{param_name}' is not a "
                    f"valid ISO-8601 date/time ({cell!r})."
                ),
            )
        return parsed.isoformat()
    if param_type == CallImportParameterType.URL:
        lower = cell.lower()
        if not (lower.startswith("http://") or lower.startswith("https://")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Row {row_idx + 1}: value for '{param_name}' is not a "
                    "valid URL (must start with http:// or https://)."
                ),
            )
        return cell
    # Unknown types: store as text and let the next migration catch up.
    return cell


def _recording_url_cell_is_valid_http(raw: str) -> bool:
    cell = (raw or "").strip()
    if not cell:
        return False
    lower = cell.lower()
    return lower.startswith("http://") or lower.startswith("https://")


def _parameter_is_required(param: CallImportSchemaParameter) -> bool:
    """Return whether a schema parameter must be mapped on every upload."""
    if param.is_required:
        return True
    try:
        param_type = CallImportParameterType(param.type)
    except ValueError:
        return False
    return param_type == CallImportParameterType.CONVERSATION_ID


def _apply_schema_mapping(
    fieldnames: List[str],
    rows_iter: Iterable[Dict[str, str]],
    parameters: List[CallImportSchemaParameter],
    parameter_mapping: Dict[str, str],
    skipped_columns: List[str],
    *,
    source_label: str = "CSV",
    validate_only: bool = False,
) -> CallImportParseResult:
    """Schema-driven row projection: parameter -> CSV header -> typed value.

    Validates that every required schema parameter is mapped to a CSV
    header that actually exists in the file, and that every CSV header
    is either mapped to a parameter or explicitly listed in
    ``skipped_columns``. Returns one dict per non-empty data row with:

      * ``conversation_id`` (str, mandatory)
      * ``recording_date`` (Optional[str], DD/MM/YYYY date)
      * ``recording_url`` (Optional[str])
      * ``transcript`` (Optional[str])
      * ``parameter_values`` (Dict[str, Any]) of typed values keyed by
        parameter name (drives ``raw_columns`` so the export can
        reproduce the source).

    ``validate_only=True`` runs the header / mapping / skipped-column
    checks (every check that doesn't need to read row data) and then
    returns an empty list — used by the MAP stage to validate a
    mapping payload against the cached sheet snapshot without
    re-fetching the source bytes from S3.
    """
    header_lookup = _header_lookup(list(fieldnames))

    # 1. Look up the conversation_id parameter so we can address it
    #    directly while building each row.
    conv_param = next(
        (p for p in parameters if p.type == CallImportParameterType.CONVERSATION_ID),
        None,
    )
    if conv_param is None:
        # The schema invariant should have caught this on create/update,
        # but a defensive 400 here keeps us safe against hand-rolled
        # API callers that bypassed validation.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected schema is missing the mandatory conversation_id parameter.",
        )
    # 2. Resolve every mapped parameter to a canonical fieldname.
    #    Required parameters MUST resolve; optional ones may resolve to
    #    None if the user left them blank (no mapping).
    canonical_by_param: Dict[str, Optional[str]] = {}
    recording_date_param_name: Optional[str] = None
    rec_url_param_name: Optional[str] = None
    transcript_param_name: Optional[str] = None
    for param in parameters:
        mapped_header = parameter_mapping.get(param.name)
        canonical = (
            _resolve_mapped_header(mapped_header, header_lookup)
            if mapped_header
            else None
        )
        if _parameter_is_required(param) and canonical is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{source_label} does not contain the column "
                    f"'{mapped_header or ''}' mapped to required parameter "
                    f"'{param.name}'."
                ),
            )
        canonical_by_param[param.name] = canonical
        if param.type == CallImportParameterType.RECORDING_DATE:
            recording_date_param_name = param.name
        elif param.type == CallImportParameterType.RECORDING_URL:
            rec_url_param_name = param.name
        elif param.type == CallImportParameterType.TRANSCRIPT:
            transcript_param_name = param.name

    # 3. Every CSV column must either be mapped to a parameter or
    #    explicitly skipped. Catches "I forgot to skip the email
    #    column" gracefully instead of dropping data silently.
    mapped_canonicals = {c for c in canonical_by_param.values() if c}
    skipped_canonicals = {
        _resolve_mapped_header(h, header_lookup)
        for h in skipped_columns
    }
    skipped_canonicals.discard(None)
    unhandled = [
        h
        for h in fieldnames
        if h not in mapped_canonicals and h not in skipped_canonicals
    ]
    if unhandled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{source_label} columns must either be mapped to a schema "
                f"parameter or explicitly skipped. Unhandled: {unhandled}."
            ),
        )

    conv_canonical = canonical_by_param[conv_param.name]
    rec_canonical = (
        canonical_by_param.get(rec_url_param_name)
        if rec_url_param_name
        else None
    )
    recording_date_canonical = (
        canonical_by_param.get(recording_date_param_name)
        if recording_date_param_name
        else None
    )
    transcript_canonical = (
        canonical_by_param.get(transcript_param_name)
        if transcript_param_name
        else None
    )

    if validate_only:
        # MAP-stage validation: every header check above has already
        # run; the row loop only matters at IMPORT time. Skip it (and
        # the "no data rows" guard at the bottom of the function) so
        # the caller gets a clean pass when the mapping is shaped right.
        return CallImportParseResult()

    parsed: List[Dict[str, Any]] = []
    skipped: List[CallImportParseSkip] = []
    for idx, row in enumerate(rows_iter):
        # Drop fully-blank lines - matches the legacy parser behavior so
        # trailing-newline edge cases don't fail an otherwise-good upload.
        non_blank = any(
            (row.get(c) or "").strip()
            for c in mapped_canonicals
            if c
        )
        if not non_blank:
            continue

        source_row = idx + 1
        conv_value = (row.get(conv_canonical) or "").strip() if conv_canonical else ""
        if not conv_value:
            skipped.append(
                CallImportParseSkip(
                    source_row=source_row,
                    reason="missing_conversation_id",
                    message=(
                        f"Row {source_row} is missing the '{conv_param.name}' "
                        "(conversation_id) value."
                    ),
                )
            )
            continue

        if rec_canonical and rec_url_param_name:
            rec_param = next(
                (p for p in parameters if p.name == rec_url_param_name),
                None,
            )
            if rec_param is not None:
                rec_raw = (row.get(rec_canonical) or "").strip()
                if _parameter_is_required(rec_param) and not rec_raw:
                    skipped.append(
                        CallImportParseSkip(
                            source_row=source_row,
                            reason="missing_recording_url",
                            message=(
                                f"Row {source_row} is missing the required "
                                f"'{rec_url_param_name}' value."
                            ),
                        )
                    )
                    continue
                if rec_raw and not _recording_url_cell_is_valid_http(rec_raw):
                    skipped.append(
                        CallImportParseSkip(
                            source_row=source_row,
                            reason="invalid_recording_url",
                            message=(
                                f"Row {source_row}: value for "
                                f"'{rec_url_param_name}' is not a valid recording "
                                "URL (must start with http:// or https://)."
                            ),
                        )
                    )
                    continue

        # Materialize every mapped parameter into the per-row snapshot,
        # running per-type coercion so a bad cell aborts the upload
        # rather than silently storing garbage.
        parameter_values: Dict[str, Any] = {}
        row_skipped = False
        for param in parameters:
            canonical = canonical_by_param[param.name]
            if canonical is None:
                continue
            try:
                param_type = CallImportParameterType(param.type)
            except ValueError:
                param_type = CallImportParameterType.TEXT
            raw_cell = row.get(canonical) or ""
            if (
                param_type == CallImportParameterType.RECORDING_URL
                and (raw_cell or "").strip()
                and not _recording_url_cell_is_valid_http(raw_cell)
            ):
                skipped.append(
                    CallImportParseSkip(
                        source_row=source_row,
                        reason="invalid_recording_url",
                        message=(
                            f"Row {source_row}: value for '{param.name}' is not a "
                            "valid recording URL (must start with http:// or https://)."
                        ),
                    )
                )
                row_skipped = True
                break
            coerced = _coerce_parameter_value(
                raw_cell,
                param_type,
                row_idx=idx,
                param_name=param.name,
            )
            if _parameter_is_required(param) and coerced is None:
                if param_type == CallImportParameterType.RECORDING_URL:
                    skipped.append(
                        CallImportParseSkip(
                            source_row=source_row,
                            reason="missing_recording_url",
                            message=(
                                f"Row {source_row} is missing the required "
                                f"'{param.name}' value."
                            ),
                        )
                    )
                    row_skipped = True
                    break
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Row {source_row} is missing the required "
                        f"'{param.name}' value."
                    ),
                )
            parameter_values[param.name] = coerced
        if row_skipped:
            continue

        rec_value = (
            (row.get(rec_canonical) or "").strip() if rec_canonical else ""
        )
        transcript_value = (
            (row.get(transcript_canonical) or "").strip()
            if transcript_canonical
            else ""
        )
        recording_date_value = (
            parameter_values.get(recording_date_param_name)
            if recording_date_param_name
            else None
        )

        parsed.append(
            {
                "conversation_id": conv_value,
                "recording_date": recording_date_value,
                "recording_url": rec_value or None,
                "transcript": transcript_value or None,
                "parameter_values": parameter_values,
            }
        )

    if not parsed and not skipped:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{source_label} did not contain any data rows.",
        )

    return CallImportParseResult(rows=parsed, skipped=skipped)


def _raise_if_no_importable_rows(
    result: CallImportParseResult, *, source_label: str = "CSV"
) -> None:
    """Sync upload / API callers fail fast when every data row was skipped."""
    if result.rows:
        return
    if result.skipped:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"No importable rows. {len(result.skipped)} row(s) skipped due "
                "to missing or invalid conversation ID or recording URL."
            ),
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{source_label} did not contain any data rows.",
    )


def _parse_csv(
    file_bytes: bytes,
    parameters: List[CallImportSchemaParameter],
    parameter_mapping: Dict[str, str],
    skipped_columns: List[str],
) -> CallImportParseResult:
    """Parse a CSV file using the resolved schema parameters."""
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

    return _apply_schema_mapping(
        list(reader.fieldnames),
        reader,
        parameters,
        parameter_mapping,
        skipped_columns,
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
    parameters: List[CallImportSchemaParameter],
    parameter_mapping: Dict[str, str],
    skipped_columns: List[str],
) -> CallImportParseResult:
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

    return _apply_schema_mapping(
        headers,
        rows,
        parameters,
        parameter_mapping,
        skipped_columns,
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
def _source_content_type(fmt: str) -> str:
    """Return the canonical ``Content-Type`` for a parsed file format."""
    if fmt == "csv":
        return "text/csv"
    if fmt == "xlsx":
        return (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    return "application/octet-stream"


def _source_s3_key(
    organization_id: UUID, call_import_id: UUID, fmt: str
) -> str:
    """Build the canonical S3 key for an upload's source file.

    Mirrors the per-row recording key convention used by
    ``process_call_import_row`` so a single prefix sweep on delete still
    cleans up both the source artefact and every fetched recording.
    """
    from app.services.storage.s3_service import s3_service

    ext = "xlsx" if fmt == "xlsx" else "csv"
    return (
        f"{s3_service.prefix}organizations/{organization_id}/call_imports/"
        f"{call_import_id}/source.{ext}"
    )


def _build_available_sheets(
    file_bytes: bytes, fmt: str, filename: Optional[str]
) -> List[CallImportPreviewSheet]:
    """Snapshot of sheets + headers cached on the batch at UPLOAD time."""
    if fmt == "csv":
        return _csv_preview_sheets(file_bytes, filename)
    return _xlsx_preview_sheets(file_bytes)

def _insert_staged_call_import_record(
    db: Session,
    *,
    call_import_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
    principal: Principal,
    filename: str,
    fmt: str,
    s3_key: str,
    content_type: str,
    file_bytes: bytes,
    normalized_dataset: str,
    schema_id: Optional[UUID],
    normalized_modality: Optional[str],
    tag_rows: List[CallImportTag],
) -> CallImport:
    sheets = _build_available_sheets(file_bytes, fmt, filename)
    call_import = CallImport(
        id=call_import_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider=None,
        telephony_integration_id=None,
        original_filename=filename,
        sheet_name=None,
        dataset=normalized_dataset,
        schema_id=schema_id,
        parameter_mapping={},
        skipped_columns=[],
        column_mapping={},
        extra_columns=[],
        custom_column_mapping={},
        source_s3_key=s3_key,
        source_format=fmt,
        source_size_bytes=len(file_bytes),
        source_content_type=content_type,
        available_sheets=[sheet.model_dump() for sheet in sheets],
        total_rows=0,
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.UPLOADED,
        content_modality=normalized_modality,
    )
    if tag_rows:
        call_import.tags = tag_rows
    stamp_call_import_actor(call_import, principal, creating=True)
    db.add(call_import)
    db.commit()
    db.refresh(call_import)
    return call_import
def _resolve_schema(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    schema_id: UUID,
) -> CallImportSchema:
    """Fetch + validate a schema row in the active workspace.

    Eager-loads ``parameters`` so callers can iterate without re-querying.
    """
    from sqlalchemy.orm import selectinload as _selectinload

    schema = (
        db.query(CallImportSchema)
        .options(_selectinload(CallImportSchema.parameters))
        .filter(
            CallImportSchema.id == schema_id,
            CallImportSchema.organization_id == organization_id,
            CallImportSchema.workspace_id == workspace_id,
        )
        .first()
    )
    if not schema:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Call import schema not found in the active workspace.",
        )
    if not list(schema.parameters):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected schema has no parameters defined.",
        )
    return schema
def _clean_parameter_mapping(
    mapping_payload: Any,
    parameters: List[CallImportSchemaParameter],
    schema_name: str,
) -> Dict[str, str]:
    """Trim values and drop empties; reject unknown parameter names.

    Accepts an already-decoded value (dict-shaped) so the same helper
    works for the JSON-form upload path and the JSON-body PATCH path.
    """
    if not isinstance(mapping_payload, dict) or not all(
        isinstance(k, str) and (v is None or isinstance(v, str))
        for k, v in mapping_payload.items()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "parameter_mapping must be an object of "
                "{parameter_name: csv_header}."
            ),
        )

    valid_param_names = {p.name for p in parameters}
    cleaned: Dict[str, str] = {}
    for raw_name, raw_header in mapping_payload.items():
        if raw_name not in valid_param_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"parameter_mapping references unknown parameter "
                    f"'{raw_name}' on schema '{schema_name}'."
                ),
            )
        header = (raw_header or "").strip()
        if header:
            cleaned[raw_name] = header
    return cleaned


def _clean_skipped_columns(skipped_payload: Any) -> List[str]:
    """Dedupe (case-insensitively) and drop blanks; preserve original casing."""
    if not isinstance(skipped_payload, list) or not all(
        isinstance(item, str) for item in skipped_payload
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="skipped_columns must be a list of header strings.",
        )
    cleaned: List[str] = []
    seen: set[str] = set()
    for item in skipped_payload:
        norm = _normalize_header(item)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        cleaned.append(item)
    return cleaned


def _parse_source_file(
    file_bytes: bytes,
    fmt: str,
    sheet_name: Optional[str],
    parameters: List[CallImportSchemaParameter],
    cleaned_mapping: Dict[str, str],
    cleaned_skipped: List[str],
) -> CallImportParseResult:
    """Run the format-appropriate parser against a buffer of file bytes."""
    if fmt == "csv":
        return _parse_csv(file_bytes, parameters, cleaned_mapping, cleaned_skipped)
    return _parse_xlsx(
        file_bytes, sheet_name, parameters, cleaned_mapping, cleaned_skipped
    )
def _validate_sheet_choice(
    fmt: str,
    sheet_name: Optional[str],
    available_sheets: Optional[List[Dict[str, Any]]],
) -> Optional[str]:
    """Normalize / validate ``sheet_name`` against the persisted snapshot.

    Returns the canonical sheet name (matching the workbook's casing)
    so downstream parsing addresses the right worksheet.
    """
    if fmt == "csv":
        if sheet_name and sheet_name.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sheet_name is not applicable to CSV uploads.",
            )
        return None

    cleaned = (sheet_name or "").strip() or None
    if cleaned is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sheet_name is required when the source is an Excel workbook.",
        )

    if not available_sheets:
        # Nothing to validate against (e.g. legacy batch without snapshot);
        # let downstream parsing error out instead of silently importing.
        return cleaned

    target = cleaned.strip().lower()
    for entry in available_sheets:
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str) and name.strip().lower() == target:
            return name
    sheet_names = [
        entry.get("name") for entry in available_sheets if isinstance(entry, dict)
    ]
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            f"Sheet '{cleaned}' not found in the staged file. "
            f"Available sheets: {sheet_names}"
        ),
    )
