"""把解析结果切成检索用的片段。

三条规则都来自财报的特点：
1. 表格按行切，每段都带表头，否则数字看不出属于哪一列。
2. 表格带上方的说明文字，因为「单位：万元」这类信息通常在表格外面。
3. 每段记录所在章节，「营业收入」在摘要和附注里出现很多次，章节能帮助区分。
"""

import re
from dataclasses import asdict, dataclass

from finrag.parsing import Block

MAX_TEXT_CHARS = 900
TEXT_OVERLAP = 120
MAX_TABLE_CHARS = 1400
TABLE_TITLE_LINES = 2

_SECTION = re.compile(
    r"^(第[一二三四五六七八九十]+[节章](\s*\S.*)?"
    r"|[一二三四五六七八九十]+、\s*\S.{0,28}"
    r"|item\s+\d+[a-z]?\.\s*\S.*"
    r"|part\s+[ivx]+\b.*"
    r"|section\s+[ivx]+\b.*)$",
    re.IGNORECASE,
)
_SEGMENTS = re.compile(r"\s{2,}")


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    company: str
    year: int
    language: str
    title: str
    page: int
    section: str
    kind: str
    text: str

    @property
    def indexed_text(self) -> str:
        """真正进入检索的文字：把公司、年份和章节也算进去。"""
        return f"{self.company} {self.year} {self.section}\n{self.text}"

    def to_dict(self) -> dict:
        return asdict(self)


def split_text(text: str, max_chars: int = MAX_TEXT_CHARS, overlap: int = TEXT_OVERLAP) -> list[str]:
    """按字符切分，尽量停在句末。overlap 让跨边界的句子在两段里都完整出现一次。"""
    if max_chars <= overlap:
        raise ValueError("max_chars 必须大于 overlap")
    text = text.strip()
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind(mark) for mark in ("。", "；", ". ", "\n"))
            if cut > max_chars // 2:
                end = start + cut + 1
        pieces.append(text[start:end].strip())
        if end == len(text):
            break
        start = end - overlap
    return [piece for piece in pieces if piece]


def render_row(row: list[str]) -> str:
    return "| " + " | ".join(row) + " |"


def split_table(rows: list[list[str]], title: str = "", max_chars: int = MAX_TABLE_CHARS) -> list[str]:
    """按行切表格，每段都重复说明文字和表头。"""
    header = render_row(rows[0])
    prefix = f"{title}\n{header}" if title else header
    pieces: list[str] = []
    current: list[str] = []
    size = len(prefix)
    for row in rows[1:]:
        line = render_row(row)
        if current and size + len(line) > max_chars:
            pieces.append(prefix + "\n" + "\n".join(current))
            current, size = [], len(prefix)
        current.append(line)
        size += len(line) + 1
    pieces.append(prefix + ("\n" + "\n".join(current) if current else ""))
    return pieces


def _update_section(text: str, section: str) -> str:
    """章名可能和页眉在同一行，所以同一行里按两个以上的空格分段后再逐段判断。"""
    for line in text.split("\n"):
        segments = _SEGMENTS.split(line.strip())
        for index, segment in enumerate(segments):
            if _SECTION.match(segment):
                # 「第二章  会计数据」这样的章名本身可能被分成两段，要接回去。
                section = re.sub(r"\s+\d+$", "", " ".join(segments[index:]))[:50]  # 去掉页眉带上的页码
                break
    return section


def build_chunks(blocks: list[Block], report: dict) -> list[Chunk]:
    """report 是 manifest 里的一条记录。"""
    chunks: list[Chunk] = []
    section = ""
    previous_table: Block | None = None
    previous_text_lines: list[str] = []
    buffer: list[str] = []
    buffer_page = 0

    def add(page: int, kind: str, text: str) -> None:
        chunks.append(
            Chunk(
                chunk_id=f"{report['doc_id']}#{len(chunks)}",
                doc_id=report["doc_id"],
                company=report["company"],
                year=report["year"],
                language=report["language"],
                title=report["title"],
                page=page,
                section=section,
                kind=kind,
                text=text,
            )
        )

    def flush(before_table: bool = False) -> None:
        """before_table 为真时，只有表格说明的短文字已经进了表格片段，不再单独成段。"""
        nonlocal buffer
        joined = "\n".join(buffer)
        if buffer and not (before_table and len(joined.split("\n")) <= TABLE_TITLE_LINES):
            for piece in split_text(joined):
                add(buffer_page, "text", piece)
        buffer = []

    for block in blocks:
        if block.kind == "text":
            # 文字块只合并同一页的内容，保证引用的页码是准确的。
            if buffer and block.page != buffer_page:
                flush()
            if not buffer:
                buffer_page = block.page
            new_section = _update_section(block.text, section)
            if new_section != section:
                flush()
                buffer_page = block.page
                section = new_section
            buffer.append(block.text)
            previous_text_lines = block.text.split("\n")[-TABLE_TITLE_LINES:]
            previous_table = None
            continue

        flush(before_table=True)
        rows = block.rows or []
        # 跨页的表格在下一页通常没有表头：列数相同且紧接着上一页的表格时，沿用上一页的表头。
        is_continuation = (
            previous_table is not None
            and block.page == previous_table.page + 1
            and previous_table.rows
            and (previous_table.columns or len(previous_table.rows[0]))
            == (block.columns or len(rows[0]))
        )
        if is_continuation:
            rows = [previous_table.rows[0], *rows]
        title = "\n".join(previous_text_lines) if not is_continuation else ""
        for piece in split_table(rows, title):
            add(block.page, "table", piece)
        previous_table = block
        if is_continuation:
            # 保留原始表头，这样连续三页以上的表格也能接上。
            block.rows = rows
    flush()
    return chunks
