"""Конфигурация приложения: YAML + .env + переменные окружения."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config.example.yaml"

#: Переменные окружения с ключом API, в порядке приоритета.
#:
#: Клиент универсальный: ключ может быть от Google, OpenAI, Anthropic,
#: DeepSeek, OpenRouter и других провайдеров. Поэтому сначала ищется
#: общая переменная PCAGENT_API_KEY, затем частные имена провайдеров -
#: чтобы один и тот же .env работал и при смене провайдера, и в CI.
API_KEY_ENV_NAMES = (
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

#: Понятная подсказка про ключ: не привязываемся к одному провайдеру.
API_KEY_HINT = (
    "ключ API не задан: положите его в .env как PCAGENT_API_KEY "
    "(универсально) или GEMINI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / "
    "OPENROUTER_API_KEY / DEEPSEEK_API_KEY / GROQ_API_KEY / MISTRAL_API_KEY / "
    "TOGETHER_API_KEY, либо укажите api_key в config.yaml"
)

#: Значение model, при котором модель подбирается под провайдера ключа.
AUTO_MODEL = "auto"

CONFIRM_MODES = ("never", "risky", "always")
ALL_CATEGORIES = ("capture", "input", "windows", "system")


@dataclass
class AppConfig:
    # --- доступ к модели ---
    api_key: str = ""
    # "auto" - подобрать модель под провайдера ключа (см. providers.py).
    # Так клиент не привязан ни к Google, ни к какой-либо другой модели.
    model: str = AUTO_MODEL
    # Запасные модели задаются вручную; по умолчанию список пуст, потому что
    # имена моделей у разных провайдеров несовместимы.
    fallback_models: list[str] = field(default_factory=list)
    temperature: float = 0.2
    request_timeout_s: int = 120
    stub_mode: bool = False          # оффлайн-режим со скриптованным "мозгом"

    # --- агентный цикл ---
    max_steps: int = 100
    action_delay: float = 0.7        # пауза после действия, секунды
    max_history_images: int = 3      # сколько снимков хранить в истории диалога
    max_tool_result_chars: int = 6000  # предел размера одного ответа инструмента
    keep_tool_results: int = 6       # сколько последних результатов хранить полностью

    # --- снимки экрана ---
    monitor: int = 0                 # 0 - основная область/монитор, -1 - все мониторы
    screenshot_max_width: int = 1440
    screenshot_format: str = "jpeg"
    screenshot_quality: int = 70
    save_screenshots: bool = False
    screenshot_dir: str = "screenshots"

    # --- чтение интерфейса ---
    include_uia_tree: bool = True
    uia_max_nodes: int = 250
    #: Исключать окно клиента из снимков экрана. Иначе модель видит на
    #: снимке саму себя и свой чат вместо целевой программы.
    hide_from_screenshots: bool = True

    # --- безопасность ---
    confirm_mode: str = "risky"      # never | risky | always
    allow_destructive: bool = True
    allow_shell: bool = True
    dry_run: bool = False

    # --- прочее ---
    language: str = "ru"
    enabled_categories: list[str] = field(default_factory=lambda: list(ALL_CATEGORIES))
    log_dir: str = "logs"
    stop_hotkey: str = "ctrl+alt+q"
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        self.model = str(self.model).strip()
        self.confirm_mode = str(self.confirm_mode).strip().lower() or "risky"
        self.screenshot_format = str(self.screenshot_format).strip().lower() or "jpeg"
        try:
            self.temperature = float(self.temperature)
        except (TypeError, ValueError):
            self.temperature = 0.2
        self.max_steps = max(1, int(self.max_steps))
        self.screenshot_max_width = max(320, int(self.screenshot_max_width))
        self.uia_max_nodes = max(10, int(self.uia_max_nodes))
        if isinstance(self.enabled_categories, str):
            self.enabled_categories = [c.strip() for c in self.enabled_categories.split(",") if c.strip()]
        if not self.enabled_categories:
            self.enabled_categories = list(ALL_CATEGORIES)

    # ------------------------------------------------------------------
    @property
    def log_path(self) -> Path:
        p = Path(self.log_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def screenshots_path(self) -> Path:
        p = Path(self.screenshot_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path = DEFAULT_CONFIG_PATH) -> Path:
        import yaml

        target = Path(path)
        data = self.to_dict()
        # Ключ API НИКОГДА не пишется в config.yaml: этот файл не в .gitignore
        # и легко уезжает в репозиторий. Ключ живёт только в .env.
        data.pop("api_key", None)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
        return target

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AppConfig":
        data = dict(data or {})
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        unknown = {k: v for k, v in data.items() if k not in known}
        cfg = cls(**clean)
        if unknown:
            cfg.extra = {**cfg.extra, **unknown}
        return cfg

    # ------------------------------------------------------------------
    def resolve_api_key_sources(self) -> list[tuple[str, str]]:
        """Все найденные ключи: [(имя источника, значение)].

        Ключ может прийти сразу из нескольких мест: переменная окружения,
        файл .env, поле api_key в config.yaml. Первая запись выигрывает -
        так же, как в resolve_api_key(). Список нужен, чтобы показать
        пользователю, откуда взят ключ и не затеняет ли его старая
        переменная окружения.
        """
        sources: list[tuple[str, str]] = []
        for name in API_KEY_ENV_NAMES:
            value = os.environ.get(name, "").strip()
            if value:
                sources.append((name, value))
        inline = (self.api_key or "").strip()
        if inline:
            sources.append(("config.yaml api_key", inline))
        return sources

    def resolve_api_key(self) -> str:
        """Ключ API: переменные окружения имеют приоритет над файлом конфигурации."""
        for name in API_KEY_ENV_NAMES:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return (self.api_key or "").strip()

    def validate(self) -> list[str]:
        issues: list[str] = []
        if self.confirm_mode not in CONFIRM_MODES:
            issues.append(f"confirm_mode={self.confirm_mode!r} неизвестен, ожидается одно из {CONFIRM_MODES}")
        if self.screenshot_format not in ("jpeg", "png"):
            issues.append(f"screenshot_format={self.screenshot_format!r}, ожидается 'jpeg' или 'png'")
        if not 1 <= self.screenshot_quality <= 100:
            issues.append("screenshot_quality должен быть в диапазоне 1..100")
        if not self.resolve_api_key() and not self.stub_mode:
            issues.append(API_KEY_HINT)
        return issues


def load_env(path: str | Path = DEFAULT_ENV_PATH) -> None:
    """Подхватить .env, если установлен python-dotenv.

    Переменная PCAGENT_NO_ENV=1 отключает чтение файла: так тесты остаются
    герметичными и не зависят от .env на машине разработчика.
    """
    if os.environ.get("PCAGENT_NO_ENV", "").strip() in ("1", "true", "yes", "on"):
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - необязательная зависимость
        return
    target = Path(path)
    if target.exists():
        load_dotenv(target, override=False)


def load_config(
    path: str | Path | None = None,
    *,
    overrides: dict[str, Any] | None = None,
    use_env: bool = True,
) -> AppConfig:
    """Загрузить конфигурацию: .env -> YAML -> явные переопределения."""
    if use_env:
        load_env()
    data: dict[str, Any] = {}
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if target.exists():
        import yaml

        try:
            raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                data = raw
        except Exception as exc:  # noqa: BLE001 - конфигурация не должна ронять запуск
            raise ValueError(f"Не удалось прочитать {target}: {exc}") from exc
    if overrides:
        data.update({k: v for k, v in overrides.items() if v is not None})
    cfg = AppConfig.from_dict(data)
    env_model = os.environ.get("PCAGENT_MODEL", "").strip()
    if env_model:
        cfg.model = env_model
    if not cfg.dry_run:
        cfg.dry_run = os.environ.get("PCAGENT_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on")
    return cfg
