"""检查评测题的格式，并核对每条 quote 是否真的出现在 PDF 的对应页上。

这个脚本只证明「引文在那一页」，不能证明题目出得合理，也不能证明答案理解正确。
后两项仍然要人工抽查。

用法：uv run python eval/check_gold.py
"""

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
ANSWER_TYPES = {"table_number", "text_fact", "english", "multi_page"}
REFUSAL_TYPES = {"company_not_covered", "year_not_covered", "investment_advice", "fact_not_disclosed"}


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


def main() -> int:
    if not QUESTIONS.exists():
        print(f"找不到 {QUESTIONS}")
        return 1
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    documents = {r["doc_id"]: pymupdf.open(ROOT / "data" / "raw" / f"{r['doc_id']}.pdf") for r in manifest}
    items = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]

    failures = 0
    seen: set[str] = set()
    for item in items:
        errors = check_format(item, set(documents))
        if item.get("id") in seen:
            errors.append("id 重复")
        seen.add(item.get("id"))
        if not item.get("should_refuse"):
            errors.extend(check_quotes(item, documents))
        if errors:
            failures += 1
            print(f"[不通过] {item.get('id')}：" + "；".join(errors))

    print(f"\n共 {len(items)} 题，{failures} 题不通过")
    print("类型分布：", dict(Counter(item.get("type") for item in items)))
    print("拒答题：", sum(bool(item.get("should_refuse")) for item in items))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
