"""Главное окно PC Agent на tkinter.

Правила потоков (важно для стабильности):
  * агент выполняется в отдельном daemon-потоке;
  * поток агента общается с интерфейсом только через EventBus;
  * все виджеты tk обновляются в главном потоке из poll_once(),
    который планируется через root.after(POLL_INTERVAL_MS).

Любой тяжёлый импорт (capture, tools, agent.loop) выполняется лениво,
поэтому отсутствие ещё не готового модуля показывает ошибку в интерфейсе,
а не роняет приложение.
"""

from __future__ import annotations

import dataclasses
import inspect
import io
import json
import os
import threading
from pathlib import Path
from typing import Any, Callable

from pcagent import events as ev
from pcagent.config import CONFIRM_MODES, DEFAULT_CONFIG_PATH, AppConfig
from pcagent.events import AskBroker, Event, EventBus, kill_switch
from pcagent.gui import (
    agent_tuning,
    console_tools,
    chat_feed,
    credentials,
    paste as paste_shortcuts,
    screen_policy,
    theme,
    tool_router,
)
from pcagent.interfaces import RunResult

ChatFeed = chat_feed.ChatFeed

APP_TITLE = "PC Agent"
POLL_INTERVAL_MS = 100
FONT_FAMILY = "Segoe UI"
MAX_CHAT_LINES = 4000
PREVIEW_FALLBACK_SIZE = (420, 260)
TREE_COLUMNS = ("step", "tool", "status", "result")
#: Резервный лимит шагов, если в конфигурации лежит мусор вместо числа.
#: Заводское значение живёт в pcagent/config.py (AppConfig.max_steps).
GUI_DEFAULT_MAX_STEPS = 100

try:  # tkinter входит в стандартную библиотеку Windows
    import tkinter as tk
    from tkinter import messagebox, ttk

    TK_AVAILABLE = True
    TK_ERROR = ""
except Exception as _tk_exc:  # pragma: no cover - среда без графической подсистемы
    tk = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    TK_AVAILABLE = False
    TK_ERROR = str(_tk_exc)


def _provider_for(provider_id: str) -> Any:
    """Описание провайдера по идентификатору (или None)."""
    if not provider_id:
        return None
    try:
        from pcagent.gui import providers

        return providers.get_provider(provider_id)
    except Exception:  # noqa: BLE001
        return None


class AutoCaptureGate:
    """Обёртка над сервисом экрана: гасит автоматический стартовый снимок.

    Агентный цикл делает один снимок в начале задачи. Если пользователь
    выключил автоснимок, этот единственный вызов возвращает None, а все
    последующие (инструмент screenshot по запросу модели) проходят как
    обычно. Остальные методы сервиса делегируются без изменений.
    """

    def __init__(self, inner: Any, allow_initial: bool = False) -> None:
        self._inner = inner
        self._allow_initial = bool(allow_initial)
        self._initial_consumed = False

    def capture(self, *args: Any, **kwargs: Any) -> Any:
        if not self._initial_consumed:
            self._initial_consumed = True
            if not self._allow_initial:
                return None
        return self._inner.capture(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def shorten(text: Any, limit: int = 120) -> str:
    """Сжать текст в одну строку для таблицы действий."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: max(0, limit - 3)] + "..."


class AgentApp:
    """Окно PC Agent: чат, превью экрана, журнал действий, подтверждения."""

    def __init__(
        self,
        config: AppConfig | None = None,
        bus: EventBus | None = None,
        broker: AskBroker | None = None,
        *,
        agent_factory: Callable[..., Any] | None = None,
        auto_poll: bool = True,
        root: Any = None,
        project_root: str | Path | None = None,
    ) -> None:
        if not TK_AVAILABLE:
            raise RuntimeError(f"tkinter недоступен: {TK_ERROR}")

        self.config = config if config is not None else AppConfig()
        self.bus = bus if bus is not None else EventBus()
        self.broker = broker if broker is not None else AskBroker(self.bus)
        self.agent_factory = agent_factory
        self.auto_poll = bool(auto_poll)

        # --- состояние ---
        self.agent: Any | None = None
        self._worker: threading.Thread | None = None
        self._shot_thread: threading.Thread | None = None
        self._closed = False
        self._poll_job: Any = None
        self._asking = False
        # Очередь результата запроса баланса: сеть нельзя ждать в главном
        # потоке, а Tk нельзя трогать из чужого потока.
        self._balance_queue: list[tuple[bool, str]] = []
        self._balance_lock = threading.Lock()
        self._pending_asks: list[Any] = []
        self._done_seen = False
        # Снимки состояний чекбоксов: читаются ТОЛЬКО в главном потоке,
        # поток агента пользуется этими значениями (tk нельзя трогать извне).
        self._auto_confirm_snapshot = False
        self._dry_run_snapshot = bool(self.config.dry_run)
        self._auto_capture_snapshot = False
        self._step = 0
        self._max_steps = self.effective_max_steps()
        self._state = "готов"
        self._chat_lines = 0
        self._pending_rows: list[str] = []
        self._logger: Any = None
        self._screen: Any = None
        self._screen_gate: Any = None
        self._tool_routing_info: dict[str, Any] = {}
        self.preview_photo: Any = None
        self.preview_image: Any = None
        # --- ключ API и автонастройка ---
        self.key_source: credentials.KeySource | None = None
        self.key_verified: bool | None = None
        self._verify_lock = threading.Lock()
        self._verify_queue: list[tuple[Callable[..., None], Any]] = []
        #: Корень проекта для поиска .env и сохранения ключа.
        self.project_root = Path(project_root) if project_root is not None else DEFAULT_CONFIG_PATH.parent
        # --- вложения (картинки и документы из буфера) ---
        self.attachments: list[dict[str, Any]] = []
        self._attach_widgets: list[Any] = []
        self._attach_frame: Any = None
        self._attach_box: Any = None

        #: hwnd окна, исключённого из снимков (None - не применялось).
        self._capture_excluded_hwnd: int | None = None

        self.root = tk.Tk() if root is None else root
        self.root.title(APP_TITLE)
        self.root.geometry("1120x720")
        try:
            self.root.minsize(920, 560)
        except Exception:  # noqa: BLE001
            pass

        # Тема применяется до построения виджетов, чтобы ttk-стили
        # уже действовали на кнопки и таблицы.
        self.palette = theme.apply_theme(self.root)
        self.font_family = self.palette.get("font_family", theme.FONT_CANDIDATES[0])

        self._build_ui()
        # Своё окно исключается из снимков экрана: иначе модель видит на
        # снимке саму себя и свой чат вместо целевой программы.
        self._exclude_from_capture()
        self.install_crash_handlers()
        self._auto_connect()
        self._update_status()
        if self.auto_poll:
            self._schedule_poll()

    # ------------------------------------------------------------------
    # снимки экрана без собственного окна
    # ------------------------------------------------------------------
    def _exclude_from_capture(self) -> bool:
        """Исключить окно клиента из снимков экрана.

        Вызывается после построения интерфейса: окно уже создано, и
        Windows может принять режим исключения. Если выключено в
        конфигурации или система не поддерживает режим, снимки остаются
        как есть - поведение не ухудшается.
        """
        try:
            if not bool(getattr(self.config, "hide_from_screenshots", True)):
                return False
            from pcagent.gui import window_exclusion

            self.root.update_idletasks()
            hwnd = int(self.root.winfo_id())
            # winfo_id даёт внутреннее окно Tk: исключать нужно верхнеуровневое.
            try:
                import win32gui

                parent = win32gui.GetAncestor(hwnd, 2)
                if parent:
                    hwnd = int(parent)
            except Exception:  # noqa: BLE001 - без win32 работаем с тем, что есть
                pass

            applied = window_exclusion.apply_with_retry(hwnd)
            self._capture_excluded_hwnd = hwnd if applied else None
            if applied:
                self._append_chat(
                    "log",
                    "Собственное окно исключено из снимков экрана: модель видит "
                    "только другие программы",
                )
            return applied
        except Exception as exc:  # noqa: BLE001 - необязательная возможность
            self._append_chat("log", f"Исключение окна из снимков недоступно: {exc}")
            return False

    # ------------------------------------------------------------------
    # построение интерфейса
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.status_var = tk.StringVar(master=self.root, value="")
        status_bar = ttk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            style="Status.TLabel",
        )
        status_bar.pack(side="bottom", fill="x")

        container = ttk.Frame(self.root, padding=6)
        container.pack(side="top", fill="both", expand=True)

        paned = ttk.PanedWindow(container, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, padding=4)
        right = ttk.Frame(paned, padding=4)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        self._build_chat(left)
        # Лента в стиле мессенджера: сообщения пузырями, служебное - в раскрывашках.
        self.feed = ChatFeed(
            self.chat,
            {k: v for k, v in self.palette.items() if isinstance(v, str)},
            self.font_family,
        )
        self._build_input(left)
        self._build_actions_panel(left)
        self._build_side_panel(right)
        self._build_menu()

    def _build_chat(self, parent: Any) -> None:
        ttk.Label(parent, text="Диалог с агентом").pack(anchor="w")
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=(2, 0))

        p = self.palette
        family = self.font_family
        self.chat = tk.Text(
            frame,
            height=18,
            wrap="word",
            state="disabled",
            background=p["bg_field"],
            foreground=p["fg"],
            insertbackground=p["fg"],
            selectbackground=p["selection"],
            selectforeground=p["fg_bright"],
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=p["border"],
            highlightcolor=p["accent"],
            font=(family, theme.FONT_SIZE),
            padx=8,
            pady=6,
        )
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.chat.yview)
        self.chat.configure(yscrollcommand=scroll.set)
        self.chat.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.chat.tag_configure("user", foreground=p["accent"], font=(family, theme.FONT_SIZE, "bold"))
        self.chat.tag_configure(
            "thought", foreground=p["thought"], font=(family, theme.FONT_SIZE_SMALL, "italic")
        )
        self.chat.tag_configure("action", foreground=p["warning"])
        self.chat.tag_configure("result", foreground=p["success"])
        self.chat.tag_configure("error", foreground=p["error"])
        self.chat.tag_configure("status", foreground=p["fg_dim"])
        self.chat.tag_configure(
            "done", foreground=p["fg_bright"], font=(family, theme.FONT_SIZE, "bold")
        )
        self.chat.tag_configure("log", foreground=p["log"])
        # Текст в чате можно выделять и копировать при любой раскладке.
        paste_shortcuts.bind_edit_shortcuts(self.chat)
        # Клик по строке-заголовку раскрывает подробности хода агента.
        self.chat.bind("<Button-1>", self._on_chat_click, add="+")
        self.chat.tag_configure(
            "attachment", foreground=p["accent"], font=(family, theme.FONT_SIZE_SMALL)
        )

    def _build_input(self, parent: Any) -> None:
        ttk.Label(
            parent,
            text="Задача для агента (Enter - отправить, Shift+Enter - перенос строки):",
        ).pack(anchor="w", pady=(8, 2))
        frame = ttk.Frame(parent)
        frame.pack(fill="x")

        p = self.palette
        family = self.font_family
        self.input = tk.Text(
            frame,
            height=4,
            wrap="word",
            font=(family, theme.FONT_SIZE),
            padx=8,
            pady=6,
            background=p["bg_field"],
            foreground=p["fg"],
            insertbackground=p["fg"],
            selectbackground=p["selection"],
            selectforeground=p["fg_bright"],
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=p["border"],
            highlightcolor=p["accent"],
            undo=True,
        )
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.input.yview)
        self.input.configure(yscrollcommand=scroll.set)
        self.input.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Enter отправляет, Shift+Enter переносит строку.
        self.input.bind("<Return>", self._on_enter)
        self.input.bind("<KP_Enter>", self._on_enter)
        self.input.bind("<Shift-Return>", self._on_shift_enter)
        self.input.bind("<Shift-KP_Enter>", self._on_shift_enter)
        # Ctrl+V перехватываем: в буфере может быть картинка или файл.
        # Привязка идёт по КОДУ клавиши: при русской раскладке Tk присылает
        # keysym "??" вместо "v", и обычный <Control-v> не срабатывает.
        paste_shortcuts.bind_paste(self.input, self._on_paste)
        # Ctrl+C, Ctrl+X, Ctrl+A при русской раскладке дают keysym "??",
        # и стандартные привязки Tk не срабатывают. Ловим по коду клавиши.
        paste_shortcuts.bind_edit_shortcuts(self.input)

        self._build_attachments(parent)

        buttons = ttk.Frame(parent)
        buttons.pack(fill="x", pady=(6, 0))
        self._buttons_frame = buttons
        self.send_button = ttk.Button(
            buttons, text="Отправить", command=self.on_send, style="Accent.TButton"
        )
        self.send_button.pack(side="left")
        self.stop_button = ttk.Button(
            buttons, text="Стоп", command=self.on_stop, state="disabled"
        )
        self.stop_button.pack(side="left", padx=(6, 0))
        self.shot_button = ttk.Button(
            buttons, text="Скриншот сейчас", command=self.on_screenshot
        )
        self.shot_button.pack(side="left", padx=(6, 0))

        options = ttk.Frame(parent)
        options.pack(fill="x", pady=(6, 0))
        # ВАЖНО: по умолчанию автоподтверждение ВЫКЛЮЧЕНО. Агент управляет
        # реальной машиной (закрытие окон, kill_process, run_command), поэтому
        # опасные действия должны подтверждаться человеком. Автоподтверждение
        # включается только осознанно - галочкой или ключом auto_confirm в YAML.
        saved_confirm = (getattr(self.config, "extra", None) or {}).get("auto_confirm")
        default_confirm = bool(saved_confirm) if saved_confirm is not None else False
        self.auto_confirm_var = tk.BooleanVar(master=self.root, value=default_confirm)
        self.auto_confirm_check = ttk.Checkbutton(
            options,
            text="Автоподтверждение опасных действий",
            variable=self.auto_confirm_var,
        )
        self.auto_confirm_check.pack(side="left")
        self.dry_run_var = tk.BooleanVar(master=self.root, value=bool(self.config.dry_run))
        self.dry_run_check = ttk.Checkbutton(
            options, text="Dry-run", variable=self.dry_run_var
        )
        self.dry_run_check.pack(side="left", padx=(14, 0))
        # Автоснимок в начале задачи выключен: экран снимается только
        # по кнопке или когда снимок запросит сам агент.
        saved_capture = bool((getattr(self.config, "extra", None) or {}).get("auto_capture", False))
        self.auto_capture_var = tk.BooleanVar(master=self.root, value=saved_capture)
        self.auto_capture_check = ttk.Checkbutton(
            options,
            text="Снимок экрана в начале задачи",
            variable=self.auto_capture_var,
        )
        self.auto_capture_check.pack(side="left", padx=(14, 0))

    def _build_actions_panel(self, parent: Any) -> None:
        box = ttk.LabelFrame(parent, text="Действия", padding=4)
        box.pack(fill="both", expand=True, pady=(8, 0))
        frame = ttk.Frame(box)
        frame.pack(fill="both", expand=True)

        self.actions = ttk.Treeview(
            frame, columns=TREE_COLUMNS, show="headings", height=8
        )
        self.actions.heading("step", text="Шаг")
        self.actions.column("step", width=52, anchor="center", stretch=False)
        self.actions.heading("tool", text="Инструмент")
        self.actions.column("tool", width=150, anchor="w", stretch=False)
        self.actions.heading("status", text="Статус")
        self.actions.column("status", width=90, anchor="center", stretch=False)
        self.actions.heading("result", text="Краткий результат")
        self.actions.column("result", width=320, anchor="w")

        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.actions.yview)
        self.actions.configure(yscrollcommand=scroll.set)
        self.actions.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _build_side_panel(self, parent: Any) -> None:
        preview_box = ttk.LabelFrame(parent, text="Экран", padding=4)
        preview_box.pack(fill="both", expand=True)
        p = self.palette
        self.preview_label = tk.Label(
            preview_box,
            text="Снимков пока нет",
            anchor="center",
            background=p["bg_field"],
            foreground=p["fg_dim"],
            font=(self.font_family, theme.FONT_SIZE_SMALL),
        )
        self.preview_label.pack(fill="both", expand=True)

        self.preview_info = tk.StringVar(master=self.root, value="")
        ttk.Label(preview_box, textvariable=self.preview_info, anchor="w").pack(
            fill="x", pady=(4, 0)
        )

        info_box = ttk.LabelFrame(parent, text="Подсказки", padding=6)
        info_box.pack(fill="x", pady=(6, 0))
        ttk.Label(
            info_box,
            anchor="w",
            justify="left",
            wraplength=380,
            text=(
                "Стоп-кран останавливает агента после текущего шага. "
                "Dry-run выполняет инструменты без реальных действий. "
                "Подтверждения приходят в это окно."
            ),
        ).pack(fill="x")

    def show_balance_async(self) -> None:
        """Показать остаток токенов по ключу (запрос в фоне)."""
        self._append_chat("status", "Запрашиваю остаток токенов...")

        def worker() -> None:
            try:
                text = self._query_balance_text()
            except Exception as exc:  # noqa: BLE001 - показываем, не падаем
                text = f"Не удалось узнать остаток: {type(exc).__name__}: {exc}"
            with self._balance_lock:
                self._balance_queue.append((True, text))

        threading.Thread(target=worker, name="pcagent-gui-balance", daemon=True).start()

    def _query_balance_text(self) -> str:
        """Синхронный запрос остатка. Вызывается только из рабочего потока."""
        from pcagent.gui import providers

        key = ""
        try:
            key = str(self.config.resolve_api_key() or "").strip()
        except Exception:  # noqa: BLE001
            key = str(getattr(self.config, "api_key", "") or "").strip()
        if not key:
            return "Ключ API не найден: откройте Файл - Ключ API..."

        provider = providers.detect_provider(key)
        if provider is None:
            return "Не удалось определить провайдера по ключу"

        extra = dict(getattr(self.config, "extra", None) or {})
        base_url = extra.get("base_url") or None
        balance, error = providers.fetch_balance(provider, key, base_url=base_url)
        if balance is None:
            return f"Остаток: неизвестен - {error}"

        lines = [
            f"Провайдер: {provider.title}",
            f"Остаток: {balance.describe()}",
        ]
        if balance.tokens is not None:
            multipliers = providers.fetch_multipliers(provider, key, base_url=base_url)
            current = str(self.config.model or "")
            if current and current in multipliers:
                share = int(balance.tokens / multipliers[current])
                lines.append(
                    f"В токенах модели {current} (множитель {multipliers[current]:g}): "
                    + f"~{share:,}".replace(",", " ")
                )
        return "\n".join(lines)

    def _drain_balance_results(self) -> int:
        """Показать результат запроса баланса в главном потоке."""
        with self._balance_lock:
            pending = list(self._balance_queue)
            self._balance_queue.clear()
        for _ok, text in pending:
            for line in str(text).splitlines():
                self._append_chat("status", line)
        return len(pending)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Ключ API...", command=self.open_api_key_dialog)
        file_menu.add_command(label="Настройки...", command=self.open_settings_dialog)
        file_menu.add_command(label="Остаток токенов...", command=self.show_balance_async)
        file_menu.add_command(label="Открыть папку журнала", command=self.open_log_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.close)
        menubar.add_cascade(label="Файл", menu=file_menu)
        self.menu = menubar
        try:
            self.root.configure(menu=menubar)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # публичные методы жизненного цикла
    # ------------------------------------------------------------------
    def run(self) -> int:
        """Показать окно и войти в mainloop. Возвращает код выхода."""
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._start_hotkey()
        if self._poll_job is None and not self._closed:
            self._schedule_poll()
        try:
            self.root.mainloop()
        except KeyboardInterrupt:  # pragma: no cover - ручное прерывание
            self.close()
        return 0

    def _start_hotkey(self) -> None:
        """Глобальный стоп-кран: работает, даже когда окно не в фокусе."""
        self._hotkey: Any = None
        combination = str(getattr(self.config, "stop_hotkey", "") or "").strip()
        if not combination:
            return
        try:
            from pcagent.hotkey import HotkeyListener

            listener = HotkeyListener(combination, callback=self._on_hotkey, logger=self._logger)
        except Exception as exc:  # noqa: BLE001 - без клавиши приложение живёт
            self.bus.publish(ev.Event.log(f"Стоп-кран недоступен: {exc}"))
            return
        if listener.start():
            self._hotkey = listener
            self.bus.publish(ev.Event.log(f"Стоп-кран: {combination}"))
        else:
            self.bus.publish(ev.Event.log(f"Стоп-кран не зарегистрирован: {listener.error}"))

    def _on_hotkey(self) -> None:
        """Вызывается из потока горячей клавиши: только потокобезопасные действия."""
        try:
            kill_switch.trigger()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.broker.cancel_all()
        except Exception:  # noqa: BLE001
            pass
        self.bus.publish(ev.Event.status("Стоп-кран: агент остановлен горячей клавишей"))

    def close(self) -> None:
        """Аккуратно закрыть окно: остановить агента и снять таймер."""
        if self._closed:
            return
        self._closed = True
        hotkey = getattr(self, "_hotkey", None)
        if hotkey is not None:
            try:
                hotkey.stop()
            except Exception:  # noqa: BLE001
                pass
            self._hotkey = None
        if self._poll_job is not None:
            try:
                self.root.after_cancel(self._poll_job)
            except Exception:  # noqa: BLE001
                pass
            self._poll_job = None
        try:
            kill_switch.trigger()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.broker.cancel_all()
        except Exception:  # noqa: BLE001
            pass
        self._close_runtime_resources()
        # Снять исключение из захвата: окно уничтожается, но режим лучше
        # вернуть явно, чтобы не осталось следов в системе.
        excluded = getattr(self, "_capture_excluded_hwnd", None)
        if excluded:
            try:
                from pcagent.gui import window_exclusion

                window_exclusion.restore(excluded)
            except Exception:  # noqa: BLE001
                pass
            self._capture_excluded_hwnd = None
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # обработка шины событий
    # ------------------------------------------------------------------
    def _schedule_poll(self) -> None:
        if self._closed:
            return
        self._poll_job = self.root.after(POLL_INTERVAL_MS, self._poll)

    def _poll(self) -> None:
        self._poll_job = None
        if self._closed:
            return
        # Пока открыт модальный диалог подтверждения, шину не читаем:
        # вложенный цикл событий Tk иначе вызовет poll повторно и
        # отклонит запрос, который пользователь ещё не видел.
        if self._asking:
            self._schedule_poll()
            return
        try:
            self.poll_once()
        finally:
            if not self._closed:
                self._schedule_poll()

    def poll_once(self, limit: int = 500) -> int:
        """Разобрать накопленные события шины. Возвращает их количество."""
        self._drain_verify_results()
        self._drain_balance_results()
        processed = 0
        for event in self.bus.drain(limit=limit):
            processed += 1
            try:
                self._handle_event(event)
            except Exception as exc:  # noqa: BLE001 - UI не должен падать
                self._append_chat("error", f"Ошибка обработки события {event.kind}: {exc}")
        return processed

    def _handle_event(self, event: Event) -> None:
        kind = event.kind
        if kind == ev.KIND_STATUS:
            self._set_state(event.text or self._state)
            self._append_chat("status", event.text)
        elif kind == ev.KIND_THOUGHT:
            self._append_chat("thought", f"Мысль: {event.text}")
        elif kind == ev.KIND_ACTION:
            self._handle_action(event)
        elif kind == ev.KIND_RESULT:
            self._handle_result(event)
        elif kind == ev.KIND_ERROR:
            self._append_chat("error", f"Ошибка: {event.text}")
            self._set_state("ошибка")
        elif kind == ev.KIND_IMAGE:
            self._handle_image(event)
        elif kind == ev.KIND_STEP:
            self._handle_step(event)
        elif kind == ev.KIND_DONE:
            self._handle_done(event)
        elif kind == ev.KIND_ASK:
            self._handle_ask(event)
        elif kind == ev.KIND_LOG:
            self._append_chat("log", event.text)
        # KIND_ANSWER и незнакомые виды событий просто игнорируются

    def _handle_action(self, event: Event) -> None:
        name = event.text or "инструмент"
        # Модель сделала шаг: следующий снимок снова осмыслен.
        gate = self._screen_gate
        if gate is not None:
            try:
                gate.note_action()
            except Exception:  # noqa: BLE001 - телеметрия не критична
                pass
        self._update_status()
        args = dict((event.data or {}).get("args") or {})
        self._append_chat("action", f"Действие: {name} {shorten(json.dumps(args, ensure_ascii=False), 160)}")
        step_label = str(self._step) if self._step else "-"
        row = self.actions.insert(
            "", "end", values=(step_label, name, "выполняется", shorten(args, 120))
        )
        self._pending_rows.append(row)
        try:
            self.actions.see(row)
        except Exception:  # noqa: BLE001
            pass

    def _handle_result(self, event: Event) -> None:
        data = event.data or {}
        name = data.get("name") or "инструмент"
        ok = bool(data.get("ok"))
        summary = event.text or ""
        self._append_chat("result", f"Результат {name}: {summary}")
        row = self._pending_rows.pop(0) if self._pending_rows else None
        if row is not None:
            try:
                values = list(self.actions.item(row, "values"))
                while len(values) < 4:
                    values.append("")
                values[2] = "ок" if ok else "ошибка"
                values[3] = shorten(summary, 160)
                self.actions.item(row, values=values)
            except Exception:  # noqa: BLE001
                pass

    def _handle_step(self, event: Event) -> None:
        data = event.data or {}
        try:
            number = int(data.get("number", event.text or 0))
        except (TypeError, ValueError):
            number = self._step
        self._step = max(0, number)
        self._append_chat("status", f"Шаг {self._step} из {self._max_steps}")
        self._update_status()

    def _handle_image(self, event: Event) -> None:
        payload = event.image_bytes
        if payload is None and event.image_path:
            try:
                payload = Path(event.image_path).read_bytes()
            except Exception as exc:  # noqa: BLE001
                self._append_chat("error", f"Не удалось прочитать снимок: {exc}")
                return
        if not payload:
            # Пустой снимок - это нормальный случай: автоснимок выключен
            # или сервис экрана недоступен. В чат не пишем, чтобы не шуметь.
            return
        if self.set_preview(payload):
            info = event.data or {}
            width = info.get("width")
            height = info.get("height")
            size = f"{width}x{height}" if width and height else ""
            self.preview_info.set(f"Снимок обновлён {size}".strip())
            self._append_chat("status", f"Снимок экрана обновлён {size}".strip())

    def _handle_done(self, event: Event) -> None:
        if self._done_seen:
            return
        self._done_seen = True
        payload = event.data or {}
        success = bool(payload.get("success"))
        final_text = str(payload.get("final_text") or "").strip()
        error = payload.get("error")
        try:
            steps = int(payload.get("steps") or 0)
        except (TypeError, ValueError):
            steps = 0
        if steps > self._step:
            self._step = steps
        if final_text:
            self._append_chat("done", f"Итог: {final_text}")
        if error:
            self._append_chat("error", f"Ошибка: {error}")
        self._set_state("задача выполнена" if success else "задача завершена с ошибкой")
        self._append_chat(
            "status",
            f"Готово: {'успех' if success else 'ошибка'}, шагов: {self._step}",
        )
        self._set_running(False)
        self._update_status()

    def _handle_ask(self, event: Event) -> None:
        data = event.data or {}
        request_id = str(data.get("request_id") or "")
        details = str(data.get("details") or "")
        question = event.text or "Разрешить действие?"
        if self._asking:
            # Диалог уже открыт: ставим запрос в очередь, а не отклоняем.
            self._pending_asks.append(event)
            return

        # Автоподтверждение: клиент отвечает сам, диалог не открывается.
        if bool(self.auto_confirm_var.get()):
            self._auto_confirm_snapshot = True
            self._append_chat("status", f"Автоподтверждение: {question}")
            if request_id:
                try:
                    self.broker.answer(request_id, True)
                except Exception:  # noqa: BLE001
                    pass
            self._append_chat("status", "Подтверждение: да (автоматически)")
            return

        self._append_chat("status", f"Требуется подтверждение: {question}")
        try:
            approved = bool(self.ask_user(question, details))
        except Exception as exc:  # noqa: BLE001 - отказ лучше падения
            approved = False
            self._append_chat("error", f"Ошибка диалога подтверждения: {exc}")
        answered = False
        if request_id:
            try:
                answered = bool(self.broker.answer(request_id, approved))
            except Exception:  # noqa: BLE001
                answered = False
        self._append_chat(
            "status",
            ("Подтверждение: да" if approved else "Подтверждение: нет")
            + ("" if answered else " (запрос уже неактуален)"),
        )
        self._drain_pending_asks()

    def ask_user(self, question: str, details: str = "") -> bool:
        """Модальное подтверждение в главном потоке.

        Выделен в отдельный метод, чтобы тесты могли подменить диалог.
        Окно поднимается наверх: иначе диалог оказывается за главным
        окном, приложение выглядит зависшим, а агент ждёт ответа.
        """
        self._auto_confirm_snapshot = bool(self.auto_confirm_var.get())
        if self._auto_confirm_snapshot:
            return True
        if self._asking:
            # Повторный запрос во время открытого диалога не отклоняем
            # молча - откладываем, чтобы пользователь увидел его следом.
            self._pending_asks.append((question, details))
            return False

        self._asking = True
        previous_state = self._state
        self._set_state("ожидает подтверждения")
        try:
            self._raise_window()
            text = question if not details else f"{question}\n\n{details}"
            return bool(messagebox.askyesno(APP_TITLE, text, parent=self.root))
        finally:
            self._asking = False
            self._set_state(previous_state or "готов")

    def _raise_window(self) -> None:
        """Поднять окно наверх, чтобы диалог был виден."""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.update_idletasks()
            # снимаем topmost, иначе окно перекрывает другие приложения
            self.root.after(300, lambda: self._drop_topmost())
        except Exception:  # noqa: BLE001 - оформление не должно ломать диалог
            pass

    def _drop_topmost(self) -> None:
        try:
            self.root.attributes("-topmost", False)
        except Exception:  # noqa: BLE001
            pass

    def _drain_pending_asks(self) -> None:
        """Показать отложенные запросы подтверждения после текущего.

        Запросы, пришедшие во время открытого диалога, ждут в очереди:
        молча отклонять их нельзя, иначе агент получит ложный отказ.
        """
        while self._pending_asks and not self._asking:
            item = self._pending_asks.pop(0)
            if isinstance(item, Event):
                self._handle_ask(item)
            else:
                question, details = item
                self._append_chat("status", f"Требуется подтверждение: {question}")

    # ------------------------------------------------------------------
    # защита от падений: любые необработанные ошибки -> в чат и журнал
    # ------------------------------------------------------------------
    def install_crash_handlers(self) -> None:
        """Перехватить необработанные ошибки Tk и потоков.

        Без этого исключение в callback Tk уходит в stderr, которого у
        GUI-приложения нет: окно просто исчезает без следов.
        """
        try:
            self.root.report_callback_exception = self._on_tk_exception
        except Exception:  # noqa: BLE001
            pass
        try:
            threading.excepthook = self._on_thread_exception
        except Exception:  # noqa: BLE001
            pass

    def _write_crash_log(self, title: str, text: str) -> str | None:
        """Записать аварийный отчёт в logs/crash-<время>.log."""
        try:
            from datetime import datetime

            folder = Path(self.config.log_path)
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = folder / f"crash-{stamp}.log"
            target.write_text(f"{title}\n\n{text}", encoding="utf-8")
            return str(target)
        except Exception:  # noqa: BLE001 - отчёт не должен падать сам
            return None

    def _on_tk_exception(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Ошибка в обработчике Tk: показать и записать, не закрывая окно."""
        import traceback

        text = "".join(traceback.format_exception(exc_type, exc, tb))
        path = self._write_crash_log("Ошибка в обработчике интерфейса", text)
        message = f"Внутренняя ошибка интерфейса: {exc_type.__name__}: {exc}"
        if path:
            message += f" (отчёт: {path})"
        try:
            self._append_chat("error", message)
            self._set_state("ошибка интерфейса")
        except Exception:  # noqa: BLE001
            pass

    def _on_thread_exception(self, args: Any) -> None:
        """Необработанная ошибка в фоновом потоке агента."""
        import traceback

        name = getattr(getattr(args, "thread", None), "name", "?")
        text = "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        )
        path = self._write_crash_log(f"Необработанная ошибка в потоке {name}", text)
        message = f"Сбой в потоке {name}: {args.exc_type.__name__}: {args.exc_value}"
        if path:
            message += f" (отчёт: {path})"
        try:
            self.bus.publish(ev.Event.error(message))
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # вложения: картинки и документы из буфера обмена
    # ------------------------------------------------------------------
    def _build_attachments(self, parent: Any) -> None:
        """Панель приложенных файлов: появляется только когда есть вложения."""
        self._attach_frame = ttk.LabelFrame(parent, text="Вложения", padding=4)
        self._attach_box = ttk.Frame(self._attach_frame)
        self._attach_box.pack(fill="x")
        # панель скрыта, пока нет вложений
        self._attach_visible = False

    def attachments_dir(self) -> Path:
        """Каталог для сохранённых вложений."""
        target = Path(self.config.log_path) / "attachments"
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001 - без каталога работаем во временном
            import tempfile

            target = Path(tempfile.gettempdir()) / "pcagent-attachments"
            target.mkdir(parents=True, exist_ok=True)
        return target

    def add_attachment(self, path: str | Path, kind: str = "file", note: str = "") -> dict[str, Any]:
        """Добавить вложение в список и обновить панель."""
        item = {
            "path": str(path),
            "kind": kind,
            "name": Path(path).name,
            "note": note,
        }
        self.attachments.append(item)
        self._refresh_attachments()
        self._append_chat("attachment", f"Вложение: {item['name']} ({kind})")
        return item

    def remove_attachment(self, item: dict[str, Any]) -> None:
        """Убрать вложение из списка."""
        try:
            self.attachments.remove(item)
        except ValueError:
            pass
        self._refresh_attachments()

    def clear_attachments(self) -> None:
        """Очистить список вложений после отправки."""
        self.attachments.clear()
        self._refresh_attachments()

    def _refresh_attachments(self) -> None:
        """Перерисовать панель вложений (только главный поток)."""
        box = self._attach_box
        if box is None:
            return
        for widget in self._attach_widgets:
            try:
                widget.destroy()
            except Exception:  # noqa: BLE001
                pass
        self._attach_widgets = []

        p = self.palette
        family = self.font_family
        for item in self.attachments:
            row = ttk.Frame(box)
            row.pack(fill="x", pady=1)
            icon = "IMG" if item["kind"] == "image" else "FILE"
            label = tk.Label(
                row,
                text=f"{icon}  {item['name']}",
                anchor="w",
                background=p["bg_panel"],
                foreground=p["accent"] if item["kind"] == "image" else p["fg"],
                font=(family, theme.FONT_SIZE_SMALL),
                padx=6,
                pady=2,
            )
            label.pack(side="left", fill="x", expand=True)

            remove = ttk.Button(
                row, text="x", width=3, command=lambda it=item: self.remove_attachment(it)
            )
            remove.pack(side="right", padx=(4, 0))
            self._attach_widgets.extend([row, label, remove])

        # показываем или прячем саму панель
        if self.attachments and not getattr(self, "_attach_visible", False):
            self._attach_frame.pack(fill="x", pady=(6, 0), before=self._buttons_frame)
            self._attach_visible = True
        elif not self.attachments and getattr(self, "_attach_visible", False):
            self._attach_frame.pack_forget()
            self._attach_visible = False

    def _save_clipboard_image(self, image: Any) -> Path | None:
        """Сохранить картинку из буфера в файл."""
        try:
            from datetime import datetime

            name = "clipboard-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".png"
            target = self.attachments_dir() / name
            image.save(target, format="PNG")
            return target
        except Exception as exc:  # noqa: BLE001
            self._append_chat("error", f"Не удалось сохранить картинку: {exc}")
            return None

    def _collect_clipboard(self) -> tuple[Any, list[str]]:
        """Прочитать буфер: вернуть (изображение|None, список путей к файлам)."""
        image = None
        files: list[str] = []
        try:
            from PIL import ImageGrab

            data = ImageGrab.grabclipboard()
            if data is None:
                return None, []
            if isinstance(data, list):
                files = [str(item) for item in data if isinstance(item, str)]
            else:
                image = data
        except Exception:  # noqa: BLE001 - буфер может быть недоступен
            return None, []
        return image, files

    def paste_from_clipboard(self) -> bool:
        """Вставить из буфера: картинку, файлы или текст.

        Возвращает True, если вставка обработана как вложение.
        """
        image, files = self._collect_clipboard()

        handled = False
        if image is not None:
            path = self._save_clipboard_image(image)
            if path is not None:
                self.add_attachment(path, kind="image", note="изображение из буфера")
                handled = True
        if files:
            for path in files:
                suffix = Path(path).suffix.lower()
                kind = "image" if suffix in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp") else "file"
                self.add_attachment(path, kind=kind, note="файл из буфера")
            handled = True

        if handled:
            return True

        # обычный текст: вставляем в позицию курсора
        text = credentials.read_clipboard(self.input)
        if text:
            try:
                self.input.insert("insert", text)
            except Exception:  # noqa: BLE001
                pass
            return False
        self._append_chat("status", "Буфер обмена пуст")
        return False

    def _on_paste(self, _event: Any = None) -> str:
        """Ctrl+V: вложения обрабатываем сами, текст вставляем как обычно."""
        if self.paste_from_clipboard():
            return "break"
        return "break"

    def compose_task(self, task: str) -> str:
        """Дополнить текст задачи списком вложений для агента."""
        text = (task or "").strip()
        if not self.attachments:
            return text
        lines = [text, "", "Приложенные файлы (доступны по путям):"]
        for item in self.attachments:
            lines.append(f"- {item['path']} [{item['kind']}]")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # действия пользователя
    # ------------------------------------------------------------------
    def _on_enter(self, _event: Any = None) -> str:
        """Enter отправляет задачу."""
        self.on_send()
        return "break"

    def _on_shift_enter(self, _event: Any = None) -> str | None:
        """Shift+Enter вставляет перенос строки."""
        try:
            self.input.insert("insert", "\n")
        except Exception:  # noqa: BLE001
            pass
        return "break"

    def _on_ctrl_enter(self, _event: Any = None) -> str:
        self.on_send()
        return "break"

    def on_send(self) -> None:
        """Отправить задачу из поля ввода агенту."""
        task = ""
        try:
            task = self.input.get("1.0", "end").strip()
        except Exception:  # noqa: BLE001
            task = ""
        if not task and not self.attachments:
            self._append_chat("status", "Введите задачу перед отправкой")
            return
        if not task:
            task = "Посмотри приложенные файлы и опиши их."
        composed = self.compose_task(task)
        if self.start_task(composed):
            try:
                self.input.delete("1.0", "end")
            except Exception:  # noqa: BLE001
                pass
            self.clear_attachments()

    def start_task(self, task: str) -> bool:
        """Запустить агента в фоновом потоке. Возвращает признак запуска."""
        task = (task or "").strip()
        if not task:
            return False
        if self._worker is not None and self._worker.is_alive():
            self._append_chat("error", "Агент уже выполняет задачу")
            return False

        if not self.has_api_key():
            self.open_api_key_dialog()
            if not self.has_api_key():
                self._append_chat(
                    "error",
                    "Задача не запущена: нужен ключ API "
                    "(Файл - Ключ API...) или stub-режим в config.yaml",
                )
                return False

        self._done_seen = False
        self._step = 0
        self._pending_rows.clear()
        self._screen_gate = None  # новый агент создаст свой гейт и бюджет
        self.read_option_flags()  # главный поток: фиксируем чекбоксы для агента
        try:
            kill_switch.reset()
        except Exception:  # noqa: BLE001
            pass

        self._append_chat("user", task)
        self._set_state("выполняется")
        self._set_running(True)
        self._update_status()

        self._worker = threading.Thread(
            target=self._worker_main,
            args=(task,),
            name="pcagent-gui-agent",
            daemon=True,
        )
        self._worker.start()
        return True

    def on_stop(self) -> None:
        """Стоп-кран: остановить агента и снять все ожидания подтверждений."""
        try:
            kill_switch.trigger()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.broker.cancel_all()
        except Exception:  # noqa: BLE001
            pass
        agent = self.agent
        stop = getattr(agent, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:  # noqa: BLE001
                pass
        self._append_chat("status", "Запрошена остановка (стоп-кран)")
        self._set_state("остановка")

    def on_screenshot(self) -> None:
        """Сделать снимок экрана в фоновом потоке и показать его справа."""
        self._shot_thread = threading.Thread(
            target=self._capture_worker, name="pcagent-gui-shot", daemon=True
        )
        self._shot_thread.start()

    def _capture_worker(self) -> None:
        try:
            shot = self._take_screenshot()
            self.bus.publish(
                ev.Event.image(
                    getattr(shot, "path", None),
                    getattr(shot, "image_bytes", None),
                    **shot.as_dict(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - показываем в чате, не падаем
            self.bus.publish(ev.Event.error(f"Не удалось сделать снимок экрана: {exc}"))

    def _take_screenshot(self) -> Any:
        """Ленивый снимок экрана через pcagent.capture.Screen."""
        from pcagent.capture import Screen

        screen = Screen()
        try:
            return screen.capture(monitor=self.config.monitor)
        finally:
            try:
                screen.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # настройки и журнал
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # ключ API: автоматический поиск и подключение
    # ------------------------------------------------------------------
    def show_privacy_notice(self, key: str | None = None) -> None:
        """Предупредить, что посредник видит скриншоты, задачи и ключ.

        Показывается один раз на провайдера, чтобы не спамить в чат при
        каждом запуске задачи. Для официального API молчит.
        """
        try:
            from pcagent.gui import providers

            value = key
            if value is None:
                try:
                    value = str(self.config.resolve_api_key() or "")
                except Exception:  # noqa: BLE001
                    value = str(getattr(self.config, "api_key", "") or "")
            provider = providers.detect_provider(value or "")
            if provider is None:
                return
            if providers.is_official(provider):
                return
            if getattr(self, "_privacy_shown_for", None) == provider.id:
                return
            self._privacy_shown_for = provider.id
            self._append_chat(
                "action",
                "ВНИМАНИЕ: " + providers.privacy_notice(provider, str(self.config.model or "")),
            )
        except Exception as exc:  # noqa: BLE001 - предупреждение не должно ломать запуск
            self._append_chat("log", f"Предупреждение о провайдере пропущено: {exc}")

    def _auto_connect(self) -> None:
        """Подтянуть настройки машины и найденный ключ API при старте окна."""
        try:
            changes = credentials.autoconfigure(self.config)
        except Exception as exc:  # noqa: BLE001 - автонастройка не критична
            self._append_chat("log", f"Автонастройка пропущена: {exc}")
            changes = {}
        if changes.get("config_file"):
            self._append_chat("status", f"Создан файл настроек: {changes['config_file']}")

        try:
            source = credentials.resolve_best_key(
                self.config, project_root=self.project_root
            )
        except Exception as exc:  # noqa: BLE001
            self._append_chat("error", f"Поиск ключа API не удался: {exc}")
            source = None

        if source is None:
            self.key_source = None
            self._append_chat(
                "status",
                "Ключ API не найден. Нажмите Файл - Ключ API... и вставьте ключ "
                "любого провайдера (Google, OpenAI, DeepSeek, OpenRouter...): "
                "адрес API и модель подхватятся автоматически.",
            )
            return

        credentials.apply_key(self.config, source)
        self.key_source = source
        self.key_verified = None
        self._append_chat("status", f"Ключ API подключён автоматически ({source.describe()})")

        # Модель должна соответствовать провайдеру: ключ посредника с моделью
        # gemini-2.5-flash получает 403 "model is not enabled". Подбираем
        # рабочую модель один раз при старте, если текущая не подходит.
        self._ensure_model_matches_provider(source.key)
        # Если ключ принадлежит посреднику, предупредить о передаче данных.
        self.show_privacy_notice(source.key)

    def _ensure_model_matches_provider(self, key: str) -> None:
        """Подобрать модель под провайдера ключа.

        Имена моделей несовместимы между провайдерами: gemini-2.5-flash у
        посредника получает 403 "model is not enabled". Если в конфигурации
        стоит "auto" или чужая модель, подбираем рабочую.
        """
        try:
            from pcagent.gui import providers

            provider = providers.detect_provider(key)
            if provider is None:
                return
            extra = dict(getattr(self.config, "extra", None) or {})
            extra["provider"] = provider.id
            if provider.google_sdk:
                extra.pop("base_url", None)
            elif provider.base_url:
                extra["base_url"] = provider.base_url.rstrip("/")
            self.config.extra = extra

            chosen = providers.resolve_model(
                provider,
                str(self.config.model or ""),
                key=key,
                base_url=extra.get("base_url"),
                timeout_s=25,
            )
            if chosen:
                self.config.model = chosen
                self._append_chat(
                    "status",
                    f"Модель для {provider.title}: {chosen}",
                )
        except Exception as exc:  # noqa: BLE001 - подбор не должен ломать запуск
            self._append_chat("log", f"Подбор модели пропущен: {exc}")

    def apply_api_key(
        self,
        key: str,
        save: bool = True,
        path: str | Path | None = None,
        base_url: str | None = None,
    ) -> bool:
        """Применить ключ, введённый пользователем, и (необязательно) сохранить."""
        value = (key or "").strip()
        if not value:
            self._append_chat("error", "Пустой ключ API")
            return False
        source = credentials.KeySource(value, "введён вручную")
        credentials.apply_key(self.config, source)
        self.key_source = source
        self.key_verified = None
        self._append_chat("status", f"Ключ API принят ({source.masked})")

        # Параметры провайдера подтягиваются по самому ключу.
        try:
            from pcagent.gui import providers

            provider = providers.detect_provider(value)
            if provider is not None:
                self.apply_provider_settings(provider, base_url=base_url)
            elif base_url:
                self.apply_provider_settings(providers.PROVIDERS_BY_ID["openai"], base_url=base_url)
        except Exception as exc:  # noqa: BLE001 - провайдер необязателен
            self._append_chat("log", f"Провайдер не определён: {exc}")

        if save:
            try:
                target = credentials.save_key(
                    value, path=path, project_root=self.project_root
                )
                self._append_chat("status", f"Ключ сохранён в {target}")
            except Exception as exc:  # noqa: BLE001 - ключ уже работает в памяти
                self._append_chat("error", f"Не удалось сохранить ключ: {exc}")
        # Ключ мог смениться на другого провайдера: показываем заново.
        self._privacy_shown_for = None
        self.show_privacy_notice(value)
        self._update_status()
        return True

    def apply_provider_settings(
        self, provider: Any, model: str | None = None, base_url: str | None = None
    ) -> None:
        """Прописать провайдера, base_url и модель в конфигурацию."""
        if provider is None:
            return
        extra = dict(getattr(self.config, "extra", None) or {})
        extra["provider"] = provider.id
        # Google работает через официальный SDK: адрес API ему не нужен, а
        # оставшийся от другого провайдера base_url только запутает проверку.
        if getattr(provider, "google_sdk", False):
            extra.pop("base_url", None)
        else:
            resolved_base = (base_url or provider.base_url or "").rstrip("/")
            if resolved_base:
                extra["base_url"] = resolved_base
            else:
                extra.pop("base_url", None)
        self.config.extra = extra

        current = str(getattr(self.config, "model", "") or "").strip()
        if model:
            self.config.model = model
        else:
            from pcagent.gui import providers as _providers

            # Подходит ли текущая модель провайдеру; иначе - модель по умолчанию.
            if not _providers.model_fits_provider(current, provider):
                self.config.model = provider.default_model

        self._append_chat(
            "status",
            f"Провайдер: {provider.title}, модель: {self.config.model or '-'}",
        )
        self._update_status()

    def has_api_key(self) -> bool:
        """Есть ли сейчас действующий ключ (с учётом stub-режима)."""
        if bool(getattr(self.config, "stub_mode", False)):
            return True
        try:
            return bool(str(self.config.resolve_api_key() or "").strip())
        except Exception:  # noqa: BLE001
            return bool(str(getattr(self.config, "api_key", "") or "").strip())

    def ensure_api_key(self) -> bool:
        """Гарантировать ключ перед запуском задачи: при отсутствии - диалог."""
        if self.has_api_key():
            return True
        self._append_chat("status", "Ключ API не найден - откройте диалог ввода")
        self.open_api_key_dialog()
        return self.has_api_key()

    def verify_api_key_async(self, key: str, on_done: Callable[[credentials.VerificationResult], None]) -> None:
        """Проверить ключ в фоне, чтобы не блокировать окно."""

        def worker() -> None:
            try:
                result = credentials.verify_key(key, config=self.config)
            except Exception as exc:  # noqa: BLE001 - показываем отказ, не падаем
                result = credentials.VerificationResult(False, f"сбой проверки: {exc}")
            self.key_verified = bool(result.ok)
            # tk нельзя трогать из чужого потока: кладём в очередь,
            # главный поток заберёт результат в poll_once().
            with self._verify_lock:
                self._verify_queue.append((on_done, result))

        threading.Thread(target=worker, name="pcagent-gui-verify", daemon=True).start()

    def _drain_verify_results(self) -> int:
        """Вызвать обработчики проверки ключа в главном потоке."""
        with self._verify_lock:
            pending = list(self._verify_queue)
            self._verify_queue.clear()
        for callback, result in pending:
            try:
                callback(result)
            except Exception:  # noqa: BLE001 - окно могло закрыться
                pass
        return len(pending)

    def open_api_key_dialog(self) -> None:
        """Диалог ввода ключа API: вставка, проверка и сохранение в .env."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Ключ API")
        dialog.transient(self.root)
        try:
            dialog.grab_set()
        except Exception:  # noqa: BLE001
            pass

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text=(
                "Ключ берётся на https://aistudio.google.com/apikey\n"
                "Скопируйте его и нажмите Вставить из буфера (или Ctrl+V).\n"
                "Можно также задать переменную PCAGENT_API_KEY в системе - "
                "тогда ключ подхватится сам."
            ),
            justify="left",
            wraplength=460,
        ).pack(anchor="w")

        state_text = (
            self.key_source.describe()
            if self.key_source is not None
            else "ключ не найден ни в одном источнике"
        )
        ttk.Label(body, text=f"Сейчас: {state_text}", foreground="#455a64").pack(
            anchor="w", pady=(8, 6)
        )

        result_var = tk.StringVar(master=dialog, value="")
        key_var = tk.StringVar(master=dialog, value="")

        entry_row = ttk.Frame(body)
        entry_row.pack(fill="x", pady=(0, 6))
        entry = ttk.Entry(entry_row, textvariable=key_var, show="*", width=44)
        entry.pack(side="left", fill="x", expand=True)

        def paste_from_clipboard(auto: bool = False) -> bool:
            """Вставить ключ из буфера обмена, очистив лишние символы."""
            raw = credentials.read_clipboard(entry)
            if not raw.strip():
                if not auto:
                    result_var.set("Буфер обмена пуст")
                return False
            key = credentials.extract_key(raw)
            if key is None:
                # Не затираем уже введённый ключ содержимым буфера.
                cleaned = raw.strip()
                if not key_var.get().strip() and len(cleaned) <= 200:
                    key_var.set(cleaned)
                    entry.icursor("end")
                result_var.set(
                    "В буфере нет ключа API (ожидается AIza..., sk-..., gsk_... и т.п.). "
                    "Скопируйте ключ на странице AI Studio и повторите."
                )
                return False

            key_var.set(key)
            entry.icursor("end")
            entry.xview_moveto(1.0)
            result_var.set(
                "Ключ вставлен из буфера обмена - нажмите Проверить или Сохранить"
            )
            return True

        ttk.Button(
            entry_row, text="Вставить из буфера", command=paste_from_clipboard
        ).pack(side="left", padx=(6, 0))
        entry.focus_set()

        show_var = tk.BooleanVar(master=dialog, value=False)

        def toggle_show() -> None:
            entry.configure(show="" if show_var.get() else "*")

        ttk.Checkbutton(
            body, text="Показать ключ", variable=show_var, command=toggle_show
        ).pack(anchor="w")

        # Ctrl+V и Shift+Insert чистят ключ от переносов строк и кавычек,
        # которые часто попадают при копировании со страницы Google.
        def on_paste_event(_event: Any = None) -> str:
            paste_from_clipboard()
            return "break"

        # Вставка по коду клавиши: при русской раскладке Tk присылает
        # keysym "??" вместо "v", и обычные привязки не срабатывают.
        paste_shortcuts.bind_paste(entry, on_paste_event)
        paste_shortcuts.bind_edit_shortcuts(entry)
        paste_shortcuts.bind_paste(dialog, on_paste_event)

        # Если ключ уже лежит в буфере - подставляем сразу при открытии.
        try:
            initial = credentials.extract_key(credentials.read_clipboard(entry))
        except Exception:  # noqa: BLE001
            initial = None
        if initial:
            key_var.set(initial)
            result_var.set(
                "Ключ найден в буфере обмена и подставлен - нажмите Сохранить"
            )

        # Адрес API: нужен для своих шлюзов и нестандартных провайдеров.
        base_row = ttk.Frame(body)
        base_row.pack(fill="x", pady=(6, 0))
        ttk.Label(base_row, text="Адрес API (base_url):").pack(side="left")
        # Предзаполняем адрес только для сторонних провайдеров: у Google
        # адрес не нужен, и старый base_url другого провайдера только
        # запутал бы проверку ключа.
        cfg_extra = dict(getattr(self.config, "extra", None) or {})
        saved_provider = str(cfg_extra.get("provider") or "")
        prefill_base = "" if saved_provider in ("", "google") else str(cfg_extra.get("base_url") or "")
        base_var = tk.StringVar(master=dialog, value=prefill_base)
        base_entry = ttk.Entry(base_row, textvariable=base_var, width=38)
        base_entry.pack(side="left", padx=(6, 0), fill="x", expand=True)

        def paste_url_from_clipboard(auto: bool = False) -> bool:
            """Вставить адрес API из буфера обмена (для своего шлюза)."""
            raw = credentials.read_clipboard(base_entry)
            if not raw.strip():
                if not auto:
                    result_var.set("Буфер обмена пуст")
                return False
            url = credentials.extract_url(raw)
            if url is None:
                if not auto:
                    result_var.set(
                        "В буфере нет адреса API (ожидается http:// или https://...)"
                    )
                return False
            base_var.set(url)
            base_entry.icursor("end")
            base_entry.xview_moveto(1.0)
            result_var.set(f"Адрес API вставлен: {url}")
            return True

        ttk.Button(base_row, text="Вставить", command=paste_url_from_clipboard).pack(
            side="left", padx=(6, 0)
        )

        # Ctrl+V в поле адреса вставляет АДРЕС, а не ключ: обработчик висит на
        # самом поле и перехватывает событие раньше диалога.
        def on_url_paste(_event: Any = None) -> str:
            paste_url_from_clipboard()
            return "break"

        paste_shortcuts.bind_paste(base_entry, on_url_paste)
        paste_shortcuts.bind_edit_shortcuts(base_entry)

        ttk.Label(
            body,
            text=(
                "Для официальных API адрес обычно не нужен: клиент подставит его сам. "
                "Пустое поле допустимо "
                "ходит на generativelanguage.googleapis.com. Адрес нужен только "
                "для своего шлюза или стороннего провайдера, "
                "например https://api.example.com/v1"
            ),
            foreground="#607d8b",
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))


        save_var = tk.BooleanVar(master=dialog, value=True)
        ttk.Checkbutton(
            body,
            text="Сохранить в .env проекта (подхватится при следующем запуске)",
            variable=save_var,
        ).pack(anchor="w", pady=(6, 0))

        result_label = ttk.Label(body, textvariable=result_var, wraplength=460, justify="left")
        result_label.pack(anchor="w", pady=(8, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))

        def resolve_custom_base(value: str) -> str:
            """Адрес API для текущего ключа.

            Для ключа Google адрес не используется никогда: SDK ходит на
            официальный endpoint, а чужой base_url отправил бы ключ AIza...
            на сторонний сервер. Поле при этом очищается.
            """
            if credentials.looks_like_google_key(value):
                if base_var.get().strip():
                    base_var.set("")
                    result_var.set(
                        "Для ключа Google адрес API не нужен - он очищен. "
                        "SDK сам обращается к generativelanguage.googleapis.com"
                    )
                return ""
            return base_var.get().strip()

        def on_verify() -> None:
            value = key_var.get().strip()
            if not value:
                result_var.set("Введите ключ")
                return
            custom = resolve_custom_base(value)
            if custom:
                # Временный base_url для проверки именно этого адреса.
                extra = dict(getattr(self.config, "extra", None) or {})
                extra["base_url"] = custom
                self.config.extra = extra
            result_var.set("Проверяю ключ у провайдера...")

            def done(result: credentials.VerificationResult) -> None:
                prefix = "Готово: " if result.ok else "Ошибка: "
                result_var.set(prefix + result.message)
                if result.ok:
                    self.apply_provider_settings(
                        _provider_for(result.provider_id),
                        model=result.model or None,
                        base_url=result.base_url or custom or None,
                    )
                    self.key_verified = True
                    self._update_status()

            self.verify_api_key_async(value, done)

        def on_save() -> None:
            value = key_var.get().strip()
            custom = resolve_custom_base(value)
            if not self.apply_api_key(value, save=bool(save_var.get()), base_url=custom or None):
                result_var.set("Ключ не принят: пустое значение")
                return
            dialog.destroy()

        ttk.Button(buttons, text="Отмена", command=dialog.destroy).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(buttons, text="Сохранить", command=on_save).pack(side="right")
        ttk.Button(buttons, text="Проверить", command=on_verify).pack(side="right", padx=(0, 6))

        dialog.bind("<Return>", lambda _event: on_save())

    def open_settings_dialog(self) -> None:
        """Диалог настроек: модель, шаги, режим подтверждений, монитор, UIA."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Настройки")
        dialog.transient(self.root)
        try:
            dialog.grab_set()
        except Exception:  # noqa: BLE001
            pass

        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        model_var = tk.StringVar(master=dialog, value=str(self.config.model))
        steps_var = tk.StringVar(master=dialog, value=str(self.effective_max_steps()))
        mode_var = tk.StringVar(master=dialog, value=str(self.config.confirm_mode))
        monitor_var = tk.StringVar(master=dialog, value=str(self.config.monitor))
        uia_var = tk.BooleanVar(master=dialog, value=bool(self.config.include_uia_tree))

        ttk.Label(body, text="Модель:").grid(row=0, column=0, sticky="w", pady=3)
        model_box = ttk.Combobox(
            body, textvariable=model_var, width=32, values=[str(self.config.model)]
        )
        model_box.grid(row=0, column=1, sticky="we", pady=3)
        ttk.Label(body, text="Максимум шагов:").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Spinbox(body, from_=1, to=1000, textvariable=steps_var, width=8).grid(
            row=1, column=1, sticky="w", pady=3
        )
        ttk.Label(body, text="Режим подтверждений:").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(
            body,
            values=list(CONFIRM_MODES),
            textvariable=mode_var,
            state="readonly",
            width=12,
        ).grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(body, text="Монитор (-1 - все):").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Spinbox(body, from_=-1, to=8, textvariable=monitor_var, width=8).grid(
            row=3, column=1, sticky="w", pady=3
        )
        ttk.Checkbutton(
            body, text="Читать дерево UI Automation", variable=uia_var
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=6)

        confirm_var = tk.BooleanVar(master=dialog, value=bool(self.auto_confirm_var.get()))
        ttk.Checkbutton(
            body,
            text="Подтверждать опасные действия автоматически",
            variable=confirm_var,
        ).grid(row=7, column=0, columnspan=2, sticky="w")

        capture_var = tk.BooleanVar(master=dialog, value=bool(self.auto_capture_var.get()))
        ttk.Checkbutton(
            body,
            text="Делать снимок экрана в начале каждой задачи",
            variable=capture_var,
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(0, 6))

        # --- экономия трафика ---
        extra = dict(getattr(self.config, "extra", None) or {})
        shot_limit_var = tk.StringVar(
            master=dialog,
            value=str(extra.get("screenshot_max_per_task", screen_policy.DEFAULT_MAX_PER_TASK)),
        )
        shot_interval_var = tk.StringVar(
            master=dialog,
            value=str(extra.get("screenshot_min_interval_s", screen_policy.DEFAULT_MIN_INTERVAL_S)),
        )
        shot_width_var = tk.StringVar(
            master=dialog,
            value=str(extra.get("agent_screenshot_max_width", screen_policy.DEFAULT_AGENT_MAX_WIDTH)),
        )
        crop_var = tk.BooleanVar(
            master=dialog,
            value=bool(extra.get("crop_to_active_window", screen_policy.DEFAULT_CROP_TO_WINDOW)),
        )

        ttk.Label(body, text="Снимков на задачу:").grid(row=10, column=0, sticky="w", pady=3)
        ttk.Spinbox(body, from_=0, to=50, textvariable=shot_limit_var, width=8).grid(
            row=10, column=1, sticky="w", pady=3
        )
        ttk.Label(body, text="Пауза между снимками, с:").grid(row=11, column=0, sticky="w", pady=3)
        ttk.Spinbox(body, from_=0, to=60, textvariable=shot_interval_var, width=8).grid(
            row=11, column=1, sticky="w", pady=3
        )
        ttk.Label(body, text="Ширина снимка для модели, px:").grid(
            row=12, column=0, sticky="w", pady=3
        )
        ttk.Spinbox(body, from_=320, to=2560, increment=64, textvariable=shot_width_var, width=8).grid(
            row=12, column=1, sticky="w", pady=3
        )
        ttk.Checkbutton(
            body, text="Обрезать снимок по активному окну", variable=crop_var
        ).grid(row=13, column=0, columnspan=2, sticky="w", pady=(4, 0))

        console_var = tk.BooleanVar(
            master=dialog, value=agent_tuning.console_first_enabled(self.config)
        )
        ttk.Checkbutton(
            body,
            text="Сначала консоль и скрипты, снимок - только при необходимости",
            variable=console_var,
        ).grid(row=14, column=0, columnspan=2, sticky="w")

        routing_var = tk.BooleanVar(
            master=dialog, value=tool_router.routing_enabled(self.config)
        )
        ttk.Checkbutton(
            body,
            text="Отбирать инструменты под задачу (экономия токенов)",
            variable=routing_var,
        ).grid(row=15, column=0, columnspan=2, sticky="w")

        compact_var = tk.BooleanVar(
            master=dialog, value=tool_router.compacting_enabled(self.config)
        )
        ttk.Checkbutton(
            body,
            text="Сжимать описания инструментов",
            variable=compact_var,
        ).grid(row=16, column=0, columnspan=2, sticky="w", pady=(0, 6))

        probe_var = tk.StringVar(master=dialog, value="")
        probe_label = ttk.Label(body, textvariable=probe_var, wraplength=380, justify="left")
        probe_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))

        def probe_models() -> None:
            key = ""
            try:
                key = str(self.config.resolve_api_key() or "")
            except Exception:  # noqa: BLE001
                key = str(getattr(self.config, "api_key", "") or "")
            if not key:
                probe_var.set("Сначала задайте ключ API: Файл - Ключ API...")
                return
            probe_var.set("Запрашиваю список моделей у провайдера...")

            def done(result: credentials.VerificationResult) -> None:
                if not result.ok:
                    probe_var.set(f"Не удалось: {result.message}")
                    return
                names = [name for name in result.models if name]
                if names:
                    model_box["values"] = names
                    if model_var.get().strip() not in names:
                        preferred = [n for n in names if "flash" in n]
                        model_var.set(preferred[0] if preferred else names[0])
                probe_var.set(
                    f"Ключ работает. Доступно моделей: {len(names)}. "
                    "Выберите модель в списке."
                )

            self.verify_api_key_async(key, done)

        ttk.Button(
            body, text="Проверить ключ и подобрать модель", command=probe_models
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=17, column=0, columnspan=2, sticky="e", pady=(10, 0))

        def save() -> None:
            values = {
                "model": model_var.get(),
                "max_steps": steps_var.get(),
                "confirm_mode": mode_var.get(),
                "monitor": monitor_var.get(),
                "include_uia_tree": bool(uia_var.get()),
                "auto_confirm": bool(confirm_var.get()),
                "auto_capture": bool(capture_var.get()),
                "screenshot_max_per_task": shot_limit_var.get(),
                "screenshot_min_interval_s": shot_interval_var.get(),
                "agent_screenshot_max_width": shot_width_var.get(),
                "crop_to_active_window": bool(crop_var.get()),
                "console_first": bool(console_var.get()),
                "tool_routing": bool(routing_var.get()),
                "tool_compact": bool(compact_var.get()),
            }
            dialog.destroy()
            self.apply_settings(values)

        ttk.Button(buttons, text="Отмена", command=dialog.destroy).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(buttons, text="Сохранить", command=save).pack(side="right")

    def apply_settings(self, values: dict[str, Any], path: str | Path | None = None) -> bool:
        """Применить настройки к конфигурации и сохранить их в YAML."""
        values = dict(values or {})
        model = str(values.get("model", self.config.model) or "").strip()
        if model:
            self.config.model = model
        if "max_steps" in values:
            try:
                self.config.max_steps = max(1, int(str(values["max_steps"]).strip()))
                # Пользователь выбрал лимит сам - больше не подменяем его
                # значением GUI по умолчанию.
                extra = dict(getattr(self.config, "extra", None) or {})
                extra["max_steps_explicit"] = True
                self.config.extra = extra
            except (TypeError, ValueError):
                pass
        if "confirm_mode" in values:
            mode = str(values["confirm_mode"]).strip().lower()
            if mode in CONFIRM_MODES:
                self.config.confirm_mode = mode
        if "monitor" in values:
            try:
                self.config.monitor = int(str(values["monitor"]).strip())
            except (TypeError, ValueError):
                pass
        if "include_uia_tree" in values:
            self.config.include_uia_tree = bool(values["include_uia_tree"])
        if "auto_capture" in values:
            enabled = bool(values["auto_capture"])
            extra = dict(getattr(self.config, "extra", None) or {})
            extra["auto_capture"] = enabled
            self.config.extra = extra
            self.auto_capture_var.set(enabled)

        # Экономия трафика: числовые параметры снимков.
        traffic_keys = {
            "screenshot_max_per_task": int,
            "agent_screenshot_max_width": int,
            "screenshot_min_interval_s": float,
        }
        extra = dict(getattr(self.config, "extra", None) or {})
        changed_extra = False
        for key, caster in traffic_keys.items():
            if key not in values:
                continue
            try:
                extra[key] = caster(str(values[key]).strip().replace(",", "."))
                changed_extra = True
            except (TypeError, ValueError):
                continue
        if "crop_to_active_window" in values:
            extra["crop_to_active_window"] = bool(values["crop_to_active_window"])
            changed_extra = True
        if "console_first" in values:
            extra["console_first"] = bool(values["console_first"])
            changed_extra = True
        if "tool_routing" in values:
            extra["tool_routing"] = bool(values["tool_routing"])
            changed_extra = True
        if "tool_compact" in values:
            extra["tool_compact"] = bool(values["tool_compact"])
            changed_extra = True
        if changed_extra:
            self.config.extra = extra
        if "auto_confirm" in values:
            enabled = bool(values["auto_confirm"])
            extra = dict(getattr(self.config, "extra", None) or {})
            extra["auto_confirm"] = enabled
            self.config.extra = extra
            self.auto_confirm_var.set(enabled)

        self._max_steps = self.effective_max_steps()
        self._update_status()
        try:
            saved = self.config.save(path) if path is not None else self.config.save()
            self._persist_extra_flags(saved)
        except Exception as exc:  # noqa: BLE001
            self._append_chat("error", f"Не удалось сохранить настройки: {exc}")
            return False
        self._append_chat("status", f"Настройки сохранены: {saved}")
        return True

    def _persist_extra_flags(self, path: str | Path) -> None:
        """Записать флаги GUI внутрь секции extra: в YAML.

        AppConfig.save() не сериализует extra, поэтому дописываем его сами.
        Важно: флаги пишутся ВНУТРЬ extra, а не в корень файла - иначе они
        дублируются (и в extra, и в корне), а секреты вроде api_key вообще
        не должны попадать в config.yaml.
        """
        extra = dict(getattr(self.config, "extra", None) or {})
        wanted = {
            key: value
            for key, value in extra.items()
            if isinstance(value, (str, int, float, bool))
        }
        if not wanted:
            return
        import yaml

        target = Path(path)
        try:
            data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 - файл мог быть только что создан
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.pop("api_key", None)
        section = data.get("extra")
        if not isinstance(section, dict):
            section = {}
        section.update(wanted)
        data["extra"] = section
        target.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def open_log_folder(self) -> None:
        """Открыть папку журналов в проводнике."""
        path = Path(self.config.log_path)
        try:
            path.mkdir(parents=True, exist_ok=True)
            startfile = getattr(os, "startfile", None)
            if callable(startfile):
                startfile(str(path))
                self._append_chat("status", f"Открыта папка журнала: {path}")
            else:  # pragma: no cover - не Windows
                self._append_chat("status", f"Папка журнала: {path}")
        except Exception as exc:  # noqa: BLE001
            self._append_chat("error", f"Не удалось открыть журнал: {exc}")

    # ------------------------------------------------------------------
    # работа агента
    # ------------------------------------------------------------------
    def read_option_flags(self) -> tuple[bool, bool]:
        """Прочитать чекбоксы. Вызывать только в главном потоке."""
        self._auto_confirm_snapshot = bool(self.auto_confirm_var.get())
        self._dry_run_snapshot = bool(self.dry_run_var.get())
        self._auto_capture_snapshot = bool(self.auto_capture_var.get())
        return self._auto_confirm_snapshot, self._dry_run_snapshot

    def runtime_config(self) -> AppConfig:
        """Копия конфигурации с учётом чекбокса Dry-run.

        Читает только снимок состояния, снятый в главном потоке, поэтому
        метод безопасен и для потока агента.
        """
        dry_run = bool(self._dry_run_snapshot)
        steps = self.effective_max_steps()
        try:
            return dataclasses.replace(
                self.config, dry_run=dry_run, max_steps=steps
            )
        except Exception:  # noqa: BLE001
            clone = AppConfig.from_dict(self.config.to_dict())
            clone.dry_run = dry_run
            clone.max_steps = steps
            return clone

    def effective_max_steps(self) -> int:
        """Лимит шагов для запуска задачи - ровно то, что в конфигурации.

        Никаких подмен: значение по умолчанию задаётся в AppConfig.max_steps
        (pcagent/config.py) и в config.yaml, и пользователь всегда видит
        в настройках именно то число, которое будет применено.
        """
        try:
            return max(1, int(self.config.max_steps))
        except (TypeError, ValueError):
            return GUI_DEFAULT_MAX_STEPS

    def _worker_main(self, task: str) -> None:
        result: Any = None
        try:
            agent = self._build_agent(task)
            self.agent = agent
            result = agent.run_task(task)
        except Exception as exc:  # noqa: BLE001 - показываем ошибку в интерфейсе
            self.bus.publish(ev.Event.error(f"Сбой агента: {exc}"))
        finally:
            self.agent = None
            self._close_runtime_resources()
            self.bus.publish(ev.Event.done(self.result_payload(result)))

    def _build_agent(self, task: str = "") -> Any:
        """Создать агентную сессию: фабрика из тестов или реальный AgentSession."""
        if self.agent_factory is not None:
            factory = self.agent_factory
            try:
                params = [
                    p
                    for p in inspect.signature(factory).parameters.values()
                    if p.kind
                    in (
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        inspect.Parameter.VAR_POSITIONAL,
                    )
                ]
            except (TypeError, ValueError):
                params = [1]
            if not params:
                return factory()
            return factory(self.config, self.bus, self.broker)
        return self._build_default_agent(task)

    def _route_tools(self, registry: Any, task: str, cfg: AppConfig) -> Any:
        """Отфильтровать инструменты под задачу (экономия трафика).

        Правила жёсткие: инструменты capture и finish_task остаются
        всегда, а нераспознанная задача получает полный набор.
        """
        try:
            routed, info = tool_router.filter_registry(
                registry,
                task,
                enabled=tool_router.routing_enabled(cfg),
                compact=tool_router.compacting_enabled(cfg),
            )
        except Exception as exc:  # noqa: BLE001 - без отбора агент работает
            self.bus.publish(ev.Event.log(f"Отбор инструментов не выполнен: {exc}"))
            return registry
        self._tool_routing_info = dict(info)
        if info.get("fallback"):
            self.bus.publish(
                ev.Event.log(
                    f"Задача не распознана: модель получит все {info['total']} инструментов"
                )
            )
        elif info.get("kept") != info.get("total"):
            self.bus.publish(
                ev.Event.log(
                    f"Инструментов для задачи: {info['kept']} из {info['total']} "
                    f"(группы: {', '.join(info.get('groups') or []) or '-'})"
                )
            )
        return routed

    def _build_default_agent(self, task: str = "") -> Any:
        cfg = self.runtime_config()
        try:
            from pcagent.agent.loop import AgentSession
            from pcagent.logging_utils import JsonlLogger
            from pcagent.safety import AutoConfirmer, Policy
            from pcagent.tools.base import build_default_registry
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"агент недоступен: {exc}") from exc

        registry = build_default_registry(list(cfg.enabled_categories))
        # Отбор инструментов под задачу: модель видит только то, что ей
        # нужно, и не платит за остальные декларации на каждом шаге.
        #
        # ВАЖНО: консольные инструменты (run_script/run_powershell) уже входят
        # в реестр через pcagent/tools/TOOL_MODULES и учитывают
        # enabled_categories. Повторная регистрация здесь не нужна: на
        # отфильтрованном реестре она падала с "уже зарегистрирован", а при
        # отключённой категории system - возвращала запрещённые инструменты.
        registry = self._route_tools(registry, task, cfg)

        # Автоподтверждение: опасные действия разрешаются без диалога.
        # Решение принимается в главном потоке и зафиксировано в снимке,
        # поэтому поток агента не трогает tk-переменные.
        if self._auto_confirm_snapshot:
            confirmer = AutoConfirmer(True)
        else:
            confirmer = self.broker
        policy = Policy(
            confirm_mode=cfg.confirm_mode,
            allow_destructive=cfg.allow_destructive,
            allow_shell=cfg.allow_shell,
            dry_run=cfg.dry_run,
            confirmer=confirmer,
        )
        logger = JsonlLogger(cfg.log_path)
        self._logger = logger

        kwargs: dict[str, Any] = {
            "config": cfg,
            "registry": registry,
            "policy": policy,
            "bus": self.bus,
            "logger": logger,
        }
        try:
            params = inspect.signature(AgentSession).parameters
        except (TypeError, ValueError):
            params = {}
        if "screen" in params:
            try:
                inner = self._ensure_screen()
                # Умный снимок: бюджет трафика, обрезка по активному окну,
                # сжатие и компактное UIA-дерево вместо лишних картинок.
                gate_options = dict(getattr(cfg, "extra", None) or {})
                if "screenshot_max_per_task" not in gate_options:
                    # Бюджет растёт вместе с длиной задачи: 4 снимка на 60
                    # шагов душили агента, и он уходил в текстовые обходы
                    # вместо нормального визуального управления.
                    gate_options["screenshot_max_per_task"] = screen_policy.budget_for_steps(
                        int(getattr(cfg, "max_steps", 30) or 30)
                    )
                gate = screen_policy.SmartScreenGate(
                    inner,
                    allow_initial=self._auto_capture_snapshot,
                    extra=gate_options,
                    on_event=lambda text: self.bus.publish(ev.Event.log(text)),
                )
                self._screen_gate = gate
                kwargs["screen"] = gate
            except Exception:  # noqa: BLE001 - снимки не обязательны для запуска
                pass

        # Сторонний провайдер: подставляем собственный мозг по ключу.
        if "brain" in params and not cfg.stub_mode:
            brain = self._build_provider_brain(cfg, logger)
            if brain is not None:
                # Правила "сначала текст, снимок в последнюю очередь".
                kwargs["brain"] = agent_tuning.wrap_brain(brain, cfg)

        agent = AgentSession(**kwargs)

        # Мозг мог быть создан самим агентом (Google SDK, stub): оборачиваем
        # его тем же правилом. Ошибку доступа не считаем фатальной.
        try:
            current = getattr(agent, "brain", None)
            if current is not None and not isinstance(
                current, agent_tuning.ConsoleFirstBrain
            ):
                agent.brain = agent_tuning.wrap_brain(current, cfg)
        except Exception:  # noqa: BLE001 - без обёртки агент тоже работает
            pass
        return agent

    def _build_provider_brain(self, cfg: AppConfig, logger: Any) -> Any | None:
        """Мозг под ключ: Google через SDK, остальные через HTTP-провайдера.

        Возвращает None, если ключа нет - тогда AgentSession создаст мозг сам.
        """
        key = ""
        try:
            key = str(cfg.resolve_api_key() or "").strip()
        except Exception:  # noqa: BLE001
            key = str(getattr(cfg, "api_key", "") or "").strip()
        if not key:
            return None
        try:
            from pcagent.gui import providers

            brain = providers.make_brain(cfg, key, logger=logger)
        except Exception as exc:  # noqa: BLE001 - падать из-за провайдера нельзя
            self.bus.publish(ev.Event.log(f"Провайдер недоступен: {exc}"))
            return None
        provider = getattr(brain, "provider", None)
        if provider is not None:
            self.bus.publish(
                ev.Event.log(
                    f"Запросы идут через {provider.title}, "
                    f"модель {getattr(brain, 'model', '-')}"
                )
            )
        return brain

    def _ensure_screen(self) -> Any:
        if self._screen is None:
            from pcagent.capture import Screen

            self._screen = Screen()
        return self._screen

    def _close_runtime_resources(self) -> None:
        logger = self._logger
        self._logger = None
        if logger is not None:
            try:
                logger.close()
            except Exception:  # noqa: BLE001
                pass
        screen = self._screen
        self._screen = None
        if screen is not None:
            try:
                screen.close()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def result_payload(result: Any) -> dict[str, Any]:
        """Привести результат агента к словарю для события KIND_DONE."""
        if result is None:
            return {
                "success": False,
                "steps": 0,
                "final_text": "",
                "error": "агент не вернул результат",
            }
        if isinstance(result, RunResult):
            return result.as_dict()
        as_dict = getattr(result, "as_dict", None)
        if callable(as_dict):
            try:
                payload = as_dict()
                if isinstance(payload, dict):
                    return dict(payload)
            except Exception:  # noqa: BLE001
                pass
        if isinstance(result, dict):
            return dict(result)
        return {
            "success": bool(getattr(result, "success", False)),
            "steps": int(getattr(result, "steps", 0) or 0),
            "final_text": str(getattr(result, "final_text", "") or ""),
            "error": getattr(result, "error", None),
        }

    # ------------------------------------------------------------------
    # мелкие помощники интерфейса
    # ------------------------------------------------------------------
    def _append_chat(self, tag: str, text: str) -> None:
        """Записать строку в ленту чата.

        Видимыми остаются только сообщения пользователя и ответы агента.
        Мысли, действия, результаты и служебные строки складываются в
        раскрывашку хода - иначе вопрос и ответ тонут в техническом шуме.
        """
        text = str(text or "").rstrip()
        if not text:
            return
        feed = getattr(self, "feed", None)
        if feed is None:
            # Лента ещё не построена (ранний вызов): пишем напрямую.
            try:
                self.chat.configure(state="normal")
                self.chat.insert("end", text + "\n", tag)
                self.chat.see("end")
            finally:
                try:
                    self.chat.configure(state="disabled")
                except Exception:  # noqa: BLE001
                    pass
            return

        if tag == "user":
            feed.add_user(text)
        elif tag == "done":
            # Итог задачи - это ответ агента: показываем как сообщение.
            feed.close_details()
            answer = text
            if answer.startswith("Итог: "):
                answer = answer[len("Итог: "):]
            feed.add_bot(answer)
        elif tag == "error":
            feed.add_error(text)
        elif tag == "status":
            feed.add_detail(text, header="Ход выполнения")
        elif tag == "thought":
            feed.add_detail(text, header="Ход выполнения")
        elif tag == "action":
            feed.add_detail(text, header="Ход выполнения")
        elif tag == "result":
            feed.add_detail(text, header="Ход выполнения")
        elif tag == "log":
            feed.add_detail(text, header="Служебные сообщения")
        else:
            feed.add_detail(text, header="Подробности")

    def _on_chat_click(self, event: Any = None) -> None:
        """Клик по заголовку раскрывашки разворачивает или сворачивает её."""
        feed = getattr(self, "feed", None)
        if feed is None or event is None:
            return
        try:
            index = self.chat.index("@{0},{1}".format(event.x, event.y))
            line_start = self.chat.index(index + " linestart")
            line_end = self.chat.index(index + " lineend")
            line = self.chat.get(line_start, line_end)
        except Exception:  # noqa: BLE001 - клик вне текста
            return
        if not (line.startswith("▶") or line.startswith("▼")):
            return
        for number, item in enumerate(feed.details):
            marker = "▼ " if item.expanded else "▶ "
            if line.startswith(marker + item.header):
                feed.toggle(number)
                return

    def chat_text(self) -> str:
        """Весь текст ленты, включая свёрнутые подробности.

        Видимая часть ленты - вопрос и ответ; технические строки лежат
        в раскрывашках. Для проверок и копирования нужен полный текст.
        """
        feed = getattr(self, "feed", None)
        if feed is not None:
            return feed.full_text()
        try:
            return self.chat.get("1.0", "end")
        except Exception:  # noqa: BLE001
            return ""

    def _screenshots_status(self) -> str:
        """Сколько снимков израсходовано в текущей задаче (экономия трафика)."""
        gate = self._screen_gate
        if gate is None:
            return ""
        try:
            budget = gate.budget
            return f"{budget.used}/{budget.max_per_task}"
        except Exception:  # noqa: BLE001
            return ""

    def _set_state(self, state: str) -> None:
        self._state = str(state or "")
        self._update_status()

    def _update_status(self) -> None:
        model = self.config.model or "-"
        provider_name = ""
        try:
            from pcagent.gui import providers

            extra = getattr(self.config, "extra", None) or {}
            if extra.get("provider"):
                provider_name = providers.get_provider(extra["provider"]).title
        except Exception:  # noqa: BLE001
            provider_name = ""
        if provider_name:
            model = f"{model} ({provider_name})"
        key_text = credentials.describe_key_state(self.config)
        if self.key_verified is True:
            key_text += ", проверен"
        elif self.key_verified is False:
            key_text += ", не проверен"
        shot_text = self._screenshots_status()
        text = (
            f"Модель: {model} | {key_text} | Шаг: {self._step}/{self._max_steps}"
            + (f" | Снимки: {shot_text}" if shot_text else "")
            + f" | Состояние: {self._state}"
        )
        try:
            self.status_var.set(text)
        except Exception:  # noqa: BLE001
            pass

    def _set_running(self, running: bool) -> None:
        try:
            self.send_button.configure(state="disabled" if running else "normal")
            self.stop_button.configure(state="normal" if running else "disabled")
        except Exception:  # noqa: BLE001
            pass

    def _preview_max_size(self) -> tuple[int, int]:
        width = height = 0
        try:
            width = int(self.preview_label.winfo_width())
            height = int(self.preview_label.winfo_height())
        except Exception:  # noqa: BLE001
            width = height = 0
        if width < 40 or height < 40:
            return PREVIEW_FALLBACK_SIZE
        return max(40, width - 8), max(40, height - 8)

    def set_preview(self, data: bytes) -> bool:
        """Показать снимок экрана в правой панели (масштаб под размер панели)."""
        try:
            from PIL import Image, ImageTk
        except Exception as exc:  # noqa: BLE001
            self.preview_label.configure(text=f"PIL недоступен: {exc}", image="")
            return False
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except Exception as exc:  # noqa: BLE001
            self.preview_label.configure(text=f"Не удалось открыть снимок: {exc}", image="")
            return False

        image = image.convert("RGB")
        max_width, max_height = self._preview_max_size()
        image.thumbnail((max_width, max_height))
        try:
            photo = ImageTk.PhotoImage(image, master=self.root)
        except Exception:  # noqa: BLE001
            photo = ImageTk.PhotoImage(image)
        self.preview_photo = photo
        self.preview_image = image
        self.preview_label.configure(image=photo, text="")
        return True


def main(argv: list[str] | None = None) -> int:
    """Точка входа: python -m pcagent.gui.app."""
    from pcagent.gui import launch

    return launch()


if __name__ == "__main__":  # pragma: no cover - ручной запуск
    raise SystemExit(main())
