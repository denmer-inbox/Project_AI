"""Лента чата в стиле мессенджера: вопрос, ответ и свёрнутые подробности.

Раньше каждое событие агента писало строку в ленту: шаги, мысли,
действия, результаты. Вопрос и ответ тонули в служебном шуме. Теперь
видно только сообщения пользователя и ответы агента, а технические
строки лежат в раскрывашке, которую можно открыть кликом.
"""

from __future__ import annotations

import pytest

from pcagent.gui.chat_feed import ChatFeed


@pytest.fixture()
def feed():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except Exception as exc:  # noqa: BLE001 - нет дисплея
        pytest.skip(f"Tk недоступен: {exc}")
    root.withdraw()
    widget = tk.Text(root)
    widget.configure(state="disabled")
    instance = ChatFeed(
        widget,
        {"accent": "#2d6cdf", "fg": "#eeeeee", "fg_dim": "#888888",
         "bg_field": "#1b1c1f", "error": "#e05c5c"},
        "Segoe UI",
    )
    yield instance
    root.destroy()


def test_user_message_is_visible(feed):
    feed.add_user("Открой блокнот")
    assert "Открой блокнот" in feed.full_text()
    assert feed.visible_messages() == [("user", "Открой блокнот")]


def test_bot_answer_is_visible(feed):
    feed.add_bot("Блокнот открыт")
    assert "Блокнот открыт" in feed.full_text()


def test_details_are_collapsed_by_default(feed):
    """Технические строки не показываются, пока их не раскрыли."""
    feed.add_detail("Действие: click {x: 10, y: 20}", header="Ход выполнения")
    assert feed.details, "раскрывашка должна создаться"
    assert feed.details[0].expanded is False
    visible = feed.plain_text()
    assert "click" not in visible, "тело раскрывашки не должно быть видно"
    assert "Ход выполнения" in visible, "заголовок раскрывашки виден"


def test_expand_shows_details(feed):
    feed.add_detail("Действие: click {x: 10, y: 20}")
    feed.toggle(0)
    assert feed.details[0].expanded is True
    assert "click" in feed.plain_text()


def test_collapse_hides_details_again(feed):
    feed.add_detail("Результат: окно найдено")
    feed.toggle(0)
    assert "окно найдено" in feed.plain_text()
    feed.toggle(0)
    assert "окно найдено" not in feed.plain_text()


def test_details_group_into_one_block(feed):
    """Все строки хода агента попадают в одну раскрывашку."""
    feed.add_detail("строка 1")
    feed.add_detail("строка 2")
    feed.add_detail("строка 3")
    assert len(feed.details) == 1
    assert feed.details[0].body.count("строка") == 3


def test_new_block_after_close(feed):
    feed.add_detail("первый ход")
    feed.close_details()
    feed.add_detail("второй ход")
    assert len(feed.details) == 2


def test_error_is_visible(feed):
    """Ошибку прятать нельзя."""
    feed.add_error("Не удалось открыть программу")
    assert "Не удалось открыть программу" in feed.plain_text()
    assert ("error", "Не удалось открыть программу") in feed.visible_messages()


def test_empty_text_is_ignored(feed):
    feed.add_user("")
    feed.add_bot("   ")
    feed.add_detail("")
    assert feed.visible_messages() == []
    assert feed.details == []


def test_toggle_last(feed):
    feed.add_detail("раз")
    feed.close_details()
    feed.add_detail("два")
    assert feed.toggle_last() is True
    assert feed.details[-1].expanded is True
    assert feed.toggle_last() is False
    assert feed.details[-1].expanded is False


def test_toggle_out_of_range(feed):
    assert feed.toggle(0) is False
    assert feed.toggle_last() is False


def test_full_text_includes_hidden_body(feed):
    """Полный текст нужен для копирования и проверок."""
    feed.add_detail("скрытая строка")
    assert "скрытая строка" in feed.full_text()
    assert "скрытая строка" not in feed.plain_text()


def test_widget_stays_disabled(feed):
    """Пользователь не должен печатать прямо в ленту."""
    feed.add_user("задача")
    assert str(feed.widget.cget("state")) == "disabled"


def test_messages_keep_order(feed):
    feed.add_user("вопрос")
    feed.add_bot("ответ")
    assert feed.visible_messages() == [("user", "вопрос"), ("bot", "ответ")]