"""結構化 JSON 日誌:同時寫入 stdout(供 docker logs 蒐集)與輪替檔案(供長期查閱)。"""

from __future__ import annotations

import json
import logging
import sys
from logging.handlers import RotatingFileHandler

from .config import Settings

# LogRecord 的內建欄位,格式化時要排除,剩下的才是呼叫端用 extra= 帶入的自訂欄位
_BUILTIN_RECORD_FIELDS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)


class JsonLogFormatter(logging.Formatter):
    """把一筆 LogRecord 序列化成單行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            {key: value for key, value in record.__dict__.items() if key not in _BUILTIN_RECORD_FIELDS}
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _build_file_handler(settings: Settings) -> logging.Handler | None:
    """建立輪替檔案 handler;目錄不可寫時退回只留 stdout,不讓服務因日誌失敗而中止。"""
    try:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            settings.log_dir / "gateway.jsonl",
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
    except OSError:
        return None
    return handler


def configure_logging(settings: Settings) -> None:
    """設定 root logger,重複呼叫時會先清空既有 handler 避免日誌重複輸出。"""
    formatter = JsonLogFormatter()
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    file_handler = _build_file_handler(settings)
    if file_handler is not None:
        handlers.append(file_handler)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(settings.log_level)

    # werkzeug 的預設存取日誌與本檔的結構化請求日誌重複,降級為僅記錄警告
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
