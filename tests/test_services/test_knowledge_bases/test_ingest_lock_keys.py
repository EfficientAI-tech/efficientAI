"""Advisory lock keys must fit PostgreSQL signed int32 pair form."""

from uuid import UUID

from app.services.knowledge_bases.ingest import _ingest_advisory_keys


def test_ingest_advisory_keys_fit_signed_int32():
    samples = [
        UUID("80000000-0000-4000-8000-000000000000"),
        UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        UUID(int=0),
    ]
    for doc_id in samples:
        k1, k2 = _ingest_advisory_keys(doc_id)
        assert -0x80000000 <= k1 <= 0x7FFFFFFF
        assert -0x80000000 <= k2 <= 0x7FFFFFFF
