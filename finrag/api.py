"""HTTP adapter for the answer module. Importing this module never loads secrets.

Run locally with ``uv run python -m finrag.api``. Tests use create_app with fakes.
"""

import json
import logging
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from finrag.answer import AnswerResult, stream_answer
from finrag.contracts import Retriever

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"
PDF_DIR = ROOT / "data" / "raw"
WEB_FILE = ROOT / "web" / "index.html"
logger = logging.getLogger(__name__)
PUBLIC_ERROR = "回答生成失败，请稍后重试。"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500, strict=True)

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value):
        return value.strip() if isinstance(value, str) else value


def _redact(text: str) -> str:
    """服务器日志要能排查问题（比如 401），但不能写入密钥。浏览器只会收到 PUBLIC_ERROR。"""
    return re.sub(r"sk-[A-Za-z0-9_\-]+", "sk-***", text)


def _read_manifest() -> list[dict]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _event(name: str, payload: dict) -> str:
    # json.dumps escapes embedded newlines, so source text cannot inject SSE frames.
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _done(result: AnswerResult) -> dict:
    failed = bool(result.error)
    if failed:
        logger.error("问答流程失败：%s", _redact(result.error))
    citations = []
    if not failed and not result.refused:
        for number in result.citations:
            chunk = result.sources[number - 1].chunk
            citations.append(dict(n=number, doc_id=chunk.doc_id, title=chunk.title,
                                  page=chunk.page, section=chunk.section,
                                  kind=chunk.kind, text=chunk.text))
    return dict(
        answer="" if failed or result.refused else result.answer,
        refused=result.refused,
        refusal_reason=result.refusal_reason,
        citations=citations,
        unverified_numbers=[] if failed or result.refused else result.unverified_numbers,
        usage=dict(input_tokens=result.usage.input_tokens,
                   output_tokens=result.usage.output_tokens, cost_yuan=result.usage.cost_yuan),
        error=PUBLIC_ERROR if failed else "",
    )


def create_app(retriever: Retriever, client, model: str, max_year: int) -> FastAPI:
    """Build an app without configuration reads, real clients or index loading."""
    app = FastAPI(title="财报问答", docs_url=None, redoc_url=None)
    raw_dir = PDF_DIR.resolve()
    # Resolve only manifest entries, never a path assembled from route input.
    pdfs = {}
    for report in _read_manifest():
        doc_id = report["doc_id"]
        path = (raw_dir / f"{doc_id}.pdf").resolve()
        if path.parent == raw_dir:
            pdfs[doc_id] = path

    @app.get("/")
    def home():
        return FileResponse(WEB_FILE, media_type="text/html")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/pdf/{doc_id}")
    def pdf(doc_id: str):
        path = pdfs.get(doc_id)
        if path is None or not path.is_file() or path.resolve().parent != raw_dir:
            raise HTTPException(404, "找不到这份财报")
        return FileResponse(path, media_type="application/pdf", filename=f"{doc_id}.pdf",
                            content_disposition_type="inline")

    @app.post("/api/ask")
    def ask(body: AskRequest):
        def generate():
            try:
                for item in stream_answer(body.question, retriever, client, model, max_year):
                    if isinstance(item, str):
                        yield _event("token", {"text": item})
                    elif isinstance(item, AnswerResult):
                        yield _event("done", _done(item))
                        return
                # A missing final result is a protocol failure, not a completed answer.
                raise RuntimeError("Missing final answer result")
            except Exception as error:
                logger.error("问答响应流异常终止：%s", _redact(f"{type(error).__name__}: {error}"))
                yield _event("done", _done(AnswerResult(question=body.question, error="stream_failed")))

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def main() -> None:
    """Real startup is deliberately separate from the injectable, offline app factory."""
    import uvicorn
    from openai import OpenAI

    from finrag.config import ConfigError, load_settings
    from finrag.retrieval import IndexNotReady, load_retriever

    try:
        settings = load_settings()
        # 用评测里效果最好的方案：混合检索 + 重排（eval/report.md）。
        retriever = load_retriever(mode="hybrid", use_rerank=True)
        reports = _read_manifest()
        max_year = max(int(report["year"]) for report in reports)
        client = OpenAI(api_key=settings.api_key, base_url=settings.base_url)
        app = create_app(retriever, client, settings.model, max_year)
    except ConfigError:
        raise SystemExit("启动失败：缺少有效的 DASHSCOPE_API_KEY，请先配置密钥。") from None
    except IndexNotReady:
        raise SystemExit("启动失败：检索索引缺失或不完整，请先构建切分结果和向量索引。") from None
    except (OSError, ValueError, KeyError, TypeError) as error:
        # 只给出异常类型，方便排查，又不会把路径或配置内容打印出来。
        raise SystemExit(f"启动失败：财报清单、索引或模型配置不可用（{type(error).__name__}），请检查配置。") from None
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
