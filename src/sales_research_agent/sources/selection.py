"""按问题保底和来源等级稳定选择候选来源。"""

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from sales_research_agent.domain.models import SourceAuthority


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    url: str
    authority: SourceAuthority
    score: float | None = None
    title: str = ""
    question_ids: tuple[str, ...] = ()


def select_sources(
    candidates_by_question: dict[str, list[SourceCandidate]], max_sources: int
) -> list[SourceCandidate]:
    """先为每个问题保留一个 URL，再按等级和相关度补齐全局上限。"""
    if max_sources <= 0:
        return []
    selected: dict[str, SourceCandidate] = {}
    order: list[str] = []
    for question_id, candidates in candidates_by_question.items():
        for candidate in candidates:
            key = _canonical_url(candidate.url)
            if key in selected:
                selected[key] = _merge(selected[key], candidate, question_id)
                continue
            selected[key] = _with_question(candidate, question_id)
            order.append(key)
            break
    remaining = []
    for candidates in candidates_by_question.values():
        for candidate in candidates:
            key = _canonical_url(candidate.url)
            if key not in selected:
                selected[key] = candidate
                remaining.append(key)
    rank = {"OFFICIAL_PRIMARY": 0, "TRUSTED_SECONDARY": 1, "UNCLASSIFIED": 2}
    remaining.sort(key=lambda key: (rank[selected[key].authority], -(selected[key].score or 0.0), order.index(key) if key in order else len(order) + remaining.index(key)))
    keys = order + remaining
    return [selected[key] for key in keys[:max_sources]]


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def _with_question(candidate: SourceCandidate, question_id: str) -> SourceCandidate:
    return SourceCandidate(candidate.url, candidate.authority, candidate.score, candidate.title, (question_id,))


def _merge(left: SourceCandidate, right: SourceCandidate, question_id: str) -> SourceCandidate:
    questions = tuple(dict.fromkeys((*left.question_ids, *right.question_ids, question_id)))
    return SourceCandidate(left.url, left.authority, max(left.score or 0.0, right.score or 0.0), left.title or right.title, questions)
