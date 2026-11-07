"""把 PDF 解析成带页码的段落和表格。

为什么不直接用 page.get_text()：财报表格按单元格输出时，科目名和数字会被拆到不同行，
模型和检索都无法知道数字属于哪一行。这里按坐标还原行，并把有框线的表格单独取出。
"""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from finrag.text import normalize

COLUMN_GAP = 8  # 同一行两个词的横向间距超过它，就当作不同的列
LINE_TOLERANCE = 3  # 纵向中心差小于它的词算同一行
PARAGRAPH_GAP_RATIO = 1.7  # 行距超过中位行高的倍数时，算新段落
REPEATED_LINE_RATIO = 0.3  # 在超过这个比例的页面上重复出现的行，当作页眉页脚

_PAGE_NUMBER = re.compile(r"^(第?\s*\d+\s*(页|/\s*\d+)?|\d+\s*/\s*\d+)$")
_CJK = r"一-鿿"
# 章名有时和页眉排在同一行（如招商银行每页顶部），这种行不能当页眉删掉，章节要靠它识别。
_CHAPTER = re.compile(r"(^|\s{2})第[一二三四五六七八九十]+[节章]\s*\S")


@dataclass
class Block:
    kind: str  # "text" 或 "table"
    page: int  # 从 1 开始，和 PDF 阅读器显示的页码一致
    y: float
    text: str = ""
    rows: list[list[str]] | None = None
    columns: int = 0  # 原始表格的列数，用来判断跨页表格是否接得上


def _join_words(words: list[tuple]) -> str:
    """按横向间距把同一行的词拼起来，表格的列之间用两个空格分隔。"""
    parts: list[str] = []
    previous_x1 = None
    previous_word = ""
    for word in sorted(words, key=lambda item: item[0]):
        x0, x1, content = word[0], word[2], word[4]
        if previous_x1 is not None:
            gap = x0 - previous_x1
            both_cjk = re.search(f"[{_CJK}]$", previous_word) and re.match(f"[{_CJK}]", content)
            if gap > COLUMN_GAP:
                parts.append("  ")
            elif not both_cjk:
                parts.append(" ")
        parts.append(content)
        previous_x1, previous_word = x1, content
    return "".join(parts).strip()


def _lines_from_words(words: list[tuple]) -> list[tuple[float, float, str]]:
    """把词按纵坐标聚成行，返回 (y0, y1, 文本)。"""
    lines: list[list[tuple]] = []
    for word in sorted(words, key=lambda item: (item[1] + item[3]) / 2):
        center = (word[1] + word[3]) / 2
        if lines:
            last_center = sum((w[1] + w[3]) / 2 for w in lines[-1]) / len(lines[-1])
            if abs(center - last_center) <= LINE_TOLERANCE:
                lines[-1].append(word)
                continue
        lines.append([word])
    return [
        (min(w[1] for w in line), max(w[3] for w in line), _join_words(line))
        for line in lines
    ]


def _inside_any(word: tuple, boxes: list[tuple]) -> bool:
    center_x, center_y = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
    return any(x0 <= center_x <= x1 and y0 <= center_y <= y1 for x0, y0, x1, y1 in boxes)


def _join_lines(lines: list[str]) -> str:
    """把单元格里折行的文字接回去：中文之间不加空格，其他情况加一个空格。"""
    result = ""
    for line in lines:
        line = " ".join(line.split())
        if result and not (re.search(f"[{_CJK}]$", result) and re.match(f"[{_CJK}]", line)):
            result += " "
        result += line
    return result


def _tidy_rows(rows: list[list[str | None]]) -> list[list[str]]:
    """去掉版式造成的空单元格。

    有合并单元格（None）的表格，表头和数据的列本来就对不齐，只能每行去掉空格子；
    这样真正为空的单元格会让后面的列左移，是已知的局限。
    规整的表格只删除整列都为空的列，保留真正为空的单元格。
    """
    if any(cell is None for row in rows for cell in row):
        tidied = [[cell for cell in row if cell and cell != "$"] for row in rows]
    else:
        keep = [i for i in range(len(rows[0])) if any(row[i] for row in rows)]
        tidied = [[row[i] for i in keep] for row in rows]
    return [row for row in tidied if any(row)]


def _rows_from_lines(words: list[tuple]) -> list[list[str]]:
    """不信任表格的格子，按行还原。列之间在 _join_words 里已经用两个空格隔开。"""
    return [re.split(r"\s{2,}", line) for _, _, line in _lines_from_words(words) if line]


def _table_rows(table, page_words: list[tuple]) -> list[list[str]]:
    """按单元格的坐标取词，不用 table.extract()。

    table.extract() 会把逗号和小数点排到另一行，168,838,102,514.79 会变成
    「168 838 102 514 79」和「, , , .」两行，而 get_text("words") 得到的是完整数字。

    没有横线的表格（如招商银行）会被识别成一个格子里塞多行数字。
    一个格子里有两行以上带数字时，就改用按行还原。
    """
    words = [w for w in page_words if _inside_any(w, [tuple(table.bbox)])]
    raw_rows: list[list[str | None]] = []
    for row in table.rows:
        cells: list[str | None] = []
        for box in row.cells:
            if box is None:
                cells.append(None)
                continue
            lines = [
                line
                for _, _, line in _lines_from_words([w for w in words if _inside_any(w, [tuple(box)])])
            ]
            if sum(bool(re.search(r"\d", line)) for line in lines) >= 2:
                return _rows_from_lines(words)
            cells.append(_join_lines(lines))
        raw_rows.append(cells)
    return _tidy_rows(raw_rows)


def _page_blocks(page: pymupdf.Page, page_number: int) -> list[Block]:
    table_blocks: list[Block] = []
    table_boxes: list[tuple] = []
    page_words = page.get_text("words")
    for table in page.find_tables().tables:
        rows = _table_rows(table, page_words)
        # 只有一行或一列的多半是带边框的文字，不当作表格，文字留给下面的逐行提取。
        if len(rows) < 2 or table.col_count < 2:
            continue
        table_boxes.append(tuple(table.bbox))
        table_blocks.append(Block("table", page_number, table.bbox[1], rows=rows, columns=table.col_count))

    words = [w for w in page_words if not _inside_any(w, table_boxes)]
    lines = _lines_from_words(words)
    text_blocks: list[Block] = []
    if lines:
        heights = sorted(y1 - y0 for y0, y1, _ in lines)
        median = heights[len(heights) // 2] or 1
        current: list[str] = []
        start_y = lines[0][0]
        previous_y0 = None
        for y0, _, content in lines:
            if previous_y0 is not None and y0 - previous_y0 > median * PARAGRAPH_GAP_RATIO:
                text_blocks.append(Block("text", page_number, start_y, text="\n".join(current)))
                current, start_y = [], y0
            current.append(content)
            previous_y0 = y0
        text_blocks.append(Block("text", page_number, start_y, text="\n".join(current)))

    return sorted(table_blocks + text_blocks, key=lambda block: block.y)


def _repeated_lines(pages: list[list[Block]]) -> set[str]:
    """找出页眉页脚。比较时去掉数字，这样「第 3 页」和「第 4 页」算同一行。"""
    counts: Counter[str] = Counter()
    for blocks in pages:
        seen = {
            re.sub(r"\d+", "#", line.strip())
            for block in blocks
            if block.kind == "text"
            for line in block.text.split("\n")
        }
        counts.update(seen)
    threshold = max(3, len(pages) * REPEATED_LINE_RATIO)
    return {line for line, count in counts.items() if count >= threshold and line}


def _strip_furniture(block: Block, repeated: set[str]) -> None:
    kept = [
        line
        for line in block.text.split("\n")
        if _CHAPTER.search(line)
        or (
            re.sub(r"\d+", "#", line.strip()) not in repeated
            and not _PAGE_NUMBER.match(line.strip())
        )
    ]
    block.text = "\n".join(kept).strip()


def parse_pdf(path: Path) -> list[Block]:
    """返回整份 PDF 的段落和表格，文字已去掉页眉页脚并统一成简体。"""
    with pymupdf.open(path) as document:
        pages = [_page_blocks(page, index + 1) for index, page in enumerate(document)]

    repeated = _repeated_lines(pages)
    blocks: list[Block] = []
    for page_blocks in pages:
        for block in page_blocks:
            if block.kind == "table":
                block.rows = [[normalize(cell) for cell in row] for row in block.rows or []]
                blocks.append(block)
                continue
            _strip_furniture(block, repeated)
            if block.text:
                block.text = normalize(block.text)
                blocks.append(block)
    return blocks
