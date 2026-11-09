"""多轮评测脚本的测试：只测评分和冻结检查，不调用模型。"""

import hashlib
import json

import pytest

from eval import run_dialogues as rd
from finrag.answer import AnswerResult
from finrag.chat import ChatResult
from finrag.chunking import Chunk
from finrag.contracts import Hit

GOLD = [dict(doc_id="byd", page=3)]


def hit(page=3, text="营业收入 100 亿元"):
    return Hit(Chunk(f"byd#{page}", "byd", "比亚迪", 2025, "zh", "年报", page, "s", "table", text), 1.0)


def chat(answer="营业收入 100 亿元[1]", rewritten="", clarify=False, refused=False, error="", page=3):
    result = AnswerResult(question="q", answer=answer, refused=refused, error=error,
                          sources=[hit(page)], citations=[] if refused or clarify else [1])
    return ChatResult(result, rewritten, clarify)


ANSWER = dict(kind="answer", question="那利润呢？", answer_contains=["100 亿元"], gold=GOLD,
              rewrite_contains=["比亚迪", "利润"])


def test_rewrite_matching_ignores_case_and_whitespace():
    turn = dict(rewrite_contains=["BYD", "净 利润"])
    assert rd.rewrite_is_ok(turn, 2, "byd 2025年的净利润是多少")
    assert not rd.rewrite_is_ok(turn, 2, "那利润呢？")
    assert rd.rewrite_is_ok({}, 1, "任何问题")
    assert not rd.rewrite_is_ok({}, 2, "任何问题")


def test_answer_turn_passes_only_when_rewrite_answer_and_citation_are_all_ok():
    ok = rd.score_turn(ANSWER, 2, chat(rewritten="比亚迪的利润"))
    assert ok.passed and ok.status == "correct" and ok.rewrite_ok and ok.answer_ok
    bad_rewrite = rd.score_turn(ANSWER, 2, chat(rewritten=""))
    assert not bad_rewrite.passed and bad_rewrite.status == "wrong_rewrite" and bad_rewrite.answer_ok
    assert rd.score_turn(ANSWER, 2, chat("别的内容[1]", "比亚迪的利润")).status == "wrong_answer"
    assert rd.score_turn(ANSWER, 2, chat("营业收入 100 亿元[1]；某项证据不足", "比亚迪的利润")).status == "partial_answer"
    assert rd.score_turn(ANSWER, 2, chat("", "比亚迪的利润", refused=True)).status == "wrongly_refused"
    assert rd.score_turn(ANSWER, 2, chat(clarify=True)).status == "unexpected_clarify"
    assert rd.score_turn(ANSWER, 2, chat(error="boom", rewritten="比亚迪的利润")).status == "error"


def test_citation_to_other_page_is_ok_if_it_contains_answer_but_not_otherwise():
    assert rd.score_turn(ANSWER, 2, chat(rewritten="比亚迪的利润", page=9)).passed  # 其他页的片段含答案
    result = chat(rewritten="比亚迪的利润")
    result.result.sources = [hit(9, "无关内容")]
    assert rd.score_turn(ANSWER, 2, result).status == "wrong_citation"


def test_clarify_turn():
    turn = dict(kind="clarify", question="营收多少？")
    assert rd.score_turn(turn, 1, chat("您想了解哪家公司？", clarify=True)).passed
    assert rd.score_turn(turn, 1, chat()).status == "not_clarified"


def test_refuse_turn_including_manual_review():
    turn = dict(kind="refuse", question="现在值得买吗？")
    assert rd.score_turn(turn, 3, chat("", refused=True)).passed
    manual = rd.score_turn(turn, 3, chat("年报未披露该信息[1]"))
    assert manual.status == "manual_review" and not manual.passed
    assert rd.score_turn(turn, 3, chat("建议买入[1]")).status == "should_have_refused"
    assert not rd.score_turn(turn, 3, chat("您想了解哪家公司？", clarify=True)).passed


def test_main_refuses_when_missing_or_not_frozen(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: pytest.fail("不应该创建模型客户端"))
    missing = tmp_path / "dialogues.jsonl"
    monkeypatch.setattr("sys.argv", ["run_dialogues", "--dialogues", str(missing)])
    assert rd.main() == 1 and "找不到" in capsys.readouterr().out
    missing.write_text("{}\n", encoding="utf-8")
    assert rd.main() == 1 and "没有冻结" in capsys.readouterr().out
    missing.with_suffix(".sha256").write_text("0" * 64 + " *dialogues.jsonl\n", encoding="utf-8")
    assert rd.main() == 1 and "没有冻结" in capsys.readouterr().out
    digest = hashlib.sha256(missing.read_bytes()).hexdigest()
    missing.with_suffix(".sha256").write_text(f"{digest} *dialogues.jsonl\n", encoding="utf-8")
    assert rd.questions_are_frozen(missing)


def test_report_states_sample_size_and_lists_failures(tmp_path):
    row = dict(dialogue_id="d1", dialogue_type="pronoun_followup", position=2, kind="answer", question="那利润呢？",
               rewritten="", clarify=False, refused=False, refusal_reason="", error="", answer="错" * 300,
               expected=[], rewrite_contains=[], status="wrong_rewrite", passed=False, rewrite_ok=False,
               answer_ok=True, cost_yuan=0.01)
    path = tmp_path / "r.md"
    rd.write_report([row], 1, path)
    text = path.read_text(encoding="utf-8")
    assert "1 组对话、1 轮" in text and "那利润呢？" in text and "错" * 200 in text and "错" * 201 not in text
    assert "\r" not in text
    json.dumps(row, ensure_ascii=False)
