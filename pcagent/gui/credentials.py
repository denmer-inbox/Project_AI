r"""Автоматический поиск, проверка и сохранение ключей API и настроек агента.

Модуль намеренно не импортирует tkinter: им пользуется и GUI, и любые
другие точки входа (CLI может вызывать те же функции).

Ключ ищется по всем типовым источникам в порядке приоритета:
  1. переменные окружения процесса (PCAGENT_API_KEY, затем частные имена
     провайдеров: GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY,
     OPENROUTER_API_KEY, DEEPSEEK_API_KEY, GROQ_API_KEY, MISTRAL_API_KEY,
     TOGETHER_API_KEY);
  2. файл .env проекта;
  3. файл .env рядом с проектом и в домашнем каталоге пользователя;
  4. %APPDATA%\PCAgent\.env и ~/.pcagent/.env;
  5. переменные окружения Windows из реестра (пользователя и системы);
  6. поле api_key в config.yaml.

Сохранение ключа никогда не пишет его в журнал: наружу отдаётся только
маска вида AIzaSy...4fGh.
"""

from __future__ import annotations

import os
import re
import tempfile
import winreg
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Имена переменных окружения с ключом, в порядке приоритета.
#: Клиент универсальный, поэтому первым идёт общее имя, а частные имена
#: провайдеров нужны, чтобы работали привычные .env и системные переменные.
API_KEY_ENV_NAMES: tuple[str, ...] = (
    "PCAGENT_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "TOGETHER_API_KEY",
)

#: Каноническое имя переменной, в которое проект пишет найденный ключ.
#: Общее имя, а не GEMINI_API_KEY: ключ может быть от любого провайдера.
PRIMARY_ENV_NAME = "PCAGENT_API_KEY"

#: Ключи Google AI Studio начинаются с AIza и имеют длину около 39 символов.
KEY_PATTERN = re.compile(r"^AIza[0-9A-Za-z_\-]{20,80}$")

REGISTRY_PATHS: tuple[tuple[int, str, str], ...] = (
    (winreg.HKEY_CURRENT_USER, r"Environment", "реестр Windows (пользователь)"),
    (
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        "реестр Windows (система)",
    ),
)


@dataclass(frozen=True)
class KeySource:
    """Найденный ключ API вместе с описанием источника."""

    key: str
    source: str
    path: str | None = None

    @property
    def masked(self) -> str:
        return mask_key(self.key)

    def describe(self) -> str:
        return f"{self.source}: {self.masked}"


@dataclass(frozen=True)
class VerificationResult:
    """Результат проверки ключа на сервере."""

    ok: bool
    message: str
    models: tuple[str, ...] = ()
    provider_id: str = ""
    provider_title: str = ""
    base_url: str = ""
    model: str = ""


#: Ключ внутри произвольного текста (вывод консоли, JSON, строка .env).
KEY_IN_TEXT_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{30,50}")

#: Префиксы, которые пользователи копируют вместе с ключом.
KEY_PREFIXES: tuple[str, ...] = (
    "PCAGENT_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "TOGETHER_API_KEY",
    "API_KEY",
)


def extract_key(text: str | None) -> str | None:
    """Вытащить ключ API любого провайдера из текста буфера обмена.

    Понимает: чистый ключ, строку вида KEY=значение, значение в кавычках,
    JSON-фрагмент и текст с ключом внутри. Возвращает None, если ключа
    не нашлось.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    # 1. Ключ любого поддерживаемого провайдера прямо в тексте.
    match = _any_key_pattern().search(raw)
    if match:
        return match.group(0)

    # 2. Строка вида KEY=значение или "KEY": "значение".
    candidate = raw
    for prefix in KEY_PREFIXES:
        if candidate.upper().startswith(prefix):
            _, _, rest = candidate.partition("=")
            if not rest:
                _, _, rest = candidate.partition(":")
            candidate = rest
            break
    candidate = candidate.strip().strip("'\"").strip().rstrip(",;").strip()

    if looks_like_any_key(candidate):
        return candidate
    return None


def read_clipboard(widget: Any = None) -> str:
    """Прочитать текст буфера обмена.

    Сначала пробуем pyperclip (работает без окна), затем буфер tkinter
    через переданный виджет. Возвращает пустую строку при неудаче.
    """
    try:
        import pyperclip

        value = pyperclip.paste()
        if value:
            return str(value)
    except Exception:  # noqa: BLE001 - буфер может быть занят другим процессом
        pass

    if widget is not None:
        try:
            return str(widget.clipboard_get())
        except Exception:  # noqa: BLE001 - пустой или не текстовый буфер
            return ""
    return ""


URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


def extract_url(text: str | None) -> str | None:
    """Вытащить адрес API из произвольного текста буфера обмена.

    Понимает: чистый URL, URL в кавычках, строку BASE_URL=..., адрес
    внутри текста. Возвращает None, если адреса нет. Хвостовой слэш,
    кавычки и знаки препинания отбрасываются.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    match = URL_PATTERN.search(raw)
    if not match:
        return None
    url = match.group(0)
    url = url.rstrip("\"' ,;.)]}>")
    url = url.rstrip("/")
    if not url.startswith(("http://", "https://")):
        return None
    if len(url) < 12:
        return None
    return url


def looks_like_url(text: str | None) -> bool:
    """Похож ли текст на адрес API."""
    return extract_url(text) is not None


def mask_key(key: str | None) -> str:
    """Показать ключ в безопасном виде: начало и последние символы."""
    value = (key or "").strip()
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def looks_like_google_key(key: str | None) -> bool:
    """Похож ли ключ на ключ Google AI Studio."""
    return bool(KEY_PATTERN.match((key or "").strip()))


def _any_key_pattern() -> Any:
    """Регулярка ключей всех провайдеров (или только Google как запасной)."""
    try:
        from pcagent.gui import providers

        return providers.ANY_KEY_PATTERN
    except Exception:  # noqa: BLE001 - модуль провайдеров необязателен
        return KEY_IN_TEXT_PATTERN


def looks_like_any_key(key: str | None) -> bool:
    """Похож ли текст на ключ любого поддерживаемого провайдера."""
    value = (key or "").strip()
    if not value:
        return False
    try:
        from pcagent.gui import providers

        return providers.looks_like_any_key(value)
    except Exception:  # noqa: BLE001
        return looks_like_google_key(value)


def read_env_file(path: str | Path) -> dict[str, str]:
    """Прочитать .env в UTF-8, UTF-8 BOM или UTF-16 и вернуть словарь.

    Битые файлы и отсутствующие пути дают пустой словарь: поиск ключа не
    должен падать из-за одного испорченного файла.
    """
    target = Path(path)
    try:
        raw = target.read_bytes()
    except (OSError, ValueError):
        return {}

    text = ""
    for encoding in ("utf-8-sig", "utf-16", "utf-8", "cp1251"):
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if text:
            break
    if not text:
        return {}

    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("export "):
            stripped = stripped[7:].strip()
        if "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if name:
            result[name] = value
    return result


def candidate_env_files(project_root: str | Path | None = None) -> list[Path]:
    """Список путей к .env, которые имеет смысл проверять (по приоритету)."""
    root = Path(project_root) if project_root is not None else Path.cwd()
    home = Path.home()
    appdata = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")

    candidates: list[Path] = [
        root / ".env",
        root.parent / ".env",
        home / ".pcagent" / ".env",
        home / ".env",
    ]
    if appdata:
        candidates.append(Path(appdata) / "PCAgent" / ".env")
    if localappdata:
        candidates.append(Path(localappdata) / "PCAgent" / ".env")

    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def registry_env(names: tuple[str, ...] = API_KEY_ENV_NAMES) -> dict[str, str]:
    """Переменные окружения Windows из реестра (пользователь и система).

    Нужны, когда ключ задан через свойства системы, но текущий процесс
    запущен до обновления окружения.
    """
    wanted = {name.upper() for name in names}
    found: dict[str, str] = {}
    for hive, subkey, _label in REGISTRY_PATHS:
        try:
            with winreg.OpenKey(hive, subkey) as handle:
                index = 0
                while True:
                    try:
                        name, value, _kind = winreg.EnumValue(handle, index)
                    except OSError:
                        break
                    index += 1
                    if name.upper() in wanted and str(value).strip():
                        found.setdefault(name.upper(), str(value).strip())
        except OSError:
            continue
    return found


def discover_keys(
    config: Any = None,
    project_root: str | Path | None = None,
    *,
    include_process_env: bool = True,
    include_registry: bool = True,
) -> list[KeySource]:
    """Найти все ключи API во всех известных источниках.

    Результат отсортирован по приоритету и очищен от дубликатов: первым
    идёт самый надёжный источник.
    """
    found: list[KeySource] = []

    if include_process_env:
        for name in API_KEY_ENV_NAMES:
            value = (os.environ.get(name) or "").strip()
            if value:
                found.append(KeySource(value, f"переменная окружения {name}"))

    for path in candidate_env_files(project_root):
        data = read_env_file(path)
        for name in API_KEY_ENV_NAMES:
            value = (data.get(name) or "").strip()
            if value:
                found.append(KeySource(value, f"файл {path.name}", str(path)))

    if include_registry:
        for name, value in registry_env().items():
            found.append(KeySource(value, f"реестр Windows: {name}"))

    config_key = str(getattr(config, "api_key", "") or "").strip()
    if config_key:
        found.append(KeySource(config_key, "config.yaml (api_key)"))

    unique: list[KeySource] = []
    seen: set[str] = set()
    for item in found:
        if item.key in seen:
            continue
        seen.add(item.key)
        unique.append(item)
    return unique


def resolve_best_key(
    config: Any = None,
    project_root: str | Path | None = None,
    **kwargs: Any,
) -> KeySource | None:
    """Выбрать лучший ключ: сначала похожие на настоящие, потом остальные."""
    candidates = discover_keys(config, project_root, **kwargs)
    if not candidates:
        return None
    for item in candidates:
        if looks_like_google_key(item.key):
            return item
    return candidates[0]


def apply_key(config: Any, source: KeySource) -> KeySource:
    """Прописать ключ в конфигурацию и в окружение процесса.

    resolve_api_key() в config.py смотрит сначала на переменные окружения,
    поэтому ключ выставляется и туда: этого достаточно и для llm.py.
    """
    key = source.key.strip()
    try:
        config.api_key = key
    except Exception:  # noqa: BLE001 - конфиг может быть неизменяемым
        pass
    os.environ[PRIMARY_ENV_NAME] = key
    return source


def save_key(
    key: str,
    path: str | Path | None = None,
    project_root: str | Path | None = None,
) -> Path:
    """Сохранить ключ в .env, не затирая остальные переменные.

    Запись атомарная: сначала временный файл рядом, затем os.replace.
    """
    value = (key or "").strip()
    if not value:
        raise ValueError("пустой ключ API")
    target = Path(path) if path is not None else (
        Path(project_root) / ".env" if project_root is not None else Path.cwd() / ".env"
    )

    existing = read_env_file(target)
    # Уважаем имя переменной, которое уже есть в файле: если пользователь
    # держит там GEMINI_API_KEY, не заводим рядом вторую переменную с тем же
    # ключом. Для нового файла используем общее имя PCAGENT_API_KEY.
    chosen_name = PRIMARY_ENV_NAME
    for name in API_KEY_ENV_NAMES:
        if name in existing:
            chosen_name = name
            break
    existing[chosen_name] = value
    for name in API_KEY_ENV_NAMES:
        if name != chosen_name:
            existing.pop(name, None)

    lines = [
        "# Ключи PC Agent. Файл создан автоматически, не коммитьте его в git.",
        f"{chosen_name}={value}",
    ]
    for name, item in existing.items():
        if name == chosen_name:
            continue
        lines.append(f"{name}={item}")

    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=".env-", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return target


def remove_saved_key(path: str | Path | None = None, project_root: str | Path | None = None) -> bool:
    """Удалить ключ из .env. Возвращает True, если файл был изменён."""
    target = Path(path) if path is not None else (
        Path(project_root) / ".env" if project_root is not None else Path.cwd() / ".env"
    )
    data = read_env_file(target)
    if not any(name in data for name in API_KEY_ENV_NAMES):
        return False
    for name in API_KEY_ENV_NAMES:
        data.pop(name, None)
    target.write_text(
        "\n".join(f"{name}={value}" for name, value in data.items()) + "\n",
        encoding="utf-8",
    )
    return True


def _friendly_error(exc: Exception) -> str:
    """Перевести ошибку SDK в понятный текст на русском."""
    text = str(exc)
    low = text.lower()
    if "api key not valid" in low or "api_key_invalid" in low or "400" in low:
        return "ключ не принят провайдером: проверьте, что он скопирован целиком"
    if "permission" in low or "403" in low:
        return "ключ действителен, но доступ к модели запрещён (403)"
    if "quota" in low or "429" in low or "resource_exhausted" in low:
        return "превышена квота запросов (429): попробуйте позже"
    if "timeout" in low or "deadline" in low:
        return "истекло время ожидания ответа провайдера"
    if "getaddrinfo" in low or "connection" in low or "network" in low:
        return "нет связи с серверами провайдера (проверьте интернет)"
    return f"ошибка проверки ключа: {text[:200]}"


def verify_key(key: str, timeout_s: int = 20, config: Any = None) -> VerificationResult:
    """Проверить ключ у его провайдера и подобрать модель.

    Провайдер определяется по префиксу ключа; если он не угадан, ключ
    по очереди проверяется у остальных OpenAI-совместимых провайдеров.
    Сетевой вызов: выполняется только по явному действию пользователя.
    """
    value = (key or "").strip()
    if not value:
        return VerificationResult(False, "ключ не задан")

    # Явно не ключ - отказываем сразу, без сетевых запросов.
    if not looks_like_any_key(value):
        return VerificationResult(
            False,
            "не похоже на ключ API. Ожидается ключ вида AIza... (Google), "
            "sk-... (OpenAI/DeepSeek), sk-ant-... (Anthropic), gsk_... (Groq) "
            "или укажите адрес своего API в поле base_url",
        )

    try:
        from pcagent.gui import providers
    except Exception as exc:  # noqa: BLE001
        return VerificationResult(False, f"модуль провайдеров недоступен: {exc}")

    candidates = providers.candidate_providers(value)
    if not candidates:
        return VerificationResult(False, "не удалось определить провайдера по ключу")

    # Пользовательский base_url (свой шлюз) проверяем первым и отдельно.
    # ВАЖНО: для Google-ключа адрес не применяется - Google работает через
    # собственный SDK, и отправлять ключ AIza... на чужой endpoint нельзя.
    custom_base = ""
    if config is not None and not candidates[0].google_sdk:
        custom_base = str((getattr(config, "extra", None) or {}).get("base_url") or "").strip()
    if custom_base:
        provider = candidates[0]
        current = str(getattr(config, "model", "") or "").strip()
        models, _list_error = providers.fetch_models(
            provider, value, base_url=custom_base, timeout_s=timeout_s
        )
        if current and current not in models:
            models = [current, *models]
        model, error = providers.find_working_model(
            provider, value, models, base_url=custom_base, timeout_s=timeout_s
        )
        if model:
            return VerificationResult(
                True,
                f"ключ работает на {custom_base}, модель {model}",
                tuple(models),
                provider_id=provider.id,
                provider_title=provider.title,
                base_url=custom_base,
                model=model,
            )
        return VerificationResult(
            False,
            f"ключ не принят по адресу {custom_base}. "
            f"{providers.friendly_error(error or '')}",
            provider_id=provider.id,
            provider_title=provider.title,
            base_url=custom_base,
        )

    errors: list[str] = []
    for provider in candidates:
        # Список моделей нужен только чтобы знать кандидатов.
        models, list_error = providers.fetch_models(provider, value, timeout_s=timeout_s)

        # Ключ валидируется реальным запросом к модели: у части
        # провайдеров /models публичный и отвечает 200 даже на мусор.
        # Заодно перебираем модели: у посредников права уже каталога.
        model, chat_error = providers.find_working_model(
            provider, value, models, timeout_s=timeout_s
        )
        if model:
            return VerificationResult(
                True,
                f"{provider.title}: ключ работает, выбрана модель {model} "
                f"(в каталоге {len(models) or 1})",
                tuple(models),
                provider_id=provider.id,
                provider_title=provider.title,
                base_url=provider.base_url,
                model=model,
            )
        detail = chat_error or list_error or "нет ответа"
        errors.append(f"{provider.title}: {providers.friendly_error(detail)}")

    detail = errors[0] if errors else "ни один провайдер не принял ключ"
    return VerificationResult(
        False, f"ключ не принят. {detail}",
        provider_id=(candidates[0].id if candidates else ""),
        provider_title=(candidates[0].title if candidates else ""),
    )


_MONITOR_CACHE: int | None = None


def detect_monitors(use_cache: bool = True) -> int:
    """Число мониторов без тяжёлых зависимостей; 1 при любой ошибке."""
    global _MONITOR_CACHE
    if use_cache and _MONITOR_CACHE is not None:
        return _MONITOR_CACHE
    count = 1
    try:
        import mss

        factory = getattr(mss, "MSS", None) or mss.mss
        with factory() as sct:
            count = max(1, len(sct.monitors) - 1)
    except Exception:  # noqa: BLE001 - без mss считаем один монитор
        count = 1
    _MONITOR_CACHE = count
    return count


def autoconfigure(config: Any, path: str | Path | None = None) -> dict[str, Any]:
    """Подтянуть настройки под эту машину и сохранить config.yaml.

    Вызывается при старте GUI: заполняет пропущенные/некорректные значения
    (монитор, ширина снимка, число шагов) и создаёт файл конфигурации,
    если его ещё нет.
    """
    from pcagent.config import DEFAULT_CONFIG_PATH

    changes: dict[str, Any] = {}
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH

    monitors = detect_monitors()
    try:
        monitor = int(getattr(config, "monitor", 0))
    except (TypeError, ValueError):
        monitor = 0
    if monitor < -1 or monitor >= monitors:
        changes["monitor"] = 0
        config.monitor = 0

    try:
        width = int(getattr(config, "screenshot_max_width", 1440))
    except (TypeError, ValueError):
        width = 1440
    if width < 320:
        changes["screenshot_max_width"] = 1440
        config.screenshot_max_width = 1440

    try:
        steps = int(getattr(config, "max_steps", 25))
    except (TypeError, ValueError):
        steps = 25
    if steps < 1:
        changes["max_steps"] = 25
        config.max_steps = 25

    saved: Path | None = None
    if not target.exists():
        try:
            saved = config.save(target)
            changes["config_file"] = str(saved)
        except Exception as exc:  # noqa: BLE001 - запись не обязательна
            changes["config_error"] = str(exc)
    return changes


def describe_key_state(config: Any) -> str:
    """Короткая строка о состоянии ключа для статус-бара."""
    key = ""
    try:
        key = str(config.resolve_api_key() or "")
    except Exception:  # noqa: BLE001
        key = str(getattr(config, "api_key", "") or "")
    if not key:
        return "ключ API не найден"
    return f"ключ {mask_key(key)}"
