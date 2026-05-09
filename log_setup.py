import contextvars
import logging
import sys
import uuid
from logging.handlers import RotatingFileHandler

import config

_CONFIGURED = False

_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        return True


def get_request_id() -> str:
    return _request_id_ctx.get()


def set_request_id(value: str | None = None) -> str:
    rid = value or uuid.uuid4().hex[:12]
    _request_id_ctx.set(rid)
    return rid


def reset_request_id() -> None:
    _request_id_ctx.set("-")


def setup() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if config.LOG_FILE:
        handlers.append(
            RotatingFileHandler(
                config.LOG_FILE,
                maxBytes=config.LOG_MAX_BYTES,
                backupCount=config.LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        )

    fmt = "%(asctime)s %(levelname)s [%(name)s] [rid=%(request_id)s] %(message)s"
    rid_filter = _RequestIdFilter()
    for h in handlers:
        h.addFilter(rid_filter)
    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)
    _CONFIGURED = True
