"""对公开来源执行确定性的归属和内容类型分类。"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from sales_research_agent.domain.models import ContentKind, SourceAuthority


@dataclass(frozen=True, slots=True)
class SourceAuthorityPolicy:
    """仅依据显式域名集合分类，不让模型猜测来源等级。"""

    official_hosts: frozenset[str] = frozenset()
    trusted_secondary_hosts: frozenset[str] = frozenset()

    def classify(self, url: str) -> SourceAuthority:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        if _matches_host(host, self.official_hosts):
            return "OFFICIAL_PRIMARY"
        if _matches_host(host, self.trusted_secondary_hosts):
            return "TRUSTED_SECONDARY"
        return "UNCLASSIFIED"

    def content_kind(self, url: str, media_type: str | None = None) -> ContentKind:
        normalized = (media_type or "").split(";", 1)[0].strip().lower()
        if normalized == "application/pdf":
            return "PDF"
        if normalized in {"text/html", "application/xhtml+xml"}:
            return "HTML"
        suffix = (urlsplit(url).path.rsplit(".", 1)[-1] if "." in urlsplit(url).path else "").lower()
        if suffix == "pdf":
            return "PDF"
        if suffix in {"html", "htm", "xhtml"}:
            return "HTML"
        return "UNKNOWN"


def _matches_host(host: str, allowed: frozenset[str]) -> bool:
    return any(host == candidate or host.endswith("." + candidate) for candidate in allowed)
