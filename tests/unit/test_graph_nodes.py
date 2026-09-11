from types import SimpleNamespace

from sales_research_agent.graph.nodes import _service_call_count


def test_service_call_count_supports_production_provider_counter() -> None:
    assert _service_call_count(SimpleNamespace(call_count=4)) == 4


def test_service_call_count_keeps_legacy_fake_calls_compatibility() -> None:
    assert _service_call_count(SimpleNamespace(calls=[1, 2, 3])) == 3
