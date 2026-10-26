"""Отбор инструментов под задачу и сжатие их описаний.

Модель получает декларации всех инструментов на КАЖДОМ шаге, потому что
chat/completions не хранит состояние. Замер на 29 инструментах: 14 237
символов (около 4 745 токенов) служебного текста на каждый запрос. Для
задачи "открой orcaslicer" инструменты drag, scroll, clipboard_set и
десяток других не нужны вовсе.

Модуль решает две задачи:
  * оставляет только инструменты, нужные задаче;
  * сокращает описания, сохраняя структуру параметров без изменений.

Жёсткие правила (нарушать нельзя):
  * инструменты категории capture (screenshot, screen_info, ui_tree)
    остаются всегда - клиент задуман как агент, который читает экран;
  * finish_task остаётся всегда;
  * если по тексту задачи ничего не распознано, возвращаются все
    инструменты: лучше потратить токены, чем лишить модель действия.

Правки живут в GUI: общий реестр и модули инструментов не меняются.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

#: Имя встроенного инструмента завершения задачи.
FINISH_TOOL = "finish_task"

#: Категория инструментов экрана: не фильтруется никогда.
CAPTURE_CATEGORY = "capture"

#: Минимальный набор, который остаётся всегда.
CORE_TOOLS: tuple[str, ...] = (
    "run_script",     # универсальный путь: любой сценарий PowerShell/cmd/Python
    "ui_tree",        # элементы интерфейса текстом
    "screen_info",    # геометрия экрана и активное окно
    "screenshot",     # экран нужен по замыслу продукта
)

#: Инструменты экрана: помимо категории capture тянутся по смыслу задачи.
SCREEN_TOOLS: tuple[str, ...] = ("screenshot",)

#: Группы инструментов и основы слов, которые их включают.
#: Основы (а не целые слова) выбраны из-за русской морфологии:
#: "открой", "открыть", "открывает" -> основа "откр".
GROUPS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "window": (
        (
            "откр", "запуст", "закр", "окн", "сверн", "разверн", "переключ",
            "фокус", "приложен", "программ", "ярлык",
            "open", "launch", "close", "window", "focus", "switch", "app",
        ),
        (
            "launch_app", "close_window", "focus_window", "list_windows",
            "wait_for_window", "minimize_window", "maximize_window",
            "restore_window", "move_window",
        ),
    ),
    "input": (
        (
            "нажм", "клик", "щелк", "введ", "напечат", "текст", "выдел",
            "прокрут", "перетащ", "сочетан", "горяч", "посчита", "набер",
            "заполн", "отмет", "выбер",
            "click", "press", "type", "keyboard", "mouse", "scroll",
            "drag", "hotkey", "shortcut",
        ),
        (
            "click", "type_text", "press_key", "hotkey", "move_mouse",
            "scroll", "drag",
        ),
    ),
    "screen": (
        (
            "экран", "скриншот", "снимок", "посмотр", "видиш", "что на",
            "изображен", "картинк",
            "screenshot", "screen", "look", "vision", "image",
        ),
        SCREEN_TOOLS,
    ),
    "files": (
        (
            "файл", "папк", "каталог", "сохран", "документ", "директори",
            "file", "folder", "directory", "save", "path",
        ),
        ("open_path", "start_uri"),
    ),
    "process": (
        (
            "процесс", "служб", "заверш", "убей", "убить", "завис",
            "process", "service", "kill", "hang",
        ),
        ("list_processes", "kill_process"),
    ),
    "clipboard": (
        ("буфер", "скопир", "встав", "clipboard", "copy", "paste"),
        ("clipboard_get", "clipboard_set"),
    ),
    "system": (
        (
            "систем", "верси", "диск", "памят", "процессор", "сеть",
            "железо", "батаре", "system", "info", "disk", "memory",
            "cpu", "network", "battery",
        ),
        ("get_system_info", "run_powershell", "run_command"),
    ),
}

#: Связки между группами: если найдена группа-ключ, добавляется группа-значение.
#:
#: input -> screen: инструменты ввода работают в координатах снимка.
IMPLIES: dict[str, tuple[str, ...]] = {
    "input": ("screen",),
}

#: Связки на уровне отдельных инструментов.
#:
#: window -> базовый ввод: приложение почти никогда не открывают "просто так",
#:   его открывают, чтобы что-то в нём сделать. Без этой связки задача
#:   "открой калькулятор и посчитай 15*7" получала launch_app без click и
#:   type_text: модель видела окно, но не могла в нём работать.
#:   Тянем только базовый ввод, а не всю группу: drag/scroll/move_mouse для
#:   открытия приложения действительно не нужны.
IMPLIES_TOOLS: dict[str, tuple[str, ...]] = {
    "window": ("click", "type_text", "press_key", "hotkey"),
}

#: Сколько символов оставлять в описании инструмента и параметра.
#: 200 выбрано осознанно: при 130 теряются подсказки вроде "поддерживаемые
#: языки" и "предпочитай это вместо снимков", а выигрыш даёт всего 8%.
#: Основная экономия идёт от отбора инструментов, а не от сжатия текста.
MAX_DESC_CHARS = 200
MAX_PARAM_CHARS = 70


def detect_groups(task: str) -> set[str]:
    """Определить группы инструментов по тексту задачи."""
    text = str(task or "").lower()
    if not text.strip():
        return set()
    found: set[str] = set()
    for group, (keywords, _tools) in GROUPS.items():
        for keyword in keywords:
            if keyword in text:
                found.add(group)
                break
    # группа ввода тянет за собой снимок экрана
    for group in list(found):
        for implied in IMPLIES.get(group, ()):
            found.add(implied)
    return found


def _first_sentence(text: str, limit: int) -> str:
    """Первое предложение описания, обрезанное по границе слова."""
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    cut = clean[:limit]
    for mark in (". ", "; ", ", "):
        position = cut.rfind(mark)
        if position > limit // 3:
            return cut[: position + 1].strip()
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).strip() + " ..."


def compact_declaration(declaration: dict[str, Any]) -> dict[str, Any]:
    """Сжать текстовые части декларации, не трогая структуру параметров."""
    result = dict(declaration)
    description = str(result.get("description") or "")
    if description:
        result["description"] = _first_sentence(description, MAX_DESC_CHARS)

    parameters = result.get("parameters")
    if isinstance(parameters, dict):
        properties = parameters.get("properties")
        if isinstance(properties, dict):
            compact_props: dict[str, Any] = {}
            for name, spec in properties.items():
                if not isinstance(spec, dict):
                    compact_props[name] = spec
                    continue
                item = dict(spec)
                param_desc = str(item.get("description") or "")
                if param_desc:
                    item["description"] = _first_sentence(param_desc, MAX_PARAM_CHARS)
                compact_props[name] = item
            new_params = dict(parameters)
            new_params["properties"] = compact_props
            result["parameters"] = new_params
    return result


class FilteredRegistry:
    """Обёртка реестра: модель видит только нужные декларации.

    Выполнение делегируется исходному реестру целиком: если модель всё же
    назовёт отфильтрованный инструмент, он сработает, а не вернёт ошибку.
    """

    def __init__(self, inner: Any, keep: Sequence[str], compact: bool = True) -> None:
        self._inner = inner
        keep_set = {str(name) for name in keep}
        source = dict(getattr(inner, "_tools", {}) or {})
        self._tools = {name: tool for name, tool in source.items() if name in keep_set}
        self._compact = bool(compact)

    # --- совместимость с ToolRegistry --------------------------------
    def get(self, name: str) -> Any:
        return self._tools.get(name)

    def all(self) -> list[Any]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return sorted(self._tools)

    def categories(self) -> list[str]:
        return sorted({tool.category for tool in self._tools.values()})

    def declarations(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for tool in self._tools.values():
            declaration = tool.declaration()
            result.append(compact_declaration(declaration) if self._compact else declaration)
        return result

    def execute(self, ctx: Any, name: str, args: dict[str, Any] | None = None) -> Any:
        return self._inner.execute(ctx, name, args)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        # Проверка членства смотрит на ПОЛНЫЙ реестр: модель видит только
        # отобранные декларации, но если назовёт другой инструмент, он
        # должен выполниться, а не считаться несуществующим.
        return name in self._inner

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)


def always_kept(registry: Any) -> set[str]:
    """Инструменты, которые не фильтруются ни при каких условиях."""
    keep: set[str] = set(CORE_TOOLS) | {FINISH_TOOL}
    for name, tool in dict(getattr(registry, "_tools", {}) or {}).items():
        if str(getattr(tool, "category", "")) == CAPTURE_CATEGORY:
            keep.add(name)
    return keep


def filter_registry(
    registry: Any,
    task: str,
    *,
    enabled: bool = True,
    compact: bool = True,
) -> tuple[Any, dict[str, Any]]:
    """Отфильтровать реестр под задачу.

    Возвращает (реестр или обёртку, сведения об отборе). При выключенном
    отборе и при нераспознанной задаче возвращается исходный реестр.
    """
    source = dict(getattr(registry, "_tools", {}) or {})
    info: dict[str, Any] = {
        "total": len(source),
        "kept": len(source),
        "groups": [],
        "fallback": False,
        "enabled": bool(enabled),
        "compacted": False,
    }
    if not enabled or not source:
        return registry, info

    groups = detect_groups(task)
    info["groups"] = sorted(groups)
    if not groups:
        # Ничего не распознали - оставляем ВСЕ инструменты, это безопаснее.
        # Но описания всё равно сжимаем: структура параметров не меняется,
        # поэтому риск нулевой, а экономия есть.
        info["fallback"] = True
        info["compacted"] = bool(compact)
        return FilteredRegistry(registry, sorted(source), compact=compact), info

    keep = always_kept(registry)
    for group in groups:
        keep.update(GROUPS[group][1])
        keep.update(IMPLIES_TOOLS.get(group, ()))
    # Инструменты из IMPLIES_TOOLS существуют не во всех сборках:
    # оставляем только те, что реально есть в реестре.
    keep = {name for name in keep if name in source}

    # слишком агрессивный отбор недопустим
    if len(keep) < 3:
        info["fallback"] = True
        return registry, info

    info["kept"] = len([name for name in source if name in keep])
    info["compacted"] = bool(compact)
    return FilteredRegistry(registry, sorted(keep), compact=compact), info


def _flag(config: Any, key: str, default: bool) -> bool:
    """Прочитать булев флаг из config.extra."""
    value = (getattr(config, "extra", None) or {}).get(key)
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "да")
    return bool(value)


def routing_enabled(config: Any) -> bool:
    """Включён ли отбор инструментов (по умолчанию да)."""
    return _flag(config, "tool_routing", True)


def compacting_enabled(config: Any) -> bool:
    """Включено ли сжатие описаний (по умолчанию да)."""
    return _flag(config, "tool_compact", True)


def declaration_size(declarations: Iterable[dict[str, Any]]) -> int:
    """Размер деклараций в символах - для отчёта об экономии."""
    import json

    return len(json.dumps(list(declarations or []), ensure_ascii=False))
