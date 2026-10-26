#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenCode Provider Manager
=========================
Графический менеджер внешних профилей-провайдеров для OpenCode V2.

Возможности
-----------
* читает ~/.config/opencode/opencode.json при запуске и показывает все профили;
* добавление / редактирование / удаление профилей-провайдеров;
* ввод URL провайдера и API-ключа с проверкой доступных моделей (GET /models);
* выбор моделей, которые будут видны в OpenCode;
* запись изменений с автоматическим снимком предыдущей версии (откат);
* отдельное окно истории версий и откат в один клик (Ctrl+Z);
* экспорт и импорт профиля в JSON;
* стиль интерфейса — тёмный «космический» HUD (палитра из index.html шутера).
"""

from __future__ import annotations

import copy
import json
import os
import queue
import re
import shutil
import socket
import ssl
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception as exc:  # pragma: no cover
    sys.stderr.write("tkinter недоступен: %s\n" % exc)
    raise SystemExit(1)

APP_TITLE = "OpenCode — менеджер провайдеров"
PACKAGES = [
    "@ai-sdk/openai-compatible",
    "@ai-sdk/openai",
    "@ai-sdk/anthropic",
    "@ai-sdk/google",
]


# ==========================================================================
# Тема оформления: палитра из «Звёздный рубеж» (index.html)
# ==========================================================================

class T:
    bg = "#010206"
    bg_panel = "#04101a"
    bg_panel_hi = "#071a26"
    bg_input = "#020a12"
    line = "#0e2b3a"
    cyan = "#6df4ff"
    cyan_soft = "#a6f0ff"
    cyan_dim = "#2b6a7a"
    amber = "#ffc16b"
    red = "#ff5568"
    green = "#6dffb0"
    ink = "#d9fbff"
    ink_dim = "#93c2d4"
    mono = ("Consolas", 10)
    mono_small = ("Consolas", 9)
    mono_title = ("Consolas", 12, "bold")
    mono_big = ("Consolas", 18, "bold")
    ui = ("Segoe UI", 10)


def apply_tk_styles(root) -> None:
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure(".", background=T.bg, foreground=T.ink, fieldbackground=T.bg_input,
                 font=T.ui, bordercolor=T.line)
    st.configure("TFrame", background=T.bg)
    st.configure("TLabel", background=T.bg, foreground=T.ink, font=T.ui)
    st.configure("TButton", background=T.bg_panel_hi, foreground=T.cyan_soft,
                 bordercolor=T.cyan_dim, focuscolor=T.cyan, font=T.mono_small, padding=(10, 6))
    st.map("TButton", background=[("active", "#0b2c3d"), ("disabled", T.bg_panel)],
           foreground=[("disabled", T.cyan_dim)])
    st.configure("Accent.TButton", background="#0b3547", foreground=T.cyan,
                 bordercolor=T.cyan, font=T.mono_small, padding=(10, 6))
    st.map("Accent.TButton", background=[("active", "#0f4a61")])
    st.configure("Danger.TButton", background="#2a0d13", foreground=T.red,
                 bordercolor="#7a2230", font=T.mono_small, padding=(10, 6))
    st.map("Danger.TButton", background=[("active", "#3d121b")])
    st.configure("TEntry", fieldbackground=T.bg_input, foreground=T.cyan_soft,
                 insertcolor=T.cyan, bordercolor=T.cyan_dim, lightcolor=T.line,
                 darkcolor=T.bg_input, padding=6, font=T.mono)
    st.map("TEntry", bordercolor=[("focus", T.cyan)])
    st.configure("TCombobox", fieldbackground=T.bg_input, background=T.bg_panel_hi,
                 foreground=T.cyan_soft, arrowcolor=T.cyan, bordercolor=T.cyan_dim, padding=4)
    st.map("TCombobox", fieldbackground=[("readonly", T.bg_input)],
           foreground=[("readonly", T.cyan_soft)])
    st.configure("Treeview", background=T.bg_panel, fieldbackground=T.bg_panel,
                 foreground=T.ink, rowheight=24, font=T.mono_small, bordercolor=T.line)
    st.map("Treeview", background=[("selected", "#0b3547")], foreground=[("selected", T.cyan)])
    st.configure("Treeview.Heading", background=T.bg_panel_hi, foreground=T.ink_dim,
                 font=T.mono_small, relief="flat")
    st.map("Treeview.Heading", background=[("active", "#0b2c3d")],
           foreground=[("active", T.cyan)])
    st.configure("TScrollbar", background=T.bg_panel_hi, troughcolor=T.bg,
                 bordercolor=T.bg, arrowcolor=T.cyan_dim)
    st.map("TScrollbar", background=[("active", T.cyan_dim)])


class ScanStrip(tk.Canvas):
    """Декоративная линия-разделитель в стиле HUD."""

    def __init__(self, master, height=2, color="#6df4ff", **kw):
        super().__init__(master, height=height, bg=T.bg, highlightthickness=0, **kw)
        self._color = color
        self._h = height
        self.bind("<Configure>", lambda e: self._draw(e.width))

    def _draw(self, w):
        self.delete("all")
        h = self._h
        self.create_line(0, h // 2, w, h // 2, fill=T.line)
        self.create_line(0, h // 2, max(0, w // 3), h // 2, fill=self._color)


# ==========================================================================
# TLS: подбор доверенной цепочки (исправляет просроченные корни)
# ==========================================================================

_CTX_CACHE: dict = {}


def _ca_bundles():
    out = []
    env = os.environ.get("SSL_CERT_FILE")
    if env:
        out.append(Path(env))
    try:
        import certifi  # type: ignore

        out.append(Path(certifi.where()))
    except Exception:
        pass
    site = Path(sys.prefix) / "Lib" / "site-packages"
    out += [
        site / "pip" / "_vendor" / "certifi" / "cacert.pem",
        Path(r"C:\Program Files\Git\mingw64\etc\ssl\certs\ca-bundle.crt"),
        Path(r"C:\Program Files\Git\usr\ssl\certs\ca-bundle.crt"),
        Path(r"C:\Program Files\Common Files\SSL\cert.pem"),
    ]
    res = []
    for p in out:
        try:
            if p and p.is_file() and p.stat().st_size > 4096:
                if str(p).lower() not in [str(x).lower() for x in res]:
                    res.append(p)
        except OSError:
            continue
    return res


def _probe(ctx, host):
    try:
        with socket.create_connection((host, 443), timeout=8) as raw:
            with ctx.wrap_socket(raw, server_hostname=host):
                return True
    except ssl.SSLCertVerificationError:
        return False
    except Exception:
        return True


def _ssl_context(host):
    host = (host or "").lower()
    if host in _CTX_CACHE:
        return _CTX_CACHE[host]
    ctx = ssl.create_default_context()
    ok = _probe(ctx, host)
    if not ok:
        for bundle in _ca_bundles():
            try:
                cand = ssl.create_default_context(cafile=str(bundle))
            except Exception:
                continue
            if _probe(cand, host):
                ctx, ok = cand, True
                break
    _CTX_CACHE[host] = ctx
    return ctx

# ==========================================================================
# Конфиг: чтение / запись / история версий
# ==========================================================================

def default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "opencode" / "opencode.json"


def strip_jsonc(text: str) -> str:
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


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = json.loads(strip_jsonc(raw))
    if not isinstance(data, dict):
        raise ValueError("Корень конфига должен быть объектом JSON")
    return data


HISTORY_LIMIT = 50


def history_dir(path: Path) -> Path:
    return path.parent / "backups"


def list_backups(path: Path) -> list:
    items = []
    cands = []
    if path.exists():
        cands += [p for p in path.parent.glob(path.name + ".bak-*") if p.is_file()]
    hdir = history_dir(path)
    if hdir.is_dir():
        cands += [p for p in hdir.glob(path.name + ".*.bak") if p.is_file()]
    for p in cands:
        entry = {"path": p, "name": p.name, "time": None, "valid": False,
                 "providers": [], "model": "", "_mtime": 0}
        try:
            entry["time"] = datetime.fromtimestamp(p.stat().st_mtime)
            entry["_mtime"] = p.stat().st_mtime
        except OSError:
            pass
        try:
            data = load_config(p)
            entry["valid"] = True
            entry["providers"] = list((data.get("providers") or {}).keys())
            entry["model"] = default_model_ref(data)
        except Exception:
            pass
        items.append(entry)
    items.sort(key=lambda e: e["_mtime"], reverse=True)
    return items


def make_snapshot(path: Path):
    if not path.exists():
        return None
    hdir = history_dir(path)
    hdir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S") + "-%03d" % (now.microsecond // 1000)
    dest = hdir / ("%s.%s.bak" % (path.name, stamp))
    shutil.copy2(path, dest)
    return dest


def prune_history(path: Path, keep: int = HISTORY_LIMIT) -> None:
    targets = []
    hdir = history_dir(path)
    if hdir.is_dir():
        targets.append((hdir, "*.bak"))
    targets.append((path.parent, path.name + ".bak-*"))
    for base, pattern in targets:
        files = sorted((p for p in base.glob(pattern) if p.is_file()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            try:
                old.unlink()
            except OSError:
                pass


def save_config(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = make_snapshot(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    prune_history(path)
    return backup


def restore_backup(path: Path, backup: Path):
    data = load_config(backup)
    if not isinstance(data, dict):
        raise ValueError("Снимок не содержит объект JSON")
    safety = make_snapshot(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(backup.read_text(encoding="utf-8-sig"), encoding="utf-8")
    os.replace(tmp, path)
    prune_history(path)
    return safety


# ==========================================================================
# Модели: сеть
# ==========================================================================

def normalize_base_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return url
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "https://" + url
    return url.rstrip("/")


def http_json(url: str, api_key: str = "", timeout: float = 15.0):
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "opencode-provider-manager/2.0")
    if api_key:
        req.add_header("Authorization", "Bearer " + api_key)
    host = urllib.parse.urlsplit(url).hostname or ""
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context(host)) as resp:
            body = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        status = exc.code
    try:
        return status, json.loads(body)
    except Exception:
        return status, body




def coefficient_estimate(units, coefficient) -> dict:
    """Пересчёт единиц баланса в реальные токены по коэффициенту пакета.

    Проверено на api.aikeysforyou.com: 917 токенов списали 92 единицы при
    коэффициенте 0.1, т.е. расход_единиц ≈ токены × коэффициент.
    Значит запас токенов ≈ balance_units / коэффициент.
    """
    try:
        units = float(units)
        coef = float(coefficient)
    except Exception:
        return {}
    if not coef or coef <= 0:
        return {}
    tokens = units / coef
    return {
        "tokens_by_coef": int(tokens),
        "text": fmt_tokens(int(tokens)),
    }


def fetch_balance(base_url: str, api_key: str) -> dict:
    """Запрос баланса провайдера.

    Поддерживаются известные схемы OpenAI-совместимых шлюзов:
      * {base}/balance            -> {"object":"balance","token_balance":N}
      * {base}/credits            -> OpenAI-подобный (total_granted/total_used)
      * {base}/usage              -> {"total_usage": …} (в центах)
    Возвращает dict: raw, tokens, usd, text.
    """
    base = normalize_base_url(base_url)
    if not base:
        raise ValueError("Не задан URL провайдера")
    hosts = [base]
    # часто baseURL = .../v1, а баланс лежит на корне
    if re.search(r"/v\d+[a-z]?$", base, re.I):
        hosts.append(base[: base.rfind("/")])
    tried = []
    for root in hosts:
        for path in ("/balance", "/credits", "/usage"):
            url = root + path
            try:
                status, data = http_json(url, api_key)
            except Exception as exc:
                tried.append("%s: %s" % (url, exc))
                continue
            if status == 404:
                continue
            if status in (401, 403):
                raise PermissionError("Сервер отклонил ключ (HTTP %s)" % status)
            if status >= 400:
                tried.append("%s: HTTP %s" % (url, status))
                continue
            if not isinstance(data, dict):
                continue
            parsed = parse_balance(data)
            if parsed:
                parsed["url"] = url
                parsed["raw"] = data
                return parsed
    raise RuntimeError("Эндпоинт баланса не найден. Проверено: %d адрес(ов). "
                       "Последние ошибки: %s" % (len(tried), "; ".join(tried[-3:]) or "—"))


def parse_balance(data: dict) -> dict:
    """Извлекает из ответа баланс в токенах и/или деньгах."""
    out = {"tokens": None, "usd": None, "text": ""}

    def as_int(v):
        try:
            if isinstance(v, bool) or v is None:
                return None
            return int(float(v))
        except Exception:
            return None

    def as_float(v):
        try:
            if isinstance(v, bool) or v is None:
                return None
            return float(v)
        except Exception:
            return None

    # 1) простая схема с токенами
    for k in ("token_balance", "balance_tokens", "tokens_left", "tokens", "credit_tokens"):
        v = as_int(data.get(k))
        if v is not None:
            out["tokens"] = v
            break
    # 2) деньги
    for k in ("balance", "remaining", "credits", "credit_balance", "amount", "usd"):
        v = as_float(data.get(k))
        if v is not None:
            out["usd"] = v
            break
    # 3) OpenAI-подобные credits/usage
    if out["usd"] is None:
        granted = as_float(data.get("total_granted"))
        used = as_float(data.get("total_used")) or as_float(data.get("total_usage"))
        if granted is not None:
            used = used or 0.0
            out["usd"] = (granted - used) / 100.0 if granted > 1000 else granted - used
    if out["tokens"] is None:
        total = as_int(data.get("total_available")) or as_int(data.get("remaining_tokens"))
        if total is not None:
            out["tokens"] = total

    parts = []
    if out["usd"] is not None:
        parts.append("%.2f" % out["usd"])
    if out["tokens"] is not None:
        parts.append(fmt_tokens(out["tokens"]))
    out["text"] = " • ".join(parts) if parts else ""
    return out


def fmt_tokens(n) -> str:
    """1 502 210 163 -> 1.50 млрд (читаемо)."""
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n >= 1_000_000_000:
        return "%.2f млрд токенов" % (n / 1_000_000_000)
    if n >= 1_000_000:
        return "%.2f млн токенов" % (n / 1_000_000)
    if n >= 1_000:
        return "%.1f тыс. токенов" % (n / 1_000)
    return "%d токенов" % n


def discover_models(base_url: str, api_key: str) -> list:
    base = normalize_base_url(base_url)
    if not base:
        raise ValueError("Не задан URL провайдера")
    urls = []
    if re.search(r"/v\d+[a-z]?$", base, re.I):
        urls.append(base + "/models")
    else:
        urls += [base + "/v1/models", base + "/models"]
    last = None
    for url in urls:
        try:
            status, data = http_json(url, api_key)
        except Exception as exc:
            last = exc
            continue
        if status == 404:
            continue
        if status in (401, 403):
            raise PermissionError("Сервер отклонил ключ (HTTP %s)" % status)
        if status >= 400:
            raise RuntimeError("HTTP %s при запросе %s" % (status, url))
        items = data.get("data") or data.get("models") or [] if isinstance(data, dict) else data
        models = []
        for item in items or []:
            if isinstance(item, str):
                item = {"id": item}
            if not isinstance(item, dict):
                continue
            mid = item.get("id") or item.get("name")
            if not mid:
                continue
            models.append({
                "id": str(mid),
                "display": item.get("display_name") or item.get("name") or str(mid),
                "context": item.get("context_window") or item.get("contextWindow")
                or item.get("context_length") or item.get("max_context_tokens"),
                "output": item.get("max_output_tokens") or item.get("max_tokens"),
                "tools": item.get("supports_tools"),
                "vision": item.get("supports_vision"),
            })
        if models:
            return sorted(models, key=lambda m: m["display"].lower())
        last = RuntimeError("Сервер вернул пустой список моделей")
    if isinstance(last, Exception):
        raise last
    raise RuntimeError("Не удалось получить список моделей")

# ==========================================================================
# Профили <-> конфиг
# ==========================================================================

def profiles_from_config(config: dict) -> list:
    providers = config.get("providers")
    result = []
    if not isinstance(providers, dict):
        return result
    for pid, proxy in providers.items():
        proxy = proxy if isinstance(proxy, dict) else {}
        settings = proxy.get("settings") if isinstance(proxy.get("settings"), dict) else {}
        models_spec = proxy.get("models") if isinstance(proxy.get("models"), dict) else {}
        selected, known = [], []
        for mid, spec in models_spec.items():
            known.append(mid)
            if isinstance(spec, dict) and spec.get("disabled"):
                continue
            selected.append(mid)
        for mid in known:
            if mid not in selected:
                continue
        result.append({
            "id": pid,
            "display_name": proxy.get("name") or pid,
            "coefficient": str(proxy.get("_coefficient") or ""),
            "base_url": settings.get("baseURL") or "",
            "api_key": settings.get("apiKey") or "",
            "package": proxy.get("package") or PACKAGES[0],
            "models": selected,
            "known_models": known,
            "extra_settings": {k: v for k, v in settings.items()
                               if k not in ("baseURL", "apiKey")},
            "_raw": copy.deepcopy(proxy),
        })
    return result


def default_model_ref(config: dict) -> str:
    model = config.get("model")
    if isinstance(model, str):
        return model
    if isinstance(model, dict):
        pid = model.get("providerID") or ""
        mid = model.get("model") or model.get("modelID") or ""
        if pid and mid:
            return "%s/%s" % (pid, mid)
    return ""


def parse_model_ref(ref: str):
    ref = (ref or "").strip()
    if "/" not in ref:
        return "", ""
    pid, mid = ref.split("/", 1)
    return pid.strip(), mid.strip()


def model_spec(model: dict, existing=None) -> dict:
    spec = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    spec.pop("disabled", None)
    spec.setdefault("name", model.get("display") or model["id"])
    limit = spec.get("limit") if isinstance(spec.get("limit"), dict) else {}
    if model.get("context"):
        limit["context"] = int(model["context"])
    if model.get("output"):
        limit["output"] = int(model["output"])
    if limit:
        spec["limit"] = limit
    caps = spec.get("capabilities") if isinstance(spec.get("capabilities"), dict) else {}
    if model.get("tools") is not None:
        caps["tools"] = bool(model["tools"])
    caps.setdefault("tools", True)
    if model.get("vision"):
        caps["input"] = ["text", "image"]
    caps.setdefault("input", ["text"])
    caps.setdefault("output", ["text"])
    spec["capabilities"] = caps
    return spec


def _strip_coef(obj):
    """Убирает служебные поля (коэффициент) из объекта, уходящего в конфиг."""
    if isinstance(obj, dict):
        return {k: _strip_coef(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_coef(v) for v in obj]
    return obj


def read_coefficient(config: dict, pid: str) -> str:
    """Коэффициент храним в самом конфиге (providers.<id>._coefficient) — служебное поле."""
    providers = config.get("providers") or {}
    proxy = providers.get(pid) or {}
    val = proxy.get("_coefficient")
    if val in (None, ""):
        return ""
    return str(val)


def build_provider(profile: dict) -> dict:
    settings = {}
    base = normalize_base_url(profile.get("base_url", ""))
    if base:
        settings["baseURL"] = base
    if profile.get("api_key"):
        settings["apiKey"] = profile["api_key"]
    for k, v in (profile.get("extra_settings") or {}).items():
        settings[k] = v
    proxy = copy.deepcopy(profile.get("_raw") or {})
    coef = str(profile.get("coefficient") or "").strip()
    if coef:
        proxy["_coefficient"] = coef
    else:
        proxy.pop("_coefficient", None)
    proxy["name"] = profile.get("display_name") or profile.get("id")
    proxy["package"] = profile.get("package") or PACKAGES[0]
    if settings:
        proxy["settings"] = settings
    else:
        proxy.pop("settings", None)
    old_models = proxy.get("models") if isinstance(proxy.get("models"), dict) else {}
    models = {}
    for mid in profile.get("models") or []:
        models[mid] = model_spec({"id": mid}, old_models.get(mid))
    for mid, spec in old_models.items():
        if mid in models:
            continue
        hidden = copy.deepcopy(spec) if isinstance(spec, dict) else {}
        hidden["disabled"] = True
        models[mid] = hidden
    if models:
        proxy["models"] = models
    else:
        proxy.pop("models", None)
    return proxy


def apply_profiles(config: dict, profiles: list) -> dict:
    new = copy.deepcopy(config)
    if not isinstance(new.get("providers"), dict):
        new["providers"] = {}
    new["providers"] = {p["id"]: build_provider(p) for p in profiles}
    ref = default_model_ref(new)
    pid = parse_model_ref(ref)[0]
    if ref and pid not in new["providers"]:
        new.pop("model", None)
    return new


# ==========================================================================
# Диалог профиля
# ==========================================================================

class ProfileDialog(tk.Toplevel):
    """Добавление / редактирование провайдера."""

    def __init__(self, app, profile):
        super().__init__(app.root)
        self.app = app
        self.is_new = profile is None
        self._original_id = (profile or {}).get("id", "")
        self.result = None
        self._results = queue.Queue()
        self.models = []
        self.model_vars = {}
        self.known_models = list((profile or {}).get("known_models", []))
        self._raw = (profile or {}).get("_raw")

        self.title("НОВЫЙ ПРОФИЛЬ" if self.is_new else "ПРОФИЛЬ " + str(profile["id"]).upper())
        self.geometry("860x720")
        self.minsize(760, 470)   # меньше нельзя: строкам ввода и кнопкам нужно место
        self.configure(bg=T.bg)
        self.transient(app.root)
        self.grab_set()

        self.var_id = tk.StringVar(value=(profile or {}).get("id", ""))
        self.var_name = tk.StringVar(value=(profile or {}).get("display_name", ""))
        self.var_url = tk.StringVar(value=(profile or {}).get("base_url", ""))
        self.var_key = tk.StringVar(value=(profile or {}).get("api_key", ""))
        self.var_pkg = tk.StringVar(value=(profile or {}).get("package", PACKAGES[0]))
        self.var_set_default = tk.BooleanVar(value=False)
        self.var_coef = tk.StringVar(value=str((profile or {}).get("coefficient", "") or ""))
        self.var_filter = tk.StringVar()
        self.var_filter.trace_add("write", lambda *a: self._render_models())

        self._balance_value = (profile or {}).get("_balance") or None
        self.var_coef.trace_add("write", lambda *a: self._update_estimate())
        self._build()
        if self._balance_value:
            try:
                self.lbl_balance.configure(text=self._balance_value.get("text") or "—", fg=T.green)
                self.lbl_balance_src.configure(
                    text=(self._balance_value.get("url") or "") + "  •  из последнего запроса")
            except Exception:
                pass
        try:
            app.clipboard.bind_tree(self)
        except Exception:
            pass
        self.bind("<Escape>", lambda e: self._cancel())
        if not self.is_new and self.known_models:
            for mid in self.known_models:
                self.models.append({"id": mid, "display": mid})
            self._render_models()

    # --- UI -------------------------------------------------------------
    def _field(self, parent, row, label, var, show=None):
        tk.Label(parent, text=label, bg=T.bg, fg=T.cyan_soft, font=T.mono_small,
                 width=15, anchor="w").grid(row=row, column=0, sticky="w", padx=(4, 8), pady=4)
        ent = ttk.Entry(parent, textvariable=var, font=T.mono)
        if show:
            ent.configure(show=show)
        ent.grid(row=row, column=1, sticky="ew", padx=6, pady=4)
        return ent

    def _build(self):
        head = tk.Frame(self, bg=T.bg)
        head.pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(head, text="ПРОФИЛЬ ПРОВАЙДЕРА", bg=T.bg, fg=T.cyan,
                 font=T.mono_title).pack(anchor="w")
        ScanStrip(self, color=T.cyan).pack(fill="x", padx=16, pady=(4, 8))

        form = tk.Frame(self, bg=T.bg)
        form.pack(fill="x", padx=16)
        self.e_id = self._field(form, 0, "ID ПРОВАЙДЕРА", self.var_id)
        self._field(form, 1, "НАЗВАНИЕ", self.var_name)
        self._field(form, 2, "URL ПРОВАЙДЕРА", self.var_url)
        self.e_key = self._field(form, 3, "API KEY", self.var_key, show="•")
        ttk.Button(form, text="ПОКАЗАТЬ", command=self._toggle_key).grid(row=3, column=2, padx=6)
        tk.Label(form, text="ТРАНСПОРТ", bg=T.bg, fg=T.cyan_soft, font=T.mono_small,
                 width=15, anchor="w").grid(row=4, column=0, sticky="w", padx=(4, 8), pady=4)
        ttk.Combobox(form, values=PACKAGES, textvariable=self.var_pkg, state="readonly",
                     font=T.mono, width=34).grid(row=4, column=1, sticky="w", padx=6, pady=4)
        tk.Label(form, text="КОЭФФИЦИЕНТ", bg=T.bg, fg=T.cyan_soft, font=T.mono_small,
                 width=15, anchor="w").grid(row=5, column=0, sticky="w", padx=(4, 8), pady=4)
        coef_row = tk.Frame(form, bg=T.bg)
        coef_row.grid(row=5, column=1, sticky="w", padx=6, pady=4)
        ttk.Entry(coef_row, textvariable=self.var_coef, font=T.mono,
                  width=10).pack(side="left")
        tk.Label(coef_row, text="напр. 0.1 — множитель тарифа (лимит ÷ коэффициент = запас токенов)",
                 bg=T.bg, fg=T.ink_dim, font=T.mono_small).pack(side="left", padx=8)
        form.columnconfigure(1, weight=1)

        row = tk.Frame(self, bg=T.bg)
        row.pack(fill="x", padx=16, pady=(10, 4))
        self.btn_check = ttk.Button(row, text="ПОЛУЧИТЬ СПИСОК МОДЕЛЕЙ",
                                    style="Accent.TButton", command=self._check_key)
        self.btn_check.pack(side="left", padx=(4, 6), pady=4)
        self.btn_balance = ttk.Button(row, text="ЗАПРОСИТЬ БАЛАНС",
                                      command=self._check_balance)
        self.btn_balance.pack(side="left", padx=(0, 10), pady=4)
        self.lbl_status = tk.Label(row, text="ВВЕДИТЕ URL И КЛЮЧ, ЗАТЕМ ЗАПРОСИТЕ МОДЕЛИ",
                                   bg=T.bg, fg=T.cyan_soft, font=T.mono_small)
        self.lbl_status.pack(side="left", padx=4)

        bal_row = tk.Frame(self, bg=T.bg)
        bal_row.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(bal_row, text="БАЛАНС", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(side="left", padx=(6, 10))
        self.lbl_balance = tk.Label(bal_row, text="—", bg=T.bg, fg=T.amber,
                                    font=T.mono_big if hasattr(T, "mono_big") else T.mono_title)
        self.lbl_balance.pack(side="left", padx=4)
        self.lbl_balance_src = tk.Label(bal_row, text="", bg=T.bg, fg=T.cyan_dim,
                                        font=T.mono_small)
        self.lbl_balance_src.pack(side="left", padx=10)

        self.lbl_balance_est = tk.Label(self, text="", bg=T.bg, fg=T.cyan_soft,
                                        font=T.mono_small, anchor="w")
        self.lbl_balance_est.pack(fill="x", padx=18, pady=(0, 2))

        ScanStrip(self, color=T.amber).pack(fill="x", padx=16, pady=(6, 6))

        mid = tk.Frame(self, bg=T.bg)
        mid.pack(side="bottom", fill="both", expand=True, padx=16)
        # высота списка = остаток после всех фиксированных строк
        mid.pack_propagate(False)
        mhead = tk.Frame(mid, bg=T.bg)
        mhead.pack(fill="x")
        tk.Label(mhead, text="ДОСТУПНЫЕ МОДЕЛИ", bg=T.bg, fg=T.cyan,
                 font=T.mono_title).pack(side="left", padx=2)
        ttk.Button(mhead, text="☑ ВСЕ", width=8, style="Accent.TButton",
                   command=lambda: self._set_all(True)).pack(side="right", padx=3)
        ttk.Button(mhead, text="☐ НИЧЕГО", width=10, style="Accent.TButton",
                   command=lambda: self._set_all(False)).pack(side="right", padx=3)
        self.lbl_selected = tk.Label(mhead, text="ОТМЕЧЕНО: 0 / 0", bg=T.bg, fg=T.amber,
                                     font=T.mono_small)
        self.lbl_selected.pack(side="right", padx=10)

        khint = tk.Frame(mid, bg=T.bg)
        khint.pack(fill="x", pady=(2, 0))
        tk.Label(khint,
                 text="SHIFT+КЛИК — ИНВЕРСИЯ   •   CTRL+КЛИК — ВКЛ/ВЫКЛ ВСЁ",
                 bg=T.bg, fg=T.cyan_soft, font=T.mono_small).pack(anchor="w", padx=2)

        srow = tk.Frame(mid, bg=T.bg)
        srow.pack(fill="x", pady=(6, 4))
        tk.Label(srow, text="ФИЛЬТР", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(side="left", padx=(2, 8))
        ttk.Entry(srow, textvariable=self.var_filter, font=T.mono).pack(
            side="left", fill="x", expand=True, padx=(0, 4))

        box = tk.Frame(mid, bg=T.bg, highlightthickness=1, highlightbackground=T.line)
        box.pack(side="bottom", fill="both", expand=True, pady=(0, 6))
        self.canvas = tk.Canvas(box, bg=T.bg_panel, highlightthickness=0)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=T.bg_panel)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self.inner_id, width=e.width))
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

        # ---- нижний блок: ВСЕГДА виден, не участвует в сжатии ----
        bottom = tk.Frame(self, bg=T.bg)
        bottom.pack(side="bottom", fill="x", padx=16, pady=(4, 14))
        tk.Checkbutton(bottom, text="МОДЕЛЬ ПО УМОЛЧАНИЮ", variable=self.var_set_default,
                       bg=T.bg, fg=T.ink, selectcolor=T.bg_input, activebackground=T.bg,
                       activeforeground=T.cyan, font=T.mono_small, bd=0).pack(side="left", padx=4)
        ttk.Button(bottom, text="ОТМЕНА", command=self._cancel).pack(side="right", padx=4)
        ttk.Button(bottom, text="СОХРАНИТЬ", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=4)

    def _bind_wheel(self, _=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _=None):
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

    def _on_wheel(self, event):
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def _toggle_key(self):
        showing = self.e_key.cget("show") == ""
        self.e_key.configure(show="•" if showing else "")

    def _set_all(self, value):
        """Проставить/снять все галочки (учитывая фильтр)."""
        for mid, var in self.model_vars.items():
            if self._visible(mid):
                var.set(value)
        self._update_counter()

    def toggle_all(self, flip=False, want=None):
        """flip=True — инверсия видимых; иначе включить/выключить все."""
        visible = [mid for mid in self.model_vars if self._visible(mid)]
        if not visible:
            return
        if flip:
            for mid in visible:
                self.model_vars[mid].set(not self.model_vars[mid].get())
        else:
            if want is None:
                want = not all(self.model_vars[mid].get() for mid in visible)
            for mid in visible:
                self.model_vars[mid].set(want)
        self._update_counter()

    def _count_selected(self):
        return sum(1 for v in self.model_vars.values() if v.get())

    def _update_counter(self):
        try:
            self.lbl_selected.configure(
                text="ОТМЕЧЕНО: %d / %d" % (self._count_selected(), len(self.model_vars)))
        except Exception:
            pass

    def _visible(self, mid):
        q = (self.var_filter.get() or "").strip().lower()
        return not q or q in mid.lower() or q in self._display_for(mid).lower()

    def _display_for(self, mid):
        for m in self.models:
            if m["id"] == mid:
                return m.get("display") or mid
        return mid

    def _render_models(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self._update_counter()
        if not self.models:
            tk.Label(self.inner, text="МОДЕЛЕЙ ПОКА НЕТ — ПРОВЕРЬТЕ URL/КЛЮЧ",
                     bg=T.bg_panel, fg=T.ink_dim,
                     font=T.mono_small).pack(anchor="w", padx=10, pady=10)
            return
        shown = 0
        for m in self.models:
            mid = m["id"]
            if mid not in self.model_vars:
                var = tk.BooleanVar(value=mid in (self.known_models or []))
                var.trace_add("write", lambda *a: self._update_counter())
                self.model_vars[mid] = var
            if not self._visible(mid):
                continue
            shown += 1
            text = self._display_for(mid)
            if text != mid:
                text = "%s   (%s)" % (text, mid)
            cb = SmartCheck(self.inner, self, self.model_vars[mid], text)
            cb.var = self.model_vars[mid]
            cb.pack(anchor="w", padx=8, pady=1, fill="x")
        if shown == 0:
            tk.Label(self.inner, text="ПО ФИЛЬТРУ НИЧЕГО НЕ НАЙДЕНО",
                     bg=T.bg_panel, fg=T.ink_dim,
                     font=T.mono_small).pack(anchor="w", padx=10, pady=10)

    # --- сеть -------------------------------------------------------------
    def _check_key(self):
        base, key = self.var_url.get(), self.var_key.get()
        if not base.strip():
            messagebox.showwarning("Проверка", "Сначала введите URL провайдера", parent=self)
            return
        self.btn_check.configure(state="disabled")
        self.lbl_status.configure(text="ПРОВЕРЯЕМ…")

        def work():
            try:
                self._results.put((discover_models(base, key), None))
            except Exception as exc:
                self._results.put((None, exc))

        threading.Thread(target=work, daemon=True).start()
        self._poll_results()

    def _poll_results(self):
        try:
            item = self._results.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_results)
            return
        if isinstance(item, tuple) and len(item) == 3 and item[0] == "balance":
            self._on_balance(item[1], item[2])
            return
        found, err = item
        self._on_checked(found, err)

    def _on_checked(self, found, err):
        self.btn_check.configure(state="normal")
        if err is not None:
            self.lbl_status.configure(text="ОШИБКА: %s" % err)
            messagebox.showerror("Проверка ключа", str(err), parent=self)
            return
        keep = {mid for mid, var in self.model_vars.items() if var.get()} or set(self.known_models or [])
        default_all = not keep
        self.models = found
        self.model_vars = {}
        for m in found:
            var = tk.BooleanVar(value=default_all or m["id"] in keep)
            var.trace_add("write", lambda *a: self._update_counter())
            self.model_vars[m["id"]] = var
        self.lbl_status.configure(text="НАЙДЕНО МОДЕЛЕЙ: %d" % len(found))
        self._render_models()
        self._update_counter()

    # --- баланс ------------------------------------------------------------
    def _check_balance(self):
        base, key = self.var_url.get(), self.var_key.get()
        if not base.strip():
            messagebox.showwarning("Баланс", "Сначала введите URL провайдера", parent=self)
            return
        self.btn_balance.configure(state="disabled")
        self.lbl_balance.configure(text="…", fg=T.ink_dim)
        self.lbl_balance_src.configure(text="запрашиваю")

        def work():
            try:
                self._results.put(("balance", fetch_balance(base, key), None))
            except Exception as exc:
                self._results.put(("balance", None, exc))

        threading.Thread(target=work, daemon=True).start()
        self._poll_results()

    def _on_balance(self, data, err):
        try:
            self.btn_balance.configure(state="normal")
        except Exception:
            pass
        if err is not None:
            self.lbl_balance.configure(text="—", fg=T.red)
            self.lbl_balance_src.configure(text=str(err)[:90])
            return
        text = data.get("text") or "—"
        self.lbl_balance.configure(text=text, fg=T.green)
        self.lbl_balance_src.configure(text=data.get("url") or "")
        self._balance_value = data
        self._update_estimate()

    def _update_estimate(self):
        """Показывает, сколько токенов осталось с учётом коэффициента пакета."""
        lbl = getattr(self, "lbl_balance_est", None)
        if lbl is None:
            return
        try:
            coef_txt = (self.var_coef.get() or "").replace(",", ".").strip()
            data = self._balance_value
            if not data or not coef_txt:
                lbl.configure(text="")
                return
            units = data.get("tokens")
            if units is None:
                lbl.configure(text="")
                return
            est = coefficient_estimate(units, coef_txt)
            if not est:
                lbl.configure(text="коэффициент должен быть > 0")
                return
            lbl.configure(
                text="≈ %s по коэффициенту %s   (единиц на ключе: %s)"
                     % (est["text"], coef_txt, format(units, ",").replace(",", " ")))
        except Exception:
            pass

    # --- сохранение -------------------------------------------------------
    def _save(self):
        pid = (self.var_id.get() or "").strip()
        if not pid:
            messagebox.showwarning("Проверка", "Укажите ID провайдера", parent=self)
            return
        if not re.match(r"^[A-Za-z0-9._-]+$", pid):
            messagebox.showwarning("Проверка",
                                   "ID может содержать только латиницу, цифры, «.», «_», «-»",
                                   parent=self)
            return
        base = normalize_base_url(self.var_url.get())
        if not base:
            messagebox.showwarning("Проверка", "Укажите URL провайдера", parent=self)
            return
        if not self.var_key.get().strip():
            if not messagebox.askyesno("API key", "Ключ не заполнен. Сохранить без ключа?",
                                       parent=self):
                return
        others = [p["id"] for p in self.app.profiles if p["id"] != self._original_id]
        if pid in others:
            messagebox.showwarning("Проверка", "Провайдер с таким ID уже существует", parent=self)
            return
        chosen = [mid for mid, var in self.model_vars.items() if var.get()]
        if not chosen and not messagebox.askyesno(
                "Модели", "Ни одна модель не отмечена — профиль будет без моделей. Продолжить?",
                parent=self):
            return
        self.result = {
            "id": pid,
            "display_name": (self.var_name.get() or pid).strip(),
            "base_url": base,
            "api_key": self.var_key.get().strip(),
            "package": self.var_pkg.get(),
            "models": chosen,
            "known_models": [m["id"] for m in self.models] or list(self.known_models),
            "set_default": bool(self.var_set_default.get()),
            "coefficient": self.var_coef.get().strip(),
            "_raw": copy.deepcopy(self._raw) if self._raw else None,
        }
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


# ==========================================================================
# Окно истории версий
# ==========================================================================

class HistoryWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("ИСТОРИЯ КОНФИГА И ОТКАТ")
        self.geometry("920x620")
        self.minsize(780, 430)
        self.configure(bg=T.bg)
        self.transient(app.root)
        self.grab_set()

        head = tk.Frame(self, bg=T.bg)
        head.pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(head, text="ИСТОРИЯ ВЕРСИЙ", bg=T.bg, fg=T.cyan,
                 font=T.mono_title).pack(side="left", padx=2)
        ttk.Button(head, text="СНИМОК СЕЙЧАС", command=self.make_now).pack(side="right", padx=4)
        ttk.Button(head, text="ОБНОВИТЬ", command=self.reload).pack(side="right", padx=4)
        ScanStrip(self, color=T.cyan).pack(fill="x", padx=16, pady=(4, 8))

        foot = tk.Frame(self, bg=T.bg)
        foot.pack(side="bottom", fill="x", padx=16, pady=(4, 14))
        tk.Label(foot, text="ОТКАТ ВОССТАНАВЛИВАЕТ ФАЙЛ ЦЕЛИКОМ", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(side="left", padx=4)
        ttk.Button(foot, text="ЗАКРЫТЬ", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(foot, text="ВОССТАНОВИТЬ ВЫБРАННОЕ", style="Accent.TButton",
                   command=self.restore_selected).pack(side="right", padx=4)

        prev = tk.Frame(self, bg=T.bg)
        prev.pack(side="bottom", fill="x", padx=16, pady=(8, 4))
        tk.Label(prev, text="СОДЕРЖИМОЕ СНИМКА", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w")
        self.preview_box = tk.Text(prev, height=7, bg=T.bg_input, fg=T.ink, relief="flat",
                                   font=T.mono_small, insertbackground=T.cyan, wrap="none",
                                   highlightthickness=1, highlightbackground=T.line)
        self.preview_box.pack(fill="both", expand=True, pady=4)

        mid = tk.Frame(self, bg=T.bg, highlightthickness=1, highlightbackground=T.line)
        mid.pack(fill="both", expand=True, padx=16)
        cols = ("time", "name", "providers", "model")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        for col, title, width in (("time", "КОГДА", 150), ("name", "ФАЙЛ", 250),
                                  ("providers", "ПРОВАЙДЕРЫ", 240), ("model", "МОДЕЛЬ", 190)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w")
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.preview())
        self.tree.bind("<Double-1>", lambda e: self.restore_selected())

        self.items = []
        try:
            self.app.clipboard.bind_tree(self)
        except Exception:
            pass
        self.reload()

    def reload(self):
        self.items = list_backups(self.app.config_path)
        self.tree.delete(*self.tree.get_children())
        for i, e in enumerate(self.items):
            when = e["time"].strftime("%d.%m.%Y %H:%M:%S") if e.get("time") else "?"
            provs = ", ".join(e.get("providers") or []) or "(нет данных)"
            self.tree.insert("", "end", iid=str(i),
                             values=(when, e["name"], provs, e.get("model") or "(не задана)"))
        if self.items:
            self.tree.selection_set("0")
            self.preview()
        else:
            self._set_preview("Снимков пока нет. Нажмите «СНИМОК СЕЙЧАС».")

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return self.items[int(sel[0])]
        except (IndexError, ValueError):
            return None

    def _set_preview(self, text):
        try:
            self.preview_box.configure(state="normal")
            self.preview_box.delete("1.0", "end")
            self.preview_box.insert("1.0", text)
        except Exception:
            pass

    def preview(self):
        entry = self._selected()
        if not entry:
            return
        try:
            raw = entry["path"].read_text(encoding="utf-8-sig", errors="replace")
        except Exception as exc:
            self._set_preview("Не удалось прочитать снимок: %s" % exc)
            return
        self._set_preview(raw[:20000])

    def make_now(self):
        snap = self.app.snapshot_now("Ручной снимок")
        self.reload()
        if snap:
            messagebox.showinfo("Снимок", "Сохранён:\n%s" % snap.name, parent=self)

    def restore_selected(self):
        entry = self._selected()
        if not entry:
            messagebox.showinfo("Откат", "Выберите снимок в списке", parent=self)
            return
        self.app.quick_restore(entry)
        self.reload()


class HistoryDialog:
    pass





class SmartCheck(tk.Checkbutton):
    """Чекбокс с модификаторами:
       Shift + клик — инвертировать ВСЕ (видимые) галочки
       Ctrl  + клик — включить все / выключить все (переключатель)
    Обычный клик работает как обычно.
    """

    def __init__(self, master, owner, variable, text, **kw):
        kw.setdefault("bg", T.bg_panel)
        kw.setdefault("fg", T.ink)
        kw.setdefault("selectcolor", T.bg_input)
        kw.setdefault("activebackground", T.bg_panel)
        kw.setdefault("activeforeground", T.cyan)
        kw.setdefault("font", T.mono_small)
        kw.setdefault("anchor", "w")
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, text=text, variable=variable, **kw)
        self._owner = owner
        self._watcher = variable
        self._old = variable.get()
        variable.trace_add("write", self._on_var)
        self.bind("<Button-1>", self._on_click, add="+")

    def _on_var(self, *_):
        self._old = self._watcher.get()

    def _on_click(self, event):
        mods = event.state
        shift = bool(mods & 0x0001)
        ctrl = bool(mods & 0x0004)
        ctrl2 = bool(mods & 0x0008)
        alt = bool(mods & 0x20000)
        if shift or ctrl or ctrl2:
            if shift:
                self._owner.toggle_all(flip=True)
            else:
                self._owner.toggle_all(flip=False, want=not self._old)
            try:
                self.selection_clear()
            except Exception:
                pass
            return "break"
        return None

# ==========================================================================
# Буфер обмена: контекстное меню и горячие клавиши для полей ввода
# ==========================================================================

class ClipboardMenu:
    """ПКМ по полю: Вырезать / Копировать / Вставить / Выделить всё."""

    def __init__(self, root):
        self.root = root
        self.menu = tk.Menu(root, tearoff=0, bg=T.bg_panel_hi, fg=T.ink,
                            activebackground="#0b3547", activeforeground=T.cyan,
                            font=T.mono_small, bd=0, relief="flat")
        self.menu.add_command(label="ВЫРЕЗАТЬ        Ctrl+X", command=self._cut)
        self.menu.add_command(label="КОПИРОВАТЬ      Ctrl+C", command=self._copy)
        self.menu.add_command(label="ВСТАВИТЬ        Ctrl+V", command=self._paste)
        self.menu.add_separator()
        self.menu.add_command(label="ВЫДЕЛИТЬ ВСЁ    Ctrl+A", command=self._select_all)
        self._target = None
        # Win+V: история буфера Windows подставляет текст так же, как обычный буфер,
        # но после выбора пункта нам нужно «догнать» вставку, поэтому следим за буфером.
        self._last_clip = ""
        self._watch_widget = None
        self._watch_after = None
        self._watch_armed = False
        # не «залипающее» меню: закрывается по клику вне его
        self.menu.bind("<FocusOut>", lambda e: self.menu.unpost())

    def _widget(self, event):
        w = event.widget
        try:
            if w.winfo_class() in ("TEntry", "Entry", "Text"):
                return w
        except Exception:
            pass
        return None

    def bind(self, widget):
        widget.bind("<Button-3>", self.popup, add="+")
        return widget

    def bind_tree(self, widget):
        self.bind(widget)
        for child in widget.winfo_children():
            self.bind_tree(child)

    def _cls(self, w):
        try:
            return w.winfo_class()
        except Exception:
            return ""

    def _copy(self):
        w = self._target
        if not w:
            return
        try:
            if self._cls(w) == "Text":
                text = w.get("sel.first", "sel.last") if w.tag_ranges("sel") else w.get("1.0", "end-1c")
            else:
                text = w.selection_get()
        except Exception:
            text = ""
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def _cut(self):
        w = self._target
        if not w:
            return
        self._copy()
        try:
            if self._cls(w) == "Text":
                if w.tag_ranges("sel"):
                    w.delete("sel.first", "sel.last")
            else:
                w.delete("sel.first", "sel.last")
        except Exception:
            pass

    def _paste(self):
        w = self._target
        if not w:
            return
        text = self._read_clip()
        if not text:
            return
        self._insert_text(w, text)

    def _select_all(self):
        w = self._target
        if not w:
            return
        try:
            if self._cls(w) == "Text":
                w.tag_add("sel", "1.0", "end-1c")
            else:
                w.selection_range(0, "end")
                w.icursor("end")
        except Exception:
            pass

    # --- слежение за буфером (Win+V) --------------------------------------
    def _read_clip(self):
        try:
            return self.root.clipboard_get()
        except Exception:
            return ""

    def watch_begin(self, widget):
        """Запомнили поле и текущий буфер — ждём, пока Win+V подменит содержимое."""
        self._watch_widget = widget
        self._last_clip = self._read_clip()
        self._watch_armed = True
        if self._watch_after is not None:
            try:
                self.root.after_cancel(self._watch_after)
            except Exception:
                pass
        self._watch_after = self.root.after(150, self._watch_tick)

    def _watch_tick(self):
        self._watch_after = None
        if not self._watch_armed:
            return
        w = self._watch_widget
        try:
            alive = w is not None and w.winfo_exists()
        except Exception:
            alive = False
        if not alive:
            self._watch_armed = False
            return
        cur = self._read_clip()
        if cur and cur != self._last_clip:
            self._watch_armed = False
            self._watch_widget = None
            self._target = w
            # ставим каретку в конец поля и вставляем новое содержимое
            try:
                w.icursor("end")
            except Exception:
                try:
                    w.mark_set("insert", "end")
                except Exception:
                    pass
            self._insert_text(w, cur)
            try:
                w.focus_force()
            except Exception:
                pass
            return
        self._watch_after = self.root.after(200, self._watch_tick)

    def _insert_text(self, w, text):
        try:
            if str(w.cget("state")) == "readonly":
                return
        except Exception:
            pass
        try:
            try:
                w.delete("sel.first", "sel.last")
            except Exception:
                pass
            w.insert("insert", text)
        except Exception:
            pass

    def popup(self, event):
        w = self._widget(event)
        if w is None:
            return "break"
        self._target = w
        self._last_clip = self._read_clip()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"


def install_global_watch(menu, root, interval=700):
    """Фоновый сторож: ловит изменения буфера Windows (в т.ч. выбор из истории Win+V)
    и вставляет выбранный текст в активное поле, если пользователь сам его не вставил."""

    state = {"last": menu._read_clip(), "skip": 0}

    def tick():
        try:
            cur = menu._read_clip()
        except Exception:
            cur = ""
        if cur and cur != state["last"]:
            state["last"] = cur
            w = None
            try:
                w = root.focus_get()
            except Exception:
                w = None
            try:
                is_field = w is not None and w.winfo_class() in ("TEntry", "Entry", "Text")
            except Exception:
                is_field = False
            if is_field and not menu._watch_armed:
                before = ""
                try:
                    before = w.get()
                except Exception:
                    pass
                if cur not in (before or ""):
                    menu._insert_text(w, cur)
                    state["skip"] = 2
        try:
            root.after(interval, tick)
        except Exception:
            pass

    root.after(interval, tick)


def install_clipboard(root):
    """Ctrl+C / Ctrl+V / Ctrl+X / Ctrl+A + Shift+Ins / Ctrl+Ins для всех полей."""
    menu = ClipboardMenu(root)

    def cur():
        try:
            return root.focus_get()
        except Exception:
            return None

    def do(action):
        def handler(_=None):
            menu._target = cur()
            action()
            return "break"
        return handler

    # 1) на каждый текущий виджет ввода — «свои» биндинги (высший приоритет)
    def bind_to(widget):
        try:
            if widget.winfo_class() in ("TEntry", "Entry", "Text"):
                for seq, fn in (
                    ("<Control-c>", do(menu._copy)), ("<Control-v>", do(menu._paste)),
                    ("<Control-x>", do(menu._cut)), ("<Control-a>", do(menu._select_all)),
                ):
                    widget.bind(seq, fn, add="+")
        except Exception:
            pass
        for child in widget.winfo_children():
            bind_to(child)

    bind_to(root)
    # 2) первая линия: классы виджетов
    for klass, seq, fn in (
        ("TEntry", "<Control-c>", do(menu._copy)),
        ("TEntry", "<Control-v>", do(menu._paste)),
        ("TEntry", "<Control-x>", do(menu._cut)),
        ("TEntry", "<Control-a>", do(menu._select_all)),
        ("Text", "<Control-c>", do(menu._copy)),
        ("Text", "<Control-v>", do(menu._paste)),
        ("Text", "<Control-x>", do(menu._cut)),
        ("Text", "<Control-a>", do(menu._select_all)),
    ):
        try:
            root.bind_class(klass, seq, fn, add="+")
        except Exception:
            pass
    # 3) резерв: любые нестандартные поля (Entry с show=, combobox и т.п.)
    for seq, fn in (
        ("<Control-c>", do(menu._copy)),
        ("<Control-v>", do(menu._paste)),
        ("<Control-x>", do(menu._cut)),
        ("<Control-a>", do(menu._select_all)),
        ("<Control-Insert>", do(menu._copy)),
        ("<Shift-Insert>", do(menu._paste)),
    ):
        try:
            root.bind_all(seq, fn, add="+")
        except Exception:
            pass
    def do_winv(_=None):
        """Win+V: системный диалог истории буфера выберет текст — мы подхватим его."""
        w = cur()
        if w is not None:
            menu.watch_begin(w)
        return None   # не глушим событие: пусть Windows откроет историю

    # Tk не знает keysym Win/Super (их перехватывает сама Windows), поэтому
    # расширенные клавиши регистрируем «тихо» и, главное, взводим слежение за буфером
    # на обычных Ctrl+V / Shift+Insert: когда Windows подменит буфер через Win+V,
    # наш сторож подхватит текст и вставит его в поле.
    for seq in ("<Control-KeyPress-v>", "<Shift-KeyPress-Insert>", "<Control-Insert>"):
        def arm(event, _seq=seq):
            w = menu._widget(event)
            if w is not None:
                menu.watch_begin(w)
            return None
        try:
            root.bind_all(seq, arm, add="+")
        except Exception:
            pass
    try:
        install_global_watch(menu, root)
    except Exception:
        pass
    return menu


# ==========================================================================
# Главное окно
# ==========================================================================

class App:
    def __init__(self):
        self.root_ready = True
        self.config_path = default_config_path()
        self.config = {}
        self.profiles = []
        self.selected = None
        self._base_signature = ""
        self._history = []
        self._balance_results = queue.Queue()
        self._lang = "ru"
        self._build_root()
        self.load()

    # --- окна -------------------------------------------------------------
    def _build_root(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1160x780")
        self.root.minsize(960, 640)
        self.root.configure(bg=T.bg)
        apply_tk_styles(self.root)
        self.clipboard = install_clipboard(self.root)
        self._build()
        try:
            self.clipboard.bind_tree(self.root)
        except Exception:
            pass
        self.root.bind("<Control-z>", lambda e: self.undo_last())
        self.root.bind("<Control-Z>", lambda e: self.undo_last())

    # --- построение интерфейса -------------------------------------------
    def _build(self):
        root = self.root

        header = tk.Frame(root, bg=T.bg)
        header.pack(fill="x", padx=16, pady=(14, 4))
        title_box = tk.Frame(header, bg=T.bg)
        title_box.pack(side="left", padx=(2, 20))
        tk.Label(title_box, text="OPENCODE", bg=T.bg, fg=T.cyan, font=T.mono_big).pack(anchor="w")
        tk.Label(title_box, text="ПРОВАЙДЕРЫ И МОДЕЛИ", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w")

        path_box = tk.Frame(header, bg=T.bg)
        path_box.pack(side="left", fill="x", expand=True, padx=8)
        tk.Label(path_box, text="КОНФИГУРАЦИЯ", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w")
        self.var_path = tk.StringVar(value=str(self.config_path))
        ttk.Entry(path_box, textvariable=self.var_path, font=T.mono).pack(
            fill="x", pady=(2, 0))
        btns = tk.Frame(header, bg=T.bg)
        btns.pack(side="right", padx=(8, 2))
        ttk.Button(btns, text="ОТКРЫТЬ ПАПКУ", command=self._open_folder).pack(side="left", padx=3)
        ttk.Button(btns, text="ПЕРЕЗАГРУЗИТЬ", command=self.load).pack(side="left", padx=3)

        ScanStrip(root, color=T.cyan).pack(fill="x", padx=16, pady=(6, 0))

        body = tk.Frame(root, bg=T.bg)
        body.pack(fill="both", expand=True, padx=16, pady=8)

        # левая колонка
        left = tk.Frame(body, bg=T.bg, width=430, highlightthickness=1,
                        highlightbackground=T.line)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        head = tk.Frame(left, bg=T.bg_panel)
        head.pack(fill="x", padx=10, pady=(10, 6))
        tk.Label(head, text="ПРОФИЛИ", bg=T.bg_panel, fg=T.cyan,
                 font=T.mono_title).pack(side="left")
        self.lbl_count = tk.Label(head, text="0", bg=T.bg_panel, fg=T.ink_dim,
                                  font=T.mono_small)
        self.lbl_count.pack(side="right")

        holder = tk.Frame(left, bg=T.bg_panel)
        holder.pack(fill="both", expand=True, padx=8, pady=4)
        self.tree = ttk.Treeview(holder, columns=("name", "url"), show="headings",
                                 selectmode="browse")
        self.tree.heading("name", text="ПРОФИЛЬ")
        self.tree.heading("url", text="URL")
        self.tree.column("name", width=150, anchor="w")
        self.tree.column("url", width=245, anchor="w")
        vsb = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        self.tree.bind("<Double-1>", lambda e: self.edit_profile())

        brow = tk.Frame(left, bg=T.bg_panel)
        brow.pack(fill="x", padx=8, pady=(6, 10))
        ttk.Button(brow, text="+ ДОБАВИТЬ", style="Accent.TButton",
                   command=self.add_profile).pack(side="left", padx=(2, 3), pady=4)
        ttk.Button(brow, text="ИЗМЕНИТЬ", command=self.edit_profile).pack(side="left", padx=3)
        ttk.Button(brow, text="УДАЛИТЬ", style="Danger.TButton",
                   command=self.delete_profile).pack(side="left", padx=3)

        # правая колонка
        right = tk.Frame(body, bg=T.bg, highlightthickness=1, highlightbackground=T.line)
        right.pack(side="left", fill="both", expand=True)
        dhead = tk.Frame(right, bg=T.bg_panel)
        dhead.pack(fill="x", padx=12, pady=(10, 2))
        tk.Label(dhead, text="ПРОФИЛЬ", bg=T.bg_panel, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w")
        self.lbl_title = tk.Label(dhead, text="— НЕ ВЫБРАН —", bg=T.bg_panel, fg=T.cyan,
                                  font=T.mono_big)
        self.lbl_title.pack(anchor="w", pady=(2, 0))

        grid = tk.Frame(right, bg=T.bg_panel)
        grid.pack(fill="x", padx=10, pady=(8, 4))
        self.detail_vars = {}
        for row, (label, key) in enumerate(
            [("ID", "id"), ("НАЗВАНИЕ", "display_name"), ("URL", "base_url"),
             ("API KEY", "api_key"), ("ТРАНСПОРТ", "package")]
        ):
            tk.Label(grid, text=label, bg=T.bg_panel, fg=T.ink_dim, font=T.mono_small,
                     width=11, anchor="w").grid(row=row, column=0, sticky="w",
                                                padx=(6, 8), pady=3)
            var = tk.StringVar()
            self.detail_vars[key] = var
            ent = ttk.Entry(grid, textvariable=var, font=T.mono)
            ent.grid(row=row, column=1, sticky="ew", padx=6, pady=3)
            ent.configure(state="readonly")
            if key == "api_key":
                ent.configure(show="•")
                ttk.Button(grid, text="ПОКАЗАТЬ",
                           command=lambda e=ent: self._toggle_entry(e)).grid(row=row, column=2,
                                                                             padx=6)
        grid.columnconfigure(1, weight=1)

        balpan = tk.Frame(right, bg=T.bg_panel)
        balpan.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(balpan, text="БАЛАНС", bg=T.bg_panel, fg=T.ink_dim,
                 font=T.mono_small).pack(side="left")
        self.lbl_balance_main = tk.Label(balpan, text="—", bg=T.bg_panel, fg=T.ink_dim,
                                         font=T.mono)
        self.lbl_balance_main.pack(side="left", padx=(10, 8))
        self.btn_balance_main = ttk.Button(balpan, text="ОБНОВИТЬ",
                                           command=self.request_balance)
        self.btn_balance_main.pack(side="right", padx=2)
        self.lbl_balance_when = tk.Label(balpan, text="", bg=T.bg_panel, fg=T.cyan_dim,
                                         font=T.mono_small)
        self.lbl_balance_when.pack(side="right", padx=8)

        self.lbl_balance_est_main = tk.Label(right, text="", bg=T.bg_panel, fg=T.cyan_soft,
                                             font=T.mono_small, anchor="w")
        self.lbl_balance_est_main.pack(fill="x", padx=18, pady=(1, 0))

        mhead = tk.Frame(right, bg=T.bg_panel)
        mhead.pack(fill="x", padx=12, pady=(10, 2))
        tk.Label(mhead, text="МОДЕЛИ ПРОФИЛЯ", bg=T.bg_panel, fg=T.ink_dim,
                 font=T.mono_small).pack(side="left")
        self.lbl_models_count = tk.Label(mhead, text="", bg=T.bg_panel, fg=T.amber,
                                         font=T.mono_small)
        self.lbl_models_count.pack(side="right")

        self.lst_models = tk.Listbox(right, height=4, bg=T.bg_input, fg=T.cyan_soft,
                                     selectbackground="#0b3547", selectforeground=T.cyan,
                                     relief="flat", font=T.mono_small,
                                     highlightthickness=1, highlightbackground=T.line)
        self.lst_models.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.lst_models.bind("<Double-1>", lambda e: self.make_default())
        self.lst_models.bind("<Return>", lambda e: self.make_default())

        actions = tk.Frame(right, bg=T.bg_panel)
        actions.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(actions, text="ИЗМЕНИТЬ ПРОФИЛЬ…", style="Accent.TButton",
                   command=self.edit_profile).pack(side="left", fill="x", expand=True,
                                                  padx=(2, 4), pady=4)
        ttk.Button(actions, text="ПО УМОЛЧАНИЮ",
                   command=self.make_default).pack(side="left", fill="x", expand=True,
                                                  padx=(4, 2), pady=4)

        # нижняя панель
        ScanStrip(root, color=T.amber).pack(fill="x", padx=16, pady=(2, 0))
        footer = tk.Frame(root, bg=T.bg)
        footer.pack(fill="x", padx=16, pady=(8, 6))
        leftrow = tk.Frame(footer, bg=T.bg)
        leftrow.pack(fill="x")
        tk.Label(leftrow, text="МОДЕЛЬ ПО УМОЛЧАНИЮ", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(side="left", padx=(4, 10))
        self.var_default_model = tk.StringVar()
        ent = ttk.Entry(leftrow, textvariable=self.var_default_model, font=T.mono)
        ent.configure(state="readonly")
        ent.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        ttk.Button(leftrow, text="ПРИМЕНИТЬ К КОНФИГУ", style="Accent.TButton",
                   command=self.write_config).pack(side="left", padx=(8, 4))
        self.lbl_dirty = tk.Label(leftrow, text="", bg=T.bg, fg=T.amber, font=T.mono_small)
        self.lbl_dirty.pack(side="left", padx=(6, 2))

        row2 = tk.Frame(footer, bg=T.bg)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Button(row2, text="ИСТОРИЯ И ОТКАТ…",
                   command=self.open_history).pack(side="left", padx=3)
        ttk.Button(row2, text="СНИМОК СЕЙЧАС",
                   command=lambda: self.snapshot_now("Ручной снимок")).pack(side="left", padx=3)
        ttk.Button(row2, text="ЭКСПОРТ ПРОФИЛЯ…",
                   command=self.export_profile).pack(side="left", padx=3)
        ttk.Button(row2, text="ИМПОРТ ПРОФИЛЯ…",
                   command=self.import_profile).pack(side="left", padx=3)
        self.hist_info = tk.Label(row2, text="Снимков: 0", bg=T.bg, fg=T.cyan_soft,
                                  font=T.mono_small, anchor="e")
        self.hist_info.pack(side="right", padx=(6, 10))

        # справа от кнопок больше не остаётся «пустых кнопок» — только ровный фон
        tk.Frame(row2, bg=T.bg).pack(side="left", fill="x", expand=True)
        tk.Label(root, text="CTRL+Z — ОТКАТ К ПРЕДЫДУЩЕЙ ВЕРСИИ", bg=T.bg, fg=T.cyan_dim,
                 font=T.mono_small).pack(anchor="w", padx=22, pady=(0, 2))

        status_bar = tk.Frame(root, bg=T.bg_panel_hi, height=26)
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)
        self.status = tk.Label(status_bar, text="", bg=T.bg_panel_hi, fg=T.cyan_soft,
                               font=T.mono_small, anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=14)

    def _toggle_entry(self, ent):
        showing = ent.cget("show") == ""
        ent.configure(show="•" if showing else "")

    # --- данные -----------------------------------------------------------
    def load(self):
        path = Path(self.var_path.get().strip() or default_config_path())
        self.config_path = path
        try:
            self.config = load_config(path)
            self.profiles = profiles_from_config(self.config)
        except Exception as exc:
            messagebox.showerror("Чтение конфига",
                                 "Не удалось прочитать:\n%s\n\n%s" % (path, exc))
            self.config, self.profiles = {}, []
        self.var_default_model.set(default_model_ref(self.config) or "(не задана)")
        self._render_list()
        self._refresh_history()
        self._base_signature = self._signature()
        self._set_status("ЗАГРУЖЕНО ПРОФИЛЕЙ: %d   •   %s" % (len(self.profiles), path))

    def _signature(self) -> str:
        try:
            return json.dumps([self.config, self.profiles], sort_keys=True,
                              ensure_ascii=False, default=str)
        except Exception:
            return ""

    def _is_dirty(self) -> bool:
        return self._base_signature != self._signature()

    def _refresh_dirty_marker(self):
        lbl = getattr(self, "lbl_dirty", None)
        if lbl is None:
            return
        try:
            lbl.configure(text="● ЕСТЬ НЕСОХРАНЁННЫЕ ИЗМЕНЕНИЯ" if self._is_dirty() else "")
        except Exception:
            pass

    def _set_status(self, text):
        try:
            self.status.configure(text=text)
        except Exception:
            pass

    def _render_list(self):
        self.tree.delete(*self.tree.get_children())
        for p in self.profiles:
            self.tree.insert("", "end", iid=p["id"],
                             values=(p["display_name"], p["base_url"]))
        try:
            self.lbl_count.configure(text=str(len(self.profiles)))
        except Exception:
            pass
        if self.profiles:
            self.tree.selection_set(self.profiles[0]["id"])
            self._on_select()
        else:
            self._clear_details()
        self._refresh_dirty_marker()

    def _find(self, pid):
        for p in self.profiles:
            if p["id"] == pid:
                return p
        return None

    def _on_select(self):
        sel = self.tree.selection()
        if not sel:
            self._clear_details()
            return
        self.selected = sel[0]
        profile = self._find(self.selected)
        if not profile:
            return
        self.lbl_title.configure(text=(profile["display_name"] or profile["id"]).upper())
        for key in ("id", "display_name", "base_url", "package"):
            self.detail_vars[key].set(profile[key])
        key = profile["api_key"]
        self.detail_vars["api_key"].set(
            "(не задан)" if not key else (key[:6] + "…" + key[-4:] if len(key) > 12 else "••••"))
        self.lst_models.delete(0, "end")
        for mid in profile["models"]:
            self.lst_models.insert("end", mid)
        if profile["models"]:
            current = self.var_default_model.get()
            prefix = str(profile["id"]) + "/"
            idx = 0
            if current.startswith(prefix):
                cur_model = current[len(prefix):]
                if cur_model in profile["models"]:
                    idx = profile["models"].index(cur_model)
            self.lst_models.selection_set(idx)
            self.lst_models.see(idx)
        else:
            self.lst_models.insert("end", "(модели не выбраны)")
        try:
            self.lbl_models_count.configure(text=str(len(profile["models"])))
            self.lst_models.configure(height=max(3, min(10, len(profile["models"]) or 3)))
        except Exception:
            pass
        self._show_balance(profile)
        if not profile.get("_balance") and not profile.get("_balance_tried"):
            profile["_balance_tried"] = True
            self.root.after(250, self.request_balance)

    def _clear_details(self):
        self.lbl_title.configure(text="— НЕ ВЫБРАН —")
        for var in self.detail_vars.values():
            var.set("")
        self.lst_models.delete(0, "end")

    # --- операции ---------------------------------------------------------
    def add_profile(self):
        dlg = ProfileDialog(self, None)
        self.root.wait_window(dlg)
        res = dlg.result
        if not res:
            return
        self.profiles.append(self._from_dialog(res))
        self._render_list()
        self.tree.selection_set(res["id"])
        self._set_status("ДОБАВЛЕН ПРОФИЛЬ %s (НЕ СОХРАНЁН)" % res["id"])
        self._refresh_dirty_marker()
        if res.get("set_default") and res["models"]:
            self.var_default_model.set("%s/%s" % (res["id"], res["models"][0]))

    def edit_profile(self):
        if not self.selected:
            messagebox.showinfo("Изменить", "Выберите профиль в списке", parent=self.root)
            return
        profile = self._find(self.selected)
        if not profile:
            return
        dlg = ProfileDialog(self, profile)
        self.root.wait_window(dlg)
        res = dlg.result
        if not res:
            return
        index = self.profiles.index(profile)
        self.profiles[index] = self._from_dialog(res)
        self.selected = res["id"]
        self._render_list()
        self._set_status("ПРОФИЛЬ %s ОБНОВЛЁН (НЕ СОХРАНЁН)" % res["id"])
        self._refresh_dirty_marker()

    def _from_dialog(self, res):
        return {
            "id": res["id"],
            "display_name": res["display_name"],
            "base_url": res["base_url"],
            "api_key": res["api_key"],
            "package": res["package"],
            "models": list(res["models"]),
            "known_models": list(res["known_models"]),
            "coefficient": res.get("coefficient") or "",
            "extra_settings": res.get("extra_settings") or {},
            "_raw": res.get("_raw"),
        }

    def delete_profile(self):
        profile = self._find(self.selected) if self.selected else None
        if not profile:
            messagebox.showinfo("Удалить", "Выберите профиль в списке", parent=self.root)
            return
        if not messagebox.askyesno(
                "Удалить профиль",
                "Удалить профиль «%s»?\n\nИз конфига он исчезнет после "
                "«ПРИМЕНИТЬ К КОНФИГУ»." % profile["display_name"], parent=self.root):
            return
        self.profiles.remove(profile)
        self.selected = None
        self._render_list()
        self._set_status("ПРОФИЛЬ %s УДАЛЁН ИЗ СПИСКА" % profile["id"])
        self._refresh_dirty_marker()

    # --- модель по умолчанию ---------------------------------------------
    def make_default(self):
        profile = self._find(self.selected) if self.selected else None
        if not profile or not profile["models"]:
            messagebox.showinfo("По умолчанию",
                                "У выбранного профиля нет моделей", parent=self.root)
            return
        picked = self._selected_model()
        if not picked:
            # ничего не выделено в списке моделей
            if len(profile["models"]) == 1:
                picked = profile["models"][0]
            else:
                # спрашиваем выбор ТОЛЬКО когда модель не выделена
                picked = self._ask_model(profile)
                if not picked:
                    return
        self._apply_default(profile, picked)

    def _selected_model(self):
        """Модель, выделенная курсором в списке «МОДЕЛИ ПРОФИЛЯ»."""
        try:
            sel = self.lst_models.curselection()
            if sel:
                val = self.lst_models.get(sel[0])
                if val and val != "(модели не выбраны)":
                    return val
        except Exception:
            pass
        return None

    def _apply_default(self, profile, picked):
        self.var_default_model.set("%s/%s" % (profile["id"], picked))
        self._set_status("МОДЕЛЬ ПО УМОЛЧАНИЮ: %s/%s (НЕ СОХРАНЕНО)" % (profile["id"], picked))
        self._refresh_dirty_marker()

    def _ask_model(self, profile):
        win = tk.Toplevel(self.root)
        win.title("МОДЕЛЬ ПО УМОЛЧАНИЮ")
        win.configure(bg=T.bg)
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text="ВЫБЕРИТЕ МОДЕЛЬ", bg=T.bg, fg=T.cyan,
                 font=T.mono_title).pack(anchor="w", padx=14, pady=(12, 6))
        lb = tk.Listbox(win, height=min(12, len(profile["models"])), width=62,
                        bg=T.bg_panel, fg=T.ink, selectbackground="#0b3547",
                        selectforeground=T.cyan, font=T.mono_small, relief="flat",
                        highlightthickness=1, highlightbackground=T.line)
        for mid in profile["models"]:
            lb.insert("end", mid)
        lb.pack(fill="both", expand=True, padx=14, pady=4)
        lb.selection_set(0)
        chosen = {"value": None}

        def ok():
            sel = lb.curselection()
            if sel:
                chosen["value"] = profile["models"][sel[0]]
            win.destroy()

        row = tk.Frame(win, bg=T.bg)
        row.pack(fill="x", padx=14, pady=(4, 12))
        ttk.Button(row, text="ОК", style="Accent.TButton", command=ok).pack(side="right", padx=4)
        ttk.Button(row, text="ОТМЕНА", command=win.destroy).pack(side="right")
        win.wait_window()
        return chosen["value"]

    # --- баланс профиля ---------------------------------------------------
    def request_balance(self):
        if not hasattr(self, "_balance_results"):
            self._balance_results = queue.Queue()
        profile = self._find(self.selected) if self.selected else None
        if not profile:
            messagebox.showinfo("Баланс", "Выберите профиль в списке", parent=self.root)
            return
        self.lbl_balance_main.configure(text="ЗАГРУЗКА…", fg=T.ink_dim)
        self.lbl_balance_when.configure(text="запрос…")
        try:
            self.btn_balance_main.configure(state="disabled")
        except Exception:
            pass

        def work():
            try:
                self._balance_results.put((profile["id"], fetch_balance(
                    profile["base_url"], profile["api_key"]), None))
            except Exception as exc:
                self._balance_results.put((profile["id"], None, exc))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(120, self._poll_balance)

    def _poll_balance(self):
        try:
            pid, data, err = self._balance_results.get_nowait()
        except queue.Empty:
            self.root.after(120, self._poll_balance)
            return
        try:
            self.btn_balance_main.configure(state="normal")
        except Exception:
            pass
        profile = self._find(pid)
        if profile is None:
            return
        if err is not None:
            self.lbl_balance_main.configure(text="нет данных", fg=T.red)
            self.lbl_balance_when.configure(text=str(err)[:70])
            profile["_balance"] = None
            profile["_balance_error"] = str(err)
            return
        profile["_balance"] = data
        profile["_balance_error"] = None
        profile["_balance_at"] = datetime.now()
        if pid == self.selected:
            self._show_balance(profile)
        if not profile.get("_balance") and not profile.get("_balance_tried"):
            profile["_balance_tried"] = True
            self.root.after(250, self.request_balance)

    def _show_balance(self, profile):
        data = profile.get("_balance")
        when = profile.get("_balance_at")
        try:
            if data:
                self.lbl_balance_main.configure(text=data.get("text") or "—", fg=T.green)
                self.lbl_balance_when.configure(
                    text=("обновлено %s" % when.strftime("%H:%M:%S")) if when else "")
                coef = str(profile.get("coefficient") or "").strip()
                est = coefficient_estimate(data.get("tokens"), coef) if coef else {}
                if est:
                    self.lbl_balance_est_main.configure(
                        text="≈ %s при коэффициенте %s" % (est["text"], coef))
                elif not coef:
                    self.lbl_balance_est_main.configure(
                        text="коэффициент не задан — укажите в профиле, чтобы видеть остаток в токенах")
                else:
                    self.lbl_balance_est_main.configure(text="")
            else:
                err = profile.get("_balance_error")
                self.lbl_balance_main.configure(text="—" if not err else "нет данных",
                                                fg=T.ink_dim if not err else T.red)
                self.lbl_balance_when.configure(text=(err or "")[:70])
                self.lbl_balance_est_main.configure(text="")
        except Exception:
            pass

    def _open_folder(self):
        try:
            os.startfile(str(self.config_path.parent))
        except Exception as exc:
            messagebox.showerror("Папка", str(exc), parent=self.root)

    # --- история и откат --------------------------------------------------
    def _refresh_history(self):
        try:
            self._history = list_backups(self.config_path)
        except Exception:
            self._history = []
        info = getattr(self, "hist_info", None)
        if info is not None:
            last = self._history[0]["time"].strftime("%d.%m.%Y %H:%M:%S") \
                if self._history and self._history[0].get("time") else "—"
            info.configure(text="Снимков: %d  •  последний: %s" % (len(self._history), last))

    def open_history(self):
        HistoryWindow(self)

    def snapshot_now(self, reason=""):
        try:
            snap = make_snapshot(self.config_path)
        except Exception as exc:
            messagebox.showerror("Снимок", str(exc), parent=self.root)
            return None
        if snap:
            self._refresh_history()
            self._set_status((reason + "  •  " if reason else "") + "СНИМОК: " + snap.name)
        return snap

    def undo_last(self):
        if self._is_dirty():
            if not messagebox.askyesno(
                    "Откат",
                    "Есть неприменённые изменения в форме. Откатить файл к предыдущей версии?",
                    parent=self.root):
                return
        self._refresh_history()
        if not self._history:
            messagebox.showinfo("Откат", "Снимков ещё нет.", parent=self.root)
            return
        self.quick_restore(self._history[0])

    def quick_restore(self, entry):
        if not entry.get("valid"):
            messagebox.showerror("Откат", "Снимок повреждён:\n%s" % entry["name"],
                                 parent=self.root)
            return
        when = entry["time"].strftime("%d.%m.%Y %H:%M:%S") if entry.get("time") else "?"
        if not messagebox.askyesno(
                "Откатить конфиг?",
                "Восстановить версию от %s?\n\nФайл: %s\nПровайдеры: %s\nМодель: %s\n\n"
                "Текущая версия тоже сохранится в историю." % (
                    when, entry["path"].name,
                    ", ".join(entry.get("providers") or []) or "(нет)",
                    entry.get("model") or "(не задана)"), parent=self.root):
            return
        try:
            safety = restore_backup(self.config_path, entry["path"])
        except Exception as exc:
            messagebox.showerror("Откат", str(exc), parent=self.root)
            return
        self.load()
        self._set_status("ОТКАТ ВЫПОЛНЕН. ВЕРСИЯ ДО ОТКАТА: %s" %
                         (safety.name if safety else "—"))
        messagebox.showinfo("Откат", "Конфиг восстановлен из снимка %s.\nОткат самого отката: %s"
                            % (entry["name"], safety.name if safety else "—"), parent=self.root)

    # --- сохранение -------------------------------------------------------
    def write_config(self):
        was_dirty = self._is_dirty()
        try:
            new_config = apply_profiles(self.config, self.profiles)
            ref = self.var_default_model.get().strip()
            if ref and ref != "(не задана)":
                new_config["model"] = ref
            backup = save_config(self.config_path, new_config)
        except Exception as exc:
            messagebox.showerror("Запись конфига", str(exc), parent=self.root)
            return
        self.config = new_config
        self.profiles = profiles_from_config(self.config)
        self._base_signature = self._signature()
        self._render_list()
        self._refresh_history()
        self._refresh_dirty_marker()
        msg = "Конфиг записан. Предыдущая версия: %s" % (backup.name if backup else "—")
        self._set_status(msg.upper())
        messagebox.showinfo(
            "Готово",
            "%s\n\nФайл: %s\n\nОткат: кнопка «ИСТОРИЯ И ОТКАТ…» или Ctrl+Z" % (
                msg, self.config_path), parent=self.root)
        if not was_dirty:
            self._set_status("СОХРАНЕНА КОНТРОЛЬНАЯ ТОЧКА: " + (backup.name if backup else "—"))

    # --- экспорт / импорт -------------------------------------------------
    def export_profile(self):
        profile = self._find(self.selected) if self.selected else None
        if not profile:
            messagebox.showinfo("Экспорт", "Выберите профиль в списке", parent=self.root)
            return
        data = {
            "version": 1,
            "type": "opencode-provider-profile",
            "id": profile["id"],
            "display_name": profile["display_name"],
            "base_url": profile["base_url"],
            "package": profile["package"],
            "api_key": profile["api_key"],
            "models": list(profile["models"]),
            "known_models": list(profile["known_models"]),
            "extra_settings": profile.get("extra_settings") or {},
            "raw": profile.get("_raw") or {},
        }
        default_dir = str(Path.home() / "Downloads")
        name = filedialog.asksaveasfilename(
            parent=self.root, title="Экспорт профиля", defaultextension=".json",
            initialdir=default_dir if Path(default_dir).is_dir() else str(Path.home()),
            initialfile=profile["id"] + ".profile.json",
            filetypes=[("JSON файлы", "*.json"), ("Все файлы", "*.*")])
        if not name:
            return
        path = Path(name)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except PermissionError:
            messagebox.showerror(
                "Экспорт",
                "Нет доступа к папке: %s\n\nВыберите другую папку (например, Загрузки)." % path.parent,
                parent=self.root)
            return
        except Exception as exc:
            messagebox.showerror("Экспорт", "Не удалось сохранить файл:\n%s\n\n%s" % (path, exc),
                                 parent=self.root)
            return
        if not path.exists():
            messagebox.showerror("Экспорт", "Файл не создан: %s" % path, parent=self.root)
            return
        self._set_status("ПРОФИЛЬ %s ЭКСПОРТИРОВАН: %s" % (profile["id"], path))
        messagebox.showinfo("Экспорт", "Сохранено:\n%s\n\nРазмер: %d байт"
                            % (path, path.stat().st_size), parent=self.root)

    def import_profile(self):
        default_dir = str(Path.home() / "Downloads")
        name = filedialog.askopenfilename(
            parent=self.root, title="Импорт профиля",
            initialdir=default_dir if Path(default_dir).is_dir() else str(Path.home()),
            filetypes=[("JSON файлы", "*.json"), ("Все файлы", "*.*")])
        if not name:
            return
        src = Path(name)
        if not src.exists():
            messagebox.showerror("Импорт", "Файл не найден:\n%s" % src, parent=self.root)
            return
        try:
            raw = json.loads(src.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            messagebox.showerror("Импорт", "Не удалось прочитать файл:\n%s\n\n%s" % (src, exc),
                                 parent=self.root)
            return
        if not isinstance(raw, dict):
            messagebox.showerror("Импорт", "Файл не содержит объект JSON", parent=self.root)
            return
        pid = str(raw.get("id") or "").strip()
        if not re.match(r"^[A-Za-z0-9._-]+$", pid or ""):
            messagebox.showerror("Импорт", "В файле отсутствует корректный ID профиля",
                                 parent=self.root)
            return
        existing = self._find(pid)
        if existing is not None and not messagebox.askyesno(
                "Импорт", "Профиль «%s» уже есть. Заменить его?" % pid, parent=self.root):
            return
        profile = {
            "id": pid,
            "display_name": raw.get("display_name") or pid,
            "base_url": raw.get("base_url") or "",
            "api_key": raw.get("api_key") or "",
            "package": raw.get("package") or PACKAGES[0],
            "models": list(raw.get("models") or []),
            "known_models": list(raw.get("known_models") or raw.get("models") or []),
            "extra_settings": raw.get("extra_settings") or {},
            "_raw": raw.get("raw") or None,
        }
        if existing is not None:
            self.profiles[self.profiles.index(existing)] = profile
        else:
            self.profiles.append(profile)
        self.selected = pid
        self._render_list()
        self._set_status("ИМПОРТИРОВАН ПРОФИЛЬ %s (НЕ СОХРАНЁН)" % pid)

    def run(self):
        self.root.mainloop()


# ==========================================================================
# Зависимости и точка входа
# ==========================================================================

def _have(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


# Пакеты, которые проверяются при старте: модуль -> (пакет на PyPI, чем полезен)
REQUIRED = {
    "certifi": ("certifi", "актуальные корневые сертификаты для TLS"),
}
# Необязательные улучшения (ставим, только если ещё нет)
OPTIONAL = {
    "PIL": ("Pillow", "запасной захват экрана диагностики"),
}


def _pip_install(pkg: str) -> tuple[bool, str]:
    import subprocess
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", "--upgrade", "--quiet", pkg],
            capture_output=True, text=True, timeout=240)
        if proc.returncode == 0:
            return True, ""
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, (detail[-1] if detail else "pip завершился с кодом %d" % proc.returncode)
    except Exception as exc:
        return False, str(exc)


def ensure_dependencies() -> list:
    """Проверяет окружение и догружает отсутствующие пакеты в реальном времени."""
    notes = []
    if not _have("tkinter"):
        return ["tkinter не найден — переустановите Python с компонентом Tcl/Tk"]

    needed = []
    for module, (pkg, why) in REQUIRED.items():
        if not _have(module):
            needed.append((pkg, why))
    if getattr(sys, "frozen", False):
        # в exe всё уже упаковано: pip не нужен и его там нет
        needed = []
    if needed and not _have("pip"):
        # в собранном exe pip вырезан — автодогрузка не нужна и не возможна
        if getattr(sys, "frozen", False):
            return notes
        try:
            import ensurepip  # noqa: F401
            ensurepip.bootstrap()
        except Exception:
            pass
    if needed and not _have("pip"):
        notes.append("pip недоступен — автодогрузка невозможна (python -m ensurepip)")
        return notes

    for pkg, why in needed:
        notes.append("Догружаю %s — %s…" % (pkg, why))
        ok, err = _pip_install(pkg)
        if ok and _have(pkg):
            notes.append("%s установлен" % pkg)
        else:
            notes.append("%s не установился: %s" % (pkg, err or "неизвестная ошибка"))
    return notes


def hide_console():
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass


def main():
    hide_console()
    notes = ensure_dependencies()
    app = App()
    if notes:
        app._set_status("  •  ".join(notes))
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
