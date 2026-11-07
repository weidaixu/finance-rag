"""用真实财报页面做回归测试，防止数字再被拆散。

期望值都来自 page.get_text() 的原文。data/raw/ 不在 Git 里，缺文件时跳过，
运行 scripts/download_reports.py 后就能跑。
"""

from pathlib import Path

import pymupdf
import pytest

from finrag.chunking import build_chunks
from finrag.parsing import Block, _page_blocks

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


def table_rows(doc_id: str, page_number: int) -> list[list[str]]:
    path = RAW / f"{doc_id}.pdf"
    if not path.exists():
        pytest.skip(f"缺少 {path.name}")
    with pymupdf.open(path) as document:
        blocks = _page_blocks(document[page_number - 1], page_number)
    return [row for block in blocks if block.kind == "table" for row in block.rows or []]


def row_with(rows: list[list[str]], label: str) -> list[str]:
    for row in rows:
        if any(label in cell for cell in row):
            return row
    raise AssertionError(f"没有找到 {label}，实际前几行：{rows[:5]}")


def test_moutai_numbers_stay_whole_in_grid_table():
    row = row_with(table_rows("moutai-2025-zh", 6), "营业收入")
    assert "168,838,102,514.79" in row and "170,899,152,276.34" in row and "-1.21" in row


def test_byd_merged_cells_keep_numbers_in_one_row():
    row = row_with(table_rows("byd-2025-zh", 11), "营业收入（元）")
    assert row[:3] == ["营业收入（元）", "803,964,958,000.00", "777,102,455,000.00"]


def test_catl_numbers_stay_whole():
    row = row_with(table_rows("catl-2025-zh", 11), "营业收入")
    assert "423,701,834" in row and "17.04%" in row


def test_cmb_table_without_rulings_is_rebuilt_row_by_row():
    row = row_with(table_rows("cmb-2025-zh", 14), "营业收入")
    assert row == ["营业收入", "337,532", "337,488", "0.01", "339,123"]


def test_english_cells_keep_their_spaces():
    rows = table_rows("moutai-2025-en", 11)
    assert row_with(rows, "Domestic")[1] == "163,924,442,864.97"
    assert row_with(rows, "Main business grouped by sales model")


def test_tesla_row_keeps_label_and_numbers_together():
    row = row_with(table_rows("tesla-2025-en", 53), "Total revenues")
    assert row == ["Total revenues", "94,827", "97,690", "96,773"]


def test_chapter_in_running_header_sets_section():
    report = {"doc_id": "d", "company": "c", "year": 2025, "language": "zh", "title": "t"}
    head = "招商银行股份有限公司  2025年度报告（A股）  13  第二章  会计数据和财务指标摘要"
    chunks = build_chunks([Block("text", 14, 0, text=head + "\n" + "正文内容。" * 10)], report)
    assert chunks[0].section == "第二章 会计数据和财务指标摘要"


def test_section_drops_page_number_from_running_header():
    report = {"doc_id": "d", "company": "c", "year": 2025, "language": "zh", "title": "t"}
    head = "第二章 会计数据和财务指标摘要  13"
    chunks = build_chunks([Block("text", 14, 0, text=head + "\n" + "正文内容。" * 10)], report)
    assert chunks[0].section == "第二章 会计数据和财务指标摘要"


def test_short_table_caption_is_not_also_a_separate_chunk():
    report = {"doc_id": "d", "company": "c", "year": 2025, "language": "zh", "title": "t"}
    blocks = [Block("text", 3, 0, text="单位：元"), Block("table", 3, 1, rows=[["项目", "金额"], ["甲", "1"]])]
    chunks = build_chunks(blocks, report)
    assert [chunk.kind for chunk in chunks] == ["table"] and "单位：元" in chunks[0].text
