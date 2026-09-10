"""外部事实的最小质量门禁。"""

from dataclasses import dataclass
from typing import Literal

ClaimKind = Literal["FACT", "INFERENCE", "QUESTION"]


@dataclass(frozen=True, slots=True)
class GateResult:
    """门禁是否允许该 Claim 进入外部事实输出。"""

    approved: bool
    reason: str


def decide_claim(
    *,
    kind: ClaimKind,
    located: bool,
    numeric_ok: bool,
    semantic: str | None,
) -> GateResult:
    """按定位、数字、语义的固定顺序判定外部事实。"""
    if kind != "FACT":
        return GateResult(approved=False, reason="NON_FACT_CLAIM")
    if not located:
        return GateResult(approved=False, reason="EVIDENCE_NOT_LOCATED")
    if not numeric_ok:
        return GateResult(approved=False, reason="NUMERIC_MISMATCH")
    if semantic != "SUPPORTED":
        return GateResult(approved=False, reason="SEMANTIC_NOT_SUPPORTED")
    return GateResult(approved=True, reason="APPROVED")
