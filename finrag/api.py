"""HTTP adapter for the answer module. Importing this module never loads secrets.

Run locally with ``uv run python -m finrag.api``. Tests use create_app with fakes.
"""

import json
import logging
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from finrag.answer import AnswerResult, stream_answer
from finrag.contracts import Retriever

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"
PDF_DIR = ROOT / "data" / "raw"
WEB_FILE = ROOT / "web" / "index.html"
logger = logging.getLogger(__name__)
PUBLIC_ERROR = "回答生成失败，请稍后重试。"

# 限流默认值，可用环境变量覆盖（见 RateLimiter.from_env）。
DEFAULT_PER_IP_LIMIT = 10
DEFAULT_WINDOW_SECONDS = 60
DEFAULT_DAILY_LIMIT = 300
DAY_SECONDS = 24 * 60 * 60


class RateLimiter:
    """保护付费接口的访问频率限制：每个客户端 IP 的滑动窗口 + 全站 24 小时滑动窗口。

    局限：
    - 计数只存在本进程内存里，进程重启后清零。
    - 多进程（如 uvicorn --workers N）或多副本部署时各自独立计数，总额度会被放大 N 倍。
      需要跨进程共享时应改用 Redis 等外部存储。
    - 只有被放行的请求才计数；被拒绝的请求不占用额度。
    - 时间来源 clock 可注入，测试里传入假时钟即可，不需要真的等待。
    """

    def __init__(self, per_ip_limit: int = DEFAULT_PER_IP_LIMIT,
                 window_seconds: float = DEFAULT_WINDOW_SECONDS,
                 daily_limit: int = DEFAULT_DAILY_LIMIT,
                 clock: Callable[[], float] = time.monotonic):
        if per_ip_limit < 1 or window_seconds <= 0 or daily_limit < 1:
            raise ValueError("限流参数必须为正数")
        self.per_ip_limit, self.window_seconds, self.daily_limit = per_ip_limit, window_seconds, daily_limit
        self.clock = clock
        self._ip_hits: dict[str, deque[float]] = {}
        self._day_hits: deque[float] = deque()
        # 同步路由跑在线程池里，多个线程会同时进入，所以要加锁。
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, clock: Callable[[], float] = time.monotonic) -> "RateLimiter":
        return cls(
            per_ip_limit=_env_int("FINRAG_RATE_LIMIT_PER_IP", DEFAULT_PER_IP_LIMIT),
            window_seconds=_env_int("FINRAG_RATE_LIMIT_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS),
            daily_limit=_env_int("FINRAG_DAILY_LIMIT", DEFAULT_DAILY_LIMIT),
            clock=clock,
        )

    def check(self, ip: str) -> tuple[str, int] | None:
        """放行返回 None 并记一次；超限返回 (中文提示, 建议等待秒数)，且不计数。"""
        with self._lock:
            now = self.clock()
            while self._day_hits and now - self._day_hits[0] >= DAY_SECONDS:
                self._day_hits.popleft()
            if len(self._ip_hits) > 256:
                self._sweep(now)
            hits = self._ip_hits.get(ip)
            if hits is not None:
                self._expire(hits, now)
            if hits and len(hits) >= self.per_ip_limit:
                wait = max(1, int(hits[0] + self.window_seconds - now) + 1)
                return f"请求太频繁，请 {wait} 秒后再试。", wait
            if len(self._day_hits) >= self.daily_limit:
                wait = max(1, int(self._day_hits[0] + DAY_SECONDS - now) + 1)
                return "今日提问次数已达上限，请明天再试。", wait
            self._ip_hits.setdefault(ip, deque()).append(now)
            self._day_hits.append(now)
            return None

    def _expire(self, hits: deque[float], now: float) -> None:
        while hits and now - hits[0] >= self.window_seconds:
            hits.popleft()

    def _sweep(self, now: float) -> None:
        # 清掉窗口已过期的 IP，避免字典无限增长。
        for key in list(self._ip_hits):
            self._expire(self._ip_hits[key], now)
            if not self._ip_hits[key]:
                del self._ip_hits[key]


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"环境变量 {name} 必须是正整数") from None
    if value < 1:
        raise ValueError(f"环境变量 {name} 必须是正整数")
    return value


def _client_ip(request: Request) -> str:
    # 只用 TCP 连接的对端地址。不读 X-Forwarded-For：该请求头由客户端随意填写，
    # 信任它等于让攻击者每次换一个假 IP 就能绕过限流。若前面加了反向代理，
    # 所有请求会共用代理的地址，此时全站每日上限仍然生效。
    # main() 也不改 uvicorn 的默认设置：默认只信任来自 127.0.0.1 的转发头，容器内不会生效。
    return request.client.host if request.client else "unknown"


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


def create_app(retriever: Retriever, client, model: str, max_year: int,
               rate_limiter: RateLimiter | None = None) -> FastAPI:
    """Build an app without real clients or index loading.

    rate_limiter 缺省时按环境变量（未设置则用模块常量）创建；测试可传入带假时钟的实例。
    """
    limiter = rate_limiter if rate_limiter is not None else RateLimiter.from_env()
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
    def ask(body: AskRequest, request: Request):
        # 必须在检索和调用模型之前判断，超限的请求不产生任何费用。
        # 格式不合法的请求（422）在此之前就被拒绝，不占用额度。
        limited = limiter.check(_client_ip(request))
        if limited is not None:
            message, wait = limited
            return JSONResponse({"error": "rate_limited", "message": message}, status_code=429,
                                headers={"Retry-After": str(wait)})

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
        host = os.getenv("FINRAG_HOST", "").strip() or "127.0.0.1"
        port = _env_int("FINRAG_PORT", 8000)
        limiter = RateLimiter.from_env()
    except ValueError as error:
        # 消息里只有变量名，没有取值。
        raise SystemExit(f"启动失败：{error}。") from None
    try:
        settings = load_settings()
        # 用评测里效果最好的方案：混合检索 + 重排（eval/report.md）。
        retriever = load_retriever(mode="hybrid", use_rerank=True)
        reports = _read_manifest()
        max_year = max(int(report["year"]) for report in reports)
        client = OpenAI(api_key=settings.api_key, base_url=settings.base_url)
        app = create_app(retriever, client, settings.model, max_year, limiter)
    except ConfigError:
        raise SystemExit("启动失败：缺少有效的 DASHSCOPE_API_KEY，请先配置密钥。") from None
    except IndexNotReady:
        raise SystemExit("启动失败：检索索引缺失或不完整，请先构建切分结果和向量索引。") from None
    except (OSError, ValueError, KeyError, TypeError) as error:
        # 只给出异常类型，方便排查，又不会把路径或配置内容打印出来。
        raise SystemExit(f"启动失败：财报清单、索引或模型配置不可用（{type(error).__name__}），请检查配置。") from None
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
