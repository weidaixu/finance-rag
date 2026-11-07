"""切分和文字处理的测试：用构造的小数据，不依赖 PDF。"""

import pytest

from finrag.chunking import build_chunks, split_table, split_text
from finrag.parsing import Block
from finrag.text import normalize, tokenize

REPORT = {
    "doc_id": "doc",
    "company": "测试公司",
    "year": 2025,
    "language": "zh",
    "title": "测试公司2025年年度报告",
}


def table(page, rows):
    return Block("table", page, 100, rows=rows)


def text(page, content):
    return Block("text", page, 50, text=content)


def test_split_text_keeps_short_text_whole():
    assert split_text("短文本。") == ["短文本。"]


def test_split_text_respects_limit_and_overlap():
    source = "".join(f"第{i}句话内容。" for i in range(200))
    pieces = split_text(source, max_chars=100, overlap=20)
    assert len(pieces) > 1
    assert all(len(piece) <= 100 for piece in pieces)
    assert pieces[1][:5] in pieces[0]


def test_split_text_has_no_gap():
    source = "abcdefghij" * 50
    pieces = split_text(source, max_chars=60, overlap=10)
    rebuilt = pieces[0]
    for piece in pieces[1:]:
        rebuilt += piece[10:]
    assert rebuilt == source


def test_split_text_rejects_overlap_not_smaller_than_limit():
    with pytest.raises(ValueError):
        split_text("abc", max_chars=10, overlap=10)


def test_split_text_empty_input():
    assert split_text("   ") == []


def test_split_table_repeats_title_and_header_in_every_piece():
    rows = [["项目", "金额"]] + [[f"科目{i}", str(i)] for i in range(100)]
    pieces = split_table(rows, title="单位：元", max_chars=200)
    assert len(pieces) > 1
    assert all(piece.startswith("单位：元\n| 项目 | 金额 |") for piece in pieces)
    assert sum(piece.count("科目") for piece in pieces) == 100


def test_split_table_with_header_only():
    assert split_table([["项目", "金额"]]) == ["| 项目 | 金额 |"]


def test_table_uses_preceding_text_as_title_so_unit_is_kept():
    blocks = [text(3, "主要会计数据\n单位：元 币种：人民币"), table(3, [["项目", "金额"], ["营业收入", "100"]])]
    table_chunk = [c for c in build_chunks(blocks, REPORT) if c.kind == "table"][0]
    assert "单位：元 币种：人民币" in table_chunk.text
    assert table_chunk.page == 3


def test_continued_table_on_next_page_gets_header_and_own_page():
    blocks = [table(3, [["项目", "金额"], ["甲", "1"]]), table(4, [["乙", "2"]])]
    chunks = build_chunks(blocks, REPORT)
    assert chunks[1].page == 4
    assert "| 项目 | 金额 |" in chunks[1].text and "| 乙 | 2 |" in chunks[1].text


def test_table_after_text_is_not_treated_as_continuation():
    blocks = [table(3, [["项目", "金额"], ["甲", "1"]]), text(4, "新的说明"), table(4, [["名称", "数量"], ["丙", "3"]])]
    assert "项目" not in build_chunks(blocks, REPORT)[-1].text


def test_table_with_different_column_count_is_not_continuation():
    blocks = [table(3, [["项目", "金额"], ["甲", "1"]]), table(4, [["名称", "数量", "备注"], ["丙", "3", "无"]])]
    assert "项目" not in build_chunks(blocks, REPORT)[-1].text


def test_text_chunks_keep_their_own_page_number():
    chunks = build_chunks([text(3, "第三页内容"), text(4, "第四页内容")], REPORT)
    assert [(c.page, c.text) for c in chunks] == [(3, "第三页内容"), (4, "第四页内容")]


def test_section_is_recorded_and_used_in_indexed_text():
    chunks = build_chunks([text(1, "第三节 管理层讨论与分析\n本期经营情况")], REPORT)
    assert chunks[0].section == "第三节 管理层讨论与分析"
    assert "第三节" in chunks[0].indexed_text and "测试公司" in chunks[0].indexed_text


def test_chunk_ids_are_unique():
    blocks = [text(1, "甲"), table(1, [["项目", "金额"], ["乙", "1"]]), text(2, "丙")]
    ids = [c.chunk_id for c in build_chunks(blocks, REPORT)]
    assert len(ids) == len(set(ids))


def test_traditional_chinese_matches_simplified_question():
    assert normalize("招商銀行營業收入") == "招商银行营业收入"
    assert set(tokenize("招商银行营业收入")) == set(tokenize("招商銀行營業收入"))


def test_tokenize_removes_thousands_separator_and_stopwords():
    tokens = tokenize("The total revenues were 97,690")
    assert "97690" in tokens and "the" not in tokens and "revenues" in tokens
