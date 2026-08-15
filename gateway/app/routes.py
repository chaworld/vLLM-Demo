"""HTTP 路由:對外提供 OpenAI 相容介面,對內以非串流方式轉送到 vLLM。"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Iterator

from flask import Blueprint, Response, current_app, g, jsonify, request

from .llm_client import ChatCompletionClient, UpstreamError
from .metrics import MetricsRegistry

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__)


def _client() -> ChatCompletionClient:
    return current_app.extensions["llm_client"]


def _metrics() -> MetricsRegistry:
    return current_app.extensions["metrics"]


@api.before_request
def _start_request_context() -> None:
    """為每個請求配置追蹤 ID 與計時起點,讓日誌可串接同一次呼叫。"""
    g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    g.started_at = time.perf_counter()


@api.after_request
def _log_request(response: Response) -> Response:
    """輸出結構化存取日誌,並把延遲寫進指標。"""
    latency_ms = round((time.perf_counter() - g.started_at) * 1000, 2)
    response.headers["X-Request-ID"] = g.request_id
    _metrics().record_request(latency_ms, failed=response.status_code >= 500)
    logger.info(
        "http_access",
        extra={
            "request_id": g.request_id,
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "latency_ms": latency_ms,
        },
    )
    return response


@api.get("/healthz")
def health() -> Response:
    """存活檢查:只確認 gateway 行程本身,不觸碰上游。"""
    return jsonify({"status": "ok", "service": "qwen35-gateway"})


@api.get("/readyz")
def ready() -> tuple[Response, int]:
    """就緒檢查:實際打上游模型清單,確認整條推論鏈可用。"""
    try:
        models = _client().list_models()
    except UpstreamError as exc:
        return jsonify({"status": "unavailable", "reason": str(exc)}), 503
    served = [item.get("id") for item in models.get("data", [])]
    return jsonify({"status": "ready", "upstream_models": served}), 200


@api.get("/metrics")
def metrics() -> Response:
    """輸出行程內累積的請求量、錯誤數、延遲百分位與 token 用量。"""
    return jsonify(_metrics().snapshot())


@api.get("/v1/models")
def list_models() -> Response:
    """回報本 gateway 對外開放的唯一模型,不透出上游其他模型。"""
    client = _client()
    return jsonify(
        {
            "object": "list",
            "data": [
                {
                    "id": client.model_name,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "qwen35-stack",
                }
            ],
        }
    )


@api.post("/v1/chat/completions")
def chat_completions() -> Response:
    """對話補全:強制關閉 thinking,並依前端需求決定回傳 JSON 或單塊 SSE。"""
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not body.get("messages"):
        return jsonify({"error": {"message": "請求必須包含非空的 messages 陣列", "type": "invalid_request_error"}}), 400

    client = _client()
    completion = client.create_chat_completion(body)

    usage = completion.get("usage") or {}
    _metrics().record_usage(
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
    )
    logger.info(
        "chat_completion",
        extra={
            "request_id": g.request_id,
            "model": client.model_name,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "finish_reason": _first_finish_reason(completion),
        },
    )

    if body.get("stream"):
        return Response(
            _sse_chunks(completion, client.model_name),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return jsonify(completion)


def _first_finish_reason(completion: dict[str, Any]) -> str | None:
    choices = completion.get("choices") or []
    return choices[0].get("finish_reason") if choices else None


def _sse_chunks(completion: dict[str, Any], model: str) -> Iterator[str]:
    """把一次性完成的回應包裝成單一 SSE chunk,維持 OpenAI 串流格式相容。"""
    choice = (completion.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    envelope = {
        "id": completion.get("id", f"chatcmpl-{uuid.uuid4().hex[:16]}"),
        "object": "chat.completion.chunk",
        "created": completion.get("created", int(time.time())),
        "model": model,
    }
    content_chunk = {
        **envelope,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": message.get("content", "")},
                "finish_reason": None,
            }
        ],
    }
    final_chunk = {
        **envelope,
        "choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}],
        "usage": completion.get("usage"),
    }
    yield f"data: {json.dumps(content_chunk, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


def handle_upstream_error(exc: UpstreamError) -> tuple[Response, int]:
    """把上游錯誤轉成 OpenAI 格式的錯誤回應,避免洩漏內部堆疊。"""
    logger.error("request_failed", extra={"error": str(exc), "status": exc.status_code})
    return (
        jsonify({"error": {"message": str(exc), "type": "upstream_error", "detail": exc.payload}}),
        exc.status_code,
    )
