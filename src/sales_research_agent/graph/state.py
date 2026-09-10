from typing import Annotated, NotRequired, TypedDict


def merge_unique(current: list[str], update: list[str]) -> list[str]:
    """按首次出现顺序合并字符串 ID，避免重复。"""
    return list(dict.fromkeys([*current, *update]))


class PocState(TypedDict):
    run_id: str
    thread_id: str
    brief_id: str
    research_question_ids: Annotated[list[str], merge_unique]
    source_ids: Annotated[list[str], merge_unique]
    successful_source_ids: Annotated[list[str], merge_unique]
    failed_source_ids: Annotated[list[str], merge_unique]
    evidence_ids: Annotated[list[str], merge_unique]
    claim_ids: Annotated[list[str], merge_unique]
    approved_claim_ids: Annotated[list[str], merge_unique]
    rejected_claim_ids: Annotated[list[str], merge_unique]
    gap_ids: Annotated[list[str], merge_unique]
    failure_ids: Annotated[list[str], merge_unique]
    report_version_id: NotRequired[str | None]
    execution_status: str
    report_outcome: str
    started_at: str
    deadline_at: str
    current_source_id: NotRequired[str]
