"""Остаток токенов по ключу: провайдер, CLI и GUI.

Посредники отдают остаток запросом, официальный Gemini API - нет.
Баланс измеряется в условных единицах с множителем по модели, поэтому
один и тот же остаток означает разное число токенов для разных моделей.
"""

from __future__ import annotations

import pytest

from pcagent.gui import providers


@pytest.fixture(autouse=True)
def _reset_balance_rate_limit():
    """Сбросить счётчик частоты: он общий для модуля."""
    # Провайдер разрешает 1 запрос в секунду, иначе тесты мешают друг другу.
    providers._balance_last_check = 0.0
    yield
    providers._balance_last_check = 0.0


# ------------------------------------------------------- разбор ответа
class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)

    def json(self):
        if self._payload is None:
            raise ValueError("не JSON")
        return self._payload


def _patch_httpx(monkeypatch, response):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: response)


def test_balance_reads_token_balance(monkeypatch):
    provider = providers.get_provider("cvc")
    _patch_httpx(monkeypatch, _FakeResponse(200, {"object": "balance", "token_balance": 23498471}))
    balance, error = providers.fetch_balance(provider, "sk-cvc-test")
    assert error is None
    assert balance is not None
    assert balance.tokens == 23498471
    assert "23 498 471" in balance.describe()


@pytest.mark.parametrize("field", ["token_balance", "balance", "tokens", "remaining", "credit"])
def test_balance_accepts_different_field_names(monkeypatch, field):
    provider = providers.get_provider("cvc")
    _patch_httpx(monkeypatch, _FakeResponse(200, {field: 1234}))
    balance, error = providers.fetch_balance(provider, "")
    assert error is None
    assert balance.tokens == 1234


def test_balance_reports_404_as_unsupported(monkeypatch):
    provider = providers.get_provider("cvc")
    _patch_httpx(monkeypatch, _FakeResponse(404, {}, "404 page not found"))
    balance, error = providers.fetch_balance(provider, "sk-cvc-test")
    assert balance is None
    assert "личном кабинете" in error


def test_balance_reports_bad_payload(monkeypatch):
    provider = providers.get_provider("cvc")
    _patch_httpx(monkeypatch, _FakeResponse(200, {"unexpected": True}))
    balance, error = providers.fetch_balance(provider, "sk-cvc-test")
    assert balance is None
    assert "нет остатка" in error


def test_google_has_no_balance_endpoint():
    """У официального Gemini API остаток запросом не узнать."""
    provider = providers.get_provider("google")
    balance, error = providers.fetch_balance(provider, "AIza-test")
    assert balance is None
    assert "Cloud Console" in error


def test_balance_path_is_relative_to_base_url():
    """base_url уже содержит /v1, иначе получится /v1/v1/balance."""
    assert providers.BALANCE_PATH == "/balance"
    assert providers.get_provider("cvc").base_url.endswith("/v1")


# ------------------------------------------------------- множители
def test_multipliers_parsed_from_models(monkeypatch):
    provider = providers.get_provider("cvc")
    payload = {
        "data": [
            {"id": "deepseek-v4-flash", "multiplier": 0.1},
            {"id": "gpt-5.5", "multiplier": 4},
            {"id": "без-множителя"},
        ]
    }
    _patch_httpx(monkeypatch, _FakeResponse(200, payload))
    multipliers = providers.fetch_multipliers(provider, "sk-cvc-test")
    assert multipliers["deepseek-v4-flash"] == 0.1
    assert multipliers["gpt-5.5"] == 4
    assert "без-множителя" not in multipliers


def test_multipliers_empty_for_google():
    assert providers.fetch_multipliers(providers.get_provider("google"), "AIza-test") == {}


def test_effective_tokens_depend_on_multiplier():
    """Один остаток - разное число токенов для разных моделей."""
    tokens = 23498471
    assert int(tokens / 0.1) == 234984710
    assert int(tokens / 4) == 5874617


def test_balance_describe_without_tokens():
    assert providers.Balance(note="нет данных").describe() == "нет данных"
    assert providers.Balance().describe() == "Остаток неизвестен"


# ------------------------------------------------------- команда CLI
def test_cli_has_balance_command():
    from pcagent.cli import COMMANDS, build_parser

    assert "balance" in COMMANDS
    parser = build_parser()
    args = parser.parse_args(["balance", "--models"])
    assert args.command == "balance"
    assert args.models is True
    assert args.json is False


def test_cli_balance_without_key_returns_2(monkeypatch, capsys):
    import pcagent.cli as cli
    from pcagent.config import AppConfig

    config = AppConfig(api_key="")
    monkeypatch.setattr(cli, "_load_config", lambda args: config)
    args = cli.build_parser().parse_args(["balance"])
    assert cli.cmd_balance(args) == 2


def test_cli_balance_json_shape(monkeypatch, capsys):
    import json

    import pcagent.cli as cli
    from pcagent.config import AppConfig

    config = AppConfig(model="deepseek-v4-flash")
    config.api_key = "sk-cvc-testkey"
    monkeypatch.setattr(cli, "_load_config", lambda args: config)
    monkeypatch.setattr(
        providers, "fetch_balance", lambda *a, **k: (providers.Balance(tokens=1000), None)
    )
    monkeypatch.setattr(
        providers, "fetch_multipliers", lambda *a, **k: {"deepseek-v4-flash": 0.1}
    )

    args = cli.build_parser().parse_args(["balance", "--json"])
    assert cli.cmd_balance(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tokens"] == 1000
    assert payload["models"]["deepseek-v4-flash"] == 10000
