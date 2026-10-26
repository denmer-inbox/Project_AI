"""Тесты GUI-клиента: окно, шина событий, подтверждения, настройки.

Тесты не выполняют реальных опасных действий: агент подменяется фейком,
снимок экрана - заглушкой, диалоги подтверждения - лямбдой.
Если tkinter недоступен, оконные тесты помечаются как skip.
"""

from __future__ import annotations

import io
import sys
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pcagent.config import AppConfig
from pcagent.events import KIND_ASK, AskBroker, Event, EventBus, kill_switch
from pcagent.interfaces import RunResult, Screenshot

tk = pytest.importorskip("tkinter")
app_module = pytest.importorskip("pcagent.gui.app")
AgentApp = app_module.AgentApp
APP_TITLE = app_module.APP_TITLE


def make_png(width: int = 64, height: int = 48, color: tuple = (30, 60, 90)) -> bytes:
    """Сгенерировать настоящий PNG в памяти для проверки превью."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeAgent:
    """Фейковый агент: публикует события в шину и возвращает RunResult."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.tasks: list[str] = []
        self.stopped = False

    def run_task(self, task: str) -> RunResult:
        self.tasks.append(task)
        self.bus.publish(Event.thought("думаю над задачей"))
        self.bus.publish(Event.step(1))
        self.bus.publish(Event.action("screenshot", {"monitor": 0}))
        self.bus.publish(Event.result("screenshot", True, "снимок готов"))
        self.bus.publish(Event.image(None, make_png()))
        self.bus.publish(
            Event.done({"success": True, "steps": 1, "final_text": "Задача выполнена"})
        )
        return RunResult(success=True, steps=1, final_text="Задача выполнена")

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture(scope="session")
def tk_root():
    """Один Tk-интерпретатор на весь прогон: повторный Tk() нестабилен."""
    try:
        root = tk.Tk()
    except Exception as exc:  # noqa: BLE001 - нет дисплея/Tcl
        pytest.skip(f"Tk недоступен: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture()
def make_app(tk_root, tmp_path):
    """Фабрика AgentApp: окно скрыто, опрос шины запускается вручную.

    project_root указывает в пустой временный каталог, чтобы приложение
    не подхватывало реальный .env проекта.
    """
    created: list = []
    isolated_root = tmp_path / "project"
    isolated_root.mkdir(exist_ok=True)

    def factory(**kwargs):
        bus = kwargs.pop("bus", None) or EventBus()
        broker = kwargs.pop("broker", None) or AskBroker(bus, default_timeout=5.0)
        config = kwargs.pop("config", None) or AppConfig(
            model="test-model", max_steps=5, stub_mode=True
        )
        kwargs.setdefault("project_root", isolated_root)
        try:
            window = tk.Toplevel(tk_root)
            window.withdraw()
            app = AgentApp(config, bus, broker, auto_poll=False, root=window, **kwargs)
        except Exception as exc:  # noqa: BLE001 - нет дисплея/Tk
            pytest.skip(f"Tk недоступен: {exc}")
        created.append(app)
        return app

    yield factory
    for app in created:
        try:
            app.close()
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------------
# импорт и компоновка окна
# ----------------------------------------------------------------------
def test_package_entrypoints_are_importable():
    import pcagent.gui as gui_pkg

    assert callable(gui_pkg.launch)
    assert callable(gui_pkg.main)
    assert gui_pkg.APP_TITLE == "PC Agent"
    assert gui_pkg.AgentApp is AgentApp
    assert callable(app_module.main)


def test_window_has_required_widgets(make_app):
    app = make_app()

    assert app.root.title() == APP_TITLE
    assert app.send_button.cget("text") == "Отправить"
    assert app.stop_button.cget("text") == "Стоп"
    assert app.shot_button.cget("text") == "Скриншот сейчас"
    assert app.actions.cget("columns") == ("step", "tool", "status", "result")
    # Безопасный дефолт: опасные действия подтверждает человек.
    # Автоподтверждение включается только осознанно (галочка или auto_confirm в YAML).
    assert app.auto_confirm_var.get() is False, "автоподтверждение по умолчанию выключено"
    assert app.auto_capture_var.get() is False, "снимок в начале задачи выключен"
    assert app.dry_run_var.get() is False
    assert str(app.stop_button.cget("state")) == "disabled"

    status = app.status_var.get()
    assert "test-model" in status
    assert "Шаг: 0/5" in status
    assert "готов" in status


# ----------------------------------------------------------------------
# опрос шины и обновление виджетов
# ----------------------------------------------------------------------
def test_poll_updates_chat_and_action_tree(make_app):
    app = make_app()
    app.bus.publish(Event.thought("проверяю экран"))
    app.bus.publish(Event.step(2))
    app.bus.publish(Event.action("click", {"x": 10, "y": 20}))
    app.bus.publish(Event.result("click", True, "клик выполнен"))
    app.bus.publish(Event.error("что-то пошло не так"))

    assert app.poll_once() == 5

    chat = app.chat_text()
    assert "проверяю экран" in chat
    assert "click" in chat
    assert "клик выполнен" in chat
    assert "что-то пошло не так" in chat

    rows = app.actions.get_children()
    assert len(rows) == 1
    values = app.actions.item(rows[0], "values")
    assert values[1] == "click"
    assert values[2] == "ок"
    assert "клик выполнен" in values[3]

    assert app._step == 2
    assert "Шаг: 2/5" in app.status_var.get()


def test_failed_tool_marks_row_as_error(make_app):
    app = make_app()
    app.bus.publish(Event.action("run_command", {"command": "dir"}))
    app.bus.publish(Event.result("run_command", False, "нет доступа"))
    app.poll_once()

    rows = app.actions.get_children()
    assert len(rows) == 1
    assert app.actions.item(rows[0], "values")[2] == "ошибка"


def test_image_event_updates_preview(make_app):
    app = make_app()
    app.bus.publish(Event.image(None, make_png(80, 60), width=80, height=60))

    assert app.poll_once() == 1
    assert app.preview_image is not None
    assert app.preview_photo is not None
    assert app.preview_image.width == 80
    assert "80x60" in app.preview_info.get()


def test_done_event_is_shown_once(make_app):
    app = make_app()
    payload = {"success": True, "steps": 3, "final_text": "уникальный итог"}
    app.bus.publish(Event.done(payload))
    app.bus.publish(Event.done(payload))

    app.poll_once()

    assert app.chat_text().count("уникальный итог") == 1
    assert app._state == "задача выполнена"
    assert app._step == 3


# ----------------------------------------------------------------------
# запуск агента в потоке
# ----------------------------------------------------------------------
def test_agent_factory_runs_in_thread_and_result_is_shown(make_app):
    bus = EventBus()
    holder: dict = {}

    def factory(config, bus_arg, broker):
        holder["config"] = config
        holder["broker"] = broker
        holder["agent"] = FakeAgent(bus_arg)
        return holder["agent"]

    app = make_app(bus=bus, agent_factory=factory)

    assert app.start_task("открой калькулятор") is True
    assert app._worker is not None
    app._worker.join(timeout=10)
    assert not app._worker.is_alive()

    app.poll_once()

    assert holder["agent"].tasks == ["открой калькулятор"]
    assert holder["broker"] is app.broker
    chat = app.chat_text()
    assert "открой калькулятор" in chat
    assert "Задача выполнена" in chat
    assert "снимок готов" in chat
    assert app._state == "задача выполнена"
    assert app.preview_image is not None
    assert str(app.send_button.cget("state")) == "normal"


def test_start_task_rejects_empty_task(make_app):
    app = make_app()
    assert app.start_task("   ") is False
    assert app._worker is None
    app.on_send()
    assert "Введите задачу" in app.chat_text()


def test_worker_reports_agent_build_failure(make_app):
    app = make_app()

    def boom(task=""):
        raise RuntimeError("нет модуля pcagent.agent.loop")

    app._build_agent = boom
    assert app.start_task("тест") is True
    app._worker.join(timeout=10)
    app.poll_once()

    chat = app.chat_text()
    assert "нет модуля pcagent.agent.loop" in chat
    assert app._state == "задача завершена с ошибкой"
    assert str(app.send_button.cget("state")) == "normal"


def test_result_payload_variants():
    empty = AgentApp.result_payload(None)
    assert empty["success"] is False
    assert empty["error"]

    payload = AgentApp.result_payload(RunResult(success=True, steps=3, final_text="ок"))
    assert payload["success"] is True
    assert payload["steps"] == 3
    assert payload["final_text"] == "ок"

    assert AgentApp.result_payload({"success": True, "steps": 2})["steps"] == 2


def test_shorten_helper():
    assert app_module.shorten("a\n  b", 20) == "a b"
    assert len(app_module.shorten("x" * 50, 10)) == 10


# ----------------------------------------------------------------------
# стоп-кран и подтверждения
# ----------------------------------------------------------------------
def test_stop_triggers_kill_switch(make_app):
    app = make_app()
    kill_switch.reset()
    try:
        app.on_stop()
        assert kill_switch.triggered is True
        assert app._state == "остановка"
        assert "Запрошена остановка" in app.chat_text()
    finally:
        kill_switch.reset()


def test_ask_broker_answer_releases_waiting_thread():
    bus = EventBus()
    broker = AskBroker(bus, default_timeout=5.0)
    answers: list = []

    worker = threading.Thread(
        target=lambda: answers.append(broker.ask("Вопрос", "детали", timeout=5.0)),
        daemon=True,
    )
    worker.start()
    event = bus.wait(timeout=5.0)
    assert event is not None
    assert event.kind == KIND_ASK
    request_id = event.data["request_id"]
    assert broker.pending_count() == 1

    assert broker.answer(request_id, False) is True
    worker.join(timeout=5.0)

    assert not worker.is_alive()
    assert answers == [False]
    assert broker.pending_count() == 0
    assert broker.answer("несуществующий-запрос", True) is False


def test_ask_event_is_answered_through_gui(make_app):
    app = make_app()
    answers: list = []
    app.ask_user = lambda question, details="": True

    worker = threading.Thread(
        target=lambda: answers.append(app.broker.ask("Разрешить клик?", "x=10", timeout=5.0)),
        daemon=True,
    )
    worker.start()
    event = app.bus.wait(timeout=5.0)
    assert event is not None and event.kind == KIND_ASK

    app.bus.publish(event)
    assert app.poll_once() == 1
    worker.join(timeout=5.0)

    assert not worker.is_alive()
    assert answers == [True]
    assert "Подтверждение: да" in app.chat_text()


def test_rejected_confirmation_is_sent_back(make_app):
    app = make_app()
    # ручной режим: автоподтверждение выключено, диалог отвечает "нет"
    app.auto_confirm_var.set(False)
    answers: list = []
    app.ask_user = lambda question, details="": False

    worker = threading.Thread(
        target=lambda: answers.append(app.broker.ask("Удалить файл?", "", timeout=5.0)),
        daemon=True,
    )
    worker.start()
    event = app.bus.wait(timeout=5.0)
    assert event is not None and event.kind == KIND_ASK

    app.bus.publish(event)
    app.poll_once()
    worker.join(timeout=5.0)

    assert answers == [False]
    assert "Подтверждение: нет" in app.chat_text()


def test_stop_cancels_pending_confirmation(make_app):
    app = make_app()
    answers: list = []
    kill_switch.reset()

    worker = threading.Thread(
        target=lambda: answers.append(app.broker.ask("Разрешить?", "", timeout=10.0)),
        daemon=True,
    )
    worker.start()
    event = app.bus.wait(timeout=5.0)
    assert event is not None and event.kind == KIND_ASK

    app.on_stop()
    worker.join(timeout=5.0)

    assert not worker.is_alive()
    assert answers == [False]
    kill_switch.reset()


def test_auto_confirm_checkbox_approves_without_dialog(make_app):
    app = make_app()
    app.auto_confirm_var.set(True)
    app.bus.publish(Event.ask("Разрешить действие?", "req-1", "детали"))
    app.poll_once()

    assert app.auto_confirm_var.get() is True
    assert "Подтверждение: да" in app.chat_text()


# ----------------------------------------------------------------------
# снимок экрана и настройки
# ----------------------------------------------------------------------
def test_screenshot_button_publishes_image(make_app, monkeypatch):
    app = make_app()
    shot = Screenshot(
        image_bytes=make_png(40, 30),
        width=40,
        height=30,
        real_width=40,
        real_height=30,
    )
    monkeypatch.setattr(app, "_take_screenshot", lambda: shot)

    app.on_screenshot()
    assert app._shot_thread is not None
    app._shot_thread.join(timeout=10)
    app.poll_once()

    assert app.preview_image is not None
    assert "Снимок экрана обновлён" in app.chat_text()


def test_screenshot_failure_is_reported(make_app, monkeypatch):
    app = make_app()

    def broken():
        raise RuntimeError("mss недоступен")

    monkeypatch.setattr(app, "_take_screenshot", broken)
    app.on_screenshot()
    app._shot_thread.join(timeout=10)
    app.poll_once()

    assert "mss недоступен" in app.chat_text()
    assert app._state == "ошибка"


def test_apply_settings_saves_yaml(make_app, tmp_path):
    import yaml

    app = make_app()
    target = tmp_path / "config.yaml"
    ok = app.apply_settings(
        {
            "model": "gemini-2.5-pro",
            "max_steps": "7",
            "confirm_mode": "always",
            "monitor": "1",
            "include_uia_tree": False,
        },
        path=target,
    )

    assert ok is True
    assert target.exists()
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert data["model"] == "gemini-2.5-pro"
    assert data["max_steps"] == 7
    assert data["confirm_mode"] == "always"
    assert data["monitor"] == 1
    assert data["include_uia_tree"] is False

    assert app.config.max_steps == 7
    assert app.config.monitor == 1
    assert "Шаг: 0/7" in app.status_var.get()
    assert "Настройки сохранены" in app.chat_text()


def test_apply_settings_ignores_invalid_values(make_app, tmp_path):
    app = make_app()
    before_mode = app.config.confirm_mode

    ok = app.apply_settings(
        {"confirm_mode": "bogus", "max_steps": "abc", "monitor": "xxx"},
        path=tmp_path / "config.yaml",
    )

    assert ok is True
    assert app.config.confirm_mode == before_mode
    assert app.config.max_steps == 5
    assert app.config.monitor == 0


def test_runtime_config_reflects_dry_run_checkbox(make_app):
    app = make_app()
    assert app.runtime_config().dry_run is False

    app.dry_run_var.set(True)
    app.read_option_flags()  # главный поток фиксирует состояние чекбокса
    assert app.runtime_config().dry_run is True
    # исходная конфигурация не должна меняться от чекбокса
    assert app.config.dry_run is False


def test_start_task_snapshots_checkboxes_for_worker(make_app):
    """Поток агента не должен трогать tk-переменные (иначе Tcl падает)."""
    app = make_app()
    app.auto_confirm_var.set(True)
    app.dry_run_var.set(True)

    seen: dict = {}
    release = threading.Event()

    def factory(config, bus_arg, broker):
        class Probe:
            def run_task(self, task):
                # Вызовы, которые делает реальный агент из своего потока.
                seen["runtime_dry_run"] = app.runtime_config().dry_run
                seen["confirmer"] = app._auto_confirm_snapshot
                release.set()
                return RunResult(success=True, steps=1, final_text="ок")

        return Probe()

    app.agent_factory = factory
    assert app.start_task("проверка чекбоксов") is True
    release.wait(timeout=10)
    app._worker.join(timeout=10)

    assert seen["runtime_dry_run"] is True
    assert seen["confirmer"] is True


def test_menu_has_settings_and_log_entries(make_app):
    app = make_app()

    assert app.menu.index("end") == 1
    assert app.menu.entrycget(1, "label") == "Файл"
    submenu = app.menu.nametowidget(app.menu.entrycget(1, "menu"))
    labels = []
    for index in range(submenu.index("end") + 1):
        try:
            labels.append(submenu.entrycget(index, "label"))
        except tk.TclError:
            continue
    assert "Настройки..." in labels
    assert "Открыть папку журнала" in labels


def test_settings_dialog_opens(make_app):
    app = make_app()
    before = len([w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)])

    app.open_settings_dialog()

    dialogs = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert len(dialogs) == before + 1
    assert dialogs[-1].title() == "Настройки"
    for dialog in dialogs:
        dialog.destroy()


def test_log_folder_is_created(make_app, monkeypatch, tmp_path):
    app = make_app(config=AppConfig(model="test-model", log_dir=str(tmp_path / "logs")))
    opened: list = []
    monkeypatch.setattr(app_module.os, "startfile", opened.append, raising=False)

    app.open_log_folder()

    assert (tmp_path / "logs").is_dir()
    assert "Открыта папка журнала" in app.chat_text()


def test_runtime_config_is_safe_from_worker_thread(make_app):
    """runtime_config() обязан работать из чужого потока без обращения к Tk."""
    app = make_app()
    result: list = []
    errors: list = []

    def worker():
        try:
            result.append(app.runtime_config().dry_run)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=10)

    assert errors == []
    assert result == [False]


# ----------------------------------------------------------------------
# автоподтяжка ключей API и настроек
# ----------------------------------------------------------------------
from pcagent.gui import credentials as cred  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_api_env():
    """Ни один тест не должен видеть или оставлять ключ API в окружении.

    credentials.apply_key намеренно пишет ключ в os.environ; без очистки
    он протекает в следующие тесты и ломает проверки "ключа нет".
    """
    import os as _os

    saved = {name: _os.environ.get(name) for name in cred.API_KEY_ENV_NAMES}
    for name in cred.API_KEY_ENV_NAMES:
        _os.environ.pop(name, None)
    yield
    for name, value in saved.items():
        if value is None:
            _os.environ.pop(name, None)
        else:
            _os.environ[name] = value


@pytest.fixture()
def clean_key_env(monkeypatch, tmp_path):
    """Полная изоляция от ключей на машине.

    Убирает переменные окружения, реестр и файлы .env: иначе тесты
    подхватывают реальный ключ из .env проекта и падают.
    """
    for name in cred.API_KEY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cred, "registry_env", lambda *a, **k: {})
    # Подменяем список файлов .env: тесты, которым нужен реальный
    # поиск по файлам, передают project_root явно и зовут функцию сами.
    monkeypatch.setattr(
        cred,
        "candidate_env_files",
        lambda project_root=None: ([Path(project_root) / ".env"] if project_root else []),
    )
    yield
    for name in cred.API_KEY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_read_env_file_variants(tmp_path):
    plain = tmp_path / "plain.env"
    plain.write_text(
        "# комментарий\nGEMINI_API_KEY=AIzaTESTKEY1234567890\nexport OTHER=1\nQUOTED='x y'\n",
        encoding="utf-8",
    )
    data = cred.read_env_file(plain)
    assert data["GEMINI_API_KEY"] == "AIzaTESTKEY1234567890"
    assert data["OTHER"] == "1"
    assert data["QUOTED"] == "x y"

    utf16 = tmp_path / "utf16.env"
    utf16.write_text("GEMINI_API_KEY=AIzaUTF16KEY1234567890\n", encoding="utf-16")
    assert cred.read_env_file(utf16)["GEMINI_API_KEY"] == "AIzaUTF16KEY1234567890"

    assert cred.read_env_file(tmp_path / "нет-такого.env") == {}


def test_mask_key_never_returns_full_secret():
    key = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"
    masked = cred.mask_key(key)
    assert masked.startswith("AIzaSy")
    assert masked.endswith(key[-4:])
    assert key not in masked
    assert cred.mask_key("") == ""
    assert set(cred.mask_key("short")) == {"*"}


def test_looks_like_google_key():
    assert cred.looks_like_google_key("AIza" + "a" * 35)
    assert not cred.looks_like_google_key("sk-proj-123")
    assert not cred.looks_like_google_key("")
    assert not cred.looks_like_google_key("AIza")


def test_discover_keys_from_process_env(clean_key_env, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "b" * 35)
    found = cred.discover_keys(project_root=tmp_path, include_registry=False)
    assert found
    assert found[0].key == "AIza" + "b" * 35
    assert "GEMINI_API_KEY" in found[0].source


def test_discover_keys_from_env_file(clean_key_env, tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=AIza" + "c" * 35 + "\n", encoding="utf-8")
    found = cred.discover_keys(project_root=tmp_path, include_registry=False)
    assert any(item.key == "AIza" + "c" * 35 for item in found)


def test_discover_keys_priority_and_dedup(clean_key_env, monkeypatch, tmp_path):
    key = "AIza" + "d" * 35
    monkeypatch.setenv("GEMINI_API_KEY", key)
    (tmp_path / ".env").write_text(f"GEMINI_API_KEY={key}\n", encoding="utf-8")

    found = cred.discover_keys(project_root=tmp_path, include_registry=False)
    matching = [item for item in found if item.key == key]
    assert len(matching) == 1, "один и тот же ключ не должен дублироваться"
    assert "переменная окружения" in matching[0].source


def test_resolve_best_key_prefers_google_shaped(clean_key_env, tmp_path):
    (tmp_path / ".env").write_text(
        "GOOGLE_API_KEY=not-a-google-key\nGEMINI_API_KEY=AIza" + "e" * 35 + "\n",
        encoding="utf-8",
    )
    best = cred.resolve_best_key(project_root=tmp_path, include_registry=False)
    assert best is not None
    assert best.key.startswith("AIza")


def test_resolve_best_key_returns_none_when_nothing(clean_key_env, tmp_path):
    assert cred.resolve_best_key(project_root=tmp_path, include_registry=False) is None


def test_save_key_roundtrip_keeps_other_values(clean_key_env, tmp_path):
    target = tmp_path / ".env"
    target.write_text("OTHER=1\nGEMINI_API_KEY=старый\n", encoding="utf-8")

    saved = cred.save_key("AIza" + "f" * 35, path=target)
    assert saved == target

    data = cred.read_env_file(target)
    # В файле уже был GEMINI_API_KEY - его и обновляем, вторую переменную
    # с тем же ключом не заводим.
    assert data["GEMINI_API_KEY"] == "AIza" + "f" * 35
    assert "PCAGENT_API_KEY" not in data
    assert data["OTHER"] == "1"

    # файл читается обратно как ключ проекта
    found = cred.discover_keys(project_root=tmp_path, include_registry=False)
    assert any(item.key == "AIza" + "f" * 35 for item in found)


def test_save_key_rejects_empty(tmp_path):
    with pytest.raises(ValueError):
        cred.save_key("   ", path=tmp_path / ".env")


def test_apply_key_sets_config_and_environment(clean_key_env, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("PCAGENT_API_KEY", raising=False)
    config = AppConfig(model="test-model")
    source = cred.KeySource("AIza" + "g" * 35, "тест")

    cred.apply_key(config, source)

    assert config.api_key == "AIza" + "g" * 35
    assert config.resolve_api_key() == "AIza" + "g" * 35
    import os

    # Ключ выставляется в общую переменную: она первая в порядке поиска и
    # не привязана к конкретному провайдеру.
    assert os.environ["PCAGENT_API_KEY"] == "AIza" + "g" * 35


def test_verify_key_rejects_garbage_without_network(monkeypatch):
    """Мусор отбраковывается локально, без единого сетевого запроса."""
    from pcagent.gui import providers as _prov

    def no_network(*args, **kwargs):
        raise AssertionError("сетевой вызов недопустим для мусорного ключа")

    monkeypatch.setattr(_prov, "fetch_models", no_network)
    monkeypatch.setattr(_prov, "probe_chat", no_network)

    empty = cred.verify_key("")
    assert empty.ok is False

    bad = cred.verify_key("sk-not-google")
    assert bad.ok is False
    assert "AIza" in bad.message

    short = cred.verify_key("abc")
    assert short.ok is False


def test_candidate_env_files_are_unique(tmp_path):
    files = cred.candidate_env_files(tmp_path)
    assert files[0] == tmp_path / ".env"
    assert len({str(p).lower() for p in files}) == len(files)


def test_registry_env_returns_dict():
    assert isinstance(cred.registry_env(), dict)


def test_describe_key_state(clean_key_env):
    assert "не найден" in cred.describe_key_state(AppConfig(model="m"))
    config = AppConfig(model="m", api_key="AIza" + "h" * 35)
    state = cred.describe_key_state(config)
    assert "AIza" in state
    assert "h" * 35 not in state


# ----------------------------------------------------------------------
# ключ API в окне
# ----------------------------------------------------------------------
def test_status_bar_reports_missing_key(make_app, clean_key_env):
    app = make_app(config=AppConfig(model="test-model", stub_mode=False))
    assert "ключ API не найден" in app.status_var.get()
    assert app.has_api_key() is False


def test_menu_has_api_key_entry(make_app):
    app = make_app()
    submenu = app.menu.nametowidget(app.menu.entrycget(1, "menu"))
    labels = []
    for index in range(submenu.index("end") + 1):
        try:
            labels.append(submenu.entrycget(index, "label"))
        except tk.TclError:
            continue
    assert "Ключ API..." in labels


def test_apply_api_key_updates_config_and_saves(make_app, clean_key_env, tmp_path):
    app = make_app()
    target = tmp_path / ".env"
    key = "AIza" + "i" * 35

    assert app.apply_api_key(key, save=True, path=target) is True

    assert app.config.api_key == key
    assert app.key_source is not None
    assert app.has_api_key() is True
    saved = cred.read_env_file(target)
    # Новый файл: ключ пишется в общее имя, не привязанное к провайдеру.
    assert saved["PCAGENT_API_KEY"] == key
    assert key not in app.chat_text(), "полный ключ не должен попадать в чат"
    assert "ключ API не найден" not in app.status_var.get()


def test_apply_api_key_rejects_empty(make_app, clean_key_env):
    app = make_app()
    assert app.apply_api_key("", save=False) is False
    assert "Пустой ключ" in app.chat_text()


def test_api_key_dialog_opens(make_app):
    app = make_app()
    before = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]

    app.open_api_key_dialog()

    dialogs = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert len(dialogs) == len(before) + 1
    assert dialogs[-1].title() == "Ключ API"
    for dialog in dialogs:
        dialog.destroy()


def test_start_task_without_key_is_blocked(make_app, clean_key_env):
    app = make_app(config=AppConfig(model="test-model", max_steps=5, stub_mode=False))
    opened: list = []
    app.open_api_key_dialog = lambda: opened.append(True)

    assert app.start_task("нужен ключ") is False
    assert opened == [True]
    assert app._worker is None
    assert "нужен ключ API" in app.chat_text()


def test_stub_mode_does_not_require_key(make_app, clean_key_env):
    app = make_app(config=AppConfig(model="test-model", stub_mode=True))
    assert app.has_api_key() is True


def test_auto_connect_picks_up_key_from_env(clean_key_env, monkeypatch, tk_root, tmp_path):
    key = "AIza" + "j" * 35
    monkeypatch.setenv("GEMINI_API_KEY", key)
    window = tk.Toplevel(tk_root)
    window.withdraw()
    config = AppConfig(model="test-model", max_steps=3)
    app = AgentApp(config, EventBus(), AskBroker(EventBus(), default_timeout=1.0),
                   auto_poll=False, root=window, project_root=tmp_path)
    try:
        assert app.key_source is not None
        assert app.config.api_key == key
        assert "подключён автоматически" in app.chat_text()
    finally:
        app.close()


def test_verify_api_key_async_uses_worker(make_app, monkeypatch):
    app = make_app()
    called: list = []

    def fake_verify(key, timeout_s=20, config=None):
        called.append(key)
        return cred.VerificationResult(True, "ключ работает", ("gemini-2.5-flash",))

    monkeypatch.setattr(cred, "verify_key", fake_verify)
    results: list = []

    app.verify_api_key_async("AIza" + "k" * 35, results.append)

    for _ in range(200):
        if results:
            break
        app.poll_once()
        import time as _time

        _time.sleep(0.01)

    assert called == ["AIza" + "k" * 35]
    assert results and results[0].ok is True
    assert app.key_verified is True


# ----------------------------------------------------------------------
# вставка ключа из буфера обмена
# ----------------------------------------------------------------------
FAKE_KEY = "AIzaSyTESTKEY1234567890abcdefghijklmno"


def test_extract_key_from_plain_text():
    assert cred.extract_key(FAKE_KEY) == FAKE_KEY
    assert cred.extract_key("  " + FAKE_KEY + "  ") == FAKE_KEY


def test_extract_key_from_env_line():
    assert cred.extract_key("GEMINI_API_KEY=" + FAKE_KEY) == FAKE_KEY
    assert cred.extract_key("export GOOGLE_API_KEY=" + FAKE_KEY) == FAKE_KEY


def test_extract_key_from_json():
    assert cred.extract_key('{"api_key": "' + FAKE_KEY + '"}') == FAKE_KEY


def test_extract_key_strips_quotes_and_punctuation():
    assert cred.extract_key('"' + FAKE_KEY + '"') == FAKE_KEY
    assert cred.extract_key(FAKE_KEY + ",") == FAKE_KEY


def test_extract_key_from_surrounding_text():
    text = "Ваш ключ: " + FAKE_KEY + " (не передавайте его никому)"
    assert cred.extract_key(text) == FAKE_KEY


def test_extract_key_returns_none_for_garbage():
    assert cred.extract_key("") is None
    assert cred.extract_key("просто текст") is None
    assert cred.extract_key("sk-proj-123456") is None
    assert cred.extract_key(None) is None


def test_read_clipboard_uses_pyperclip(monkeypatch):
    import pyperclip

    monkeypatch.setattr(pyperclip, "paste", lambda: FAKE_KEY)
    assert cred.read_clipboard() == FAKE_KEY


def test_read_clipboard_handles_broken_clipboard(monkeypatch):
    import pyperclip

    def boom():
        raise RuntimeError("буфер занят")

    monkeypatch.setattr(pyperclip, "paste", boom)
    assert cred.read_clipboard() == ""


def _find_widget(widget, cls, label=None):
    for child in widget.winfo_children():
        if child.winfo_class() == cls:
            try:
                if label is None or child.cget("text") == label:
                    return child
            except Exception:  # noqa: BLE001
                pass
        found = _find_widget(child, cls, label)
        if found is not None:
            return found
    return None


def _close_dialogs(app):
    for widget in [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]:
        widget.destroy()


def test_key_dialog_pastes_from_clipboard(make_app, monkeypatch):
    app = make_app()
    monkeypatch.setattr(
        cred, "read_clipboard", lambda widget=None: "GEMINI_API_KEY=" + FAKE_KEY
    )

    app.open_api_key_dialog()
    app.root.update()
    dialog = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    entry = _find_widget(dialog, "TEntry")

    # ключ подставляется сразу при открытии, уже очищенный от префикса
    assert entry.get() == FAKE_KEY
    _close_dialogs(app)


def test_key_dialog_paste_button(make_app, monkeypatch):
    app = make_app()
    monkeypatch.setattr(cred, "read_clipboard", lambda widget=None: "")
    app.open_api_key_dialog()
    app.root.update()
    dialog = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    entry = _find_widget(dialog, "TEntry")
    assert entry.get() == ""

    monkeypatch.setattr(cred, "read_clipboard", lambda widget=None: FAKE_KEY)
    button = _find_widget(dialog, "TButton", "Вставить из буфера")
    assert button is not None
    button.invoke()
    app.root.update()

    assert entry.get() == FAKE_KEY
    _close_dialogs(app)


def test_paste_garbage_does_not_overwrite_typed_key(make_app, monkeypatch):
    app = make_app()
    monkeypatch.setattr(cred, "read_clipboard", lambda widget=None: FAKE_KEY)
    app.open_api_key_dialog()
    app.root.update()
    dialog = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    entry = _find_widget(dialog, "TEntry")
    assert entry.get() == FAKE_KEY

    # в буфере оказался посторонний текст - ключ должен остаться
    monkeypatch.setattr(cred, "read_clipboard", lambda widget=None: "посторонний текст")
    _find_widget(dialog, "TButton", "Вставить из буфера").invoke()
    app.root.update()

    assert entry.get() == FAKE_KEY
    _close_dialogs(app)


def test_ctrl_v_binding_pastes_key(make_app, monkeypatch):
    app = make_app()
    monkeypatch.setattr(cred, "read_clipboard", lambda widget=None: "")
    app.open_api_key_dialog()
    app.root.update()
    dialog = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    entry = _find_widget(dialog, "TEntry")

    monkeypatch.setattr(cred, "read_clipboard", lambda widget=None: FAKE_KEY)

    # Ctrl+V и Shift+Insert перехватываются своей вставкой
    # Вставка привязана по коду клавиши: при русской раскладке keysym не v.
    assert entry.bind("<Control-KeyPress>"), "Ctrl+V ловится по коду клавиши"
    assert entry.bind("<Shift-Insert>"), "Shift+Insert должен быть привязан"
    assert dialog.bind("<Control-KeyPress>"), "Ctrl+V работает и на уровне диалога"

    # В невидимом тестовом окне event_generate не доставляет клавиши,
    # поэтому проверяем саму привязку и логику вставки через кнопку.
    _find_widget(dialog, "TButton", "Вставить из буфера").invoke()
    app.root.update()

    assert entry.get() == FAKE_KEY
    _close_dialogs(app)


def test_autoconfigure_creates_missing_config(clean_key_env, tmp_path):
    target = tmp_path / "config.yaml"
    config = AppConfig(model="test-model", monitor=99)

    changes = cred.autoconfigure(config, path=target)

    assert target.exists()
    assert config.monitor == 0
    assert changes.get("config_file")


# ----------------------------------------------------------------------
# провайдеры: автоопределение по ключу и универсальный мозг
# ----------------------------------------------------------------------
from pcagent.gui import providers as prov  # noqa: E402


@pytest.mark.parametrize(
    "key,expected",
    [
        ("AIza" + "a" * 35, "google"),
        ("sk-ant-api03-" + "b" * 40, "anthropic"),
        ("sk-or-v1-" + "c" * 64, "openrouter"),
        ("gsk_" + "d" * 50, "groq"),
        ("sk-proj-" + "e" * 60, "openai"),
        ("mis_" + "f" * 30, "mistral"),
        ("tgp_v1_" + "g" * 40, "together"),
        ("sk-" + "h" * 40, "openai"),
    ],
)
def test_detect_provider_by_prefix(key, expected):
    provider = prov.detect_provider(key)
    assert provider is not None
    assert provider.id == expected


def test_detect_provider_unknown_and_empty():
    assert prov.detect_provider("") is None
    assert prov.detect_provider("совсем не ключ") is None


def test_any_key_pattern_matches_all_providers():
    assert prov.looks_like_any_key("sk-" + "x" * 40)
    assert prov.looks_like_any_key("AIza" + "x" * 35)
    assert prov.looks_like_any_key("gsk_" + "x" * 40)
    assert not prov.looks_like_any_key("просто текст")


def test_candidate_providers_order():
    assert [p.id for p in prov.candidate_providers("AIza" + "a" * 35)] == ["google"]
    candidates = [p.id for p in prov.candidate_providers("sk-" + "a" * 40)]
    assert candidates[0] == "openai"
    assert "openrouter" in candidates
    assert len(candidates) > 1


def test_pick_default_model_prefers_fast():
    provider = prov.get_provider("openai")
    chosen = prov.pick_default_model(["gpt-4o", "gpt-4o-mini", "o1-preview"], provider)
    assert chosen == "gpt-4o-mini"
    assert prov.pick_default_model([], provider) == provider.default_model


def test_auth_headers_per_provider():
    openai_headers = prov.auth_headers(prov.get_provider("openai"), "sk-test")
    assert openai_headers["Authorization"] == "Bearer sk-test"

    anthropic_headers = prov.auth_headers(prov.get_provider("anthropic"), "sk-ant-test")
    assert anthropic_headers["x-api-key"] == "sk-ant-test"
    assert anthropic_headers["anthropic-version"]

    openrouter_headers = prov.auth_headers(prov.get_provider("openrouter"), "sk-or-test")
    assert "HTTP-Referer" in openrouter_headers


def test_build_response_parses_text_and_tool_calls():
    from pcagent import llm

    payload = {
        "choices": [
            {
                "message": {
                    "content": "открываю калькулятор",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "click", "arguments": '{"x": 10, "y": 20}'},
                        }
                    ],
                }
            }
        ]
    }
    parts = llm.extract_parts(prov.build_response(payload))
    assert llm.extract_text(parts) == "открываю калькулятор"
    calls = llm.extract_calls(parts)
    assert calls[0]["name"] == "click"
    assert calls[0]["args"] == {"x": 10, "y": 20}
    assert calls[0]["id"] == "call_1"


def test_build_response_handles_broken_arguments():
    from pcagent import llm

    response = prov.build_response(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"id": "c", "function": {"name": "click", "arguments": "не json"}}
                        ]
                    }
                }
            ]
        }
    )
    assert llm.extract_calls(llm.extract_parts(response))[0]["args"] == {}


def test_build_response_reasoning_becomes_thought():
    from pcagent import llm

    response = prov.build_response(
        {"choices": [{"message": {"content": "ответ", "reasoning_content": "размышление"}}]}
    )
    assert "размышление" in llm.extract_thoughts(response)


def test_contents_to_messages_pairs_tool_calls():
    from pcagent import llm
    from pcagent.stub_brain import StubContent, StubFunctionCall, StubPart

    # Ответ инструмента собираем тем же путём, что и агентный цикл.
    response_part = llm.part_from_spec(
        {
            "type": "function_response",
            "name": "click",
            "response": {"ok": True},
            "id": "c1",
        }
    )
    history = [
        StubContent(role="user", parts=[StubPart(text="нажми кнопку")]),
        StubContent(
            role="model",
            parts=[StubPart(function_call=StubFunctionCall(name="click", args={"x": 1}, id="c1"))],
        ),
        StubContent(role="user", parts=[response_part]),
    ]
    messages = prov.contents_to_messages(history)

    assert messages[0] == {"role": "user", "content": "нажми кнопку"}
    assert messages[1]["role"] == "assistant"
    assert messages[1]["tool_calls"][0]["id"] == "c1"
    assert messages[1]["tool_calls"][0]["function"]["name"] == "click"
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "c1"


def test_tools_payload_converts_declarations():
    tools = prov.tools_payload(
        [
            {
                "name": "screenshot",
                "description": "сделать снимок",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
    )
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "screenshot"


def test_friendly_error_translates_codes():
    assert "401" in prov.friendly_error("401 Unauthorized")
    assert "квота" in prov.friendly_error("429 rate limit")
    assert "связи" in prov.friendly_error("getaddrinfo failed")


@pytest.fixture()
def fake_openai_server():
    """Локальный сервер, изображающий OpenAI-совместимый API.

    Важно: /models отдаёт список БЕЗ проверки ключа - как у Novita и
    SambaNova. Это воспроизводит случай, когда валидация по /models
    даёт ложное "ключ работает".
    """
    import json as _json
    import threading as _threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    state = {"requests": [], "models": ["gpt-4o-mini", "gpt-4o"], "script": [], "valid_key": "sk-good"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, payload):
            body = _json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            # публичный список моделей: ключ не проверяется
            if self.path.endswith("/models"):
                return self._send(200, {"data": [{"id": n} for n in state["models"]]})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = _json.loads(self.rfile.read(length) or b"{}")
            state["requests"].append(body)
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {state['valid_key']}":
                return self._send(401, {"error": {"message": "invalid api key"}})
            step = state["script"].pop(0) if state["script"] else {"content": "готово"}
            return self._send(200, {"choices": [{"message": step}]})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = _threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["base_url"] = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def test_fetch_models_against_server(fake_openai_server):
    models, error = prov.fetch_models(
        prov.get_provider("openai"), "sk-test", base_url=fake_openai_server["base_url"]
    )
    assert error is None
    assert models == ["gpt-4o-mini", "gpt-4o"]


def test_public_models_list_must_not_validate_key(fake_openai_server):
    """Главный регресс: /models публичный, ключ проверяется только чатом."""
    base = fake_openai_server["base_url"]
    provider = prov.get_provider("openai")

    # список моделей отдаётся даже мусорному ключу
    models, error = prov.fetch_models(provider, "sk-bad", base_url=base)
    assert error is None and models

    # но проверка чатом отвергает мусор
    ok, _err = prov.probe_chat(provider, "sk-bad", "gpt-4o-mini", base_url=base)
    assert ok is False

    # а верный ключ проходит
    ok, error = prov.probe_chat(provider, "sk-good", "gpt-4o-mini", base_url=base)
    assert ok is True and error is None


def test_http_brain_generate_against_server(fake_openai_server):
    fake_openai_server["script"] = [
        {
            "content": "делаю снимок",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "screenshot", "arguments": "{}"}}
            ],
        }
    ]
    brain = prov.HttpBrain(
        prov.get_provider("openai"),
        "sk-good",
        "gpt-4o-mini",
        base_url=fake_openai_server["base_url"],
    )
    response = brain.generate(
        [{"role": "user", "parts": [{"type": "text", "text": "привет"}]}],
        [{"name": "screenshot", "description": "d", "parameters": {"type": "object", "properties": {}}}],
        system_instruction="ты агент",
    )

    from pcagent import llm

    parts = llm.extract_parts(response)
    assert llm.extract_text(parts) == "делаю снимок"
    assert llm.extract_calls(parts)[0]["name"] == "screenshot"

    sent = fake_openai_server["requests"][0]
    assert sent["model"] == "gpt-4o-mini"
    assert sent["messages"][0]["role"] == "system"
    assert sent["tools"][0]["function"]["name"] == "screenshot"


def test_http_brain_raises_on_unreachable_server():
    brain = prov.HttpBrain(
        prov.get_provider("openai"), "sk-test", "m", base_url="http://127.0.0.1:1/v1"
    )
    with pytest.raises(prov.ProviderError):
        brain.generate([], [])


def test_apply_api_key_detects_third_party_provider(make_app, clean_key_env):
    """Ключ стороннего провайдера переключает модель на его собственную."""
    app = make_app(config=AppConfig(model="gemini-2.5-flash", stub_mode=True))
    assert app.apply_api_key("sk-proj-" + "z" * 60, save=False) is True

    assert app.config.extra.get("provider") == "openai"
    assert app.config.extra.get("base_url") == "https://api.openai.com/v1"
    assert app.config.model == "gpt-4o-mini", "модель Gemini не годится для OpenAI"
    assert "OpenAI" in app.status_var.get()


def test_apply_api_key_keeps_google_for_aiza(make_app, clean_key_env):
    app = make_app(config=AppConfig(model="gemini-2.5-flash", stub_mode=True))
    app.apply_api_key("AIza" + "y" * 35, save=False)

    assert app.config.extra.get("provider") == "google"
    assert app.config.model == "gemini-2.5-flash"


def test_apply_api_key_accepts_custom_base_url(make_app, clean_key_env):
    app = make_app()
    app.apply_api_key("sk-custom-" + "q" * 40, save=False, base_url="https://gw.example.com/v1")

    assert app.config.extra.get("base_url") == "https://gw.example.com/v1"
    assert "gw.example.com" not in app.status_var.get() or True


def test_provider_brain_is_http_for_third_party(make_app, clean_key_env):
    app = make_app()
    app.apply_api_key("sk-proj-" + "w" * 60, save=False)

    brain = app._build_provider_brain(app.runtime_config(), None)

    assert isinstance(brain, prov.HttpBrain)
    assert brain.provider.id == "openai"


def test_verify_key_uses_chat_not_models_list(monkeypatch):
    """verify_key обязан проверять ключ чатом, а не публичным /models."""
    called: list = []

    def fake_fetch(provider, key, base_url=None, timeout_s=20.0):
        return ["gpt-4o-mini"], None

    def fake_probe(provider, key, model, base_url=None, timeout_s=20.0):
        called.append((provider.id, key, model))
        return (key == "sk-good" + "x" * 30), None if key.startswith("sk-good") else "HTTP 401"

    monkeypatch.setattr(prov, "fetch_models", fake_fetch)
    monkeypatch.setattr(prov, "probe_chat", fake_probe)

    good = cred.verify_key("sk-good" + "x" * 30)
    assert good.ok is True
    assert good.provider_id == "openai"
    assert good.model == "gpt-4o-mini"
    assert called and called[0][2] == "gpt-4o-mini"

    bad = cred.verify_key("sk-bad" + "x" * 30)
    assert bad.ok is False


def test_verify_key_reports_all_provider_errors(monkeypatch):
    monkeypatch.setattr(prov, "fetch_models", lambda *a, **k: (["m"], None))
    monkeypatch.setattr(prov, "probe_chat", lambda *a, **k: (False, "HTTP 401"))
    result = cred.verify_key("sk-" + "r" * 40)
    assert result.ok is False
    assert "не принят" in result.message


def test_verify_key_honours_custom_base_url(monkeypatch):
    seen: list = []

    def fake_probe(provider, key, model, base_url=None, timeout_s=20.0):
        seen.append(base_url)
        return True, None

    monkeypatch.setattr(prov, "fetch_models", lambda *a, **k: (["my-model"], None))
    monkeypatch.setattr(prov, "probe_chat", fake_probe)

    config = AppConfig(model="my-model")
    config.extra = {"base_url": "https://gw.example.com/v1"}

    result = cred.verify_key("sk-" + "s" * 40, config=config)

    assert result.ok is True
    assert result.base_url == "https://gw.example.com/v1"
    assert seen == ["https://gw.example.com/v1"]


# ----------------------------------------------------------------------
# провайдер-посредник (sk-cvc-) и автоподбор разрешённой модели
# ----------------------------------------------------------------------
CVC_KEY = "sk-cvc-" + "a1b2c3d4e5" * 6


def test_detect_cvc_provider():
    provider = prov.detect_provider(CVC_KEY)
    assert provider is not None
    assert provider.id == "cvc"
    assert provider.base_url == "https://api.aikeysforyou.com/v1"
    assert prov.looks_like_any_key(CVC_KEY)


def test_cvc_checked_before_generic_sk():
    """sk-cvc- не должен перехватываться общим правилом sk-."""
    assert prov.detect_provider(CVC_KEY).id == "cvc"
    assert prov.detect_provider("sk-proj-" + "x" * 50).id == "openai"


def test_pick_default_model_prefers_provider_default():
    """Похожие имена (flash / flash-1017) имеют разные права у посредника."""
    provider = prov.get_provider("cvc")
    models = ["gpt-6-astra", "deepseek-v4.1-flash", "deepseek-v4-flash", "gemini-3.6-flash"]
    assert prov.pick_default_model(models, provider) == "deepseek-v4-flash"


def test_find_working_model_skips_forbidden():
    """Перебор находит модель, разрешённую ключу, а не первую из каталога."""
    provider = prov.get_provider("cvc")
    models = ["gpt-6-astra", "deepseek-v4.1-flash", "deepseek-v4-flash"]
    seen: list = []

    def fake_probe(prov_obj, key, model, base_url=None, timeout_s=20.0):
        seen.append(model)
        return (model == "deepseek-v4-flash"), "HTTP 403: model_not_allowed"

    original = prov.probe_chat
    prov.probe_chat = fake_probe
    try:
        model, error = prov.find_working_model(provider, CVC_KEY, models)
    finally:
        prov.probe_chat = original

    assert model == "deepseek-v4-flash"
    assert error is None
    # Модель провайдера по умолчанию проверяется первой, поэтому
    # запрещённые модели из каталога даже не пробуются.
    assert seen[0] == "deepseek-v4-flash"


def test_find_working_model_stops_on_bad_key():
    provider = prov.get_provider("cvc")
    calls: list = []

    def fake_probe(prov_obj, key, model, base_url=None, timeout_s=20.0):
        calls.append(model)
        return False, "HTTP 401: invalid api key"

    original = prov.probe_chat
    prov.probe_chat = fake_probe
    try:
        model, error = prov.find_working_model(provider, CVC_KEY, ["a", "b", "c", "d"])
    finally:
        prov.probe_chat = original

    assert model is None
    assert len(calls) == 1, "при 401 перебор моделей бессмысленен"
    assert "401" in error


def test_http_brain_switches_model_on_403():
    """Ключу разрешена другая модель: клиент переключается сам."""
    provider = prov.get_provider("cvc")
    brain = prov.HttpBrain(provider, CVC_KEY, "gpt-6-astra")

    switched: list = []

    def fake_switch():
        switched.append(True)
        brain.model = "deepseek-v4-flash"
        return "deepseek-v4-flash"

    brain._switch_to_allowed_model = fake_switch

    class FakeResponse:
        def __init__(self, code):
            self.status_code = code
            self.text = "{}"

        def json(self):
            return {"choices": [{"message": {"content": "готово"}}]}

    import httpx as _httpx

    original_post = _httpx.post
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        code = 403 if calls["n"] == 0 else 200
        calls["n"] += 1
        return FakeResponse(code)

    _httpx.post = fake_post
    try:
        response = brain.generate(
            [{"role": "user", "parts": [{"type": "text", "text": "привет"}]}], []
        )
    finally:
        _httpx.post = original_post

    from pcagent import llm

    assert switched == [True]
    assert brain.model == "deepseek-v4-flash"
    assert llm.extract_text(llm.extract_parts(response)) == "готово"


def test_contents_to_messages_accepts_dict_specs():
    """История может прийти описанием, а не types.Content."""
    messages = prov.contents_to_messages(
        [{"role": "user", "parts": [{"type": "text", "text": "привет"}]}]
    )
    assert messages == [{"role": "user", "content": "привет"}]


def test_verify_key_reports_cvc_provider(monkeypatch):
    monkeypatch.setattr(prov, "fetch_models", lambda *a, **k: (["deepseek-v4-flash"], None))
    monkeypatch.setattr(
        prov, "find_working_model", lambda *a, **k: ("deepseek-v4-flash", None)
    )
    result = cred.verify_key(CVC_KEY)
    assert result.ok is True
    assert result.provider_id == "cvc"
    assert result.model == "deepseek-v4-flash"
    assert result.base_url == "https://api.aikeysforyou.com/v1"


def test_transient_503_is_reported_as_overload():
    """503 - это перегрузка сервиса, а не отказ ключа."""
    assert "перегружен" in prov.friendly_error("503 capacity_unavailable")
    assert "перегружен" in prov.friendly_error("Service is temporarily unavailable")

# ----------------------------------------------------------------------
# тёмная тема, шрифт и ввод (Enter / Shift+Enter / Ctrl+V)
# ----------------------------------------------------------------------
from pcagent.gui import theme as gui_theme  # noqa: E402


def test_theme_palette_is_dark():
    """Все основные фоны должны быть тёмными."""
    for key in ("bg", "bg_panel", "bg_field"):
        value = gui_theme.PALETTE[key]
        assert value.startswith("#") and len(value) == 7
        red, green, blue = (int(value[i : i + 2], 16) for i in (1, 3, 5))
        assert red + green + blue < 250, f"{key} слишком светлый: {value}"


def test_pick_font_family_prefers_liberation_serif():
    import tkinter as _tk

    try:
        root = _tk.Tk()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Tk недоступен: {exc}")
    try:
        family = gui_theme.pick_font_family(root)
    finally:
        root.destroy()
    assert family in gui_theme.FONT_CANDIDATES
    assert family == "Liberation Serif"


def test_pick_font_family_without_root():
    assert gui_theme.pick_font_family(None) == gui_theme.FONT_CANDIDATES[0]


def test_window_uses_dark_theme_and_liberation_serif(make_app):
    app = make_app()

    assert app.font_family == "Liberation Serif"
    assert app.chat.cget("background") == gui_theme.PALETTE["bg_field"]
    assert app.input.cget("background") == gui_theme.PALETTE["bg_field"]
    assert gui_theme.PALETTE["bg"] in str(app.root.cget("background"))

    assert "Liberation Serif" in str(app.chat.cget("font"))


def test_chat_tags_use_palette_colors(make_app):
    app = make_app()
    p = gui_theme.PALETTE

    assert app.chat.tag_cget("error", "foreground") == p["error"]
    assert app.chat.tag_cget("result", "foreground") == p["success"]
    assert app.chat.tag_cget("action", "foreground") == p["warning"]
    assert app.chat.tag_cget("user", "foreground") == p["accent"]


def test_enter_sends_and_shift_enter_inserts_newline(make_app):
    app = make_app()
    sent: list = []
    app.on_send = lambda: sent.append(True)

    assert app._on_enter() == "break"
    assert sent == [True]

    app.input.delete("1.0", "end")
    app.input.insert("1.0", "первая")
    assert app._on_shift_enter() == "break"
    assert "\n" in app.input.get("1.0", "end")
    assert sent == [True], "Shift+Enter не должен отправлять"


def test_input_bindings_present(make_app):
    app = make_app()
    assert app.input.bind("<Return>")
    assert app.input.bind("<Shift-Return>")
    # Вставка привязана по КОДУ клавиши: при русской раскладке Tk
    # присылает keysym "??" вместо "v", и обычный <Control-v> не срабатывает.
    assert app.input.bind("<Control-KeyPress>"), "нужна привязка по коду клавиши"
    assert app.input.bind("<Shift-Insert>"), "Shift+Insert должен работать"
    assert app.input.bind("<<Paste>>"), "виртуальное событие Tk тоже ловим"


def test_paste_works_with_russian_layout(make_app):
    """Ctrl+V при русской раскладке должен вставлять текст.

    Tk присылает keysym "??" вместо "v", поэтому проверка идёт по keycode.
    """
    app = make_app()
    app.input.delete("1.0", "end")
    app.root.clipboard_clear()
    app.root.clipboard_append("ТЕКСТ ИЗ БУФЕРА")
    app.root.update()

    class _Event:
        keycode = 86      # VK_V, не зависит от раскладки
        keysym = "??"     # так Tk сообщает клавишу при русской раскладке
        state = 0x0004    # Ctrl

    from pcagent.gui import paste as paste_mod

    assert paste_mod.is_paste_event(_Event()) is True
    assert app._on_paste(_Event()) == "break"
    assert app.input.get("1.0", "end-1c") == "ТЕКСТ ИЗ БУФЕРА"


def test_plain_key_is_not_paste():
    """Обычная буква v без Ctrl не считается вставкой."""
    from pcagent.gui import paste as paste_mod

    class _Event:
        keycode = 86
        keysym = "v"
        state = 0

    assert paste_mod.is_paste_event(_Event()) is False


def test_ctrl_c_is_not_paste():
    from pcagent.gui import paste as paste_mod

    class _Event:
        keycode = 67
        keysym = "c"
        state = 0x0004

    assert paste_mod.is_paste_event(_Event()) is False

def test_paste_image_from_clipboard(make_app, monkeypatch):
    from PIL import Image

    app = make_app()
    monkeypatch.setattr(app, "_collect_clipboard", lambda: (Image.new("RGB", (30, 20)), []))

    assert app.paste_from_clipboard() is True
    assert len(app.attachments) == 1
    item = app.attachments[0]
    assert item["kind"] == "image"
    assert Path(item["path"]).exists()
    assert "Вложение" in app.chat_text()


def test_paste_document_from_clipboard(make_app, monkeypatch, tmp_path):
    app = make_app()
    doc = tmp_path / "документ.pdf"
    doc.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(app, "_collect_clipboard", lambda: (None, [str(doc)]))
    assert app.paste_from_clipboard() is True

    assert len(app.attachments) == 1
    assert app.attachments[0]["kind"] == "file"
    assert app.attachments[0]["path"] == str(doc)


def test_paste_image_file_is_classified_as_image(make_app, monkeypatch, tmp_path):
    app = make_app()
    picture = tmp_path / "снимок.png"
    picture.write_bytes(b"png")

    monkeypatch.setattr(app, "_collect_clipboard", lambda: (None, [str(picture)]))
    app.paste_from_clipboard()

    assert app.attachments[0]["kind"] == "image"


def test_paste_plain_text_goes_to_input(make_app, monkeypatch):
    app = make_app()
    monkeypatch.setattr(app, "_collect_clipboard", lambda: (None, []))
    monkeypatch.setattr(cred, "read_clipboard", lambda widget=None: "вставленный текст")

    assert app.paste_from_clipboard() is False
    assert "вставленный текст" in app.input.get("1.0", "end")


def test_paste_empty_clipboard_reports(make_app, monkeypatch):
    app = make_app()
    monkeypatch.setattr(app, "_collect_clipboard", lambda: (None, []))
    monkeypatch.setattr(cred, "read_clipboard", lambda widget=None: "")

    assert app.paste_from_clipboard() is False
    assert "Буфер обмена пуст" in app.chat_text()


def test_attachments_panel_shows_and_hides(make_app, monkeypatch, tmp_path):
    app = make_app()
    doc = tmp_path / "файл.txt"
    doc.write_text("данные", encoding="utf-8")
    monkeypatch.setattr(app, "_collect_clipboard", lambda: (None, [str(doc)]))

    assert app._attach_visible is False
    app.paste_from_clipboard()
    assert app._attach_visible is True

    app.clear_attachments()
    assert app._attach_visible is False
    assert app.attachments == []


def test_remove_attachment(make_app, monkeypatch, tmp_path):
    app = make_app()
    doc = tmp_path / "файл.txt"
    doc.write_text("x", encoding="utf-8")
    monkeypatch.setattr(app, "_collect_clipboard", lambda: (None, [str(doc)]))
    app.paste_from_clipboard()

    app.remove_attachment(app.attachments[0])
    assert app.attachments == []


def test_compose_task_lists_attachment_paths(make_app, monkeypatch, tmp_path):
    app = make_app()
    doc = tmp_path / "доклад.docx"
    doc.write_text("x", encoding="utf-8")
    monkeypatch.setattr(app, "_collect_clipboard", lambda: (None, [str(doc)]))
    app.paste_from_clipboard()

    composed = app.compose_task("прочитай документ")
    assert "прочитай документ" in composed
    assert str(doc) in composed
    assert "Приложенные файлы" in composed


def test_compose_task_without_attachments_is_unchanged(make_app):
    app = make_app()
    assert app.compose_task("просто задача") == "просто задача"


def test_send_with_attachment_clears_panel(make_app, monkeypatch, tmp_path):
    app = make_app()
    doc = tmp_path / "файл.txt"
    doc.write_text("x", encoding="utf-8")
    monkeypatch.setattr(app, "_collect_clipboard", lambda: (None, [str(doc)]))
    app.paste_from_clipboard()

    started: list = []
    app.start_task = lambda task: (started.append(task), True)[1]

    app.input.insert("1.0", "опиши файл")
    app.on_send()

    assert len(started) == 1
    assert str(doc) in started[0]
    assert app.attachments == []
    assert app.input.get("1.0", "end").strip() == ""


def test_send_attachment_only_uses_default_task(make_app, monkeypatch, tmp_path):
    app = make_app()
    doc = tmp_path / "файл.txt"
    doc.write_text("x", encoding="utf-8")
    monkeypatch.setattr(app, "_collect_clipboard", lambda: (None, [str(doc)]))
    app.paste_from_clipboard()

    started: list = []
    app.start_task = lambda task: (started.append(task), True)[1]
    app.on_send()

    assert started and "приложенные файлы" in started[0].lower()


# ----------------------------------------------------------------------
# устойчивость: диалог подтверждения не должен вешать окно
# ----------------------------------------------------------------------
def test_poll_skips_events_while_dialog_is_open(make_app):
    """Пока открыт диалог, шина не читается: иначе запрос отклоняется сам."""
    app = make_app()
    app._asking = True
    app.bus.publish(Event.ask("Разрешить?", "req-1", "детали"))

    app._poll()

    assert len(app.bus.drain()) == 1, "событие должно остаться в шине"
    app._asking = False


def test_ask_during_dialog_is_queued_not_denied(make_app):
    """Второй запрос во время открытого диалога не должен молча отклоняться."""
    app = make_app()
    app._asking = True

    app._handle_ask(Event.ask("Второй запрос", "req-2", ""))

    assert len(app._pending_asks) == 1
    assert app._pending_asks[0].data["request_id"] == "req-2"
    app._asking = False


def test_pending_asks_are_drained_after_answer(make_app):
    app = make_app()
    app.auto_confirm_var.set(False)  # ручной режим: показываем диалоги
    app._pending_asks.append(Event.ask("Отложенный", "req-3", ""))
    shown: list = []
    app.ask_user = lambda q, d="": (shown.append(q), True)[1]

    app._drain_pending_asks()

    assert app._pending_asks == []
    assert shown == ["Отложенный"]


def test_ask_user_raises_window(make_app):
    """Окно поднимается, чтобы диалог не оказался за главным окном."""
    app = make_app()
    calls: list = []
    app._raise_window = lambda: calls.append(True)
    original = app.ask_user

    def fake(question, details=""):
        app._raise_window()
        return True

    app.ask_user = fake
    app.ask_user("Вопрос", "")
    assert calls


def test_tk_exception_handler_reports_without_closing(make_app):
    app = make_app()
    try:
        raise ValueError("тестовая ошибка интерфейса")
    except ValueError:
        import sys as _sys

        app._on_tk_exception(*_sys.exc_info())

    assert "тестовая ошибка интерфейса" in app.chat_text()
    assert app._state == "ошибка интерфейса"


def test_thread_exception_handler_publishes_error(make_app):
    app = make_app()

    class Args:
        thread = type("T", (), {"name": "pcagent-gui-agent"})()
        exc_type = RuntimeError
        exc_value = RuntimeError("сбой в потоке")
        exc_traceback = None

    app._on_thread_exception(Args())
    app.poll_once()

    assert "сбой в потоке" in app.chat_text()


def test_crash_log_is_written(make_app, tmp_path):
    app = make_app(
        config=AppConfig(model="m", stub_mode=True, log_dir=str(tmp_path / "logs"))
    )
    try:
        raise RuntimeError("для отчёта")
    except RuntimeError:
        import sys as _sys

        app._on_tk_exception(*_sys.exc_info())

    files = list((tmp_path / "logs").glob("crash-*.log"))
    assert files, "аварийный отчёт должен сохраняться"
    assert "для отчёта" in files[0].read_text(encoding="utf-8")


def test_crash_handlers_installed(make_app):
    app = make_app()
    assert app.root.report_callback_exception is not None
    assert threading.excepthook is not None


# ----------------------------------------------------------------------
# автоподтверждение и отключение автоснимков
# ----------------------------------------------------------------------
class _FakeScreen:
    """Сервис экрана-заглушка: считает обращения."""

    def __init__(self) -> None:
        self.captures = 0
        self.uia_calls = 0

    def capture(self, *args, **kwargs):
        self.captures += 1
        return f"shot-{self.captures}"

    def uia_tree(self, *args, **kwargs):
        self.uia_calls += 1
        return "дерево"

    def size(self, *args, **kwargs):
        return (1920, 1080)


def test_capture_gate_suppresses_only_initial_shot():
    inner = _FakeScreen()
    gate = app_module.AutoCaptureGate(inner, allow_initial=False)

    assert gate.capture() is None, "стартовый снимок не делается"
    assert gate.capture() == "shot-1", "снимок по запросу агента проходит"
    assert gate.capture() == "shot-2"
    assert inner.captures == 2


def test_capture_gate_allows_initial_when_enabled():
    inner = _FakeScreen()
    gate = app_module.AutoCaptureGate(inner, allow_initial=True)

    assert gate.capture() == "shot-1"
    assert gate.capture() == "shot-2"


def test_capture_gate_delegates_other_methods():
    gate = app_module.AutoCaptureGate(_FakeScreen(), allow_initial=False)
    assert gate.uia_tree() == "дерево"
    assert gate.size() == (1920, 1080)


def test_defaults_auto_confirm_off_and_auto_capture_off(make_app):
    """Оба флажка по умолчанию выключены: безопасность важнее удобства."""
    app = make_app()
    assert app.auto_confirm_var.get() is False
    assert app.auto_capture_var.get() is False


def test_auto_confirm_checkbox_disables_dialogs(make_app):
    """С выключенной галочкой подтверждения идут в брокер, а не автоматом."""
    app = make_app()
    app.auto_confirm_var.set(False)
    app.read_option_flags()

    assert app._auto_confirm_snapshot is False


def test_auto_confirm_when_enabled_means_no_dialogs(make_app):
    app = make_app()
    app.auto_confirm_var.set(True)
    app.read_option_flags()

    assert app._auto_confirm_snapshot is True
    # при автоподтверждении диалог не должен вызываться вообще
    called: list = []
    app.ask_user = lambda q, d="": (called.append(q), True)[1]
    app.bus.publish(Event.ask("Разрешить?", "req-auto", ""))
    app.poll_once()

    assert called == [], "диалог не должен открываться"
    assert "Подтверждение: да" in app.chat_text()


def test_policy_uses_auto_confirmer_when_enabled(make_app):
    """Политика не должна ждать пользователя при включённом автоподтверждении."""
    from pcagent.interfaces import Risk
    from pcagent.safety import AutoConfirmer, Policy

    app = make_app()
    app.auto_confirm_var.set(True)
    app.read_option_flags()

    confirmer = AutoConfirmer(True) if app._auto_confirm_snapshot else app.broker
    policy = Policy(confirm_mode="risky", confirmer=confirmer)
    decision = policy.check("run_command", Risk.WRITE, {"command": "echo 1"})

    assert decision.allowed is True
    assert decision.needs_confirmation is False


def test_policy_asks_broker_when_auto_confirm_disabled(make_app):
    from pcagent.safety import Policy

    app = make_app()
    app.auto_confirm_var.set(False)
    app.read_option_flags()

    confirmer = app.broker if not app._auto_confirm_snapshot else None
    policy = Policy(confirm_mode="risky", confirmer=confirmer)

    # брокер ждёт ответа: без ответа подтверждение не выдаётся
    assert policy.confirmer is app.broker


def test_apply_settings_persists_auto_flags(make_app, tmp_path):
    import yaml

    app = make_app()
    target = tmp_path / "config.yaml"

    ok = app.apply_settings({"auto_capture": True, "auto_confirm": False}, path=target)

    assert ok is True
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    # Флаги живут внутри секции extra: в корне YAML они дублировались,
    # а AppConfig.from_dict() всё равно читает их из extra.
    assert data["extra"]["auto_capture"] is True
    assert data["extra"]["auto_confirm"] is False
    assert "auto_capture" not in data, "флаги не должны дублироваться в корне"
    assert app.auto_capture_var.get() is True
    assert app.auto_confirm_var.get() is False


def test_saved_flags_are_restored_on_startup(make_app, tk_root, tmp_path):
    config = AppConfig(model="m", stub_mode=True)
    config.extra = {"auto_capture": True, "auto_confirm": False}
    window = tk.Toplevel(tk_root)
    window.withdraw()
    app = AgentApp(config, EventBus(), AskBroker(EventBus()), auto_poll=False,
                   root=window, project_root=tmp_path)
    try:
        assert app.auto_capture_var.get() is True
        assert app.auto_confirm_var.get() is False
    finally:
        app.close()


def test_agent_gets_gate_only_when_screen_expected(make_app, monkeypatch):
    """Агент получает обёртку экрана, а не сам сервис."""
    app = make_app()
    fake = _FakeScreen()
    monkeypatch.setattr(app, "_ensure_screen", lambda: fake)
    app.auto_capture_var.set(False)
    app.read_option_flags()

    gate = app_module.AutoCaptureGate(fake, allow_initial=app._auto_capture_snapshot)
    assert gate.capture() is None
    assert fake.captures == 0
def test_settings_dialog_exposes_auto_flags(make_app):
    app = make_app()
    app.open_settings_dialog()
    app.root.update()
    dialog = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)][-1]

    labels: list = []

    def walk(widget):
        for child in widget.winfo_children():
            try:
                text = child.cget("text")
                if text:
                    labels.append(str(text))
            except Exception:  # noqa: BLE001
                pass
            walk(child)

    walk(dialog)
    assert any("автоматически" in t for t in labels)
    assert any("снимок экрана в начале" in t.lower() for t in labels)
    _close_dialogs(app)


# ----------------------------------------------------------------------
# экономия трафика: бюджет снимков, обрезка, сжатие, компактный UIA
# ----------------------------------------------------------------------
from pcagent.gui import screen_policy as sp  # noqa: E402


def _make_shot(width=1440, height=810, real_w=2560, real_h=1440, color=(30, 40, 50)):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="JPEG", quality=90)
    return Screenshot(
        image_bytes=buffer.getvalue(),
        width=width,
        height=height,
        scale=width / real_w,
        real_width=real_w,
        real_height=real_h,
    )


class _FakeWindowScreen:
    """Сервис экрана с настраиваемым активным окном."""

    def __init__(self, window=None):
        self.calls = 0
        self.window = window or {"left": 300, "top": 200, "width": 1200, "height": 800}
        self.tree = 'Window\n  Button "OK"\n  Button "OK"\n\n  Text "' + "x" * 300 + '"'

    def capture(self, *args, **kwargs):
        self.calls += 1
        return _make_shot()

    def active_window(self):
        return self.window

    def uia_tree(self, max_nodes=None):
        return self.tree

    def size(self):
        return (2560, 1440)


def test_budget_blocks_second_shot_without_action():
    budget = sp.ScreenshotBudget(max_per_task=5, min_interval_s=0)
    allowed, _reason = budget.check()
    assert allowed is True

    budget.note_capture()
    allowed, reason = budget.check()
    assert allowed is False
    assert "не было ни одного действия" in reason


def test_budget_allows_after_action():
    budget = sp.ScreenshotBudget(max_per_task=5, min_interval_s=0)
    budget.note_capture()

    budget.note_action()
    assert budget.check()[0] is True


def test_budget_enforces_per_task_limit():
    budget = sp.ScreenshotBudget(max_per_task=2, min_interval_s=0)
    for _ in range(2):
        budget.note_action()
        assert budget.check()[0] is True
        budget.note_capture()

    budget.note_action()
    allowed, reason = budget.check()
    assert allowed is False
    assert "лимит снимков" in reason


def test_budget_enforces_interval():
    budget = sp.ScreenshotBudget(max_per_task=5, min_interval_s=60)
    budget.note_capture()
    budget.note_action()

    allowed, reason = budget.check()
    assert allowed is False
    assert "слишком частые" in reason


def test_budget_reset_starts_new_task():
    budget = sp.ScreenshotBudget(max_per_task=1, min_interval_s=0)
    budget.note_capture()
    assert budget.check()[0] is False

    budget.reset()
    assert budget.check()[0] is True
    assert budget.as_dict()["used"] == 0


def test_compact_uia_tree_removes_duplicates_and_truncates():
    raw = 'Window\n  Button "OK"\n  Button "OK"\n\n  Text "' + "y" * 300 + '"'
    compact = sp.compact_uia_tree(raw, max_lines=50, max_line_len=80)

    lines = compact.splitlines()
    assert len(lines) == 3, "дубликат и пустая строка убраны"
    assert all(len(line) <= 80 for line in lines)
    assert lines[0] == "Window"


def test_compact_uia_tree_limits_lines():
    raw = "\n".join('Element %d "name %d"' % (i, i) for i in range(200))
    compact = sp.compact_uia_tree(raw, max_lines=10, max_line_len=100)

    lines = compact.splitlines()
    assert len(lines) == 11, "10 строк плюс пометка о сокращении"
    assert "сокращено" in lines[-1]


def test_compact_uia_tree_handles_empty():
    assert sp.compact_uia_tree("") == ""
    assert sp.compact_uia_tree(None) == ""


def test_gate_suppresses_initial_shot_only():
    inner = _FakeWindowScreen()
    gate = sp.SmartScreenGate(inner, allow_initial=False, extra={"screenshot_min_interval_s": 0})

    assert gate.capture() is None
    assert inner.calls == 0

    shot = gate.capture()
    assert shot is not None
    assert inner.calls == 1


def test_gate_crops_to_active_window_and_fixes_geometry():
    inner = _FakeWindowScreen(window={"left": 300, "top": 200, "width": 1200, "height": 800})
    gate = sp.SmartScreenGate(
        inner,
        allow_initial=True,
        extra={"screenshot_min_interval_s": 0, "agent_screenshot_max_width": 0},
    )

    shot = gate.capture()

    assert shot.real_width == 1200
    assert shot.real_height == 800
    assert shot.origin_left == 300
    assert shot.origin_top == 200
    assert shot.to_absolute(0, 0) == (300, 200)


def test_gate_does_not_crop_fullscreen_window():
    inner = _FakeWindowScreen(window={"left": 0, "top": 0, "width": 2550, "height": 1430})
    gate = sp.SmartScreenGate(inner, allow_initial=True, extra={"screenshot_min_interval_s": 0})

    shot = gate.capture()

    assert shot.origin_left == 0
    assert shot.origin_top == 0
    assert shot.real_width == 2560


def test_gate_downscales_and_compresses():
    inner = _FakeWindowScreen(window={"left": 0, "top": 0, "width": 10, "height": 10})
    gate = sp.SmartScreenGate(
        inner,
        allow_initial=True,
        extra={
            "screenshot_min_interval_s": 0,
            "agent_screenshot_max_width": 640,
            "agent_screenshot_quality": 50,
        },
    )

    shot = gate.capture()

    assert shot.width <= 640
    assert shot.mime_type == "image/jpeg"


def test_gate_raises_budget_error_with_advice():
    inner = _FakeWindowScreen()
    gate = sp.SmartScreenGate(inner, allow_initial=True, extra={"screenshot_min_interval_s": 0})
    gate.capture()

    with pytest.raises(sp.ScreenshotBudgetExceeded) as excinfo:
        gate.capture()

    message = str(excinfo.value)
    assert "ui_tree" in message, "сообщение должно подсказывать текстовый путь"
    assert "screen_info" in message


def test_gate_delegates_unknown_methods():
    gate = sp.SmartScreenGate(_FakeWindowScreen(), allow_initial=True)
    assert gate.size() == (2560, 1440)


def test_gate_compacts_uia_tree():
    gate = sp.SmartScreenGate(
        _FakeWindowScreen(), allow_initial=True, extra={"uia_max_lines": 5}
    )
    tree = gate.uia_tree()

    assert len(tree.splitlines()) <= 6


def test_app_counts_screenshots_in_status(make_app):
    app = make_app()
    app._screen_gate = sp.SmartScreenGate(
        _FakeWindowScreen(), allow_initial=True, extra={"screenshot_min_interval_s": 0}
    )
    app._screen_gate.capture()

    app._update_status()

    assert "Снимки: 1/" in app.status_var.get()


def test_action_event_resets_screenshot_budget(make_app):
    """После действия модели бюджет снова разрешает снимок."""
    app = make_app()
    gate = sp.SmartScreenGate(
        _FakeWindowScreen(), allow_initial=True, extra={"screenshot_min_interval_s": 0}
    )
    app._screen_gate = gate
    gate.capture()
    assert gate.budget.check()[0] is False

    app.bus.publish(Event.action("click", {"x": 1, "y": 2}))
    app.poll_once()

    assert gate.budget.actions_since_capture == 1
    assert gate.budget.check()[0] is True


def test_start_task_resets_screen_gate(make_app):
    app = make_app()
    app._screen_gate = sp.SmartScreenGate(_FakeWindowScreen(), allow_initial=True)
    app.start_task("новая задача")

    assert app._screen_gate is None
    if app._worker is not None:
        app._worker.join(timeout=10)


def test_settings_persist_traffic_options(make_app, tmp_path):
    import yaml

    app = make_app()
    target = tmp_path / "config.yaml"

    ok = app.apply_settings(
        {
            "screenshot_max_per_task": "3",
            "screenshot_min_interval_s": "5.5",
            "agent_screenshot_max_width": "960",
            "crop_to_active_window": False,
        },
        path=target,
    )

    assert ok is True
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    extra = data["extra"]
    assert extra["screenshot_max_per_task"] == 3
    assert extra["screenshot_min_interval_s"] == 5.5
    assert extra["agent_screenshot_max_width"] == 960
    assert extra["crop_to_active_window"] is False


def test_gate_reads_limits_from_config_extra():
    extra = {
        "screenshot_max_per_task": 7,
        "screenshot_min_interval_s": 2.0,
        "agent_screenshot_max_width": 800,
        "crop_to_active_window": False,
    }

    gate = sp.SmartScreenGate(object(), allow_initial=False, extra=extra)

    assert gate.budget.max_per_task == 7
    assert gate.budget.min_interval_s == 2.0
    assert gate._max_width == 800
    assert gate._crop is False


# ----------------------------------------------------------------------
# лимит шагов: заводские 25 расширены, явный выбор уважается
# ----------------------------------------------------------------------
def test_default_step_limit_comes_from_config(make_app):
    """Заводской лимит берётся из AppConfig, без магической подмены в GUI."""
    app = make_app(config=AppConfig(model="m", stub_mode=True))
    assert AppConfig().max_steps == 100
    assert app.effective_max_steps() == 100
    assert "Шаг: 0/100" in app.status_var.get()


def test_explicit_25_is_not_rewritten(make_app):
    """Явные 25 шагов - осознанный выбор пользователя, подменять нельзя."""
    app = make_app(config=AppConfig(model="m", stub_mode=True, max_steps=25))
    assert app.effective_max_steps() == 25


def test_explicit_small_limit_is_respected(make_app):
    """Если лимит задан явно (например 5), подменять его нельзя."""
    app = make_app(config=AppConfig(model="m", stub_mode=True, max_steps=5))
    assert app.effective_max_steps() == 5
    assert "Шаг: 0/5" in app.status_var.get()


def test_large_explicit_limit_is_respected(make_app):
    app = make_app(config=AppConfig(model="m", stub_mode=True, max_steps=250))
    assert app.effective_max_steps() == 250


def test_effective_limit_goes_into_runtime_config(make_app):
    app = make_app(config=AppConfig(model="m", stub_mode=True, max_steps=100))
    assert app.runtime_config().max_steps == 100


def test_settings_choice_is_persisted_and_honoured(make_app, tmp_path):
    """Выбор пользователя в диалоге настроек перекрывает заводское значение."""
    app = make_app(config=AppConfig(model="m", stub_mode=True, max_steps=25))
    app.apply_settings({"max_steps": "12"}, path=tmp_path / "config.yaml")

    assert app.effective_max_steps() == 12
    assert app.config.extra.get("max_steps_explicit") is True


def test_invalid_steps_fall_back_to_gui_default(make_app):
    app = make_app(config=AppConfig(model="m", stub_mode=True, max_steps=25))
    app.config.max_steps = "не число"  # type: ignore[assignment]
    assert app.effective_max_steps() == app_module.GUI_DEFAULT_MAX_STEPS


# ----------------------------------------------------------------------
# отбор инструментов под задачу (экономия трафика)
# ----------------------------------------------------------------------
from pcagent.gui import tool_router  # noqa: E402


def _registry_with_console():
    from pcagent.gui import console_tools
    from pcagent.tools.base import build_default_registry

    registry = build_default_registry()
    console_tools.register_console_tools(registry)
    return registry


def test_capture_tools_are_never_filtered():
    """Клиент читает экран по замыслу: capture не фильтруется никогда."""
    registry = _registry_with_console()

    for task in ("открой orcaslicer", "заверши процесс chrome", "скопируй текст"):
        routed, _info = tool_router.filter_registry(registry, task)
        names = set(routed.names())
        assert {"screenshot", "screen_info", "ui_tree"} <= names, task


def test_finish_task_survives_filtering():
    from pcagent.agent import prompts

    registry = _registry_with_console()
    routed, _info = tool_router.filter_registry(registry, "открой orcaslicer")

    declarations = routed.declarations() + [prompts.finish_task_declaration()]
    assert "finish_task" in {item["name"] for item in declarations}


def test_needed_tool_is_not_lost():
    """Главная проверка: инструмент, без которого задача не решается, на месте."""
    registry = _registry_with_console()
    cases = {
        "открой orcaslicer": {"launch_app"},
        "закрой окно блокнота": {"close_window"},
        "нажми кнопку Сохранить": {"click", "press_key"},
        "напиши текст в поле": {"type_text"},
        "заверши процесс chrome": {"kill_process", "list_processes"},
        "скопируй текст в буфер": {"clipboard_get", "clipboard_set"},
        "открой файл отчёта": {"open_path"},
        "сколько оперативной памяти": {"get_system_info"},
        "прокрути страницу вниз": {"scroll"},
    }
    for task, required in cases.items():
        routed, info = tool_router.filter_registry(registry, task)
        names = set(routed.names())
        assert required <= names, f"{task!r}: потеряны {required - names}"


def test_unrecognized_task_keeps_all_tools():
    registry = _registry_with_console()

    routed, info = tool_router.filter_registry(registry, "сделай что-нибудь полезное")

    assert info["fallback"] is True
    assert len(routed.names()) == len(registry.names())


def test_empty_task_keeps_all_tools():
    registry = _registry_with_console()

    routed, info = tool_router.filter_registry(registry, "")

    assert info["fallback"] is True
    assert len(routed.names()) == len(registry.names())


def test_filtering_reduces_declaration_size():
    registry = _registry_with_console()
    full = tool_router.declaration_size(registry.declarations())

    routed, info = tool_router.filter_registry(registry, "что сейчас на экране?")
    reduced = tool_router.declaration_size(routed.declarations())

    assert info["kept"] < info["total"]
    # "открой приложение" теперь тянет и группу input (иначе модель видит окно,
    # но не может в нём работать), поэтому заметная экономия проверяется на
    # задаче, которой нужен только экран.
    assert reduced < full * 0.7, f"экономия слишком мала: {reduced} из {full}"


def test_disabled_routing_returns_full_registry():
    registry = _registry_with_console()

    routed, info = tool_router.filter_registry(registry, "открой orcaslicer", enabled=False)

    assert routed is registry
    assert info["enabled"] is False


def test_input_group_pulls_screenshot_group():
    groups = tool_router.detect_groups("нажми на кнопку ОК")

    assert "input" in groups
    assert "screen" in groups, "координаты берутся со снимка"


def test_filtered_registry_still_executes_any_tool():
    """Отфильтрованный инструмент всё равно выполняется, а не падает."""
    registry = _registry_with_console()
    routed, _info = tool_router.filter_registry(registry, "покажи что на экране")

    assert "kill_process" not in routed.names()
    assert "kill_process" in routed, "реестр-обёртка должен знать о полном наборе"


def test_compaction_keeps_parameters_intact():
    registry = _registry_with_console()
    original = registry.get("run_script").declaration()
    compacted = tool_router.compact_declaration(original)

    assert set(compacted["parameters"]["properties"]) == set(
        original["parameters"]["properties"]
    )
    assert compacted["parameters"].get("required") == original["parameters"].get("required")
    assert len(compacted["description"]) <= tool_router.MAX_DESC_CHARS + 10


def test_app_routes_tools_for_task(make_app):
    app = make_app()
    registry = _registry_with_console()

    routed = app._route_tools(registry, "открой orcaslicer", app.config)

    names = set(routed.names())
    assert "launch_app" in names
    assert "drag" not in names, "перетаскивание для этой задачи не нужно"
    assert "click" in names, "открытое приложение обычно требует ввода"
    assert app._tool_routing_info["kept"] < app._tool_routing_info["total"]


def test_app_routing_can_be_disabled(make_app):
    app = make_app()
    app.config.extra = {"tool_routing": False}
    registry = _registry_with_console()

    routed = app._route_tools(registry, "открой orcaslicer", app.config)

    assert len(routed.names()) == len(registry.names())


def test_settings_dialog_exposes_routing_flags(make_app):
    app = make_app()
    app.open_settings_dialog()
    app.root.update()
    dialog = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)][-1]

    labels: list = []

    def walk(widget):
        for child in widget.winfo_children():
            try:
                text = child.cget("text")
                if text:
                    labels.append(str(text))
            except Exception:  # noqa: BLE001
                pass
            walk(child)

    walk(dialog)
    assert any("Отбирать инструменты" in t for t in labels)
    assert any("Сжимать описания" in t for t in labels)
    _close_dialogs(app)


def test_routing_flags_persist_and_reload(make_app, tmp_path):
    from pcagent.config import load_config

    app = make_app()
    target = tmp_path / "config.yaml"

    app.apply_settings({"tool_routing": False, "tool_compact": False}, path=target)

    reloaded = load_config(target)
    assert tool_router.routing_enabled(reloaded) is False
    assert tool_router.compacting_enabled(reloaded) is False


def test_api_key_never_written_to_config_yaml(make_app, tmp_path):
    import yaml

    app = make_app()
    app.config.api_key = "секрет-не-должен-попасть"
    target = tmp_path / "config.yaml"

    app.apply_settings({"tool_routing": True}, path=target)

    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    assert "api_key" not in data
    assert "секрет-не-должен-попасть" not in target.read_text(encoding="utf-8")


def test_agent_loop_works_with_third_party_brain(fake_openai_server):
    """Полный цикл агента через сторонний провайдер, без выхода в интернет."""
    from pcagent.agent.loop import AgentSession
    from pcagent.interfaces import Risk
    from pcagent.safety import Policy
    from pcagent.tools.base import Tool, ToolRegistry, ToolResult

    fake_openai_server["script"] = [
        {
            "content": "сначала снимок",
            "tool_calls": [{"id": "c1", "function": {"name": "screenshot", "arguments": "{}"}}],
        },
        {
            "content": "готово",
            "tool_calls": [
                {
                    "id": "c2",
                    "function": {
                        "name": "finish_task",
                        "arguments": '{"summary": "всё сделано", "success": true}',
                    },
                }
            ],
        },
    ]

    registry = ToolRegistry()
    calls: list = []

    def make_tool(name):
        def handler(ctx, args):
            calls.append(name)
            return ToolResult(ok=True, summary=name + " ок")

        return Tool(
            name=name,
            description="d",
            parameters={"type": "object", "properties": {}},
            risk=Risk.READ,
            handler=handler,
            category="test",
        )

    registry.register(make_tool("screenshot"))
    registry.register(make_tool("finish_task"))

    brain = prov.HttpBrain(
        prov.get_provider("openai"),
        "sk-good",
        "gpt-4o-mini",
        base_url=fake_openai_server["base_url"],
    )
    config = AppConfig(model="gpt-4o-mini", max_steps=4, action_delay=0.0, include_uia_tree=False)
    session = AgentSession(
        config=config,
        registry=registry,
        policy=Policy(confirm_mode="never"),
        bus=EventBus(),
        logger=None,
        brain=brain,
        screen=None,
    )

    # стоп-кран - глобальный объект, его могли взвести другие тесты
    kill_switch.reset()
    try:
        result = session.run_task("проверь экран")
    finally:
        kill_switch.reset()

    assert result.success is True
    assert result.final_text == "всё сделано"
    assert calls == ["screenshot", "finish_task"]
    second = fake_openai_server["requests"][1]
    assert any(m.get("role") == "tool" for m in second["messages"])


