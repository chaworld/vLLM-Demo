"""Gateway 組態:所有可變設定一律由環境變數注入,程式碼內不硬編碼端點。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# 強制關閉 thinking 的 chat template 參數,注入到每一個送往上游的請求
THINKING_DISABLED_KWARGS: dict[str, bool] = {"enable_thinking": False}

# 允許前端(Open WebUI / 自訂客戶端)傳入並轉送到上游的取樣參數白名單
PASSTHROUGH_FIELDS: frozenset[str] = frozenset(
    {
        "messages",
        "temperature",
        "top_p",
        "stop",
        "seed",
        "presence_penalty",
        "frequency_penalty",
        "n",
        "user",
    }
)


def _get_str(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get_str(name, str(default)))
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(_get_str(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """單一組不可變的執行期設定。"""

    upstream_base_url: str
    upstream_api_key: str
    model_name: str
    connect_timeout: float
    read_timeout: float
    max_retries: int
    default_max_tokens: int
    default_temperature: float
    log_level: str
    log_dir: Path
    log_max_bytes: int
    log_backup_count: int
    host: str
    port: int

    @property
    def request_timeout(self) -> tuple[float, float]:
        return (self.connect_timeout, self.read_timeout)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            upstream_base_url=_get_str("LLM_BASE_URL", "http://10.0.0.220:8004/v1").rstrip("/"),
            # 若 vLLM 改跑在外部遠端主機,可將 LLM_BASE_URL 手動改成 http://10.0.0.220:8004/v1
            # 若 vLLM 改跑在主機,可將 LLM_BASE_URL 手動改成 http://vllm:8000/v1
            upstream_api_key=_get_str("LLM_API_KEY", "EMPTY"),
            model_name=_get_str("LLM_MODEL_NAME", "gemma-4-26b"), #gemma-4-26b #qwen3.5-0.8b
            connect_timeout=_get_float("LLM_CONNECT_TIMEOUT", 5.0),
            read_timeout=_get_float("LLM_READ_TIMEOUT", 120.0),
            max_retries=_get_int("LLM_MAX_RETRIES", 2),
            default_max_tokens=_get_int("LLM_MAX_TOKENS", 1024),
            default_temperature=_get_float("LLM_TEMPERATURE", 0.7),
            log_level=_get_str("LOG_LEVEL", "INFO").upper(),
            log_dir=Path(_get_str("LOG_DIR", "/var/log/gateway")),
            log_max_bytes=_get_int("LOG_MAX_BYTES", 10 * 1024 * 1024),
            log_backup_count=_get_int("LOG_BACKUP_COUNT", 5),
            host=_get_str("GATEWAY_HOST", "0.0.0.0"),
            port=_get_int("GATEWAY_PORT", 8080),
        )
