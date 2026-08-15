"""測試共用夾具:以假的 HTTP session 取代真實上游,讓單元測試不需啟動 vLLM。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.llm_client import ChatCompletionClient
from app.main import create_app


class FakeResponse:
    """模擬 requests.Response 中測試會用到的介面。"""

    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    @property
    def text(self) -> str:
        return json.dumps(self._payload, ensure_ascii=False)

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    """記錄每次呼叫的參數,並依序回傳預先排定的假回應。"""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self._responses.pop(0) if self._responses else FakeResponse({}, 200)

    @property
    def last_payload(self) -> dict[str, Any]:
        return self.calls[-1]["json"]


def make_completion(content: str, reasoning: str | None = None) -> dict[str, Any]:
    """組出一份最小可用的 OpenAI 對話補全回應。"""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "qwen3.5-0.8b",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        upstream_base_url="http://vllm-test:8000/v1",
        upstream_api_key="EMPTY",
        model_name="qwen3.5-0.8b",
        connect_timeout=1.0,
        read_timeout=5.0,
        max_retries=0,
        default_max_tokens=256,
        default_temperature=0.7,
        log_level="WARNING",
        log_dir=tmp_path / "logs",
        log_max_bytes=1024,
        log_backup_count=1,
        host="127.0.0.1",
        port=8080,
    )


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession([])


@pytest.fixture
def client(settings: Settings, fake_session: FakeSession) -> ChatCompletionClient:
    return ChatCompletionClient(settings, session=fake_session)


@pytest.fixture
def flask_client(settings: Settings, client: ChatCompletionClient):
    app = create_app(settings)
    app.extensions["llm_client"] = client
    app.config.update(TESTING=True)
    return app.test_client()
