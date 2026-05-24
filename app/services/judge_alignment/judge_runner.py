"""
Run an LLM-judge against a JudgeDataset and persist alignment metrics.

Reuses the existing `LLMService` so api keys flow through the same
encrypted AIProvider path as the rest of the app. Each sample is sent
to the judge with the prompt below; the response is parsed for a binary
prediction + free-text explanation, and stored on `JudgeRun.predictions`
keyed by sample id.

The judge prompt deliberately uses AlignEval's two-line scaffolding plus
the user's own evaluator criteria (from `Evaluator.custom_prompt`).
"""

import json
import re
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import (
    Evaluator,
    JudgeDataset,
    JudgeRun,
    JudgeSample,
    ModelProvider,
)
from app.services.ai.llm_service import llm_service
from app.services.judge_alignment.metrics import compute_alignment_metrics


JUDGE_SYSTEM_PROMPT = (
    "You are an evaluator that assigns a binary pass/fail verdict to each "
    "sample based on the criteria below. Respond ONLY with a JSON object of "
    'the shape {"prediction": "pass"|"fail", "explanation": "<one short '
    'sentence>"}. Use "fail" when the output violates the criteria, "pass" '
    "otherwise. Do not include any other text."
)

# Maximum characters from input/output to keep the prompt lean.
INPUT_TRUNCATE = 4000
OUTPUT_TRUNCATE = 4000


# ---------------------------------------------------------------------------
# Sample selection
# ---------------------------------------------------------------------------


def select_samples_for_split(
    dataset_id: UUID,
    split: str,
    db: Session,
    *,
    sample_ids: Optional[Sequence[str]] = None,
) -> List[JudgeSample]:
    """
    Pick which samples to evaluate.

    - "all"   -> every labeled sample in the dataset.
    - "dev"   -> the explicit list of sample_ids supplied by the caller
                 (typically built via metrics.split_balanced).
    - "test"  -> same as dev but caller supplies the test list.
    """
    base = db.query(JudgeSample).filter(JudgeSample.dataset_id == dataset_id)

    if split == "all":
        return base.filter(JudgeSample.label.isnot(None)).all()

    if not sample_ids:
        return []

    ids: List[UUID] = []
    for raw in sample_ids:
        try:
            ids.append(UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []

    return base.filter(JudgeSample.id.in_(ids)).all()


# ---------------------------------------------------------------------------
# Prompt + parser
# ---------------------------------------------------------------------------


_FIELD_HEADERS = {
    "user": "User turns (test agent / customer)",
    "agent": "Agent turns (Voice AI under evaluation)",
    "input": "Sample input",
    "output": "Sample output",
}


def _field_header(field: Optional[str], fallback: str) -> str:
    if not field:
        return _FIELD_HEADERS[fallback]
    return _FIELD_HEADERS.get(field, field.replace("_", " ").title())


def _build_user_message(
    criteria: str,
    sample: JudgeSample,
    *,
    input_field: Optional[str] = None,
    output_field: Optional[str] = None,
) -> str:
    in_header = _field_header(input_field, "input")
    out_header = _field_header(output_field, "output")
    return (
        f"## Evaluation criteria\n{criteria.strip()}\n\n"
        f"## {in_header}\n{(sample.input_text or '')[:INPUT_TRUNCATE]}\n\n"
        f"## {out_header}\n{(sample.output_text or '')[:OUTPUT_TRUNCATE]}\n\n"
        'Respond with JSON: {"prediction": "pass"|"fail", "explanation": "..."}'
    )


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_judge_response(raw: str) -> Dict[str, Optional[str]]:
    """Extract {prediction, explanation} from the judge's response."""
    if not raw:
        return {"prediction": None, "explanation": None, "raw": ""}

    text = raw.strip()
    # Strip Markdown code fences (```json ... ```), common with Claude/Anthropic.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    match = _JSON_OBJECT_RE.search(text)
    candidate = match.group(0) if match else text

    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        # Last-ditch: look for a bare "pass"/"fail" in the response.
        lowered = text.lower()
        if "fail" in lowered and "pass" not in lowered:
            return {"prediction": "fail", "explanation": text[:300], "raw": raw}
        if "pass" in lowered and "fail" not in lowered:
            return {"prediction": "pass", "explanation": text[:300], "raw": raw}
        return {"prediction": None, "explanation": text[:300], "raw": raw}

    pred_raw = str(obj.get("prediction", "")).strip().lower()
    if pred_raw in {"fail", "1", "true"}:
        prediction = "fail"
    elif pred_raw in {"pass", "0", "false"}:
        prediction = "pass"
    else:
        prediction = None

    explanation = obj.get("explanation")
    if explanation is not None:
        explanation = str(explanation)[:500]

    return {"prediction": prediction, "explanation": explanation, "raw": raw}


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------


def run_judge(
    judge_run: JudgeRun,
    dataset: JudgeDataset,
    evaluator: Evaluator,
    samples: List[JudgeSample],
    db: Session,
) -> Dict[str, Any]:
    """
    Execute `evaluator` (treated as the judge) against `samples`,
    persist predictions + computed alignment metrics on `judge_run`,
    and return the metrics dict.
    """
    if not evaluator.custom_prompt:
        raise ValueError(
            "Judge alignment requires the Evaluator to have a custom_prompt "
            "defining the pass/fail criteria."
        )
    if not evaluator.llm_provider or not evaluator.llm_model:
        raise ValueError(
            "Judge alignment requires the Evaluator to specify llm_provider "
            "and llm_model."
        )

    try:
        provider_enum = ModelProvider(evaluator.llm_provider.lower())
    except ValueError:
        raise ValueError(
            f"Unknown llm_provider on evaluator: {evaluator.llm_provider!r}"
        )

    # Snapshot the model used so subsequent edits to the Evaluator don't
    # silently rewrite this run's history.
    judge_run.llm_provider = evaluator.llm_provider
    judge_run.llm_model = evaluator.llm_model
    db.commit()

    criteria = evaluator.custom_prompt
    predictions: Dict[str, Dict[str, Any]] = {}
    labels: List[Optional[str]] = []
    preds: List[Optional[str]] = []

    for idx, sample in enumerate(samples):
        if sample.label is None:
            # Unlabeled samples can't move the metrics needle, so skip
            # rather than spending tokens on them.
            continue

        messages = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_user_message(
                    criteria,
                    sample,
                    input_field=dataset.input_field,
                    output_field=dataset.output_field,
                ),
            },
        ]

        try:
            result = llm_service.generate_response(
                messages=messages,
                llm_provider=provider_enum,
                llm_model=evaluator.llm_model,
                organization_id=dataset.organization_id,
                db=db,
                temperature=0.0,
                max_tokens=300,
            )
            parsed = _parse_judge_response(result.get("text", ""))
        except Exception as exc:
            logger.warning(
                f"[JudgeAlignment] Sample {sample.id} judge call failed: {exc}"
            )
            parsed = {"prediction": None, "explanation": str(exc)[:300], "raw": ""}

        predictions[str(sample.id)] = parsed
        labels.append(sample.label)
        preds.append(parsed["prediction"])

        if (idx + 1) % 25 == 0:
            logger.info(
                f"[JudgeAlignment] Run {judge_run.id} progress: {idx + 1}/{len(samples)}"
            )

    metrics = compute_alignment_metrics(labels, preds)

    judge_run.predictions = predictions
    judge_run.metrics = metrics
    judge_run.status = "completed"
    db.commit()

    logger.info(
        f"[JudgeAlignment] Run {judge_run.id} done: "
        f"n={metrics['n']} f1={metrics['f1']} kappa={metrics['kappa']}"
    )
    return metrics
