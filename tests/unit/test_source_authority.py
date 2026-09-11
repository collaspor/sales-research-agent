from sales_research_agent.sources.authority import SourceAuthorityPolicy


def test_classify_source_uses_only_explicit_host_sets() -> None:
    policy = SourceAuthorityPolicy(
        official_hosts=frozenset({"haier.com"}),
        trusted_secondary_hosts=frozenset({"stcn.com"}),
    )
    assert policy.classify("https://www.haier.com/report.pdf") == "OFFICIAL_PRIMARY"
    assert policy.classify("https://www.stcn.com/article/1") == "TRUSTED_SECONDARY"
    assert policy.classify("https://unknown.example/a") == "UNCLASSIFIED"
