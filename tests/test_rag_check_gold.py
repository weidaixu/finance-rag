"""评测题校验脚本的测试。校验脚本是评测题的验收标准，它本身必须可靠。"""

import pymupdf
import pytest

from eval.check_gold import check_format, check_quotes, squeeze


@pytest.fixture
def documents():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Total revenues 97,690")
    return {"doc": document}


def answerable(**overrides):
    item = {
        "id": "q1",
        "question": "What were total revenues?",
        "type": "english",
        "should_refuse": False,
        "answer_contains": ["97,690"],
        "gold": [{"doc_id": "doc", "page": 1, "quote": "Total revenues"}],
    }
    return {**item, **overrides}


def test_valid_answerable_question_passes(documents):
    item = answerable()
    assert check_format(item, {"doc"}) == []
    assert check_quotes(item, documents) == []


def test_valid_refusal_question_passes():
    item = {"id": "q2", "question": "腾讯收入", "type": "company_not_covered", "should_refuse": True, "gold": []}
    assert check_format(item, {"doc"}) == []


def test_quote_not_on_page_is_rejected(documents):
    item = answerable(gold=[{"doc_id": "doc", "page": 1, "quote": "Net income"}])
    assert any("引文不在" in error for error in check_quotes(item, documents))


def test_invented_answer_is_rejected_even_when_quote_is_real(documents):
    item = answerable(answer_contains=["88,888"])
    assert any("answer_contains" in error for error in check_quotes(item, documents))


def test_page_out_of_range_is_rejected_without_crashing(documents):
    item = answerable(gold=[{"doc_id": "doc", "page": 99, "quote": "x"}])
    assert any("超出范围" in error for error in check_quotes(item, documents))


def test_unknown_doc_and_bad_type_are_rejected():
    item = answerable(type="other", gold=[{"doc_id": "nope", "page": 1, "quote": "x"}])
    errors = check_format(item, {"doc"})
    assert any("type" in error for error in errors) and any("doc_id" in error for error in errors)


def test_refusal_question_with_gold_is_rejected():
    item = {"id": "q", "question": "x", "type": "investment_advice", "should_refuse": True, "gold": [{"doc_id": "doc"}]}
    assert any("不应该有 gold" in error for error in check_format(item, {"doc"}))


def test_squeeze_ignores_whitespace_and_traditional_chinese():
    assert squeeze("招商銀行 營業\n收入") == "招商银行营业收入"
