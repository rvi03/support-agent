"""structlog JSON logging with the PII filter as the last step (D9, review M2).

All stdlib loggers (uvicorn, httpx, LangGraph, LiteLLM client, APScheduler) are
routed through the same formatter, so the PII filter covers every log line.
Two sinks: stdout and `LOG_DIR/<service>.jsonl`, which the S14 checker reads.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.typing import Processor

from support_agent.common.pii_filter import (
    clear_exact_values,
    pii_filter_processor,
    register_exact_values,
)

__all__ = [
    "bind_ticket",
    "clear_exact_values",
    "configure_logging",
    "get_logger",
    "register_exact_values",
    "unbind_ticket",
]

_HANDLER_MARK = "_support_agent_handler"

# Runs on both structlog and stdlib events, before the formatter's own chain.
_SHARED: list[Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
    # Tracebacks become text here, so the PII filter sees them.
    structlog.processors.format_exc_info,
]


class _StdoutHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Writes to whatever sys.stdout is at emit time (works under test capture)."""

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    @property
    def stream(self) -> Any:
        return sys.stdout

    @stream.setter
    def stream(self, _value: Any) -> None:
        pass


def _formatter() -> structlog.stdlib.ProcessorFormatter:
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[*_SHARED, structlog.stdlib.ExtraAdder()],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            pii_filter_processor,  # last before rendering
            structlog.processors.JSONRenderer(),
        ],
    )


def configure_logging(service: str, log_dir: str | Path, level: int = logging.INFO) -> Path:
    """Send all logs as JSON to stdout and LOG_DIR/<service>.jsonl. Returns the file path."""
    log_path = Path(log_dir) / f"{service}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = _formatter()
    stdout_handler = _StdoutHandler()
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _HANDLER_MARK, False)]:
        root.removeHandler(handler)
        handler.close()
    for handler in (stdout_handler, file_handler):
        handler.setFormatter(formatter)
        setattr(handler, _HANDLER_MARK, True)
        root.addHandler(handler)
    root.setLevel(level)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *_SHARED,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    return log_path


def get_logger(name: str) -> Any:
    """A structlog logger; call configure_logging once at process start first."""
    return structlog.get_logger(name)


def bind_ticket(ticket_id: str) -> None:
    """Shortcut: add ticket_id to every event in this context (not other threads)."""
    structlog.contextvars.bind_contextvars(ticket_id=ticket_id)


def unbind_ticket() -> None:
    structlog.contextvars.unbind_contextvars("ticket_id")
