"""Проверка формата экспорта перед сессией обмена (Соглашение 1.1, п.3).

Запуск:
    python check_export_version.py [путь_к_репозиторию]

Печатает строку "<EXPORT_VERSION> <EXPORT_TYPE> <commit>" и возвращает 0,
если версия равна ожидаемой (3), иначе 1.
"""
import subprocess
import sys
from pathlib import Path

EXPECTED_VERSION = 3
EXPECTED_TYPE = "opencode-provider-profiles"

repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo))

try:
    import opencode_provider_manager as m
except Exception as exc:  # pragma: no cover
    print("ERROR: cannot import opencode_provider_manager from", repo, "->", exc)
    raise SystemExit(2)

version = getattr(m, "EXPORT_VERSION", None)
etype = getattr(m, "EXPORT_TYPE", None)

try:
    commit = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
        text=True, stderr=subprocess.DEVNULL,
    ).strip()
except Exception:
    commit = "no-git"

print("%s %s %s" % (version, etype, commit))

ok = version == EXPECTED_VERSION and etype == EXPECTED_TYPE
if not ok:
    print(
        "FAIL: ожидалось %s %s, получено %s %s — экспорт не начинать (Соглашение 1.1 п.3)"
        % (EXPECTED_VERSION, EXPECTED_TYPE, version, etype),
        file=sys.stderr,
    )
raise SystemExit(0 if ok else 1)
