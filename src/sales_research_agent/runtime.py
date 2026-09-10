"""Evidence 到 Claim 的最小可追溯运行时管线。"""

import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from sales_research_agent.domain.models import (
    Brief,
    Claim,
    DocumentBlock,
    Evidence,
    Failure,
    Gap,
    ResearchQuestion,
    Verification,
)
from sales_research_agent.domain.repository import DomainRepository
from sales_research_agent.infrastructure.artifacts import ArtifactStore
from sales_research_agent.providers.base import (
    ClaimCandidate,
    ClaimSynthesis,
    EvidenceExtraction,
    ResearchModel,
    SupportVerification,
)
from sales_research_agent.providers.deepseek import ProviderSchemaError
from sales_research_agent.verification.gate import decide_claim
from sales_research_agent.verification.numeric_guard import compare_critical_tokens
from sales_research_agent.verification.quote_locator import locate_quote


@dataclass(slots=True)
class PipelineResult:
    """单个问题执行后新增实体的稳定索引。"""

    approved_claim_ids: list[str] = field(default_factory=list)
    gap_ids: list[str] = field(default_factory=list)
    failure_ids: list[str] = field(default_factory=list)


class ResearchPipeline:
    """把模型提议限制在可定位、可核验的外部事实范围内。"""

    def __init__(
        self,
        *,
        repository: DomainRepository,
        artifacts: ArtifactStore,
        model: ResearchModel,
        brief: Brief,
        question: ResearchQuestion,
    ) -> None:
        self._repository = repository
        self._artifacts = artifacts
        self.model = model
        self._brief = brief
        self._question = question
        self._gap_count = 0

    async def run(self, *, block_ids: list[str]) -> PipelineResult:
        """按固定顺序处理正文块，绝不绕过 Evidence 与语义门禁。"""
        result = PipelineResult()
        blocks = await self._load_blocks(block_ids, result)
        if not blocks:
            await self._record_gap(result, "NO_DOCUMENT_BLOCK", "没有可用于提取证据的正文块。")
            return result

        extraction = await self._extract_evidence(blocks, result)
        if extraction is None:
            await self._record_gap(result, "EVIDENCE_EXTRACTION_FAILED", "模型未能返回可用证据。")
            return result

        approved_evidence = await self._validate_and_save_evidence(extraction, blocks)
        if not approved_evidence:
            await self._record_gap(
                result, "EVIDENCE_VALIDATION_FAILED", "没有通过原文定位与数字校验的证据。"
            )
            return result

        synthesis = await self._synthesize_claims(approved_evidence, result)
        if synthesis is None:
            await self._record_gap(result, "CLAIM_SYNTHESIS_FAILED", "模型未能生成可核验 Claim。")
            return result
        if not synthesis.claims:
            await self._record_gap(result, "NO_CLAIM_PROPOSED", "模型没有提出可由证据支撑的 Claim。")
            return result

        await self._verify_and_save_claims(synthesis, approved_evidence, result)
        return result

    async def _load_blocks(
        self, block_ids: list[str], result: PipelineResult
    ) -> list[DocumentBlock]:
        blocks: list[DocumentBlock] = []
        for block_id in block_ids:
            block = await self._repository.get_document_block(block_id)
            if block is None or block.run_id != self._brief.run_id:
                await self._record_failure(
                    result, "LOAD_DOCUMENT_BLOCK", "DOCUMENT_BLOCK_NOT_FOUND", False, block_id
                )
                continue
            blocks.append(block)
        return blocks

    async def _extract_evidence(
        self, blocks: list[DocumentBlock], result: PipelineResult
    ) -> EvidenceExtraction | None:
        for attempt in range(1, 3):
            try:
                extraction = await self.model.extract_evidence(self._question, blocks)
            except ProviderSchemaError:
                if attempt == 2:
                    await self._record_failure(
                        result, "EXTRACT_EVIDENCE", "MODEL_SCHEMA_ERROR", False, self._question.id
                    )
                    return None
                continue
            except TimeoutError:
                await self._record_failure(
                    result, "EXTRACT_EVIDENCE", "MODEL_TIMEOUT", True, self._question.id
                )
                return None
            # Provider 边界必须将任何未分类异常收敛为可审计的领域失败。
            except Exception:  # noqa: BLE001
                await self._record_failure(
                    result, "EXTRACT_EVIDENCE", "MODEL_ERROR", False, self._question.id
                )
                return None
            await self._save_model_response("evidence", attempt, extraction)
            if extraction.candidates:
                return extraction
        return EvidenceExtraction(candidates=[])

    async def _validate_and_save_evidence(
        self, extraction: EvidenceExtraction, blocks: list[DocumentBlock]
    ) -> list[Evidence]:
        by_id = {block.id: block for block in blocks}
        approved: list[Evidence] = []
        for index, candidate in enumerate(extraction.candidates):
            block = by_id.get(candidate.document_block_id)
            match = locate_quote(block.text, candidate.quote) if block is not None else None
            numeric_result = (
                compare_critical_tokens(block.text[match.start : match.end], candidate.quote)
                if block is not None and match is not None
                else None
            )
            located = match is not None
            numeric_ok = numeric_result.ok if numeric_result is not None else False
            evidence = Evidence(
                id=f"evidence-{candidate.document_block_id}-{index}",
                run_id=self._brief.run_id,
                block_id=candidate.document_block_id,
                quote=candidate.quote,
                start=match.start if match is not None else 0,
                end=match.end if match is not None else 0,
                locator_method=match.method if match is not None else "NOT_FOUND",
                numeric_ok=numeric_ok,
                status="APPROVED" if located and numeric_ok else "REJECTED",
            )
            await self._repository.upsert_evidence(
                evidence, f"{self._brief.run_id}:evidence:{evidence.id}"
            )
            if evidence.status == "APPROVED":
                approved.append(evidence)
        return approved

    async def _synthesize_claims(
        self, evidence: list[Evidence], result: PipelineResult
    ) -> ClaimSynthesis | None:
        try:
            synthesis = await self.model.synthesize_claims(self._brief, evidence)
        except ProviderSchemaError:
            await self._record_failure(
                result, "SYNTHESIZE_CLAIMS", "MODEL_SCHEMA_ERROR", False, self._question.id
            )
            return None
        except TimeoutError:
            await self._record_failure(
                result, "SYNTHESIZE_CLAIMS", "MODEL_TIMEOUT", True, self._question.id
            )
            return None
        # Provider 边界必须将任何未分类异常收敛为可审计的领域失败。
        except Exception:  # noqa: BLE001
            await self._record_failure(
                result, "SYNTHESIZE_CLAIMS", "MODEL_ERROR", False, self._question.id
            )
            return None
        await self._save_model_response("claim", 1, synthesis)
        return synthesis

    async def _verify_and_save_claims(
        self,
        synthesis: ClaimSynthesis,
        evidence: list[Evidence],
        result: PipelineResult,
    ) -> None:
        approved_ids = {item.id for item in evidence}
        by_id = {item.id: item for item in evidence}
        for index, candidate in enumerate(synthesis.claims):
            evidence_ids = [item_id for item_id in candidate.evidence_ids if item_id in approved_ids]
            if candidate.kind == "FACT" and not evidence_ids:
                await self._record_gap(
                    result,
                    "CLAIM_EVIDENCE_NOT_APPROVED",
                    "Fact 没有绑定已批准的 Evidence，未保存为可用事实。",
                )
                continue

            claim = Claim(
                id=f"claim-{index}",
                run_id=self._brief.run_id,
                kind=candidate.kind,
                text=candidate.text,
                evidence_ids=evidence_ids,
                upstream_claim_ids=candidate.upstream_claim_ids,
                status="REJECTED",
            )
            semantic: str | None = None
            if candidate.kind == "FACT":
                support = await self._verify_support(candidate, evidence, result)
                if support is None:
                    await self._repository.upsert_claim(
                        claim, f"{self._brief.run_id}:claim:{claim.id}"
                    )
                    await self._record_gap(
                        result, "SEMANTIC_VERIFICATION_FAILED", "Fact 的语义核验未完成。", [claim.id]
                    )
                    continue
                semantic = support.decision
                verification = Verification(
                    id=f"verification-{claim.id}",
                    run_id=self._brief.run_id,
                    claim_id=claim.id,
                    evidence_id=evidence_ids[0],
                    located=True,
                    numeric_ok=all(by_id[item_id].numeric_ok for item_id in evidence_ids),
                    semantic_decision=support.decision,
                    reason=support.reason,
                )
                await self._repository.upsert_verification(
                    verification, f"{self._brief.run_id}:verification:{claim.id}"
                )

            gate = decide_claim(
                kind=candidate.kind,
                located=bool(evidence_ids),
                numeric_ok=bool(evidence_ids) and all(by_id[item_id].numeric_ok for item_id in evidence_ids),
                semantic=semantic,
            )
            claim = claim.model_copy(update={"status": "APPROVED" if gate.approved else "REJECTED"})
            await self._repository.upsert_claim(claim, f"{self._brief.run_id}:claim:{claim.id}")
            if gate.approved:
                result.approved_claim_ids.append(claim.id)
            else:
                await self._record_gap(result, gate.reason, "Claim 未通过质量门禁。", [claim.id])

    async def _verify_support(
        self,
        candidate: ClaimCandidate,
        evidence: list[Evidence],
        result: PipelineResult,
    ) -> SupportVerification | None:
        try:
            support = await self.model.verify_support(candidate, evidence)
        except ProviderSchemaError:
            await self._record_failure(
                result, "VERIFY_SUPPORT", "MODEL_SCHEMA_ERROR", False, self._question.id
            )
            return None
        except TimeoutError:
            await self._record_failure(
                result, "VERIFY_SUPPORT", "MODEL_TIMEOUT", True, self._question.id
            )
            return None
        # Provider 边界必须将任何未分类异常收敛为可审计的领域失败。
        except Exception:  # noqa: BLE001
            await self._record_failure(
                result, "VERIFY_SUPPORT", "MODEL_ERROR", False, self._question.id
            )
            return None
        await self._save_model_response("verification", 1, support)
        return support

    async def _save_model_response(self, operation: str, attempt: int, response: BaseModel) -> None:
        """先脱敏再落盘，避免调试制品成为密钥泄露路径。"""
        content = self._redact_secrets(response.model_dump_json())
        reference = self._artifacts.write_text(
            self._brief.run_id,
            f"model_responses/{operation}-{attempt}.json",
            content,
            media_type="application/json; charset=utf-8",
        )
        await self._repository.upsert_artifact_ref(
            reference, f"{self._brief.run_id}:model-response:{operation}:{attempt}"
        )

    async def _record_failure(
        self,
        result: PipelineResult,
        operation: str,
        code: str,
        retryable: bool,
        related_entity_id: str,
    ) -> None:
        failure = Failure(
            id=f"failure-{operation.lower()}",
            run_id=self._brief.run_id,
            operation=operation,
            code=code,
            retryable=retryable,
            message="模型或正文块处理失败，未产生未经核验的事实。",
            related_entity_id=related_entity_id,
        )
        failure_id = await self._repository.upsert_failure(
            failure, f"{self._brief.run_id}:failure:{operation}:{code}"
        )
        result.failure_ids.append(failure_id)

    async def _record_gap(
        self,
        result: PipelineResult,
        code: str,
        description: str,
        related_claim_ids: list[str] | None = None,
    ) -> None:
        gap = Gap(
            id=f"gap-{self._question.id}-{self._gap_count}",
            run_id=self._brief.run_id,
            question_id=self._question.id,
            code=code,
            description=description,
            related_source_ids=[],
            related_claim_ids=related_claim_ids or [],
        )
        self._gap_count += 1
        gap_id = await self._repository.upsert_gap(gap, f"{self._brief.run_id}:gap:{gap.id}")
        result.gap_ids.append(gap_id)

    @staticmethod
    def _redact_secrets(content: str) -> str:
        """掩盖常见 JSON 密钥字段，保持响应其余部分可审计。"""
        return re.sub(
            r'(?i)("(?:api[_-]?key|authorization|token|password)"\s*:\s*")[^"]*',
            r"\1[REDACTED]",
            content,
        )
