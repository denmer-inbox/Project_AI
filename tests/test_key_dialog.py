# -*- coding: utf-8 -*-
"""Тесты вставки ключа и адреса API из буфера + защита Google-ключа."""
from __future__ import annotations

import pytest

from pcagent.gui import credentials as cred

GOOGLE = "AIzaSyD-ExampleKey1234567890abcdefghijklm"
URL = "https://api.example.com/v1"


@pytest.mark.parametrize(
    "text",
    [
        GOOGLE,
        f"GEMINI_API_KEY={GOOGLE}",
        f"GOOGLE_API_KEY={GOOGLE}",
        f"export GEMINI_API_KEY={GOOGLE}",
        f'{{"api_key": "{GOOGLE}"}}',
        f'"{GOOGLE}"',
        f"  {GOOGLE}  \n",
        f"Ваш ключ: {GOOGLE} (не передавайте)",
        f"{GOOGLE},",
    ],
)
def test_extract_google_key_from_clipboard(text):
    assert cred.extract_key(text) == GOOGLE


@pytest.mark.parametrize("text", ["", "   ", "просто текст", "AIza", "sk-"])
def test_extract_key_ignores_non_keys(text):
    assert cred.extract_key(text) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        (URL, URL),
        (URL + "/", URL),
        (f"BASE_URL={URL}", URL),
        (f'{{"base_url": "{URL}"}}', URL),
        (f"адрес: {URL}, спасибо", URL),
        ('"https://generativelanguage.googleapis.com/v1beta"',
         "https://generativelanguage.googleapis.com/v1beta"),
    ],
)
def test_extract_url_from_clipboard(text, expected):
    assert cred.extract_url(text) == expected


@pytest.mark.parametrize("text", ["", "просто текст", GOOGLE, "ftp://example.com"])
def test_extract_url_ignores_non_urls(text):
    assert cred.extract_url(text) is None


def test_google_key_is_recognised():
    assert cred.looks_like_google_key(GOOGLE)
    assert not cred.looks_like_google_key("sk-cvc-abc")


def test_mask_hides_key():
    masked = cred.mask_key(GOOGLE)
    assert GOOGLE not in masked
    assert masked.startswith("AIzaSy") and masked.endswith("jklm")
