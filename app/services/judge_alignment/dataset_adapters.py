"""
Dataset adapters: materialize JudgeSamples from each supported source.

Three sources are supported, all funnel into the same `judge_samples`
table:

    - "transcript":      pulls voice transcripts from ManualTranscription
                         and EvaluatorResult.
    - "metric_output":   wraps existing ConversationEvaluation rows so the
                         user can calibrate a judge against a metric they
                         already trust (or want to retire).
    - "csv":             generic AlignEval-style upload of `id, input,
                         output, [label]`.

Each adapter is idempotent w.r.t. (dataset_id, external_id) so re-running
materialisation never duplicates rows.
"""

import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import (
    ConversationEvaluation,
    EvaluatorResult,
    JudgeDataset,
    JudgeSample,
    ManualTranscription,
)


SourceType = str  # "transcript" | "metric_output" | "csv"
ALLOWED_SOURCE_TYPES = {"transcript", "metric_output", "csv"}

# Default field roles for transcript datasets. The judge will see the
# user/test-agent turns as the "input" and the Voice AI's turns as the
# "output". Other source types keep the generic 'input'/'output'.
TRANSCRIPT_INPUT_FIELD = "user"
TRANSCRIPT_OUTPUT_FIELD = "agent"


# ---------------------------------------------------------------------------
# Speaker-segment splitter
# ---------------------------------------------------------------------------

# Word-style labels the codebase uses interchangeably for the Voice AI
# (Vapi/Retell/Smallest webhooks, observability, manual flows).
_AGENT_WORD_LABELS = {"agent", "assistant", "bot", "ai", "voice_agent"}
_USER_WORD_LABELS = {"user", "customer", "test_agent", "caller"}


def _classify_speaker(
    label: Optional[str],
    *,
    agent_speaker: Optional[str] = None,
    user_speaker: Optional[str] = None,
) -> Optional[str]:
    """
    Return "agent" or "user" for a speaker label, or None if it can't be
    classified.

    Resolution order:
      1. Explicit overrides from source_config (agent_speaker / user_speaker).
      2. Word-style labels (Agent/User/Assistant/Bot/Customer/test_agent...).
      3. Numbered diarization labels (Speaker 0/1/2). Speaker 2 == agent
         (matches the webhook convention used in evaluator_results.py and
         playground.py); Speaker 0 == agent (observability convention).
         Speaker 1 == user. Anything else is unclassifiable.
    """
    if label is None:
        return None
    raw = str(label).strip()
    if not raw:
        return None

    if agent_speaker and raw.lower() == str(agent_speaker).strip().lower():
        return "agent"
    if user_speaker and raw.lower() == str(user_speaker).strip().lower():
        return "user"

    lowered = raw.lower()
    if lowered in _AGENT_WORD_LABELS:
        return "agent"
    if lowered in _USER_WORD_LABELS:
        return "user"

    # Numbered diarization conventions used across this codebase:
    #   - Speaker 2 (Vapi/Retell/ElevenLabs/Smallest webhook flow) -> agent
    #   - Speaker 0 (observability bot vs. customer)               -> agent
    #   - Speaker 1                                                 -> user
    if lowered in {"speaker 2", "speaker_2", "speaker2", "2"}:
        return "agent"
    if lowered in {"speaker 0", "speaker_0", "speaker0", "0"}:
        return "agent"
    if lowered in {"speaker 1", "speaker_1", "speaker1", "1"}:
        return "user"

    return None


def split_segments_by_role(
    segments: Optional[List[Dict[str, Any]]],
    *,
    agent_speaker: Optional[str] = None,
    user_speaker: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """
    Group a `speaker_segments` list into rendered "user" / "agent" blobs.

    Returns a dict like ``{"user": "...", "agent": "...", "user_turns":
    int, "agent_turns": int}`` or ``None`` if the list is empty / no
    segment could be classified (in which case the caller should drop
    the row).

    Each turn is rendered on its own line as ``"Agent: ..."`` /
    ``"User: ..."`` so labelers see ordering even though the two panes
    are split by speaker.
    """
    if not segments:
        return None

    user_lines: List[str] = []
    agent_lines: List[str] = []

    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        role = _classify_speaker(
            seg.get("speaker"),
            agent_speaker=agent_speaker,
            user_speaker=user_speaker,
        )
        if role == "agent":
            agent_lines.append(f"Agent: {text}")
        elif role == "user":
            user_lines.append(f"User: {text}")
        # Unclassified turns are dropped on purpose -- mixing them into
        # either bucket would poison the calibration signal.

    if not user_lines and not agent_lines:
        return None

    return {
        "user": "\n".join(user_lines),
        "agent": "\n".join(agent_lines),
        "user_turns": len(user_lines),
        "agent_turns": len(agent_lines),
    }


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def materialize_samples(
    dataset: JudgeDataset,
    db: Session,
    *,
    csv_bytes: Optional[bytes] = None,
    csv_max_rows: int = 5000,
) -> int:
    """
    Populate `dataset` with JudgeSamples. Returns the number of samples
    actually inserted (existing samples for the same external_id are
    left untouched).
    """
    if dataset.source_type not in ALLOWED_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source_type: {dataset.source_type}",
        )

    if dataset.source_type == "transcript":
        # Force the transcript-specific role labels regardless of what
        # the caller passed in. The judge prompt and labeling UI both
        # rely on "user" / "agent" for this source type.
        if dataset.input_field != TRANSCRIPT_INPUT_FIELD:
            dataset.input_field = TRANSCRIPT_INPUT_FIELD
        if dataset.output_field != TRANSCRIPT_OUTPUT_FIELD:
            dataset.output_field = TRANSCRIPT_OUTPUT_FIELD
        rows = _from_transcripts(dataset, db)
    elif dataset.source_type == "metric_output":
        rows = _from_metric_outputs(dataset, db)
    else:  # csv
        if csv_bytes is None:
            raise HTTPException(
                status_code=400,
                detail="CSV bytes are required for source_type='csv'",
            )
        rows = _from_csv(csv_bytes, max_rows=csv_max_rows)

    return _insert_unique(dataset, rows, db)


# ---------------------------------------------------------------------------
# Source-specific extractors
# ---------------------------------------------------------------------------


def _from_transcripts(
    dataset: JudgeDataset, db: Session
) -> List[Dict[str, Any]]:
    """
    Voice-transcript source. Each conversation becomes a single judge
    sample where:

      - ``input_text``  == the User / test agent's turns (what the Voice
                          AI was reacting to).
      - ``output_text`` == the Voice AI's turns (what we want the judge
                          to score).

    The split is driven by ``speaker_segments`` (populated by all
    Vapi/Retell/ElevenLabs/Smallest webhooks and by Pyannote diarization
    on manual transcripts). Conversations with no ``speaker_segments``
    or whose segments cannot be classified into agent/user are dropped;
    the caller raises a friendly error if every candidate was dropped.

    Two source_config shapes are supported:

        {"transcription_ids": ["uuid", ...]}
            -> pull ManualTranscription rows by id.

        {"agent_id": "uuid", "limit": 200}
            -> pull recent EvaluatorResult rows for that agent.

    Optional overrides::

        {"agent_speaker": "Speaker 0", "user_speaker": "Speaker 1"}

    are forwarded to the splitter for organisations whose diarization
    convention differs from the codebase default (Speaker 2 = agent).
    """
    cfg = dataset.source_config or {}
    agent_speaker = cfg.get("agent_speaker")
    user_speaker = cfg.get("user_speaker")

    out: List[Dict[str, Any]] = []
    skipped = 0

    transcription_ids = cfg.get("transcription_ids") or []
    if transcription_ids:
        ids: List[UUID] = []
        for raw_id in transcription_ids:
            try:
                ids.append(UUID(str(raw_id)))
            except (TypeError, ValueError):
                logger.warning(
                    f"[JudgeAlignment] Skipping invalid transcription id: {raw_id}"
                )
        rows = (
            db.query(ManualTranscription)
            .filter(
                ManualTranscription.organization_id == dataset.organization_id,
                ManualTranscription.id.in_(ids),
            )
            .all()
            if ids
            else []
        )
        for t in rows:
            split = split_segments_by_role(
                t.speaker_segments,
                agent_speaker=agent_speaker,
                user_speaker=user_speaker,
            )
            if split is None:
                skipped += 1
                logger.info(
                    f"[JudgeAlignment] Skipping ManualTranscription {t.id}: "
                    "no usable speaker_segments"
                )
                continue
            out.append({
                "external_id": f"manual:{t.id}",
                "input_text": split["user"][:8000],
                "output_text": split["agent"][:8000],
                "extra": {
                    "source": "manual_transcription",
                    "audio_file_key": t.audio_file_key,
                    "name": t.name,
                    "user_turns": split["user_turns"],
                    "agent_turns": split["agent_turns"],
                },
            })
        if not out:
            raise HTTPException(
                status_code=400,
                detail=(
                    "None of the selected transcripts have classifiable "
                    "speaker segments. Re-run diarization or pass "
                    "agent_speaker/user_speaker overrides in source_config."
                    if skipped
                    else "No matching transcripts were found."
                ),
            )
        return out

    agent_id_raw = cfg.get("agent_id")
    if agent_id_raw:
        try:
            agent_uuid = UUID(str(agent_id_raw))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid agent_id")
        limit = int(cfg.get("limit", 200))
        results = (
            db.query(EvaluatorResult)
            .filter(
                EvaluatorResult.organization_id == dataset.organization_id,
                EvaluatorResult.agent_id == agent_uuid,
                EvaluatorResult.transcription.isnot(None),
            )
            .order_by(EvaluatorResult.created_at.desc())
            .limit(limit)
            .all()
        )
        for r in results:
            split = split_segments_by_role(
                r.speaker_segments,
                agent_speaker=agent_speaker,
                user_speaker=user_speaker,
            )
            if split is None:
                skipped += 1
                logger.info(
                    f"[JudgeAlignment] Skipping EvaluatorResult {r.id}: "
                    "no usable speaker_segments"
                )
                continue
            out.append({
                "external_id": f"evalres:{r.id}",
                "input_text": split["user"][:8000],
                "output_text": split["agent"][:8000],
                "extra": {
                    "source": "evaluator_result",
                    "result_id": r.result_id,
                    "agent_id": str(r.agent_id) if r.agent_id else None,
                    "metric_scores": r.metric_scores,
                    "user_turns": split["user_turns"],
                    "agent_turns": split["agent_turns"],
                },
            })
        if not out:
            raise HTTPException(
                status_code=400,
                detail=(
                    "None of the recent evaluator results have classifiable "
                    "speaker segments. Pass agent_speaker/user_speaker "
                    "overrides in source_config or rerun the agent so the "
                    "webhook populates speaker turns."
                    if skipped
                    else "No evaluator results were found for this agent."
                ),
            )
        return out

    raise HTTPException(
        status_code=400,
        detail="transcript source_config requires 'transcription_ids' or 'agent_id'",
    )


def _from_metric_outputs(
    dataset: JudgeDataset, db: Session
) -> Iterable[Dict[str, Any]]:
    """
    Metric-output source. source_config supports::

        {"agent_id": "uuid", "limit": 200}

    Each ConversationEvaluation becomes one sample where:
      - input_text  == the source transcript
      - output_text == the existing evaluator's reasoning + verdict
      - extra       == the existing objective_achieved flag (so the user
                       can pre-seed labels by trusting/inverting it)
    """
    cfg = dataset.source_config or {}
    q = (
        db.query(ConversationEvaluation, ManualTranscription)
        .join(
            ManualTranscription,
            ConversationEvaluation.transcription_id == ManualTranscription.id,
        )
        .filter(ConversationEvaluation.organization_id == dataset.organization_id)
    )

    if agent_id_raw := cfg.get("agent_id"):
        try:
            agent_uuid = UUID(str(agent_id_raw))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid agent_id")
        q = q.filter(ConversationEvaluation.agent_id == agent_uuid)

    limit = int(cfg.get("limit", 200))
    rows = q.order_by(ConversationEvaluation.created_at.desc()).limit(limit).all()

    for ce, t in rows:
        verdict = "PASS" if ce.objective_achieved else "FAIL"
        reason = ce.objective_achieved_reason or ""
        output_blob = (
            f"Verdict: {verdict}\n"
            f"Reasoning: {reason}\n"
            f"Overall score: {ce.overall_score}"
        )
        yield {
            "external_id": f"convoeval:{ce.id}",
            "input_text": (t.transcript or "")[:8000],
            "output_text": output_blob[:8000],
            "extra": {
                "source": "conversation_evaluation",
                "objective_achieved": bool(ce.objective_achieved),
                "overall_score": ce.overall_score,
                "agent_id": str(ce.agent_id) if ce.agent_id else None,
                "transcription_id": str(ce.transcription_id),
                "additional_metrics": ce.additional_metrics,
            },
        }


def _from_csv(csv_bytes: bytes, *, max_rows: int) -> Iterable[Dict[str, Any]]:
    """
    Mirror AlignEval's CSV format exactly:

        id, input, output[, label]

    `label` is optional. When present, "1"/"true"/"fail" -> "fail",
    everything else (including blanks) -> "pass" if explicitly set,
    or null if the cell is empty.
    """
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"CSV is not UTF-8: {exc}")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV has no header row")

    fieldnames = {f.lower(): f for f in reader.fieldnames if f}
    required = {"id", "input", "output"}
    missing = required - set(fieldnames)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"CSV is missing required columns: {sorted(missing)}",
        )

    id_col = fieldnames["id"]
    in_col = fieldnames["input"]
    out_col = fieldnames["output"]
    label_col = fieldnames.get("label")

    count = 0
    for row in reader:
        if count >= max_rows:
            raise HTTPException(
                status_code=400,
                detail=f"CSV exceeds max rows ({max_rows})",
            )
        rid = (row.get(id_col) or "").strip()
        rin = row.get(in_col) or ""
        rout = row.get(out_col) or ""
        if not rid or not rin or not rout:
            continue

        label_value = None
        if label_col:
            raw = (row.get(label_col) or "").strip().lower()
            if raw in {"1", "fail", "true", "positive", "defect"}:
                label_value = "fail"
            elif raw in {"0", "pass", "false", "negative", "ok"}:
                label_value = "pass"

        out: Dict[str, Any] = {
            "external_id": f"csv:{rid}",
            "input_text": rin[:8000],
            "output_text": rout[:8000],
            "extra": {"source": "csv", "csv_id": rid},
        }
        if label_value is not None:
            out["label"] = label_value
            out["labeled_by"] = "csv-import"
        count += 1
        yield out


# ---------------------------------------------------------------------------
# Idempotent insert
# ---------------------------------------------------------------------------


def _insert_unique(
    dataset: JudgeDataset,
    rows: Iterable[Dict[str, Any]],
    db: Session,
) -> int:
    """Insert samples that don't already exist for (dataset_id, external_id)."""
    rows = list(rows)
    if not rows:
        return 0

    external_ids = [r["external_id"] for r in rows if r.get("external_id")]
    existing: set = set()
    if external_ids:
        existing_rows = (
            db.query(JudgeSample.external_id)
            .filter(
                JudgeSample.dataset_id == dataset.id,
                JudgeSample.external_id.in_(external_ids),
            )
            .all()
        )
        existing = {r[0] for r in existing_rows}

    inserted = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.get("external_id") in existing:
            continue

        labeled_at = now if row.get("label") else None
        sample = JudgeSample(
            dataset_id=dataset.id,
            external_id=row.get("external_id"),
            input_text=row["input_text"],
            output_text=row["output_text"],
            label=row.get("label"),
            labeled_by=row.get("labeled_by"),
            labeled_at=labeled_at,
            extra=row.get("extra"),
        )
        db.add(sample)
        inserted += 1

    if inserted:
        db.commit()

    return inserted


# ---------------------------------------------------------------------------
# Validation helpers used by the API layer
# ---------------------------------------------------------------------------


def validate_source_config(
    source_type: SourceType, source_config: Dict[str, Any]
) -> None:
    """Surface configuration errors at dataset-create time, not run time."""
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"source_type must be one of {sorted(ALLOWED_SOURCE_TYPES)}",
        )

    cfg = source_config or {}

    if source_type == "transcript":
        if not cfg.get("transcription_ids") and not cfg.get("agent_id"):
            raise HTTPException(
                status_code=400,
                detail="transcript source requires 'transcription_ids' or 'agent_id'",
            )
    elif source_type == "csv":
        # csv config is finalised when the upload arrives; nothing to do here.
        return
    # metric_output has no required keys (defaults to all rows for the org).


def label_counts(dataset_id: UUID, db: Session) -> Tuple[int, int, int]:
    """Return (total, labeled, unlabeled) for a dataset."""
    from sqlalchemy import func as sa_func

    total = (
        db.query(sa_func.count(JudgeSample.id))
        .filter(JudgeSample.dataset_id == dataset_id)
        .scalar()
        or 0
    )
    labeled = (
        db.query(sa_func.count(JudgeSample.id))
        .filter(
            JudgeSample.dataset_id == dataset_id,
            JudgeSample.label.isnot(None),
        )
        .scalar()
        or 0
    )
    return int(total), int(labeled), int(total - labeled)
