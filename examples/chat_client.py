"""以 Python 呼叫 qwen3.5 服務的對話範例,支援單次提問、互動模式與功能自我測試。

用法:
    python chat_client.py --prompt "台灣最高的山是哪一座?"
    python chat_client.py --interactive
    python chat_client.py --self-test
    python chat_client.py --base-url http://localhost:8000/v1 --prompt "hi"   # 直連 vLLM
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests

DEFAULT_BASE_URL = os.environ.get("CHAT_BASE_URL", "http://localhost:8080/v1")
DEFAULT_MODEL = os.environ.get("CHAT_MODEL", "qwen3.5-0.8b")
DEFAULT_API_KEY = os.environ.get("CHAT_API_KEY", "EMPTY")
LOG_PATH = Path(os.environ.get("CHAT_LOG_PATH", "logs/chat_client.jsonl"))

# 直連 vLLM 時必須自行帶上此參數才會關閉 thinking;經由 gateway 時 gateway 會再覆寫一次
THINKING_DISABLED_KWARGS = {"enable_thinking": False}

_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)

logger = logging.getLogger("chat_client")


class ChatError(RuntimeError):
    """呼叫推論服務失敗。"""


def configure_logging(verbose: bool) -> None:
    """設定主控台與輪替檔案雙軌日誌,檔案內容為方便後續分析的 JSON Lines。"""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    file_handler = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter('{"ts":"%(asctime)s","level":"%(levelname)s","message":%(message)s}'))

    logger.handlers = [console, file_handler]
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)


def _log_event(level: int, event: str, **fields: object) -> None:
    logger.log(level, json.dumps({"event": event, **fields}, ensure_ascii=False, default=str))


def strip_thinking(text: str) -> str:
    """移除回覆中可能殘留的 <think>…</think> 區塊。"""
    return _THINK_BLOCK.sub("", text).strip()


@dataclass
class ChatSession:
    """維護多輪對話歷史並負責與推論服務往返。"""

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = DEFAULT_API_KEY
    temperature: float = 0.7
    max_tokens: int = 1024
    timeout: float = 180.0
    system_prompt: str | None = "你是一個以繁體中文回答的助理,回答務求精簡準確。"
    history: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._session = requests.Session()
        self.reset()

    def reset(self) -> None:
        """清空對話歷史,只保留系統提示。"""
        self.history = [{"role": "system", "content": self.system_prompt}] if self.system_prompt else []

    def ask(self, prompt: str) -> str:
        """送出一輪提問,回傳已清理的助理回覆並寫回對話歷史。"""
        self.history.append({"role": "user", "content": prompt})
        completion = self._post_chat_completion(self.history)

        answer = strip_thinking(completion["choices"][0]["message"].get("content", ""))
        self.history.append({"role": "assistant", "content": answer})
        return answer

    def list_models(self) -> list[str]:
        """取得服務端可用的模型 ID 清單。"""
        response = self._session.get(
            f"{self.base_url}/models", headers=self._headers(), timeout=self.timeout
        )
        self._raise_for_status(response)
        return [item["id"] for item in response.json().get("data", [])]

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}

    def _post_chat_completion(self, messages: list[dict[str, str]]) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
            "chat_template_kwargs": THINKING_DISABLED_KWARGS,
        }
        started = time.perf_counter()
        try:
            response = self._session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            _log_event(logging.ERROR, "request_failed", error=str(exc))
            raise ChatError(f"無法連線至 {self.base_url}: {exc}") from exc

        self._raise_for_status(response)
        completion = response.json()
        usage = completion.get("usage", {})
        _log_event(
            logging.INFO,
            "chat_completion",
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        return completion

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.status_code >= 400:
            _log_event(logging.ERROR, "http_error", status=response.status_code, body=response.text[:300])
            raise ChatError(f"服務回應 HTTP {response.status_code}: {response.text[:300]}")


def run_single_prompt(session: ChatSession, prompt: str) -> int:
    print(session.ask(prompt))
    return 0


def run_interactive(session: ChatSession) -> int:
    """互動模式:輸入 /reset 清空歷史,/quit 或 Ctrl-C 離開。"""
    print(f"已連線 {session.base_url}(模型 {session.model},thinking 已關閉)。輸入 /quit 離開。")
    while True:
        try:
            prompt = input("\n你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not prompt:
            continue
        if prompt in {"/quit", "/exit"}:
            return 0
        if prompt == "/reset":
            session.reset()
            print("(對話歷史已清空)")
            continue
        try:
            print(f"\n助理 > {session.ask(prompt)}")
        except ChatError as exc:
            print(f"\n[錯誤] {exc}", file=sys.stderr)


def run_self_test(session: ChatSession) -> int:
    """功能測試:依序檢查模型清單、基本問答、thinking 是否確實關閉。"""
    checks: list[tuple[str, bool, str]] = []

    try:
        models = session.list_models()
        checks.append(("模型清單可取得", bool(models), f"models={models}"))
    except ChatError as exc:
        checks.append(("模型清單可取得", False, str(exc)))

    try:
        answer = session.ask("只回答一個阿拉伯數字:2 加 3 等於多少?")
        checks.append(("基本問答有回覆", bool(answer.strip()), f"answer={answer[:60]!r}"))
        checks.append(("回覆不含 think 標籤", "<think" not in answer.lower(), f"answer={answer[:60]!r}"))
    except ChatError as exc:
        checks.append(("基本問答有回覆", False, str(exc)))
        checks.append(("回覆不含 think 標籤", False, "前一項失敗,略過"))

    for name, passed, detail in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name} — {detail}")
        _log_event(logging.INFO, "self_test", check=name, passed=passed, detail=detail)

    failed = sum(1 for _, passed, _ in checks if not passed)
    print(f"\n通過 {len(checks) - failed}/{len(checks)} 項,日誌:{LOG_PATH}")
    return 1 if failed else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="qwen3.5 對話範例客戶端")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI 相容端點,預設指向 Flask gateway")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--verbose", action="store_true")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prompt", help="送出單次提問後結束")
    mode.add_argument("--interactive", action="store_true", help="進入多輪互動對話")
    mode.add_argument("--self-test", action="store_true", help="執行功能測試並回傳結果")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    session = ChatSession(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    try:
        if args.prompt:
            return run_single_prompt(session, args.prompt)
        if args.interactive:
            return run_interactive(session)
        return run_self_test(session)
    except ChatError as exc:
        print(f"[錯誤] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
