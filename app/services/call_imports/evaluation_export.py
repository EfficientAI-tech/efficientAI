"""Paged evaluation exports. The API stores a job; a worker writes gzip parts."""

from __future__ import annotations

import csv
import gzip
import heapq
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterator, List, Optional, Sequence, Tuple
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session, load_only

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationExport,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
)

EXPORT_PAGE_SIZE = 1000
EXPORT_PART_ROW_COUNT = 100_000
XLSX_SHEET_ROW_CAP = 1_048_576
EXPORT_URL_TTL_SECONDS = 3600
EXPORT_HEARTBEAT_STALE = timedelta(minutes=15)

PRODUCTION_TRANSCRIPT_HEADER = "Production Transcript"
DIARISED_TRANSCRIPT_HEADER = "Diarised Transcript"
EVAL_SOURCE_HEADER = "Evaluated Transcript Source"

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
CSV_GZ_CONTENT_TYPE = "application/gzip"


@dataclass
class ExportLayout:
    fieldnames: List[str]
    standard_headers: List[str]
    custom_export: List[Tuple[str, str]]
    rationale_headers: Dict[str, str]
    metrics: List[Metric]
    metrics_by_id: Dict[str, Metric]
    include_transcripts: bool
    transcript_source: str = "diarised"
    omitted_raw_headers: set = field(default_factory=set)


class _ExportSuperseded(Exception):
    """Another worker owns this job. Leave its status alone."""


def _flatten_transcript(text: Optional[str]) -> str:
    if not text:
        return ""
    parts = [
        segment.strip()
        for segment in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    return " ".join(part for part in parts if part)


def _source_label(
    transcript_source: str,
    source_row: CallImportRow,
    *,
    include_transcripts: bool,
) -> str:
    source = (transcript_source or "diarised").strip().lower()
    if not include_transcripts:
        return "Production" if source == "production" else "Diarised"
    if source == "production":
        if not (source_row.transcript or "").strip():
            return ""
        return "Production"
    if not (source_row.diarised_transcript or "").strip():
        return ""
    return "Diarised"


def _metrics_for_ids(db: Session, org_id: UUID, ids: Sequence[UUID]) -> List[Metric]:
    if not ids:
        return []
    rows = (
        db.query(Metric)
        .filter(Metric.organization_id == org_id, Metric.id.in_(list(ids)))
        .all()
    )
    by_id = {row.id: row for row in rows}
    return [by_id[mid] for mid in ids if mid in by_id]


def _selected_metric_ids(value) -> List[UUID]:
    result: List[UUID] = []
    if not isinstance(value, list):
        return result
    for item in value:
        try:
            result.append(UUID(str(item)))
        except (TypeError, ValueError):
            continue
    return result


def _omitted_raw_headers(call_import: CallImport, db: Session) -> set:
    """CSV headers that carry the uploaded transcript body."""
    omitted: set = set()
    mapping = call_import.column_mapping or {}
    if isinstance(mapping, dict):
        header = mapping.get("transcript")
        if isinstance(header, str) and header.strip():
            omitted.add(header)
    if call_import.schema_id is not None:
        from app.models.database import CallImportSchema

        schema = (
            db.query(CallImportSchema)
            .filter(CallImportSchema.id == call_import.schema_id)
            .first()
        )
        if schema is not None:
            for param in schema.parameters:
                if (param.name or "").strip().lower() == "transcript":
                    omitted.add(param.name)
    return omitted


def build_export_layout(
    db: Session,
    call_import: CallImport,
    evaluation: CallImportEvaluation,
    *,
    include_transcripts: bool,
) -> ExportLayout:
    selected = _selected_metric_ids(evaluation.selected_metric_ids)
    groups_raw = (
        evaluation.selected_metric_groups
        if isinstance(evaluation.selected_metric_groups, dict)
        else {}
    )
    lookup_ids = list(selected)
    for parent_str in groups_raw.keys():
        try:
            parent_id = UUID(str(parent_str))
        except (TypeError, ValueError):
            continue
        if parent_id not in lookup_ids:
            lookup_ids.append(parent_id)
    metrics = _metrics_for_ids(db, call_import.organization_id, lookup_ids)
    metric_names = {str(metric.id): metric.name for metric in metrics}
    metrics_by_id = {str(metric.id): metric for metric in metrics}

    omitted = set() if include_transcripts else _omitted_raw_headers(call_import, db)
    standard_headers: List[str] = []
    custom_export: List[Tuple[str, str]] = []

    if call_import.schema_id is not None:
        from app.models.database import CallImportSchema

        schema = (
            db.query(CallImportSchema)
            .filter(CallImportSchema.id == call_import.schema_id)
            .first()
        )
        if schema is not None:
            for param in sorted(schema.parameters, key=lambda item: item.ordering or 0):
                if (
                    param.name
                    and param.name not in standard_headers
                    and param.name not in omitted
                ):
                    standard_headers.append(param.name)
        else:
            for param_name in (call_import.parameter_mapping or {}).keys():
                if (
                    param_name
                    and param_name not in standard_headers
                    and param_name not in omitted
                ):
                    standard_headers.append(param_name)
    else:
        mapping = call_import.column_mapping or {}
        mapped_headers = [
            mapping.get("external_call_id"),
            mapping.get("transcript"),
            mapping.get("recording_url"),
        ]
        for header in [*mapped_headers, *(call_import.extra_columns or [])]:
            if (
                isinstance(header, str)
                and header
                and header not in standard_headers
                and header not in omitted
            ):
                standard_headers.append(header)
        custom_mapping = call_import.custom_column_mapping or {}
        if isinstance(custom_mapping, dict):
            for name, csv_header in custom_mapping.items():
                if not isinstance(name, str) or not isinstance(csv_header, str):
                    continue
                if not name or not csv_header or name in standard_headers:
                    continue
                if csv_header in omitted or name in omitted:
                    continue
                custom_export.append((name, csv_header))

    if (
        call_import.source_format == "audio"
        and "conversation_id" not in standard_headers
    ):
        standard_headers.insert(0, "conversation_id")

    child_ids: set = set()
    for child_strs in groups_raw.values():
        for child_str in child_strs:
            if isinstance(child_str, str):
                child_ids.add(child_str)

    metric_headers: List[str] = []
    rationale_headers: Dict[str, str] = {}
    seen: set = set()

    def _add_metric(metric: Metric) -> None:
        mid = str(metric.id)
        if mid in seen or mid in child_ids:
            return
        seen.add(mid)
        header = metric_names[mid]
        metric_headers.append(header)
        if include_transcripts and bool(getattr(metric, "capture_rationale", False)):
            rationale_header = f"{header} - LLM Rationale"
            metric_headers.append(rationale_header)
            rationale_headers[mid] = rationale_header

    for parent_str in groups_raw.keys():
        parent = metrics_by_id.get(str(parent_str))
        if parent is not None:
            _add_metric(parent)
    for metric in metrics:
        if metric.selection_mode and not metric.parent_metric_id:
            continue
        if str(metric.id) in seen:
            continue
        _add_metric(metric)

    fieldnames = [
        *standard_headers,
        *[header for header, _key in custom_export],
    ]
    if include_transcripts:
        fieldnames.extend(
            [
                PRODUCTION_TRANSCRIPT_HEADER,
                DIARISED_TRANSCRIPT_HEADER,
                EVAL_SOURCE_HEADER,
            ]
        )
    else:
        fieldnames.append(EVAL_SOURCE_HEADER)
    fieldnames.extend(metric_headers)
    return ExportLayout(
        fieldnames=fieldnames,
        standard_headers=standard_headers,
        custom_export=custom_export,
        rationale_headers=rationale_headers,
        metrics=metrics,
        metrics_by_id=metrics_by_id,
        include_transcripts=include_transcripts,
        transcript_source=(evaluation.transcript_source or "diarised"),
        omitted_raw_headers=omitted,
    )


def project_export_row(
    layout: ExportLayout,
    _evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow,
) -> Dict[str, str]:
    row_out: Dict[str, str] = {}
    raw = source_row.raw_columns if isinstance(source_row.raw_columns, dict) else {}
    for header in layout.standard_headers:
        value = raw.get(header)
        if value is None and header == "conversation_id":
            value = source_row.conversation_id
        row_out[header] = "" if value is None else str(value)
    for export_header, csv_header in layout.custom_export:
        value = raw.get(csv_header)
        row_out[export_header] = "" if value is None else str(value)

    if layout.include_transcripts:
        row_out[PRODUCTION_TRANSCRIPT_HEADER] = _flatten_transcript(source_row.transcript)
        row_out[DIARISED_TRANSCRIPT_HEADER] = _flatten_transcript(
            source_row.diarised_transcript
        )
    row_out[EVAL_SOURCE_HEADER] = _source_label(
        layout.transcript_source,
        source_row,
        include_transcripts=layout.include_transcripts,
    )

    scores = eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {}
    for metric in layout.metrics:
        metric_score = scores.get(str(metric.id)) if isinstance(scores, dict) else None
        value = metric_score.get("value") if isinstance(metric_score, dict) else None
        if (
            metric.selection_mode
            and not metric.parent_metric_id
            and isinstance(metric_score, dict)
        ):
            if metric.selection_mode == "multi_label":
                selected = metric_score.get("selected_child_names")
                if isinstance(selected, list):
                    value = ";".join(str(item) for item in selected)
            else:
                value = metric_score.get("chosen_child_name") or metric_score.get("value")
        row_out[metric.name] = "" if value is None else str(value)
        rationale_header = layout.rationale_headers.get(str(metric.id))
        if rationale_header is not None:
            rationale = (
                metric_score.get("rationale") if isinstance(metric_score, dict) else None
            )
            row_out[rationale_header] = "" if rationale is None else str(rationale)
    return row_out


def export_page_query(
    session: Session,
    evaluation_id: UUID,
    *,
    include_transcripts: bool,
    after: Optional[Tuple[int, UUID]] = None,
):
    """One ordered page. The default query does not select transcript bodies."""
    eval_columns = (
        CallImportEvaluationRow.id,
        CallImportEvaluationRow.call_import_row_id,
        CallImportEvaluationRow.metric_scores,
    )
    source_columns = [
        CallImportRow.id,
        CallImportRow.row_index,
        CallImportRow.conversation_id,
        CallImportRow.raw_columns,
    ]
    if include_transcripts:
        source_columns.extend(
            [CallImportRow.transcript, CallImportRow.diarised_transcript]
        )
    query = (
        session.query(CallImportEvaluationRow, CallImportRow)
        .join(
            CallImportRow,
            CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
        )
        .options(
            load_only(*eval_columns),
            load_only(*source_columns),
        )
        .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
    )
    if after is not None:
        row_index, row_id = after
        query = query.filter(
            or_(
                CallImportRow.row_index > row_index,
                and_(
                    CallImportRow.row_index == row_index,
                    CallImportRow.id > row_id,
                ),
            )
        )
    return query.order_by(CallImportRow.row_index.asc(), CallImportRow.id.asc())


def _expunge_pair(session: Session, pair) -> None:
    for obj in pair:
        state = getattr(obj, "_sa_instance_state", None)
        if state is not None and state.session is session:
            session.expunge(obj)


class _ExportCursor:
    def __init__(
        self,
        session: Session,
        evaluation_id: UUID,
        *,
        include_transcripts: bool,
    ):
        self.session = session
        self.evaluation_id = evaluation_id
        self.include_transcripts = include_transcripts
        self._buf: list = []
        self._pos = 0
        self._after: Optional[Tuple[int, UUID]] = None
        self._exhausted = False

    def peek(self):
        if self._pos >= len(self._buf):
            self._fill()
        if self._pos >= len(self._buf):
            return None
        return self._buf[self._pos]

    def pop(self):
        item = self.peek()
        if item is None:
            return None
        self._pos += 1
        return item

    def _fill(self) -> None:
        if self._exhausted:
            self._buf = []
            self._pos = 0
            return
        for pair in self._buf:
            _expunge_pair(self.session, pair)
        rows = (
            export_page_query(
                self.session,
                self.evaluation_id,
                include_transcripts=self.include_transcripts,
                after=self._after,
            )
            .limit(EXPORT_PAGE_SIZE)
            .all()
        )
        for pair in rows:
            _expunge_pair(self.session, pair)
        if rows:
            last_source = rows[-1][1]
            self._after = (int(last_source.row_index or 0), last_source.id)
        self._buf = rows
        self._pos = 0
        # End this page's snapshot. The rows are already detached, so the
        # caller can project them after the commit.
        self.session.commit()
        if not rows:
            self._exhausted = True
            return
        if len(rows) < EXPORT_PAGE_SIZE:
            self._exhausted = True


def _merge_cursors(cursors: List[_ExportCursor]):
    heap: list = []
    for index, cursor in enumerate(cursors):
        item = cursor.peek()
        if item is None:
            continue
        _eval_row, source_row = item
        heapq.heappush(
            heap,
            (
                (int(source_row.row_index or 0), str(source_row.id), index),
                index,
            ),
        )
    while heap:
        _key, index = heapq.heappop(heap)
        pair = cursors[index].pop()
        if pair is None:
            continue
        yield pair
        nxt = cursors[index].peek()
        if nxt is not None:
            _eval_row, source_row = nxt
            heapq.heappush(
                heap,
                (
                    (int(source_row.row_index or 0), str(source_row.id), index),
                    index,
                ),
            )


def iter_export_pairs(
    catalog_db: Session,
    call_import_id: UUID,
    evaluation_id: UUID,
    *,
    include_transcripts: bool,
) -> Iterator[Tuple[CallImportEvaluationRow, CallImportRow]]:
    from app.db_sharding.sessions import is_sharding_enabled

    if not is_sharding_enabled():
        cursor = _ExportCursor(
            catalog_db,
            evaluation_id,
            include_transcripts=include_transcripts,
        )
        while True:
            pair = cursor.pop()
            if pair is None:
                break
            yield pair
        return

    from app.db_sharding.pool_manager import db_pool_manager
    from app.db_sharding.scatter_gather import shard_ids_for_import

    sessions = []
    try:
        for shard_id in shard_ids_for_import(catalog_db, call_import_id):
            session = db_pool_manager.shard_session_factory(shard_id)()
            sessions.append(session)
        cursors = [
            _ExportCursor(
                session,
                evaluation_id,
                include_transcripts=include_transcripts,
            )
            for session in sessions
        ]
        yielded = False
        for pair in _merge_cursors(cursors):
            yielded = True
            yield pair
        if not yielded:
            catalog_cursor = _ExportCursor(
                catalog_db,
                evaluation_id,
                include_transcripts=include_transcripts,
            )
            while True:
                pair = catalog_cursor.pop()
                if pair is None:
                    break
                yield pair
    finally:
        for session in sessions:
            session.close()


def write_csv_gz_parts(
    rows: Iterator[Dict[str, str]],
    fieldnames: Sequence[str],
    dest_dir: str,
    *,
    part_rows: int = EXPORT_PART_ROW_COUNT,
) -> List[dict]:
    """Write gzip CSV files, closing a part every ``part_rows`` data rows."""
    parts: List[dict] = []
    part_index = 0
    handle = None
    writer = None
    path = None
    part_count = 0

    def _open() -> None:
        nonlocal handle, writer, path, part_count, part_index
        part_index += 1
        path = os.path.join(dest_dir, f"part-{part_index:04d}.csv.gz")
        handle = gzip.open(path, "wt", encoding="utf-8-sig", newline="")
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        part_count = 0

    def _close() -> None:
        nonlocal handle
        if handle is None or path is None:
            return
        handle.close()
        handle = None
        parts.append(
            {
                "part": part_index,
                "path": path,
                "row_count": part_count,
                "byte_size": os.path.getsize(path),
            }
        )

    try:
        for row in rows:
            if writer is None:
                _open()
            assert writer is not None
            writer.writerow(row)
            part_count += 1
            if part_count >= part_rows:
                _close()
                writer = None
        if writer is not None:
            _close()
        return parts
    finally:
        if handle is not None:
            handle.close()


def write_xlsx(path: str, fieldnames: Sequence[str], rows: Iterator[Dict[str, str]]) -> int:
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font

    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet(title="Evaluation")
    bold = Font(bold=True)
    header_cells = []
    for header in fieldnames:
        cell = WriteOnlyCell(worksheet, value=header)
        cell.font = bold
        header_cells.append(cell)
    worksheet.append(header_cells)
    count = 0
    for row in rows:
        worksheet.append([row.get(header, "") for header in fieldnames])
        count += 1
    workbook.save(path)
    return count


def _export_object_key(
    job: CallImportEvaluationExport,
    filename: str,
) -> str:
    from app.services.storage.blob_storage_service import blob_storage_service

    prefix = blob_storage_service.prefix or ""
    return (
        f"{prefix}organizations/{job.organization_id}/call-imports/"
        f"{job.call_import_id}/evaluations/{job.evaluation_id}/exports/"
        f"{job.id}/{filename}"
    )


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def export_job_is_stale(job: CallImportEvaluationExport) -> bool:
    """True when a running export has stopped updating its heartbeat."""
    if job.status != "running":
        return False
    beat = _aware(job.heartbeat_at) or _aware(job.created_at)
    if beat is None:
        return True
    return datetime.now(timezone.utc) - beat > EXPORT_HEARTBEAT_STALE


def _fail_job(db: Session, job: CallImportEvaluationExport, message: str) -> None:
    job.status = "failed"
    job.error_message = message
    job.finished_at = datetime.now(timezone.utc)
    db.commit()


def _job_status(db: Session, job_id: UUID) -> dict:
    job = (
        db.query(CallImportEvaluationExport)
        .filter(CallImportEvaluationExport.id == job_id)
        .first()
    )
    if job is None:
        return {"job_id": str(job_id), "status": "missing"}
    return {"job_id": str(job_id), "status": job.status}


def _claim_export_job(db: Session, job_id: UUID) -> Optional[str]:
    """Take a pending job, or a running one whose heartbeat has gone stale."""
    now = datetime.now(timezone.utc)
    token = str(uuid4())
    result = db.execute(
        update(CallImportEvaluationExport)
        .where(
            CallImportEvaluationExport.id == job_id,
            or_(
                CallImportEvaluationExport.status == "pending",
                and_(
                    CallImportEvaluationExport.status == "running",
                    or_(
                        CallImportEvaluationExport.heartbeat_at.is_(None),
                        CallImportEvaluationExport.heartbeat_at
                        < now - EXPORT_HEARTBEAT_STALE,
                    ),
                ),
            ),
        )
        .values(
            status="running",
            error_message=None,
            claim_token=token,
            heartbeat_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if result.rowcount == 0:
        return None
    return token


def _touch_export_job(db: Session, job_id: UUID, claim_token: str) -> bool:
    result = db.execute(
        update(CallImportEvaluationExport)
        .where(
            CallImportEvaluationExport.id == job_id,
            CallImportEvaluationExport.claim_token == claim_token,
            CallImportEvaluationExport.status == "running",
        )
        .values(heartbeat_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return bool(result.rowcount)


def _complete_export_job(
    db: Session,
    job_id: UUID,
    claim_token: str,
    parts: List[dict],
) -> bool:
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(CallImportEvaluationExport)
        .where(
            CallImportEvaluationExport.id == job_id,
            CallImportEvaluationExport.claim_token == claim_token,
            CallImportEvaluationExport.status == "running",
        )
        .values(
            status="completed",
            parts=parts,
            error_message=None,
            heartbeat_at=now,
            finished_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return bool(result.rowcount)


def _fail_if_owner(db: Session, job_id: UUID, claim_token: str, message: str) -> bool:
    result = db.execute(
        update(CallImportEvaluationExport)
        .where(
            CallImportEvaluationExport.id == job_id,
            CallImportEvaluationExport.claim_token == claim_token,
        )
        .values(
            status="failed",
            error_message=message,
            finished_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return bool(result.rowcount)


def _detach_mapped(session: Session, obj) -> None:
    state = getattr(obj, "_sa_instance_state", None)
    if state is not None and state.session is session:
        session.expunge(obj)


def _rows_with_heartbeat(rows, db: Session, job_id: UUID, claim_token: str):
    count = 0
    for row in rows:
        count += 1
        if (
            count % EXPORT_PAGE_SIZE == 0
            and not _touch_export_job(db, job_id, claim_token)
        ):
            raise _ExportSuperseded()
        yield row


def execute_evaluation_export(db: Session, job_id: UUID) -> dict:
    """Build one export job into blob storage, one gzip part at a time."""
    from app.services.storage.blob_storage_service import blob_storage_service

    job = (
        db.query(CallImportEvaluationExport)
        .filter(CallImportEvaluationExport.id == job_id)
        .first()
    )
    if job is None:
        return {"job_id": str(job_id), "status": "missing"}
    if not blob_storage_service.is_enabled():
        if job.status not in {"completed", "failed"}:
            _fail_job(db, job, "Blob storage is not configured")
        return _job_status(db, job_id)

    claim_token = _claim_export_job(db, job_id)
    if claim_token is None:
        return _job_status(db, job_id)

    dest = None
    uploaded: List[str] = []
    try:
        evaluation = (
            db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id == job.evaluation_id)
            .first()
        )
        call_import = (
            db.query(CallImport).filter(CallImport.id == job.call_import_id).first()
        )
        if evaluation is None or call_import is None:
            _fail_if_owner(db, job_id, claim_token, "Evaluation not found")
            return {"job_id": str(job_id), "status": "failed"}

        export_format = job.format
        include_transcripts = bool(job.include_transcripts)
        call_import_id = call_import.id
        evaluation_id = evaluation.id
        layout = build_export_layout(
            db,
            call_import,
            evaluation,
            include_transcripts=include_transcripts,
        )
        for metric in layout.metrics:
            _detach_mapped(db, metric)
        db.commit()

        dest = tempfile.mkdtemp(prefix="eval-export-")
        projected = _rows_with_heartbeat(
            (
                project_export_row(layout, evaluation, eval_row, source_row)
                for eval_row, source_row in iter_export_pairs(
                    db,
                    call_import_id,
                    evaluation_id,
                    include_transcripts=include_transcripts,
                )
            ),
            db,
            job_id,
            claim_token,
        )
        stored_parts: List[dict] = []
        key_job = job
        if export_format == "xlsx":
            filename = f"call-import-{call_import_id}-evaluation-{evaluation_id}.xlsx"
            path = os.path.join(dest, filename)
            row_count = write_xlsx(path, layout.fieldnames, projected)
            key = _export_object_key(key_job, filename)
            blob_storage_service.upload_file_by_key_from_path(
                path, key, content_type=XLSX_CONTENT_TYPE
            )
            uploaded.append(key)
            stored_parts.append(
                {
                    "part": 1,
                    "s3_key": key,
                    "filename": filename,
                    "row_count": row_count,
                    "byte_size": os.path.getsize(path),
                }
            )
        else:
            written = write_csv_gz_parts(projected, layout.fieldnames, dest)
            if not written:
                filename = (
                    f"call-import-{call_import_id}-evaluation-{evaluation_id}.csv.gz"
                )
                path = os.path.join(dest, filename)
                with gzip.open(path, "wt", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=layout.fieldnames,
                        extrasaction="ignore",
                    )
                    writer.writeheader()
                written = [
                    {
                        "part": 1,
                        "path": path,
                        "row_count": 0,
                        "byte_size": os.path.getsize(path),
                    }
                ]
            for part in written:
                part_no = int(part["part"])
                filename = (
                    f"call-import-{call_import_id}-evaluation-{evaluation_id}"
                    f"-part-{part_no:04d}.csv.gz"
                )
                key = _export_object_key(key_job, filename)
                blob_storage_service.upload_file_by_key_from_path(
                    part["path"],
                    key,
                    content_type=CSV_GZ_CONTENT_TYPE,
                )
                uploaded.append(key)
                stored_parts.append(
                    {
                        "part": part_no,
                        "s3_key": key,
                        "filename": filename,
                        "row_count": part["row_count"],
                        "byte_size": part["byte_size"],
                    }
                )
                os.remove(part["path"])
        if not _complete_export_job(db, job_id, claim_token, stored_parts):
            raise _ExportSuperseded()
        return {
            "job_id": str(job_id),
            "status": "completed",
            "parts": len(stored_parts),
        }
    except _ExportSuperseded:
        db.rollback()
        return _job_status(db, job_id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        owned = _fail_if_owner(db, job_id, claim_token, str(exc))
        if owned:
            for key in uploaded:
                try:
                    blob_storage_service.delete_file_by_key(key)
                except Exception:
                    pass
        return {"job_id": str(job_id), "status": "failed", "error": str(exc)}
    finally:
        if dest is not None:
            shutil.rmtree(dest, ignore_errors=True)


def render_export_csv_bytes(
    db: Session,
    call_import: CallImport,
    evaluation: CallImportEvaluation,
    *,
    include_transcripts: bool,
) -> bytes:
    """Small in-memory CSV for column tests. The worker writes gzip files instead."""
    import io

    layout = build_export_layout(
        db,
        call_import,
        evaluation,
        include_transcripts=include_transcripts,
    )
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=layout.fieldnames, extrasaction="ignore")
    writer.writeheader()
    for eval_row, source_row in iter_export_pairs(
        db,
        call_import.id,
        evaluation.id,
        include_transcripts=include_transcripts,
    ):
        writer.writerow(
            project_export_row(layout, evaluation, eval_row, source_row)
        )
    return buffer.getvalue().encode("utf-8-sig")


def render_export_xlsx_bytes(
    db: Session,
    call_import: CallImport,
    evaluation: CallImportEvaluation,
) -> bytes:
    layout = build_export_layout(
        db,
        call_import,
        evaluation,
        include_transcripts=False,
    )
    dest = tempfile.mkdtemp(prefix="eval-export-test-")
    path = os.path.join(dest, "export.xlsx")
    try:
        projected = (
            project_export_row(layout, evaluation, eval_row, source_row)
            for eval_row, source_row in iter_export_pairs(
                db,
                call_import.id,
                evaluation.id,
                include_transcripts=False,
            )
        )
        write_xlsx(path, layout.fieldnames, projected)
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        shutil.rmtree(dest, ignore_errors=True)
