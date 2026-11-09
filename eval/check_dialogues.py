"""检查多轮对话评测题的格式，并核对每条 quote 是否真的出现在 PDF 的对应页上。

和 check_gold.py 一样，这个脚本只证明「引文在那一页」，不能证明题目出得合理，后者要人工抽查。

用法：uv run python eval/check_dialogues.py
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.check_gold import check_quotes, copies_source  # noqa: E402

DIALOGUES = ROOT / "eval" / "dialogues.jsonl"
DIALOGUE_TYPES = {
    "pronoun_followup",  # 追问省略了公司或指标，如“那利润呢？”
    "company_switch",  # 同一指标换一家公司，如“那宁德时代呢？”
    "year_switch",  # 同一指标换年份，如“2024 年呢？”
    "compare",  # 基于前文对比两家公司，如“和宁德时代比呢？”
    "clarify",  # 问题不清楚，系统要反问，用户补充后再回答
    "topic_change",  # 切换到无关话题，新问题不能被旧历史带偏
    "refuse_in_dialogue",  # 正常问答之后出现该拒答的问题
}
TURN_KINDS = {"answer", "clarify", "refuse"}
MIN_TURNS, MAX_TURNS = 2, 4


def check_turn(turn: dict, position: int, doc_ids: set[str]) -> list[str]:
    errors: list[str] = []
    kind = turn.get("kind")
    if kind not in TURN_KINDS:
        return [f"第 {position} 轮的 kind 不合法：{kind}"]
    if not str(turn.get("question", "")).strip():
        errors.append(f"第 {position} 轮缺少 question")
    if kind == "answer":
        if not turn.get("answer_contains"):
            errors.append(f"第 {position} 轮是回答轮，必须有 answer_contains")
        gold = turn.get("gold")
        if not gold:
            errors.append(f"第 {position} 轮是回答轮，必须有 gold")
        for entry in gold or []:
            if entry.get("doc_id") not in doc_ids:
                errors.append(f"第 {position} 轮的 doc_id 未知：{entry.get('doc_id')}")
        # 第 1 轮之后的回答轮要靠历史才能理解，所以必须写明改写后应包含什么。
        if position > 1 and not turn.get("rewrite_contains"):
            errors.append(f"第 {position} 轮是追问，必须有 rewrite_contains")
    elif turn.get("gold") or turn.get("answer_contains"):
        errors.append(f"第 {position} 轮是 {kind}，不应该有 gold 或 answer_contains")
    return errors


def check_dialogue(dialogue: dict, doc_ids: set[str]) -> list[str]:
    errors: list[str] = []
    if not dialogue.get("id"):
        errors.append("缺少 id")
    kind = dialogue.get("type")
    if kind not in DIALOGUE_TYPES:
        errors.append(f"type 不合法：{kind}")
    turns = dialogue.get("turns") or []
    if not MIN_TURNS <= len(turns) <= MAX_TURNS:
        errors.append(f"轮数必须在 {MIN_TURNS} 到 {MAX_TURNS} 之间，现在是 {len(turns)}")
    for position, turn in enumerate(turns, start=1):
        errors.extend(check_turn(turn, position, doc_ids))
    kinds = [turn.get("kind") for turn in turns]
    if kind == "clarify" and "clarify" not in kinds:
        errors.append("clarify 类型的对话至少要有一轮 kind=clarify")
    if kind == "refuse_in_dialogue" and "refuse" not in kinds:
        errors.append("refuse_in_dialogue 类型的对话至少要有一轮 kind=refuse")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dialogues", type=Path, default=DIALOGUES)
    args = parser.parse_args()
    if not args.dialogues.exists():
        print(f"找不到 {args.dialogues}")
        return 1

    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    documents = {r["doc_id"]: pymupdf.open(ROOT / "data" / "raw" / f"{r['doc_id']}.pdf") for r in manifest}
    dialogues = [json.loads(line) for line in args.dialogues.read_text(encoding="utf-8").splitlines() if line.strip()]

    failures = 0
    copied: list[str] = []
    seen: set[str] = set()
    for dialogue in dialogues:
        errors = check_dialogue(dialogue, set(documents))
        if dialogue.get("id") in seen:
            errors.append("id 重复")
        seen.add(dialogue.get("id"))
        for position, turn in enumerate(dialogue.get("turns") or [], start=1):
            if turn.get("kind") != "answer":
                continue
            errors.extend(f"第 {position} 轮：{error}" for error in check_quotes(turn, documents))
            if copies_source(turn, documents):
                copied.append(f"{dialogue.get('id')}#{position}")
        if errors:
            failures += 1
            print(f"[不通过] {dialogue.get('id')}：" + "；".join(errors))

    turns = [turn for dialogue in dialogues for turn in dialogue.get("turns") or []]
    print(f"\n共 {len(dialogues)} 组对话、{len(turns)} 轮，{failures} 组不通过")
    print("对话类型：", dict(Counter(dialogue.get("type") for dialogue in dialogues)))
    print("每轮类别：", dict(Counter(turn.get("kind") for turn in turns)))
    print(f"措辞贴近原文（提示，不算不通过）：{copied}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
