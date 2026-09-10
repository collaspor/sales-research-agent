"""在来源原文中确定性定位模型返回的引用。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuoteMatch:
    """引用在原文中的半开区间及定位方式。"""

    start: int
    end: int
    method: str


_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "！": "!",
        "？": "?",
        "：": ":",
        "；": ";",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "［": "[",
        "］": "]",
        "｛": "{",
        "｝": "}",
        "、": ",",
        "％": "%",
        "＃": "#",
        "＆": "&",
        "＋": "+",
        "－": "-",
        "＝": "=",
        "／": "/",
    }
)


def _normalise(text: str) -> str:
    """删除 Unicode 空白并统一常见全角标点。"""
    return "".join(
        char.translate(_PUNCTUATION_TRANSLATION)
        for char in text
        if not char.isspace()
    )


def _normalise_with_mapping(text: str) -> tuple[str, list[int]]:
    normalised: list[str] = []
    mapping: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        normalised.append(char.translate(_PUNCTUATION_TRANSLATION))
        mapping.append(index)
    return "".join(normalised), mapping


def locate_quote(text: str, quote: str) -> QuoteMatch | None:
    """先 exact、后规范化定位引用，不执行模糊匹配。"""
    if not quote:
        return None

    exact_start = text.find(quote)
    if exact_start >= 0:
        return QuoteMatch(exact_start, exact_start + len(quote), "EXACT")

    normalised_quote = _normalise(quote)
    if not normalised_quote:
        return None

    normalised_text, mapping = _normalise_with_mapping(text)
    normalised_start = normalised_text.find(normalised_quote)
    if normalised_start < 0:
        return None

    normalised_end = normalised_start + len(normalised_quote)
    original_start = mapping[normalised_start]
    original_end = mapping[normalised_end - 1] + 1
    return QuoteMatch(original_start, original_end, "NORMALIZED")
