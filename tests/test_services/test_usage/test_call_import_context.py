"""Tests for call-import usage attribution context."""

from uuid import uuid4

from app.services.usage.bucket_context import build_bucket_context
from app.services.usage.call_import_context import (
    call_import_evaluation_usage_context,
    call_import_ids_from_usage_context,
    call_import_row_usage_context,
    enrich_usage_context_workspace,
)
from app.services.usage.llm_usage import _bucket_prefix


def test_evaluation_rows_share_bucket_context():
    org_id = uuid4()
    ws_id = uuid4()
    eval_id = uuid4()
    import_id = uuid4()

    ctx_a = call_import_evaluation_usage_context(
        organization_id=org_id,
        workspace_id=ws_id,
        evaluation_id=eval_id,
        call_import_id=import_id,
    )
    ctx_b = call_import_evaluation_usage_context(
        organization_id=org_id,
        workspace_id=ws_id,
        evaluation_id=eval_id,
        call_import_id=import_id,
    )

    bucket_a = build_bucket_context(
        resource_id=ctx_a.resource_id,
        resource_type=ctx_a.resource_type,
        extra=ctx_a.extra,
    )
    bucket_b = build_bucket_context(
        resource_id=ctx_b.resource_id,
        resource_type=ctx_b.resource_type,
        extra=ctx_b.extra,
    )
    assert bucket_a == bucket_b
    assert bucket_a["evaluation_id"] == str(eval_id)
    assert bucket_a["call_import_id"] == str(import_id)
    assert "evaluation_row_id" not in bucket_a
    assert "call_import_row_id" not in bucket_a


def test_evaluation_rows_share_redis_bucket_prefix():
    from datetime import date

    org_id = uuid4()
    ws_id = uuid4()
    eval_id = uuid4()
    import_id = uuid4()
    model = "gpt-test"
    usage_date = date(2026, 8, 15)

    def prefix_for(_row_id: object) -> str:
        ctx = call_import_evaluation_usage_context(
            organization_id=org_id,
            workspace_id=ws_id,
            evaluation_id=eval_id,
            call_import_id=import_id,
        )
        context = build_bucket_context(
            resource_id=ctx.resource_id,
            resource_type=ctx.resource_type,
            extra=ctx.extra,
        )
        return _bucket_prefix(
            workspace_id=ws_id,
            product_section=ctx.product_section.value,
            model=model,
            context=context,
            usage_date=usage_date,
            usage_kind="llm",
        )

    assert prefix_for(uuid4()) == prefix_for(uuid4())


def test_row_only_transcribe_context_rolls_up_to_call_import():
    org_id = uuid4()
    import_id = uuid4()
    ctx = call_import_row_usage_context(
        organization_id=org_id,
        workspace_id=None,
        call_import_id=import_id,
    )
    assert ctx.extra == {"call_import_id": str(import_id)}
    assert ctx.resource_type == "call_import"
    assert "call_import_row_id" not in (ctx.extra or {})


def test_call_import_ids_from_evaluation_context():
    org_id = uuid4()
    eval_id = uuid4()
    import_id = uuid4()
    ctx = call_import_evaluation_usage_context(
        organization_id=org_id,
        workspace_id=uuid4(),
        evaluation_id=eval_id,
        call_import_id=import_id,
    )
    ids = call_import_ids_from_usage_context(ctx)
    assert ids["call_import_id"] == import_id
    assert ids["evaluation_id"] == eval_id
    assert ids["evaluation_row_id"] is None
    assert ids["call_import_row_id"] is None


def test_enrich_usage_context_workspace_noop_when_set():
    ws_id = uuid4()
    ctx = call_import_evaluation_usage_context(
        organization_id=uuid4(),
        workspace_id=ws_id,
        evaluation_id=uuid4(),
        call_import_id=uuid4(),
    )
    assert enrich_usage_context_workspace(ctx).workspace_id == ws_id


def test_enrich_usage_context_workspace_from_resolver():
    org_id = uuid4()
    import_id = uuid4()
    ws_id = uuid4()
    ctx = call_import_evaluation_usage_context(
        organization_id=org_id,
        workspace_id=None,
        evaluation_id=uuid4(),
        call_import_id=import_id,
    )
    from unittest.mock import patch

    with patch(
        "app.services.usage.call_import_context.resolve_workspace_id_for_usage_context",
        return_value=ws_id,
    ):
        enriched = enrich_usage_context_workspace(ctx)
    assert enriched.workspace_id == ws_id
