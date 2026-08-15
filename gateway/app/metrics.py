"""執行期指標:以行程內計數器提供最小可用的監控面,供 /metrics 端點輸出。"""

from __future__ import annotations

import threading
from collections import deque


class MetricsRegistry:
    """執行緒安全的請求計數與延遲統計。"""

    def __init__(self, window_size: int = 200) -> None:
        self._lock = threading.Lock()
        self._latencies_ms: deque[float] = deque(maxlen=window_size)
        self._total_requests = 0
        self._failed_requests = 0
        self._total_completion_tokens = 0
        self._total_prompt_tokens = 0

    def record_request(self, latency_ms: float, failed: bool) -> None:
        with self._lock:
            self._total_requests += 1
            self._failed_requests += int(failed)
            self._latencies_ms.append(latency_ms)

    def record_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        with self._lock:
            self._total_prompt_tokens += prompt_tokens
            self._total_completion_tokens += completion_tokens

    def snapshot(self) -> dict[str, float | int]:
        """回傳目前指標;延遲百分位取自最近 window_size 筆請求。"""
        with self._lock:
            samples = sorted(self._latencies_ms)
            return {
                "requests_total": self._total_requests,
                "requests_failed": self._failed_requests,
                "prompt_tokens_total": self._total_prompt_tokens,
                "completion_tokens_total": self._total_completion_tokens,
                "latency_ms_p50": _percentile(samples, 0.50),
                "latency_ms_p95": _percentile(samples, 0.95),
                "latency_ms_max": samples[-1] if samples else 0.0,
            }


def _percentile(sorted_samples: list[float], fraction: float) -> float:
    if not sorted_samples:
        return 0.0
    index = min(len(sorted_samples) - 1, int(round(fraction * (len(sorted_samples) - 1))))
    return round(sorted_samples[index], 2)
