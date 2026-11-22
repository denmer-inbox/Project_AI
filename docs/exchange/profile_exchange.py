#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка полноты переноса профилей OpenCode между двумя ПК.

Зачем: «ЭКСПОРТ ВСЕХ ПРОФИЛЕЙ…» пишет JSON, «ИМПОРТ ПРОФИЛЕЙ…» добавляет их
в список приложения. Но приложение показывает только то, что реально попало
в opencode.json после «ПРИМЕНИТЬ К КОНФИГУ». Этот скрипт сравнивает файл
экспорта с локальным конфигом и говорит: все ли профили и модели доехали.

Команды
-------
    python tools/profile_exchange.py manifest FILE
        Сводка файла экспорта: количество, ID, SHA-256, модель по умолчанию.
        Этот JSON удобно вставить в сообщение удалённой стороне.

    python tools/profile_exchange.py check FILE [--config PATH]
        Сравнить файл экспорта с локальным opencode.json.
        Код возврата 0 — всё загружено, 1 — есть расхождения, 2 — ошибка чтения.

    python tools/profile_exchange.py compare FILE_A FILE_B
        Сравнить два файла экспорта (что пропало/добавилось/изменилось).

Ключи API никогда не печатаются: только «совпадает/отличается/нет».
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

try:  # чтобы русский отчёт одинаково читался в консоли и при захвате вывода
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

EXPORT_TYPE = "opencode-provider-profiles"
EXPORT_TYPE_SINGLE = "opencode-provider-profile"
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# v3 хранит коэффициенты рядом с конфигом, а не в providers.<id>._coefficient
COEFFICIENTS_FILE_NAME = "provider_coefficients.json"


def default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "opencode" / "opencode.json"


class ExchangeError(Exception):
    """Файл нельзя прочитать или он не похож на экспорт профилей."""


# --------------------------------------------------------------------------
# Чтение JSON / JSONC
# --------------------------------------------------------------------------

def strip_jsonc(text: str) -> str:
    """Убирает // и /* */ комментарии и висячие запятые (как в конфиге OpenCode)."""
    out, i, n, in_str, esc = [], 0, len(text), False, False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i < n - 1 and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def read_json(path: Path):
    if not path.exists():
        raise ExchangeError("файл не найден: %s" % path)
    if path.suffix.lower() == ".zip":
        raise ExchangeError(
            "это ZIP-архив, а не JSON: %s\n"
            "Приложение принимает только .json. Распакуйте архив и передайте "
            "вложенный *.json (если архив с паролем — пароль должен передать "
            "его владелец)." % path)
    raw = path.read_bytes()
    if not raw.strip():
        raise ExchangeError("файл пуст: %s" % path)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExchangeError(
            "файл не в UTF-8 (%s). Пересохраните его в UTF-8 без BOM." % exc)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.loads(strip_jsonc(text))
        except json.JSONDecodeError as exc:
            raise ExchangeError(
                "внутри не JSON (%s). Похоже, файл обрезан или это не экспорт." % exc)


# --------------------------------------------------------------------------
# Разбор формата экспорта и конфига
# --------------------------------------------------------------------------

def _as_list(value) -> list:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [str(key) for key in value]
    return []


def normalize_url(url) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    return url.rstrip("/")


def export_entries(data) -> tuple:
    """(entries, default_model, source_type, version) из любого формата файла."""
    if isinstance(data, list):
        return data, "", "", None
    if not isinstance(data, dict):
        raise ExchangeError("в файле не объект JSON и не список профилей")
    default_model = str(data.get("default_model") or "").strip()
    source_type = str(data.get("type") or "")
    try:
        version = int(data.get("version")) if data.get("version") is not None else None
    except (TypeError, ValueError):
        version = None
    if isinstance(data.get("profiles"), list):
        return data["profiles"], default_model, source_type, version
    if data.get("id"):
        return [data], default_model, source_type, version
    raise ExchangeError('в файле нет списка "profiles" — это не экспорт профилей')


def profile_view(entry) -> dict:
    """Запись экспорта -> нормализованный профиль (или ошибка валидации)."""
    if not isinstance(entry, dict):
        return {"valid": False, "id": "", "error": "запись не является объектом JSON"}
    pid = str(entry.get("id") or "").strip()
    if not ID_RE.match(pid):
        return {
            "valid": False,
            "id": pid,
            "error": "недопустимый ID (только латиница, цифры, «.», «_», «-»)",
        }
    models = _as_list(entry.get("models"))
    known = _as_list(entry.get("known_models")) or list(models)
    return {
        "valid": True,
        "id": pid,
        "display_name": str(entry.get("display_name") or pid),
        "base_url": normalize_url(entry.get("base_url")),
        "api_key": str(entry.get("api_key") or ""),
        "package": str(entry.get("package") or ""),
        "coefficient": str(entry.get("coefficient") or "").strip(),
        "models": models,
        "known_models": known,
        "error": "",
    }


def export_view(data) -> dict:
    entries, default_model, source_type, version = export_entries(data)
    profiles, invalid, duplicates, seen = [], [], [], set()
    for index, entry in enumerate(entries, 1):
        view = profile_view(entry)
        if not view["valid"]:
            invalid.append({"index": index, "id": view["id"], "error": view["error"]})
            continue
        if view["id"] in seen and view["id"] not in duplicates:
            duplicates.append(view["id"])
        seen.add(view["id"])
        profiles.append(view)
    return {
        "version": version,
        "type": source_type,
        "default_model": default_model,
        "profiles": profiles,
        "invalid": invalid,
        "duplicates": duplicates,
    }


def _config_model_ref(config: dict) -> str:
    model = config.get("model")
    if isinstance(model, str):
        return model.strip()
    if isinstance(model, dict):
        pid = str(model.get("providerID") or "").strip()
        mid = str(model.get("model") or model.get("modelID") or "").strip()
        if pid and mid:
            return "%s/%s" % (pid, mid)
    return ""


def load_coefficients(config_path: Path) -> dict:
    """Коэффициенты v3 лежат рядом с конфигом: provider_coefficients.json."""
    path = Path(config_path).parent / COEFFICIENTS_FILE_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v).strip() for k, v in data.items() if str(v or "").strip()}


def config_view(config: dict, coefficients: dict | None = None) -> dict:
    coefficients = coefficients or {}
    providers = config.get("providers")
    providers = providers if isinstance(providers, dict) else {}
    result = {}
    for pid, proxy in providers.items():
        proxy = proxy if isinstance(proxy, dict) else {}
        settings = proxy.get("settings") if isinstance(proxy.get("settings"), dict) else {}
        models_spec = proxy.get("models") if isinstance(proxy.get("models"), dict) else {}
        selected, hidden = [], []
        for mid, spec in models_spec.items():
            disabled = isinstance(spec, dict) and bool(spec.get("disabled"))
            (hidden if disabled else selected).append(str(mid))
        coefficient = str(coefficients.get(str(pid))
                          or proxy.get("_coefficient") or "").strip()
        result[str(pid)] = {
            "id": str(pid),
            "display_name": str(proxy.get("name") or pid),
            "base_url": normalize_url(settings.get("baseURL")),
            "api_key": str(settings.get("apiKey") or ""),
            "package": str(proxy.get("package") or ""),
            "coefficient": coefficient,
            "models": selected,
            "hidden_models": hidden,
        }
    return {"providers": result, "default_model": _config_model_ref(config)}


# --------------------------------------------------------------------------
# Сравнение
# --------------------------------------------------------------------------

def _key_state(file_key: str, config_key: str) -> str:
    if not file_key and not config_key:
        return "нет в обоих"
    if not config_key:
        return "нет в конфиге"
    if not file_key:
        return "нет в файле"
    return "совпадает" if file_key == config_key else "отличается"


def _diff_fields(file_profile: dict, config_profile: dict) -> list:
    diffs = []
    for field, label in (("display_name", "название"), ("base_url", "URL"),
                         ("package", "package"), ("coefficient", "коэффициент")):
        if file_profile[field] != config_profile[field]:
            diffs.append({
                "field": field,
                "label": label,
                "file": file_profile[field],
                "config": config_profile[field],
            })
    state = _key_state(file_profile["api_key"], config_profile["api_key"])
    if state != "совпадает":
        diffs.append({"field": "api_key", "label": "API key", "file": state,
                      "config": state})
    return diffs


def compare(export: dict, config: dict) -> dict:
    file_profiles = {p["id"]: p for p in export["profiles"]}
    cfg_profiles = config["providers"]
    missing = [pid for pid in file_profiles if pid not in cfg_profiles]
    extra = [pid for pid in cfg_profiles if pid not in file_profiles]
    same, model_diffs, field_diffs, hidden_warnings = [], [], [], []

    for pid, file_profile in file_profiles.items():
        cfg = cfg_profiles.get(pid)
        if cfg is None:
            continue
        file_models = list(file_profile["models"])
        cfg_models = list(cfg["models"])
        not_selected = [mid for mid in file_models if mid not in cfg_models]
        extra_selected = [mid for mid in cfg_models if mid not in file_models]
        hidden = [mid for mid in file_models if mid in cfg["hidden_models"]]
        if not_selected or extra_selected:
            model_diffs.append({
                "id": pid,
                "missing": not_selected,
                "extra": extra_selected,
            })
        elif hidden:
            hidden_warnings.append({"id": pid, "hidden": hidden})
        diffs = _diff_fields(file_profile, cfg)
        if diffs:
            field_diffs.append({"id": pid, "diffs": diffs})
        if not_selected or extra_selected or diffs:
            continue
        same.append(pid)

    file_default = export["default_model"]
    cfg_default = config["default_model"]
    if file_default and cfg_default:
        default_ok = file_default == cfg_default
    elif file_default:
        default_ok = False
    else:
        default_ok = True
    default_diff = {
        "file": file_default or "(не задана)",
        "config": cfg_default or "(не задана)",
        "ok": default_ok,
    }

    ok = not missing and not model_diffs and not export["invalid"] and default_ok
    return {
        "file_count": len(file_profiles),
        "config_count": len(cfg_profiles),
        "same": same,
        "missing": missing,
        "extra": extra,
        "model_diffs": model_diffs,
        "field_diffs": field_diffs,
        "hidden": hidden_warnings,
        "invalid": export["invalid"],
        "duplicates": export["duplicates"],
        "default_model": default_diff,
        "ok": ok,
    }


# --------------------------------------------------------------------------
# Отчёты
# --------------------------------------------------------------------------

def manifest(path: Path) -> dict:
    raw = path.read_bytes()
    data = read_json(path)
    view = export_view(data)
    warnings = []
    if view["version"] is not None and view["version"] < 2:
        warnings.append("формат версии %s — вероятно, экспорт сделан старой "
                        "сборкой и содержит не все профили" % view["version"])
    if view["type"] == EXPORT_TYPE_SINGLE:
        warnings.append("это файл ОДНОГО профиля, а не «все профили»")
    if view["duplicates"]:
        warnings.append("повторяются ID: %s" % ", ".join(view["duplicates"]))
    return {
        "file": str(path.resolve()),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "type": view["type"],
        "version": view["version"],
        "profiles_count": len(view["profiles"]),
        "profiles": [p["id"] for p in view["profiles"]],
        "models_count": {p["id"]: len(p["models"]) for p in view["profiles"]},
        "default_model": view["default_model"],
        "invalid": view["invalid"],
        "duplicates": view["duplicates"],
        "warnings": warnings,
    }


def _human(export_path: Path, config_path: Path, report: dict) -> str:
    lines = ["Файл:   %s" % export_path, "Конфиг: %s" % config_path, ""]
    for pid in report["same"]:
        lines.append("[OK]      %s" % pid)
    for pid in report["missing"]:
        lines.append("[НЕТ]     %s — профиль отсутствует в конфиге" % pid)
    for item in report["model_diffs"]:
        parts = []
        if item["missing"]:
            parts.append("в конфиге нет моделей: %s" % ", ".join(item["missing"]))
        if item["extra"]:
            parts.append("в конфиге лишние выбранные: %s" % ", ".join(item["extra"]))
        lines.append("[МОДЕЛИ]  %s — %s" % (item["id"], "; ".join(parts)))
    for item in report["field_diffs"]:
        parts = ["%s: файл=%r, конфиг=%r" % (d["label"], d["file"], d["config"])
                 for d in item["diffs"]]
        lines.append("[ПОЛЯ]    %s — %s" % (item["id"], "; ".join(parts)))
    for item in report["hidden"]:
        lines.append("[СКРЫТО]  %s — модели помечены disabled: %s"
                     % (item["id"], ", ".join(item["hidden"])))
    for item in report["invalid"]:
        lines.append("[БРАК]    запись №%d %s — %s"
                     % (item["index"], item["id"] or "(без ID)", item["error"]))
    if report["duplicates"]:
        lines.append("[ДУБЛЬ]   повторяются ID: %s" % ", ".join(report["duplicates"]))
    if report["extra"]:
        lines.append("[ЛОКАЛЬНО] в конфиге есть, но нет в файле: %s"
                     % ", ".join(report["extra"]))
    dm = report["default_model"]
    lines.append("Модель по умолчанию: файл=%s, конфиг=%s%s"
                 % (dm["file"], dm["config"], "" if dm["ok"] else "  <-- РАСХОЖДЕНИЕ"))
    loaded = report["file_count"] - len(report["missing"])
    lines.append("")
    lines.append("ИТОГ: загружено %d из %d профилей." % (loaded, report["file_count"]))
    if report["ok"]:
        lines.append("ВСЁ ЗАГРУЖЕНО.")
    else:
        reasons = []
        if report["missing"]:
            reasons.append("нет профилей: %s" % ", ".join(report["missing"]))
        if report["model_diffs"]:
            reasons.append("расходятся модели у: %s"
                           % ", ".join(i["id"] for i in report["model_diffs"]))
        if report["invalid"]:
            reasons.append("в файле %d некорректных записей" % len(report["invalid"]))
        if not dm["ok"]:
            reasons.append("модель по умолчанию не совпала")
        lines.append("НЕ ВСЁ ЗАГРУЖЕНО: " + "; ".join(reasons))
    return "\n".join(lines)


def _pairs(path_a: Path, path_b: Path) -> dict:
    a = export_view(read_json(path_a))
    b = export_view(read_json(path_b))
    ids_a = [p["id"] for p in a["profiles"]]
    ids_b = [p["id"] for p in b["profiles"]]
    set_a, set_b = set(ids_a), set(ids_b)
    changed = {}
    by_id_b = {p["id"]: p for p in b["profiles"]}
    for profile in a["profiles"]:
        other = by_id_b.get(profile["id"])
        if other is None:
            continue
        fields = [f for f in ("display_name", "base_url", "package", "coefficient")
                  if profile[f] != other[f]]
        if profile["models"] != other["models"]:
            fields.append("models")
        if profile["api_key"] != other["api_key"]:
            fields.append("api_key")
        if fields:
            changed[profile["id"]] = fields
    return {
        "a": str(path_a),
        "b": str(path_b),
        "count_a": len(ids_a),
        "count_b": len(ids_b),
        "only_in_a": [pid for pid in ids_a if pid not in set_b],
        "only_in_b": [pid for pid in ids_b if pid not in set_a],
        "changed": changed,
        "same": [pid for pid in ids_a if pid in set_b and pid not in changed],
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Проверка полноты переноса профилей OpenCode между ПК.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_manifest = sub.add_parser("manifest", help="сводка файла экспорта")
    p_manifest.add_argument("file", type=Path)

    p_check = sub.add_parser("check", help="сравнить файл экспорта с opencode.json")
    p_check.add_argument("file", type=Path)
    p_check.add_argument("--config", type=Path, default=None,
                         help="путь к opencode.json (по умолчанию ~/.config/opencode)")
    p_check.add_argument("--json", action="store_true", dest="as_json",
                         help="машинный отчёт вместо текста")

    p_cmp = sub.add_parser("compare", help="сравнить два файла экспорта")
    p_cmp.add_argument("file_a", type=Path)
    p_cmp.add_argument("file_b", type=Path)
    p_cmp.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "manifest":
            print(json.dumps(manifest(args.file), ensure_ascii=False, indent=2))
            return 0

        if args.command == "compare":
            result = _pairs(args.file_a, args.file_b)
            if args.as_json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print("A: %s  (%d профилей)" % (result["a"], result["count_a"]))
                print("B: %s  (%d профилей)" % (result["b"], result["count_b"]))
                print("Только в A: %s" % (", ".join(result["only_in_a"]) or "—"))
                print("Только в B: %s" % (", ".join(result["only_in_b"]) or "—"))
                for pid, fields in result["changed"].items():
                    print("Изменился %s: %s" % (pid, ", ".join(fields)))
                print("Совпадают: %s" % (", ".join(result["same"]) or "—"))
            return 0 if not result["only_in_a"] and not result["only_in_b"] else 1

        config_path = args.config or default_config_path()
        export = export_view(read_json(args.file))
        config = config_view(read_json(config_path), load_coefficients(config_path))
        report = compare(export, config)
        report["file"] = str(args.file)
        report["config"] = str(config_path)
        report["manifest"] = manifest(args.file)
        if args.as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(_human(args.file, config_path, report))
        return 0 if report["ok"] else 1
    except ExchangeError as exc:
        sys.stderr.write("ОШИБКА: %s\n" % exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
