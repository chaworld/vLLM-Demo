"""與 vLLM OpenAI 相容端點溝通的客戶端,負責強制關閉 thinking 並清除殘留的推理內容。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import PASSTHROUGH_FIELDS, THINKING_DISABLED_KWARGS, Settings

logger = logging.getLogger(__name__)

# 即使上游已關閉 thinking,仍可能吐出 <think> 區塊;在回應端統一清除
_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK_BLOCK = re.compile(r"^\s*<think\b[^>]*>.*?(?:\n\n|\Z)", re.DOTALL | re.IGNORECASE)


class UpstreamError(RuntimeError):
    """上游推論服務無法連線或回應非 2xx。"""

    def __init__(self, message: str, status_code: int = 502, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def strip_thinking(text: str) -> str:
    """移除文字中成對的 <think>…</think> 區塊,以及開頭未閉合的推理片段。"""
    if not text:
        return text
    cleaned = _THINK_BLOCK.sub("", text)
    if "<think" in cleaned.lower():
        cleaned = _UNCLOSED_THINK_BLOCK.sub("", cleaned, count=1)
    return cleaned.strip()


class ChatCompletionClient:
    """對上游 /v1 端點的薄封裝;所有對話請求都以非串流方式送出。"""

    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self._settings = settings
        self._session = session if session is not None else self._build_session(settings)

    @staticmethod
    def _build_session(settings: Settings) -> requests.Session:
        """建立帶有指數退避重試的連線;僅對可安全重放的暫時性錯誤重試。"""
        retry = Retry(
            total=settings.max_retries,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            raise_on_status=False,
        )
        session = requests.Session()
        session.mount("http://", HTTPAdapter(max_retries=retry))
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    @property
    def model_name(self) -> str:
        return self._settings.model_name

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._settings.upstream_api_key}",
        }

    def build_upstream_payload(self, body: dict[str, Any]) -> dict[str, Any]:
        """組裝送往上游的請求;模型、串流與 thinking 開關一律由 gateway 決定,不接受前端覆寫。"""
        payload: dict[str, Any] = {
            key: value for key, value in body.items() if key in PASSTHROUGH_FIELDS
        }
        payload["model"] = self._settings.model_name
        payload["stream"] = False
        payload["chat_template_kwargs"] = dict(THINKING_DISABLED_KWARGS)
        payload.setdefault("temperature", self._settings.default_temperature)

        # 相容 OpenAI 新舊兩種長度欄位,統一送出 max_tokens
        requested_max_tokens = body.get("max_tokens") or body.get("max_completion_tokens")
        payload["max_tokens"] = int(requested_max_tokens or self._settings.default_max_tokens)
        return payload

    def sanitize_completion(self, completion: dict[str, Any]) -> dict[str, Any]:
        """清掉回應中的推理欄位與 <think> 區塊,確保前端只拿到最終答案。"""
        for choice in completion.get("choices", []):
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            message.pop("reasoning_content", None)
            message.pop("reasoning", None)
            if isinstance(message.get("content"), str):
                message["content"] = strip_thinking(message["content"])
        return completion

    def create_chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        """送出一次對話補全請求,回傳已清理的 OpenAI 格式回應。"""
        payload = self.build_upstream_payload(body)
        completion = self._post("/chat/completions", payload)
        return self.sanitize_completion(completion)

    def list_models(self) -> dict[str, Any]:
        """回傳上游模型清單,用於就緒檢查與 /v1/models。"""
        return self._get("/models")

    def _get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path, json_body=None)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, json_body=payload)

    def _request(self, method: str, path: str, json_body: dict[str, Any] | None) -> dict[str, Any]:
        url = f"{self._settings.upstream_base_url}{path}"
        started = time.perf_counter()
        try:
            response = self._session.request(
                method,
                url,
                json=json_body,
                headers=self._headers(),
                timeout=self._settings.request_timeout,
            )
        except requests.RequestException as exc:
            logger.error("upstream_unreachable", extra={"url": url, "error": str(exc)})
            raise UpstreamError(f"無法連線至上游推論服務: {exc}", status_code=503) from exc

        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        if response.status_code >= 400:
            logger.error(
                "upstream_error",
                extra={
                    "url": url,
                    "status": response.status_code,
                    "elapsed_ms": elapsed_ms,
                    "body": response.text[:500],
                },
            )
            raise UpstreamError(
                f"上游推論服務回應 {response.status_code}",
                status_code=502,
                payload=response.text[:500],
            )

        logger.info(
            "upstream_ok",
            extra={"url": url, "status": response.status_code, "elapsed_ms": elapsed_ms},
        )
        return response.json()
