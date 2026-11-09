"""多轮对话评测题校验脚本的测试。校验脚本是评测题的验收标准，它本身必须可靠。"""

from eval.check_dialogues import check_dialogue, check_turn

DOCS = {"doc"}
GOLD = [{"doc_id": "doc", "page": 1, "quote": "x"}]


def first_turn():
    return {"kind": "answer", "question": "比亚迪营收？", "answer_contains": ["100"], "gold": GOLD}


def followup_turn(**overrides):
    turn = {"kind": "answer", "question": "那利润呢？", "answer_contains": ["50"], "gold": GOLD, "rewrite_contains": ["比亚迪", "利润"]}
    return {**turn, **overrides}


def dialogue(**overrides):
    return {**{"id": "d1", "type": "pronoun_followup", "turns": [first_turn(), followup_turn()]}, **overrides}


def test_valid_dialogue_passes():
    assert check_dialogue(dialogue(), DOCS) == []


def test_followup_must_state_expected_rewrite():
    errors = check_dialogue(dialogue(turns=[first_turn(), followup_turn(rewrite_contains=[])]), DOCS)
    assert any("rewrite_contains" in error for error in errors)


def test_first_turn_does_not_need_rewrite():
    assert check_turn(first_turn(), 1, DOCS) == []


def test_too_few_or_too_many_turns_rejected():
    assert any("轮数" in e for e in check_dialogue(dialogue(turns=[first_turn()]), DOCS))
    assert any("轮数" in e for e in check_dialogue(dialogue(turns=[first_turn()] + [followup_turn()] * 4), DOCS))


def test_unknown_type_and_turn_kind_rejected():
    assert any("type" in e for e in check_dialogue(dialogue(type="other"), DOCS))
    assert any("kind" in e for e in check_turn({"kind": "chat", "question": "x"}, 1, DOCS))


def test_answer_turn_needs_answer_and_gold():
    errors = check_turn({"kind": "answer", "question": "x"}, 1, DOCS)
    assert any("answer_contains" in e for e in errors) and any("gold" in e for e in errors)


def test_unknown_doc_id_rejected():
    errors = check_turn(followup_turn(gold=[{"doc_id": "nope", "page": 1, "quote": "x"}]), 2, DOCS)
    assert any("doc_id" in e for e in errors)


def test_clarify_and_refuse_turns_must_not_have_gold():
    assert any("不应该有" in e for e in check_turn({"kind": "refuse", "question": "x", "gold": GOLD}, 2, DOCS))
    assert check_turn({"kind": "clarify", "question": "营收多少？"}, 1, DOCS) == []


def test_clarify_dialogue_needs_clarify_turn():
    assert any("clarify" in e for e in check_dialogue(dialogue(type="clarify"), DOCS))
    good = [{"kind": "clarify", "question": "营收多少？"}, followup_turn()]
    assert check_dialogue(dialogue(type="clarify", turns=good), DOCS) == []


def test_refuse_dialogue_needs_refuse_turn():
    assert any("refuse" in e for e in check_dialogue(dialogue(type="refuse_in_dialogue"), DOCS))
