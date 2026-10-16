from app.services.knowledge_bases.chunking import chunk_plain_text


def test_chunk_plain_text_splits_with_overlap():
    text = "word " * 2000
    chunks = chunk_plain_text(text, max_chars=500, overlap_chars=50)
    assert len(chunks) > 1
    assert chunks[0].chunk_index == 0
    assert all(c.text for c in chunks)
