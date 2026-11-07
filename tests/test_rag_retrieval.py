"""检索和评测指标的测试：用构造的小数据和假的模型，不联网，不产生费用。"""

from types import SimpleNamespace

import numpy as np
import pytest

from eval.run_eval import (
    answer_in_hits,
    answer_is_correct,
    covers_all_gold,
    first_gold_rank,
    load_questions,
    questions_are_frozen,
    score_answer,
    summarize_retrieval,
)
from finrag.answer import AnswerResult
from finrag.chunking import Chunk
from finrag.contracts import Hit
from finrag.retrieval import (
    BM25Index,
    HybridRetriever,
    IndexNotReady,
    detect_companies,
    make_embedder,
    make_reranker,
    rank,
    reciprocal_rank_fusion,
)

REPORTS = [
    {"company": "贵州茅台", "aliases": ["贵州茅台", "茅台", "Moutai"]},
    {"company": "比亚迪", "aliases": ["比亚迪", "BYD"]},
    {"company": "Tesla", "aliases": ["Tesla", "特斯拉"]},
]


def chunk(index: int, company: str, text: str, page: int | None = None) -> Chunk:
    return Chunk(f"c{index}", f"doc-{company}", company, 2025, "zh", "t", page or index + 1, "", "text", text)


CHUNKS = [
    chunk(0, "贵州茅台", "营业收入 168,838,102,514.79 元"),
    chunk(1, "比亚迪", "营业收入 803,964,958,000.00 元"),
    chunk(2, "比亚迪", "买入返售金融资产余额"),
    chunk(3, "Tesla", "Total revenues were 94,827 million"),
]


def test_bm25_rare_term_beats_common_term():
    index = BM25Index([["营业", "收入"], ["营业", "利润"], ["营业", "现金"], ["营业", "收入", "茅台"]])
    scores = index.scores(["茅台", "营业"])
    assert int(np.argmax(scores)) == 3
    assert scores[0] == scores[1] == scores[2]


def test_bm25_unknown_term_scores_zero():
    assert not BM25Index([["甲"], ["乙"]]).scores(["丙"]).any()


def test_bm25_prefers_shorter_document_with_same_count():
    scores = BM25Index([["甲", "乙"], ["甲", "乙", "丙", "丁", "戊", "己"], ["庚"]]).scores(["甲"])
    assert scores[0] > scores[1] > 0


def test_bm25_empty_query_and_empty_corpus():
    assert not BM25Index([["甲"]]).scores([]).any()
    assert len(BM25Index([]).scores(["甲"])) == 0


def test_rank_filters_disallowed_and_zero_scores_and_is_stable():
    scores = np.array([0.0, 5.0, 3.0, 5.0, 9.0])
    allowed = np.array([True, True, True, True, False])
    assert rank(scores, allowed, 10) == [1, 3, 2]
    assert rank(scores, allowed, 2) == [1, 3]


def test_rrf_uses_positions_with_known_values():
    fused = dict(reciprocal_rank_fusion([[1, 2], [2, 3]], rrf_k=60))
    assert fused[2] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[1] == pytest.approx(1 / 61)
    assert fused[3] == pytest.approx(1 / 62)


def test_rrf_item_in_both_lists_ranks_first_and_empty_input_is_safe():
    assert reciprocal_rank_fusion([[1, 2], [2, 3]])[0][0] == 2
    assert reciprocal_rank_fusion([]) == []


@pytest.mark.parametrize(
    "question,expected",
    [
        ("茅台的营业收入", {"贵州茅台"}),
        ("BYD revenue", {"比亚迪"}),
        ("byd revenue", {"比亚迪"}),
        ("特斯拉和比亚迪的收入", {"Tesla", "比亚迪"}),
        ("腾讯的营业收入", set()),
        ("营业收入是什么", set()),
    ],
)
def test_detect_companies(question, expected):
    assert detect_companies(question, REPORTS) == expected


def test_retrieve_only_returns_named_company():
    hits = HybridRetriever(CHUNKS, REPORTS, mode="bm25").retrieve("比亚迪营业收入", k=8)
    assert hits and {hit.chunk.company for hit in hits} == {"比亚迪"}
    assert hits[0].chunk.chunk_id == "c1"


def test_retrieve_without_company_searches_everything():
    hits = HybridRetriever(CHUNKS, REPORTS, mode="bm25").retrieve("营业收入", k=8)
    assert {hit.chunk.company for hit in hits} == {"贵州茅台", "比亚迪"}


def test_retrieve_returns_empty_when_nothing_matches():
    assert HybridRetriever(CHUNKS, REPORTS, mode="bm25").retrieve("完全无关的内容", k=8) == []


def test_retrieve_respects_k():
    many = [chunk(i, "比亚迪", "营业收入") for i in range(30)]
    assert len(HybridRetriever(many, REPORTS, mode="bm25").retrieve("营业收入", k=3)) == 3


def fake_vectors():
    """每段一个方向，fake_embed 总是指向第 3 段（下标 2）。"""
    return np.eye(4, dtype=np.float32)


def fake_embed(texts):
    return np.array([[0, 0, 1, 0]] * len(texts), dtype=np.float32)


def test_vector_mode_finds_meaning_without_shared_words():
    hits = HybridRetriever(CHUNKS, REPORTS, fake_vectors(), fake_embed, mode="vector").retrieve("没有共同词语", k=1)
    assert hits[0].chunk.chunk_id == "c2"


def test_vector_mode_still_applies_company_filter():
    hits = HybridRetriever(CHUNKS, REPORTS, fake_vectors(), fake_embed, mode="vector").retrieve("茅台", k=8)
    assert {hit.chunk.company for hit in hits} == {"贵州茅台"}


def test_hybrid_contains_results_from_both_routes():
    hits = HybridRetriever(CHUNKS, REPORTS, fake_vectors(), fake_embed).retrieve("Total revenues", k=8)
    ids = [hit.chunk.chunk_id for hit in hits]
    assert "c3" in ids and "c2" in ids


def test_rerank_order_wins_and_maps_back_to_chunks():
    def reverse(question, documents, top_n):
        return [(len(documents) - 1 - i, 1.0 - i / 10) for i in range(min(top_n, len(documents)))]

    plain = HybridRetriever(CHUNKS, REPORTS, mode="bm25").retrieve("营业收入", k=2)
    hits = HybridRetriever(CHUNKS, REPORTS, rerank=reverse, mode="bm25").retrieve("营业收入", k=2)
    assert [h.chunk.chunk_id for h in hits] == [h.chunk.chunk_id for h in reversed(plain)]
    assert hits[0].score == 1.0


def test_vector_mode_without_embeddings_is_rejected():
    with pytest.raises(ValueError):
        HybridRetriever(CHUNKS, REPORTS, mode="vector")


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        HybridRetriever(CHUNKS, REPORTS, mode="magic")


def test_embedding_count_mismatch_is_rejected():
    with pytest.raises(IndexNotReady):
        HybridRetriever(CHUNKS, REPORTS, np.eye(2), fake_embed)


class FakeEmbeddingClient:
    def __init__(self):
        self.batches = []
        self.embeddings = SimpleNamespace(create=self.create)

    def create(self, model, input, dimensions):
        self.batches.append(len(input))
        # 故意打乱返回顺序，代码必须按 index 排回去。
        items = [SimpleNamespace(index=i, embedding=[3.0, 4.0 * (i + 1)]) for i in range(len(input))]
        return SimpleNamespace(data=list(reversed(items)))


def test_embedder_batches_keeps_order_and_normalizes():
    client = FakeEmbeddingClient()
    result = make_embedder(client)(["文本"] * 23)
    assert client.batches == [10, 10, 3]
    assert result.shape == (23, 2)
    assert np.linalg.norm(result, axis=1) == pytest.approx(np.ones(23))
    assert result[0] == pytest.approx([0.6, 0.8])


def fake_post(payload, status_error=None):
    def post(url, headers, json, timeout):
        def raise_for_status():
            if status_error:
                raise status_error

        return SimpleNamespace(raise_for_status=raise_for_status, json=lambda: payload)

    return post


@pytest.mark.parametrize(
    "payload",
    [
        {"results": [{"index": 1, "relevance_score": 0.9}]},
        {"output": {"results": [{"index": 1, "relevance_score": 0.9}]}},
    ],
)
def test_reranker_reads_both_response_shapes(payload):
    assert make_reranker("key", post=fake_post(payload))("q", ["a", "b"], 1) == [(1, 0.9)]


def test_reranker_rejects_unexpected_response():
    with pytest.raises(ValueError):
        make_reranker("key", post=fake_post({"message": "bad"}))("q", ["a"], 1)


def test_reranker_surfaces_http_error():
    with pytest.raises(RuntimeError):
        make_reranker("key", post=fake_post({}, RuntimeError("401")))("q", ["a"], 1)


def hit_at(page, doc="d"):
    return Hit(chunk(0, "x", "t", page=page).__class__("c", doc, "x", 2025, "zh", "t", page, "", "text", "t"), 1.0)


def test_first_gold_rank():
    hits = [hit_at(1), hit_at(5), hit_at(9)]
    assert first_gold_rank(hits, {("d", 5)}) == 2
    assert first_gold_rank(hits, {("d", 7)}) is None
    assert first_gold_rank(hits, {("other", 5)}) is None


def test_covers_all_gold_needs_every_page():
    hits = [hit_at(1), hit_at(5)]
    assert covers_all_gold(hits, {("d", 1), ("d", 5)})
    assert not covers_all_gold(hits, {("d", 1), ("d", 7)})


def test_summary_with_known_ranks():
    rows = [
        {"rank": 1, "all_pages": True, "answer_found": True},
        {"rank": 4, "all_pages": False, "answer_found": True},
        {"rank": None, "all_pages": False, "answer_found": True},
    ]
    summary = summarize_retrieval(rows)
    assert summary["n"] == 3
    assert summary["answer_found"] == 1
    assert summary["hit@1"] == pytest.approx(1 / 3)
    assert summary["hit@8"] == pytest.approx(2 / 3)
    assert summary["mrr"] == pytest.approx((1 + 0.25) / 3)


def hit_with_text(page, text):
    return Hit(Chunk("c", "d", "x", 2025, "zh", "t", page, "", "table", text), 1.0)


def test_citation_on_other_page_counts_when_chunk_contains_answer():
    result = AnswerResult(question="q", answer="结果是 1,234[1]", citations=[1], sources=[hit_with_text(9, "| 收入 | 1,234 |")])
    item = {"should_refuse": False, "answer_contains": ["1,234"], "gold": [{"doc_id": "d", "page": 5}]}
    assert score_answer(item, result).status == "correct"


def test_citation_on_other_page_without_answer_is_wrong():
    result = AnswerResult(question="q", answer="结果是 1,234[1]", citations=[1], sources=[hit_with_text(9, "无关内容")])
    item = {"should_refuse": False, "answer_contains": ["1,234"], "gold": [{"doc_id": "d", "page": 5}]}
    assert score_answer(item, result).status == "wrong_citation"


def test_answer_in_hits_needs_all_parts():
    hits = [hit_with_text(1, "收入 1,234"), hit_with_text(2, "利润 56")]
    assert answer_in_hits(hits, ["1234", "56"])
    assert not answer_in_hits(hits, ["1234", "78"])
    assert not answer_in_hits(hits, [])


def test_questions_are_still_frozen():
    assert questions_are_frozen()


def test_question_file_without_hash_is_not_frozen(tmp_path):
    path = tmp_path / "questions_new.jsonl"
    path.write_text('{"id": "q1"}\n', encoding="utf-8")
    assert not questions_are_frozen(path)


def test_load_questions_tags_set_and_rejects_duplicate_ids(tmp_path):
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    first.write_text('{"id": "q1"}\n', encoding="utf-8")
    second.write_text('{"id": "q2"}\n\n', encoding="utf-8")
    assert [(i["id"], i["set"]) for i in load_questions([first, second])] == [("q1", "a"), ("q2", "b")]
    second.write_text('{"id": "q1"}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_questions([first, second])


def test_summary_of_no_rows_does_not_crash():
    assert summarize_retrieval([])["mrr"] == 0


def test_answer_matching_ignores_commas_spaces_and_traditional():
    assert answer_is_correct("營業收入為 1,234.5 元", ["1234.5", "营业收入"])
    assert not answer_is_correct("营业收入为 1,234.5 元", ["1234.6"])
    assert not answer_is_correct("任何答案", [])


GOLD_ITEM = {"should_refuse": False, "answer_contains": ["100"], "gold": [{"doc_id": "d", "page": 5}]}


@pytest.mark.parametrize(
    "item,result_fields,status,passed",
    [
        (GOLD_ITEM, {"answer": "结果是 100[1]", "citations": [1], "sources": [hit_at(5)]}, "correct", True),
        (GOLD_ITEM, {"answer": "结果是 200[1]", "citations": [1], "sources": [hit_at(5)]}, "wrong_answer", False),
        (GOLD_ITEM, {"answer": "结果是 100[1]", "citations": [1], "sources": [hit_at(9)]}, "wrong_citation", False),
        (GOLD_ITEM, {"refused": True}, "wrongly_refused", False),
        ({"should_refuse": True}, {"refused": True}, "correctly_refused", True),
        ({"should_refuse": True}, {"answer": "瞎答[1]"}, "should_have_refused", False),
        ({"should_refuse": True}, {"answer": "年报未单独披露该毛利率[1]"}, "manual_review", False),
        ({"should_refuse": True}, {"answer": "The filing does not disclose it [1]"}, "manual_review", False),
        (GOLD_ITEM, {"error": "超时"}, "error", False),
    ],
)
def test_score_answer(item, result_fields, status, passed):
    score = score_answer(item, AnswerResult(question="q", **result_fields))
    assert (score.status, score.passed) == (status, passed)
