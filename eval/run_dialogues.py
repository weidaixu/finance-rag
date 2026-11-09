"""多轮对话评测：按顺序走完每组对话，检查改写、回答、反问和拒答，生成 eval/report-dialogues.md。

会调用模型并产生费用。题目文件 eval/dialogues.jsonl 必须已冻结（旁边有 dialogues.sha256）：
    uv run python eval/run_dialogues.py
"""

import argparse
import json
import sys
import tempfile
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.run_eval import (  # noqa: E402
    _NOT_DISCLOSED,
    answer_is_correct,
    citation_is_correct,
    gold_pages,
    questions_are_frozen,
    squeeze,
)
from finrag.chat import ChatResult, stream_chat_turn  # noqa: E402
from finrag.sessions import SessionStore  # noqa: E402

DIALOGUES = ROOT / "eval" / "dialogues.jsonl"
REPORT = ROOT / "eval" / "report-dialogues.md"
RESULTS = ROOT / "eval" / "results"


@dataclass
class TurnScore:
    status: str  # correct / wrong_rewrite / wrong_answer / wrong_citation / wrongly_refused / partial_answer / unexpected_clarify / clarified / not_clarified / correctly_refused / should_have_refused / manual_review / error
    passed: bool
    rewrite_ok: bool | None = None  # 只有回答轮才有
    answer_ok: bool | None = None


def rewrite_is_ok(turn: dict, position: int, effective_question: str) -> bool:
    """rewrite_contains 的关键词全部出现在改写结果里（忽略大小写和空白）。第 1 轮没有这一项就算通过。"""
    expected = turn.get("rewrite_contains") or []
    if not expected:
        return position == 1
    text = squeeze(effective_question)
    return all(squeeze(str(item)) in text for item in expected)


def score_turn(turn: dict, position: int, chat: ChatResult) -> TurnScore:
    result = chat.result
    if result.error:
        return TurnScore("error", False)
    kind = turn["kind"]
    if kind == "clarify":
        return TurnScore("clarified", True) if chat.clarify else TurnScore("not_clarified", False)
    if kind == "refuse":
        if result.refused and not chat.clarify:
            return TurnScore("correctly_refused", True)
        if _NOT_DISCLOSED.search(result.answer):
            return TurnScore("manual_review", False)
        return TurnScore("should_have_refused", False)

    rewrite_ok = rewrite_is_ok(turn, position, chat.rewritten or turn["question"])
    if chat.clarify:
        return TurnScore("unexpected_clarify", False, rewrite_ok, False)
    if result.refused:
        return TurnScore("wrongly_refused", False, rewrite_ok, False)
    expected = turn["answer_contains"]
    if "证据不足" in result.answer:
        status = "partial_answer"
    elif not answer_is_correct(result.answer, expected):
        status = "wrong_answer"
    elif not citation_is_correct(result, gold_pages(turn), expected):
        status = "wrong_citation"
    else:
        status = "correct"
    answer_ok = status == "correct"
    if answer_ok and not rewrite_ok:
        status = "wrong_rewrite"
    return TurnScore(status, answer_ok and rewrite_ok, rewrite_ok, answer_ok)


def run_dialogue(dialogue: dict, retriever, client, model: str, max_year: int, reports: list[dict]) -> list[dict]:
    rows = []
    session_id = str(uuid.uuid4())
    with tempfile.TemporaryDirectory() as directory:
        store = SessionStore(Path(directory) / "dialogue.db")
        for position, turn in enumerate(dialogue["turns"], start=1):
            chat = None
            for item in stream_chat_turn(session_id, turn["question"], store, retriever, client,
                                         model, max_year, reports):
                if isinstance(item, ChatResult):
                    chat = item
            score = score_turn(turn, position, chat)
            rows.append({
                "dialogue_id": dialogue["id"],
                "dialogue_type": dialogue["type"],
                "position": position,
                "kind": turn["kind"],
                "question": turn["question"],
                "rewritten": chat.rewritten,
                "clarify": chat.clarify,
                "refused": chat.result.refused,
                "refusal_reason": chat.result.refusal_reason,
                "error": chat.result.error,
                "answer": chat.result.answer,
                "expected": turn.get("answer_contains", []),
                "rewrite_contains": turn.get("rewrite_contains", []),
                **{key: value for key, value in asdict(score).items()},
                "cost_yuan": chat.result.usage.cost_yuan,
            })
            print(f"{dialogue['id']}#{position} {score.status}")
    return rows


def write_report(rows: list[dict], dialogue_count: int, path: Path = REPORT) -> None:
    total_cost = sum(r["cost_yuan"] for r in rows)
    lines = [
        "# 多轮对话评测报告",
        "",
        f"由 `eval/run_dialogues.py` 生成。样本量：{dialogue_count} 组对话、{len(rows)} 轮，样本量小，只能看大方向。",
        "",
        "回答轮同时要求改写包含关键词、答案和引用正确；判定是偏严的子串匹配，没通过的轮次需要人工复核。",
        "",
        f"按标价估算费用 {total_cost:.4f} 元。",
        "",
        "## 按对话类型",
        "",
        "| 对话类型 | 全部轮次通过的对话 / 对话数 | 通过轮次 / 总轮次 |",
        "| --- | --- | --- |",
    ]
    for kind in sorted({r["dialogue_type"] for r in rows}):
        group = [r for r in rows if r["dialogue_type"] == kind]
        ids = {r["dialogue_id"] for r in group}
        fully = sum(all(r["passed"] for r in group if r["dialogue_id"] == i) for i in ids)
        lines.append(f"| {kind} | {fully}/{len(ids)} | {sum(r['passed'] for r in group)}/{len(group)} |")
    lines += ["", "## 按轮次类别", "", "| 类别 | 通过 / 轮次 |", "| --- | --- |"]
    for kind in sorted({r["kind"] for r in rows}):
        group = [r for r in rows if r["kind"] == kind]
        lines.append(f"| {kind} | {sum(r['passed'] for r in group)}/{len(group)} |")
    rewrites = [r for r in rows if r["rewrite_ok"] is not None]
    rate = f"{sum(r['rewrite_ok'] for r in rewrites)}/{len(rewrites)}" if rewrites else "无"
    lines += ["", f"改写通过率（回答轮）：{rate}", ""]
    failed = [r for r in rows if not r["passed"]]
    lines += [f"## 没有通过的轮次（{len(failed)} 轮）", ""]
    for r in failed:
        lines += [
            f"- `{r['dialogue_id']}` 第 {r['position']} 轮 {r['status']}",
            f"  - 问题：{r['question']}",
            f"  - 改写结果：{r['rewritten'] or '（未改写）'}",
            f"  - 回答前 200 字：{r['answer'][:200] or '（无）'}",
        ]
    if not failed:
        lines.append("无")
    # newline="\n"：固定成 LF，和仓库的换行规则一致。
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dialogues", type=Path, default=DIALOGUES)
    args = parser.parse_args()
    path = args.dialogues
    if not path.exists():
        print(f"找不到 {path}，多轮评测题还没有写好。")
        return 1
    if not questions_are_frozen(path):
        print(f"{path.name} 没有冻结，或和冻结时不一致。改题必须说明原因并更新 {path.with_suffix('.sha256').name}。")
        return 1

    from openai import OpenAI

    from finrag.config import load_settings
    from finrag.retrieval import MANIFEST, load_retriever

    dialogues = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    settings = load_settings()
    reports = json.loads(Path(MANIFEST).read_text(encoding="utf-8"))
    max_year = max(int(report["year"]) for report in reports)
    client = OpenAI(api_key=settings.api_key, base_url=settings.base_url)
    retriever = load_retriever(mode="hybrid", use_rerank=True)

    rows: list[dict] = []
    for dialogue in dialogues:
        rows += run_dialogue(dialogue, retriever, client, settings.model, max_year, reports)

    RESULTS.mkdir(exist_ok=True)
    summary = {"dialogues": len(dialogues), "turns": len(rows), "passed": sum(r["passed"] for r in rows),
               "statuses": dict(Counter(r["status"] for r in rows)),
               "cost_yuan": sum(r["cost_yuan"] for r in rows)}
    (RESULTS / "dialogues.json").write_text(
        json.dumps({"summary": summary, "turns": rows}, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    write_report(rows, len(dialogues))
    print(f"已写入 {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
