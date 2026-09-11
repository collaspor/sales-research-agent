import pytest

from sales_research_agent.ingestion.url_policy import UnsafeUrlError, UrlPolicy, validate_public_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/a",
        "http://127.0.0.1/a",
        "http://10.0.0.1/a",
        "https://user:password@example.com/a",
    ],
)
def test_url_policy_rejects_non_public_targets(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_url(url)


def test_url_policy_rejects_domain_resolving_to_private_address() -> None:
    policy = UrlPolicy(resolver=lambda _host: ["93.184.216.34", "10.0.0.1"])

    with pytest.raises(UnsafeUrlError, match="non-public"):
        policy.validate("https://public.example/article")


def test_url_policy_accepts_http_url_when_all_resolved_addresses_are_global() -> None:
    policy = UrlPolicy(resolver=lambda _host: ["93.184.216.34"])

    assert policy.validate("https://fixture.test/article") == "https://fixture.test/article"
