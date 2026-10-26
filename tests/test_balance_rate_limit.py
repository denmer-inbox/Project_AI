"""Ограничение частоты запросов остатка.

Провайдер разрешает 1 запрос в секунду и 60 в минуту. Клиент обязан это
учитывать: иначе повторный запрос получает HTTP 429, и пользователь видит
ошибку вместо остатка.
"""

from __future__ import annotations

import pytest

from pcagent.gui import providers


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    providers._balance_last_check = 0.0
    yield
    providers._balance_last_check = 0.0


class _Response:
    def __init__(self, status_code: int = 200, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {"token_balance": 42}
        self.text = text

    def json(self):
        return self._payload


def test_second_request_is_blocked_locally(monkeypatch):
    """Второй запрос подряд не уходит на сервер."""
    import httpx

    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _Response()

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = providers.get_provider("cvc")

    first, error = providers.fetch_balance(provider, "sk-cvc-test")
    assert error is None
    assert first.tokens == 42

    requests_before = len(calls)
    second, second_error = providers.fetch_balance(provider, "sk-cvc-test")
    assert second is None
    assert "1 запрос" in second_error or "секунд" in second_error
    assert len(calls) == requests_before, "второй запрос не должен идти в сеть"


def test_server_429_is_retried_once(monkeypatch):
    """429 от сервера: одна повторная попытка после паузы."""
    import httpx

    import pcagent.gui.providers as mod

    responses = [_Response(429, text="rate limit"), _Response(200)]
    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return responses.pop(0) if responses else _Response(200)

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(mod._time, "sleep", lambda seconds: None)

    balance, error = mod.fetch_balance(providers.get_provider("cvc"), "sk-cvc-test")
    assert error is None
    assert balance.tokens == 42
    assert len(calls) == 2, "должно быть ровно две попытки"


def test_interval_value_matches_server_limit():
    """Сервер разрешает 1 запрос в секунду: интервал обязан быть больше."""
    assert providers.BALANCE_MIN_INTERVAL_S > 1.0


def test_rate_limit_check_is_cheap():
    providers._balance_last_check = 0.0
    assert providers._balance_recently_checked() is False

    providers._mark_balance_checked()
    assert providers._balance_recently_checked() is True