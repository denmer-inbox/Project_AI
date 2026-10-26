"""Общие фикстуры тестов. Все импорты проекта - из корня репозитория."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Тесты никогда не должны ждать подтверждений или использовать сеть по умолчанию.
os.environ.setdefault("PCAGENT_DRY_RUN", "0")
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)
# Не читать .env разработчика: иначе тесты "без ключа" ломаются, когда
# у пользователя ключ уже настроен.
os.environ["PCAGENT_NO_ENV"] = "1"


@pytest.fixture()
def config():
    from pcagent.config import AppConfig

    return AppConfig(stub_mode=True, confirm_mode="never", save_screenshots=False, max_steps=3)


@pytest.fixture()
def bus():
    from pcagent.events import EventBus

    return EventBus()
