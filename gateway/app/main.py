"""Flask 應用程式組裝與啟動進入點。"""

from __future__ import annotations

import logging

from flask import Flask

from .config import Settings
from .llm_client import ChatCompletionClient, UpstreamError
from .logging_setup import configure_logging
from .metrics import MetricsRegistry
from .routes import api, handle_upstream_error

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> Flask:
    """建立並組裝 Flask app;測試可注入自訂 Settings。"""
    settings = settings or Settings.from_env()
    configure_logging(settings)

    app = Flask(__name__)
    app.config["SETTINGS"] = settings
    app.extensions["llm_client"] = ChatCompletionClient(settings)
    app.extensions["metrics"] = MetricsRegistry()
    app.register_blueprint(api)
    app.register_error_handler(UpstreamError, handle_upstream_error)

    logger.info(
        "gateway_configured",
        extra={
            "upstream": settings.upstream_base_url,
            "model": settings.model_name,
            "thinking": "disabled",
        },
    )
    return app


def main() -> None:
    """以 waitress 啟動正式服務;waitress 在 Windows/Linux/macOS 皆可執行。"""
    from waitress import serve

    settings = Settings.from_env()
    app = create_app(settings)
    logger.info("gateway_listening", extra={"host": settings.host, "port": settings.port})
    serve(app, host=settings.host, port=settings.port, threads=8)


if __name__ == "__main__":
    main()
