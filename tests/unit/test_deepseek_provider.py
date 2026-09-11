"""DeepSeek 结构化模型适配器的离线契约测试。"""

from pathlib import Path

import pytest

from sales_research_agent.domain.models import Brief, DocumentBlock, Evidence, ResearchQuestion
from sales_research_agent.providers.deepseek import DeepSeekProvider
from tests.fakes import SequenceChatModel


def _plan_json() -> str:
    return (Path(__file__).parents[1] / "fixtures" / "deepseek" / "plan_success.json").read_text(
        encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_deepseek_retries_one_empty_json_response() -> None:
    client = SequenceChatModel(["", _plan_json()])
    provider = DeepSeekProvider(client=client)
    brief = Brief(
        id="brief-1",
        run_id="run-1",
        customer_name="海尔智家",
        scenario="首次交流",
        known_context="公开信息调研",
        research_goal="准备首次交流问题",
    )

    plan = await provider.plan(brief)

    assert len(plan.questions) <= 4
    assert provider.call_count == 2
    assert len(client.calls) == 2
    assert client.calls[0]["kwargs"] == {"response_format": {"type": "json_object"}}
    messages = client.calls[0]["input"]
    assert isinstance(messages, list)
    assert messages[0]["role"] == "system"
    assert "JSON" in messages[0]["content"]


@pytest.mark.asyncio
async def test_deepseek_retries_plan_with_non_domain_source_type_values() -> None:
    client = SequenceChatModel(
        [
            (
                '{"questions":[{"text":"海尔智家的战略重点是什么？",'
                '"purpose":"建立公开背景。",'
                '"preferred_source_types":["公司官网","年度报告"],'
                '"completion_criteria":"至少有一个可定位的官方来源。"}]}'
            ),
            _plan_json(),
        ]
    )
    provider = DeepSeekProvider(client=client)
    brief = Brief(
        id="brief-1",
        run_id="run-1",
        customer_name="海尔智家",
        scenario="首次交流",
        known_context="公开信息调研",
        research_goal="准备首次交流问题",
    )

    plan = await provider.plan(brief)

    assert plan.questions[0].preferred_source_types == ["OFFICIAL"]
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_deepseek_exposes_structured_minimal_contracts_for_research_steps() -> None:
    client = SequenceChatModel(
        [
            (
                '{"candidates":[{"document_block_id":"block-1",'
                '"quote":"公开年度报告","rationale":"原文直接陈述。"}]}'
            ),
            (
                '{"claims":[{"kind":"FACT","text":"公司发布年度报告。",'
                '"evidence_ids":["evidence-1"],"upstream_claim_ids":[]}]}'
            ),
            '{"decision":"SUPPORTED","reason":"证据直接支持该事实。"}',
        ]
    )
    provider = DeepSeekProvider(client=client)
    brief = Brief(
        id="brief-1",
        run_id="run-1",
        customer_name="海尔智家",
        scenario="首次交流",
        known_context="公开信息调研",
        research_goal="准备首次交流问题",
    )
    question = ResearchQuestion(
        id="question-1",
        run_id="run-1",
        text="公司公开战略是什么？",
        purpose="建立背景",
        preferred_source_types=["OFFICIAL"],
        completion_criteria="有官方来源",
    )
    block = DocumentBlock(
        id="block-1",
        run_id="run-1",
        source_revision_id="revision-1",
        ordinal=0,
        text="公开年度报告",
        clean_start=0,
        clean_end=6,
    )
    evidence = Evidence(
        id="evidence-1",
        run_id="run-1",
        block_id="block-1",
        quote="公开年度报告",
        start=0,
        end=6,
        locator_method="EXACT",
        numeric_ok=True,
        status="PROPOSED",
    )

    extracted = await provider.extract_evidence(question, [block])
    claims = await provider.synthesize_claims(brief, [evidence])
    verification = await provider.verify_support(claims.claims[0], [evidence])

    assert extracted.candidates[0].document_block_id == "block-1"
    assert claims.claims[0].evidence_ids == ["evidence-1"]
    assert verification.decision == "SUPPORTED"
    assert provider.call_count == 3
