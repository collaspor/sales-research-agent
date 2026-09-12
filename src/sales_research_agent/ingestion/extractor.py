"""将原始 HTML 转换为可追溯的纯文本正文。"""

import codecs
import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser

import trafilatura

from sales_research_agent.ingestion.text_quality import is_readable


class PageMetadata(HTMLParser):
    """只读取明确的发布时间字段，不把正文中的事件日期当作发布日期。"""

    def __init__(self) -> None:
        super().__init__()
        self.dates: set[date] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        key = values.get("property") or values.get("name") or values.get("itemprop")
        if tag == "meta" and key in {
            "article:published_time", "datePublished", "pubdate", "publishdate",
        }:
            value = values.get("content") or ""
            try:
                self.dates.add(date.fromisoformat(value[:10]))
            except ValueError:
                return


def decode_html(raw: bytes) -> tuple[str, str]:
    """优先 BOM 和有效 UTF-8；旧编码仅接受可严格往返的声明。"""
    for bom, encoding in ((codecs.BOM_UTF8, "utf-8-sig"),
                          (codecs.BOM_UTF16_LE, "utf-16"),
                          (codecs.BOM_UTF16_BE, "utf-16")):
        if raw.startswith(bom):
            return raw.decode(encoding), encoding
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    labels = re.findall(rb"charset\s*=\s*[\"']?([a-zA-Z0-9_-]+)", raw[:16384])
    for label in labels:
        encoding = label.decode("ascii").lower()
        if encoding in {"gbk", "gb2312", "gb18030", "big5", "windows-1252", "iso-8859-1"}:
            try:
                return raw.decode("gb18030" if encoding.startswith("gb") else encoding), encoding
            except UnicodeDecodeError:
                continue
    raise ValueError("HTML encoding is not reliably determined")


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """正文提取的成功或失败结果。"""

    text: str | None = None
    failure_code: str | None = None
    encoding: str | None = None
    published_on: date | None = None


class HtmlExtractor:
    """固定使用 Trafilatura 的纯文本抽取配置。"""

    def extract(self, raw_html: bytes, final_url: str) -> ExtractionResult:
        """抽取正文；空白结果按可处理的结构化失败返回。"""
        try:
            decoded, encoding = decode_html(raw_html)
        except (ValueError, UnicodeError):
            return ExtractionResult(failure_code="TEXT_ENCODING_UNCERTAIN")
        try:
            text = trafilatura.extract(
                decoded,
                url=final_url,
                output_format="txt",
                include_comments=False,
                include_tables=True,
            )
        except (TypeError, ValueError):
            return ExtractionResult(failure_code="EXTRACTION_FAILED")
        if not text or not text.strip():
            return ExtractionResult(failure_code="EMPTY_CONTENT")
        if not is_readable(text):
            return ExtractionResult(failure_code="TEXT_UNREADABLE")
        metadata = PageMetadata()
        metadata.feed(decoded)
        published_on = next(iter(metadata.dates)) if len(metadata.dates) == 1 else None
        return ExtractionResult(text=text.strip(), encoding=encoding, published_on=published_on)
