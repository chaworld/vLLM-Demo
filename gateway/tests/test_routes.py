"""HTTP 路由測試:健康檢查、模型清單、對話補全與監控端點。"""

from __future__ import annotations

import json

from .conftest import FakeResponse, FakeSession, make_completion


def test_healthz_does_not_touch_upstream(flask_client, fake_session: FakeSession) -> None:
    response = flask_client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
    assert fake_session.calls == []


def test_readyz_reports_upstream_models(flask_client, fake_session: FakeSession) -> None:
    fake_session._responses.append(FakeResponse({"data": [{"id": "qwen3.5-0.8b"}]}))
    response = flask_client.get("/readyz")
    assert response.status_code == 200
    assert response.get_json()["upstream_models"] == ["qwen3.5-0.8b"]


def test_readyz_returns_503_when_upstream_fails(flask_client, fake_session: FakeSession) -> None:
    fake_session._responses.append(FakeResponse({"error": "down"}, status_code=503))
    assert flask_client.get("/readyz").status_code == 503


def test_models_exposes_single_pinned_model(flask_client) -> None:
    data = flask_client.get("/v1/models").get_json()["data"]
    assert [item["id"] for item in data] == ["qwen3.5-0.8b"]


def test_chat_completion_returns_clean_content(flask_client, fake_session: FakeSession) -> None:
    fake_session._responses.append(FakeResponse(make_completion("<think>略</think>4", reasoning="1+3")))
    response = flask_client.post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "1+3=?"}]}
    )
    message = response.get_json()["choices"][0]["message"]
    assert response.status_code == 200
    assert message["content"] == "4"
    assert "reasoning_content" not in message


def test_chat_completion_rejects_empty_messages(flask_client) -> None:
    assert flask_client.post("/v1/chat/completions", json={"messages": []}).status_code == 400


def test_chat_completion_returns_sse_when_stream_requested(
    flask_client, fake_session: FakeSession
) -> None:
    fake_session._responses.append(FakeResponse(make_completion("你好")))
    response = flask_client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
    )
    body = response.get_data(as_text=True)
    payloads = [line[len("data: ") :] for line in body.splitlines() if line.startswith("data: ")]

    assert response.mimetype == "text/event-stream"
    assert payloads[-1] == "[DONE]"
    assert json.loads(payloads[0])["choices"][0]["delta"]["content"] == "你好"


def test_upstream_failure_returns_openai_error_shape(flask_client, fake_session: FakeSession) -> None:
    fake_session._responses.append(FakeResponse({"error": "boom"}, status_code=500))
    response = flask_client.post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 502
    assert response.get_json()["error"]["type"] == "upstream_error"


def test_metrics_accumulate_requests_and_tokens(flask_client, fake_session: FakeSession) -> None:
    fake_session._responses.append(FakeResponse(make_completion("你好")))
    flask_client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
    snapshot = flask_client.get("/metrics").get_json()

    assert snapshot["requests_total"] >= 1
    assert snapshot["prompt_tokens_total"] == 11
    assert snapshot["completion_tokens_total"] == 7


def test_request_id_is_echoed_back(flask_client) -> None:
    response = flask_client.get("/healthz", headers={"X-Request-ID": "trace-abc"})
    assert response.headers["X-Request-ID"] == "trace-abc"
