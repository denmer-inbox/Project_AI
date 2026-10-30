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
* экспорт и импорт всех профилей в один JSON-файл;
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
    panel_fill = "#061722"     # заливка панели (чуть светлее фона окна)
    panel_edge = "#1d5a6e"     # контур панели
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




class RoundedPanel(tk.Canvas):
    """Панель со скруглёнными углами: рисуем скругление на канве,
    дочерние виджеты кладём во внутренний Frame через create_window.

    Использование:
        panel = RoundedPanel(parent, width=430, fill="#04101a", outline="#0e2b3a")
        panel.pack(side="left", fill="y")
        panel.inner  # -> Frame, в него упаковываем содержимое
    """

    def __init__(self, master, width=None, height=None, radius=14, fill=None,
                 outline=None, thickness=1, bg=None, **kw):
        self.radius = int(radius)
        self.fill = fill or T.bg_panel
        self.outline = outline or T.line
        self.thickness = int(thickness)
        outer_bg = bg or (master.cget("bg") if hasattr(master, "cget") else T.bg)
        super().__init__(master, bg=outer_bg, highlightthickness=0, bd=0,
                         width=width or 1, height=height or 1, **kw)
        self.configure(bg=outer_bg)
        self.inner = tk.Frame(self, bg=self.fill)
        self._win = self.create_window(0, 0, window=self.inner, anchor="nw")
        self.bind("<Configure>", self._redraw)

    def _round_rect(self, x1, y1, x2, y2, r, fill="", outline="", width=1, **kw):
        """Скруглённый прямоугольник из точной дуги (без spline-артефактов).

        Рисуем заливку как набор прямоугольников + 4 круга, а контур —
        как линии и 4 дуги. Это даёт настоящие скруглённые углы.
        """
        r = max(0, min(int(r), int((x2 - x1) / 2), int((y2 - y1) / 2)))
        ids = []
        if fill:
            ids.append(self.create_rectangle(x1 + r, y1, x2 - r, y2,
                                             fill=fill, outline=""))
            ids.append(self.create_rectangle(x1, y1 + r, x1 + r, y2 - r,
                                             fill=fill, outline=""))
            ids.append(self.create_rectangle(x2 - r, y1 + r, x2, y2 - r,
                                             fill=fill, outline=""))
            ids.append(self.create_oval(x1, y1, x1 + 2 * r, y1 + 2 * r,
                                        fill=fill, outline=""))
            ids.append(self.create_oval(x2 - 2 * r, y1, x2, y1 + 2 * r,
                                        fill=fill, outline=""))
            ids.append(self.create_oval(x1, y2 - 2 * r, x1 + 2 * r, y2,
                                        fill=fill, outline=""))
            ids.append(self.create_oval(x2 - 2 * r, y2 - 2 * r, x2, y2,
                                        fill=fill, outline=""))
        if outline:
            w = max(1, int(width))
            ids.append(self.create_line(x1 + r, y1, x2 - r, y1,
                                        fill=outline, width=w))
            ids.append(self.create_line(x1 + r, y2, x2 - r, y2,
                                        fill=outline, width=w))
            ids.append(self.create_line(x1, y1 + r, x1, y2 - r,
                                        fill=outline, width=w))
            ids.append(self.create_line(x2, y1 + r, x2, y2 - r,
                                        fill=outline, width=w))
            for (sx, sy, st) in ((1, 1, 90), (0, 1, 0), (0, 0, 270), (1, 0, 180)):
                ids.append(self.create_arc(
                    x1 if sx else x2 - 2 * r, y1 if sy else y2 - 2 * r,
                    x1 + 2 * r if sx else x2, y1 + 2 * r if sy else y2,
                    start=st, extent=90, style="arc", outline=outline, width=w))
        return ids

    def _redraw(self, event=None):
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4:
            return
        self.delete("bgshape")
        pad = max(1, self.thickness)
        ids = self._round_rect(pad, pad, w - pad, h - pad, self.radius,
                               fill=self.fill, outline=self.outline,
                               width=self.thickness)
        for i in ids:
            self.itemconfigure(i, tags="bgshape")
        self.tag_lower("bgshape")
        inset = self.thickness + 6
        self.coords(self._win, inset, inset)
        self.itemconfigure(self._win, width=max(1, w - inset * 2),
                           height=max(1, h - inset * 2))





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
            if status == 429:
                raise RuntimeError("Рейт-лимит 429 — жду минуту")
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
# Файл экспорта / импорта профилей
# ==========================================================================

EXPORT_TYPE = "opencode-provider-profiles"
EXPORT_VERSION = 2
EXPORT_TYPE_SINGLE = "opencode-provider-profile"


def profile_to_export(profile: dict) -> dict:
    """Профиль в виде, пригодном для записи в файл (без служебных полей)."""
    return {
        "id": profile["id"],
        "display_name": profile["display_name"],
        "coefficient": str(profile.get("coefficient") or ""),
        "base_url": profile["base_url"],
        "package": profile["package"],
        "api_key": profile["api_key"],
        "models": list(profile["models"]),
        "known_models": list(profile["known_models"]),
        "extra_settings": profile.get("extra_settings") or {},
        "raw": profile.get("_raw") or {},
    }


def build_export_payload(profiles: list, default_model: str = "") -> dict:
    """Один файл со всеми профилями моделей (а не с одним выбранным)."""
    payload = {
        "version": EXPORT_VERSION,
        "type": EXPORT_TYPE,
        "profiles": [profile_to_export(p) for p in profiles],
    }
    ref = (default_model or "").strip()
    if ref and ref != "(не задана)":
        payload["default_model"] = ref
    return payload


def profile_from_export(raw: dict) -> dict:
    """Превращает запись из файла экспорта во внутренний профиль."""
    if not isinstance(raw, dict):
        raise ValueError("запись профиля не является объектом JSON")
    pid = str(raw.get("id") or "").strip()
    if not re.match(r"^[A-Za-z0-9._-]+$", pid or ""):
        raise ValueError("отсутствует корректный ID профиля")
    models = [str(m) for m in (raw.get("models") or []) if str(m).strip()]
    known = [str(m) for m in (raw.get("known_models") or models) if str(m).strip()]
    return {
        "id": pid,
        "display_name": raw.get("display_name") or pid,
        "coefficient": str(raw.get("coefficient") or ""),
        "base_url": raw.get("base_url") or "",
        "api_key": raw.get("api_key") or "",
        "package": raw.get("package") or PACKAGES[0],
        "models": models,
        "known_models": known,
        "extra_settings": raw.get("extra_settings") or {},
        "_raw": raw.get("raw") or None,
    }


def profiles_from_export(data) -> tuple:
    """Разбирает файл экспорта. Понимает и новый формат (все профили),
    и старый (один профиль), и просто список профилей.

    Возвращает (profiles, default_model).
    """
    if isinstance(data, list):
        entries, default_model = data, ""
    elif isinstance(data, dict):
        default_model = str(data.get("default_model") or "").strip()
        if isinstance(data.get("profiles"), list):
            entries = data["profiles"]
        elif data.get("id"):
            # старый формат: один профиль в корне файла
            entries = [data]
        else:
            raise ValueError("В файле нет профилей (ожидается ключ \"profiles\")")
    else:
        raise ValueError("Файл не содержит объект JSON")
    result = []
    for idx, entry in enumerate(entries, 1):
        try:
            result.append(profile_from_export(entry))
        except ValueError as exc:
            raise ValueError("Профиль №%d: %s" % (idx, exc))
    if not result:
        raise ValueError("В файле нет ни одного профиля")
    return result, default_model


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

        # master=self: переменные должны принадлежать этому же Tk-интерпретатору,
        # иначе (если в процессе есть другой корень) поле теряет связь с переменной
        self.var_id = tk.StringVar(master=self, value=(profile or {}).get("id", ""))
        self.var_name = tk.StringVar(master=self, value=(profile or {}).get("display_name", ""))
        self.var_url = tk.StringVar(master=self, value=(profile or {}).get("base_url", ""))
        self.var_key = tk.StringVar(master=self, value=(profile or {}).get("api_key", ""))
        self.var_pkg = tk.StringVar(master=self, value=(profile or {}).get("package", PACKAGES[0]))
        self.var_set_default = tk.BooleanVar(master=self, value=False)
        self.var_coef = tk.StringVar(master=self,
                                     value=str((profile or {}).get("coefficient", "") or ""))
        self.var_filter = tk.StringVar(master=self)
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
        # сразу ставим фокус в первое поле: вставка работает без лишнего клика
        try:
            self.after(60, self._focus_first_field)
        except Exception:
            pass
        self.bind("<Escape>", lambda e: self._cancel())
        if not self.is_new and self.known_models:
            for mid in self.known_models:
                self.models.append({"id": mid, "display": mid})
            self._render_models()

    # --- UI -------------------------------------------------------------
    def _focus_first_field(self):
        """Фокус в первое поле ввода (вызывается после отрисовки диалога)."""
        try:
            self.e_id.focus_set()
        except Exception:
            pass

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

        box_panel = RoundedPanel(mid, radius=16, fill=T.bg_panel,
                                 outline=T.cyan_dim, thickness=1, bg=T.bg)
        box_panel.pack(side="bottom", fill="both", expand=True, pady=(0, 6))
        box = box_panel.inner
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

        mid_panel = RoundedPanel(self, radius=18, fill=T.bg_panel,
                                 outline=T.cyan_dim, thickness=1, bg=T.bg)
        mid_panel.pack(fill="both", expand=True, padx=16)
        mid = mid_panel.inner
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

# Виртуальные коды Windows одинаковы при любой раскладке: Tk кладёт их в
# event.keycode. При русской раскладке Ctrl+V приходит с keysym «м»
# (Cyrillic_em), а не «v», поэтому привязки вида <Control-v> и штатная
# карта <<Paste>> молчат — вставка не работает. Распознаём сочетания по коду
# клавиши и выполняем действие штатным виртуальным событием Tk.
VK_INSERT = 45
VK_A = 65
VK_C = 67
VK_V = 86
VK_X = 88

#: Маска состояния Ctrl в событии Tk.
CONTROL_STATE = 0x0004

#: Действие -> виртуальное событие Tk, которое выполняет его штатно.
SHORTCUT_EVENTS = {
    "paste": "<<Paste>>",
    "copy": "<<Copy>>",
    "cut": "<<Cut>>",
    "select_all": "<<SelectAll>>",
}

#: Действие -> коды клавиш, которые запускают его с зажатым Ctrl.
CONTROL_KEYCODES = {
    "paste": (VK_V,),
    "copy": (VK_C, VK_INSERT),
    "cut": (VK_X,),
    "select_all": (VK_A,),
}

#: Латинские символы этих же клавиш: с ними Tk справляется сам.
LATIN_SHORTCUT_KEYSYMS = {
    "paste": ("v", "V"),
    "copy": ("c", "C"),
    "cut": ("x", "X"),
    "select_all": ("a", "A"),
}

#: Классы виджетов, в которых работают вставка и команды редактирования.
INPUT_CLASSES = ("TEntry", "TCombobox", "TSpinbox", "Entry", "Spinbox", "Text")


def is_input_widget(widget):
    """Поле ввода, в котором имеет смысл вставка/копирование."""
    try:
        return widget.winfo_class() in INPUT_CLASSES
    except Exception:
        return False


def _int_attr(event, name):
    try:
        return int(getattr(event, name, 0) or 0)
    except Exception:
        return 0


def event_state(event):
    return _int_attr(event, "state")


def event_keycode(event):
    return _int_attr(event, "keycode")


def event_keysym(event):
    return str(getattr(event, "keysym", "") or "")


def shortcut_action(event):
    """Команда редактирования для Ctrl+клавиша (по коду клавиши) или None.

    Код клавиши не зависит от раскладки: Ctrl+V — это V=86 и при английской,
    и при русской раскладке.
    """
    if event is None:
        return None
    if not event_state(event) & CONTROL_STATE:
        return None
    keycode = event_keycode(event)
    for action, codes in CONTROL_KEYCODES.items():
        if keycode in codes:
            return action
    return None


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
        # не «залипающее» меню: закрывается по клику вне его
        self.menu.bind("<FocusOut>", lambda e: self.menu.unpost())

    def _widget(self, event):
        w = event.widget
        return w if is_input_widget(w) else None

    def bind(self, widget):
        widget.bind("<Button-3>", self.popup, add="+")
        return widget

    def bind_tree(self, widget):
        """ПКМ-меню и горячие клавиши для виджета и всех его детей."""
        self.bind(widget)
        if is_input_widget(widget):
            widget.bind("<Control-KeyPress>", self.on_control_key, add="+")
        for child in widget.winfo_children():
            self.bind_tree(child)

    def _target_for(self, event=None):
        """Поле, к которому относится нажатие: виджет события или фокус."""
        widget = getattr(event, "widget", None) if event is not None else None
        if is_input_widget(widget):
            return widget
        try:
            widget = self.root.focus_get()
        except Exception:
            widget = None
        return widget if is_input_widget(widget) else None

    def _run_shortcut(self, widget, action):
        """Выполнить команду штатным виртуальным событием Tk."""
        virtual = SHORTCUT_EVENTS[action]
        if widget is None:
            return None
        try:
            widget.event_generate(virtual)
        except Exception:
            return None
        return "break"

    def on_control_key(self, event):
        """Ctrl+V / Ctrl+C / Ctrl+X / Ctrl+A при любой раскладке.

        При латинском keysym команду штатно выполнит сам Tk (привязки
        <Control-v>, <<Paste>> и т.п.), поэтому ничего не делаем — иначе
        текст вставится дважды. Если keysym не латинский (русская
        раскладка: «м», «с», «ч», «ф»), штатные привязки молчат —
        распознаём клавишу по коду и выполняем действие вручную.
        """
        action = shortcut_action(event)
        if action is None:
            return None
        if event_keysym(event) in LATIN_SHORTCUT_KEYSYMS[action]:
            return None
        return self._run_shortcut(self._target_for(event), action)

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

    # --- буфер ------------------------------------------------------------
    def _read_clip(self):
        try:
            return self.root.clipboard_get()
        except Exception:
            return ""

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
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"


def install_clipboard(root):
    """Ctrl+C / Ctrl+V / Ctrl+X / Ctrl+A + Shift+Ins / Ctrl+Ins для всех полей.

    Латинскую раскладку Tk понимает сам; для нелатинской (русской) раскладки
    в ClipboardMenu есть обработчик по коду клавиши — иначе Ctrl+V приходит с
    keysym «м» и штатные привязки <<Paste>> / <Control-v> не срабатывают.
    Поля конкретного окна подключаются через clipboard.bind_tree(...) — так
    диалоги (например, «ПРОФИЛЬ ПРОВАЙДЕРА») получают обработчики для своих
    полей, созданных позже.
    """
    menu = ClipboardMenu(root)
    for klass in INPUT_CLASSES:
        try:
            root.bind_class(klass, "<Control-KeyPress>", menu.on_control_key, add="+")
        except Exception:
            pass
    return menu


# ==========================================================================
# Главное окно
# ==========================================================================



# ==========================================================================
# Системный трей (Shell_NotifyIcon через ctypes, без внешних зависимостей)
# ==========================================================================

class TrayIcon:
    """Иконка в системном трее Windows: меню по правому клику, скрытие/показ окна."""

    WM_APP = 0x8000
    WM_TRAYICON = WM_APP + 20
    WM_LBUTTONUP = 0x0202
    WM_RBUTTONUP = 0x0205
    WM_LBUTTONDBLCLK = 0x0203
    NIM_ADD = 0
    NIM_MODIFY = 1
    NIM_DELETE = 2
    NIF_MESSAGE = 0x01
    NIF_ICON = 0x02
    NIF_TIP = 0x04
    NIF_INFO = 0x10
    NIIF_INFO = 0x01

    def __init__(self, app, icon_path=None):
        self.app = app
        self.hwnd = None
        self._hinst = None
        self._hicon = None
        self._added = False
        self._menu_map = {}
        self._menu = None
        self.icon_path = icon_path
        self._cls_name = "OCMTrayWnd"
        self._wndproc_ref = None

    # --- регистрация окна ------------------------------------------------
    def install(self):
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            shell32 = ctypes.windll.shell32
            self._user32 = user32
            self._shell32 = shell32
            self._wintypes = wintypes
            self._hinst = kernel32.GetModuleHandleW(None)

            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM)
            # правильные прототипы, иначе lparam переполняется при передаче в DefWindowProc
            user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                              wintypes.WPARAM, wintypes.LPARAM]
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.RegisterClassW.argtypes = [ctypes.c_void_p]
            user32.RegisterClassW.restype = wintypes.ATOM
            user32.GetCursorPos.argtypes = [ctypes.c_void_p]
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                          wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                          wintypes.UINT]
            user32.LoadImageW.restype = wintypes.HANDLE
            user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
            user32.LoadIconW.restype = wintypes.HICON
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE

            def wnd_proc(hwnd, msg, wparam, lparam):
                try:
                    if msg == self.WM_TRAYICON:
                        low = int(lparam) & 0xFFFF
                        if low in (self.WM_RBUTTONUP,):
                            self._show_menu()
                            return 0
                        if low in (self.WM_LBUTTONUP, self.WM_LBUTTONDBLCLK):
                            self.app.root.after(0, self._on_left_click)
                            return 0
                    if msg == 0x0010:  # WM_CLOSE
                        return 0
                except Exception:
                    pass
                return int(user32.DefWindowProcW(hwnd, msg, wparam, lparam))

            self._wndproc_ref = WNDPROC(wnd_proc)

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [("style", wintypes.UINT),
                            ("lpfnWndProc", WNDPROC),
                            ("cbClsExtra", ctypes.c_int),
                            ("cbWndExtra", ctypes.c_int),
                            ("hInstance", wintypes.HINSTANCE),
                            ("hIcon", wintypes.HICON),
                            ("hCursor", wintypes.HANDLE),
                            ("hbrBackground", wintypes.HBRUSH),
                            ("lpszMenuName", wintypes.LPCWSTR),
                            ("lpszClassName", wintypes.LPCWSTR)]

            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc_ref
            wc.hInstance = self._hinst
            wc.lpszClassName = self._cls_name
            user32.RegisterClassW(ctypes.cast(ctypes.byref(wc), ctypes.c_void_p))

            self.hwnd = user32.CreateWindowExW(
                0, self._cls_name, "OCM Tray", 0, 0, 0, 0, 0,
                None, None, self._hinst, None)
            if not self.hwnd:
                return False

            # иконка: из .ico-файла, иначе стандартная
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE = 0x0040
            if self.icon_path and Path(self.icon_path).exists():
                self._hicon = user32.LoadImageW(None, str(self.icon_path),
                                                IMAGE_ICON, 0, 0,
                                                LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if not self._hicon:
                self._hicon = user32.LoadIconW(None, wintypes.LPCWSTR(32512))  # IDI_APPLICATION

            return self._add_icon()
        except Exception:
            return False

    def _add_icon(self):
        import ctypes
        from ctypes import wintypes

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD),
                        ("hWnd", wintypes.HWND),
                        ("uID", wintypes.UINT),
                        ("uFlags", wintypes.UINT),
                        ("uCallbackMessage", wintypes.UINT),
                        ("hIcon", wintypes.HICON),
                        ("szTip", wintypes.WCHAR * 128),
                        ("dwState", wintypes.DWORD),
                        ("dwStateMask", wintypes.DWORD),
                        ("szInfo", wintypes.WCHAR * 256),
                        ("uVersion", wintypes.UINT),
                        ("szInfoTitle", wintypes.WCHAR * 64),
                        ("dwInfoFlags", wintypes.DWORD)]

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        nid.uCallbackMessage = self.WM_TRAYICON
        nid.hIcon = self._hicon
        nid.szTip = "OpenCode — менеджер провайдеров"
        ok = bool(self._shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(nid)))
        self._nid = nid
        self._added = ok
        return ok

    def set_tooltip(self, text):
        if not self._added:
            return
        import ctypes
        self._nid.szTip = text[:127]
        self._nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        try:
            self._shell32.Shell_NotifyIconW(self.NIM_MODIFY, ctypes.byref(self._nid))
        except Exception:
            pass

    def notify(self, title, text):
        if not self._added:
            return
        import ctypes
        try:
            self._nid.uFlags = self.NIF_INFO
            self._nid.szInfoTitle = title[:63]
            self._nid.szInfo = text[:255]
            self._nid.dwInfoFlags = self.NIIF_INFO
            self._shell32.Shell_NotifyIconW(self.NIM_MODIFY, ctypes.byref(self._nid))
        except Exception:
            pass

    # --- действия ---------------------------------------------------------
    def _on_left_click(self):
        self.app.root.deiconify()
        self.app.root.lift()
        self.app.root.focus_force()

    def _show_menu(self):
        try:
            self.app.root.after(0, self._build_and_show_menu)
        except Exception:
            pass

    def _build_and_show_menu(self):
        import ctypes
        from ctypes import wintypes

        menu = tk.Menu(self.app.root, tearoff=0, bg=T.bg_panel_hi, fg=T.ink,
                       activebackground="#0b3547", activeforeground=T.cyan,
                       font=T.mono_small)
        menu.add_command(label="ОТКРЫТЬ", command=self._on_left_click)
        menu.add_separator()
        aos_on = bool(getattr(self.app, "aos", None) and self.app.aos.enabled)
        menu.add_command(label="AOS: " + ("ВЫКЛЮЧИТЬ" if aos_on else "ВКЛЮЧИТЬ"),
                         command=self.app.toggle_aos)
        menu.add_command(label="НАСТРОЙКИ AOS…", command=self.app.open_aos_settings)
        menu.add_separator()
        menu.add_command(label="ОБНОВИТЬ БАЛАНС", command=lambda: self.app.request_balance())
        menu.add_separator()
        menu.add_command(label="ВЫХОД", command=self.app.quit_app)

        x, y = self._cursor_pos()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()
        self._menu = menu

    def _cursor_pos(self):
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        ctypes.windll.user32.SetForegroundWindow(self.hwnd)
        return pt.x, pt.y

    def remove(self):
        if not getattr(self, "_added", False):
            return
        try:
            import ctypes
            self._shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(self._nid))
        except Exception:
            pass
        self._added = False


def find_icon_file():
    """Ищет opencode_manager.ico рядом с exe/скриптом (нужно и в собранном exe)."""
    candidates = []
    try:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
            candidates += [base / "opencode_manager.ico",
                           base / "_internal" / "opencode_manager.ico"]
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                candidates.append(Path(meipass) / "opencode_manager.ico")
        candidates.append(Path(__file__).resolve().parent / "opencode_manager.ico")
        candidates.append(Path.cwd() / "opencode_manager.ico")
    except Exception:
        pass
    for c in candidates:
        try:
            if c.exists():
                return c
        except Exception:
            continue
    return None


# ==========================================================================
# AOS — Always-On-Screen оверлей с балансом
# ==========================================================================

AOS_POSITIONS = [
    ("top-left", "СВЕРХУ СЛЕВА"),
    ("top-center", "СВЕРХУ ЦЕНТР"),
    ("top-right", "СВЕРХУ СПРАВА"),
    ("mid-left", "СЛЕВА ЦЕНТР"),
    ("mid-right", "СПРАВА ЦЕНТР"),
    ("bottom-left", "СНИЗУ СЛЕВА"),
    ("bottom-center", "СНИЗУ ЦЕНТР"),
    ("bottom-right", "СНИЗУ СПРАВА"),
]
AOS_PRESETS = {"compact": "КОМПАКТНЫЙ", "normal": "ОБЫЧНЫЙ", "wide": "ШИРОКИЙ"}


def aos_settings_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "OpenCodeProviderManager" / "aos.json"


def load_aos_settings() -> dict:
    path = aos_settings_path()
    defaults = {"enabled": False, "position": "top-right", "preset": "normal",
                "opacity": 0.92, "offset_x": 18, "offset_y": 18,
                "refresh_sec": 60, "show_profile": True, "show_coefficient": True}
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                defaults.update({k: v for k, v in data.items() if k in defaults})
    except Exception:
        pass
    return defaults


def save_aos_settings(settings: dict) -> None:
    path = aos_settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


class AOSOverlay:
    """Плавающее окно поверх всех окон: баланс выбранного провайдера."""

    def __init__(self, app):
        self.app = app
        self.settings = load_aos_settings()
        self.win = None
        self._after_id = None
        self._drag = {"x": 0, "y": 0}
        self._manual_pos = None

    @property
    def enabled(self):
        return bool(self.settings.get("enabled", False))

    def toggle(self, enabled=None):
        if enabled is None:
            enabled = not self.enabled
        self.settings["enabled"] = bool(enabled)
        save_aos_settings(self.settings)
        if enabled:
            self.show()
        else:
            self.hide()

    def show(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.apply_position()
            self.refresh()
            return
        self._create()

    def hide(self):
        if self._after_id and self.win is not None:
            try:
                self.win.after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = None
        if self.win is not None and self.win.winfo_exists():
            self.win.destroy()
        self.win = None

    def _create(self):
        w = tk.Toplevel(self.app.root)
        self.win = w
        try:
            w.title("")            # не показываемся в Alt+Tab / панели задач
        except Exception:
            pass
        w.overrideredirect(True)
        try:
            w.attributes("-topmost", True)
        except Exception:
            pass
        try:
            w.attributes("-alpha", float(self.settings.get("opacity", 0.92)))
        except Exception:
            pass
        w.bind("<Escape>", lambda e: self.toggle(False))
        self._build_content(w)
        self.apply_position()
        self.refresh()
        self._schedule_refresh()

    def _build_content(self, w):
        for child in w.winfo_children():
            child.destroy()
        preset = self.settings.get("preset", "normal")
        pad = 10 if preset == "compact" else 14
        if preset == "compact":
            font_big, font_small = ("Consolas", 12, "bold"), ("Consolas", 8)
        elif preset == "wide":
            font_big, font_small = ("Consolas", 16, "bold"), ("Consolas", 9)
        else:
            font_big, font_small = ("Consolas", 15, "bold"), ("Consolas", 9)

        w.configure(bg=T.bg)
        shell = tk.Frame(w, bg=T.bg)
        shell.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(shell, bg=T.bg, highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)
        body = tk.Frame(self._canvas, bg=T.panel_fill)
        self._win_id = self._canvas.create_window(0, 0, window=body, anchor="nw")

        top = tk.Frame(body, bg=T.panel_fill)
        top.pack(fill="x", padx=pad, pady=(pad, 2))
        tk.Label(top, text="AOS", bg=T.panel_fill, fg=T.cyan,
                 font=("Consolas", 10, "bold")).pack(side="left")
        self.lbl_state = tk.Label(top, text="", bg=T.panel_fill, fg=T.ink_dim,
                                  font=font_small)
        self.lbl_state.pack(side="left", padx=(8, 0))
        close = tk.Label(top, text="X", bg=T.panel_fill, fg=T.ink_dim, font=font_small,
                         cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.toggle(False))

        self.lbl_profile = tk.Label(body, text="", bg=T.panel_fill, fg=T.ink_dim,
                                    font=font_small, anchor="w")
        self.lbl_profile.pack(fill="x", padx=pad)
        self.lbl_value = tk.Label(body, text="—", bg=T.panel_fill, fg=T.green,
                                  font=font_big, anchor="w")
        self.lbl_value.pack(fill="x", padx=pad)
        self.lbl_est = tk.Label(body, text="", bg=T.panel_fill, fg=T.cyan_soft,
                                font=font_small, anchor="w")
        self.lbl_est.pack(fill="x", padx=pad)
        self.lbl_when = tk.Label(body, text="", bg=T.panel_fill, fg=T.ink_dim,
                                 font=font_small, anchor="w")
        self.lbl_when.pack(fill="x", padx=pad, pady=(0, pad))

        width = {"compact": 200, "wide": 360}.get(preset, 280)
        self.settings["_width"] = width
        body.update_idletasks()
        self._canvas.configure(width=width, height=max(70, body.winfo_reqheight()))
        self._draw_round(width, max(70, body.winfo_reqheight()))
        self._canvas.bind("<Configure>", lambda e: self._draw_round(e.width, e.height))

        def bind_all(widget):
            try:
                widget.bind("<Button-1>", self._start_drag, add="+")
                widget.bind("<B1-Motion>", self._drag_move, add="+")
                widget.bind("<ButtonRelease-1>", self._end_drag, add="+")
                widget.bind("<Button-3>", self._context_menu, add="+")
                widget.bind("<MouseWheel>", lambda e: self.refresh(), add="+")
            except Exception:
                pass
            for ch in widget.winfo_children():
                bind_all(ch)

        bind_all(w)
        bind_all(body)

    def _draw_round(self, w, h):
        c = self._canvas
        c.delete("bg")
        r = 16
        c.create_rectangle(r, 0, w - r, h, fill=T.panel_fill, outline="", tags="bg")
        c.create_rectangle(0, r, w, h - r, fill=T.panel_fill, outline="", tags="bg")
        for x1, y1, x2, y2, st in ((0, 0, 2 * r, 2 * r, 90), (w - 2 * r, 0, w, 2 * r, 0),
                                   (0, h - 2 * r, 2 * r, h, 180),
                                   (w - 2 * r, h - 2 * r, w, h, 270)):
            c.create_arc(x1, y1, x2, y2, start=st, extent=90, style="arc",
                         outline=T.cyan_dim, tags="bg")
        for x1, y1, x2, y2 in ((r, 0, w - r, 0), (r, h - 1, w - r, h - 1),
                               (0, r, 0, h - r), (w - 1, r, w - 1, h - r)):
            c.create_line(x1, y1, x2, y2, fill=T.cyan_dim, tags="bg")
        c.tag_lower("bg")
        c.coords(self._win_id, 0, 0)

    def apply_position(self):
        if self.win is None or not self.win.winfo_exists():
            return
        self.win.update_idletasks()
        ww = self.win.winfo_reqwidth()
        wh = self.win.winfo_reqheight()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        ox = int(self.settings.get("offset_x", 18))
        oy = int(self.settings.get("offset_y", 18))
        pos = self.settings.get("position", "top-right")
        if pos == "manual" and "manual_x" in self.settings:
            self.win.geometry("%+d%+d" % (int(self.settings["manual_x"]),
                                          int(self.settings["manual_y"])))
            return
        coords = {
            "top-left": (ox, oy),
            "top-center": ((sw - ww) // 2, oy),
            "top-right": (sw - ww - ox, oy),
            "mid-left": (ox, (sh - wh) // 2),
            "mid-right": (sw - ww - ox, (sh - wh) // 2),
            "bottom-left": (ox, sh - wh - oy - 40),
            "bottom-center": ((sw - ww) // 2, sh - wh - oy - 40),
            "bottom-right": (sw - ww - ox, sh - wh - oy - 40),
        }
        x, y = coords.get(pos, coords["top-right"])
        self.win.geometry("%+d%+d" % (int(x), int(y)))

    def _start_drag(self, event):
        try:
            self._drag["x"] = event.x_root - self.win.winfo_x()
            self._drag["y"] = event.y_root - self.win.winfo_y()
        except Exception:
            pass

    def _drag_move(self, event):
        try:
            self.win.geometry("%+d%+d" % (event.x_root - self._drag["x"],
                                          event.y_root - self._drag["y"]))
        except Exception:
            pass

    def _end_drag(self, event):
        try:
            self.settings["manual_x"] = self.win.winfo_x()
            self.settings["manual_y"] = self.win.winfo_y()
            self.settings["position"] = "manual"
            save_aos_settings(self.settings)
        except Exception:
            pass

    def set_position(self, key):
        self.settings["position"] = key
        save_aos_settings(self.settings)
        self.apply_position()

    def set_preset(self, key):
        self.settings["preset"] = key
        save_aos_settings(self.settings)
        if self.win is not None and self.win.winfo_exists():
            self._build_content(self.win)
            self.apply_position()
            self.refresh()

    def _context_menu(self, event):
        m = tk.Menu(self.win, tearoff=0, bg=T.bg_panel_hi, fg=T.ink,
                    activebackground="#0b3547", activeforeground=T.cyan,
                    font=T.mono_small)
        m.add_command(label="— ПОЛОЖЕНИЕ —", state="disabled")
        for key, title in AOS_POSITIONS:
            m.add_command(label=title, command=lambda k=key: self.set_position(k))
        m.add_separator()
        m.add_command(label="— РАЗМЕР —", state="disabled")
        for key, title in AOS_PRESETS.items():
            m.add_command(label=title, command=lambda k=key: self.set_preset(k))
        m.add_separator()
        m.add_command(label="ОБНОВИТЬ", command=self.refresh)
        m.add_command(label="ОТКРЫТЬ ОКНО",
                      command=lambda: (self.app.root.deiconify(), self.app.root.lift()))
        m.add_command(label="СКРЫТЬ AOS", command=lambda: self.toggle(False))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def refresh(self):
        profile = self.app._find(self.app.selected) if self.app.selected else None
        if not profile:
            try:
                self.lbl_profile.configure(text="нет профиля")
                self.lbl_value.configure(text="—", fg=T.ink_dim)
                self.lbl_est.configure(text="")
            except Exception:
                pass
            return
        data = profile.get("_balance")
        err = profile.get("_balance_error")
        try:
            self.lbl_state.configure(text="●", fg=T.green if data else T.red)
            if self.settings.get("show_profile", True):
                self.lbl_profile.configure(
                    text=str(profile.get("display_name") or profile["id"])[:28])
            if data:
                self.lbl_value.configure(text=data.get("text") or "—", fg=T.green)
                coef = str(profile.get("coefficient") or "").strip()
                est = coefficient_estimate(data.get("tokens"), coef) if (
                    coef and self.settings.get("show_coefficient", True)) else {}
                self.lbl_est.configure(
                    text=("≈ %s при к=%s" % (est["text"], coef)) if est else "")
                at = profile.get("_balance_at")
                self.lbl_when.configure(text=at.strftime("%H:%M:%S") if at else "")
            else:
                self.lbl_value.configure(text="—", fg=T.ink_dim)
                self.lbl_est.configure(text=self._fit_error(err))
                self.lbl_when.configure(text="")
        except Exception:
            pass

    def _fit_error(self, err):
        """Короткий текст ошибки, гарантированно влезающий по ширине."""
        if not err:
            return ""
        text = str(err).replace("\n", " ")
        # убираем техническую часть с URL — она длинная и не нужна на оверлее
        for sep in ("Проверено:", "Последние ошибки:", "Проверен"):
            if sep in text:
                text = text.split(sep)[0]
        text = text.strip().rstrip(".,;")
        # 280px панель, паддинги 28px, Consolas 9 ~7px/символ -> ~34 символа безопасно
        panel_w = int(self.settings.get("_width", 280))
        width = max(16, (panel_w - 32) // 7)
        if len(text) > width:
            text = text[:width - 1].rstrip() + "…"
        return text

    def _schedule_refresh(self):
        if self.win is None or not self.win.winfo_exists():
            return
        # баланс обновляется раз в минуту (минимум 60 секунд, чтобы не ловить 429)
        sec = max(60, int(self.settings.get("refresh_sec", 60)))
        try:
            self.app.request_balance(silent=True)
        except Exception:
            pass
        try:
            self._after_id = self.win.after(sec * 1000, self._tick)
        except Exception:
            pass

    def _tick(self):
        self._after_id = None
        self.refresh()
        self._schedule_refresh()



class AOSSettingsDialog(tk.Toplevel):
    """Настройки AOS-оверлея: положение на экране, размер, прозрачность, обновление."""

    def __init__(self, app, aos):
        super().__init__(app.root)
        self.app = app
        self.aos = aos
        self.title("НАСТРОЙКИ AOS")
        self.geometry("560x600")
        self.minsize(500, 540)
        self.configure(bg=T.bg)
        self.transient(app.root)
        self.grab_set()

        self.var_pos = tk.StringVar(value=aos.settings.get("position", "top-right"))
        self.var_preset = tk.StringVar(value=aos.settings.get("preset", "normal"))
        self.var_opacity = tk.DoubleVar(value=float(aos.settings.get("opacity", 0.92)))
        self.var_refresh = tk.IntVar(value=int(aos.settings.get("refresh_sec", 60)))
        self.var_profile = tk.BooleanVar(value=bool(aos.settings.get("show_profile", True)))
        self.var_coef = tk.BooleanVar(value=bool(aos.settings.get("show_coefficient", True)))
        self.var_enabled = tk.BooleanVar(value=bool(aos.settings.get("enabled", False)))

        self._build()
        self.bind("<Escape>", lambda e: self.destroy())
        try:
            app.clipboard.bind_tree(self)
        except Exception:
            pass

    def _build(self):
        head = tk.Frame(self, bg=T.bg)
        head.pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(head, text="AOS · ВСЕГДА НА ЭКРАНЕ", bg=T.bg, fg=T.cyan,
                 font=T.mono_title).pack(anchor="w")
        ScanStrip(self, color=T.cyan).pack(fill="x", padx=16, pady=(4, 8))

        # включение
        row = tk.Frame(self, bg=T.bg)
        row.pack(fill="x", padx=16, pady=4)
        tk.Checkbutton(row, text="ПОКАЗЫВАТЬ AOS", variable=self.var_enabled,
                       bg=T.bg, fg=T.ink, selectcolor=T.bg_input, activebackground=T.bg,
                       activeforeground=T.cyan, font=T.mono_small, bd=0,
                       command=self._toggle_enabled).pack(anchor="w")

        # положение — сетка 3x3, как на экране
        tk.Label(self, text="ПОЛОЖЕНИЕ НА ЭКРАНЕ", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w", padx=18, pady=(10, 2))
        grid = tk.Frame(self, bg=T.bg)
        grid.pack(padx=16)
        layout = [
            [("top-left", "СВЕРХУ\nСЛЕВА"), ("top-center", "СВЕРХУ\nЦЕНТР"), ("top-right", "СВЕРХУ\nСПРАВА")],
            [("mid-left", "СЛЕВА\nЦЕНТР"), None, ("mid-right", "СПРАВА\nЦЕНТР")],
            [("bottom-left", "СНИЗУ\nСЛЕВА"), ("bottom-center", "СНИЗУ\nЦЕНТР"), ("bottom-right", "СНИЗУ\nСПРАВА")],
        ]
        self._pos_buttons = {}
        for r, row_items in enumerate(layout):
            for c, item in enumerate(row_items):
                if item is None:
                    tk.Label(grid, text="·", bg=T.bg, fg=T.cyan_dim,
                             font=T.mono_small, width=12, height=3).grid(row=r, column=c, padx=3, pady=3)
                    continue
                key, title = item
                b = tk.Button(grid, text=title, bg=T.bg_panel_hi, fg=T.ink,
                              activebackground="#0b3547", activeforeground=T.cyan,
                              relief="flat", font=T.mono_small, width=12, height=3,
                              command=lambda k=key: self._choose_pos(k))
                b.grid(row=r, column=c, padx=3, pady=3)
                self._pos_buttons[key] = b
        self._refresh_pos_buttons()

        # размер
        tk.Label(self, text="РАЗМЕР", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w", padx=18, pady=(12, 2))
        sizes = tk.Frame(self, bg=T.bg)
        sizes.pack(fill="x", padx=16)
        for key, title in AOS_PRESETS.items():
            ttk.Radiobutton(sizes, text=title, value=key, variable=self.var_preset,
                            command=self._apply_live).pack(side="left", padx=(2, 12))

        # прозрачность
        tk.Label(self, text="ПРОЗРАЧНОСТЬ", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w", padx=18, pady=(12, 0))
        tk.Scale(self, from_=0.4, to=1.0, resolution=0.02, orient="horizontal",
                 variable=self.var_opacity, bg=T.bg, fg=T.ink, troughcolor=T.bg_input,
                 highlightthickness=0, font=T.mono_small, showvalue=True,
                 command=lambda v: self._apply_live()).pack(fill="x", padx=18)

        # частота обновления
        tk.Label(self, text="ОБНОВЛЯТЬ БАЛАНС", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w", padx=18, pady=(8, 2))
        freq = tk.Frame(self, bg=T.bg)
        freq.pack(fill="x", padx=16)
        for sec, title in ((60, "1 МИН"), (120, "2 МИН"), (300, "5 МИН"), (900, "15 МИН")):
            ttk.Radiobutton(freq, text=title, value=sec, variable=self.var_refresh,
                            command=self._apply_live).pack(side="left", padx=(2, 12))

        # что показывать
        tk.Label(self, text="СОДЕРЖИМОЕ", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w", padx=18, pady=(12, 2))
        opts = tk.Frame(self, bg=T.bg)
        opts.pack(fill="x", padx=16)
        ttk.Checkbutton(opts, text="имя профиля", variable=self.var_profile,
                        command=self._apply_live).pack(side="left", padx=(2, 16))
        ttk.Checkbutton(opts, text="пересчёт по коэффициенту", variable=self.var_coef,
                        command=self._apply_live).pack(side="left")

        # кнопки
        foot = tk.Frame(self, bg=T.bg)
        foot.pack(fill="x", padx=16, pady=(16, 14), side="bottom")
        ttk.Button(foot, text="ЗАКРЫТЬ", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(foot, text="ПРИМЕНИТЬ", style="Accent.TButton",
                   command=self._apply_and_close).pack(side="right", padx=4)
        ttk.Button(foot, text="СБРОСИТЬ ПОЛОЖЕНИЕ",
                   command=self._reset_position).pack(side="left", padx=4)

    # --- действия ---------------------------------------------------------
    def _toggle_enabled(self):
        self.aos.toggle(self.var_enabled.get())
        self.app._refresh_aos_button()

    def _choose_pos(self, key):
        self.var_pos.set(key)
        self.aos.set_position(key)
        self._refresh_pos_buttons()

    def _refresh_pos_buttons(self):
        cur = self.var_pos.get()
        for key, btn in self._pos_buttons.items():
            try:
                if key == cur:
                    btn.configure(bg="#0b3547", fg=T.cyan, relief="flat")
                else:
                    btn.configure(bg=T.bg_panel_hi, fg=T.ink)
            except Exception:
                pass

    def _reset_position(self):
        self._choose_pos("top-right")

    def _apply_live(self):
        s = self.aos.settings
        s["preset"] = self.var_preset.get()
        s["opacity"] = round(float(self.var_opacity.get()), 2)
        s["refresh_sec"] = max(60, int(self.var_refresh.get()))
        s["show_profile"] = bool(self.var_profile.get())
        s["show_coefficient"] = bool(self.var_coef.get())
        save_aos_settings(s)
        try:
            if self.aos.win is not None and self.aos.win.winfo_exists():
                self.aos.win.attributes("-alpha", s["opacity"])
        except Exception:
            pass
        if self.aos.win is not None and self.aos.win.winfo_exists():
            self.aos._build_content(self.aos.win)
            self.aos.apply_position()
            self.aos.refresh()

    def _apply_and_close(self):
        self._apply_live()
        self.app._refresh_aos_button()
        self.destroy()


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
        # AOS-оверлей: создаём лениво, но включаем, если так сохранено в настройках
        try:
            self.aos = AOSOverlay(self)
            if self.aos.enabled:
                self.root.after(600, self.aos.show)
        except Exception:
            self.aos = None
        # иконка в системном трее
        try:
            self.tray = TrayIcon(self, icon_path=find_icon_file())
            self.root.after(400, self._install_tray)
        except Exception:
            self.tray = None

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
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

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

        # путь к конфигу и кнопки — на одной сетке, кнопки выровнены по полю ввода
        path_box = tk.Frame(header, bg=T.bg)
        path_box.pack(side="left", fill="x", expand=True, padx=8)
        tk.Label(path_box, text="КОНФИГУРАЦИЯ", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).grid(row=0, column=0, columnspan=3, sticky="w")
        self.var_path = tk.StringVar(value=str(self.config_path))
        self.path_entry = ttk.Entry(path_box, textvariable=self.var_path, font=T.mono)
        self.path_entry.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        ttk.Button(path_box, text="ОТКРЫТЬ ПАПКУ",
                   command=self._open_folder).grid(row=1, column=1, padx=(8, 3), pady=(2, 0),
                                                   sticky="nsew")
        ttk.Button(path_box, text="ПЕРЕЗАГРУЗИТЬ",
                   command=self.load).grid(row=1, column=2, padx=(3, 2), pady=(2, 0),
                                           sticky="nsew")
        path_box.columnconfigure(0, weight=1)

        ScanStrip(root, color=T.cyan).pack(fill="x", padx=16, pady=(6, 0))

        body = tk.Frame(root, bg=T.bg)
        body.pack(fill="both", expand=True, padx=16, pady=8)

        # левая колонка
        left_panel = RoundedPanel(body, width=430, radius=20,
                                  fill=T.panel_fill, outline=T.panel_edge, thickness=1, bg=T.bg)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        left = left_panel.inner
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
        right_panel = RoundedPanel(body, radius=20, fill=T.panel_fill,
                                   outline=T.panel_edge, thickness=1, bg=T.bg)
        right_panel.pack(side="left", fill="both", expand=True)
        right = right_panel.inner
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
        ttk.Button(row2, text="ЭКСПОРТ ВСЕХ ПРОФИЛЕЙ…",
                   command=self.export_profile).pack(side="left", padx=3)
        ttk.Button(row2, text="ИМПОРТ ПРОФИЛЕЙ…",
                   command=self.import_profile).pack(side="left", padx=3)
        self.btn_aos = ttk.Button(row2, text="AOS: ВЫКЛ",
                                  command=self.toggle_aos)
        self.btn_aos.pack(side="left", padx=(12, 3))
        ttk.Button(row2, text="НАСТРОЙКИ AOS…",
                   command=self.open_aos_settings).pack(side="left", padx=3)
        ttk.Button(row2, text="В ТРЕЙ",
                   command=self.minimize_to_tray).pack(side="left", padx=(12, 3))
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
    def request_balance(self, silent=False):
        if not hasattr(self, "_balance_results"):
            self._balance_results = queue.Queue()
        profile = self._find(self.selected) if self.selected else None
        if not profile:
            if not silent:
                messagebox.showinfo("Баланс", "Выберите профиль в списке", parent=self.root)
            return
        if not silent:
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
            self._log_balance_error(str(err))
            try:
                aos = getattr(self, "aos", None)
                if aos is not None and aos.win is not None and aos.win.winfo_exists():
                    aos.refresh()
            except Exception:
                pass
            return
        profile["_balance"] = data
        profile["_balance_error"] = None
        profile["_balance_at"] = datetime.now()
        if pid == self.selected:
            self._show_balance(profile)
            # AOS тоже должен обновиться сразу после запроса
            try:
                aos = getattr(self, "aos", None)
                if aos is not None and aos.win is not None and aos.win.winfo_exists():
                    aos.refresh()
            except Exception:
                pass
        if err is not None and "429" in str(err):
            # слишком частые запросы: не повторяем сразу, ждём следующий цикл AOS
            return
        if not profile.get("_balance") and not profile.get("_balance_tried"):
            profile["_balance_tried"] = True
            self.root.after(250, self.request_balance)

    def _log_balance_error(self, text):
        """Пишет ошибку баланса в файл рядом с aos.json — для диагностики в собранном exe."""
        try:
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
            d = base / "OpenCodeProviderManager"
            d.mkdir(parents=True, exist_ok=True)
            log = d / "balance_error.log"
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log, "a", encoding="utf-8") as fh:
                fh.write("[%s] %s\n" % (stamp, text))
        except Exception:
            pass

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

    # --- трей ---------------------------------------------------------------
    def _install_tray(self):
        tray = getattr(self, "tray", None)
        if tray is None:
            return
        try:
            ok = tray.install()
            self._tray_ok = bool(ok)
            if ok:
                self._set_status(self.status.cget("text") + "   •   в трее")
        except Exception:
            self._tray_ok = False

    def minimize_to_tray(self):
        """Свернуть окно в трей (окно скрывается, процесс живёт)."""
        tray = getattr(self, "tray", None)
        if tray is None or not getattr(self, "_tray_ok", False):
            self.root.iconify()
            return
        self.root.withdraw()
        try:
            tray.notify("OpenCode — менеджер провайдеров",
                        "Приложение свёрнуто в трей. Двойной клик — открыть.")
        except Exception:
            pass

    def quit_app(self):
        """Полный выход: убрать иконку из трея и закрыть приложение."""
        tray = getattr(self, "tray", None)
        if tray is not None:
            try:
                tray.remove()
            except Exception:
                pass
        try:
            aos = getattr(self, "aos", None)
            if aos is not None:
                aos.hide()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _on_window_close(self):
        """Крестик: прячем в трей. Выход — через меню трея «ВЫХОД»."""
        tray = getattr(self, "tray", None)
        if tray is not None and getattr(self, "_tray_ok", False):
            self.minimize_to_tray()
        else:
            self.quit_app()

    # --- AOS ---------------------------------------------------------------
    def _aos(self):
        if getattr(self, "aos", None) is None:
            try:
                self.aos = AOSOverlay(self)
            except Exception:
                self.aos = None
        return self.aos

    def toggle_aos(self, enabled=None):
        aos = self._aos()
        if aos is None:
            return
        aos.toggle(enabled)
        self._refresh_aos_button()
        self._set_status("AOS ВКЛЮЧЁН" if aos.enabled else "AOS ВЫКЛЮЧЕН")

    def _refresh_aos_button(self):
        btn = getattr(self, "btn_aos", None)
        aos = getattr(self, "aos", None)
        if btn is None:
            return
        try:
            on = bool(aos and aos.enabled)
            btn.configure(text="AOS: ВКЛ" if on else "AOS: ВЫКЛ",
                          style="Accent.TButton" if on else "TButton")
        except Exception:
            pass

    def open_aos_settings(self):
        aos = self._aos()
        if aos is None:
            messagebox.showerror("AOS", "Не удалось создать оверлей", parent=self.root)
            return
        AOSSettingsDialog(self, aos)

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
        if not self.profiles:
            messagebox.showinfo("Экспорт профилей", "Список профилей пуст — нечего сохранять",
                                parent=self.root)
            return
        data = build_export_payload(self.profiles, self.var_default_model.get())
        default_dir = str(Path.home() / "Downloads")
        name = filedialog.asksaveasfilename(
            parent=self.root, title="Экспорт всех профилей моделей", defaultextension=".json",
            initialdir=default_dir if Path(default_dir).is_dir() else str(Path.home()),
            initialfile="opencode-profiles.json",
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
        self._set_status("ЭКСПОРТИРОВАНО ПРОФИЛЕЙ: %d → %s" % (len(data["profiles"]), path))
        messagebox.showinfo(
            "Экспорт",
            "Сохранено профилей: %d\n\nФайл:\n%s\n\nРазмер: %d байт" % (
                len(data["profiles"]), path, path.stat().st_size), parent=self.root)

    def import_profile(self):
        default_dir = str(Path.home() / "Downloads")
        name = filedialog.askopenfilename(
            parent=self.root, title="Импорт профилей",
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
        try:
            imported, default_model = profiles_from_export(raw)
        except ValueError as exc:
            messagebox.showerror("Импорт", "%s\n\nФайл: %s" % (exc, src), parent=self.root)
            return
        existing = [p["id"] for p in imported if self._find(p["id"]) is not None]
        if existing:
            if not messagebox.askyesno(
                    "Импорт",
                    "Уже есть профили с такими ID:\n%s\n\nЗаменить их?" % ", ".join(existing),
                    parent=self.root):
                return
        added = replaced = 0
        for profile in imported:
            current = self._find(profile["id"])
            if current is not None:
                self.profiles[self.profiles.index(current)] = profile
                replaced += 1
            else:
                self.profiles.append(profile)
                added += 1
        if default_model:
            self.var_default_model.set(default_model)
        self.selected = imported[0]["id"]
        self._render_list()
        self._set_status("ИМПОРТИРОВАНО ПРОФИЛЕЙ: %d (новых %d, заменено %d) — НЕ СОХРАНЁН"
                         % (len(imported), added, replaced))
        messagebox.showinfo(
            "Импорт",
            "Импортировано профилей: %d\nНовых: %d\nЗаменено: %d\n\n"
            "Не забудьте «ПРИМЕНИТЬ К КОНФИГУ»." % (len(imported), added, replaced),
            parent=self.root)

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
