from sales_research_agent.web import validate_web_payload


def test_validate_web_payload_accepts_required_presales_context() -> None:
    payload = validate_web_payload(
        {"customer_name": "海尔智家", "scenario": "首次交流", "known_context": "家电", "research_goal": "了解业务"}
    )

    assert payload["customer_name"] == "海尔智家"


def test_validate_web_payload_rejects_missing_context() -> None:
    try:
        validate_web_payload({"customer_name": "海尔智家"})
    except ValueError as error:
        assert str(error) == "customer_name, scenario, known_context, research_goal are required"
    else:
        raise AssertionError("expected missing context validation error")
