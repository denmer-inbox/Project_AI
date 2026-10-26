"""Журналирование: JSONL-аудит действий + вывод в консоль."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

LOGGER_NAME = "pcagent"


def setup_console_logging(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(handler)
    return logger


class JsonlLogger:
    """Пишет поток событий агента в logs/agent-<дата>.jsonl."""

    def __init__(self, log_dir: str | Path, session_name: str = "session") -> None:
        self.dir = Path(log_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = self.dir / f"{session_name}-{stamp}.jsonl"
        self._lock = threading.Lock()
        self._fh = open(self.path, "a", encoding="utf-8")

    def log(self, kind: str, payload: dict[str, Any] | None = None, **extra: Any) -> None:
        record = {"ts": round(time.time(), 4), "kind": kind}
        if payload:
            record["payload"] = payload
        if extra:
            record.update(extra)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            try:
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "JsonlLogger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class NullLogger:
    """Заглушка для тестов."""

    path = None

    def log(self, kind: str, payload: dict[str, Any] | None = None, **extra: Any) -> None:
        return None

    def close(self) -> None:
        return None
