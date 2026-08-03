from construction_os.drawing.chat_evidence import _ranking_debug


def test_ranking_debug_sanitizes_top_sheet_results():
    response = {
        "rankings": {
            "existing": {
                "result_count": 2,
                "duration_ms": 12.5,
                "score_space": "native_existing_retrieval",
                "retrieval_mode_used": "vector",
                "error": None,
                "results": [
                    {
                        "id": "chunk:one",
                        "parent_id": "source:p203",
                        "title": "Page_007_P203.pdf - Page 1",
                        "similarity": 0.82,
                        "rank": 1,
                    },
                    {
                        "id": "chunk:two",
                        "parent_id": "source:p204",
                        "title": "Page_008_P204.pdf - Page 1",
                        "similarity": 0.71,
                        "rank": 2,
                    },
                ],
            }
        }
    }

    debug = _ranking_debug(response, "existing")

    assert debug is not None
    assert debug["result_count"] == 2
    assert debug["results"][0]["source_id"] == "source:p203"
    assert debug["results"][0]["sheet_number"] == "P203"
    assert debug["results"][0]["score"] == 0.82
    assert "content" not in debug["results"][0]
