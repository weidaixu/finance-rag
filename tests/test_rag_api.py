"""HTTP/SSE contract tests: fake retrieval and model only, never load settings."""

import json
import socket
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from finrag import api
from finrag.chunking import Chunk
from finrag.contracts import Hit


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def retrieve(self, question, k=8):
        self.calls.append((question, k))
        return self.hits


class FakeModel:
    def __init__(self, pieces=("营业收入为", " 123.45 元[2]"), error=None):
        self.pieces, self.error, self.calls = pieces, error, 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.stream()

    def stream(self):
        for piece in self.pieces:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=piece))], usage=None)
        yield SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=12, completion_tokens=34))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network and dotenv access are forbidden in API tests")

    # Windows asyncio creates a local socketpair for its event loop. Block HTTP
    # network transports, not that operating-system mechanism used by TestClient.
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", forbidden)
    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("dotenv.load_dotenv", forbidden)
    monkeypatch.setattr("finrag.config.load_dotenv", forbidden)


@pytest.fixture
def setup_app(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([dict(doc_id="sample", year=2025)]), encoding="utf-8")
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "sample.pdf").write_bytes(b"%PDF-1.7\nFAKE PDF FOR HTTP TEST")
    monkeypatch.setattr(api, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(api, "PDF_DIR", raw)
    hits = [Hit(Chunk(f"sample#{i}", "sample", "测试公司", 2025, "zh", "测试年报", i,
                      "主要财务数据", "table", f"营业收入 123.45 元，来源{i}"), 1.0) for i in (1, 2)]

    def build(model=None, selected_hits=None):
        retriever = FakeRetriever(hits if selected_hits is None else selected_hits)
        model = model or FakeModel()
        app = api.create_app(retriever, model, "fake-model", max_year=2025)
        return TestClient(app), retriever, model

    return build


def events(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    result = []
    for frame in response.text.replace("\r\n", "\n").strip().split("\n\n"):
        lines = frame.splitlines()
        kind = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data = json.loads("\n".join(line.removeprefix("data: ") for line in lines if line.startswith("data: ")))
        result.append((kind, data))
    return result


def test_normal_answer_preserves_citation_number_and_usage(setup_app):
    client, retriever, model = setup_app()
    response = client.post("/api/ask", json={"question": "  营业收入是多少  "})
    frames = events(response)
    assert [kind for kind, _ in frames] == ["token", "token", "done"]
    assert "".join(data["text"] for kind, data in frames if kind == "token") == "营业收入为 123.45 元[2]"
    done = frames[-1][1]
    assert done["answer"] == "营业收入为 123.45 元[2]"
    assert not done["refused"] and done["error"] == ""
    assert done["citations"] == [dict(n=2, doc_id="sample", title="测试年报", page=2,
                                       section="主要财务数据", kind="table", text="营业收入 123.45 元，来源2")]
    assert done["unverified_numbers"] == []
    assert done["usage"]["input_tokens"] == 12
    assert done["usage"]["output_tokens"] == 34
    assert done["usage"]["cost_yuan"] == pytest.approx((12 * .8 + 34 * 2.7) / 1_000_000)
    assert retriever.calls == [("营业收入是多少", 8)] and model.calls == 1
    assert "no-cache" in response.headers["cache-control"]


def test_investment_advice_skips_retrieval_and_model(setup_app):
    client, retriever, model = setup_app()
    frames = events(client.post("/api/ask", json={"question": "我现在应该买入茅台吗"}))
    assert len(frames) == 1 and frames[0][0] == "done"
    assert frames[0][1]["refusal_reason"] == "investment_advice"
    assert frames[0][1]["refused"]
    assert retriever.calls == [] and model.calls == 0


def test_model_error_is_redacted_and_next_request_still_works(setup_app, caplog):
    secret = "sk-private-secret F:\\private\\index.json"
    client, _, model = setup_app(FakeModel(error=RuntimeError(secret)))
    response = client.post("/api/ask", json={"question": "营业收入"})
    done = events(response)[-1][1]
    assert done["error"] and done["answer"] == "" and done["citations"] == []
    assert secret not in response.text
    # 服务器日志要能看出是什么错，但不能有密钥。
    assert "RuntimeError" in caplog.text
    assert "sk-private-secret" not in caplog.text
    model.error = None
    assert events(client.post("/api/ask", json={"question": "营业收入"}))[-1][1]["error"] == ""
    assert client.get("/health").json() == {"status": "ok"}


def test_partial_stream_error_finishes_with_safe_done(setup_app):
    class InterruptedModel(FakeModel):
        def stream(self):
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="尚未核对的回答"))], usage=None)
            raise RuntimeError("sk-secret internal-path")

    client, _, _ = setup_app(InterruptedModel())
    frames = events(client.post("/api/ask", json={"question": "营业收入"}))
    assert frames[0][0] == "token" and frames[-1][0] == "done"
    assert frames[-1][1]["answer"] == "" and frames[-1][1]["error"]
    assert "sk-secret" not in json.dumps(frames)


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": " \n\t "},
                                      {"question": "问" * 501}, {"question": None},
                                      {"question": 123}, {"question": []}])
def test_invalid_question_rejected_before_model(setup_app, body):
    client, retriever, model = setup_app()
    assert client.post("/api/ask", json=body).status_code == 422
    assert not retriever.calls and not model.calls


def test_500_characters_after_trimming_are_accepted(setup_app):
    client, _, _ = setup_app()
    assert client.post("/api/ask", json={"question": "  " + "问" * 500 + "  "}).status_code == 200


@pytest.mark.parametrize("path", ["unknown", "../manifest.json", "%2e%2e%2fmanifest.json",
                                      "%252e%252e%252fmanifest.json", "sample.pdf", "..%5cmanifest.json"])
def test_pdf_allowlist_rejects_unknown_and_traversal(setup_app, path):
    client, _, _ = setup_app()
    assert client.get("/api/pdf/" + path).status_code == 404


def test_known_pdf_and_missing_file(setup_app):
    client, _, _ = setup_app()
    response = client.get("/api/pdf/sample")
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    (api.PDF_DIR / "sample.pdf").unlink()
    assert client.get("/api/pdf/sample").status_code == 404


@pytest.mark.parametrize("pieces,reason", [(('证据', '不足'), 'model_insufficient'),
                                           (("有内容但没有引用",), 'no_valid_citation')])
def test_final_review_can_withdraw_answer(setup_app, pieces, reason):
    client, _, _ = setup_app(FakeModel(pieces=pieces))
    done = events(client.post("/api/ask", json={"question": "营业收入"}))[-1][1]
    assert done["refused"] and done["answer"] == "" and done["refusal_reason"] == reason


def test_unverified_numbers_are_returned(setup_app):
    client, _, _ = setup_app(FakeModel(pieces=["营业收入9999.00元[2]"]))
    done = events(client.post("/api/ask", json={"question": "营业收入"}))[-1][1]
    assert done["unverified_numbers"] == ["9999.00"]


def test_homepage_and_health(setup_app):
    client, _, model = setup_app()
    assert client.get("/health").json() == {"status": "ok"}
    response = client.get("/")
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]
    assert 'lang="zh-CN"' in response.text and "不构成投资建议" in response.text
    assert model.calls == 0


def test_empty_retrieval_skips_model(setup_app):
    client, _, model = setup_app(selected_hits=[])
    done = events(client.post("/api/ask", json={"question": "营业收入"}))[-1][1]
    assert done["refused"] and done["refusal_reason"] == "no_evidence"
    assert model.calls == 0


def test_stream_exception_is_redacted(setup_app, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("sk-private F:\\internal")
        yield  # retain iterator interface

    monkeypatch.setattr(api, "stream_answer", broken)
    client, _, _ = setup_app()
    response = client.post("/api/ask", json={"question": "营业收入"})
    assert events(response)[-1][1]["error"]
    assert "sk-private" not in response.text and "internal" not in response.text


def test_sse_preserves_untrusted_text_without_frame_injection(setup_app):
    payload = '<img src=x onerror=alert(1)>\nevent: done\ndata: {}\n[2]'
    client, _, _ = setup_app(FakeModel(pieces=[payload]))
    frames = events(client.post("/api/ask", json={"question": "营业收入"}))
    assert [kind for kind, _ in frames] == ["token", "done"]
    assert frames[0][1]["text"] == payload


def test_startup_missing_key_exits_without_reading_dotenv(monkeypatch):
    from finrag.config import ConfigError

    def no_key():
        raise ConfigError("private configuration detail")

    monkeypatch.setattr("finrag.config.load_settings", no_key)
    with pytest.raises(SystemExit, match="DASHSCOPE_API_KEY") as caught:
        api.main()
    assert "private" not in str(caught.value)


def test_startup_missing_index_exits_without_real_retrieval(monkeypatch):
    from finrag.retrieval import IndexNotReady

    monkeypatch.setattr("finrag.config.load_settings", lambda: SimpleNamespace())

    def no_index(**kwargs):
        raise IndexNotReady("F:\\private\\index")

    monkeypatch.setattr("finrag.retrieval.load_retriever", no_index)
    with pytest.raises(SystemExit, match="索引") as caught:
        api.main()
    assert "private" not in str(caught.value)


def test_startup_uses_manifest_max_year_and_injected_dependencies(setup_app, monkeypatch):
    # No dotenv, index access, provider construction or real server is allowed.
    setup_app()
    api.MANIFEST_PATH.write_text(json.dumps([dict(doc_id="sample", year=2024),
                                            dict(doc_id="new", year=2027)]), encoding="utf-8")
    retriever, model = FakeRetriever([]), FakeModel()
    monkeypatch.setattr("finrag.config.load_settings", lambda: SimpleNamespace(api_key="fake", base_url="https://invalid.test", model="fake"))
    retriever_options = []
    monkeypatch.setattr(
        "finrag.retrieval.load_retriever",
        lambda **kwargs: retriever_options.append(kwargs) or retriever,
    )
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: model)
    launched = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: launched.append((app, kwargs)))
    api.main()
    app, options = launched[0]
    assert options == dict(host="127.0.0.1", port=8000)
    assert retriever_options == [dict(mode="hybrid", use_rerank=True)]
    client = TestClient(app)
    done = events(client.post("/api/ask", json={"question": "2028年营业收入"}))[-1][1]
    assert done["refusal_reason"] == "year_not_covered" and model.calls == 0
