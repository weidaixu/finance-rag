"""检查评测题的格式，并核对每条 quote 是否真的出现在 PDF 的对应页上。

这个脚本只证明「引文在那一页」，不能证明题目出得合理，也不能证明答案理解正确。
后两项仍然要人工抽查。

用法：
    uv run python eval/check_gold.py
    uv run python eval/check_gold.py --questions eval/questions_v2.jsonl --existing eval/questions.jsonl
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finrag.text import normalize  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions.jsonl"
ANSWER_TYPES = {"table_number", "text_fact", "english", "multi_page", "cross_language", "multi_company"}
REFUSAL_TYPES = {"company_not_covered", "year_not_covered", "investment_advice", "fact_not_disclosed"}

# 题目和引用页原文连续相同的长度超过这个值，就提示「措辞贴近原文」。
# 照抄原文的题对关键词检索特别有利，会让评测分数偏高。
# 中文取 16：「归属于上市公司股东的净利润」这类标准科目名有 13 个字，用户本来就会照着说，不算照抄。
# 英文去掉空格后字母更多，所以阈值更高。
COPY_LIMIT_CJK = 16
COPY_LIMIT_LATIN = 30


def squeeze(text: str) -> str:
    """去掉所有空白并统一简体，避免 PDF 换行或繁简差异造成误判。"""
    return re.sub(r"\s+", "", normalize(text))


def check_format(item: dict, doc_ids: set[str]) -> list[str]:
    errors: list[str] = []
    if not item.get("id") or not str(item.get("question", "")).strip():
        errors.append("缺少 id 或 question")
    question_type = item.get("type")
    if item.get("should_refuse") is True:
        if question_type not in REFUSAL_TYPES:
            errors.append(f"拒答题的 type 不合法：{question_type}")
        if item.get("gold"):
            errors.append("拒答题不应该有 gold")
        return errors
    if item.get("should_refuse") is not False:
        errors.append("should_refuse 必须是 true 或 false")
    if question_type not in ANSWER_TYPES:
        errors.append(f"回答题的 type 不合法：{question_type}")
    if not item.get("answer_contains"):
        errors.append("回答题必须有 answer_contains")
    gold = item.get("gold")
    if not gold:
        errors.append("回答题必须有 gold")
        return errors
    for entry in gold:
        if entry.get("doc_id") not in doc_ids:
            errors.append(f"未知的 doc_id：{entry.get('doc_id')}")
        if not isinstance(entry.get("page"), int) or entry["page"] < 1:
            errors.append(f"page 必须是从 1 开始的整数：{entry.get('page')}")
        if not str(entry.get("quote", "")).strip():
            errors.append("gold 里缺少 quote")
    return errors


def check_quotes(item: dict, documents: dict[str, pymupdf.Document]) -> list[str]:
    """引文必须在对应页上；answer_contains 也必须能在这些页上找到，否则标准答案可能是编的。"""
    errors: list[str] = []
    page_text = ""
    for entry in item.get("gold") or []:
        document = documents.get(entry.get("doc_id"))
        page = entry.get("page")
        if document is None or not isinstance(page, int) or not 1 <= page <= len(document):
            errors.append(f"页码超出范围：{entry.get('doc_id')} 第 {page} 页")
            continue
        text = squeeze(document[page - 1].get_text())
        page_text += text
        if squeeze(str(entry.get("quote", ""))) not in text:
            errors.append(f"引文不在 {entry['doc_id']} 第 {page} 页：{str(entry.get('quote'))[:40]}")
    for expected in item.get("answer_contains") or []:
        if squeeze(str(expected)) not in page_text:
            errors.append(f"answer_contains 不在引用页上：{expected}")
    return errors


def check_structure(item: dict, companies: dict[str, str]) -> list[str]:
    """多页题至少引用两页，多公司题至少涉及两家公司，否则题型名不副实。"""
    gold = item.get("gold") or []
    if item.get("type") == "multi_page" and len({(g.get("doc_id"), g.get("page")) for g in gold}) < 2:
        return ["multi_page 题至少要引用两个不同的页面"]
    if item.get("type") == "multi_company" and len({companies.get(g.get("doc_id")) for g in gold}) < 2:
        return ["multi_company 题至少要涉及两家不同的公司"]
    return []


def longest_common_run(a: str, b: str) -> int:
    """两段文字最长的连续相同部分有多长。用动态规划，只保留上一行，内存是 O(len(b))。"""
    best = 0
    previous = [0] * (len(b) + 1)
    for char in a:
        current = [0] * (len(b) + 1)
        for j, other in enumerate(b, start=1):
            if char == other:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def copies_source(item: dict, documents: dict[str, pymupdf.Document]) -> bool:
    """题目是否照抄了引用页的原文。只是提示，不算不通过。"""
    question = squeeze(str(item.get("question", ""))).lower()
    if not question or item.get("should_refuse"):
        return False
    limit = COPY_LIMIT_CJK if re.search(r"[一-鿿]", question) else COPY_LIMIT_LATIN
    for entry in item.get("gold") or []:
        document = documents.get(entry.get("doc_id"))
        page = entry.get("page")
        if document is None or not isinstance(page, int) or not 1 <= page <= len(document):
            continue
        if longest_common_run(question, squeeze(document[page - 1].get_text()).lower()) >= limit:
            return True
    return False


def read_items(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, default=QUESTIONS, help="要检查的题目文件")
    parser.add_argument("--existing", type=Path, nargs="*", default=[], help="已有的题目文件，用来查重")
    args = parser.parse_args()

    if not args.questions.exists():
        print(f"找不到 {args.questions}")
        return 1
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    documents = {r["doc_id"]: pymupdf.open(ROOT / "data" / "raw" / f"{r['doc_id']}.pdf") for r in manifest}
    companies = {r["doc_id"]: r["company"] for r in manifest}
    items = read_items(args.questions)

    existing = [item for path in args.existing for item in read_items(path)]
    existing_ids = {item.get("id") for item in existing}
    existing_questions = {squeeze(str(item.get("question", ""))) for item in existing}

    failures = 0
    copied: list[str] = []
    seen: set[str] = set()
    for item in items:
        errors = check_format(item, set(documents))
        if item.get("id") in seen:
            errors.append("id 重复")
        if item.get("id") in existing_ids:
            errors.append("id 和已有题目重复")
        if squeeze(str(item.get("question", ""))) in existing_questions:
            errors.append("题目和已有题目重复")
        seen.add(item.get("id"))
        if not item.get("should_refuse"):
            errors.extend(check_quotes(item, documents))
            errors.extend(check_structure(item, companies))
            if copies_source(item, documents):
                copied.append(item.get("id"))
        if errors:
            failures += 1
            print(f"[不通过] {item.get('id')}：" + "；".join(errors))

    answerable = sum(not item.get("should_refuse") for item in items)
    print(f"\n共 {len(items)} 题，{failures} 题不通过")
    print("类型分布：", dict(Counter(item.get("type") for item in items)))
    print("拒答题：", sum(bool(item.get("should_refuse")) for item in items))
    print(f"措辞贴近原文（提示，不算不通过）：{len(copied)}/{answerable} 道回答题 {copied}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
