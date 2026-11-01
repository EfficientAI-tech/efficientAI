from app.services.knowledge_bases.retrieval import format_search_results_for_tool


def test_format_search_results_includes_document_name():
    formatted = format_search_results_for_tool(
        [{"text": "Refund policy is 30 days.", "document_name": "handbook.pdf", "page": 2}]
    )
    assert "handbook.pdf" in formatted
    assert "Refund policy" in formatted


def test_format_search_results_empty():
    assert "No matching" in format_search_results_for_tool([])
