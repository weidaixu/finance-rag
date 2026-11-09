"""多轮对话流程的测试：假检索器、假模型，不联网。"""

import json
import logging
from types import SimpleNamespace

import pytest

from finrag.chat import ChatResult, rewrite_question, stream_chat_turn
from finrag.chunking import Chunk
from finrag.contracts import Hit
from finrag.llm import Usage
from finrag.sessions import SessionStore

REPORTS = [
    dict(doc_id="byd", company="比亚迪", aliases=["比亚迪", "BYD"], year=2025),
    dict(doc_id="catl", company="宁德时代", aliases=["宁德时代"], year=2025),
]


class FakeRetriever:
    def __init__(self, hits=None):
        self.hits = [Hit(Chunk("byd#1", "byd", "比亚迪", 2025, "zh", "比亚迪年报", 1, "s", "table",
                               "营业收入 100 元"), 1.0)] if hits is None else hits
        self.questions = []

    def retrieve(self, question, k=8):
        self.questions.append(question)
        return self.hits


class FakeClient:
    """非流式调用依次返回 rewrites；流式调用返回 pieces。记录每类调用的 messages。"""

    def __init__(self, rewrites=(), pieces=("收入 100 元[1]",), rewrite_error=None, answer_error=None):
        self.rewrites, self.pieces = list(rewrites), pieces
        self.rewrite_error, self.answer_error = rewrite_error, answer_error
        self.rewrite_calls, self.answer_calls = [], []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    @property
    def calls(self):
        return len(self.rewrite_calls) + len(self.answer_calls)

    def create(self, **kwargs):
        if kwargs.get("stream"):
            self.answer_calls.append(kwargs["messages"])
            if self.answer_error:
                raise self.answer_error
            return self._stream()
        self.rewrite_calls.append(kwargs["messages"])
        if self.rewrite_error:
            raise self.rewrite_error
        content = self.rewrites.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))

    def _stream(self):
        for piece in self.pieces:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=piece))], usage=None)
        yield SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def rw(question="", clarify=False, message=""):
    return json.dumps(dict(question=question, clarify=clarify, clarify_message=message), ensure_ascii=False)


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "s.db")


def turn(store, client, question, retriever=None, sid="s1", max_year=2025):
    retriever = retriever or FakeRetriever()
    items = list(stream_chat_turn(sid, question, store, retriever, client, "m", max_year, REPORTS))
    assert isinstance(items[-1], ChatResult)
    return items, items[-1], retriever


def test_followup_is_rewritten_and_retrieval_uses_rewrite(store):
    store.add_turn("s1", "比亚迪2025年营收多少？", "", "营收 100 元[1]", "answered")
    client = FakeClient(rewrites=[rw("比亚迪2025年的净利润是多少？")])
    items, final, retriever = turn(store, client, "那利润呢？")
    assert retriever.questions == ["比亚迪2025年的净利润是多少？"]
    assert items[0] == {"type": "rewritten", "question": "比亚迪2025年的净利润是多少？"}
    assert "收入 100 元[1]" in items
    assert final.rewritten == "比亚迪2025年的净利润是多少？" and not final.clarify
    assert store.history("s1")[-1].rewritten == "比亚迪2025年的净利润是多少？"


def test_rewrite_history_prefers_rewritten_question(store):
    # “那利润呢？”本身没有公司和年份，再下一轮要靠改写后的完整问题来理解。
    store.add_turn("s1", "那利润呢？", "比亚迪2025年的净利润是多少？", "利润 50 元[1]", "answered")
    client = FakeClient(rewrites=[rw("比亚迪2024年的净利润是多少？")])
    turn(store, client, "2024年呢？")
    prompt = client.rewrite_calls[0][1]["content"]
    assert "比亚迪2025年的净利润是多少？" in prompt and "那利润呢？" not in prompt


def test_generation_messages_never_contain_history(store):
    store.add_turn("s1", "上一轮的独特问题XYZ", "", "上一轮的独特回答ABC", "answered")
    client = FakeClient(rewrites=[rw("比亚迪2025年的净利润是多少？")])
    turn(store, client, "那利润呢？")
    sent = json.dumps(client.answer_calls, ensure_ascii=False)
    assert "XYZ" not in sent and "ABC" not in sent and "净利润" in sent
    assert "XYZ" in json.dumps(client.rewrite_calls, ensure_ascii=False)  # 历史只给改写


def test_history_answer_truncated_and_limited_to_three_turns(store):
    for n in range(5):
        store.add_turn("s1", f"Q{n}", "", "答" * 400 + "END", "answered")
    client = FakeClient(rewrites=[rw("比亚迪利润")])
    turn(store, client, "那利润呢？")
    text = client.rewrite_calls[0][1]["content"]
    assert "Q1" not in text and "Q2" in text and "Q4" in text
    assert "END" not in text and "答" * 300 in text and "答" * 301 not in text


def test_no_history_with_company_skips_rewrite_call(store):
    client = FakeClient()
    items, final, _ = turn(store, client, "比亚迪2025年营收多少？")
    assert client.rewrite_calls == [] and len(client.answer_calls) == 1
    assert final.rewritten == "" and not any(isinstance(i, dict) for i in items)


@pytest.mark.parametrize("bad", ["不是JSON", "[1,2]", rw(""), '{"question": 5}'])
def test_invalid_rewrite_falls_back_to_original(store, bad, caplog):
    store.add_turn("s1", "比亚迪营收", "", "答 [1]", "answered")
    client = FakeClient(rewrites=[bad])
    with caplog.at_level(logging.WARNING):
        _, final, retriever = turn(store, client, "那利润呢？")
    assert retriever.questions == ["那利润呢？"] and final.rewritten == ""
    assert "改写" in caplog.text


def test_rewrite_error_falls_back_and_fenced_json_is_accepted(store):
    store.add_turn("s1", "比亚迪营收", "", "答 [1]", "answered")
    _, _, retriever = turn(store, FakeClient(rewrite_error=RuntimeError("sk-secret")), "那利润呢？")
    assert retriever.questions == ["那利润呢？"]
    fenced = "```json\n" + rw("比亚迪利润") + "\n```"
    result = rewrite_question(FakeClient(rewrites=[fenced]), "m", [], "那利润呢？", ["比亚迪"])
    assert result.question == "比亚迪利润" and result.usage == Usage(100, 20)


def test_clarify_skips_retrieval_and_is_saved(store):
    client = FakeClient(rewrites=[rw("营业收入多少？", True, "您想了解哪家公司？目前可以查询：比亚迪、宁德时代。")])
    _, final, retriever = turn(store, client, "营业收入多少？")
    assert final.clarify and retriever.questions == [] and client.answer_calls == []
    assert final.result.answer.startswith("您想了解哪家公司")
    saved = store.history("s1")[0]
    assert saved.status == "clarify" and saved.answer == final.result.answer


def test_clarify_without_message_gets_default_listing_companies():
    result = rewrite_question(FakeClient(rewrites=[rw("x", True, "")]), "m", [], "营收多少", ["比亚迪", "宁德时代"])
    assert result.clarify and "比亚迪" in result.clarify_message


def test_advice_in_original_blocks_all_model_calls(store):
    client = FakeClient()
    _, final, retriever = turn(store, client, "我现在应该买入茅台吗")
    assert final.result.refusal_reason == "investment_advice"
    assert client.calls == 0 and retriever.questions == []
    assert store.history("s1")[0].status == "refused"


def test_advice_exposed_only_by_rewrite_is_blocked(store):
    store.add_turn("s1", "茅台2025年营收", "", "营收 1 元[1]", "answered")
    client = FakeClient(rewrites=[rw("我现在应该买入茅台吗")])
    _, final, retriever = turn(store, client, "那现在值得买吗？")
    assert final.result.refused and final.result.refusal_reason == "investment_advice"
    assert retriever.questions == [] and client.answer_calls == []
    assert store.history("s1")[-1].status == "refused" and store.history("s1")[-1].answer == ""


def test_every_outcome_is_saved(store):
    turn(store, FakeClient(), "比亚迪2025年营收多少？", sid="a")
    assert store.history("a")[0].status == "answered" and store.history("a")[0].citations[0]["n"] == 1
    turn(store, FakeClient(pieces=("证据不足",)), "比亚迪2025年营收多少？", sid="b")
    assert store.history("b")[0].status == "refused" and store.history("b")[0].answer == ""
    turn(store, FakeClient(answer_error=RuntimeError("boom")), "比亚迪2025年营收多少？", sid="c")
    saved = store.history("c")[0]
    assert saved.status == "error" and saved.answer == "" and saved.citations == []
    turn(store, FakeClient(), "比亚迪2025年营收多少？", retriever=FakeRetriever([]), sid="d")
    assert store.history("d")[0].status == "refused"


def test_rewrite_usage_is_added_to_total_cost(store):
    store.add_turn("s1", "比亚迪营收", "", "答 [1]", "answered")
    _, final, _ = turn(store, FakeClient(rewrites=[rw("比亚迪利润")]), "那利润呢？")
    assert final.result.usage == Usage(110, 25)
    assert final.result.usage.cost_yuan == pytest.approx((110 * .8 + 25 * 2.7) / 1_000_000)
    store.clear("s1")
    _, clarified, _ = turn(store, FakeClient(rewrites=[rw("营收", True, "哪家？")]), "营收多少？")
    assert clarified.result.usage == Usage(100, 20)
