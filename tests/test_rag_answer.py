"""问答模块的测试：用假的检索器和模型，不联网，不产生费用。"""

from types import SimpleNamespace

import pytest

from finrag.answer import SYSTEM_PROMPT, AnswerResult, find_unverified_numbers, precheck, review, stream_answer
from finrag.chunking import Chunk
from finrag.contracts import Hit
from finrag.llm import Usage


def make_hit(text: str, page: int = 5) -> Hit:
    chunk = Chunk(
        chunk_id=f"doc#{page}",
        doc_id="doc",
        company="测试公司",
        year=2025,
        language="zh",
        title="测试公司2025年年度报告",
        page=page,
        section="第三节",
        kind="table",
        text=text,
    )
    return Hit(chunk=chunk, score=1.0)


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.calls = 0

    def retrieve(self, question, k=8):
        self.calls += 1
        return self.hits


class FakeClient:
    """按预设内容模拟流式回复，并记录是否被调用。"""

    def __init__(self, pieces=(), error=None, usage=(12, 34)):
        self.pieces, self.error, self.usage, self.calls = pieces, error, usage, 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self._stream()

    def _stream(self):
        for piece in self.pieces:
            delta = SimpleNamespace(content=piece)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)
        usage = SimpleNamespace(prompt_tokens=self.usage[0], completion_tokens=self.usage[1])
        yield SimpleNamespace(choices=[], usage=usage)


def run(question, retriever, client):
    items = list(stream_answer(question, retriever, client, "fake-model", max_year=2025))
    return [item for item in items if isinstance(item, str)], items[-1]


@pytest.mark.parametrize(
    "question",
    ["我现在该买茅台吗", "是否应该买入比亚迪", "特斯拉股价会涨吗", "Should I buy Tesla stock?", "给点投资建议"],
)
def test_investment_questions_are_refused(question):
    assert precheck(question, 2025) == "investment_advice"


@pytest.mark.parametrize(
    "question",
    ["招商银行买入返售金融资产余额是多少", "比亚迪是否投资了新的工厂", "Tesla 2025 total revenues", "茅台的持有至到期投资"],
)
def test_normal_questions_pass_precheck(question):
    assert precheck(question, 2025) is None


def test_year_after_coverage_is_refused_but_earlier_year_passes():
    assert precheck("茅台2026年营业收入", 2025) == "year_not_covered"
    assert precheck("茅台2024年营业收入", 2025) is None


def test_precheck_refusal_calls_neither_retriever_nor_model():
    retriever, client = FakeRetriever([make_hit("x")]), FakeClient(["y"])
    _, result = run("我该买茅台吗", retriever, client)
    assert result.refused and result.refusal_reason == "investment_advice"
    assert retriever.calls == 0 and client.calls == 0


def test_no_evidence_does_not_call_model():
    client = FakeClient(["y"])
    _, result = run("茅台营业收入", FakeRetriever([]), client)
    assert result.refusal_reason == "no_evidence" and client.calls == 0


def test_normal_answer_streams_and_records_citation_and_usage():
    pieces, result = run(
        "营业收入是多少",
        FakeRetriever([make_hit("| 营业收入 | 1,234.50 |")]),
        FakeClient(["营业收入为", " 1,234.50 元", "[1]"]),
    )
    assert "".join(pieces) == "营业收入为 1,234.50 元[1]"
    assert not result.refused
    assert result.citations == [1]
    assert result.unverified_numbers == []
    assert result.usage == Usage(12, 34)


def test_model_refusal_split_across_chunks_is_not_shown():
    pieces, result = run("x", FakeRetriever([make_hit("y")]), FakeClient(["证据", "不足"]))
    assert pieces == []
    assert result.refused and result.refusal_reason == "model_insufficient" and result.answer == ""


def test_answer_starting_like_marker_is_still_shown():
    pieces, result = run("x", FakeRetriever([make_hit("y")]), FakeClient(["证据", "显示如此[1]"]))
    assert "".join(pieces) == "证据显示如此[1]"
    assert not result.refused


def test_answer_without_citation_becomes_refusal():
    _, result = run("x", FakeRetriever([make_hit("y")]), FakeClient(["大约一百亿"]))
    assert result.refused and result.refusal_reason == "no_valid_citation"


def test_only_out_of_range_citation_becomes_refusal():
    _, result = run("x", FakeRetriever([make_hit("y")]), FakeClient(["结果如此[9]"]))
    assert result.refused and result.invalid_citations == [9]


def test_mixed_citations_keep_valid_and_report_invalid():
    result = AnswerResult(question="x", answer="甲[1]乙[3]", sources=[make_hit("y")])
    review(result)
    assert result.citations == [1] and result.invalid_citations == [3] and not result.refused


def test_number_missing_from_cited_chunk_is_flagged():
    hit = make_hit("| 营业收入 | 1,234.50 |")
    assert find_unverified_numbers("营业收入 9,999.00 元[1]", [hit], "问题") == ["9999.00"]


def test_number_check_ignores_commas_years_and_question_numbers():
    hit = make_hit("| 营业收入 | 1234.50 |")
    answer = "2025年营业收入 1,234.50 元，同比第3项[1]"
    assert find_unverified_numbers(answer, [hit], "第3项是多少") == []


def test_number_is_compared_whole_not_as_substring():
    hit = make_hit("| 比例 | 12.7 |")
    assert find_unverified_numbers("比例为 2.7[1]", [hit], "问题") == ["2.7"]


def test_model_error_is_reported_without_raising():
    _, result = run("x", FakeRetriever([make_hit("y")]), FakeClient(error=RuntimeError("密钥错误")))
    assert "密钥错误" in result.error and not result.refused


def test_retriever_error_is_reported_without_raising():
    class Broken:
        def retrieve(self, question, k=8):
            raise ConnectionError("索引不可用")

    _, result = run("x", Broken(), FakeClient(["y"]))
    assert "索引不可用" in result.error


def test_prompt_allows_partial_answers_only_for_independent_items():
    assert "该项证据不足" in SYSTEM_PROMPT
    assert "相互独立的信息" in SYSTEM_PROMPT


def test_prompt_does_not_doubt_units_once_number_is_found():
    assert "不要因为单位、口径或报表名称" in SYSTEM_PROMPT


def test_prompt_refuses_trading_questions_entirely():
    # 投资类问题不能先列股价再说不提供建议，必须整题拒答。
    assert "建仓" in SYSTEM_PROMPT and "不要先列出股价" in SYSTEM_PROMPT


def test_partial_answer_is_not_refused_and_is_flagged():
    text = "甲公司资产总计为 1,234.50 元[1]；乙公司该项证据不足"
    pieces, result = run("甲和乙的资产总计", FakeRetriever([make_hit("| 资产总计 | 1,234.50 |")]), FakeClient([text]))
    assert not result.refused and result.partial
    assert result.citations == [1] and "".join(pieces) == text


def test_complete_answer_is_not_partial():
    _, result = run("x", FakeRetriever([make_hit("| 营业收入 | 1,234.50 |")]), FakeClient(["营业收入为 1,234.50 元[1]"]))
    assert not result.refused and not result.partial


def test_answer_starting_with_marker_is_refused_not_partial():
    _, result = run("x", FakeRetriever([make_hit("y")]), FakeClient(["证据不足"]))
    assert result.refused and result.refusal_reason == "model_insufficient" and not result.partial


def test_partial_text_without_citation_is_still_refused():
    result = AnswerResult(question="x", answer="甲该项证据不足", sources=[make_hit("y")])
    review(result)
    assert result.refused and result.refusal_reason == "no_valid_citation" and not result.partial
