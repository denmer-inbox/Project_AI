"""Тёмная тема оформления GUI и шрифты.

Единая палитра и настройка ttk-стилей: всё оформление собирается здесь,
чтобы app.py не разбрасывал цвета по виджетам.

Шрифт Liberation Serif берётся из системных (в этой системе он лежит в
пользовательских шрифтах Windows). Если семейства нет, тема аккуратно
откатывается на Georgia, затем на стандартный serif.
"""

from __future__ import annotations

from typing import Any

#: Основная палитра тёмной темы.
PALETTE: dict[str, str] = {
    "bg": "#1e1f22",          # фон окна
    "bg_panel": "#2b2d30",    # панели, поля ввода
    "bg_field": "#1b1c1f",    # текстовые поля
    "bg_hover": "#3a3d41",    # наведение
    "border": "#3c3f41",      # рамки
    "fg": "#dfe1e5",          # основной текст
    "fg_dim": "#9aa0a6",      # второстепенный текст
    "fg_bright": "#ffffff",   # акцентный текст
    "accent": "#5b9cf8",      # акцент (кнопки, заголовки)
    "accent_dark": "#3574f0", # нажатие
    "selection": "#2f4f7f",   # выделение
    "success": "#6fbf5b",     # успешный результат
    "error": "#f0616d",       # ошибки
    "warning": "#e0a44a",     # действия
    "thought": "#8b949e",     # рассуждения модели
    "log": "#6b7280",         # служебный лог
}

#: Кандидаты шрифта по убыванию предпочтения.
FONT_CANDIDATES: tuple[str, ...] = (
    "Liberation Serif",
    "Georgia",
    "Times New Roman",
    "serif",
)

#: Базовые размеры шрифтов.
FONT_SIZE = 11
FONT_SIZE_SMALL = 10
FONT_SIZE_HEADER = 11


def pick_font_family(root: Any = None) -> str:
    """Выбрать доступное семейство шрифта.

    Проверяет реальные семейства Tk, чтобы не подставлять молча
    несуществующий шрифт: иначе Tk покажет случайный fallback.
    """
    if root is None:
        return FONT_CANDIDATES[0]
    try:
        from tkinter import font as tkfont

        available = {name.lower() for name in tkfont.families(root)}
    except Exception:  # noqa: BLE001 - без Tk остаётся первый кандидат
        return FONT_CANDIDATES[0]
    for family in FONT_CANDIDATES:
        if family.lower() in available:
            return family
    return FONT_CANDIDATES[0]


def font(family: str, size: int = FONT_SIZE, *styles: str) -> tuple:
    """Собрать кортеж шрифта для tk-виджетов."""
    return (family, size, *styles) if styles else (family, size)


def apply_theme(root: Any) -> dict[str, str]:
    """Применить тёмную тему к окну. Возвращает палитру и имя шрифта.

    Тема применяется к ttk-стилям (кнопки, поля, таблицы) и к фону самого
    окна; классические tk-виджеты (Text, Menu) красятся в app.py.
    """
    from tkinter import ttk

    palette = dict(PALETTE)
    family = pick_font_family(root)
    palette["font_family"] = family

    try:
        root.configure(background=palette["bg"])
    except Exception:  # noqa: BLE001
        pass

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:  # noqa: BLE001 - тема может отсутствовать
        pass

    base_font = font(family, FONT_SIZE)
    small_font = font(family, FONT_SIZE_SMALL)
    bold_font = font(family, FONT_SIZE_HEADER, "bold")

    # --- общий фон ---
    for name in ("TFrame", "TLabelframe", "TPanedwindow", "TNotebook"):
        style.configure(name, background=palette["bg"], borderwidth=0)

    style.configure("TLabel", background=palette["bg"], foreground=palette["fg"], font=base_font)
    style.configure(
        "TLabelframe.Label",
        background=palette["bg"],
        foreground=palette["accent"],
        font=bold_font,
    )
    style.configure(
        "TLabelframe",
        background=palette["bg"],
        bordercolor=palette["border"],
        relief="solid",
        borderwidth=1,
    )
    style.configure("TPanedwindow", background=palette["bg"])

    # --- кнопки ---
    style.configure(
        "TButton",
        background=palette["bg_panel"],
        foreground=palette["fg"],
        bordercolor=palette["border"],
        focuscolor=palette["accent"],
        font=base_font,
        padding=(10, 4),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[
            ("pressed", palette["accent_dark"]),
            ("active", palette["bg_hover"]),
            ("disabled", palette["bg_panel"]),
        ],
        foreground=[("disabled", palette["fg_dim"])],
    )
    style.configure(
        "Accent.TButton",
        background=palette["accent_dark"],
        foreground=palette["fg_bright"],
        font=bold_font,
    )
    style.map(
        "Accent.TButton",
        background=[("pressed", palette["accent"]), ("active", palette["accent"])],
    )

    # --- поля ввода ---
    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(
            name,
            fieldbackground=palette["bg_field"],
            background=palette["bg_panel"],
            foreground=palette["fg"],
            bordercolor=palette["border"],
            arrowcolor=palette["fg"],
            insertcolor=palette["fg"],
            font=base_font,
        )
        style.map(
            name,
            fieldbackground=[("readonly", palette["bg_panel"]), ("disabled", palette["bg"])],
            foreground=[("disabled", palette["fg_dim"])],
        )
    style.configure(
        "TCombobox",
        selectbackground=palette["bg_panel"],
        selectforeground=palette["fg"],
    )
    try:
        root.option_add("*TCombobox*Listbox.background", palette["bg_panel"])
        root.option_add("*TCombobox*Listbox.foreground", palette["fg"])
        root.option_add("*TCombobox*Listbox.selectBackground", palette["selection"])
        root.option_add("*TCombobox*Listbox.selectForeground", palette["fg_bright"])
    except Exception:  # noqa: BLE001
        pass

    # --- флажки ---
    style.configure(
        "TCheckbutton",
        background=palette["bg"],
        foreground=palette["fg"],
        font=base_font,
        focuscolor=palette["accent"],
    )
    style.map(
        "TCheckbutton",
        background=[("active", palette["bg"])],
        foreground=[("disabled", palette["fg_dim"])],
        indicatorcolor=[
            ("selected", palette["accent_dark"]),
            ("!selected", palette["bg_field"]),
        ],
    )

    # --- таблица действий ---
    style.configure(
        "Treeview",
        background=palette["bg_field"],
        fieldbackground=palette["bg_field"],
        foreground=palette["fg"],
        bordercolor=palette["border"],
        font=small_font,
        rowheight=24,
    )
    style.map(
        "Treeview",
        background=[("selected", palette["selection"])],
        foreground=[("selected", palette["fg_bright"])],
    )
    style.configure(
        "Treeview.Heading",
        background=palette["bg_panel"],
        foreground=palette["accent"],
        font=bold_font,
        relief="flat",
    )
    style.map("Treeview.Heading", background=[("active", palette["bg_hover"])])

    # --- полосы прокрутки ---
    style.configure(
        "TScrollbar",
        background=palette["bg_panel"],
        troughcolor=palette["bg"],
        bordercolor=palette["border"],
        arrowcolor=palette["fg_dim"],
        relief="flat",
    )
    style.map("TScrollbar", background=[("active", palette["bg_hover"])])

    # --- статус-бар ---
    style.configure(
        "Status.TLabel",
        background=palette["bg_panel"],
        foreground=palette["fg_dim"],
        font=small_font,
        padding=(8, 4),
    )
    style.configure(
        "Hint.TLabel",
        background=palette["bg"],
        foreground=palette["fg_dim"],
        font=small_font,
    )

    return palette
