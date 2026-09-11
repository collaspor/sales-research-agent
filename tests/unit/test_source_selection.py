from sales_research_agent.sources.selection import SourceCandidate, select_sources


def test_select_sources_reserves_one_unique_url_per_question_then_prefers_authority() -> None:
    selected = select_sources(
        {
            "q1": [SourceCandidate("https://media.example/a", "TRUSTED_SECONDARY", 0.9)],
            "q2": [SourceCandidate("https://official.example/b", "OFFICIAL_PRIMARY", 0.5)],
            "q3": [
                SourceCandidate("https://media.example/a", "TRUSTED_SECONDARY", 0.8),
                SourceCandidate("https://official.example/c", "OFFICIAL_PRIMARY", 0.7),
            ],
            "q4": [SourceCandidate("https://other.example/d", "UNCLASSIFIED", 0.99)],
        },
        max_sources=6,
    )
    assert [item.url for item in selected] == [
        "https://media.example/a",
        "https://official.example/b",
        "https://official.example/c",
        "https://other.example/d",
    ]
    assert selected[0].question_ids == ("q1", "q3")
