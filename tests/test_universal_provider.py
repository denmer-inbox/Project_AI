"""Клиент универсальный: любая модель, любой провайдер.

Раньше клиент был «клиентом для Google Gemini»: модель по умолчанию
gemini-2.5-flash, переменная GEMINI_API_KEY, заголовок окна с "(Gemini)".
Теперь провайдер определяется по ключу, а модель подбирается под него.
"""

from __future__ import annotations

import os

import pytest

from pcagent.config import API_KEY_ENV_NAMES, AUTO_MODEL, AppConfig
from pcagent.gui import providers


# --------------------------------------------------- имена переменных окружения
def test_generic_env_name_comes_first():
    """Общая переменная ищется раньше частных имён провайдеров."""
    assert API_KEY_ENV_NAMES[0] == "PCAGENT_API_KEY"


def test_env_names_cover_major_providers():
    names = set(API_KEY_ENV_NAMES)
    for expected in (
        "PCAGENT_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "TOGETHER_API_KEY",
    ):
        assert expected in names, f"нет переменной {expected}"


def test_generic_env_wins_over_provider_specific(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("PCAGENT_API_KEY", "generic-key")
    config = AppConfig()
    assert config.resolve_api_key() == "generic-key"


def test_provider_env_used_when_generic_absent(monkeypatch):
    monkeypatch.delenv("PCAGENT_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    config = AppConfig()
    assert config.resolve_api_key() == "openai-key"


# --------------------------------------------------- выбор модели
def test_default_model_is_auto():
    """Никакой модели по умолчанию: она подбирается под провайдера."""
    assert AppConfig().model == AUTO_MODEL
    assert AUTO_MODEL == "auto"


def test_default_fallback_models_are_empty():
    """Имена моделей несовместимы между провайдерами."""
    assert AppConfig().fallback_models == []


@pytest.mark.parametrize(
    "provider_id,model,expected",
    [
        ("google", "gemini-2.5-flash", True),
        ("google", "gpt-4o", False),
        ("google", "auto", False),
        ("cvc", "deepseek-v4-flash", True),
        ("cvc", "gemini-2.5-flash", False),
        ("openai", "gpt-4o-mini", True),
        ("openai", "gemini-2.5-flash", False),
        ("anthropic", "claude-3-5-sonnet-latest", True),
        ("groq", "llama-3.3-70b-versatile", True),
    ],
)
def test_model_fits_provider(provider_id, model, expected):
    provider = providers.get_provider(provider_id)
    assert providers.model_fits_provider(model, provider) is expected


@pytest.mark.parametrize("provider_id", ["google", "cvc", "openai", "anthropic", "deepseek"])
def test_auto_resolves_to_provider_default(provider_id):
    provider = providers.get_provider(provider_id)
    # probe=False: без сети, только модель по умолчанию провайдера.
    assert providers.resolve_model(provider, "auto", probe=False) == provider.default_model


def test_explicit_model_is_kept_when_it_fits():
    provider = providers.get_provider("cvc")
    assert providers.resolve_model(provider, "gpt-5.5", probe=False) == "gpt-5.5"


def test_foreign_model_is_replaced():
    """gemini-* у посредника получает 403 - его надо заменить."""
    provider = providers.get_provider("cvc")
    resolved = providers.resolve_model(provider, "gemini-2.5-flash", probe=False)
    assert not resolved.startswith("gemini")
    assert resolved == provider.default_model


def test_auto_model_marker_matches_config():
    assert providers.AUTO_MODEL == AUTO_MODEL


# --------------------------------------------------- прочее
def test_app_title_is_provider_neutral():
    from pcagent.gui import app as gui_app

    assert gui_app.APP_TITLE == "PC Agent"
    assert "Gemini" not in gui_app.APP_TITLE
    assert "Google" not in gui_app.APP_TITLE


def test_cli_help_says_any_model():
    from pcagent.cli import build_parser

    help_text = build_parser().format_help()
    assert "любой моделью" in help_text or "любой" in help_text
    assert "модели, доступные ключу (любой провайдер)" in help_text


def test_save_key_keeps_existing_variable_name(tmp_path):
    """Если в .env уже есть GEMINI_API_KEY, не заводим вторую переменную."""
    from pcagent.gui import credentials

    target = tmp_path / ".env"
    target.write_text("OTHER=1\nGEMINI_API_KEY=старый\n", encoding="utf-8")
    credentials.save_key("AIza" + "z" * 35, path=target)
    data = credentials.read_env_file(target)
    assert data["GEMINI_API_KEY"] == "AIza" + "z" * 35
    assert "PCAGENT_API_KEY" not in data
    assert data["OTHER"] == "1"


def test_save_key_uses_generic_name_for_new_file(tmp_path):
    from pcagent.gui import credentials

    target = tmp_path / ".env"
    credentials.save_key("AIza" + "y" * 35, path=target)
    data = credentials.read_env_file(target)
    assert data["PCAGENT_API_KEY"] == "AIza" + "y" * 35


def test_credentials_primary_name_is_generic():
    from pcagent.gui import credentials

    assert credentials.PRIMARY_ENV_NAME == "PCAGENT_API_KEY"


def test_config_hint_mentions_several_providers():
    from pcagent.config import API_KEY_HINT

    for token in ("PCAGENT_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        assert token in API_KEY_HINT


def test_validation_message_is_provider_neutral():
    config = AppConfig(api_key="")
    issues = config.validate()
    assert issues
    joined = " ".join(issues)
    assert "PCAGENT_API_KEY" in joined
    assert "Google Gemini" not in joined
