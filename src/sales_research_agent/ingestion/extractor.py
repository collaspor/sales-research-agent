"""将原始 HTML 转换为可追溯的纯文本正文。"""

from dataclasses import dataclass

import trafilatura


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """正文提取的成功或失败结果。"""

    text: str | None = None
    failure_code: str | None = None


class HtmlExtractor:
    """固定使用 Trafilatura 的纯文本抽取配置。"""

    def extract(self, raw_html: bytes, final_url: str) -> ExtractionResult:
        """抽取正文；空白结果按可处理的结构化失败返回。"""
        try:
            text = trafilatura.extract(
                raw_html,
                url=final_url,
                output_format="txt",
                include_comments=False,
                include_tables=True,
            )
        except (TypeError, ValueError):
            return ExtractionResult(failure_code="EXTRACTION_FAILED")
        if not text or not text.strip():
            return ExtractionResult(failure_code="EMPTY_CONTENT")
        return ExtractionResult(text=text.strip())
