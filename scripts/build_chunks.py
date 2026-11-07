"""解析 data/raw/ 里的 PDF，把片段写到 data/index/chunks.jsonl。不调用模型，不产生费用。"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finrag.chunking import build_chunks  # noqa: E402
from finrag.parsing import parse_pdf  # noqa: E402

OUTPUT = ROOT / "data" / "index" / "chunks.jsonl"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    reports = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    with OUTPUT.open("w", encoding="utf-8") as file:
        for report in reports:
            started = time.perf_counter()
            blocks = parse_pdf(ROOT / "data" / "raw" / f"{report['doc_id']}.pdf")
            chunks = build_chunks(blocks, report)
            for chunk in chunks:
                file.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
            tables = sum(chunk.kind == "table" for chunk in chunks)
            print(
                f"{report['doc_id']}: {len(chunks)} 段，其中表格 {tables} 段，"
                f"用时 {time.perf_counter() - started:.0f} 秒"
            )


if __name__ == "__main__":
    main()
