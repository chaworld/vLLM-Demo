"""ChatCompletionClient 單元測試:驗證 thinking 強制關閉與上游錯誤轉譯。"""

from __future__ import annotations

import pytest
import requests

from app.config import Settings
from app.llm_client import ChatCompletionClient, UpstreamError, strip_thinking

from .conftest import FakeResponse, FakeSession, make_completion


def test_payload_always_disables_thinking(client: ChatCompletionClient) -> None:
    payload = client.build_upstream_payload({"messages": [{"role": "user", "content": "hi"}]})
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_payload_ignores_client_attempt_to_enable_thinking(client: ChatCompletionClient) -> None:
    payload = client.build_upstream_payload(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "chat_template_kwargs": {"enable_thinking": True},
        }
    )
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_payload_pins_model_and_forces_non_streaming(client: ChatCompletionClient) -> None:
    payload = client.build_upstream_payload(
        {"messages": [{"role": "user", "content": "hi"}], "model": "some-other-model", "stream": True}
    )
    assert payload["model"] == "qwen3.5-0.8b"
    assert payload["stream"] is False


def test_payload_accepts_both_max_token_field_names(client: ChatCompletionClient) -> None:
    legacy = client.build_upstream_payload({"messages": [], "max_tokens": 64})
    modern = client.build_upstream_payload({"messages": [], "max_completion_tokens": 128})
    fallback = client.build_upstream_payload({"messages": []})
    assert (legacy["max_tokens"], modern["max_tokens"], fallback["max_tokens"]) == (64, 128, 256)


def test_payload_drops_unknown_fields(client: ChatCompletionClient) -> None:
    payload = client.build_upstream_payload({"messages": [], "logit_bias": {"1": 2}, "top_p": 0.9})
    assert "logit_bias" not in payload
    assert payload["top_p"] == 0.9


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<think>先想一下</think>答案是 4", "答案是 4"),
        ("<think>\n多行\n推理\n</think>\n\n最終答案", "最終答案"),
        ("沒有推理標籤的純文字", "沒有推理標籤的純文字"),
        ("", ""),
    ],
)
def test_strip_thinking_removes_reasoning_blocks(raw: str, expected: str) -> None:
    assert strip_thinking(raw) == expected


def test_strip_thinking_removes_unclosed_block() -> None:
    assert strip_thinking("<think>推理被截斷\n\n最終答案") == "最終答案"


def test_sanitize_removes_reasoning_field(client: ChatCompletionClient) -> None:
    completion = client.sanitize_completion(make_completion("答案", reasoning="內部推理"))
    message = completion["choices"][0]["message"]
    assert "reasoning_content" not in message
    assert message["content"] == "答案"


def test_create_chat_completion_sends_sanitized_result(
    client: ChatCompletionClient, fake_session: FakeSession
) -> None:
    fake_session._responses.append(FakeResponse(make_completion("<think>略</think>你好")))
    result = client.create_chat_completion({"messages": [{"role": "user", "content": "hi"}]})
    assert result["choices"][0]["message"]["content"] == "你好"
    assert fake_session.last_payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_upstream_http_error_raises(client: ChatCompletionClient, fake_session: FakeSession) -> None:
    fake_session._responses.append(FakeResponse({"error": "boom"}, status_code=500))
    with pytest.raises(UpstreamError) as excinfo:
        client.create_chat_completion({"messages": []})
    assert excinfo.value.status_code == 502


def test_connection_failure_raises_service_unavailable(settings: Settings) -> None:
    class BrokenSession:
        def request(self, *_args: object, **_kwargs: object) -> None:
            raise requests.ConnectionError("connection refused")

    client = ChatCompletionClient(settings, session=BrokenSession())
    with pytest.raises(UpstreamError) as excinfo:
        client.list_models()
    assert excinfo.value.status_code == 503
