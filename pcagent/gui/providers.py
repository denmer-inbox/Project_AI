"""Автоопределение провайдера ИИ по ключу и универсальный мозг.

У каждого провайдера свой префикс ключа: AIza... у Google, sk-... у
OpenAI и OpenRouter, gsk_ у Groq и так далее. Провайдер определяется
по префиксу, поэтому клиент не привязан ни к одной модели.
(sk-proj- у OpenAI, sk-ant- у Anthropic, gsk_ у Groq и так далее).
Модуль определяет провайдера по ключу, сам находит base_url и список
моделей, а затем умеет работать с любым OpenAI-совместимым API.

Возвращаемые ответы структурно совпадают с ответами google-genai
(StubResponse из pcagent.stub_brain), поэтому агентный цикл разбирает их
теми же функциями llm.extract_*.
"""

from __future__ import annotations

import json
import re
import time as _time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

TIMEOUT_S = 20.0


@dataclass(frozen=True)
class Provider:
    """Описание провайдера: как проверить ключ и куда слать запросы."""

    id: str
    title: str
    base_url: str
    default_model: str
    key_prefixes: tuple[str, ...] = ()
    models_path: str = "/models"
    chat_path: str = "/chat/completions"
    google_sdk: bool = False
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    vision: bool = True
    #: Официальный API самой компании-разработчика модели. False означает
    #: посредника: он видит все запросы, включая скриншоты рабочего стола.
    official: bool = False


#: Порядок важен: более специфичные префиксы проверяются раньше.
PROVIDERS: tuple[Provider, ...] = (
    Provider(
        id="google",
        official=True,
        title="Google Gemini",
        base_url="",
        default_model="gemini-2.5-flash",
        key_prefixes=("AIza",),
        google_sdk=True,
    ),
    Provider(
        id="anthropic",
        official=True,
        title="Anthropic Claude",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-3-5-sonnet-latest",
        key_prefixes=("sk-ant-",),
        extra_headers={"anthropic-version": "2023-06-01"},
    ),
    Provider(
        id="cvc",
        official=False,
        title="AI Keys For You (CVC)",
        base_url="https://api.aikeysforyou.com/v1",
        default_model="deepseek-v4-flash",
        key_prefixes=("sk-cvc-",),
        # Каталог моделей больше, чем разрешено конкретному ключу,
        # поэтому стартовую модель подбирает probe по самому ключу.
        vision=True,
    ),
    Provider(
        id="openrouter",
        official=False,
        title="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="google/gemini-2.0-flash-001",
        key_prefixes=("sk-or-v1-",),
    ),
    Provider(
        id="groq",
        official=True,
        title="Groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        key_prefixes=("gsk_",),
    ),
    Provider(
        id="openai",
        official=True,
        title="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        key_prefixes=("sk-proj-", "sk-svcacct-", "sk-"),
    ),
    Provider(
        id="deepseek",
        official=True,
        title="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        key_prefixes=("sk-",),
    ),
    Provider(
        id="mistral",
        official=True,
        title="Mistral",
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-large-latest",
        key_prefixes=("mis_",),
    ),
    Provider(
        id="together",
        official=True,
        title="Together AI",
        base_url="https://api.together.xyz/v1",
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        key_prefixes=("tgp_v1_",),
    ),
)

PROVIDERS_BY_ID: dict[str, Provider] = {item.id: item for item in PROVIDERS}

#: Провайдеры, которые стоит перебрать, если угаданный не принял ключ.
FALLBACK_ORDER: tuple[str, ...] = (
    "cvc",
    "openai",
    "openrouter",
    "deepseek",
    "groq",
    "anthropic",
    "mistral",
    "together",
)

#: Ключ любого провайдера внутри произвольного текста.
ANY_KEY_PATTERN = re.compile(
    r"(?:AIza[0-9A-Za-z_\-]{30,50}"
    r"|sk-cvc-[A-Za-z0-9_\-]{20,200}"
    r"|sk-ant-[A-Za-z0-9_\-]{20,200}"
    r"|sk-or-v1-[A-Za-z0-9]{20,200}"
    r"|sk-proj-[A-Za-z0-9_\-]{20,200}"
    r"|sk-[A-Za-z0-9_\-]{20,200}"
    r"|gsk_[A-Za-z0-9]{20,200}"
    r"|mis_[A-Za-z0-9]{20,200}"
    r"|tgp_v1_[A-Za-z0-9_\-]{20,200})"
)


#: Кого считать официальным API, а кого посредником.
#:
#: Посредник (шлюз) проксирует запросы через себя: он видит текст задачи,
#: снимки экрана и ключ. Официальный API видит только запросы своего
#: продукта и работает по договору с вами напрямую.

PRIVACY_NOTICE_TITLE = "Внимание: данные идут через посредника"

PRIVACY_NOTICE = (
    "Провайдер {title} - посредник, а не API компании-разработчика модели. "
    "Через него проходят текст задач, снимки вашего экрана и ключ API, "
    "то есть всё это видит третья сторона. "
    "Для работы с личными данными используйте официальный ключ "
    "(Google AI Studio: ключ AIza..., адрес API не нужен)."
)


def is_official(provider: Provider | None) -> bool:
    """Официальный ли это API компании-разработчика."""
    return bool(provider is not None and provider.official)


def privacy_notice(provider: Provider | None, model: str = "") -> str:
    """Предупреждение о передаче данных посреднику. Пусто для официальных API."""
    if provider is None or provider.official:
        return ""
    return PRIVACY_NOTICE.format(title=provider.title)


def check_tls(provider: Provider, timeout_s: float = 6.0) -> tuple[bool | None, str]:
    """Проверить TLS-сертификат адреса провайдера.

    Просроченный сертификат означает, что клиент не может убедиться, что
    говорит с нужным сервером. Возвращает (состояние, пояснение):
    True - сертификат в порядке, False - проблема, None - проверить нельзя.
    """
    import socket
    import ssl
    from urllib.parse import urlparse

    if not provider.base_url:
        return None, "адрес не задан (официальный API, проверять нечего)"
    host = urlparse(provider.base_url).hostname or ""
    if not host:
        return None, "не удалось выделить адрес из base_url"

    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=timeout_s) as sock:
            with context.wrap_socket(sock, server_hostname=host) as secure:
                cert = secure.getpeercert()
    except ssl.SSLCertVerificationError as exc:
        return False, f"сертификат {host} не прошёл проверку: {exc}"
    except Exception as exc:  # noqa: BLE001 - нет сети и т.п.
        return None, f"проверить сертификат {host} не удалось: {type(exc).__name__}: {exc}"

    if not cert:
        return None, f"{host} не отдал сертификат"
    not_after = str(cert.get("notAfter") or "")
    return True, f"сертификат {host} действителен до {not_after}"


def get_provider(provider_id: str | None) -> Provider:
    """Провайдер по идентификатору; по умолчанию Google (самый частый случай)."""
    return PROVIDERS_BY_ID.get((provider_id or "").strip().lower(), PROVIDERS[0])


def detect_provider(key: str | None) -> Provider | None:
    """Определить провайдера по префиксу ключа.

    Для неоднозначных ключей (sk-...) возвращается наиболее вероятный
    провайдер; окончательно вопрос решает проверка на сервере.
    """
    value = (key or "").strip()
    if not value:
        return None
    for provider in PROVIDERS:
        for prefix in provider.key_prefixes:
            if value.startswith(prefix):
                return provider
    return None


def looks_like_any_key(key: str | None) -> bool:
    """Похож ли текст на ключ любого поддерживаемого провайдера."""
    return bool(ANY_KEY_PATTERN.fullmatch((key or "").strip()))


def candidate_providers(key: str | None) -> list[Provider]:
    """Кого пробовать проверять: сначала угаданный, затем остальные."""
    detected = detect_provider(key)
    if detected is not None and detected.google_sdk:
        return [detected]
    ordered: list[Provider] = []
    if detected is not None:
        ordered.append(detected)
    for provider_id in FALLBACK_ORDER:
        provider = PROVIDERS_BY_ID[provider_id]
        if provider not in ordered:
            ordered.append(provider)
    return ordered


def auth_headers(provider: Provider, key: str) -> dict[str, str]:
    """Заголовки авторизации для OpenAI-совместимого API."""
    headers = {
        "Authorization": f"Bearer {key.strip()}",
        "Content-Type": "application/json",
    }
    headers.update(dict(provider.extra_headers))
    if provider.id == "anthropic":
        # Anthropic принимает и Bearer (совместимый слой), и x-api-key.
        headers["x-api-key"] = key.strip()
    if provider.id == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/pcagent"
        headers["X-Title"] = "PC Agent"
    return headers


def _clean_model_name(name: str) -> str:
    return str(name or "").replace("models/", "").strip()


def fetch_models(
    provider: Provider,
    key: str,
    base_url: str | None = None,
    timeout_s: float = TIMEOUT_S,
) -> tuple[list[str], str | None]:
    """Список моделей провайдера. Возвращает (модели, текст ошибки)."""
    if provider.google_sdk:
        try:
            from google import genai
        except Exception as exc:  # noqa: BLE001
            return [], f"SDK google-genai недоступен: {exc}"
        try:
            client = genai.Client(
                api_key=key, http_options={"timeout": int(timeout_s * 1000)}
            )
            names = [
                _clean_model_name(getattr(model, "name", ""))
                for model in client.models.list()
            ]
            return [name for name in names if name], None
        except Exception as exc:  # noqa: BLE001
            return [], str(exc)

    try:
        import httpx
    except Exception as exc:  # noqa: BLE001
        return [], f"httpx недоступен: {exc}"

    root = (base_url or provider.base_url).rstrip("/")
    url = root + provider.models_path
    try:
        response = httpx.get(
            url,
            headers=auth_headers(provider, key),
            timeout=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001 - сеть
        return [], f"нет связи с {root}: {exc}"

    if response.status_code != 200:
        return [], f"HTTP {response.status_code}: {response.text[:200]}"

    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        return [], f"ответ не JSON: {exc}"

    raw_items = payload.get("data") if isinstance(payload, dict) else payload
    names: list[str] = []
    for item in raw_items or []:
        if isinstance(item, Mapping):
            name = item.get("id") or item.get("name")
        else:
            name = str(item)
        name = _clean_model_name(str(name or ""))
        if name:
            names.append(name)
    return names, None


#: Путь к остатку у провайдеров-посредников (шлюзов с общим балансом).
#: Путь остатка ОТНОСИТЕЛЬНО base_url. base_url уже содержит версию
#: ("https://host/v1"), поэтому здесь только "/balance": иначе получается
#: ".../v1/v1/balance" и провайдер отвечает 404.
BALANCE_PATH = "/balance"

#: Провайдер ограничивает частоту запросов остатка: 1 в секунду и 60 в минуту.
#: Без паузы второй запрос подряд получает HTTP 429.
BALANCE_MIN_INTERVAL_S = 1.1

#: Провайдеры, у которых остаток смотрят в личном кабинете, а не запросом.
BALANCE_NOTE_GOOGLE = (
    "У Gemini API нет запроса остатка: ключ AI Studio оплачивается по факту, "
    "а расход и лимиты видны в Google Cloud Console -> Billing -> Квоты."
)


@dataclass
class Balance:
    """Остаток токенов на ключе."""

    tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def describe(self) -> str:
        """Человекочитаемая строка остатка."""
        if self.tokens is None:
            return self.note or "Остаток неизвестен"
        return f"{self.tokens:,} токен-единиц".replace(",", " ")


#: Когда последний раз запрашивали остаток (монотонное время).
_balance_last_check = 0.0


def _balance_recently_checked() -> bool:
    """Не слишком ли часто спрашиваем остаток."""
    return (_time.monotonic() - _balance_last_check) < BALANCE_MIN_INTERVAL_S


def _mark_balance_checked() -> None:
    global _balance_last_check
    _balance_last_check = _time.monotonic()


def fetch_balance(
    provider: Provider,
    key: str,
    base_url: str | None = None,
    timeout_s: float = TIMEOUT_S,
) -> tuple[Balance | None, str | None]:
    """Остаток токенов по ключу. Возвращает (Balance, текст ошибки).

    У официального Gemini API такого эндпоинта нет, поэтому для Google
    возвращается None и подсказка, где смотреть расход. Посредники
    (шлюзы с общим балансом) отдают остаток запросом.
    """
    if provider.google_sdk:
        return None, BALANCE_NOTE_GOOGLE

    try:
        import httpx
    except Exception as exc:  # noqa: BLE001
        return None, f"httpx недоступен: {exc}"

    if _balance_recently_checked():
        return None, (
            "остаток только что запрашивали: провайдер разрешает 1 запрос "
            "в секунду и 60 в минуту. Повторите через секунду."
        )

    root = (base_url or provider.base_url).rstrip("/")
    # Некоторые шлюзы держат остаток на корне домена, а не в /v1.
    candidates = [root + BALANCE_PATH]
    if root.endswith("/v1"):
        candidates.append(root[:-3] + "/v1" + BALANCE_PATH)
    response = None
    last_error = ""
    for url in candidates:
        attempt = None
        for attempt_index in range(2):
            try:
                attempt = httpx.get(url, headers=auth_headers(provider, key), timeout=timeout_s)
            except Exception as exc:  # noqa: BLE001 - сеть или TLS
                last_error = f"нет связи с {root}: {exc}"
                attempt = None
                break
            # Ограничение частоты: одна повторная попытка после паузы.
            if attempt.status_code == 429 and attempt_index == 0:
                _time.sleep(BALANCE_MIN_INTERVAL_S)
                continue
            break
        if attempt is None:
            continue
        _mark_balance_checked()
        if attempt.status_code == 200:
            response = attempt
            break
        last_error = f"HTTP {attempt.status_code}: {attempt.text[:200]}"
        response = attempt
    if response is None:
        return None, last_error or f"нет связи с {root}"

    if response.status_code == 404:
        return None, (
            f"{provider.title} не отдаёт остаток запросом (HTTP 404). "
            "Смотрите баланс в личном кабинете провайдера."
        )
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}: {response.text[:200]}"

    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        return None, f"ответ не JSON: {exc}"

    if not isinstance(payload, Mapping):
        return None, "неожиданный формат ответа баланса"

    tokens: int | None = None
    for field_name in ("token_balance", "balance", "tokens", "remaining", "credit"):
        value = payload.get(field_name)
        if isinstance(value, (int, float)):
            tokens = int(value)
            break
    if tokens is None:
        return None, f"в ответе нет остатка: {str(payload)[:200]}"
    return Balance(tokens=tokens, raw=dict(payload)), None


def fetch_multipliers(
    provider: Provider,
    key: str,
    base_url: str | None = None,
    timeout_s: float = TIMEOUT_S,
) -> dict[str, float]:
    """Множители расхода по моделям. Пустой словарь, если их не отдают.

    У шлюзов баланс измеряется не в токенах модели, а в условных единицах:
    запрос по модели с множителем 4 списывает вчетверо больше. Без этого
    остаток вводит в заблуждение.
    """
    if provider.google_sdk:
        return {}
    try:
        import httpx
    except Exception:  # noqa: BLE001
        return {}
    root = (base_url or provider.base_url).rstrip("/")
    try:
        response = httpx.get(
            root + provider.models_path,
            headers=auth_headers(provider, key),
            timeout=timeout_s,
        )
        payload = response.json()
    except Exception:  # noqa: BLE001 - множители необязательны
        return {}
    items = payload.get("data") if isinstance(payload, Mapping) else None
    result: dict[str, float] = {}
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("id") or "")
        value = item.get("multiplier")
        if name and isinstance(value, (int, float)) and float(value) > 0:
            result[name] = float(value)
    return result


#: Значение модели, означающее "подобрать под провайдера".
AUTO_MODEL = "auto"


def model_fits_provider(model: str, provider: Provider) -> bool:
    """Подходит ли имя модели этому провайдеру.

    Имена моделей несовместимы между провайдерами: gemini-* не существует
    у OpenAI, gpt-* не существует у Google. Пустое имя и "auto" означают
    "подбери сам".
    """
    value = str(model or "").strip()
    if not value or value.lower() == AUTO_MODEL:
        return False
    low = value.lower()
    if provider.google_sdk:
        return low.startswith("gemini")
    # Посредникам и чужим API gemini-* заведомо не подходит: 403 model not enabled.
    if low.startswith("gemini"):
        return False
    return True


def resolve_model(
    provider: Provider,
    configured: str,
    key: str | None = None,
    base_url: str | None = None,
    timeout_s: float = TIMEOUT_S,
    probe: bool = True,
) -> str:
    """Подобрать рабочую модель для провайдера.

    Порядок: явно заданная подходящая модель -> модель по умолчанию
    провайдера -> первая разрешённая этому ключу. Проверка настоящим
    запросом выполняется только если передан ключ и probe=True.
    """
    if model_fits_provider(configured, provider):
        return str(configured).strip()

    default = str(provider.default_model or "").strip()
    if not key or not probe:
        return default

    if default:
        ok, _error = probe_chat(provider, key, default, base_url=base_url, timeout_s=timeout_s)
        if ok:
            return default

    models, _error = fetch_models(provider, key, base_url=base_url, timeout_s=timeout_s)
    if not models:
        return default
    found, _error = find_working_model(
        provider, key, models, base_url=base_url, timeout_s=timeout_s
    )
    return found or default


def probe_chat(
    provider: Provider,
    key: str,
    model: str,
    base_url: str | None = None,
    timeout_s: float = TIMEOUT_S,
) -> tuple[bool, str | None]:
    """Проверить ключ настоящим запросом к модели.

    Список моделей у части провайдеров публичный (Novita, SambaNova
    отвечают 200 даже на мусорный ключ), поэтому валидировать ключ
    через /models нельзя - нужен реальный chat/completions.
    Возвращает (ключ принят, текст ошибки).
    """
    if provider.google_sdk:
        ok, error = _probe_google(key, model, timeout_s)
        return ok, error

    try:
        import httpx
    except Exception as exc:  # noqa: BLE001
        return False, f"httpx недоступен: {exc}"

    root = (base_url or provider.base_url).rstrip("/")
    url = root + provider.chat_path
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    # Временные сбои сервиса (503/502/429) не должны выглядеть как
    # "ключ не принят": делаем до трёх попыток с короткой паузой.

    last_status = 0
    last_text = ""
    for attempt in range(3):
        try:
            response = httpx.post(
                url,
                headers=auth_headers(provider, key),
                json=body,
                timeout=timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 - сеть
            return False, f"нет связи с {root}: {exc}"

        if response.status_code == 200:
            return True, None

        last_status = response.status_code
        last_text = response.text[:200]
        if response.status_code not in (429, 500, 502, 503, 504):
            break
        _time.sleep(1.0 * (attempt + 1))

    return False, f"HTTP {last_status}: {last_text}"


def _probe_google(key: str, model: str, timeout_s: float) -> tuple[bool, str | None]:
    """Проверка ключа Google минимальным запросом к модели."""
    try:
        from google import genai
    except Exception as exc:  # noqa: BLE001
        return False, f"SDK google-genai недоступен: {exc}"
    try:
        client = genai.Client(
            api_key=key, http_options={"timeout": int(timeout_s * 1000)}
        )
        client.models.generate_content(model=model, contents="ping")
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def find_working_model(
    provider: Provider,
    key: str,
    models: Sequence[str],
    base_url: str | None = None,
    timeout_s: float = TIMEOUT_S,
    limit: int = 8,
) -> tuple[str | None, str | None]:
    """Найти модель, реально разрешённую этому ключу.

    У посредников каталог шире прав ключа: /models показывает 40 моделей,
    а запросы проходят только к одной-двум (иначе 403 model_not_allowed).
    Поэтому кандидаты перебираются с приоритетом дешёвых и быстрых.
    Возвращает (модель, последняя ошибка).
    """
    candidates: list[str] = []
    preferred = pick_default_model(models, provider)
    if preferred:
        candidates.append(preferred)
    for token in ("flash", "mini", "turbo", "haiku", "instant", "lite", "small"):
        for name in models:
            low = name.lower()
            if token in low and name not in candidates:
                candidates.append(name)
    for name in models:
        if name not in candidates:
            candidates.append(name)

    last_error = "нет моделей для проверки"
    for model in candidates[: max(1, limit)]:
        ok, error = probe_chat(
            provider, key, model, base_url=base_url, timeout_s=timeout_s
        )
        if ok:
            return model, None
        last_error = error or last_error
        low = str(last_error).lower()
        # Ошибка ключа, а не модели: перебирать дальше бессмысленно.
        if "401" in low or "invalid api key" in low or "failed_to_auth" in low:
            break
        # Временный сбой сервиса: пробуем эту же модель ещё раз.
        if "503" in low or "capacity" in low or "temporarily" in low:
            ok, retry_error = probe_chat(
                provider, key, model, base_url=base_url, timeout_s=timeout_s
            )
            if ok:
                return model, None
            last_error = retry_error or last_error
    return None, last_error


def pick_default_model(models: Sequence[str], provider: Provider) -> str:
    """Выбрать разумную модель из списка.

    Сначала уважаем default_model провайдера: у посредников похожие
    названия (deepseek-v4-flash и deepseek-v4.1-flash) имеют разные
    права, и угадывание по подстроке выбирает запрещённую.
    """
    available = [str(item) for item in models if item]
    if not available:
        return provider.default_model

    default = str(provider.default_model or "").strip()
    if default and default in available:
        return default

    for token in ("flash", "mini", "turbo", "haiku", "instant"):
        for name in available:
            if token in name.lower():
                return name
    return available[0]


def friendly_error(text: str) -> str:
    """Перевести ошибку провайдера в понятную фразу на русском."""
    low = (text or "").lower()
    if "unsupported_country" in low or "not available in your region" in low or "region" in low:
        return (
            "провайдер блокирует вашу страну (403) - это не ошибка ключа, "
            "нужен другой провайдер или свой шлюз"
        )
    if "401" in low or "invalid api key" in low or "unauthorized" in low or "failed_to_auth" in low:
        return "ключ не принят этим провайдером (401)"
    if "403" in low or "permission" in low:
        return "доступ запрещён (403)"
    if "404" in low:
        return "эндпоинт не найден (404): возможно, нужен другой base_url"
    if "429" in low or "quota" in low or "rate limit" in low:
        return "превышена квота или лимит запросов (429)"
    if "503" in low or "capacity_unavailable" in low or "temporarily unavailable" in low:
        return "сервис провайдера временно перегружен (503), повторите запрос"
    if "timeout" in low or "deadline" in low:
        return "истекло время ожидания ответа"
    if "getaddrinfo" in low or "connect" in low or "network" in low:
        return "нет связи с сервером провайдера"
    return (text or "неизвестная ошибка")[:200]


# ---------------------------------------------------------------------------
# Преобразование истории в формат OpenAI
# ---------------------------------------------------------------------------
def _part_kind(part: Any) -> str:
    if getattr(part, "function_call", None) is not None:
        return "function_call"
    if getattr(part, "function_response", None) is not None:
        return "function_response"
    if getattr(part, "inline_data", None) is not None:
        return "image"
    if getattr(part, "thought", False):
        return "thought"
    return "text"


def _image_data_uri(part: Any) -> str | None:
    inline = getattr(part, "inline_data", None)
    if inline is None:
        return None
    data = getattr(inline, "data", None)
    mime = str(getattr(inline, "mime_type", "image/jpeg") or "image/jpeg")
    if not data:
        return None
    import base64

    encoded = base64.b64encode(bytes(data)).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _spec_to_part(spec: Any) -> Any:
    """Описание части словарём -> types.Part (или None)."""
    if not isinstance(spec, Mapping):
        return spec
    try:
        from pcagent import llm

        return llm.part_from_spec(spec)
    except Exception:  # noqa: BLE001 - llm может быть недоступен
        return None


#: Подпись для сообщения, в котором были только изображения.
#: Провайдеры OpenAI-формата отбрасывают сообщение без текста, и модель
#: отвечает "картинка не пришла" (проверено на реальном прогоне).
IMAGE_ONLY_CAPTION = "Снимок экрана:"


def contents_to_messages(contents: Sequence[Any]) -> list[dict[str, Any]]:
    """История types.Content -> сообщения OpenAI chat/completions.

    Вызовы инструментов и их ответы связываются по имени: модели нужен
    tool_call_id, а Gemini-история хранит только имя функции.
    """
    messages: list[dict[str, Any]] = []
    open_calls: dict[str, list[str]] = {}

    for index, content in enumerate(contents or []):
        # История приходит как types.Content, но тесты и внешние
        # вызывающие могут передать описание словарём.
        if isinstance(content, Mapping):
            role = str(content.get("role") or "user")
            raw_parts = content.get("parts") or []
            parts = [_spec_to_part(item) for item in raw_parts]
            parts = [part for part in parts if part is not None]
        else:
            role = str(getattr(content, "role", "user") or "user")
            parts = getattr(content, "parts", None) or []
        if role == "model":
            role = "assistant"

        texts: list[str] = []
        images: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []

        for part in parts:
            kind = _part_kind(part)
            if kind == "text":
                value = getattr(part, "text", None)
                if value:
                    texts.append(str(value))
            elif kind == "image":
                uri = _image_data_uri(part)
                if uri:
                    images.append({"type": "image_url", "image_url": {"url": uri}})
            elif kind == "function_call":
                call = getattr(part, "function_call", None)
                name = str(getattr(call, "name", "") or "")
                if not name:
                    continue
                call_id = str(getattr(call, "id", "") or "") or f"call_{index}_{name}"
                open_calls.setdefault(name, []).append(call_id)
                args = getattr(call, "args", None) or {}
                tool_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args, ensure_ascii=False, default=str),
                        },
                    }
                )
            elif kind == "function_response":
                response = getattr(part, "function_response", None)
                name = str(getattr(response, "name", "") or "")
                payload = getattr(response, "response", None) or {}
                call_id = str(getattr(response, "id", "") or "")
                if not call_id:
                    pending = open_calls.get(name) or []
                    call_id = pending.pop(0) if pending else f"call_{index}_{name}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(payload, ensure_ascii=False, default=str),
                    }
                )

        if tool_calls:
            message: dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
            if texts:
                message["content"] = "\n".join(texts)
            messages.append(message)
            continue

        if images or texts:
            if images:
                content_parts: list[dict[str, Any]] = []
                # Сообщение только из картинок провайдеры молча отбрасывают:
                # модель отвечает, что изображение не пришло. Подпись делает
                # сообщение обычным мультимодальным и картинка доходит.
                content_parts.append(
                    {"type": "text", "text": "\n".join(texts) if texts else IMAGE_ONLY_CAPTION}
                )
                content_parts.extend(images)
                messages.append({"role": role, "content": content_parts})
            else:
                messages.append({"role": role, "content": "\n".join(texts)})

    return messages


def tools_payload(declarations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Объявления инструментов -> формат OpenAI tools."""
    tools: list[dict[str, Any]] = []
    for item in declarations or []:
        name = str(item.get("name") or "")
        if not name:
            continue
        parameters = item.get("parameters") or {"type": "object", "properties": {}}
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(item.get("description") or ""),
                    "parameters": parameters,
                },
            }
        )
    return tools


class ProviderError(RuntimeError):
    """Ошибка обращения к провайдеру."""


class HttpBrain:
    """Мозг для любого OpenAI-совместимого API.

    Реализует тот же контракт, что GoogleBrain: generate(contents,
    tools_declarations, system_instruction=...) -> ответ, который
    разбирают функции llm.extract_*.
    """

    def __init__(
        self,
        provider: Provider,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        timeout_s: float = 120.0,
        logger: Any = None,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.model = model or provider.default_model
        self.base_url = (base_url or provider.base_url).rstrip("/")
        self.timeout_s = float(timeout_s)
        self.logger = logger
        self.active_model = self.model
        self.last_model = self.model
        self.calls = 0
        self._model_fallback_done = False
        self._retries_done = 0
        self._model_cache: list[str] | None = None

    def _switch_to_allowed_model(self) -> str | None:
        """Найти разрешённую ключу модель и переключиться на неё."""
        try:
            models, error = fetch_models(
                self.provider, self.api_key, base_url=self.base_url, timeout_s=TIMEOUT_S
            )
        except Exception:  # noqa: BLE001 - подбор не должен ломать запрос
            return None
        if error or not models:
            return None
        self._model_cache = list(models)
        model, _err = find_working_model(
            self.provider, self.api_key, models, base_url=self.base_url, timeout_s=TIMEOUT_S
        )
        if not model or model == self.model:
            return None
        self._log("model_fallback", {"from": self.model, "to": model})
        self.model = model
        self.active_model = model
        self.last_model = model
        return model

    def _log(self, kind: str, payload: dict[str, Any]) -> None:
        if self.logger is not None:
            try:
                self.logger.log(kind, payload)
            except Exception:  # noqa: BLE001
                pass

    def generate(
        self,
        contents: Sequence[Any],
        tools_declarations: Sequence[Mapping[str, Any]] | None = None,
        system_instruction: str | None = None,
    ) -> Any:
        """Запрос к провайдеру. Возвращает объект формы StubResponse."""
        import httpx

        messages = contents_to_messages(contents)
        if system_instruction:
            messages.insert(0, {"role": "system", "content": str(system_instruction)})

        body: dict[str, Any] = {"model": self.model, "messages": messages}
        tools = tools_payload(tools_declarations or ())
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        url = f"{self.base_url}{self.provider.chat_path}"
        self.calls += 1
        try:
            response = httpx.post(
                url,
                headers=auth_headers(self.provider, self.api_key),
                json=body,
                timeout=self.timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 - сеть
            raise ProviderError(f"{self.provider.title}: {friendly_error(str(exc))}") from exc

        # Ключу может быть разрешена не та модель, что выбрана: у
        # посредников каталог шире прав. Признак бывает разный - 403
        # model_not_allowed, а иногда 503/400 на запрещённую модель.
        # Поэтому один раз пробуем подобрать рабочую модель.
        needs_fallback = response.status_code in (400, 403, 404, 503)
        if needs_fallback and not self._model_fallback_done:
            self._model_fallback_done = True
            working = self._switch_to_allowed_model()
            if working:
                # Посредник отвечает 503 на частые запросы подряд:
                # даём сервису паузу перед повтором.
                import time

                time.sleep(2.5)
                return self.generate(contents, tools_declarations, system_instruction)

        # Временные сбои посредника (503/502/429) лечатся повтором с
        # нарастающей паузой: сервис ограничивает частоту запросов.
        if response.status_code in (429, 502, 503, 504) and self._retries_done < 3:
            self._retries_done += 1
            delay = 2.5 * self._retries_done
            self._log(
                "provider_retry",
                {"status": response.status_code, "attempt": self._retries_done, "delay": delay},
            )
            import time

            time.sleep(delay)
            return self.generate(contents, tools_declarations, system_instruction)

        if response.status_code != 200:
            raise ProviderError(
                f"{self.provider.title}: {friendly_error(f'{response.status_code} {response.text[:300]}')}"
            )

        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"{self.provider.title}: ответ не JSON ({exc})") from exc

        self._log("provider_response", {"model": self.model, "status": 200})
        return build_response(payload)


def build_response(payload: Mapping[str, Any]) -> Any:
    """Ответ OpenAI -> объект, совместимый с разбором llm.extract_*."""
    from pcagent.stub_brain import (
        StubCandidate,
        StubContent,
        StubFunctionCall,
        StubPart,
        StubResponse,
    )

    choices = payload.get("choices") or []
    message = (choices[0] or {}).get("message") if choices else {}
    message = message or {}

    parts: list[StubPart] = []
    text = message.get("content")
    if isinstance(text, str) and text.strip():
        parts.append(StubPart(text=text))
    reasoning = message.get("reasoning_content") or message.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        parts.insert(0, StubPart(text=reasoning, thought=True))

    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        name = str(function.get("name") or "")
        if not name:
            continue
        raw_args = function.get("arguments")
        if isinstance(raw_args, Mapping):
            args = dict(raw_args)
        else:
            try:
                args = json.loads(raw_args or "{}")
            except (TypeError, ValueError):
                args = {}
            if not isinstance(args, dict):
                args = {}
        parts.append(
            StubPart(function_call=StubFunctionCall(name=name, args=args, id=call.get("id")))
        )

    content = StubContent(role="model", parts=parts)
    return StubResponse(candidates=[StubCandidate(content=content)], text=text or "")


def make_brain(
    config: Any,
    api_key: str,
    logger: Any = None,
    provider_id: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> Any:
    """Собрать мозг под ключ: Google через SDK, остальные через HTTP."""
    extra = getattr(config, "extra", None) or {}
    chosen_id = provider_id or extra.get("provider")
    provider = get_provider(chosen_id) if chosen_id else detect_provider(api_key)
    if provider is None:
        provider = PROVIDERS[0]

    if provider.google_sdk:
        # Для Google SDK имя модели нормализуем так же: "auto" -> модель
        # провайдера. Иначе SDK получит model="auto" и ответит 404.
        chosen = str(config.model or "")
        if not model_fits_provider(chosen, provider):
            config.model = provider.default_model
        from pcagent.llm import GoogleBrain

        return GoogleBrain(config, logger=logger)

    resolved = resolve_model(
        provider,
        str(model or getattr(config, "model", "") or ""),
        key=api_key,
        base_url=base_url or extra.get("base_url"),
        timeout_s=float(getattr(config, "request_timeout_s", 120) or 120),
    )
    # Запоминаем выбранную модель: иначе в статусе останется "auto".
    try:
        config.model = resolved
    except Exception:  # noqa: BLE001 - конфиг может быть неизменяемым
        pass

    return HttpBrain(
        provider,
        api_key,
        resolved,
        base_url=base_url or extra.get("base_url"),
        timeout_s=float(getattr(config, "request_timeout_s", 120) or 120),
        logger=logger,
    )