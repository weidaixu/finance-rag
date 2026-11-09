"""运行评测，生成 eval/report.md 和 eval/results/ 里的逐题明细。

只评检索（BM25 不需要密钥，也不产生费用）：
    uv run python eval/run_eval.py --modes bm25

对比多种检索方式（需要先建好向量）：
    uv run python eval/run_eval.py --modes bm25,vector,hybrid

连答案一起评（调用模型，会产生费用），检索对比和答案结果写进同一份报告：
    uv run python eval/run_eval.py --modes bm25,vector,hybrid,hybrid+rerank --answers hybrid+rerank
"""

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finrag.answer import AnswerResult, stream_answer  # noqa: E402
from finrag.contracts import Hit  # noqa: E402
from finrag.text import normalize  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions.jsonl"
REPORT = ROOT / "eval" / "report.md"
RESULTS = ROOT / "eval" / "results"
CUTOFFS = (1, 3, 8)
_NOT_DISCLOSED = re.compile(r"证据不足|(未|没有|并未)(单独|单列)?(披露|列示|提供)|not\s+(separately\s+|specifically\s+)?disclos|does\s+not\s+disclose", re.IGNORECASE)


def questions_are_frozen(path: Path = QUESTIONS) -> bool:
    """题目经用户抽查后冻结：内容变了就拒绝运行，防止为了分数悄悄改题。

    每份题目文件旁边都有同名的 .sha256 文件，比如 questions_v2.jsonl 对应 questions_v2.sha256。
    """
    hash_file = path.with_suffix(".sha256")
    if not hash_file.exists():
        return False
    expected = hash_file.read_text(encoding="utf-8").split()[0]
    return hashlib.sha256(path.read_bytes()).hexdigest() == expected


def load_questions(paths: list[Path]) -> list[dict]:
    """读取多份题目文件，每题记下来自哪份（set），id 不能重复。"""
    items: list[dict] = []
    seen: set[str] = set()
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item["id"] in seen:
                raise ValueError(f"题目 id 重复：{item['id']}")
            seen.add(item["id"])
            items.append({**item, "set": path.stem})
    return items


def squeeze(text: str) -> str:
    """比较答案时忽略空白、千分位逗号和繁简差异。"""
    return re.sub(r"[\s,，]+", "", normalize(text)).lower()


def gold_pages(item: dict) -> set[tuple[str, int]]:
    return {(entry["doc_id"], entry["page"]) for entry in item.get("gold") or []}


def first_gold_rank(hits: list[Hit], gold: set[tuple[str, int]]) -> int | None:
    """第一条命中标准页面的结果排第几（从 1 开始），没有命中时返回 None。"""
    for position, hit in enumerate(hits, start=1):
        if (hit.chunk.doc_id, hit.chunk.page) in gold:
            return position
    return None


def covers_all_gold(hits: list[Hit], gold: set[tuple[str, int]]) -> bool:
    """多页题要找齐所有页面，答案才可能完整。"""
    return gold <= {(hit.chunk.doc_id, hit.chunk.page) for hit in hits}


def answer_is_correct(answer: str, expected: list[str]) -> bool:
    """所有关键内容都出现才算对。这是偏严的近似：答案换了说法也会被判错，要人工复核。"""
    text = squeeze(answer)
    return bool(expected) and all(squeeze(str(item)) in text for item in expected)


def citation_is_correct(result: AnswerResult, gold: set[tuple[str, int]], expected: list[str]) -> bool:
    """引用指向标准页面，或者引用的片段确实含有答案。

    同一个数字常出现在多页（如营业收入出现在摘要和财务报表里），题目只标了其中一页，
    引用另一页同样是真实证据，不应该判错。
    """
    cited = [result.sources[number - 1] for number in result.citations]
    if any((hit.chunk.doc_id, hit.chunk.page) in gold for hit in cited):
        return True
    text = squeeze(" ".join(hit.chunk.text for hit in cited))
    return any(squeeze(str(item)) in text for item in expected)


def answer_in_hits(hits: list[Hit], expected: list[str]) -> bool:
    """答案的关键内容是否全部出现在检索结果里。比标准页命中更接近模型实际能看到的证据。"""
    text = squeeze(" ".join(hit.chunk.text for hit in hits))
    return bool(expected) and all(squeeze(str(item)) in text for item in expected)


@dataclass
class AnswerScore:
    status: str  # correct / partial_answer / wrong_answer / wrong_citation / wrongly_refused / correctly_refused / should_have_refused / manual_review / error
    passed: bool


def score_answer(item: dict, result: AnswerResult) -> AnswerScore:
    if result.error:
        return AnswerScore("error", False)
    if item["should_refuse"]:
        if result.refused:
            return AnswerScore("correctly_refused", True)
        # 回答「年报未披露」其实也是正确的拒绝，但脚本判断不了它有没有同时给出数字，所以不自动算通过。
        if _NOT_DISCLOSED.search(result.answer):
            return AnswerScore("manual_review", False)
        return AnswerScore("should_have_refused", False)
    if result.refused:
        return AnswerScore("wrongly_refused", False)
    # 回答题的每一部分在资料里都有依据。回答里出现“证据不足”，说明有一部分没答或在否定自己给出的数字，
    # 即使标准答案字符串都出现了，也不能算完整答对。
    if "证据不足" in result.answer:
        return AnswerScore("partial_answer", False)
    if not answer_is_correct(result.answer, item["answer_contains"]):
        return AnswerScore("wrong_answer", False)
    if not citation_is_correct(result, gold_pages(item), item["answer_contains"]):
        return AnswerScore("wrong_citation", False)
    return AnswerScore("correct", True)


def evaluate_retrieval(items: list[dict], retriever, k: int) -> list[dict]:
    rows = []
    for item in items:
        if item["should_refuse"]:
            continue
        gold = gold_pages(item)
        hits = retriever.retrieve(item["question"], k=k)
        rows.append(
            {
                "id": item["id"],
                "set": item.get("set", ""),
                "type": item["type"],
                "question": item["question"],
                "rank": first_gold_rank(hits, gold),
                "all_pages": covers_all_gold(hits, gold),
                "answer_found": answer_in_hits(hits, item["answer_contains"]),
                "top": [f"{hit.chunk.doc_id} p{hit.chunk.page}" for hit in hits[:3]],
                "gold": sorted(f"{doc} p{page}" for doc, page in gold),
            }
        )
    return rows


def summarize_retrieval(rows: list[dict]) -> dict:
    size = len(rows)
    summary = {"n": size}
    for cutoff in CUTOFFS:
        summary[f"hit@{cutoff}"] = sum(r["rank"] is not None and r["rank"] <= cutoff for r in rows) / size if size else 0
    summary["mrr"] = sum(1 / r["rank"] for r in rows if r["rank"]) / size if size else 0
    summary["all_pages"] = sum(r["all_pages"] for r in rows) / size if size else 0
    summary["answer_found"] = sum(r["answer_found"] for r in rows) / size if size else 0
    return summary


def evaluate_answers(items: list[dict], retriever, client, model: str, max_year: int) -> list[dict]:
    rows = []
    for item in items:
        *_, result = stream_answer(item["question"], retriever, client, model, max_year)
        score = score_answer(item, result)
        rows.append(
            {
                "id": item["id"],
                "set": item.get("set", ""),
                "type": item["type"],
                "question": item["question"],
                "status": score.status,
                "passed": score.passed,
                "answer": result.answer,
                "refusal_reason": result.refusal_reason,
                "error": result.error,
                "expected": item["answer_contains"],
                "gold": sorted(f"{doc} p{page}" for doc, page in gold_pages(item)),
                "cited": [
                    f"{result.sources[n - 1].chunk.doc_id} p{result.sources[n - 1].chunk.page}"
                    for n in result.citations
                ],
                "unverified_numbers": result.unverified_numbers,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "cost_yuan": result.usage.cost_yuan,
            }
        )
        print(f"{item['id']} {score.status}")
    return rows


def write_report(retrieval: dict[str, list[dict]], answers: dict[str, list[dict]]) -> None:
    lines = [
        "# 评测报告",
        "",
        "由 `eval/run_eval.py` 生成，数字来自真实运行。样本量小，只能看大方向。",
        "",
        "答案判定是偏严的子串匹配：换了说法的正确答案也会被判错，`manual_review` 的题要人工判断，所以没通过的题都要人工复核。",
        "",
    ]
    lines += [
        "## 检索",
        "",
        "Hit@k 和 MRR 按标准页计算。同一数字可能出现在多页，而题目只标了部分页面，所以它们偏严；「答案在前 8 条」看的是证据内容，较短的答案可能偶然命中，所以偏松。两者要一起看。",
        "",
        "| 方式 | 题数 | Hit@1 | Hit@3 | Hit@8 | MRR | 找齐全部页面 | 答案在前 8 条 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    sets = sorted({r.get("set", "") for rows in retrieval.values() for r in rows})
    for name, rows in retrieval.items():
        # 有多份题目文件时，先写合计，再分别写每份，方便和旧结果对比。
        groups = [(name, rows)]
        if len(sets) > 1:
            groups += [(f"{name}（{s}）", [r for r in rows if r.get("set") == s]) for s in sets]
        for label, group in groups:
            s = summarize_retrieval(group)
            lines.append(
                f"| {label} | {s['n']} | {s['hit@1']:.0%} | {s['hit@3']:.0%} | {s['hit@8']:.0%} | {s['mrr']:.3f} | {s['all_pages']:.0%} | {s['answer_found']:.0%} |"
            )
    for name, rows in retrieval.items():
        missed = [r for r in rows if r["rank"] is None or not r["answer_found"]]
        lines += ["", f"### {name} 没有命中标准页或答案不全的题（{len(missed)} 道）", ""]
        lines += [
            f"- `{r['id']}` {r['type']}：{r['question']}；标准页 {r['gold']}，名次 {r['rank']}，答案在前 8 条 {r['answer_found']}，实际前 3 条 {r['top']}"
            for r in missed
        ] or ["无"]

    for name, rows in answers.items():
        passed = sum(r["passed"] for r in rows)
        lines += ["", f"## 答案：{name}", "", f"通过 {passed}/{len(rows)}，按标价估算费用 {sum(r['cost_yuan'] for r in rows):.4f} 元。", ""]
        answer_sets = sorted({r.get("set", "") for r in rows})
        if len(answer_sets) > 1:
            lines += ["| 题目文件 | 通过 / 题数 |", "| --- | --- |"]
            for s in answer_sets:
                group = [r for r in rows if r.get("set") == s]
                lines.append(f"| {s} | {sum(r['passed'] for r in group)}/{len(group)} |")
            lines.append("")
        lines += ["| 类型 | 通过 / 题数 |", "| --- | --- |"]
        for kind in sorted({r["type"] for r in rows}):
            group = [r for r in rows if r["type"] == kind]
            lines.append(f"| {kind} | {sum(r['passed'] for r in group)}/{len(group)} |")
        failed = [r for r in rows if not r["passed"]]
        lines += ["", f"### 没有通过的题（{len(failed)} 道）", ""]
        lines += [
            f"- `{r['id']}` {r['status']}：{r['question']}；期望 {r['expected']}，标准页 {r['gold']}，引用 {r['cited']}"
            for r in failed
        ] or ["无"]
        flagged = [r for r in rows if r["unverified_numbers"]]
        if flagged:
            lines += ["", "### 引用原文里找不到的数字", ""]
            lines += [f"- `{r['id']}`：{r['unverified_numbers']}" for r in flagged]
    # newline="\n"：Windows 默认会把 \n 写成 \r\n，固定成 LF，和仓库的换行规则一致。
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", default="bm25", help="逗号分隔：bm25,vector,hybrid，加 +rerank 表示再重排，如 hybrid+rerank")
    parser.add_argument("--rerank", action="store_true", help="在每种方式后面加重排")
    parser.add_argument("--answers", default="", help="逗号分隔，对哪几种方式评答案（会调用模型产生费用），如 hybrid+rerank")
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument(
        "--questions",
        default="eval/questions.jsonl",
        help="逗号分隔的题目文件，每份都必须已冻结，如 eval/questions.jsonl,eval/questions_v2.jsonl",
    )
    args = parser.parse_args()

    paths = [ROOT / part.strip() for part in args.questions.split(",") if part.strip()]
    for path in paths:
        if not path.exists():
            print(f"找不到 {path}，评测题还没有写好")
            return 1
        if not questions_are_frozen(path):
            print(f"{path.name} 没有冻结，或和冻结时不一致。改题必须说明原因并更新 {path.with_suffix('.sha256').name}。")
            return 1

    from finrag.retrieval import MANIFEST, load_retriever

    items = load_questions(paths)
    RESULTS.mkdir(exist_ok=True)
    retrieval_rows: dict[str, list[dict]] = {}
    answer_rows: dict[str, list[dict]] = {}

    for name in args.modes.split(","):
        # 写成 hybrid+rerank 表示这种方式后面加重排，这样一次运行就能把几种方案放进同一张表。
        mode, _, extra = name.partition("+")
        use_rerank = args.rerank or extra == "rerank"
        name = f"{mode}+rerank" if use_rerank else mode
        retriever = load_retriever(mode=mode, use_rerank=use_rerank)
        retrieval_rows[name] = evaluate_retrieval(items, retriever, args.k)
        print(name, summarize_retrieval(retrieval_rows[name]))

        if name in {item.strip() for item in args.answers.split(",") if item.strip()}:
            from openai import OpenAI

            from finrag.config import load_settings

            settings = load_settings()
            reports = json.loads(MANIFEST.read_text(encoding="utf-8"))
            answer_rows[name] = evaluate_answers(
                items,
                retriever,
                OpenAI(api_key=settings.api_key, base_url=settings.base_url),
                settings.model,
                max(report["year"] for report in reports),
            )

        output = {"retrieval": retrieval_rows[name], "answers": answer_rows.get(name, [])}
        (RESULTS / f"{name}.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )

    write_report(retrieval_rows, answer_rows)
    print(f"已写入 {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
