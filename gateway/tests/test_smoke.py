"""端對端冒煙測試:對已啟動的 gateway 實際發話,驗證整條推論鏈與 thinking 關閉狀態。"""

from __future__ import annotations

import os

import pytest
import requests

pytestmark = pytest.mark.smoke

GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "http://localhost:8080").rstrip("/")
SMOKE_TIMEOUT = float(os.environ.get("SMOKE_TIMEOUT", "180"))


def _get(path: str) -> requests.Response:
    return requests.get(f"{GATEWAY_BASE_URL}{path}", timeout=SMOKE_TIMEOUT)


@pytest.fixture(scope="session", autouse=True)
def require_running_gateway() -> None:
    """gateway 未啟動時整批跳過,避免把環境問題誤判為程式錯誤。"""
    try:
        response = _get("/healthz")
    except requests.RequestException as exc:
        pytest.skip(f"gateway 未啟動於 {GATEWAY_BASE_URL}: {exc}")
    if response.status_code != 200:
        pytest.skip(f"gateway 健康檢查未通過: HTTP {response.status_code}")


def test_gateway_is_ready() -> None:
    response = _get("/readyz")
    assert response.status_code == 200, response.text
    assert response.json()["upstream_models"], "上游未回報任何模型"


def test_model_list_is_pinned() -> None:
    model_ids = [item["id"] for item in _get("/v1/models").json()["data"]]
    assert len(model_ids) == 1


def test_chat_returns_answer_without_thinking_traces() -> None:
    response = requests.post(
        f"{GATEWAY_BASE_URL}/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "用一句話回答:台灣最高的山是哪一座?"}],
            "max_tokens": 128,
            "temperature": 0.2,
        },
        timeout=SMOKE_TIMEOUT,
    )
    assert response.status_code == 200, response.text

    message = response.json()["choices"][0]["message"]
    assert message["content"].strip(), "模型回覆為空"
    assert "<think>" not in message["content"].lower()
    assert "reasoning_content" not in message


def test_streaming_shape_is_openai_compatible() -> None:
    response = requests.post(
        f"{GATEWAY_BASE_URL}/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "說「你好」兩個字"}], "stream": True, "max_tokens": 32},
        timeout=SMOKE_TIMEOUT,
    )
    assert response.status_code == 200, response.text
    assert "data: [DONE]" in response.text


def test_metrics_endpoint_exposes_counters() -> None:
    snapshot = _get("/metrics").json()
    assert {"requests_total", "latency_ms_p50", "completion_tokens_total"} <= snapshot.keys()
    assert snapshot["requests_total"] > 0
