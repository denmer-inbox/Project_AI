"""Лента чата в стиле мессенджера: сообщения пузырями, детали свёрнуты."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Details:
    """Одна раскрывашка внутри ленты."""

    header: str
    body: str = ""
    expanded: bool = False

    def add(self, text: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        self.body = (self.body + "\n" + text) if self.body else text


class ChatFeed:
    """Чат как в Телеграме: вопрос, ответ и свёрнутые подробности.

    Раньше каждое событие агента писало строку в ленту: шаги, мысли,
    действия, результаты. Читать это невозможно - вопрос и ответ тонут в
    служебном шуме. Теперь служебные строки складываются в одну
    раскрывашку на ход агента, а видно только "Задача:" и "Ответ:".
    """

    def __init__(self, widget: Any, palette: dict[str, str], font_family: str,
                 font_size: int = 10, font_size_small: int = 9) -> None:
        self.widget = widget
        self.palette = palette
        self.font_family = font_family
        self.font_size = font_size
        self.font_size_small = font_size_small

        #: Раскрывашки в порядке добавления.
        self.details: list[_Details] = []
        #: Текущая открытая раскрывашка хода агента (None - нет активной).
        self.current: _Details | None = None
        #: Сообщение пользователя и ответ - только для тестов и поиска.
        self.messages: list[tuple[str, str]] = []

        self._configure_tags()

    # ------------------------------------------------------------- теги
    def _configure_tags(self) -> None:
        p = self.palette
        family = self.font_family
        w = self.widget

        w.tag_configure("bubble_user", background=p.get("accent", "#2d6cdf"),
                        foreground="#ffffff", lmargin1=90, lmargin2=90, rmargin=8,
                        spacing1=4, spacing3=4, justify="right",
                        font=(family, self.font_size, "bold"))
        w.tag_configure("bubble_bot", background=p.get("bg_field", "#1b1c1f"),
                        foreground=p.get("fg", "#e6e6e6"), lmargin1=8, lmargin2=8,
                        rmargin=90, spacing1=4, spacing3=4,
                        font=(family, self.font_size))
        w.tag_configure("meta", foreground=p.get("fg_dim", "#8a8a8a"),
                        font=(family, self.font_size_small),
                        lmargin1=10, lmargin2=10, spacing1=2, spacing3=2)
        w.tag_configure("details_header", foreground=p.get("accent", "#2d6cdf"),
                        font=(family, self.font_size_small, "underline"),
                        lmargin1=10, lmargin2=10, spacing1=2, spacing3=2)
        w.tag_configure("details_body", foreground=p.get("fg_dim", "#8a8a8a"),
                        font=(family, self.font_size_small),
                        lmargin1=26, lmargin2=26, spacing1=1, spacing3=1)
        w.tag_configure("error", foreground=p.get("error", "#e05c5c"),
                        font=(family, self.font_size, "bold"),
                        lmargin1=8, lmargin2=8, spacing1=3, spacing3=3)

    # ------------------------------------------------------------ утилиты
    def _insert(self, text: str, *tags: str) -> None:
        """Вставить текст, сняв блокировку ввода.

        Виджет чата создаётся с state="disabled", чтобы пользователь не мог
        печатать в него. Лента пишет сама, поэтому состояние снимается на
        время вставки и возвращается обратно.
        """
        widget = self.widget
        try:
            previous = str(widget.cget("state"))
        except Exception:  # noqa: BLE001
            previous = "disabled"
        try:
            if previous != "normal":
                widget.configure(state="normal")
            widget.insert("end", text, tags)
        finally:
            if previous != "normal":
                try:
                    widget.configure(state=previous)
                except Exception:  # noqa: BLE001
                    pass

    def _seen(self) -> None:
        try:
            self.widget.see("end")
        except Exception:  # noqa: BLE001 - виджет мог закрыться
            pass

    # ----------------------------------------------------------- сообщения
    def add_user(self, text: str) -> None:
        """Сообщение пользователя (вопрос)."""
        value = str(text or "").strip()
        if not value:
            return
        self.close_details()
        self._insert("\n" + value + "\n", "bubble_user")
        self.messages.append(("user", value))
        self._seen()

    def add_bot(self, text: str) -> None:
        """Ответ агента."""
        value = str(text or "").strip()
        if not value:
            return
        self.close_details()
        self._insert("\n" + value + "\n", "bubble_bot")
        self.messages.append(("bot", value))
        self._seen()

    def add_meta(self, text: str) -> None:
        """Короткая служебная строка (статус, время)."""
        value = str(text or "").strip()
        if not value:
            return
        self._insert(value + "\n", "meta")
        self._seen()

    def add_error(self, text: str) -> None:
        value = str(text or "").strip()
        if not value:
            return
        self._insert("\n" + value + "\n", "error")
        self.messages.append(("error", value))
        self._seen()

    # --------------------------------------------------------- раскрывашки
    def add_detail(self, text: str, header: str = "Подробности") -> None:
        """Добавить строку в текущую раскрывашку (или создать новую)."""
        value = str(text or "").strip()
        if not value:
            return
        if self.current is None:
            self.open_details(header)
        assert self.current is not None
        self.current.add(value)

    def open_details(self, header: str = "Подробности") -> None:
        """Начать новую свёрнутую раскрывашку."""
        self.close_details()
        item = _Details(header=str(header or "Подробности"))
        self.details.append(item)
        self.current = item
        self._render_header(item)

    def close_details(self) -> None:
        """Закрыть текущую раскрывашку (следующие строки пойдут в новую)."""
        self.current = None

    def _render_header(self, item: _Details) -> None:
        marker = "▼ " if item.expanded else "▶ "
        self._insert("\n" + marker + item.header + "\n", "details_header")
        self._seen()

    def toggle_last(self) -> bool:
        """Раскрыть или свернуть последнюю раскрывашку. Возвращает новое состояние."""
        if not self.details:
            return False
        return self.toggle(len(self.details) - 1)

    def toggle(self, index: int) -> bool:
        """Переключить раскрывашку по номеру."""
        if not (0 <= index < len(self.details)):
            return False
        item = self.details[index]
        item.expanded = not item.expanded
        self._redraw()
        return item.expanded

    def _redraw(self) -> None:
        """Перерисовать ленту: раскрывашки разворачиваются и сворачиваются."""
        widget = self.widget
        try:
            state = str(widget.cget("state"))
        except Exception:  # noqa: BLE001
            state = "normal"
        try:
            widget.configure(state="normal")
            widget.delete("1.0", "end")

            for role, text in self.messages:
                if role == "user":
                    self._insert("\n" + text + "\n", "bubble_user")
                elif role == "bot":
                    self._insert("\n" + text + "\n", "bubble_bot")
                elif role == "error":
                    self._insert("\n" + text + "\n", "error")
                elif role == "meta":
                    self._insert(text + "\n", "meta")

            self._insert("\n", "meta")
            for item in self.details:
                marker = "▼ " if item.expanded else "▶ "
                self._insert(marker + item.header + "\n", "details_header")
                if item.expanded and item.body:
                    self._insert(item.body + "\n", "details_body")
            self._seen()
        finally:
            try:
                widget.configure(state=state)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ чтение
    def plain_text(self) -> str:
        """Весь текст ленты (для тестов и копирования)."""
        try:
            return self.widget.get("1.0", "end")
        except Exception:  # noqa: BLE001
            return ""

    def visible_messages(self) -> list[tuple[str, str]]:
        """Видимые сообщения без служебных строк."""
        return list(self.messages)

    def full_text(self) -> str:
        """Весь текст ленты, включая свёрнутые подробности.

        Видимая часть - только вопрос и ответ, но для проверок и копирования
        нужен полный текст: технические строки лежат в раскрывашках.
        """
        parts: list[str] = []
        for _role, text in self.messages:
            parts.append(text)
        for item in self.details:
            parts.append(item.header)
            if item.body:
                parts.append(item.body)
        return "\n".join(parts) + "\n"


__all__ = ["ChatFeed"]