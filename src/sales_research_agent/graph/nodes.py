"""POC Graph 的无状态节点工厂。"""

from datetime import UTC, datetime
from typing import Any

from sales_research_agent.domain.models import DocumentBlock, ResearchQuestion, Source
from sales_research_agent.ingestion.extractor import HtmlExtractor
from sales_research_agent.ingestion.ingestor import HtmlIngestor
from sales_research_agent.ingestion.pdf_ingestor import PdfIngestor
from sales_research_agent.reporting.compiler import publish_report
from sales_research_agent.reporting.models import (
    ReportEvidence,
    ReportFact,
    ReportFailure,
    ReportGap,
    ReportModel,
    ReportQuestion,
    ReportSource,
    ReportStats,
)
from sales_research_agent.runtime import ResearchPipeline
from sales_research_agent.sources.selection import SourceCandidate, select_sources


def make_nodes(services: Any) -> dict[str, Any]:
    """使用闭包绑定基础设施，确保检查点状态仅包含基础数据。"""

    async def plan_research(state: dict[str, Any]) -> dict[str, object]:
        briefs = await services.repository.list_briefs(state["run_id"])
        if len(briefs) != 1:
            raise ValueError("brief is not persisted for this run")
        brief = briefs[0]
        plan = await services.model.plan(brief)
        question_ids: list[str] = []
        for index, planned in enumerate(plan.questions[: services.max_questions]):
            question = ResearchQuestion(
                id=f"question-{index}",
                run_id=state["run_id"],
                text=planned.text,
                purpose=planned.purpose,
                preferred_source_types=planned.preferred_source_types,
                completion_criteria=planned.completion_criteria,
            )
            await services.repository.append_audit_event(
                state["run_id"], {"operation": "PLAN_RESEARCH", "question_id": question.id}
            )
            await services.repository.upsert_research_question(
                question, f"{state['run_id']}:question:{question.id}"
            )
            question_ids.append(question.id)
        return {"research_question_ids": question_ids}

    async def discover_sources(state: dict[str, Any]) -> dict[str, object]:
        candidates_by_question: dict[str, list[SourceCandidate]] = {}
        for question_id in state["research_question_ids"]:
            question = await services.repository.get_research_question(question_id)
            if question is None:
                raise ValueError("research question is not persisted")
            results = await services.search.search(question.text, services.max_sources)
            candidates_by_question[question_id] = [
                SourceCandidate(
                    url=result.url,
                    title=result.title,
                    score=result.score,
                    authority=services.source_policy.classify(result.url),
                    question_ids=(question_id,),
                )
                for result in results
            ]
        source_ids: list[str] = []
        for index, candidate in enumerate(select_sources(candidates_by_question, services.max_sources)):
            source = Source(
                id=f"source-{index}", run_id=state["run_id"], url=candidate.url,
                    canonical_url=candidate.url, title=candidate.title, source_type="WEB",
                discovered_by_question_ids=list(candidate.question_ids), authority=candidate.authority,
                content_kind=services.source_policy.content_kind(candidate.url),
            )
            await services.repository.upsert_source(source, f"{state['run_id']}:source:{source.canonical_url}")
            source_ids.append(source.id)
        return {"source_ids": source_ids}

    async def ingest_source(state: dict[str, Any]) -> dict[str, object]:
        source_id = state["current_source_id"]
        if services.crash_once and source_id == "source-1":
            services.crash_once = False
            raise RuntimeError("injected graph crash")
        source = await services.repository.get_source(source_id)
        if source is None:
            return {"failed_source_ids": [source_id]}
        is_pdf = source.content_kind == "PDF" or source.url.lower().split("?", 1)[0].endswith(".pdf")
        ingestor = (
            PdfIngestor(services.fetcher, services.pdf_parser, services.artifacts, services.repository)
            if is_pdf
            else HtmlIngestor(services.fetcher, HtmlExtractor(), services.artifacts, services.repository)
        )
        outcome = await ingestor.ingest(state["run_id"], source_id, source.url)
        if outcome.failure is not None or outcome.source_revision is None or outcome.clean_ref is None:
            return {"failed_source_ids": [source_id]}

        clean_text = services.artifacts.read_text(outcome.clean_ref)
        block = DocumentBlock(
            id=f"{source_id}-block-0",
            run_id=state["run_id"],
            source_revision_id=outcome.source_revision.id,
            ordinal=0,
            text=clean_text,
            clean_start=0,
            clean_end=len(clean_text),
        )
        await services.repository.upsert_document_block(
            block, f"{state['run_id']}:document-block:{block.id}"
        )
        question_id = source.discovered_by_question_ids[0]
        question = await services.repository.get_research_question(question_id)
        briefs = await services.repository.list_briefs(state["run_id"])
        if question is None or len(briefs) != 1:
            raise ValueError("persisted Graph inputs are incomplete")
        brief = briefs[0]
        pipeline = ResearchPipeline(
            repository=services.repository,
            artifacts=services.artifacts,
            model=services.model,
            brief=brief,
            question=question,
        )
        pipeline_result = await pipeline.run(block_ids=[block.id])
        return {
            "successful_source_ids": [source_id],
            "approved_claim_ids": pipeline_result.approved_claim_ids,
            "gap_ids": pipeline_result.gap_ids,
            "failure_ids": pipeline_result.failure_ids,
        }

    async def publish(state: dict[str, Any]) -> dict[str, object]:
        report = await _build_report(services, state)
        version = await publish_report(services.artifacts, services.repository, state["run_id"], report)
        failures = await services.repository.list_failures(state["run_id"])
        claims = await services.repository.list_claims(state["run_id"])
        now = services.clock()
        await services.repository.save_stats(
            services.run_stats_type(
                run_id=state["run_id"],
                started_at=datetime.fromisoformat(state["started_at"]),
                finished_at=now.astimezone(UTC),
                search_calls=_service_call_count(services.search),
                http_calls=_service_call_count(services.fetcher),
                model_calls=_model_call_count(services.model),
                sources_succeeded=len(state["successful_source_ids"]),
                sources_failed=len(state["failed_source_ids"]),
                claims_approved=len([claim for claim in claims if claim.status == "APPROVED"]),
                claims_rejected=len([claim for claim in claims if claim.status == "REJECTED"]),
                official_sources_succeeded=sum(1 for item in await services.repository.list_sources(state["run_id"]) if item.authority == "OFFICIAL_PRIMARY" and item.id in state["successful_source_ids"]),
                secondary_sources_succeeded=sum(1 for item in await services.repository.list_sources(state["run_id"]) if item.authority == "TRUSTED_SECONDARY" and item.id in state["successful_source_ids"]),
            )
        )
        return {
            "report_version_id": version.id,
            "execution_status": "FINISHED",
            "report_outcome": "PARTIAL" if failures or state["failed_source_ids"] else "COMPLETE",
        }

    return {"plan_research": plan_research, "discover_sources": discover_sources,
            "ingest_source": ingest_source, "publish_report": publish}


async def _build_report(services: Any, state: dict[str, Any]) -> ReportModel:
    """仅从已持久化且批准的实体构建报告，避免分支时序影响内容。"""
    run_id = state["run_id"]
    sources = await services.repository.list_sources(run_id)
    revisions = {item.id: item for item in await services.repository.list_source_revisions(run_id)}
    blocks = {item.id: item for item in await services.repository.list_document_blocks(run_id)}
    evidence = [item for item in await services.repository.list_evidence(run_id) if item.status == "APPROVED"]
    evidence_source = {
        item.id: revisions[blocks[item.block_id].source_revision_id].source_id
        for item in evidence if item.block_id in blocks and blocks[item.block_id].source_revision_id in revisions
    }
    claims = await services.repository.list_claims(run_id)
    approved = [item for item in claims if item.kind == "FACT" and item.status == "APPROVED"]
    gaps = await services.repository.list_gaps(run_id)
    failures = await services.repository.list_failures(run_id)
    return ReportModel(
        declaration="本报告仅基于公开信息，不代表客户存在任何需求。",
        summary="已完成公开信息核验。",
        facts=tuple(
            ReportFact(
                claim_id=item.id, text=item.text, evidence_ids=tuple(item.evidence_ids),
                source_ids=tuple(sorted({evidence_source[eid] for eid in item.evidence_ids if eid in evidence_source})),
                authority=_fact_authority(item.evidence_ids, evidence_source, sources),
            ) for item in approved
        ),
        recent_changes=(), inferences=(),
        questions=tuple(ReportQuestion(claim_id=item.id, text=item.text) for item in claims if item.kind == "QUESTION"),
        gaps=tuple(ReportGap(code=item.code, description=item.description) for item in gaps),
        failures=tuple(ReportFailure(code=item.code, message=item.message) for item in failures),
        sources=tuple(ReportSource(source_id=item.id, title=item.title, url=item.url, authority=item.authority) for item in sources),
        evidence_index=tuple(
            ReportEvidence(evidence_id=item.id, quote=item.quote, source_id=evidence_source[item.id])
            for item in evidence if item.id in evidence_source
        ),
        stats=ReportStats(
            sources_succeeded=len(state["successful_source_ids"]),
            sources_failed=len(state["failed_source_ids"]), claims_approved=len(approved),
            official_sources_succeeded=sum(1 for item in sources if item.authority == "OFFICIAL_PRIMARY" and item.id in state["successful_source_ids"]),
            secondary_sources_succeeded=sum(1 for item in sources if item.authority == "TRUSTED_SECONDARY" and item.id in state["successful_source_ids"]),
            official_coverage=any(item.authority == "OFFICIAL_PRIMARY" and item.id in state["successful_source_ids"] for item in sources),
        ),
    )


def _fact_authority(evidence_ids: list[str], evidence_source: dict[str, str], sources: list[Source]) -> str:
    by_id = {item.id: item.authority for item in sources}
    authorities = [by_id.get(evidence_source[eid], "UNCLASSIFIED") for eid in evidence_ids if eid in evidence_source]
    if "OFFICIAL_PRIMARY" in authorities:
        return "OFFICIAL_PRIMARY"
    if "TRUSTED_SECONDARY" in authorities:
        return "TRUSTED_SECONDARY"
    return "UNCLASSIFIED"


def _model_call_count(model: Any) -> int:
    return sum(
        len(getattr(model, field, []))
        for field in ("plan_calls", "evidence_calls", "claim_calls", "verification_calls")
    )


def _service_call_count(service: Any) -> int:
    """读取真实 Provider 计数，并兼容测试桩的 calls 列表。"""
    call_count = getattr(service, "call_count", None)
    if isinstance(call_count, int):
        return call_count
    return len(getattr(service, "calls", []))
