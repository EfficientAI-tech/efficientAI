"""Rate limit tests for trace ingest routes."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.auth.principal import AuthMethod, Principal
from app.core.rate_limit import check_trace_rate_limit


def _principal() -> Principal:
    return Principal(
        organization_id=uuid4(),
        auth_method=AuthMethod.API_KEY,
        api_key_id=uuid4(),
    )


@patch("app.core.rate_limit.settings.TRACES_RATE_LIMIT_ENFORCE", True)
@patch("app.core.rate_limit.settings.TRACES_RATE_LIMIT_PER_MINUTE", 2)
@patch("app.core.rate_limit._get_redis")
def test_check_trace_rate_limit_blocks_over_limit(mock_get_redis):
    client = MagicMock()
    client.pipeline.return_value.execute.side_effect = [
        [None, None, 1, None],
        [None, None, 3, None],
    ]
    mock_get_redis.return_value = client

    check_trace_rate_limit(_principal(), route_group="ingest")
    with pytest.raises(HTTPException) as exc:
        check_trace_rate_limit(_principal(), route_group="ingest")
    assert exc.value.status_code == 429
