"""Предупреждение о посреднике и проверка TLS провайдера.

Посредник (шлюз) проксирует запросы через себя: он видит текст задач,
снимки экрана и ключ API. Клиент обязан сказать об этом до начала работы,
а не молчать. Официальный API предупреждения не получает.
"""

from __future__ import annotations

import pytest

from pcagent.gui import providers


# --------------------------------------------------- официальный или посредник
def test_google_is_official():
    assert providers.is_official(providers.get_provider("google")) is True


@pytest.mark.parametrize("provider_id", ["openai", "anthropic", "deepseek", "groq", "mistral", "together"])
def test_vendor_apis_are_official(provider_id):
    assert providers.is_official(providers.get_provider(provider_id)) is True


@pytest.mark.parametrize("provider_id", ["cvc", "openrouter"])
def test_gateways_are_not_official(provider_id):
    assert providers.is_official(providers.get_provider(provider_id)) is False


def test_is_official_handles_none():
    assert providers.is_official(None) is False


# --------------------------------------------------- текст предупреждения
def test_notice_for_gateway_mentions_data():
    notice = providers.privacy_notice(providers.get_provider("cvc"))
    assert notice
    assert "посредник" in notice.lower()
    # Должны быть названы все три вида данных, которые уходят наружу.
    assert "снимки" in notice.lower()
    assert "ключ" in notice.lower()
    assert "задач" in notice.lower()


def test_notice_is_empty_for_official():
    assert providers.privacy_notice(providers.get_provider("google")) == ""
    assert providers.privacy_notice(None) == ""


def test_notice_names_the_provider():
    notice = providers.privacy_notice(providers.get_provider("cvc"))
    assert "AI Keys For You" in notice


def test_notice_suggests_official_key():
    notice = providers.privacy_notice(providers.get_provider("cvc"))
    assert "AIza" in notice or "Google" in notice


# --------------------------------------------------- проверка сертификата
def test_check_tls_without_base_url():
    """У официального Google адрес не задан - проверять нечего."""
    ok, detail = providers.check_tls(providers.get_provider("google"))
    assert ok is None
    assert "нечего" in detail or "не задан" in detail


def test_check_tls_reports_certificate_problem(monkeypatch):
    """Просроченный сертификат должен вернуть False, а не исключение."""
    import socket
    import ssl

    provider = providers.Provider(
        id="broken",
        title="Broken",
        base_url="https://broken.example/v1",
        default_model="x",
    )

    class _FailingContext:
        def __init__(self, *args, **kwargs):
            pass

        def wrap_socket(self, sock, server_hostname=None):
            raise ssl.SSLCertVerificationError("certificate has expired")

    class _Sock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: _FailingContext())
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: _Sock())

    ok, detail = providers.check_tls(provider)
    assert ok is False
    assert "не прошёл проверку" in detail


def test_check_tls_without_network_is_not_a_failure(monkeypatch):
    """Если сети нет, это не проблема сертификата."""
    import socket

    provider = providers.Provider(
        id="offline",
        title="Offline",
        base_url="https://offline.example/v1",
        default_model="x",
    )

    def boom(*args, **kwargs):
        raise OSError("сеть недоступна")

    monkeypatch.setattr(socket, "create_connection", boom)
    ok, detail = providers.check_tls(provider)
    assert ok is None
    assert "не удалось" in detail


# --------------------------------------------------- doctor
def test_doctor_reports_gateway_and_tls(monkeypatch, capsys):
    import pcagent.cli as cli
    from pcagent.config import AppConfig

    config = AppConfig(api_key="sk-cvc-testkey", model="deepseek-v4-flash")
    monkeypatch.setattr(cli, "_load_config", lambda args: config)
    monkeypatch.setattr(
        providers,
        "check_tls",
        lambda provider, **kwargs: (False, "сертификат истёк"),
    )

    args = cli.build_parser().parse_args(["doctor"])
    cli.cmd_doctor(args)
    out = capsys.readouterr().out
    assert "ПОСРЕДНИК" in out
    assert "истёк" in out


def test_doctor_says_official_for_google(monkeypatch, capsys):
    import pcagent.cli as cli
    from pcagent.config import AppConfig

    config = AppConfig(api_key="AIza" + "x" * 35, model="gemini-2.5-flash")
    monkeypatch.setattr(cli, "_load_config", lambda args: config)
    monkeypatch.setattr(providers, "check_tls", lambda provider, **kwargs: (None, "адрес не задан"))

    args = cli.build_parser().parse_args(["doctor"])
    cli.cmd_doctor(args)
    out = capsys.readouterr().out
    assert "официальный API" in out
    assert "ПОСРЕДНИК" not in out
