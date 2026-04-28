"""Public, unauthenticated blind-test endpoints.

These endpoints serve the sharable blind-test form. They are deliberately
NOT mounted under any auth or enterprise gate - the share_token in the URL
is the capability that grants access. Owner-side management of shares lives
under /api/v1/voice-playground/comparisons/{id}/share and friends, which DO
require auth and the voice_playground enterprise feature.

Security relies on:
- An unguessable share_token (secrets.token_urlsafe(16))
- status='closed' returning 410 on both GET and POST
- A signed client_token that encodes the per-sample A/B flip used in this
  rendering, so the rater's UI shows neutral 'X'/'Y' but submissions can be
  de-flipped server-side without trusting the client.
- Provider/voice names never appearing in the public payload.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.database import (
    TTSBlindTestResponse,
    TTSBlindTestShare,
    TTSBlindTestShareStatus,
    TTSComparison,
    TTSSample,
    TTSSampleStatus,
)
from app.services.storage.s3_service import s3_service


router = APIRouter(
    prefix="/public/blind-tests",
    tags=["Public Blind Tests"],
)


# Form payloads expire after this many seconds. Raters who leave the tab open
# longer than this will get a stale-token error and need to refresh.
CLIENT_TOKEN_TTL_SECONDS = 60 * 60 * 4  # 4 hours


def _sign(payload_b64: str) -> str:
    secret = (settings.SECRET_KEY or "").encode("utf-8")
    digest = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _make_client_token(share_id: str, flips: List[int]) -> str:
    payload = {
        "sid": share_id,
        "flips": flips,
        "exp": int(time.time()) + CLIENT_TOKEN_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(8),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"{payload_b64}.{_sign(payload_b64)}"


def _verify_client_token(token: str, expected_share_id: str) -> List[int]:
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        raise HTTPException(400, "Malformed form token")

    expected_sig = _sign(payload_b64)
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(400, "Invalid form token signature")

    try:
        padding = "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(raw)
    except Exception:
        raise HTTPException(400, "Malformed form token payload")

    if payload.get("sid") != expected_share_id:
        raise HTTPException(400, "Form token is for a different share")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(400, "Form token expired - please refresh the page")
    flips = payload.get("flips") or []
    if not isinstance(flips, list) or any(f not in (0, 1) for f in flips):
        raise HTTPException(400, "Form token has an invalid flips vector")
    return flips


def _get_open_share(token: str, db: Session) -> TTSBlindTestShare:
    share = db.query(TTSBlindTestShare).filter(
        TTSBlindTestShare.share_token == token,
    ).first()
    if not share:
        raise HTTPException(404, "Blind test not found")
    if share.status != TTSBlindTestShareStatus.OPEN.value:
        raise HTTPException(
            status_code=410,
            detail="This blind test is no longer accepting responses",
        )
    return share


def _build_blind_pairs(comparison: TTSComparison, db: Session) -> List[Dict[str, Any]]:
    """For each sample_index, pick one completed A sample and one completed B sample.

    Returns a list of dicts with internal ('a_sample_id', 'b_sample_id') we use
    to render audio. The caller decides flip orientation separately.
    """
    samples = (
        db.query(TTSSample)
        .filter(
            TTSSample.comparison_id == comparison.id,
            TTSSample.status == TTSSampleStatus.COMPLETED.value,
            TTSSample.audio_s3_key.isnot(None),
        )
        .order_by(TTSSample.sample_index, TTSSample.run_index)
        .all()
    )

    pairs: List[Dict[str, Any]] = []
    sample_count = len(comparison.sample_texts or [])
    for i in range(sample_count):
        pool = [s for s in samples if s.sample_index == i]
        a_pool = [s for s in pool if (s.side == "A") or (not s.side and s.provider == comparison.provider_a)]
        b_pool = [s for s in pool if (s.side == "B") or (not s.side and s.provider == comparison.provider_b)]
        if not a_pool or not b_pool:
            continue
        pairs.append({
            "sample_index": i,
            "text": comparison.sample_texts[i] if i < len(comparison.sample_texts) else "",
            "a_sample": a_pool[0],
            "b_sample": b_pool[0],
        })
    return pairs


def _presign(audio_s3_key: Optional[str]) -> Optional[str]:
    if not audio_s3_key:
        return None
    try:
        return s3_service.generate_presigned_url_by_key(audio_s3_key, expiration=3600)
    except Exception:
        return None


# ---------------------------------------------------------------------- #
# Endpoints
# ---------------------------------------------------------------------- #


class PublicBlindResponseEntry(BaseModel):
    sample_index: int
    preferred: str  # 'X' or 'Y'
    ratings_x: Dict[str, float] = {}
    ratings_y: Dict[str, float] = {}
    comment: Optional[str] = None


class PublicBlindResponseSubmit(BaseModel):
    rater_name: str
    rater_email: str
    client_token: str
    responses: List[PublicBlindResponseEntry]


@router.get("/{share_token}", operation_id="getPublicBlindTest")
async def get_public_blind_test(
    share_token: str,
    db: Session = Depends(get_db),
):
    """Return the form metadata + masked X/Y audio for a rater."""
    share = _get_open_share(share_token, db)

    comparison = db.query(TTSComparison).filter(
        TTSComparison.id == share.comparison_id,
    ).first()
    if not comparison:
        raise HTTPException(404, "Underlying comparison no longer exists")

    pairs = _build_blind_pairs(comparison, db)
    if not pairs:
        raise HTTPException(409, "This blind test has no playable audio yet")

    flips: List[int] = []
    samples_payload: List[Dict[str, Any]] = []
    for p in pairs:
        flipped = secrets.randbits(1)  # 0 = X=A, 1 = X=B
        flips.append(flipped)
        a, b = p["a_sample"], p["b_sample"]
        x_sample = b if flipped else a
        y_sample = a if flipped else b
        samples_payload.append({
            "sample_index": p["sample_index"],
            "text": p["text"],
            "voice_x_url": _presign(x_sample.audio_s3_key),
            "voice_y_url": _presign(y_sample.audio_s3_key),
        })

    client_token = _make_client_token(str(share.id), flips)

    return {
        "title": share.title,
        "description": share.description,
        "custom_metrics": share.custom_metrics or [],
        "samples": samples_payload,
        "client_token": client_token,
        "status": share.status,
    }


@router.post("/{share_token}/responses", operation_id="submitPublicBlindTestResponse")
async def submit_public_blind_test_response(
    share_token: str,
    data: PublicBlindResponseSubmit,
    request: Request,
    db: Session = Depends(get_db),
):
    """Accept a rater's submission and merge into the comparison summary."""
    share = _get_open_share(share_token, db)

    name = (data.rater_name or "").strip()
    email = (data.rater_email or "").strip().lower()
    if not name:
        raise HTTPException(400, "Name is required")
    if not email or "@" not in email or len(email) > 320:
        raise HTTPException(400, "A valid email is required")

    # Reject duplicate submissions from the same email up front so the rater
    # gets a clear error instead of a generic 500 from the unique constraint.
    already = (
        db.query(TTSBlindTestResponse.id)
        .filter(
            TTSBlindTestResponse.share_id == share.id,
            TTSBlindTestResponse.rater_email == email,
        )
        .first()
    )
    if already:
        raise HTTPException(
            status_code=409,
            detail="This email has already submitted a response for this blind test.",
        )

    flips = _verify_client_token(data.client_token, str(share.id))

    # Build allowed metric keys + scales for validation
    rating_metrics: Dict[str, int] = {}
    for m in share.custom_metrics or []:
        if isinstance(m, dict) and m.get("type") == "rating":
            rating_metrics[m["key"]] = int(m.get("scale") or 5)

    comparison = db.query(TTSComparison).filter(
        TTSComparison.id == share.comparison_id,
    ).first()
    if not comparison:
        raise HTTPException(404, "Underlying comparison no longer exists")

    pairs = _build_blind_pairs(comparison, db)
    sample_idx_to_position = {p["sample_index"]: pos for pos, p in enumerate(pairs)}

    seen_sample_indices: set = set()
    cleaned_entries: List[Dict[str, Any]] = []
    for entry in data.responses:
        if entry.sample_index in seen_sample_indices:
            raise HTTPException(400, f"Duplicate response for sample {entry.sample_index}")
        seen_sample_indices.add(entry.sample_index)

        pos = sample_idx_to_position.get(entry.sample_index)
        if pos is None or pos >= len(flips):
            raise HTTPException(400, f"Unknown sample_index {entry.sample_index}")
        flipped = bool(flips[pos])

        preferred_xy = entry.preferred.upper().strip()
        if preferred_xy not in ("X", "Y"):
            raise HTTPException(400, "preferred must be 'X' or 'Y'")
        # De-flip: when flipped, X corresponds to B; otherwise X corresponds to A.
        if preferred_xy == "X":
            preferred_ab = "B" if flipped else "A"
        else:
            preferred_ab = "A" if flipped else "B"

        def _clean_ratings(raw: Dict[str, float]) -> Dict[str, float]:
            out: Dict[str, float] = {}
            for k, v in (raw or {}).items():
                if k not in rating_metrics:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                scale = rating_metrics[k]
                if fv < 0 or fv > scale:
                    continue
                out[k] = fv
            return out

        x_clean = _clean_ratings(entry.ratings_x or {})
        y_clean = _clean_ratings(entry.ratings_y or {})

        if flipped:
            ratings_a, ratings_b = y_clean, x_clean
        else:
            ratings_a, ratings_b = x_clean, y_clean

        comment = (entry.comment or "").strip()
        if len(comment) > 4000:
            comment = comment[:4000]

        cleaned_entries.append({
            "sample_index": entry.sample_index,
            "preferred": preferred_ab,
            "ratings_a": ratings_a,
            "ratings_b": ratings_b,
            "comment": comment or None,
            "flipped": flipped,
        })

    if not cleaned_entries:
        raise HTTPException(400, "At least one response entry is required")

    record = TTSBlindTestResponse(
        share_id=share.id,
        rater_name=name[:255],
        rater_email=email[:320],
        responses=cleaned_entries,
        ip=(request.client.host if request.client else None),
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
    )
    db.add(record)
    try:
        db.commit()
    except Exception:
        # Race condition: another concurrent submit by the same email beat us
        # to the unique constraint. Treat the same as the up-front check.
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This email has already submitted a response for this blind test.",
        )

    # Re-aggregate into the comparison's evaluation_summary
    from app.api.v1.routes.voice_playground import _recompute_summary
    _recompute_summary(comparison, db)

    return {"message": "Thanks for your response!"}
