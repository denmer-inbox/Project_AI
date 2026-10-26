"""Шина событий, стоп-кран и брокер подтверждений.

Контракт используется CLI, GUI и агентным циклом одновременно.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

# --- виды событий ---------------------------------------------------------
KIND_STATUS = "status"      # текст о состоянии (запуск, ожидание, завершение)
KIND_THOUGHT = "thought"    # рассуждение модели
KIND_ACTION = "action"      # вызов инструмента
KIND_RESULT = "result"      # результат инструмента
KIND_ERROR = "error"        # ошибка
KIND_IMAGE = "image"        # снимок экрана (image_path / image_bytes)
KIND_STEP = "step"          # номер шага
KIND_DONE = "done"          # задача завершена (data: RunResult.as_dict())
KIND_ASK = "ask"            # UI-запрос подтверждения (data: request_id, details)
KIND_ANSWER = "answer"      # ответ UI (data: request_id, approved)
KIND_LOG = "log"            # отладочное сообщение


@dataclass
class Event:
    kind: str
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    image_path: str | None = None
    image_bytes: bytes | None = None
    ts: float = field(default_factory=time.time)

    # --- фабрики ---
    @classmethod
    def status(cls, text: str) -> "Event":
        return cls(KIND_STATUS, text)

    @classmethod
    def thought(cls, text: str) -> "Event":
        return cls(KIND_THOUGHT, text)

    @classmethod
    def action(cls, name: str, args: dict[str, Any] | None = None) -> "Event":
        return cls(KIND_ACTION, name, {"args": args or {}})

    @classmethod
    def result(cls, name: str, ok: bool, summary: str, data: dict[str, Any] | None = None) -> "Event":
        return cls(KIND_RESULT, summary, {"name": name, "ok": ok, "data": data or {}})

    @classmethod
    def error(cls, text: str) -> "Event":
        return cls(KIND_ERROR, text)

    @classmethod
    def image(cls, shot_path: str | None = None, shot_bytes: bytes | None = None, **info: Any) -> "Event":
        """Событие со снимком экрана.

        Принимает и позиционные, и именованные аргументы; ключи path/data в
        info не конфликтуют с параметрами (частый вызов:
        Event.image(shot.path, shot.image_bytes, **shot.as_dict())).
        """
        if shot_path is None:
            shot_path = info.pop("path", None) or info.pop("image_path", None)
        else:
            info.pop("path", None)
            info.pop("image_path", None)
        if shot_bytes is None:
            shot_bytes = info.pop("data", None) or info.pop("image_bytes", None)
        else:
            info.pop("data", None)
            info.pop("image_bytes", None)
        return cls(KIND_IMAGE, data=info, image_path=shot_path, image_bytes=shot_bytes)

    @classmethod
    def step(cls, number: int) -> "Event":
        return cls(KIND_STEP, str(number), {"number": number})

    @classmethod
    def done(cls, payload: dict[str, Any]) -> "Event":
        return cls(KIND_DONE, data=payload)

    @classmethod
    def ask(cls, question: str, request_id: str, details: str = "") -> "Event":
        return cls(KIND_ASK, question, {"request_id": request_id, "details": details})

    @classmethod
    def log(cls, text: str) -> "Event":
        return cls(KIND_LOG, text)


class EventBus:
    """Потокобезопасная шина: очередь (для GUI) + подписчики (для CLI)."""

    def __init__(self) -> None:
        self._queue: "queue.Queue[Event]" = queue.Queue()
        self._subscribers: list[Callable[[Event], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, callback: Callable[[Event], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def publish(self, event: Event) -> None:
        self._queue.put(event)
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:  # noqa: BLE001 - подписчик не должен ломать агента
                pass

    def drain(self, limit: int = 500) -> list[Event]:
        items: list[Event] = []
        while len(items) < limit:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items

    def wait(self, timeout: float | None = None) -> Event | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def clear(self) -> None:
        self.drain(limit=10_000)


class KillSwitch:
    """Стоп-кран: агент проверяет его на каждом шаге."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def trigger(self) -> None:
        self._event.set()

    def reset(self) -> None:
        self._event.clear()

    @property
    def triggered(self) -> bool:
        return self._event.is_set()


kill_switch = KillSwitch()


class AskBroker:
    """Мост "агент ждёт ответ - UI отвечает".

    Агент вызывает ask() (блокируется), UI получает событие KIND_ASK и
    вызывает answer() с тем же request_id.
    """

    def __init__(self, bus: EventBus, default_timeout: float | None = 300.0) -> None:
        self.bus = bus
        self.default_timeout = default_timeout
        self._pending: dict[str, list[Any]] = {}
        self._lock = threading.Lock()

    def ask(self, question: str, details: str = "", timeout: float | None = None) -> bool:
        request_id = uuid.uuid4().hex[:10]
        gate = threading.Event()
        state: list[Any] = [gate, False]
        with self._lock:
            self._pending[request_id] = state
        self.bus.publish(Event.ask(question, request_id, details))
        effective_timeout = self.default_timeout if timeout is None else timeout
        answered = gate.wait(effective_timeout)
        with self._lock:
            self._pending.pop(request_id, None)
        if not answered:
            self.bus.publish(Event(KIND_LOG, f"Подтверждение не получено за {effective_timeout} с - считаю отказом"))
            return False
        return bool(state[1])

    def answer(self, request_id: str, approved: bool) -> bool:
        with self._lock:
            state = self._pending.get(request_id)
        if state is None:
            return False
        state[1] = bool(approved)
        state[0].set()
        return True

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def cancel_all(self) -> None:
        with self._lock:
            states = list(self._pending.values())
            self._pending.clear()
        for state in states:
            state[1] = False
            state[0].set()
