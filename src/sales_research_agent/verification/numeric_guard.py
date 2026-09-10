"""保护引用中的关键数字、日期、金额和百分比。"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NumericGuardResult:
    """关键 token 比对结果。"""

    ok: bool
    reason: str
    source_tokens: tuple[str, ...]
    quote_tokens: tuple[str, ...]


_NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_CRITICAL_TOKEN_RE = re.compile(
    rf"""
    (?P<date>
        \d{{4}}\s*年\s*\d{{1,2}}\s*月(?:\s*\d{{1,2}}\s*日)?
        |\d{{4}}\s*[-/.]\s*\d{{1,2}}\s*[-/.]\s*\d{{1,2}}
    )
    |(?P<percentage>百分之\s*{_NUMBER}|{_NUMBER}\s*[%％])
    |(?P<amount>(?:[$€£¥￥]\s*{_NUMBER}|{_NUMBER}\s*(?:元|万元|亿元|美元|人民币|万美元|亿美元)))
    |(?P<unit>{_NUMBER}\s*(?:万|亿|人|家|件|个|次|名|项|台|吨|公里|平方米))
    |(?P<year>\d{{4}}(?!\d))
    |(?P<number>{_NUMBER})
    """,
    re.VERBOSE,
)


def _normalise_token(token: str) -> str:
    return "".join(unicodedata.normalize("NFKC", token).split())


def _extract_tokens(text: str) -> tuple[str, ...]:
    return tuple(_normalise_token(match.group(0)) for match in _CRITICAL_TOKEN_RE.finditer(text))


def compare_critical_tokens(source: str, quote: str) -> NumericGuardResult:
    """要求引用与对应来源文本的关键 token multiset 完全相等。"""
    source_tokens = _extract_tokens(source)
    quote_tokens = _extract_tokens(quote)
    ok = Counter(source_tokens) == Counter(quote_tokens)
    return NumericGuardResult(
        ok=ok,
        reason="OK" if ok else "NUMERIC_MISMATCH",
        source_tokens=source_tokens,
        quote_tokens=quote_tokens,
    )
