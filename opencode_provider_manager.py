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
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
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
    "@opencode/ai/providers/openai-compatible",
    "@ai-sdk/openai-compatible",
    "@ai-sdk/openai",
    "@ai-sdk/anthropic",
    "@ai-sdk/google",
]

#: Возможности модели, которые пользователь включает галочками. Значение —
#: подпись в интерфейсе; ключ пишется в `capabilities` модели в opencode.json
#: (и читается из него при загрузке). `output` в OpenCode — список типов,
#: поэтому «веб» записывается строкой "web", как это делает models.dev.
CAPABILITY_KEYS = (
    ("tools", "ИНСТРУМЕНТЫ (TOOLS)"),
    ("vision", "ВИДИТ ИЗОБРАЖЕНИЯ (VISION)"),
    ("audio", "ВИДИТ/СЛЫШИТ АУДИО"),
    ("video", "ВИДИТ ВИДЕО"),
    ("web", "ВЕБ-ПОИСК"),
    ("reasoning", "РАССУЖДЕНИЯ (REASONING)"),
    ("temperature", "ТЕМПЕРАТУРА"),
    ("attachment", "ВЛОЖЕНИЯ"),
)

CAPABILITY_LABELS = dict(CAPABILITY_KEYS)

#: Одноимённые ключи модели (не в capabilities), которые дописываются, когда
#: галочка стоит. Если галочка снята — ключ удаляется. `null` — ключ не нужен.
#:
#: ВЛОЖЕНИЯ намеренно не пишутся в модель ключом `attachment`: официальная
#: схема OpenCode (Config.ModelEncoded, additionalProperties: false) такого
#: ключа у модели не знает, и конфиг становится невалидным. Вложить файл
#: в модель можно, только если у неё есть типы входа image/audio/video —
#: то есть через галочки VISION/АУДИО/ВИДЕО. Галочка ВЛОЖЕНИЯ управляет
#: той же тройкой и записывается туда единым образом.
CAPABILITY_EXTRAS = {
    "attachment": None,
}


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
        capabilities = {}
        for mid, spec in models_spec.items():
            known.append(mid)
            if isinstance(spec, dict):
                capabilities[mid] = _capability_flags_from_spec(spec)
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
            "model_capabilities": capabilities,
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


def _capability_flags_from_spec(spec) -> dict:
    """Что известно о возможностях модели в конфиге -> флаги для галочек."""
    flags = {}
    spec = spec if isinstance(spec, dict) else {}
    caps = spec.get("capabilities") if isinstance(spec.get("capabilities"), dict) else {}
    if isinstance(caps.get("tools"), bool):
        flags["tools"] = caps["tools"]
    inputs = capabilities_inputs(spec)
    flags["vision"] = "image" in inputs
    flags["audio"] = "audio" in inputs
    flags["video"] = "video" in inputs
    outputs = caps.get("output")
    if isinstance(outputs, str):
        outputs = outputs.split()
    outputs = [str(x) for x in outputs] if isinstance(outputs, list) else []
    flags["web"] = "web" in outputs
    reasoning = caps.get("reasoning")
    if isinstance(reasoning, dict):
        # нет явного supported — значит, описан только набор effort: это
        # всё равно включает рассуждения
        flags["reasoning"] = bool(reasoning.get("supported", True))
    elif isinstance(reasoning, bool):
        flags["reasoning"] = reasoning
    flags["temperature"] = caps.get("temperature") is not False
    # «вложения» = модели можно отдать файл (картинку/аудио/видео).
    flags["attachment"] = any(k in inputs for k in ("image", "audio", "video"))
    return flags


def capabilities_inputs(spec) -> list:
    """Типы входа модели: `capabilities.input` строкой или списком."""
    caps = spec.get("capabilities") if isinstance(spec, dict) else None
    caps = caps if isinstance(caps, dict) else {}
    value = caps.get("input")
    if isinstance(value, str):
        value = value.split()
    if not isinstance(value, list):
        return ["text"]
    return [str(x) for x in value] or ["text"]


def model_supports_vision(spec, discovery=None) -> bool:
    """Видит ли модель картинки: по конфигу, иначе по данным провайдера."""
    if isinstance(spec, dict) and spec.get("capabilities") is not None:
        return "image" in capabilities_inputs(spec)
    return bool((discovery or {}).get("vision"))


def profile_model_vision(profile, mid) -> bool:
    """Видит ли модель картинки по профилю менеджера (галочки или конфиг)."""
    flags = (profile.get("model_capabilities") or {}).get(mid) or {}
    if "vision" in flags:
        return bool(flags.get("vision"))
    raw_models = (profile.get("_raw") or {}).get("models") or {}
    existing = raw_models.get(mid) if isinstance(raw_models, dict) else None
    return model_supports_vision(existing)


def model_capabilities(model: dict, existing=None) -> dict:
    """Флаги возможностей для галочек: явное значение из конфига, иначе
    предположение (инструменты есть, картинки — если провайдер так сказал)."""
    flags = _capability_flags_from_spec(existing)
    if not flags:
        return {
            "tools": True,
            "vision": bool(model.get("vision")),
            "audio": False,
            "video": False,
            "web": False,
            "reasoning": False,
            "temperature": False,
            "attachment": bool(model.get("vision")),
        }
    return flags


def _apply_capabilities(spec: dict, flags) -> dict:
    """Пишет выбранные галочки в `capabilities` модели.

    Всё, что понимает OpenCode, живёт внутри `capabilities`:
    tools/input/output/reasoning/temperature. Ключа `attachment` у модели нет —
    вложить файл можно только через типы входа, поэтому галочка ВЛОЖЕНИЯ
    дописывает image/audio/video к уже выбранным (сама типы не убирает).
    """
    flags = flags if isinstance(flags, dict) else {}
    caps = spec.get("capabilities")
    caps = copy.deepcopy(caps) if isinstance(caps, dict) else {}
    # мусор из старых версий: невалидные для схемы OpenCode ключи модели
    spec.pop("attachment", None)

    if flags.get("tools") is not None:
        caps["tools"] = bool(flags.get("tools"))
    caps.setdefault("tools", True)

    current = caps.get("input") if isinstance(caps.get("input"), list) else []
    attachment_on = bool(flags.get("attachment"))
    inputs = []
    for key, kind in (("vision", "image"), ("audio", "audio"), ("video", "video")):
        if flags.get(key) is None:
            # галочки нет — оставляем как было в конфиге
            wanted = kind in current
        else:
            wanted = bool(flags.get(key))
        if attachment_on:
            wanted = True
        if wanted:
            inputs.append(kind)
    caps["input"] = ["text"] + inputs

    outputs = caps.get("output")
    if isinstance(outputs, str):
        outputs = outputs.split()
    outputs = [str(x) for x in outputs] if isinstance(outputs, list) else ["text"]
    was_web = "web" in outputs
    outputs = [x for x in outputs if x != "web"]
    if flags.get("web") is None:
        if was_web:
            outputs.append("web")
    elif flags.get("web"):
        outputs.append("web")
    caps["output"] = outputs or ["text"]

    if flags.get("reasoning") is not None:
        want = bool(flags.get("reasoning"))
        current = caps.get("reasoning")
        if isinstance(current, dict):
            if want:
                current["supported"] = True
            else:
                # выключено = возможностей рассуждений нет вовсе; отдельная
                # запись supported:false вызывает у OpenCode сомнения при
                # разборе, поэтому ключ убираем целиком
                caps.pop("reasoning", None)
        elif want:
            caps["reasoning"] = {"supported": True}
        else:
            caps.pop("reasoning", None)
    if flags.get("temperature") is not None:
        caps["temperature"] = bool(flags.get("temperature"))

    spec["capabilities"] = caps
    return spec


def model_spec(model: dict, existing=None, flags=None) -> dict:
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
    if flags is None:
        # галочек нет (профиль из старого файла): не теряем старые значения,
        # а новые подхватываем из ответа провайдера, как раньше
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
    return _apply_capabilities(spec, flags)


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


def is_chat_completions_package(package) -> bool:
    """Пакет, в котором `settings.apiKey` реально передаётся в запрос."""
    return "openai-compatible" in (package or "").lower()


def _env_key(pid: str) -> str:
    """Имя переменной с ключом профиля (providers.<id>.env)."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", str(pid)).strip("_").upper() or "PROVIDER"
    return "OPENCODE_%s_API_KEY" % safe


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
    if not is_chat_completions_package(proxy["package"]):
        # Только openai-compatible отправляет settings.apiKey в запрос. Другие
        # пакеты (openai, anthropic, google) берут ключ из окружения — иначе
        # OpenCode отвечает «API key is required». Отдаём ключ через env.
        env_name = _env_key(profile.get("id") or "")
        proxy["env"] = [env_name]
        settings["apiKey"] = "{env:%s}" % env_name
        os.environ[env_name] = profile["api_key"]
    if settings:
        proxy["settings"] = settings
    else:
        proxy.pop("settings", None)
    old_models = proxy.get("models") if isinstance(proxy.get("models"), dict) else {}
    flags_by_model = profile.get("model_capabilities") or {}
    models = {}
    for mid in profile.get("models") or []:
        models[mid] = model_spec({"id": mid}, old_models.get(mid),
                                 flags_by_model.get(mid))
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


def migrate_provider_keys(config: dict) -> list:
    """Лечит профили, созданные версией, которая выбирала пакет
    `@ai-sdk/openai` (ключ из `settings.apiKey` там не читается).

    Возвращает список ID исправленных провайдеров.
    """
    fixed = []
    providers = config.get("providers") if isinstance(config, dict) else None
    if not isinstance(providers, dict):
        return fixed
    for pid, proxy in providers.items():
        if not isinstance(proxy, dict):
            continue
        if is_chat_completions_package(proxy.get("package")):
            continue
        settings = proxy.get("settings")
        settings = settings if isinstance(settings, dict) else {}
        key = settings.get("apiKey") or ""
        if not key.startswith("sk-cvc-"):
            continue
        proxy["package"] = "@opencode/ai/providers/openai-compatible"
        env_name = _env_key(pid)
        proxy["env"] = [env_name]
        settings["apiKey"] = "{env:%s}" % env_name
        os.environ[env_name] = key
        proxy["settings"] = settings
        fixed.append(pid)
    return fixed


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
EXPORT_VERSION = 3
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
        "model_capabilities": copy.deepcopy(profile.get("model_capabilities") or {}),
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
    caps = raw.get("model_capabilities")
    caps = copy.deepcopy(caps) if isinstance(caps, dict) else {}
    return {
        "id": pid,
        "display_name": raw.get("display_name") or pid,
        "coefficient": str(raw.get("coefficient") or ""),
        "base_url": raw.get("base_url") or "",
        "api_key": raw.get("api_key") or "",
        "package": raw.get("package") or PACKAGES[0],
        "models": models,
        "known_models": known,
        "model_capabilities": caps,
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
# Перенос профилей в ИИ-агентов
# ==========================================================================
#
# Профили (URL + ключ + модели) уже настроены в OpenCode. Здесь их можно
# одной кнопкой перенести в конфиги других ИИ-агентов: VS Code (расширение
# opencode-lm читает тот же opencode.json), Cline, Continue, Codex CLI,
# Claude Code, Aider. Ручная правка конфигов не нужна.

AGENT_IDS = ("opencode", "vscode", "cline", "continue", "codex", "claude", "aider", "dsh")

AGENTS_FILE_NAME = "agents.json"

#: Пункты, которые мы дописываем в чужие конфиги: их можно безопасно
#: перезаписывать, не задевая остальные настройки пользователя.
CONTINUE_ROLES = ["chat", "edit", "apply"]

VSCODE_EXT_ID = "local.opencode-lm"


def merge_profiles_into_config(config: dict, profiles: list) -> dict:
    """Аккуратно дописывает профили в конфиг, НЕ трогая остальные.

    Нужна для переноса в агентов: там пользователь отмечает произвольный
    поднабор профилей, и стирать непереданные провайдеры или помечать их
    модели `disabled` нельзя. Остальные провайдеры, их модели, mcp, agent,
    skills и прочие ключи остаются как были.
    """
    new = copy.deepcopy(config)
    providers = new.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        new["providers"] = providers
    for profile in profiles:
        pid = profile.get("id")
        if not pid:
            continue
        existing = providers.get(pid) if isinstance(providers.get(pid), dict) else {}
        raw = profile.get("_raw")
        # основа — то, что уже лежит в конфиге; поверх кладём «сырой» объект
        # профиля, но модели объединяем, а не заменяем
        base = copy.deepcopy(existing)
        if isinstance(raw, dict):
            for key, value in raw.items():
                if key == "models":
                    continue
                base[key] = copy.deepcopy(value)
            raw_models = raw.get("models")
            if isinstance(raw_models, dict):
                merged = raw_models if isinstance(base.get("models"), dict) else {}
                for mid, spec in base.get("models", {}).items():
                    merged.setdefault(mid, spec)
                base["models"] = merged
        settings = {}
        base_url = normalize_base_url(profile.get("base_url", ""))
        if base_url:
            settings["baseURL"] = base_url
        if profile.get("api_key"):
            settings["apiKey"] = profile["api_key"]
        for key, value in (profile.get("extra_settings") or {}).items():
            settings[key] = value
        base["name"] = profile.get("display_name") or pid
        base["package"] = profile.get("package") or PACKAGES[0]
        env_name = ""
        if not is_chat_completions_package(base["package"]):
            # пакет не читает settings.apiKey — ключ уходит через окружение
            env_name = _env_key(pid)
            base["env"] = [env_name]
            settings["apiKey"] = "{env:%s}" % env_name
            if profile.get("api_key"):
                os.environ[env_name] = profile["api_key"]
        elif env_name and base.get("env") == [env_name]:
            base.pop("env", None)
        if settings:
            base["settings"] = settings
        coef = str(profile.get("coefficient") or "").strip()
        if coef:
            base["_coefficient"] = coef
        # модели: отмеченные добавляем/включаем, остальные НЕ трогаем.
        # Скрывать чужие модели здесь нельзя: перенос не должен менять то,
        # что пользователь не выбирал (иначе пропадали модели из OpenCode).
        old_models = base.get("models") if isinstance(base.get("models"), dict) else {}
        old_models = dict(old_models) if isinstance(old_models, dict) else {}
        flags_by_model = profile.get("model_capabilities") or {}
        for mid in list(profile.get("models") or []):
            spec = model_spec({"id": mid}, old_models.get(mid),
                              flags_by_model.get(mid))
            spec.pop("disabled", None)
            old_models[mid] = spec
        if old_models:
            base["models"] = old_models
        providers[pid] = base
    return new


def agents_settings_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "OpenCodeProviderManager" / AGENTS_FILE_NAME


def load_agents_settings() -> dict:
    """Сохранённый выбор агентов и профилей (переживает перезапуск)."""
    defaults = {"agents": [], "profiles": []}
    try:
        path = agents_settings_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                for key in defaults:
                    if key in data:
                        defaults[key] = data[key]
    except Exception:
        pass
    return defaults


def save_agents_settings(settings: dict) -> None:
    try:
        path = agents_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: settings.get(key) for key in ("agents", "profiles")}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _home_dir(home=None) -> Path:
    return Path(home) if home else Path(os.path.expanduser("~"))


def vscode_user_dir(home=None) -> Path:
    if home:
        return _home_dir(home) / "AppData" / "Roaming" / "Code" / "User"
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else _home_dir() / "AppData" / "Roaming"
    return base / "Code" / "User"


def vscode_settings_path(home=None) -> Path:
    return vscode_user_dir(home) / "settings.json"


def vscode_extensions_dir(home=None) -> Path:
    """Каталог расширений VS Code (stable)."""
    return _home_dir(home) / ".vscode" / "extensions"


def vscode_lm_source_dir(home=None) -> Path:
    """Исходники расширения opencode-lm (если лежат рядом с домашней папкой)."""
    return _home_dir(home) / "opencode-lm-vscode"


def continue_config_path(home=None) -> Path:
    return _home_dir(home) / ".continue" / "config.yaml"


def codex_config_path(home=None) -> Path:
    return _home_dir(home) / ".codex" / "config.toml"


def claude_settings_path(home=None) -> Path:
    return _home_dir(home) / ".claude" / "settings.json"


def aider_config_path(home=None) -> Path:
    return _home_dir(home) / ".aider.conf.yml"


def cline_providers_path(home=None) -> Path:
    """Cline хранит провайдеров в ~/.cline/data/settings/providers.json."""
    return _home_dir(home) / ".cline" / "data" / "settings" / "providers.json"


def cline_models_path(home=None) -> Path:
    return cline_providers_path(home).parent / "models.json"


def cline_dir(home=None) -> Path:
    return _home_dir(home) / ".cline"


def dsh_profile_dir(home=None) -> Path:
    """Каталог профиля DeepSeek Harness (dsh)."""
    return _home_dir(home) / ".dsh" / "profiles" / "desktop"


def dsh_patch_path(home=None) -> Path:
    """Патч-слой, где лежат провайдеры: cordis.patch.yml."""
    return dsh_profile_dir(home) / "cordis.patch.yml"


def dsh_credentials_path(home=None) -> Path:
    """Сюда dsh пишет API-ключи (refs.<ENV_NAME>)."""
    return _home_dir(home) / ".dsh" / ".credentials.yaml"


def agent_catalog(home=None, config_path=None) -> list:
    """Список ИИ-агентов для диалога переноса (порядок = AGENT_IDS)."""
    home = _home_dir(home)
    config = _resolve_config_path(config_path, home)
    items = [
        {
            "id": "opencode",
            "title": "OpenCode (этот конфиг)",
            "path": config,
            "kind": "config",
            "description": "Записать профили в opencode.json — тот же файл читают OpenCode и расширения VS Code.",
        },
        {
            "id": "vscode",
            "title": "VS Code (чат-модели)",
            "path": config,
            "kind": "config",
            "description": "Поставить расширение OpenCode LM и подключить его к этому же конфигу — профили появятся в пикере моделей VS Code.",
            "extension": VSCODE_EXT_ID,
        },
        {
            "id": "cline",
            "title": "Cline (VS Code, ~/.cline)",
            "path": cline_providers_path(home),
            "kind": "config",
            "description": "Прописать профили в providers.json Cline (openai-compatible) и models.json.",
        },
        {
            "id": "continue",
            "title": "Continue (.continue/config.yaml)",
            "path": continue_config_path(home),
            "kind": "config",
            "description": "Дописать модели как openai-совместимые провайдеры Continue.",
        },
        {
            "id": "codex",
            "title": "Codex CLI (~/.codex/config.toml)",
            "path": codex_config_path(home),
            "kind": "config",
            "description": "Добавить блоки [model_providers.*] и bearer-токены.",
        },
        {
            "id": "claude",
            "title": "Claude Code (~/.claude/settings.json)",
            "path": claude_settings_path(home),
            "kind": "config",
            "description": "Прописать ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_MODEL.",
        },
        {
            "id": "aider",
            "title": "Aider (~/.aider.conf.yml)",
            "path": aider_config_path(home),
            "kind": "config",
            "description": "openai-api-base, openai-api-key и модель по умолчанию.",
        },
        {
            "id": "dsh",
            "title": "DeepSeek Harness (~/.dsh)",
            "path": dsh_patch_path(home),
            "kind": "config",
            "description": "Провайдеры в cordis.patch.yml (llm-pi-ai) и ключи в .credentials.yaml.",
        },
    ]
    catalog = []
    for item in items:
        entry = dict(item)
        if entry["id"] == "vscode":
            entry["exists"] = _vscode_extension_installed(home)
        else:
            entry["exists"] = Path(entry["path"]).exists()
        catalog.append(entry)
    return catalog


def _backup_file(path: Path):
    """Копия файла перед изменением. Возвращает путь копии или None."""
    try:
        if not path.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        dest = path.with_name("%s.bak-%s" % (path.name, stamp))
        shutil.copy2(path, dest)
        return dest
    except Exception:
        return None


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return ""


def _yaml_available() -> bool:
    try:
        import yaml  # noqa: F401
        return True
    except Exception:
        return False


def _load_yaml_doc(text: str) -> dict:
    """Разбирает YAML. Без PyYAML — считаем, что файла нет."""
    if not text.strip():
        return {}
    try:
        import yaml
    except Exception:
        return {}
    try:
        data = yaml.safe_load(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _dump_yaml_doc(data: dict) -> str:
    """YAML через PyYAML; если его нет — минимальный YAML руками.

    Ручная запись безопасна только для файлов, которые мы создаём сами:
    разбор существующего файла требует PyYAML (см. _require_yaml).
    """
    try:
        import yaml
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                              default_flow_style=False)
    except Exception:
        return _dump_minimal_yaml(data)


def _dump_minimal_yaml(data: dict) -> str:
    lines = []
    for key, value in data.items():
        if isinstance(value, list):
            if not value:
                lines.append("%s: []" % key)
                continue
            lines.append("%s:" % key)
            for item in value:
                if not isinstance(item, dict):
                    lines.append("  - %s" % json.dumps(item, ensure_ascii=False))
                    continue
                first = True
                for sub_key, sub_value in item.items():
                    prefix = "  - " if first else "    "
                    first = False
                    if isinstance(sub_value, list):
                        lines.append("%s%s:" % (prefix, sub_key))
                        for sub_item in sub_value:
                            lines.append("      - %s" % sub_item)
                    else:
                        lines.append("%s%s: %s" % (
                            prefix, sub_key,
                            json.dumps(sub_value, ensure_ascii=False)))
            continue
        lines.append("%s: %s" % (key, json.dumps(value, ensure_ascii=False)))
    return "\n".join(lines) + "\n"


def _require_yaml(text: str, path: Path) -> dict:
    """Разбор YAML для правки существующего файла.

    Если PyYAML нет, а файл непустой — лучше отказаться, чем затереть чужие
    настройки: в отчёте будет понятная ошибка.
    """
    if not text.strip():
        return {}
    if not _yaml_available():
        raise RuntimeError(
            "нужен PyYAML, чтобы не затереть %s — установите: pip install pyyaml" % path)
    data = _load_yaml_doc(text)
    if not data:
        raise RuntimeError("%s не разбирается как YAML — файл не тронут" % path)
    return data


def _require_yaml_any(text: str, path: Path, default):
    """Разбор YAML, где корень может быть списком (cordis.patch.yml).

    default — что вернуть для пустого/отсутствующего файла.
    """
    if not text.strip():
        return default
    if not _yaml_available():
        raise RuntimeError(
            "нужен PyYAML, чтобы не затереть %s — установите: pip install pyyaml" % path)
    try:
        import yaml
        data = yaml.safe_load(text)
    except Exception as exc:
        raise RuntimeError("%s не разбирается как YAML: %s" % (path, exc))
    if data is None:
        return default
    if not isinstance(data, (dict, list)):
        raise RuntimeError("%s: неожиданный корень YAML — файл не тронут" % path)
    return data


def _dump_yaml_any(data) -> str:
    """YAML для словаря ИЛИ списка (списком является cordis.patch.yml)."""
    try:
        import yaml
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                              default_flow_style=False)
    except Exception:
        if isinstance(data, dict):
            return _dump_minimal_yaml(data)
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _profiles_for_transfer(profiles, ids=None) -> list:
    if not ids:
        return [p for p in profiles if p.get("base_url")]
    wanted = set(ids)
    return [p for p in profiles if p.get("id") in wanted and p.get("base_url")]


def _pick_primary(profiles, default_model=""):
    """Профиль, который станет «моделью по умолчанию» у агента с одной моделью."""
    if not profiles:
        return None
    pid = parse_model_ref(default_model)[0]
    if pid:
        for profile in profiles:
            if profile.get("id") == pid:
                return profile
    for profile in profiles:
        if profile.get("models"):
            return profile
    return profiles[0]


def _primary_model(profile, default_model="") -> str:
    models = list((profile or {}).get("models") or [])
    pid, mid = parse_model_ref(default_model)
    if profile and pid == profile.get("id") and mid in models:
        return mid
    return models[0] if models else ""


def _provider_kind(package: str, base_url: str = "") -> str:
    package = (package or "").lower()
    if "anthropic" in package:
        return "anthropic"
    if "google" in package or "gemini" in package:
        return "gemini"
    if "openai" in package:
        return "openai"
    return "openai"


def _toml_quote(value) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _resolve_config_path(config_path, home=None) -> Path:
    """Путь к opencode.json: явный, затем <home>/.config/opencode, затем реальный."""
    if config_path:
        return Path(config_path)
    if home is not None:
        return _home_dir(home) / ".config" / "opencode" / "opencode.json"
    return default_config_path()


def _transfer_opencode(profiles, default_model, config_path=None, home=None):
    """Дописывает профили в opencode.json, не затирая остальные провайдеры."""
    path = Path(config_path) if config_path else _resolve_config_path(None, home)
    config = load_config(path)
    new_config = merge_profiles_into_config(config, profiles)
    ref = (default_model or "").strip()
    if ref and ref != "(не задана)":
        new_config["model"] = ref
    backup = save_config(path, new_config)
    return {
        "agent": "opencode", "title": "OpenCode (этот конфиг)", "ok": True,
        "path": path, "backup": backup,
        "message": "Записано профилей: %d (остальные не тронуты)" % len(profiles),
    }


def _vscode_extension_dir(home=None):
    """Папка установленного расширения opencode-lm (или None)."""
    base = vscode_extensions_dir(home)
    try:
        dirs = sorted(p for p in base.glob(VSCODE_EXT_ID + "-*") if p.is_dir())
    except Exception:
        return None
    return dirs[-1] if dirs else None


def _vscode_extension_installed(home=None) -> bool:
    return _vscode_extension_dir(home) is not None


def find_vscode_vsix(home=None):
    """Ищем собранный .vsix рядом с исходниками расширения."""
    src = vscode_lm_source_dir(home)
    for pattern in ("*.vsix", "extension/*.vsix"):
        try:
            found = sorted(src.glob(pattern))
        except Exception:
            found = []
        if found:
            return found[-1]
    return None


def _vscode_cli_candidates(home=None):
    """Как запустить установку расширения: CLI VS Code или node cli.js."""
    roots = []
    local = os.environ.get("LOCALAPPDATA")
    if local and not home:
        roots.append(Path(local) / "Programs" / "Microsoft VS Code")
    pf = os.environ.get("ProgramFiles")
    if pf and not home:
        roots.append(Path(pf) / "Microsoft VS Code")
    pfx86 = os.environ.get("ProgramFiles(x86)")
    if pfx86 and not home:
        roots.append(Path(pfx86) / "Microsoft VS Code")
    candidates = []
    for root in roots:
        try:
            if not root.is_dir():
                continue
            for sub in root.iterdir():
                cli = sub / "resources" / "app" / "out" / "cli.js"
                if cli.is_file():
                    candidates.append(("node", cli))
        except Exception:
            continue
        cmd = root / "bin" / "code.cmd"
        if cmd.is_file():
            candidates.append(("cmd", cmd))
    return candidates


def _run_cli_install(kind, cli_path, vsix, extensions_dir):
    """Пробуем официальный CLI. Возвращает (ok, вывод)."""
    import subprocess
    if kind == "node":
        cmd = ["node", str(cli_path)]
    else:
        cmd = ["cmd", "/c", str(cli_path)]
    cmd += ["--extensions-dir", str(extensions_dir),
            "--install-extension", str(vsix), "--force"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                              encoding="utf-8", errors="replace")
    except Exception as exc:
        return False, str(exc)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    ok = proc.returncode == 0 and re.search(r"successfully installed|already installed", out, re.I)
    return bool(ok), out


def _register_extension(ext_dir: Path, extensions_json: Path, version: str):
    """Дописывает запись в extensions.json (UTF-8 без BOM, массив)."""
    entries = []
    if extensions_json.exists() and extensions_json.stat().st_size > 0:
        try:
            data = json.loads(extensions_json.read_text(encoding="utf-8-sig"))
            if isinstance(data, list):
                entries = [e for e in data
                           if not (isinstance(e, dict)
                                   and (e.get("identifier") or {}).get("id") == VSCODE_EXT_ID)]
        except Exception:
            backup = extensions_json.with_name(
                extensions_json.name + ".broken-" + datetime.now().strftime("%Y%m%d%H%M%S"))
            try:
                shutil.copy2(extensions_json, backup)
            except Exception:
                pass
    uri = "/" + str(ext_dir.resolve()).replace("\\", "/").lstrip("/")
    entries.append({
        "identifier": {"id": VSCODE_EXT_ID,
                       "uuid": "8f3c1c2e-4a55-4c07-9d3b-3f0a6d5e7b21"},
        "version": version,
        "location": {"$mid": 1, "path": uri, "scheme": "file"},
        "relativeLocation": ext_dir.name,
        "metadata": {
            "source": "vsix",
            "installedTimestamp": int(datetime.now().timestamp() * 1000),
            "pinned": False,
            "updated": True,
            "private": True,
            "isPreReleaseVersion": False,
            "preRelease": False,
        },
    })
    extensions_json.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(extensions_json, json.dumps(entries, ensure_ascii=False, separators=(",", ":")))


def _install_extension_from_vsix(vsix: Path, home=None):
    """Ставит расширение копированием из .vsix (fallback без CLI)."""
    import zipfile
    extensions_dir = vscode_extensions_dir(home)
    extensions_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(vsix) as zf:
        names = zf.namelist()
        try:
            manifest = zf.read("extension/package.json").decode("utf-8-sig")
            version = str(json.loads(manifest).get("version") or "1.0.0")
        except Exception:
            version = "1.0.0"
        target = extensions_dir / ("%s-%s" % (VSCODE_EXT_ID, version))
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        for name in names:
            if not name.startswith("extension/") or name.endswith("/"):
                continue
            rel = name[len("extension/"):]
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        # VS Code ищет скрытый .vsixmanifest именно с точкой
        if "extension.vsixmanifest" in names:
            (target / ".vsixmanifest").write_bytes(zf.read("extension.vsixmanifest"))
    _register_extension(target, extensions_dir / "extensions.json", version)
    return target


def _ensure_vscode_extension(home=None) -> str:
    """Ставит opencode-lm, если его нет. Возвращает текст для отчёта."""
    if _vscode_extension_installed(home):
        found = _vscode_extension_dir(home)
        return "Расширение уже установлено: %s" % found.name
    vsix = find_vscode_vsix(home)
    if vsix is None:
        return ("Расширение не установлено и .vsix не найден — "
                "положите opencode-lm-*.vsix в %s" % vscode_lm_source_dir(home))
    extensions_dir = vscode_extensions_dir(home)
    for kind, cli in _vscode_cli_candidates(home):
        ok, out = _run_cli_install(kind, cli, vsix, extensions_dir)
        if ok and _vscode_extension_installed(home):
            return "Расширение установлено через CLI: %s" % vsix.name
    try:
        target = _install_extension_from_vsix(vsix, home)
    except Exception as exc:
        return "Не удалось установить расширение: %s" % exc
    return "Расширение установлено: %s" % target.name


def _patch_vscode_settings(settings_path: Path, config_path) -> str:
    """Прописывает opencodeLM.configPath в settings.json, не ломая остальное.

    Если файл содержит комментарии (JSONC), он не перезаписывается целиком:
    строка вставляется сразу после открывающей скобки, чтобы комментарии
    и форматирование пользователя остались на месте.
    """
    text = _read_text(settings_path)
    if not text.strip():
        data = {"opencodeLM.configPath": str(config_path)}
        _atomic_write(settings_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return "settings.json создан"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = json.loads(strip_jsonc(text))
        except Exception:
            return "settings.json не разбирается — пропущен (задайте путь вручную)"
        if not isinstance(data, dict):
            return "settings.json не является объектом — пропущен"
        if data.get("opencodeLM.configPath") == str(config_path):
            return "opencodeLM.configPath уже указывает на конфиг"
        insert_at = text.find("{")
        if insert_at < 0:
            return "settings.json без открывающей скобки — пропущен"
        line = '\n    "opencodeLM.configPath": %s,' % json.dumps(
            str(config_path), ensure_ascii=False)
        patched = text[:insert_at + 1] + line + text[insert_at + 1:]
        _backup_file(settings_path)
        _atomic_write(settings_path, patched)
        return "opencodeLM.configPath = %s (комментарии сохранены)" % config_path
    if not isinstance(data, dict):
        return "settings.json не является объектом — пропущен"
    if config_path and data.get("opencodeLM.configPath") != str(config_path):
        data["opencodeLM.configPath"] = str(config_path)
        _backup_file(settings_path)
        _atomic_write(settings_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return "opencodeLM.configPath = %s" % config_path
    return "opencodeLM.configPath уже указывает на конфиг"


def _transfer_vscode(profiles, default_model, config_path=None, home=None):
    """VS Code: профили уже лежат в opencode.json — расширение читает их оттуда.

    Поэтому перенос = поставить расширение opencode-lm (если его нет) и
    прописать ему путь к конфигу. Ключи никуда не копируются.
    """
    config = _resolve_config_path(config_path, home)
    notes = [_ensure_vscode_extension(home)]
    try:
        notes.append(_patch_vscode_settings(vscode_settings_path(home), config))
    except Exception as exc:
        notes.append("settings.json не изменён: %s" % exc)
    notes.append("Профили берутся из %s" % config)
    return {
        "agent": "vscode", "title": "VS Code (чат-модели)", "ok": True,
        "path": config, "backup": None, "message": "; ".join(notes),
    }


def _transfer_cline(profiles, default_model, home=None):
    """Cline: providers.json (формат v4) + models.json со списком моделей."""
    path = cline_providers_path(home)
    text = _read_text(path)
    try:
        data = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        try:
            data = json.loads(strip_jsonc(text))
        except Exception as exc:
            raise RuntimeError("providers.json не разбирается: %s" % exc)
    if not isinstance(data, dict):
        raise RuntimeError("providers.json не является объектом JSON")
    data.setdefault("version", 1)
    providers = data.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    now = datetime.now().astimezone().isoformat(timespec="milliseconds").replace("+00:00", "Z")
    for profile in profiles:
        pid = str(profile.get("id") or "")
        settings = {
            "provider": "openai-compatible",
            "apiKey": profile.get("api_key") or "",
            "model": _primary_model(profile, default_model),
            "baseUrl": profile.get("base_url"),
            "headers": {},
            "reasoning": {"enabled": False},
        }
        previous = providers.get(pid) if isinstance(providers.get(pid), dict) else {}
        entry = dict(previous)
        entry["settings"] = settings
        entry["updatedAt"] = now
        entry["tokenSource"] = "manual"
        providers[pid] = entry
    data["providers"] = providers
    primary = _pick_primary(profiles, default_model)
    if primary is not None:
        data["lastUsedProvider"] = str(primary.get("id"))
    data.setdefault("modes", {})
    _backup_file(path)
    _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    # список моделей: Cline берёт оттуда supportsVision и т.п.
    models_path = cline_models_path(home)
    try:
        models_doc = json.loads(_read_text(models_path) or "{}")
    except Exception:
        models_doc = {}
    if not isinstance(models_doc, dict):
        models_doc = {}
    models_doc.setdefault("version", 1)
    per_provider = models_doc.get("providers")
    if not isinstance(per_provider, dict):
        per_provider = {}
    for profile in profiles:
        pid = str(profile.get("id") or "")
        entry = per_provider.get(pid) if isinstance(per_provider.get(pid), dict) else {}
        known = entry.get("models") if isinstance(entry.get("models"), dict) else {}
        for mid in profile.get("models") or []:
            spec = known.get(mid) if isinstance(known.get(mid), dict) else {}
            spec["supportsVision"] = profile_model_vision(profile, mid)
            known[mid] = spec
        entry["models"] = known
        per_provider[pid] = entry
    models_doc["providers"] = per_provider
    _backup_file(models_path)
    _atomic_write(models_path, json.dumps(models_doc, indent=2, ensure_ascii=False) + "\n")

    count = sum(len(p.get("models") or []) for p in profiles)
    return {
        "agent": "cline", "title": "Cline", "ok": True, "path": path,
        "backup": None,
        "message": "Провайдеров: %d, моделей: %d" % (len(profiles), count),
    }


def _transfer_continue(profiles, default_model, home=None):
    path = continue_config_path(home)
    doc = _require_yaml(_read_text(path), path)
    if not doc:
        doc = {"name": "Local Config", "version": "1.0.0", "schema": "v1"}
    old = doc.get("models")
    models = list(old) if isinstance(old, list) else []
    ours_bases = {p.get("base_url") for p in profiles if p.get("base_url")}

    def is_ours(entry):
        return isinstance(entry, dict) and entry.get("apiBase") in ours_bases

    kept = [m for m in models if not is_ours(m)]
    added = 0
    for profile in profiles:
        kind = _provider_kind(profile.get("package"), profile.get("base_url"))
        for mid in profile.get("models") or []:
            entry = {
                "name": "%s · %s" % (profile.get("display_name") or profile.get("id"), mid),
                "provider": kind,
                "model": mid,
                "apiBase": profile.get("base_url"),
                "apiKey": profile.get("api_key") or "",
                "roles": list(CONTINUE_ROLES),
            }
            if profile_model_vision(profile, mid):
                entry["capabilities"] = ["tool_use", "image_input"]
            kept.append(entry)
            added += 1
    doc["models"] = kept
    _backup_file(path)
    _atomic_write(path, _dump_yaml_doc(doc))
    return {
        "agent": "continue", "title": "Continue", "ok": True, "path": path,
        "backup": None,
        "message": "Моделей добавлено: %d, всего: %d" % (added, len(kept)),
    }


def _toml_top_level_lines(text: str) -> tuple:
    lines = text.splitlines()
    split = len(lines)
    for idx, line in enumerate(lines):
        if line.lstrip().startswith("["):
            split = idx
            break
    return lines[:split], lines[split:]


def _toml_set_top_level(text: str, values: dict) -> str:
    head, body = _toml_top_level_lines(text)
    keep = []
    for line in head:
        stripped = line.strip()
        if any(stripped.startswith("%s =" % key) or stripped.startswith("%s=" % key)
               for key in values):
            continue
        keep.append(line)
    while keep and not keep[0].strip():
        keep.pop(0)
    prefix = ["%s = %s" % (key, _toml_quote(value)) for key, value in values.items()]
    result = prefix + keep
    if body:
        result = result + [""] + body
    return "\n".join(result).strip("\n") + "\n"


def _toml_drop_tables(text: str, headers) -> str:
    lines = text.splitlines()
    out = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and not stripped.startswith("[["):
            skipping = stripped in headers
            if skipping:
                continue
        elif stripped.startswith("[["):
            skipping = False
        if skipping:
            continue
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def _transfer_codex(profiles, default_model, home=None):
    path = codex_config_path(home)
    text = _read_text(path)
    headers = {"[model_providers.%s]" % p.get("id") for p in profiles}
    body = _toml_drop_tables(text, headers)
    blocks = []
    for profile in profiles:
        pid = str(profile.get("id") or "")
        blocks.append("[model_providers.%s]" % pid)
        blocks.append("name = %s" % _toml_quote(profile.get("display_name") or pid))
        blocks.append("base_url = %s" % _toml_quote(profile.get("base_url")))
        blocks.append("wire_api = \"chat\"")
        blocks.append("env_key = %s" % _toml_quote(_env_key(pid)))
        if profile.get("api_key"):
            blocks.append("experimental_bearer_token = %s" % _toml_quote(profile["api_key"]))
        blocks.append("")
    merged = (body.rstrip() + "\n\n" + "\n".join(blocks)).strip("\n") + "\n"
    primary = _pick_primary(profiles, default_model)
    if primary is not None:
        model = _primary_model(primary, default_model)
        values = {"model_provider": primary.get("id")}
        if model:
            values["model"] = model
        merged = _toml_set_top_level(merged, values)
    _backup_file(path)
    _atomic_write(path, merged)
    return {
        "agent": "codex", "title": "Codex CLI", "ok": True, "path": path,
        "backup": None,
        "message": "Провайдеров записано: %d" % len(profiles),
    }


def _transfer_claude(profiles, default_model, home=None):
    path = claude_settings_path(home)
    text = _read_text(path)
    try:
        data = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        try:
            data = json.loads(strip_jsonc(text))
        except Exception as exc:
            raise RuntimeError("settings.json не разбирается: %s" % exc)
    if not isinstance(data, dict):
        raise RuntimeError("settings.json не является объектом JSON")
    primary = _pick_primary(profiles, default_model)
    if primary is None:
        raise RuntimeError("нет профилей с baseURL")
    env = data.get("env") if isinstance(data.get("env"), dict) else {}
    env["ANTHROPIC_BASE_URL"] = primary.get("base_url")
    if primary.get("api_key"):
        env["ANTHROPIC_AUTH_TOKEN"] = primary["api_key"]
        env["ANTHROPIC_API_KEY"] = primary["api_key"]
    model = _primary_model(primary, default_model)
    if model:
        env["ANTHROPIC_MODEL"] = model
    data["env"] = env
    _backup_file(path)
    _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return {
        "agent": "claude", "title": "Claude Code", "ok": True, "path": path,
        "backup": None,
        "message": "%s → %s" % (primary.get("id"), model or "(модель не задана)"),
    }


def _transfer_aider(profiles, default_model, home=None):
    path = aider_config_path(home)
    doc = _require_yaml(_read_text(path), path)
    primary = _pick_primary(profiles, default_model)
    if primary is None:
        raise RuntimeError("нет профилей с baseURL")
    model = _primary_model(primary, default_model)
    doc["openai-api-base"] = primary.get("base_url")
    if primary.get("api_key"):
        doc["openai-api-key"] = primary["api_key"]
    if model:
        doc["model"] = "openai/%s" % model
    _backup_file(path)
    _atomic_write(path, _dump_yaml_doc(doc))
    return {
        "agent": "aider", "title": "Aider", "ok": True, "path": path,
        "backup": None,
        "message": "%s → %s" % (primary.get("id"), model or "(модель не задана)"),
    }


def _dsh_env_key(pid: str) -> str:
    """Имя переменной с ключом в .credentials.yaml (refs.<NAME>)."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", str(pid)).strip("_").upper() or "PROVIDER"
    return "DEEPSEEK_%s_API_KEY" % safe


def _dsh_replace_patch(doc, block_id, name, new_config):
    """Заменяет (или добавляет) один патч-элемент по id, не трогая остальные."""
    if not isinstance(doc, list):
        doc = []
    replaced = False
    for entry in doc:
        if isinstance(entry, dict) and entry.get("id") == block_id:
            entry["name"] = name
            entry["config"] = new_config
            replaced = True
            break
    if not replaced:
        doc.append({"id": block_id, "name": name, "config": new_config})
    return doc


def _dsh_provider_entry(profile, default_model):
    """Провайдер в формате dsh llm-pi-ai."""
    models = []
    for mid in profile.get("models") or []:
        spec = {"id": mid, "name": mid}
        raw_models = ((profile.get("_raw") or {}).get("models") or {})
        existing = raw_models.get(mid) if isinstance(raw_models, dict) else None
        if isinstance(existing, dict):
            name = existing.get("name")
            if isinstance(name, str) and name.strip():
                spec["name"] = name
            caps = existing.get("capabilities") or {}
            inputs = caps.get("input")
            if isinstance(inputs, str):
                inputs = inputs.split()
            if isinstance(inputs, list) and inputs:
                spec["input"] = [str(x) for x in inputs]
            else:
                spec["input"] = ["text"]
            limit = existing.get("limit") or {}
            if limit.get("context"):
                spec["contextWindow"] = int(limit["context"])
            if limit.get("output"):
                spec["maxTokens"] = int(limit["output"])
        spec.setdefault("input", ["text"])
        models.append(spec)
    entry = {
        "displayName": profile.get("display_name") or profile.get("id"),
        "apiKeyEnv": _dsh_env_key(profile.get("id")),
        "api": "openai-completions",
        "baseURL": profile.get("base_url"),
        "models": models,
    }
    return entry


def _transfer_dsh(profiles, default_model, home=None):
    """DeepSeek Harness: провайдеры в cordis.patch.yml, ключи в .credentials.yaml."""
    patch_path = dsh_patch_path(home)
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    doc = _require_yaml_any(_read_text(patch_path), patch_path, [])

    # текущий блок llm-pi-ai (если он уже есть) — дополняем, а не затираем
    providers = {}
    for entry in doc if isinstance(doc, list) else []:
        if isinstance(entry, dict) and entry.get("id") == "llm-pi-ai":
            cfg = entry.get("config") if isinstance(entry.get("config"), dict) else {}
            existing = cfg.get("providers")
            if isinstance(existing, dict):
                providers = copy.deepcopy(existing)
            break

    for profile in profiles:
        providers[str(profile["id"])] = _dsh_provider_entry(profile, default_model)

    doc = _dsh_replace_patch(
        doc, "llm-pi-ai", "@deepseek-ai/dsh-llm-pi-ai", {"providers": providers})

    _backup_file(patch_path)
    _atomic_write(patch_path, _dump_yaml_any(doc))

    # ключи — в .credentials.yaml, в refs.<ENV>: значения не теряем
    cred_path = dsh_credentials_path(home)
    creds = _require_yaml_any(_read_text(cred_path), cred_path, {})
    if not isinstance(creds, dict):
        creds = {}
    refs = creds.get("refs")
    if not isinstance(refs, dict):
        refs = {}
    written = 0
    for profile in profiles:
        key = profile.get("api_key")
        if key:
            refs[_dsh_env_key(profile.get("id"))] = key
            written += 1
    if written:
        creds["refs"] = refs
        _backup_file(cred_path)
        _atomic_write(cred_path, _dump_yaml_any(creds))

    return {
        "agent": "dsh", "title": "DeepSeek Harness", "ok": True,
        "path": patch_path, "backup": None,
        "message": "Провайдеров: %d, ключей: %d" % (len(providers), written),
    }


TRANSFER_WRITERS = {
    "opencode": _transfer_opencode,
    "vscode": _transfer_vscode,
    "cline": _transfer_cline,
    "continue": _transfer_continue,
    "codex": _transfer_codex,
    "claude": _transfer_claude,
    "aider": _transfer_aider,
    "dsh": _transfer_dsh,
}


def _read_json_lenient(path: Path):
    """JSON/JSONC файл или None, если его нет или он не разбирается."""
    try:
        text = _read_text(path)
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return json.loads(strip_jsonc(text))
    except Exception:
        return None


def _count_models(providers) -> int:
    if not isinstance(providers, dict):
        return 0
    total = 0
    for value in providers.values():
        models = (value or {}).get("models") if isinstance(value, dict) else None
        if isinstance(models, dict):
            total += len(models)
        elif isinstance(models, list):
            total += len(models)
    return total


def transfer_plan(profiles, default_model="", agent_ids=None, home=None,
                  config_path=None):
    """Сухой прогон: что произойдёт при переносе — без единой записи.

    Проверяет только то, что реально может сломаться или удивить:
      * сколько моделей станет в opencode.json (было → стало);
      * разбирается ли целевой файл агента (иначе перенос откажется);
      * есть ли уже расширение VS Code и куда указывает settings.json.

    Возвращает список {agent, title, ok, path, message}, как transfer_profiles.
    """
    selected = [a for a in (agent_ids or []) if a in TRANSFER_WRITERS]
    selected.sort(key=lambda a: AGENT_IDS.index(a) if a in AGENT_IDS else 99)
    targets = _profiles_for_transfer(profiles)
    if not targets:
        return [{"agent": "—", "title": "—", "ok": False, "path": None,
                 "message": "нет профилей с baseURL"}]

    plan = []
    for agent in selected:
        title = agent
        path = None
        ok = True
        notes = []
        try:
            if agent == "opencode":
                path = Path(config_path) if config_path else _resolve_config_path(None, home)
                if path.exists():
                    before_doc = load_config(path)
                else:
                    before_doc = {}
                before = _count_models(before_doc.get("providers"))
                merged = merge_profiles_into_config(before_doc, targets)
                after = _count_models(merged.get("providers"))
                existing_ids = set((before_doc.get("providers") or {}))
                new_ids = [p["id"] for p in targets if p["id"] not in existing_ids]
                notes.append("провайдеров %d → %d" % (len(existing_ids),
                                                      len(merged.get("providers") or {})))
                notes.append("моделей %d → %d" % (before, after))
                if new_ids:
                    notes.append("новые: %s" % ", ".join(new_ids[:4]))
                if after < before:
                    ok = False
                    notes.append("ВНИМАНИЕ: моделей станет меньше")
            elif agent == "vscode":
                path = vscode_settings_path(home)
                cfg = _resolve_config_path(config_path, home)
                installed = _vscode_extension_installed(home)
                if installed:
                    notes.append("расширение уже установлено")
                elif find_vscode_vsix(home) is not None:
                    notes.append("расширение будет установлено из .vsix")
                else:
                    ok = False
                    notes.append("расширения нет и .vsix не найден — установка не удастся")
                data = _read_json_lenient(path)
                if path.exists() and data is None:
                    ok = False
                    notes.append("settings.json не разбирается — будет пропущен")
                elif isinstance(data, dict) and data.get("opencodeLM.configPath") == str(cfg):
                    notes.append("путь к конфигу OpenCode уже прописан")
                else:
                    notes.append("пропишет путь к конфигу OpenCode")
            elif agent == "dsh":
                path = dsh_patch_path(home)
                if path.exists():
                    doc = _require_yaml_any(_read_text(path), path, [])
                    if not isinstance(doc, list):
                        ok = False
                        notes.append("cordis.patch.yml: корень не список")
                    else:
                        notes.append("патч-записей: %d" % len(doc))
                else:
                    notes.append("cordis.patch.yml будет создан")
            elif agent in ("continue", "aider"):
                path = (continue_config_path(home) if agent == "continue"
                        else aider_config_path(home))
                if path.exists():
                    _require_yaml(_read_text(path), path)
                    notes.append("YAML разбирается")
                else:
                    notes.append("файл будет создан")
            elif agent == "cline":
                path = cline_providers_path(home)
                if path.exists():
                    data = _read_json_lenient(path)
                    if data is None:
                        ok = False
                        notes.append("providers.json не разбирается")
                    else:
                        notes.append("провайдеров сейчас: %d"
                                     % len(data.get("providers") or {}))
                else:
                    notes.append("providers.json будет создан")
            elif agent == "codex":
                path = codex_config_path(home)
                notes.append("блоки [model_providers.*] будут дописаны"
                             if path.exists() else "config.toml будет создан")
            elif agent == "claude":
                path = claude_settings_path(home)
                if path.exists():
                    data = _read_json_lenient(path)
                    if data is None:
                        ok = False
                        notes.append("settings.json не разбирается")
                    else:
                        notes.append("env будет дополнен")
                else:
                    notes.append("settings.json будет создан")
        except Exception as exc:
            ok = False
            notes.append(str(exc))

        for item in _agent_catalog_snapshot(home):
            if item["id"] == agent:
                title = item["title"]
                break
        plan.append({"agent": agent, "title": title, "ok": ok, "path": path,
                     "message": "; ".join(notes)})
    return plan


def _agent_catalog_snapshot(home=None):
    try:
        return agent_catalog(home=home)
    except Exception:
        return []


def transfer_profiles(profiles, default_model="", agent_ids=None, home=None,
                      config_path=None):
    """Переносит выбранные профили в выбранных ИИ-агентов.

    Возвращает список результатов: {"agent", "title", "ok", "path",
    "message"} — по одному на каждого запрошенного агента.
    """
    selected = [a for a in (agent_ids or []) if a in TRANSFER_WRITERS]
    selected.sort(key=lambda a: AGENT_IDS.index(a) if a in AGENT_IDS else 99)
    targets = _profiles_for_transfer(profiles)
    results = []
    if not targets:
        return [{"agent": "—", "title": "—", "ok": False, "path": None,
                 "message": "нет профилей с baseURL"}]
    for agent in selected:
        writer = TRANSFER_WRITERS[agent]
        try:
            if agent == "opencode":
                result = writer(targets, default_model, config_path=config_path,
                                home=home)
            elif agent == "vscode":
                result = writer(targets, default_model, config_path=config_path,
                                home=home)
            else:
                result = writer(targets, default_model, home=home)
        except Exception as exc:
            result = {"agent": agent, "title": agent, "ok": False, "path": None,
                      "backup": None, "message": str(exc)}
        results.append(result)
    return results


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
        self.capability_vars = {}
        self.capability_hidden = set()
        self.known_models = list((profile or {}).get("known_models", []))
        self._raw = (profile or {}).get("_raw")

        self.title("НОВЫЙ ПРОФИЛЬ" if self.is_new else "ПРОФИЛЬ " + str(profile["id"]).upper())
        # окно повыше: у моделей раскрываются галочки возможностей
        self.geometry("860x880")
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
        tk.Label(khint,
                 text="«ВОЗМОЖНОСТИ» — ЧТО ПРОВАЙДЕР УМЕЕТ. ГАЛОЧКИ ПИШУТСЯ В "
                      "opencode.json (capabilities: input/output, tools, reasoning)",
                 bg=T.bg, fg=T.ink_dim, font=T.mono_small).pack(anchor="w", padx=2)

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

    def _model_entry(self, mid):
        for m in self.models:
            if m["id"] == mid:
                return m
        return {"id": mid}

    def _cap_vars(self, mid):
        """Галочки возможностей модели: что в конфиге, иначе предположение."""
        if mid not in self.capability_vars:
            existing = None
            raw_models = (self._raw or {}).get("models") or {}
            if isinstance(raw_models, dict) and isinstance(raw_models.get(mid), dict):
                existing = raw_models.get(mid)
            flags = model_capabilities(self._model_entry(mid), existing)
            self.capability_vars[mid] = {
                key: tk.BooleanVar(master=self, value=bool(flags.get(key)))
                for key, _ in CAPABILITY_KEYS
            }
        return self.capability_vars[mid]

    def _has_capability_flags(self, mid):
        raw_models = (self._raw or {}).get("models") or {}
        existing = raw_models.get(mid) if isinstance(raw_models, dict) else None
        if not isinstance(existing, dict):
            return False
        return bool(existing.get("capabilities"))

    def _cap_summary(self, mid):
        """Короткая строка для закрытого вида: «tool vision»."""
        vars_ = self._cap_vars(mid)
        names = [key for key, _ in CAPABILITY_KEYS if vars_[key].get()]
        return " · ".join(names) or "нет"

    def _toggle_caps(self, mid):
        if mid in self.capability_hidden:
            self.capability_hidden.discard(mid)
        else:
            self.capability_hidden.add(mid)
        self._render_models()

    def _refresh_cap_summary(self, mid):
        btn = (getattr(self, "cap_buttons", {}) or {}).get(mid)
        if btn is None:
            return
        try:
            btn.configure(text="ВОЗМОЖНОСТИ: %s" % self._cap_summary(mid))
        except Exception:
            pass

    def _render_models(self):
        for child in list(self.inner.winfo_children()):
            child.pack_forget()
            child.destroy()
        self.cap_buttons = {}
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
            row = tk.Frame(self.inner, bg=T.bg_panel)
            row.pack(anchor="w", padx=8, pady=1, fill="x")
            cb = SmartCheck(row, self, self.model_vars[mid], text)
            cb.var = self.model_vars[mid]
            cb.pack(anchor="w", fill="x")
            caps_var = tk.BooleanVar(master=self, value=(mid not in self.capability_hidden))
            btn = tk.Checkbutton(
                row, text="ВОЗМОЖНОСТИ: %s" % self._cap_summary(mid),
                variable=caps_var, onvalue=True, offvalue=False,
                command=lambda mid=mid: self._toggle_caps(mid),
                bg=T.bg_panel, fg=T.cyan_dim, selectcolor=T.bg_input,
                activebackground=T.bg_panel, activeforeground=T.cyan,
                font=T.mono_small, bd=0, highlightthickness=0, anchor="w")
            btn.pack(anchor="w", padx=(24, 0))
            self.cap_buttons[mid] = btn
            if mid in self.capability_hidden:
                continue
            caps_row = tk.Frame(row, bg=T.bg_input)
            caps_row.pack(anchor="w", padx=(28, 4), pady=(1, 4), fill="x")
            vars_ = self._cap_vars(mid)
            for col, (key, label) in enumerate(CAPABILITY_KEYS):
                var = vars_[key]
                var.trace_add("write", lambda *a, m=mid: self._refresh_cap_summary(m))
                tk.Checkbutton(
                    caps_row, text=label, variable=var,
                    bg=T.bg_input, fg=T.ink, selectcolor=T.bg_panel_hi,
                    activebackground=T.bg_input, activeforeground=T.cyan,
                    font=T.mono_small, bd=0, highlightthickness=0, anchor="w"
                ).grid(row=col // 3, column=col % 3, sticky="w", padx=(4, 12), pady=1)
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
            "model_capabilities": {
                mid: {key: bool(var.get()) for key, var in caps.items()}
                for mid, caps in self.capability_vars.items()
            },
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


# ==========================================================================
# MCP-серверы и скиллы (инструменты для OpenCode и других агентов)
# ==========================================================================
#
# Что делает этот раздел:
#   * MCP — дописывает записи в `mcp` конфига OpenCode (и в JSON-конфиги
#     остальных агентов, у которых есть файл настроек) по образцам из каталога;
#   * скиллы — умеет посмотреть установленные, проверить файл-каталог скиллов
#     (папку, ZIP или tar.gz — архив открывается только если внутри есть
#     SKILL.md) и разложить их по папке OpenCode, не задевая чужие.
#
# Ничего чужого не удаляется: перед любой записью делается копия, а каждое
# действие возвращает отчёт из тех же полей, что перенос профилей.

    mcp_placeholder = "C:\\путь\\к\\папке"

#: Каталог MCP-серверов. `build` собирает проводку из полей (сам конфиг сюда
#: не пишется), `fields` — то, что спрашивают у пользователя в окне.
MCP_CATALOG = (
    {
        "id": "rea",
        "title": "REA — реверс-инжиниринг (нативный/браузер/менеджер пакетов)",
        "description": "rea-agents через npx. Ghidra/JDK необязательны: без них "
                       "работают Frida, Rizin, браузер и разбор пакетов.",
        "kind": "local",
        "command": ["cmd.exe", "/d", "/c", "npx", "-y", "rea-agents@6.7.0", "mcp"],
        "fields": (
            {"key": "GHIDRA_INSTALL_DIR", "label": "Ghidra (пусто — не нужна)"},
            {"key": "JAVA_HOME", "label": "JAVA_HOME (пусто — не нужен)"},
        ),
        "requires": "node",
    },
    {
        "id": "filesystem",
        "title": "Filesystem — доступ к папкам",
        "description": "Официальный сервер @modelcontextprotocol/server-filesystem: "
                       "чтение/запись только в разрешённых папках.",
        "kind": "local",
        "command": ["cmd.exe", "/d", "/c", "npx", "-y",
                    "@modelcontextprotocol/server-filesystem@2025.7.1"],
        "path_args": True,
        "fields": ({"key": "path", "label": "Разрешённая папка", "required": True,
                    "path_arg": True},),
        "requires": "node",
    },
    {
        "id": "memory",
        "title": "Memory — заметки между сессиями",
        "description": "Официальный сервер памяти @modelcontextprotocol/server-memory "
                       "(граф знаний в JSON).",
        "kind": "local",
        "command": ["cmd.exe", "/d", "/c", "npx", "-y",
                    "@modelcontextprotocol/server-memory@2025.7.1"],
        "fields": (),
        "requires": "node",
    },
    {
        "id": "sequential-thinking",
        "title": "Sequential Thinking — цепочки рассуждений",
        "description": "Сервер @modelcontextprotocol/server-sequential-thinking: "
                       "пошаговое планирование для сложных задач.",
        "kind": "local",
        "command": ["cmd.exe", "/d", "/c", "npx", "-y",
                    "@modelcontextprotocol/server-sequential-thinking@2025.7.1"],
        "fields": (),
        "requires": "node",
    },
    {
        "id": "github",
        "title": "GitHub — issues, PR, файлы репозиториев",
        "description": "Официальный remote-сервер https://api.githubcopilot.com/mcp/. "
                       "Нужен токен GitHub с правами на репозитории.",
        "kind": "remote",
        "url": "https://api.githubcopilot.com/mcp/",
        "fields": ({"key": "GITHUB_PAT", "label": "GitHub token (ghp_…)", "secret": True,
                    "required": True, "env": True},),
        "requires": "network",
    },
)

MCP_SERVER_IDS = tuple(item["id"] for item in MCP_CATALOG)

#: Файлы-настройки MCP у остальных агентов (`mcpServers` — их общий формат).
MCP_AGENT_FILES = (
    ("claude", "Claude Code", lambda home: claude_settings_path(home)),
    ("codex", "Codex CLI", lambda home: _home_dir(home) / ".codex" / "config.toml"),
    ("cline", "Cline", lambda home: cline_dir(home) / "mcp_settings.json"),
    ("vscode", "VS Code", lambda home: vscode_user_dir(home) / "mcp.json"),
)

#: Где OpenCode ищет скиллы, если в конфиге нет ключа `skills`.
SKILLS_FOLDER = "skills"


def mcp_catalog_entry(server_id):
    for item in MCP_CATALOG:
        if item["id"] == server_id:
            return item
    return None


def mcp_server_entry(item, values=None) -> dict:
    """Собирает запись для `mcp.<id>` из каталога и значений полей.

    Значения-секреты пишутся не открытым текстом, а подстановкой
    `{env:ИМЯ}`: OpenCode возьмёт переменную из окружения, а конфиг можно
    безопасно копировать и архивировать.
    """
    values = values if isinstance(values, dict) else {}
    if item.get("kind") == "remote":
        headers = {}
        for field in item.get("fields") or ():
            value = str(values.get(field["key"]) or "").strip()
            if not value:
                if field.get("required"):
                    raise ValueError("не заполнено поле «%s»" % field["label"])
                continue
            if field.get("secret"):
                headers["Authorization"] = "Bearer {env:%s}" % field["key"]
            else:
                headers["X-%s" % field["key"]] = value
        entry = {"type": "remote", "url": item["url"], "enabled": True}
        if headers:
            entry["headers"] = headers
        return _norm_mcp_entry(entry)

    command = list(item.get("command") or [])
    if item.get("path_args"):
        path = str(values.get("path") or "").strip()
        if not path:
            raise ValueError("не заполнена папка для сервера «%s»" % item["id"])
        command.append(os.path.expanduser(path))
    entry = {"type": "local", "command": command, "enabled": True}
    environment = {}
    for field in item.get("fields") or ():
        value = str(values.get(field["key"]) or "").strip()
        if not value:
            if field.get("required"):
                raise ValueError("не заполнено поле «%s»" % field["label"])
            continue
        if field.get("env"):
            # секрет: в файл попадает только ссылка на переменную окружения
            environment[field["key"]] = "{env:%s}" % field["key"]
        elif not field.get("path_arg"):
            environment[field["key"]] = value
    if environment:
        entry["environment"] = environment
    return _norm_mcp_entry(entry)


def _norm_mcp_entry(entry) -> dict:
    """Запись сервера в формате `mcp.servers`.

    В новой схеме вместо `enabled` используется `disabled`, поэтому выключенный
    или включённый сервер пишется явно, а лишний ключ убирается.
    """
    result = {k: v for k, v in dict(entry or {}).items() if k != "enabled"}
    if entry.get("enabled") is False:
        result["disabled"] = True
    else:
        result["disabled"] = False
    return result


def mcp_entry_secrets(entry) -> dict:
    """Переменные окружения, которые запись ждёт через `{env:ИМЯ}`."""
    result = {}
    if not isinstance(entry, dict):
        return result
    values = list((entry.get("headers") or {}).values())
    values += list((entry.get("environment") or {}).values())
    for value in values:
        for name in re.findall(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}", str(value)):
            result[name] = None
    return result


def mcp_servers_map(config) -> dict:
    """Рабочий словарь серверов `mcp.servers`.

    Новая схема OpenCode хранит серверы в `mcp.servers` (в `mcp` разрешены
    только `timeout`/`servers`). Старые конфиги держат их прямо в `mcp` —
    такие записи поднимаем наверх, чтобы не потерять rea и прочие.
    """
    mcp = (config or {}).get("mcp")
    if not isinstance(mcp, dict):
        return {}
    servers = mcp.get("servers") if isinstance(mcp.get("servers"), dict) else {}
    for name, entry in mcp.items():
        if name in ("servers", "timeout"):
            continue
        if isinstance(entry, dict):
            servers.setdefault(name, entry)
    return servers


def _looks_like_server(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    return any(key in entry for key in ("type", "command", "url"))


def mcp_servers_from_config(config) -> dict:
    """Серверы из конфига в читаемом виде: только включённые."""
    servers = {}
    for name, entry in mcp_servers_map(config).items():
        if not _looks_like_server(entry):
            # сокращённая запись вида {"enabled": true} — не сервер
            continue
        if entry.get("enabled") is False or entry.get("disabled") is True:
            continue
        kind = entry.get("type") or ("remote" if entry.get("url") else "local")
        servers[name] = {
            "type": kind,
            "command": entry.get("command"),
            "url": entry.get("url"),
            "environment": entry.get("environment") or {},
        }
    return servers


def _mcp_servers_style(entry) -> dict:
    """Запись сервера в формате `mcpServers` (Claude Code, Cline, VS Code)."""
    entry = entry if isinstance(entry, dict) else {}
    if entry.get("type") == "remote":
        result = {"type": "http", "url": entry.get("url")}
        if entry.get("headers"):
            result["headers"] = copy.deepcopy(entry["headers"])
        return result
    command = list(entry.get("command") or [])
    result = {"command": command[0] if command else ""}
    if len(command) > 1:
        result["args"] = command[1:]
    if entry.get("environment"):
        result["env"] = copy.deepcopy(entry["environment"])
    return result


def _mcp_merge_check(config, name, entry) -> list:
    """Чем новая запись отличается от уже записанной (для отчёта)."""
    old = mcp_servers_map(config).get(name)
    notes = []
    if isinstance(old, dict):
        for key in ("type", "command", "url", "environment"):
            if old.get(key) != entry.get(key):
                notes.append("обновлён «%s»" % key)
    else:
        notes.append("новый сервер")
    return notes


def _toml_mcp_block(name, entry) -> str:
    """Блок `[mcp_servers.<id>]` для config.toml Codex CLI."""
    lines = ["[mcp_servers.%s]" % name]
    if entry.get("type") == "remote":
        lines.append('url = "%s"' % entry.get("url"))
        for key, value in (entry.get("headers") or {}).items():
            lines.append("http_headers = { %s = %s }" % (json.dumps(key), json.dumps(value)))
    else:
        command = entry.get("command") or []
        if command:
            lines.append("command = %s" % json.dumps(command[0]))
            if len(command) > 1:
                lines.append("args = %s" % json.dumps(command[1:]))
        env = entry.get("environment") or {}
        if env:
            pairs = ", ".join("%s = %s" % (json.dumps(k), json.dumps(v))
                              for k, v in env.items())
            lines.append("env = { %s }" % pairs)
    return "\n".join(lines)


def apply_mcp_servers(config, servers, mcp_config_path=None) -> dict:
    """Дописывает MCP-серверы в конфиг OpenCode; остальное не трогает.

    `servers` — {id: запись из `mcp_server_entry`}. Дополнительно (если задан
    `mcp_config_path`) пишется сводный файл `{"mcpServers": …}` — его читают
    Claude Code, Cline и VS Code.
    """
    new = copy.deepcopy(config) if isinstance(config, dict) else {}
    report = {}
    before = copy.deepcopy(new)
    mcp = new.get("mcp")
    if not isinstance(mcp, dict):
        mcp = {}
        new["mcp"] = mcp
    # схема OpenCode: в `mcp` только `timeout` и `servers`, поэтому серверы
    # живут в `mcp.servers`; старые записи «прямо в mcp» переносим туда же
    legacy = {name: sc for name, sc in mcp.items()
              if name not in ("servers", "timeout") and isinstance(sc, dict)}
    for name in legacy:
        mcp.pop(name, None)
    box = mcp.get("servers")
    if not isinstance(box, dict):
        box = {}
    box = {name: copy.deepcopy(sc) for name, sc in box.items() if isinstance(sc, dict)}
    for name, sc in legacy.items():
        # старые записи хранят включённость в `enabled` — приводим к `disabled`
        box.setdefault(name, _norm_mcp_entry(sc))
    for name, entry in (servers or {}).items():
        report[name] = _mcp_merge_check(before, name, entry)
        box[name] = copy.deepcopy(entry)
        for env_name in mcp_entry_secrets(entry):
            os.environ.setdefault(env_name, "")
    mcp["servers"] = box
    if mcp_config_path:
        path = Path(mcp_config_path)
        old = _read_json_lenient(path)
        old = old if isinstance(old, dict) else {}
        merged = old.get("mcpServers") if isinstance(old.get("mcpServers"), dict) else {}
        merged = copy.deepcopy(merged)
        for name, entry in (servers or {}).items():
            merged[name] = _mcp_servers_style(entry)
        old["mcpServers"] = merged
        _backup_file(path)
        _atomic_write(path, json.dumps(old, indent=2, ensure_ascii=False) + "\n")
    return {"config": new, "changes": report}


def install_mcp_servers(servers, config_path=None, home=None, mcp_config_path=None,
                        mcp_agent_ids=None) -> list:
    """Пишет серверы в opencode.json и в файлы выбранных агентов.

    Возвращает список {agent, title, ok, path, backup, message}.
    """
    path = Path(config_path) if config_path else _resolve_config_path(None, home)
    results = []
    try:
        config = load_config(path)
        applied = apply_mcp_servers(config, servers, mcp_config_path=mcp_config_path)
        backup = save_config(path, applied["config"])
        parts = ["%s: %s" % (name, ", ".join(changes) or "без изменений")
                 for name, changes in applied["changes"].items()]
        results.append({
            "agent": "opencode", "title": "OpenCode (этот конфиг)", "ok": True,
            "path": path, "backup": backup,
            "message": "; ".join(parts) or "серверы не выбраны",
        })
    except Exception as exc:
        results.append({"agent": "opencode", "title": "OpenCode (этот конфиг)",
                        "ok": False, "path": path, "backup": None,
                        "message": str(exc)})

    wanted = set(mcp_agent_ids or ())
    for agent_id, title, path_fn in MCP_AGENT_FILES:
        if agent_id not in wanted:
            continue
        target = path_fn(home)
        try:
            if agent_id == "codex":
                results.append(_write_mcp_codex_toml(target, title, agent_id, servers))
            else:
                results.append(_write_mcp_json_file(target, title, agent_id, servers))
        except Exception as exc:
            results.append({"agent": agent_id, "title": title, "ok": False,
                            "path": target, "backup": None, "message": str(exc)})
    return results


def _write_mcp_json_file(path: Path, title, agent_id, servers) -> dict:
    data = _read_json_lenient(path)
    if path.exists() and not isinstance(data, dict):
        raise RuntimeError("файл не разбирается — пропущен")
    data = copy.deepcopy(data) if isinstance(data, dict) else {}
    box = data.get("mcpServers") if isinstance(data.get("mcpServers"), dict) else {}
    box = copy.deepcopy(box)
    for name, entry in (servers or {}).items():
        box[name] = _mcp_servers_style(entry)
    data["mcpServers"] = box
    backup = _backup_file(path)
    _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return {"agent": agent_id, "title": title, "ok": True, "path": path,
            "backup": backup, "message": "серверов в mcpServers: %d" % len(box)}


def _write_mcp_codex_toml(path: Path, title, agent_id, servers) -> dict:
    text = _read_text(path)
    lines = []
    for name, entry in (servers or {}).items():
        # старый блок того же сервера убираем: TOML не разрешает дважды
        # определять одну и ту же таблицу
        pattern = re.compile(r"(?ms)^\[mcp_servers\.%s\]\s*\n.*?(?=^\[|\Z)"
                             % re.escape(name))
        text = pattern.sub("", text)
        lines.append(_toml_mcp_block(name, entry))
    if not lines:
        return {"agent": agent_id, "title": title, "ok": True, "path": path,
                "backup": None, "message": "серверы не выбраны"}
    body = text.rstrip()
    new_text = (body + "\n\n" if body else "") + "\n\n".join(lines) + "\n"
    backup = _backup_file(path)
    _atomic_write(path, new_text)
    return {"agent": agent_id, "title": title, "ok": True, "path": path,
            "backup": backup, "message": "записано блоков [mcp_servers.*]: %d"
                                         % len(lines)}


# --- скиллы ----------------------------------------------------------------


def skills_base_dir(config=None, home=None) -> Path:
    """Папка скиллов: из конфига (`skills`), иначе ~/.config/opencode/skills."""
    value = (config or {}).get("skills")
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                candidate = Path(os.path.expanduser(item.strip()))
                if not candidate.is_absolute():
                    candidate = _home_dir(home) / ".config" / "opencode" / candidate
                return candidate
    if isinstance(value, dict) and isinstance(value.get("paths"), list):
        for item in value["paths"]:
            if isinstance(item, str) and item.strip():
                return Path(os.path.expanduser(item.strip()))
    return _home_dir(home) / ".config" / "opencode" / SKILLS_FOLDER


def skill_manifest(path) -> dict:
    """Шапка SKILL.md (`name:` и `description:` из YAML-фронтматтера)."""
    text = _read_text(Path(path))
    result = {"name": "", "description": ""}
    if not text.lstrip().startswith("---"):
        return result
    body = text.lstrip().split("\n")[1:]
    for line in body:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower()
            if key in result:
                result[key] = value.strip().strip('"').strip("'")
    return result


def find_skill_dirs(root) -> list:
    """Папки со скиллами: сам `root`, затем на глубине 1, 2 и 3.

    Глубина 2–3 нужна для архивов, где скиллы лежат в подпапке пакета:
    `pack/skills/имя/SKILL.md` или `pack/skills/<категория>/имя/SKILL.md`.
    Спускаемся только внутрь папок без SKILL.md — дальше скилл уже лежит.
    """
    root = Path(root)
    found = []
    if (root / "SKILL.md").is_file():
        return [root]

    def walk(folder: Path, depth: int):
        try:
            children = sorted(p for p in folder.iterdir() if p.is_dir())
        except Exception:
            return
        for child in children:
            if (child / "SKILL.md").is_file():
                found.append(child)
            elif depth < 3:
                walk(child, depth + 1)

    walk(root, 1)
    return found


def list_installed_skills(base=None, config=None, home=None) -> list:
    base = Path(base) if base else skills_base_dir(config, home)
    items = []
    for path in find_skill_dirs(base):
        manifest = skill_manifest(path / "SKILL.md")
        items.append({
            "name": manifest.get("name") or path.name,
            "description": manifest.get("description") or "",
            "path": path,
        })
    return items


def _safe_folder_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "")).strip("-.")
    return cleaned or "skill"


def _archive_member_paths(source, fmt) -> list:
    """Имена файлов в архиве (ZIP или tar), без записи на диск."""
    source = Path(source)
    if fmt == "zip":
        with zipfile.ZipFile(source) as archive:
            return archive.namelist()
    with tarfile.open(source, "r:*") as archive:
        return [member.name for member in archive.getmembers()]


def _check_archive_paths(source, fmt) -> None:
    """Отказ от архива, который может расписаться вне целевой папки."""
    bad = []
    for name in _archive_member_paths(source, fmt):
        text = str(name).replace("\\", "/")
        parts = [p for p in text.split("/") if p not in ("", ".")]
        if text.startswith("/") or re.match(r"^[A-Za-z]:", text) or ".." in parts:
            bad.append(text)
    if bad:
        raise ValueError("архив отменён: подозрительные пути (%s)"
                         % ", ".join(bad[:3]))


def install_skills(source, base=None, overwrite=False, home=None) -> dict:
    """Раскладывает скиллы из папки / ZIP / tar.gz в папку скиллов.

    Архив сначала смотрится «вхолостую»: если в нём есть хоть один путь,
    который может выйти за пределы папки (zip-slip), распаковка отменяется.
    Существующие скиллы без `overwrite` не перезаписываются.
    """
    base = Path(base) if base else skills_base_dir(None, home)
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError("нет файла или папки: %s" % source)
    report = {"installed": [], "skipped": [], "errors": [], "base": base}
    with tempfile.TemporaryDirectory(prefix="ocm-skills-") as tmp:
        stage = Path(tmp) / "src"
        root = Path(tmp).resolve()
        if source.is_dir():
            shutil.copytree(source, stage)
        elif source.suffix.lower() == ".zip":
            _check_archive_paths(source, "zip")
            shutil.unpack_archive(str(source), str(stage), "zip")
            actual = Path(os.path.realpath(stage))
            if not actual.is_relative_to(os.path.realpath(root)):
                raise ValueError("архив распакован вне временной папки")
        elif source.name.lower().endswith((".tar.gz", ".tgz", ".tar")):
            fmt = "tar" if source.name.lower().endswith(".tar") else "gztar"
            _check_archive_paths(source, fmt)
            shutil.unpack_archive(str(source), str(stage), fmt)
            actual = Path(os.path.realpath(stage))
            if not actual.is_relative_to(os.path.realpath(root)):
                raise ValueError("архив распакован вне временной папки")
        else:
            raise ValueError("нужна папка, .zip или .tar.gz")
        for path in find_skill_dirs(stage):
            resolved = path.resolve()
            if root not in resolved.parents and resolved != root:
                report["errors"].append("%s: путь вне папки" % path.name)
                continue
            manifest = skill_manifest(path / "SKILL.md")
            name = _safe_folder_name(manifest.get("name") or path.name)
            dest = base / name
            if dest.exists() and not overwrite:
                report["skipped"].append(name)
                continue
            try:
                if dest.exists():
                    shutil.rmtree(dest)
                base.mkdir(parents=True, exist_ok=True)
                shutil.copytree(path, dest)
                report["installed"].append(name)
            except Exception as exc:
                report["errors"].append("%s: %s" % (name, exc))
    return report


def remove_skill(name, base=None, home=None) -> bool:
    """Удаляет один скилл из папки скиллов (только внутри неё)."""
    base = Path(base) if base else skills_base_dir(None, home)
    target = (base / _safe_folder_name(name)).resolve()
    if base.resolve() not in target.parents:
        return False
    if not (target / "SKILL.md").is_file():
        return False
    shutil.rmtree(target)
    return True


def skills_config_entry(base=None, home=None):
    """Какой ключ `skills` должен быть в конфиге, чтобы папка была видна."""
    base = Path(base) if base else skills_base_dir(None, home)
    return [str(base)]


def mcp_report_lines(results) -> list:
    lines = []
    for res in results or []:
        mark = "OK " if res.get("ok") else "ОШИБКА "
        lines.append("%s%s\n    %s\n    %s" % (
            mark, res.get("title") or res.get("agent"),
            str(res.get("path") or "—"), res.get("message") or ""))
    return lines


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
                # ВАЖНО: эта процедура вызывается из потока Windows, где Python-поток
                # может быть не инициализирован. Любой вызов Tk отсюда валит процесс
                # (Fatal Python error: PyEval_RestoreThread, GIL is NULL).
                # Поэтому здесь ТОЛЬКО ставим событие, а окно/меню трогает главный поток.
                try:
                    if msg == self.WM_TRAYICON:
                        low = int(lparam) & 0xFFFF
                        if low == self.WM_RBUTTONUP:
                            self._pending_menu = True
                            return 0
                        if low == self.WM_LBUTTONDBLCLK:
                            self._pending_dblclick = True
                            return 0
                        if low == self.WM_LBUTTONUP:
                            # может стать двойным кликом — решает главный поток
                            self._pending_single = True
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
        self._pending_menu = False
        self._pending_single = False
        self._pending_dblclick = False
        self._single_due = 0.0
        self._start_menu_pump()
        return ok

    def _start_menu_pump(self):
        """Опрашивает флаги из оконной процедуры в главном потоке Tk.

        Левый клик  — открыть меню (с задержкой, чтобы отличить двойной);
        двойной левый — развернуть/свернуть окно программы;
        правый клик — меню.
        """
        try:
            now = time.monotonic()

            if getattr(self, "_pending_dblclick", False):
                self._pending_dblclick = False
                self._pending_single = False
                self._single_due = 0.0
                self.app.root.after(0, self._toggle_app_window)

            elif getattr(self, "_pending_single", False):
                self._pending_single = False
                self._single_due = now + 0.35   # ждём возможный второй клик

            if self._single_due and now >= self._single_due:
                self._single_due = 0.0
                self._build_and_show_menu()

            if getattr(self, "_pending_menu", False):
                self._pending_menu = False
                self._build_and_show_menu()
        except Exception:
            pass
        try:
            self.app.root.after(60, self._start_menu_pump)
        except Exception:
            pass

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
        aos = getattr(self.app, "aos", None)
        aos_visible = bool(aos and aos.win is not None and aos.win.winfo_exists())
        root = self.app.root
        win_shown = root.state() == "normal"

        menu = tk.Menu(root, tearoff=0, bg=T.bg_panel_hi, fg=T.ink,
                       activebackground="#0b3547", activeforeground=T.cyan,
                       font=T.mono_small)
        # --- AOS ---
        menu.add_command(
            label=("СКРЫТЬ AOS" if aos_visible else "ПОКАЗАТЬ AOS"),
            command=self._toggle_aos_visible)
        ct = bool(aos and aos.click_through)
        menu.add_command(label=("✓ " if ct else "   ") + "КЛИКИ СКВОЗЬ AOS",
                         command=self._toggle_aos_click)
        menu.add_separator()
        # --- главное окно ---
        menu.add_command(
            label=("СВЕРНУТЬ ПРИЛОЖЕНИЕ" if win_shown else "РАЗВЕРНУТЬ ПРИЛОЖЕНИЕ"),
            command=self._toggle_app_window)
        menu.add_separator()
        menu.add_command(label="НАСТРОЙКИ AOS…", command=self.app.open_aos_settings)
        menu.add_separator()
        auto = autostart_enabled()
        menu.add_command(label=("✓ " if auto else "   ") + "АВТОЗАГРУЗКА В ТРЕЕ",
                         command=self._toggle_autostart)
        menu.add_separator()
        menu.add_command(label="ЗАКРЫТЬ ПРИЛОЖЕНИЕ", command=self.app.quit_app)

        x, y = self._cursor_pos()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()
        self._menu = menu

    # --- действия меню ----------------------------------------------------
    def _toggle_autostart(self):
        """Включает/выключает автозагрузку приложения в трее."""
        target = not autostart_enabled()
        ok = set_autostart(target)
        if not ok:
            try:
                messagebox.showerror("Автозагрузка",
                                     "Не удалось изменить параметр автозагрузки.",
                                     parent=self.app.root)
            except Exception:
                pass
            return
        state = "ВКЛЮЧЕНА" if target else "ВЫКЛЮЧЕНА"
        try:
            self.app._set_status("АВТОЗАГРУЗКА В ТРЕЕ: " + state)
        except Exception:
            pass

    def _toggle_aos_visible(self):
        aos = getattr(self.app, "aos", None) or self.app._aos()
        if aos is None:
            return
        if aos.win is not None and aos.win.winfo_exists():
            aos.hide()
            aos.settings["enabled"] = False
            save_aos_settings(aos.settings)
        else:
            aos.settings["enabled"] = True
            save_aos_settings(aos.settings)
            aos.show()
        self.app._refresh_aos_button()

    def _toggle_aos_click(self):
        if getattr(self.app, "aos", None) is not None:
            self.app.toggle_aos_click_through()

    def _toggle_app_window(self):
        root = self.app.root
        if root.state() == "normal":
            root.withdraw()
        else:
            root.deiconify()
            root.lift()
            root.focus_force()

    def _on_left_click(self):
        """Оставлено для совместимости — разворачивает окно и не трогает значок."""
        self._toggle_app_window()

    def _cursor_pos(self):
        import ctypes
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



# Расширенные стили окна для «прозрачности для мыши»
_CT_WNDPORC = {}

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000


def _set_click_through(hwnd, enabled: bool) -> bool:
    """Включает/выключает прохождение кликов мыши сквозь окно.

    WS_EX_TRANSPARENT работает только если окно возвращает HTTRANSPARENT на
    WM_NCHITTEST. Tk перехватывает это сообщение ради собственного WM, поэтому
    подменяем оконную процедуру и в нужном режиме отвечаем HTTRANSPARENT.
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                             ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.CallWindowProcW.argtypes = [ctypes.c_ssize_t, wintypes.HWND,
                                           wintypes.UINT, wintypes.WPARAM,
                                           wintypes.LPARAM]
        user32.CallWindowProcW.restype = LRESULT
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                        ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL

        GWL_EXSTYLE = -20
        GWLP_WNDPROC = -4
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        WM_NCHITTEST = 0x0084
        HTTRANSPARENT = -1
        SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER = 0x0002, 0x0001, 0x0004
        SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0010, 0x0020

        hwnd = wintypes.HWND(hwnd)
        state = _CT_WNDPORC.setdefault(hwnd.value, {})

        # 1) расширенные стили
        style = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
        style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
        if enabled:
            style |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
        else:
            style &= ~WS_EX_TRANSPARENT
            style &= ~WS_EX_NOACTIVATE
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)

        # 2) подменяем оконную процедуру, чтобы отвечать HTTRANSPARENT
        if "orig" not in state:
            def make_proc(hwnd_value):
                def proc(h_wnd, msg, wparam, lparam):
                    if msg == WM_NCHITTEST:
                        mode = _CT_WNDPORC.get(hwnd_value, {}).get("enabled", False)
                        if mode:
                            return HTTRANSPARENT
                    orig = _CT_WNDPORC.get(hwnd_value, {}).get("orig", 0)
                    if orig:
                        return user32.CallWindowProcW(orig, h_wnd, msg,
                                                      wparam, lparam)
                    return 0
                return WNDPROC(proc)

            proc_ref = make_proc(hwnd.value)
            old = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC,
                                           ctypes.cast(proc_ref, ctypes.c_void_p).value)
            state["orig"] = int(old or 0)
            state["proc"] = proc_ref   # держим ссылку, иначе GC убьёт колбэк

        state["enabled"] = bool(enabled)

        # 3) переприменяем, чтобы Windows учла стили
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
                            SWP_NOACTIVATE | SWP_FRAMECHANGED)
        return True
    except Exception:
        return False


def _hwnd_of(tk_window):
    """Получает HWND окна Tk (Toplevel/Tk)."""
    try:
        import ctypes
        tk_window.update_idletasks()
        name = tk_window.wm_frame()
        if isinstance(name, str) and name:
            return int(name, 16)
        return int(tk_window.winfo_id())
    except Exception:
        return 0


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
                "refresh_sec": 60, "show_profile": True, "show_coefficient": True,
                "click_through": True, "always_visible": False,
                "profiles": []}
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
        alt_id = getattr(self, "_alt_after", None)
        if alt_id and self.win is not None:
            try:
                self.win.after_cancel(alt_id)
            except Exception:
                pass
            self._alt_after = None
        self._through_active = None
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
        # сквозной режим: мышь работает с окнами под оверлеем
        self.root_after = None
        try:
            w.after(60, self.fit_to_content)
            w.after(140, self.fit_to_content)
            w.after(80, self.apply_click_through)
            w.after(300, self._poll_alt)
        except Exception:
            pass

    def _set_state_dot(self, color):
        """Меняет цвет индикатора состояния «●»."""
        self._dot_color = color
        try:
            lbl = getattr(self, "lbl_state", None)
            if lbl is not None:
                lbl.configure(fg=color)
        except Exception:
            pass

    def fit_to_content(self):
        """Подгоняет окно точно под содержимое: ширина по самой широкой строке.

        Меряем шрифтом Tk, а не reqwidth контейнера — тот после удаления строк
        отдаёт устаревшее маленькое значение. Ширина может и уменьшаться
        (когда профилей стало меньше) — это и убирает пустое место справа.
        """
        win = self.win
        if win is None or not win.winfo_exists():
            return
        body = getattr(self, "_body", None)
        if body is None:
            return
        try:
            body.update_idletasks()
            win.update_idletasks()

            rows_box = getattr(self, "rows_box", None)
            labels = getattr(self, "_row_labels", {}) or {}
            if not labels:
                return

            # 1) ширина по фактическим строкам текста
            text_w = 0
            try:
                import tkinter.font as tkfont
                f_small = tkfont.Font(font=self._row_font)
                f_big = tkfont.Font(font=self._row_font_big)
                for pid, pair in labels.items():
                    val, est = pair
                    for widget, font in ((val, f_big), (est, f_small)):
                        txt = widget.cget("text") or ""
                        if txt:
                            text_w = max(text_w, font.measure(txt))
            except Exception:
                text_w = 0

            # 2) измерение контейнера как запасной вариант
            geo_w = 0
            if rows_box is not None:
                rows_box.update_idletasks()
                geo_w = rows_box.winfo_reqwidth()
            # отступы содержимого: pad слева/справа + небольшой запас на рамку
            pad = 2 * (10 if self.settings.get("preset") == "compact" else 14) + 4
            # если строки пока без данных («—»), ориентируемся на геометрию контейнера
            if text_w and text_w > 40:
                cw = text_w + pad
            else:
                cw = max(geo_w, body.winfo_reqwidth())

            body.update_idletasks()
            # низ содержимого = самая нижняя точка последней строки профиля
            bottom = 0
            for pair in getattr(self, "_row_labels", {}).values():
                for widget in pair:
                    try:
                        bottom = max(bottom,
                                     widget.master.winfo_y() + widget.winfo_y()
                                     + widget.winfo_height())
                    except Exception:
                        pass
            ch = bottom + 1 if bottom else max(body.winfo_height(), 30)
            if cw < 60 or ch < 30:
                return

            width = int(cw) + 2
            height = int(ch) + 4
            cur_w = self._canvas.winfo_width()
            cur_h = self._canvas.winfo_height()
            cur_w = 0 if cur_w <= 1 else cur_w
            cur_h = 0 if cur_h <= 1 else cur_h
            # меняем при реальной разнице (и когда до этого окно было не того размера)
            if cur_w == width and cur_h == height and self._body.winfo_height() == height - 4:
                return
            self._last_fit_w = width
            self._canvas.configure(width=width, height=height)
            self._draw_round(width, height)
        except Exception:
            pass

    def set_opacity(self, value):
        """Меняет прозрачность окна на лету, без пересоздания содержимого."""
        try:
            value = max(0.25, min(1.0, float(value)))
        except Exception:
            return
        self.settings["opacity"] = value
        win = self.win
        if win is None or not win.winfo_exists():
            return
        try:
            win.attributes("-alpha", value)
        except Exception:
            pass

    @property
    def click_through(self):
        return bool(self.settings.get("click_through", True))

    def apply_click_through(self, enabled=None):
        """Применяет режим «мышь сквозь оверлей»."""
        if enabled is not None:
            self.settings["click_through"] = bool(enabled)
            save_aos_settings(self.settings)
        if self.win is None or not self.win.winfo_exists():
            return False
        hwnd = _hwnd_of(self.win)
        if not hwnd:
            return False
        ok = _set_click_through(hwnd, self.click_through)
        # у overrideredirect-окна Tk есть родитель-обёртка: стили нужны и ей
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            parent = int(user32.GetParent(wintypes.HWND(hwnd)) or 0)
            if parent:
                _set_click_through(parent, self.click_through)
        except Exception:
            pass
        try:
            # подсказка в самом оверлее: как перетащить, если включён сквозной режим
            self.lbl_hint.configure(
                text="сквозной · Alt = перетащить"
                if self.click_through else "можно перетаскивать")
        except Exception:
            pass
        return ok

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
        self._body = body
        self._win_id = self._canvas.create_window(0, 0, window=body, anchor="nw")

        # индикатор «●» правым краем сверху; высота минимальная, чтобы
        # не добавлять заметного отступа над строками профилей
        # индикатор «●» живёт в первой строке профиля (справа), а не отдельной строкой

        # строки профилей: имя + баланс (по одной на профиль)
        self._row_frames = []
        self._row_labels = {}
        self.rows_box = tk.Frame(body, bg=T.panel_fill)
        self.rows_box.pack(fill="x", padx=pad, pady=0)
        self._row_font = font_small
        self._row_font_big = font_big
        self._rebuild_rows()


        self.lbl_hint = tk.Label(body, text="", bg=T.panel_fill, fg=T.cyan_dim,
                                 font=("Consolas", 7), anchor="w")
        # сначала даём Tk разложить всё, потом меряем реальные размеры содержимого
        body.update_idletasks()
        try:
            body.master.master.update_idletasks()   # окно -> canvas -> body
        except Exception:
            pass
        content_w = max(body.winfo_reqwidth(), body.winfo_width())
        content_h = max(body.winfo_reqheight(), body.winfo_height())
        width = max(170, content_w + 18)   # +18: правый отступ, чтобы текст не прилипал к краю
        need_h = max(60, content_h + 6)
        self._canvas.configure(width=width, height=need_h)
        self._draw_round(width, need_h)
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
        """Прямоугольный фон окна без скруглений и рамки."""
        c = self._canvas
        c.delete("bg")
        c.create_rectangle(0, 0, w, h, fill=T.panel_fill, outline="", tags="bg")
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

    def toggle_click_through(self):
        self.apply_click_through(not self.click_through)
        return self.click_through

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
        m.add_command(
            label=("✓ " if self.click_through else "") + "КЛИКИ СКВОЗЬ ОВЕРЛЕЙ",
            command=self.toggle_click_through)
        m.add_command(label="ОБНОВИТЬ", command=self.refresh)
        m.add_command(label="ОТКРЫТЬ ОКНО",
                      command=lambda: (self.app.root.deiconify(), self.app.root.lift()))
        m.add_command(label="СКРЫТЬ AOS", command=lambda: self.toggle(False))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def refresh(self):
        profiles = self._visible_profiles()
        if not profiles:
            try:
                self._set_state_dot(T.ink_dim)
                self.lbl_when.configure(text="нет профиля")
            except Exception:
                pass
            return
        any_data = any(p.get("_balance") for p in profiles)
        any_err = any(p.get("_balance_error") for p in profiles)
        try:
            self._set_state_dot(T.green if any_data else (T.red if any_err else T.ink_dim))
        except Exception:
            pass
        self._update_rows()
        try:
            stamps = [p.get("_balance_at") for p in profiles if p.get("_balance_at")]
            self.lbl_when.configure(
                text=max(stamps).strftime("%H:%M:%S") if stamps else "")
        except Exception:
            pass

    def _visible_profiles(self):
        """Профили для оверлея: отмеченные галочками; если ничего не отмечено — все."""
        want = list(self.settings.get("profiles") or [])
        if not want:
            return list(self.app.profiles)
        out = []
        for pid in want:
            prof = self.app._find(pid)
            if prof is not None:
                out.append(prof)
        return out or list(self.app.profiles)

    def _rebuild_rows(self):
        """Пересоздаёт строки профилей (вызывается при смене состава/размера)."""
        box = getattr(self, "rows_box", None)
        if box is None:
            return
        for ch in box.winfo_children():
            ch.destroy()
        self._row_labels = {}
        profiles = self._visible_profiles()
        for idx, prof in enumerate(profiles):
            if idx:  # разделительная полоса между профилями
                sep = tk.Canvas(box, height=1, bg=T.panel_fill,
                                highlightthickness=0, bd=0, width=1)
                sep.pack(fill="x", padx=1, pady=6)
                sep.create_line(0, 0, 400, 0, fill=T.panel_edge, width=1)
            row = tk.Frame(box, bg=T.panel_fill)
            row.pack(fill="x", pady=1)
            panel_w = int(self.settings.get("_width", 280))
            max_chars = max(12, (panel_w - 30) // 7)
            shown = str(prof.get("display_name") or prof["id"])
            if len(shown) > max_chars:
                shown = shown[:max_chars - 1] + "…"
            name_line = tk.Frame(row, bg=T.panel_fill)
            name_line.pack(fill="x")
            name = tk.Label(name_line, text=shown, bg=T.panel_fill, fg=T.ink_dim,
                            font=self._row_font, anchor="w")
            name.pack(side="left")
            if idx == 0:
                # индикатор состояния — справа в строке первого профиля
                self.lbl_state = tk.Label(name_line, text="●", bg=T.panel_fill,
                                          fg=getattr(self, "_dot_color", T.ink_dim),
                                          font=("Consolas", 9, "bold"), bd=0, pady=0)
                self.lbl_state.pack(side="right")
            value = tk.Label(row, text="—", bg=T.panel_fill, fg=T.ink_dim,
                             font=self._row_font_big, anchor="w", bd=0, pady=0)
            value.pack(anchor="w", pady=0)
            est = tk.Label(row, text="", bg=T.panel_fill, fg=T.cyan_soft,
                           font=self._row_font, anchor="w", bd=0, pady=0)
            est.pack(anchor="w", pady=0)
            self._row_labels[prof["id"]] = (value, est)

    def _update_rows(self):
        """Обновляет текст строк без пересоздания виджетов."""
        profiles = self._visible_profiles()
        known = set(self._row_labels)
        want = {p["id"] for p in profiles}
        if known != want:
            self._rebuild_rows()
        for prof in profiles:
            pair = self._row_labels.get(prof["id"])
            if not pair:
                continue
            value, est = pair
            data = prof.get("_balance")
            err = prof.get("_balance_error")
            if data:
                value.configure(text=data.get("text") or "—", fg=T.green)
                coef = str(prof.get("coefficient") or "").strip()
                e = coefficient_estimate(data.get("tokens"), coef) if (
                    coef and self.settings.get("show_coefficient", True)) else {}
                est.configure(text=("≈ %s (к=%s)" % (e["text"], coef)) if e else "")
            elif err:
                value.configure(text="—", fg=T.red)
                est.configure(text=self._fit_error(err))
            else:
                value.configure(text="—", fg=T.ink_dim)
                est.configure(text="нет данных")
        # текст мог стать длиннее -> окно подстраиваем под фактическое содержимое
        try:
            if self.win is not None and self.win.winfo_exists():
                self.win.after_idle(self.fit_to_content)
        except Exception:
            pass

    def set_profiles(self, ids):
        """Задаёт список профилей для отображения в AOS."""
        self.settings["profiles"] = list(ids)
        save_aos_settings(self.settings)
        if self.win is not None and self.win.winfo_exists():
            self._build_content(self.win)
            self.apply_position()
            self.refresh()

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

    def _poll_alt(self):
        """Пока зажат Alt — оверлей ловит мышь (можно перетащить); отпустили — снова сквозной."""
        if self.win is None or not self.win.winfo_exists():
            return
        try:
            import ctypes
            alt_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x12) & 0x8000)
        except Exception:
            alt_down = False
        want_through = self.click_through and not alt_down
        if want_through != getattr(self, "_through_active", None):
            self._through_active = want_through
            hwnd = _hwnd_of(self.win)
            if hwnd:
                _set_click_through(hwnd, want_through)
        try:
            self._alt_after = self.win.after(150, self._poll_alt)
        except Exception:
            pass

    def _schedule_refresh(self, immediate=True):
        if self.win is None or not self.win.winfo_exists():
            return
        # отменяем прежний таймер, иначе они накапливаются и шлют пачку запросов
        if self._after_id is not None:
            try:
                self.win.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        sec = max(60, int(self.settings.get("refresh_sec", 60)))
        if immediate:
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
        self._schedule_refresh(immediate=True)





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



# Расширенные стили окна для «прозрачности для мыши»
_CT_WNDPORC = {}

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000


def _set_click_through(hwnd, enabled: bool) -> bool:
    """Включает/выключает прохождение кликов мыши сквозь окно.

    WS_EX_TRANSPARENT работает только если окно возвращает HTTRANSPARENT на
    WM_NCHITTEST. Tk перехватывает это сообщение ради собственного WM, поэтому
    подменяем оконную процедуру и в нужном режиме отвечаем HTTRANSPARENT.
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                             ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.CallWindowProcW.argtypes = [ctypes.c_ssize_t, wintypes.HWND,
                                           wintypes.UINT, wintypes.WPARAM,
                                           wintypes.LPARAM]
        user32.CallWindowProcW.restype = LRESULT
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                        ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL

        GWL_EXSTYLE = -20
        GWLP_WNDPROC = -4
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        WM_NCHITTEST = 0x0084
        HTTRANSPARENT = -1
        SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER = 0x0002, 0x0001, 0x0004
        SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0010, 0x0020

        hwnd = wintypes.HWND(hwnd)
        state = _CT_WNDPORC.setdefault(hwnd.value, {})

        # 1) расширенные стили
        style = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
        style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
        if enabled:
            style |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
        else:
            style &= ~WS_EX_TRANSPARENT
            style &= ~WS_EX_NOACTIVATE
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)

        # 2) подменяем оконную процедуру, чтобы отвечать HTTRANSPARENT
        if "orig" not in state:
            def make_proc(hwnd_value):
                def proc(h_wnd, msg, wparam, lparam):
                    if msg == WM_NCHITTEST:
                        mode = _CT_WNDPORC.get(hwnd_value, {}).get("enabled", False)
                        if mode:
                            return HTTRANSPARENT
                    orig = _CT_WNDPORC.get(hwnd_value, {}).get("orig", 0)
                    if orig:
                        return user32.CallWindowProcW(orig, h_wnd, msg,
                                                      wparam, lparam)
                    return 0
                return WNDPROC(proc)

            proc_ref = make_proc(hwnd.value)
            old = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC,
                                           ctypes.cast(proc_ref, ctypes.c_void_p).value)
            state["orig"] = int(old or 0)
            state["proc"] = proc_ref   # держим ссылку, иначе GC убьёт колбэк

        state["enabled"] = bool(enabled)

        # 3) переприменяем, чтобы Windows учла стили
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
                            SWP_NOACTIVATE | SWP_FRAMECHANGED)
        return True
    except Exception:
        return False


def _hwnd_of(tk_window):
    """Получает HWND окна Tk (Toplevel/Tk)."""
    try:
        import ctypes
        tk_window.update_idletasks()
        name = tk_window.wm_frame()
        if isinstance(name, str) and name:
            return int(name, 16)
        return int(tk_window.winfo_id())
    except Exception:
        return 0


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
                "refresh_sec": 60, "show_profile": True, "show_coefficient": True,
                "click_through": True, "always_visible": False,
                "profiles": []}
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




class AOSSettingsDialog(tk.Toplevel):
    """Настройки AOS-оверлея: положение, размер, прозрачность, профили, обновление."""

    def __init__(self, app, aos):
        super().__init__(app.root)
        self.app = app
        self.aos = aos
        self.title("НАСТРОЙКИ AOS")
        self.minsize(520, 560)
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
        self.var_click = tk.BooleanVar(value=bool(aos.settings.get("click_through", True)))
        self._profiles_sel = list(aos.settings.get("profiles") or [])
        self.profile_vars = {}

        self._build()
        self._fit_dialog()
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

        row = tk.Frame(self, bg=T.bg)
        row.pack(fill="x", padx=16, pady=4)
        tk.Checkbutton(row, text="ПОКАЗЫВАТЬ AOS", variable=self.var_enabled,
                       bg=T.bg, fg=T.ink, selectcolor=T.bg_input, activebackground=T.bg,
                       activeforeground=T.cyan, font=T.mono_small, bd=0,
                       command=self._toggle_enabled).pack(anchor="w")

        # положение — сетка 3x3
        tk.Label(self, text="ПОЛОЖЕНИЕ НА ЭКРАНЕ", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w", padx=18, pady=(10, 2))
        grid = tk.Frame(self, bg=T.bg)
        grid.pack(padx=16)
        layout = [
            [("top-left", "СВЕРХУ\nСЛЕВА"), ("top-center", "СВЕРХУ\nЦЕНТР"),
             ("top-right", "СВЕРХУ\nСПРАВА")],
            [("mid-left", "СЛЕВА\nЦЕНТР"), None, ("mid-right", "СПРАВА\nЦЕНТР")],
            [("bottom-left", "СНИЗУ\nСЛЕВА"), ("bottom-center", "СНИЗУ\nЦЕНТР"),
             ("bottom-right", "СНИЗУ\nСПРАВА")],
        ]
        self._pos_buttons = {}
        for r, row_items in enumerate(layout):
            for c, item in enumerate(row_items):
                if item is None:
                    tk.Label(grid, text="·", bg=T.bg, fg=T.cyan_dim, font=T.mono_small,
                             width=12, height=3).grid(row=r, column=c, padx=3, pady=3)
                    continue
                key, title = item
                b = tk.Button(grid, text=title, bg=T.bg_panel_hi, fg=T.ink,
                              activebackground="#0b3547", activeforeground=T.cyan,
                              relief="flat", font=T.mono_small, width=12, height=3,
                              command=lambda k=key: self._choose_pos(k))
                b.grid(row=r, column=c, padx=3, pady=3)
                self._pos_buttons[key] = b
        self._refresh_pos_buttons()

        # профили — галочками
        tk.Label(self, text="ПРОФИЛИ В ОВЕРЛЕЕ — отметьте нужные", bg=T.bg,
                 fg=T.ink_dim, font=T.mono_small).pack(anchor="w", padx=18, pady=(10, 2))
        prow = tk.Frame(self, bg=T.bg)
        prow.pack(fill="x", padx=16)
        box = tk.Frame(prow, bg=T.bg_input, highlightthickness=1,
                       highlightbackground=T.line)
        box.pack(side="left", fill="both", expand=True)
        self._pcan = tk.Canvas(box, bg=T.bg_input, highlightthickness=0, bd=0, height=92)
        self._pcan.pack(side="left", fill="both", expand=True)
        psb = ttk.Scrollbar(box, orient="vertical", command=self._pcan.yview)
        psb.pack(side="right", fill="y")
        self._pcan.configure(yscrollcommand=psb.set)
        self._checks_inner = tk.Frame(self._pcan, bg=T.bg_input)
        self._pcan.create_window((0, 0), window=self._checks_inner, anchor="nw",
                                 tags="inner")
        self._checks_inner.bind(
            "<Configure>",
            lambda e: self._pcan.configure(scrollregion=self._pcan.bbox("all")))
        self._pcan.bind(
            "<Configure>", lambda e: self._pcan.itemconfigure("inner", width=e.width))
        self._fill_profiles_list()

        # размер
        tk.Label(self, text="РАЗМЕР", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w", padx=18, pady=(10, 2))
        sizes = tk.Frame(self, bg=T.bg)
        sizes.pack(fill="x", padx=16)
        for key, title in AOS_PRESETS.items():
            ttk.Radiobutton(sizes, text=title, value=key, variable=self.var_preset,
                            command=self._apply_live).pack(side="left", padx=(2, 12))

        # прозрачность
        tk.Label(self, text="ПРОЗРАЧНОСТЬ", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w", padx=18, pady=(8, 0))
        tk.Scale(self, from_=0.4, to=1.0, resolution=0.02, orient="horizontal",
                 variable=self.var_opacity, bg=T.bg, fg=T.ink, troughcolor=T.bg_input,
                 highlightthickness=0, font=T.mono_small, showvalue=True,
                 command=lambda v: self._apply_live()).pack(fill="x", padx=18)

        # частота
        tk.Label(self, text="ОБНОВЛЯТЬ БАЛАНС", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w", padx=18, pady=(6, 2))
        freq = tk.Frame(self, bg=T.bg)
        freq.pack(fill="x", padx=16)
        for sec, title in ((60, "1 МИН"), (120, "2 МИН"), (300, "5 МИН"),
                           (900, "15 МИН")):
            ttk.Radiobutton(freq, text=title, value=sec, variable=self.var_refresh,
                            command=self._apply_live).pack(side="left", padx=(2, 12))

        # содержимое
        tk.Label(self, text="СОДЕРЖИМОЕ", bg=T.bg, fg=T.ink_dim,
                 font=T.mono_small).pack(anchor="w", padx=18, pady=(8, 2))
        opts = tk.Frame(self, bg=T.bg)
        opts.pack(fill="x", padx=16)
        ttk.Checkbutton(opts, text="имя профиля", variable=self.var_profile,
                        command=self._apply_live).pack(side="left", padx=(2, 14))
        ttk.Checkbutton(opts, text="пересчёт по коэффициенту", variable=self.var_coef,
                        command=self._apply_live).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(opts, text="клики сквозь оверлей", variable=self.var_click,
                        command=self._apply_live).pack(side="left")

        foot = tk.Frame(self, bg=T.bg)
        foot.pack(fill="x", padx=16, pady=(14, 12), side="bottom")
        ttk.Button(foot, text="ЗАКРЫТЬ", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(foot, text="ПРИМЕНИТЬ", style="Accent.TButton",
                   command=self._apply_and_close).pack(side="right", padx=4)
        ttk.Button(foot, text="СБРОСИТЬ ПОЛОЖЕНИЕ",
                   command=self._reset_position).pack(side="left", padx=4)

    def _fit_dialog(self):
        """Подгоняет окно так, чтобы все элементы и кнопки были видны."""
        try:
            self.update_idletasks()
            need_w = max(560, self.winfo_reqwidth() + 8)
            need_h = self.winfo_reqheight() + 8
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            need_h = min(need_h, sh - 80)
            x = max(20, (sw - need_w) // 2)
            y = max(20, (sh - need_h) // 2)
            self.geometry("%dx%d+%d+%d" % (need_w, need_h, x, y))
            self.update_idletasks()
            # выводим диалог на передний план: из меню трея главное окно может быть свёрнуто
            try:
                parent = self.master
                if parent is not None and parent.winfo_exists() and parent.winfo_viewable():
                    pass
                else:
                    # родитель скрыт -> transient сделал бы диалог невидимым
                    try:
                        self.transient("")
                    except Exception:
                        pass
                self.deiconify()
                self.lift()
                self.attributes("-topmost", True)
                self.after(300, lambda: self.attributes("-topmost", False))
                self.focus_force()
                self.update_idletasks()
            except Exception:
                pass
        except Exception:
            self.geometry("620x720")

    # --- профили ----------------------------------------------------------
    def _fill_profiles_list(self):
        for ch in list(self._checks_inner.winfo_children()):
            ch.destroy()
        self.profile_vars = {}
        for prof in self.app.profiles:
            pid = prof.get("id")
            if not pid:
                continue
            name = str(prof.get("display_name") or pid)
            var = tk.BooleanVar(value=pid in self._profiles_sel)
            self.profile_vars[pid] = var
            text = "%-18s  %s" % (name[:18], str(prof.get("base_url", ""))[:24])
            cb = tk.Checkbutton(
                self._checks_inner, text=text, variable=var, bg=T.bg_input, fg=T.ink,
                selectcolor=T.bg_panel_hi, activebackground=T.bg_input,
                activeforeground=T.cyan, font=T.mono_small, bd=0, anchor="w",
                highlightthickness=0, command=self._apply_live)
            cb.pack(fill="x", padx=4, pady=1)

    def _read_profiles_selection(self):
        return [pid for pid, var in self.profile_vars.items() if bool(var.get())]

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
                    btn.configure(bg="#0b3547", fg=T.cyan)
                else:
                    btn.configure(bg=T.bg_panel_hi, fg=T.ink)
            except Exception:
                pass

    def _reset_position(self):
        self._choose_pos("top-right")

    def _apply_live(self):
        """Применяет настройки на лету: прозрачность не пересоздаёт окно."""
        s = self.aos.settings
        prev_preset = s.get("preset")
        prev_profiles = list(s.get("profiles") or [])
        s["preset"] = self.var_preset.get()
        s["opacity"] = round(float(self.var_opacity.get()), 2)
        s["refresh_sec"] = max(60, int(self.var_refresh.get()))
        s["show_profile"] = bool(self.var_profile.get())
        s["show_coefficient"] = bool(self.var_coef.get())
        s["click_through"] = bool(self.var_click.get())
        selected = self._read_profiles_selection()
        s["profiles"] = selected
        save_aos_settings(s)

        if self.aos.win is None or not self.aos.win.winfo_exists():
            return

        self.aos.set_opacity(s["opacity"])

        if selected != prev_profiles:
            try:
                self.aos._rebuild_rows()
                self.aos.fit_to_content()
                self.aos.apply_position()
            except Exception:
                pass
            # у новых профилей баланса ещё нет — запрашиваем
            try:
                missing = [p for p in self.aos._visible_profiles()
                           if not p.get("_balance")]
                if missing:
                    self.app.request_balance(silent=True, force=True)
            except Exception:
                pass

        self.aos.refresh()
        self.aos.apply_click_through()

        if prev_preset != s["preset"]:
            self.aos._build_content(self.aos.win)
            self.aos.apply_position()
            self.aos.refresh()
            self.aos.apply_click_through()

    def _apply_and_close(self):
        self._apply_live()
        self.app._refresh_aos_button()
        self.destroy()


class AgentsDialog(tk.Toplevel):
    """Перенос профилей в ИИ-агентов: галочки агентов и профилей + импорт."""

    def __init__(self, app, home=None):
        super().__init__(app.root)
        self.app = app
        self.title("ПЕРЕНОС ПРОФИЛЕЙ В ИИ-АГЕНТОВ")
        self.geometry("900x760")
        self.minsize(780, 620)
        self.configure(bg=T.bg)
        self.transient(app.root)
        self.grab_set()

        saved = load_agents_settings()
        saved_agents = [a for a in (saved.get("agents") or []) if a in AGENT_IDS]
        saved_profiles = list(saved.get("profiles") or [])
        self.agent_vars = {}
        self.profile_vars = {}
        self.var_profile_filter = tk.StringVar(master=self)
        self.var_profile_filter.trace_add("write", lambda *a: self._render_profiles())
        self._result = None
        self.home = home          # подменяется в тестах: куда писать конфиги

        self.catalog = agent_catalog(home=self.home,
                                     config_path=str(app.config_path))

        for item in self.catalog:
            self.agent_vars[item["id"]] = tk.BooleanVar(
                master=self, value=(item["id"] in saved_agents))
        for profile in app.profiles:
            self.profile_vars[profile["id"]] = tk.BooleanVar(
                master=self, value=(profile["id"] in saved_profiles or not saved_profiles))

        self._build()
        try:
            app.clipboard.bind_tree(self)
        except Exception:
            pass
        self.bind("<Escape>", lambda e: self.destroy())

    # --- UI ---------------------------------------------------------------
    def _build(self):
        head = tk.Frame(self, bg=T.bg)
        head.pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(head, text="ПЕРЕНОС ПРОФИЛЕЙ В ИИ-АГЕНТОВ", bg=T.bg, fg=T.cyan,
                 font=T.mono_title).pack(anchor="w")
        tk.Label(head, text="Отметьте агентов и профили — профили попадут в конфиги агентов.",
                 bg=T.bg, fg=T.ink_dim, font=T.mono_small).pack(anchor="w", pady=(2, 0))
        ScanStrip(self, color=T.cyan).pack(fill="x", padx=16, pady=(6, 6))

        mid = tk.Frame(self, bg=T.bg)
        mid.pack(fill="both", expand=True, padx=16)
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)
        mid.rowconfigure(0, weight=1)

        # агенты
        apanel = RoundedPanel(mid, radius=16, fill=T.bg_panel, outline=T.cyan_dim,
                              thickness=1, bg=T.bg)
        apanel.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=2)
        abox = apanel.inner
        ahead = tk.Frame(abox, bg=T.bg_panel)
        ahead.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(ahead, text="ИИ-АГЕНТЫ", bg=T.bg_panel, fg=T.cyan,
                 font=T.mono_title).pack(side="left")
        self.lbl_agents = tk.Label(ahead, text="", bg=T.bg_panel, fg=T.amber,
                                   font=T.mono_small)
        self.lbl_agents.pack(side="right")

        arow = tk.Frame(abox, bg=T.bg_panel)
        arow.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Button(arow, text="☑ ВСЕ", width=8, style="Accent.TButton",
                   command=lambda: self._set_agents(True)).pack(side="left", padx=2)
        ttk.Button(arow, text="☐ НИЧЕГО", width=10,
                   command=lambda: self._set_agents(False)).pack(side="left", padx=2)

        self._agent_canvas = tk.Canvas(abox, bg=T.bg_panel, highlightthickness=0)
        asb = ttk.Scrollbar(abox, orient="vertical", command=self._agent_canvas.yview)
        self._agent_canvas.configure(yscrollcommand=asb.set)
        self._agent_inner = tk.Frame(self._agent_canvas, bg=T.bg_panel)
        self._agent_window = self._agent_canvas.create_window(
            (0, 0), window=self._agent_inner, anchor="nw")
        self._agent_inner.bind(
            "<Configure>",
            lambda e: self._agent_canvas.configure(
                scrollregion=self._agent_canvas.bbox("all")))
        self._agent_canvas.bind(
            "<Configure>",
            lambda e: self._agent_canvas.itemconfigure(self._agent_window, width=e.width))
        self._agent_canvas.pack(fill="both", expand=True, padx=(10, 0), pady=(0, 8))
        asb.pack(side="right", fill="y", padx=(0, 10), pady=(0, 8))
        self._agent_canvas.bind("<Enter>", self._bind_agent_wheel)
        self._agent_canvas.bind("<Leave>", self._unbind_agent_wheel)
        self._render_agents()

        # профили
        ppanel = RoundedPanel(mid, radius=16, fill=T.bg_panel, outline=T.cyan_dim,
                              thickness=1, bg=T.bg)
        ppanel.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=2)
        pbox = ppanel.inner
        phead = tk.Frame(pbox, bg=T.bg_panel)
        phead.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(phead, text="ПРОФИЛИ ДЛЯ ПЕРЕНОСА", bg=T.bg_panel, fg=T.cyan,
                 font=T.mono_title).pack(side="left")
        self.lbl_profiles = tk.Label(phead, text="", bg=T.bg_panel, fg=T.amber,
                                     font=T.mono_small)
        self.lbl_profiles.pack(side="right")

        prow = tk.Frame(pbox, bg=T.bg_panel)
        prow.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Button(prow, text="☑ ВСЕ", width=8, style="Accent.TButton",
                   command=lambda: self._set_profiles(True)).pack(side="left", padx=2)
        ttk.Button(prow, text="☐ НИЧЕГО", width=10,
                   command=lambda: self._set_profiles(False)).pack(side="left", padx=2)
        ttk.Entry(prow, textvariable=self.var_profile_filter, font=T.mono,
                  width=18).pack(side="right", padx=2)

        self._profile_canvas = tk.Canvas(pbox, bg=T.bg_panel, highlightthickness=0)
        psb = ttk.Scrollbar(pbox, orient="vertical", command=self._profile_canvas.yview)
        self._profile_canvas.configure(yscrollcommand=psb.set)
        self._profile_inner = tk.Frame(self._profile_canvas, bg=T.bg_panel)
        self._profile_window = self._profile_canvas.create_window(
            (0, 0), window=self._profile_inner, anchor="nw")
        self._profile_inner.bind(
            "<Configure>",
            lambda e: self._profile_canvas.configure(
                scrollregion=self._profile_canvas.bbox("all")))
        self._profile_canvas.bind(
            "<Configure>",
            lambda e: self._profile_canvas.itemconfigure(self._profile_window,
                                                         width=e.width))
        self._profile_canvas.pack(fill="both", expand=True, padx=(10, 0), pady=(0, 8))
        psb.pack(side="right", fill="y", padx=(0, 10), pady=(0, 8))
        self._profile_canvas.bind("<Enter>", self._bind_profile_wheel)
        self._profile_canvas.bind("<Leave>", self._unbind_profile_wheel)
        self._render_profiles()

        rep_panel = RoundedPanel(self, radius=12, fill=T.bg_panel, outline=T.line,
                                 thickness=1, bg=T.bg, height=104)
        rep_panel.pack(fill="x", padx=16, pady=(6, 0))
        rep_box = rep_panel.inner
        self.txt_report = tk.Text(rep_box, height=5, bg=T.bg_panel, fg=T.cyan_soft,
                                  font=T.mono_small, relief="flat", bd=0, wrap="word",
                                  highlightthickness=0, insertbackground=T.cyan)
        rsb = ttk.Scrollbar(rep_box, orient="vertical", command=self.txt_report.yview)
        self.txt_report.configure(yscrollcommand=rsb.set)
        self.txt_report.pack(side="left", fill="both", expand=True)
        rsb.pack(side="right", fill="y")
        self.txt_report.insert("1.0", "Отметьте агентов и профили, затем «ИМПОРТ В АГЕНТОВ».")
        self.txt_report.configure(state="disabled")

        foot = tk.Frame(self, bg=T.bg)
        foot.pack(fill="x", padx=16, pady=(8, 12), side="bottom")
        ttk.Button(foot, text="ЗАКРЫТЬ", command=self.destroy).pack(side="right", padx=4)
        self.btn_import = ttk.Button(foot, text="ИМПОРТ В АГЕНТОВ",
                                     style="Accent.TButton", command=self._import)
        self.btn_import.pack(side="right", padx=4)
        ttk.Button(foot, text="ТОЛЬКО ОТЧЁТ (ПРОВЕРКА)",
                   command=lambda: self._import(dry_run=True)).pack(side="left", padx=4)

    def _bind_agent_wheel(self, _=None):
        self._agent_canvas.bind_all("<MouseWheel>", self._on_agent_wheel)

    def _unbind_agent_wheel(self, _=None):
        try:
            self._agent_canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

    def _on_agent_wheel(self, event):
        try:
            self._agent_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def _bind_profile_wheel(self, _=None):
        self._profile_canvas.bind_all("<MouseWheel>", self._on_profile_wheel)

    def _unbind_profile_wheel(self, _=None):
        try:
            self._profile_canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

    def _on_profile_wheel(self, event):
        try:
            self._profile_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def _render_agents(self):
        for child in list(self._agent_inner.winfo_children()):
            child.destroy()
        for item in self.catalog:
            var = self.agent_vars[item["id"]]
            row = tk.Frame(self._agent_inner, bg=T.bg_panel)
            row.pack(fill="x", pady=1)
            tk.Checkbutton(
                row, text=item["title"], variable=var, bg=T.bg_panel, fg=T.ink,
                selectcolor=T.bg_input, activebackground=T.bg_panel,
                activeforeground=T.cyan, font=T.mono_small, bd=0, anchor="w",
                highlightthickness=0, command=self._update_counts).pack(
                side="left", anchor="w")
            mark = "●" if item["exists"] else "○"
            color = T.green if item["exists"] else T.cyan_dim
            tk.Label(row, text=mark, bg=T.bg_panel, fg=color,
                     font=T.mono_small).pack(side="right", padx=(4, 2))
            desc = tk.Label(self._agent_inner, text=item["description"], bg=T.bg_panel,
                            fg=T.ink_dim, font=T.mono_small, anchor="w", justify="left",
                            wraplength=360)
            desc.pack(fill="x", padx=(24, 4))
            path = tk.Label(self._agent_inner, text=str(item["path"]), bg=T.bg_panel,
                            fg=T.cyan_dim, font=T.mono_small, anchor="w", justify="left",
                            wraplength=360)
            path.pack(fill="x", padx=(24, 4), pady=(0, 4))
        self._update_counts()

    def _render_profiles(self):
        for child in list(self._profile_inner.winfo_children()):
            child.destroy()
        needle = (self.var_profile_filter.get() or "").strip().lower()
        for profile in self.app.profiles:
            pid = profile["id"]
            text = "%s  (%s)" % (profile.get("display_name") or pid, pid)
            if needle and needle not in text.lower():
                continue
            var = self.profile_vars.get(pid)
            if var is None:
                var = tk.BooleanVar(master=self, value=True)
                self.profile_vars[pid] = var
            cb = tk.Checkbutton(
                self._profile_inner, text=text, variable=var, bg=T.bg_panel, fg=T.ink,
                selectcolor=T.bg_input, activebackground=T.bg_panel,
                activeforeground=T.cyan, font=T.mono_small, bd=0, anchor="w",
                highlightthickness=0, command=self._update_counts)
            cb.pack(fill="x", padx=4, pady=1)
            tk.Label(self._profile_inner, text=str(profile.get("base_url") or ""),
                     bg=T.bg_panel, fg=T.cyan_dim, font=T.mono_small,
                     anchor="w").pack(fill="x", padx=(24, 4))
        self._update_counts()

    def _update_counts(self):
        try:
            agents = [a for a in AGENT_IDS if self.agent_vars[a].get()]
            profiles = [p for p, v in self.profile_vars.items() if v.get()]
            self.lbl_agents.configure(text="ВЫБРАНО: %d / %d" % (len(agents), len(AGENT_IDS)))
            self.lbl_profiles.configure(
                text="ВЫБРАНО: %d / %d" % (len(profiles), len(self.app.profiles)))
        except Exception:
            pass

    def _set_agents(self, value):
        for var in self.agent_vars.values():
            var.set(value)
        self._update_counts()

    def _set_profiles(self, value):
        for var in self.profile_vars.values():
            var.set(value)
        self._update_counts()

    # --- импорт -----------------------------------------------------------
    def _selection(self):
        agents = [a for a in AGENT_IDS if self.agent_vars[a].get()]
        ids = [p for p, v in self.profile_vars.items() if v.get()]
        profiles = [p for p in self.app.profiles if p["id"] in ids]
        return agents, profiles

    def _import(self, dry_run=False):
        agents, profiles = self._selection()
        if not agents:
            messagebox.showinfo("Перенос", "Отметьте хотя бы одного агента", parent=self)
            return
        if not profiles:
            messagebox.showinfo("Перенос", "Отметьте хотя бы один профиль", parent=self)
            return
        save_agents_settings({
            "agents": agents,
            "profiles": [p["id"] for p in profiles],
        })
        if dry_run:
            plan = transfer_plan(
                profiles, self.app.var_default_model.get(), agents,
                home=self.home, config_path=str(self.app.config_path))
            lines = ["Проверка (файлы не изменяются):", ""]
            for res in plan:
                mark = "OK " if res.get("ok") else "ВНИМАНИЕ "
                lines.append("%s%s\n    %s\n    %s" % (
                    mark, res.get("title") or res.get("agent"),
                    str(res.get("path") or "—"), res.get("message") or ""))
            lines.append("")
            lines.append("Профилей: %d (моделей %d)" % (
                len(profiles), sum(len(p.get("models") or []) for p in profiles)))
            bad = [r for r in plan if not r.get("ok")]
            if bad:
                lines.append("Требуют внимания: %d из %d — перенос в них может не сработать"
                             % (len(bad), len(plan)))
            self._report("\n".join(lines))
            return
        self.btn_import.configure(state="disabled")
        try:
            results = transfer_profiles(
                profiles, self.app.var_default_model.get(), agents,
                home=self.home,
                config_path=self.app.config_path)
        finally:
            try:
                self.btn_import.configure(state="normal")
            except Exception:
                pass
        lines = []
        for res in results:
            mark = "OK " if res.get("ok") else "ОШИБКА "
            where = str(res.get("path") or "—")
            lines.append("%s%s\n    %s\n    %s" % (
                mark, res.get("title") or res.get("agent"), where, res.get("message") or ""))
        ok = sum(1 for r in results if r.get("ok"))
        header = "ГОТОВО: УСПЕШНО %d ИЗ %d" % (ok, len(results))
        if ok != len(results):
            header = "ЗАВЕРШЕНО С ОШИБКАМИ: УСПЕШНО %d ИЗ %d" % (ok, len(results))
        self._report(header + "\n\n" + "\n\n".join(lines))
        self._result = results
        self.app._set_status("ПЕРЕНОС В АГЕНТОВ: УСПЕШНО %d ИЗ %d" % (ok, len(results)))

    def _report(self, text):
        try:
            self.txt_report.configure(state="normal")
            self.txt_report.delete("1.0", "end")
            self.txt_report.insert("1.0", text)
            self.txt_report.configure(state="disabled")
            self.txt_report.see("1.0")
        except Exception:
            pass


class ToolsDialog(tk.Toplevel):
    """MCP-серверы и скиллы: что стоит сейчас и как поставить новое.

    Пишет только в opencode.json `self.app.config_path` (и, по галочкам,
    в файлы других агентов). Скиллы раскладываются в папку из ключа
    `skills` (по умолчанию ~/.config/opencode/skills).
    """

    def __init__(self, app, home=None):
        super().__init__(app.root)
        self.app = app
        self.home = home
        self.title("MCP И СКИЛЛЫ")
        self.geometry("960x780")
        self.minsize(820, 640)
        self.configure(bg=T.bg)
        self.transient(app.root)
        self.grab_set()

        self.var_source = tk.StringVar(master=self)
        self.var_overwrite = tk.BooleanVar(master=self, value=False)
        self.field_vars = {}
        self.server_checks = {}
        self.agent_files = {}
        self._result = None

        try:
            self.config = load_config(self.app.config_path)
        except Exception:
            self.config = {}
        self._build()
        try:
            app.clipboard.bind_tree(self)
        except Exception:
            pass
        self.bind("<Escape>", lambda e: self.destroy())

    # --- UI ---------------------------------------------------------------
    def _build(self):
        head = tk.Frame(self, bg=T.bg)
        head.pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(head, text="MCP И СКИЛЛЫ", bg=T.bg, fg=T.cyan,
                 font=T.mono_title).pack(anchor="w")
        tk.Label(head, text="Серверы инструментов и папки навыков для OpenCode и других агентов.",
                 bg=T.bg, fg=T.ink_dim, font=T.mono_small).pack(anchor="w", pady=(2, 0))
        ScanStrip(self, color=T.cyan).pack(fill="x", padx=16, pady=(6, 6))

        body = tk.Frame(self, bg=T.bg)
        body.pack(fill="both", expand=True, padx=16)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_mcp_panel(body)
        self._build_skills_panel(body)

        rep_panel = RoundedPanel(self, radius=12, fill=T.bg_panel, outline=T.line,
                                 thickness=1, bg=T.bg, height=118)
        rep_panel.pack(fill="x", padx=16, pady=(6, 0))
        rep_box = rep_panel.inner
        self.txt_report = tk.Text(rep_box, height=6, bg=T.bg_panel, fg=T.cyan_soft,
                                  font=T.mono_small, relief="flat", bd=0, wrap="word",
                                  highlightthickness=0, insertbackground=T.cyan)
        rsb = ttk.Scrollbar(rep_box, orient="vertical", command=self.txt_report.yview)
        self.txt_report.configure(yscrollcommand=rsb.set)
        self.txt_report.pack(side="left", fill="both", expand=True)
        rsb.pack(side="right", fill="y")
        self.txt_report.insert("1.0", "Выберите серверы или папку скиллов, затем нажмите кнопку.")
        self.txt_report.configure(state="disabled")

        foot = tk.Frame(self, bg=T.bg)
        foot.pack(fill="x", padx=16, pady=(8, 12), side="bottom")
        ttk.Button(foot, text="ЗАКРЫТЬ", command=self.destroy).pack(side="right", padx=4)
        self.btn_install = ttk.Button(foot, text="УСТАНОВИТЬ ВЫБРАННОЕ",
                                      style="Accent.TButton", command=self._install)
        self.btn_install.pack(side="right", padx=4)

    def _build_mcp_panel(self, body):
        panel = RoundedPanel(body, radius=16, fill=T.bg_panel, outline=T.cyan_dim,
                             thickness=1, bg=T.bg)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=2)
        box = panel.inner
        title = tk.Frame(box, bg=T.bg_panel)
        title.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(title, text="MCP-СЕРВЕРЫ", bg=T.bg_panel, fg=T.cyan,
                 font=T.mono_title).pack(side="left")

        installed = mcp_servers_from_config(self.config)
        self.installed_label = tk.Label(
            box, text="в конфиге сейчас: %s" % (", ".join(sorted(installed)) or "нет"),
            bg=T.bg_panel, fg=T.green, font=T.mono_small, anchor="w", justify="left",
            wraplength=380)
        self.installed_label.pack(fill="x", padx=10)

        canvas = tk.Canvas(box, bg=T.bg_panel, highlightthickness=0, height=420)
        sb = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        inner = tk.Frame(canvas, bg=T.bg_panel)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(6, 8))
        sb.pack(side="right", fill="y", padx=(0, 10), pady=(6, 8))
        canvas.bind("<Enter>", lambda _=None: canvas.bind_all(
            "<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)),
                                                         "units")))
        canvas.bind("<Leave>", lambda _=None: canvas.unbind_all("<MouseWheel>"))

        for item in MCP_CATALOG:
            row = tk.Frame(inner, bg=T.bg_panel)
            row.pack(fill="x", pady=(4, 0))
            var = tk.BooleanVar(master=self, value=(item["id"] in installed))
            self.server_checks[item["id"]] = var
            tk.Checkbutton(row, text=item["title"], variable=var, bg=T.bg_panel, fg=T.ink,
                           selectcolor=T.bg_input, activebackground=T.bg_panel,
                           activeforeground=T.cyan, font=T.mono_small, bd=0, anchor="w",
                           highlightthickness=0).pack(side="left", anchor="w")
            mark = "●" if item["id"] in installed else "○"
            tk.Label(row, text=mark, bg=T.bg_panel,
                     fg=T.green if item["id"] in installed else T.cyan_dim,
                     font=T.mono_small).pack(side="right", padx=(4, 2))
            tk.Label(inner, text=item["description"], bg=T.bg_panel, fg=T.ink_dim,
                     font=T.mono_small, anchor="w", justify="left",
                     wraplength=360).pack(fill="x", padx=(24, 4))
            for field in item.get("fields") or ():
                field_row = tk.Frame(inner, bg=T.bg_panel)
                field_row.pack(fill="x", padx=(24, 4), pady=(2, 0))
                tk.Label(field_row, text=field["label"], bg=T.bg_panel, fg=T.cyan_soft,
                         font=T.mono_small, width=19, anchor="w").pack(side="left")
                var_field = tk.StringVar(master=self)
                entry = ttk.Entry(field_row, textvariable=var_field, font=T.mono,
                                  width=26)
                if field.get("secret"):
                    entry.configure(show="*")
                entry.pack(side="left", fill="x", expand=True)
                self.field_vars[(item["id"], field["key"])] = var_field
            tk.Frame(inner, bg=T.line, height=1).pack(fill="x", padx=4, pady=(6, 0))

        tk.Label(box, text="Дополнительно записать в файлы других агентов:", bg=T.bg_panel,
                 fg=T.ink_dim, font=T.mono_small, anchor="w", justify="left",
                 wraplength=380).pack(fill="x", padx=10, pady=(0, 2))
        for agent_id, title_text, path_fn in MCP_AGENT_FILES:
            var = tk.BooleanVar(master=self, value=False)
            self.agent_files[agent_id] = var
            row = tk.Frame(box, bg=T.bg_panel)
            row.pack(fill="x", padx=10, anchor="w")
            tk.Checkbutton(row, text=str(path_fn(self.home)), variable=var,
                           bg=T.bg_panel, fg=T.cyan_soft, selectcolor=T.bg_input,
                           activebackground=T.bg_panel, activeforeground=T.cyan,
                           font=T.mono_small, bd=0, anchor="w",
                           highlightthickness=0).pack(side="left", anchor="w")

    def _build_skills_panel(self, body):
        panel = RoundedPanel(body, radius=16, fill=T.bg_panel, outline=T.cyan_dim,
                             thickness=1, bg=T.bg)
        panel.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=2)
        box = panel.inner
        title = tk.Frame(box, bg=T.bg_panel)
        title.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(title, text="СКИЛЛЫ", bg=T.bg_panel, fg=T.cyan,
                 font=T.mono_title).pack(side="left")
        base = skills_base_dir(self.config, self.home)
        self.skills_base = base
        tk.Label(box, text="папка: %s" % base, bg=T.bg_panel, fg=T.green,
                 font=T.mono_small, anchor="w", justify="left",
                 wraplength=380).pack(fill="x", padx=10)

        row = tk.Frame(box, bg=T.bg_panel)
        row.pack(fill="x", padx=10, pady=(6, 2))
        ttk.Entry(row, textvariable=self.var_source, font=T.mono,
                  width=26).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="…", width=3,
                   command=self._pick_source).pack(side="left", padx=2)
        ttk.Checkbutton(row, text="перезаписывать", variable=self.var_overwrite,
                        command=self._update_counts).pack(side="left", padx=4)
        ttk.Button(box, text="УСТАНОВИТЬ СКИЛЛЫ ИЗ ФАЙЛА/ПАПКИ",
                   style="Accent.TButton",
                   command=self._install_skills).pack(fill="x", padx=10, pady=(4, 4))
        ttk.Button(box, text="УДАЛИТЬ ВЫБРАННЫЕ СКИЛЛЫ",
                   command=self._remove_skills).pack(fill="x", padx=10, pady=(0, 6))

        self.skill_vars = {}
        canvas = tk.Canvas(box, bg=T.bg_panel, highlightthickness=0)
        sb = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        inner = tk.Frame(canvas, bg=T.bg_panel)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 8))
        sb.pack(side="right", fill="y", padx=(0, 10), pady=(0, 8))
        self._skill_inner = inner
        self._render_skills()

    def _skill_summary(self, count):
        if not count:
            return "не установлено ни одного навыка"
        return "установлено навыков: %d" % count

    def _render_skills(self):
        for child in list(self._skill_inner.winfo_children()):
            child.destroy()
        self.skill_vars = {}
        items = list_installed_skills(self.skills_base)
        tk.Label(self._skill_inner, text=self._skill_summary(len(items)),
                 bg=T.bg_panel, fg=T.green, font=T.mono_small,
                 anchor="w").pack(fill="x", pady=(0, 4))
        for item in items:
            var = tk.BooleanVar(master=self, value=False)
            self.skill_vars[item["name"]] = var
            tk.Checkbutton(self._skill_inner, text=item["name"], variable=var,
                           bg=T.bg_panel, fg=T.ink, selectcolor=T.bg_input,
                           activebackground=T.bg_panel, activeforeground=T.cyan,
                           font=T.mono_small, bd=0, anchor="w",
                           highlightthickness=0).pack(fill="x", padx=4, pady=(2, 0))
            description = (item.get("description") or "").strip()
            if description:
                tk.Label(self._skill_inner, text=description[:220], bg=T.bg_panel,
                         fg=T.ink_dim, font=T.mono_small, anchor="w", justify="left",
                         wraplength=360).pack(fill="x", padx=(24, 4))

    def _pick_source(self):
        choice = messagebox.askyesno(
            "Источник скиллов",
            "Да — выбрать папку со скиллами.\nНет — выбрать архив .zip / .tar.gz (/ .tgz).",
            parent=self)
        if choice:
            path = filedialog.askdirectory(parent=self, title="Папка со скиллами")
        else:
            path = filedialog.askopenfilename(
                parent=self, title="Архив скиллов",
                filetypes=[("Архивы", "*.zip *.tar.gz *.tgz *.tar"),
                           ("Все файлы", "*.*")])
        if path:
            self.var_source.set(path)

    def _update_counts(self):
        pass

    # --- действия ---------------------------------------------------------
    def _selected_servers(self):
        servers = {}
        errors = []
        for item in MCP_CATALOG:
            if not self.server_checks[item["id"]].get():
                continue
            values = {}
            for field in item.get("fields") or ():
                var = self.field_vars.get((item["id"], field["key"]))
                values[field["key"]] = var.get() if var is not None else ""
            try:
                servers[item["id"]] = mcp_server_entry(item, values)
            except ValueError as exc:
                errors.append("%s: %s" % (item["id"], exc))
        return servers, errors

    def _install(self):
        servers, errors = self._selected_servers()
        if errors:
            messagebox.showerror("MCP", "\n".join(errors), parent=self)
            return
        if not servers:
            messagebox.showinfo("MCP", "Отметьте хотя бы один сервер", parent=self)
            return
        agents = [a for a, v in self.agent_files.items() if v.get()]
        try:
            config = load_config(self.app.config_path)
        except Exception as exc:
            messagebox.showerror("MCP", "Конфиг не разбирается: %s" % exc, parent=self)
            return
        self.btn_install.configure(state="disabled")
        try:
            applied = apply_mcp_servers(config, servers)
            backup = save_config(self.app.config_path, applied["config"])
            results = [{
                "agent": "opencode", "title": "OpenCode (этот конфиг)", "ok": True,
                "path": self.app.config_path, "backup": backup,
                "message": "; ".join("%s: %s" % (name, ", ".join(changes) or "без изменений")
                                     for name, changes in applied["changes"].items()),
            }]
            if agents:
                results += install_mcp_servers(
                    servers, config_path=self.app.config_path, home=self.home,
                    mcp_agent_ids=agents)
            self.app.config = applied["config"]
        except Exception as exc:
            messagebox.showerror("MCP", "Не удалось записать: %s" % exc, parent=self)
            return
        finally:
            try:
                self.btn_install.configure(state="normal")
            except Exception:
                pass
        lines = ["MCP-СЕРВЕРЫ ЗАПИСАНЫ:%s" % ("" if not errors else " с ошибками")]
        lines.append("")
        lines += mcp_report_lines(results)
        lines.append("")
        lines.append("Перезапустите OpenCode, чтобы серверы поднялись.")
        self._report("\n".join(lines))
        self.config = load_config(self.app.config_path)
        installed = mcp_servers_from_config(self.config)
        self.installed_label.configure(
            text="в конфиге сейчас: %s" % (", ".join(sorted(installed)) or "нет"))
        ok = sum(1 for r in results if r.get("ok"))
        self.app._set_status("MCP: ЗАПИСАНО %d ИЗ %d" % (ok, len(results)))
        self._result = results

    def _install_skills(self):
        source = (self.var_source.get() or "").strip()
        if not source:
            messagebox.showinfo("Скиллы", "Укажите папку или архив со скиллами",
                                parent=self)
            return
        try:
            report = install_skills(source, base=self.skills_base,
                                    overwrite=self.var_overwrite.get(), home=self.home)
        except Exception as exc:
            messagebox.showerror("Скиллы", "Не удалось установить: %s" % exc, parent=self)
            return
        lines = ["СКИЛЛЫ"]
        lines.append("папка: %s" % report["base"])
        lines.append("установлено: %s" % (", ".join(report["installed"]) or "—"))
        if report["skipped"]:
            lines.append("пропущено (уже есть, без «перезаписывать»): %s"
                         % ", ".join(report["skipped"]))
        if report["errors"]:
            lines.append("ошибки: %s" % "; ".join(report["errors"]))
        lines.append("")
        lines.append("Чтобы OpenCode видел папку, в opencode.json: "
                     "\"skills\": %s" % json.dumps(skills_config_entry(
                         self.skills_base), ensure_ascii=False))
        self._report("\n".join(lines))
        self._render_skills()
        self.app._set_status("СКИЛЛЫ: УСТАНОВЛЕНО %d" % len(report["installed"]))
        self._result = report

    def _remove_skills(self):
        selected = [name for name, var in self.skill_vars.items() if var.get()]
        if not selected:
            messagebox.showinfo("Скиллы", "Отметьте, что удалить", parent=self)
            return
        if not messagebox.askyesno(
                "Скиллы", "Удалить безвозвратно: %s?" % ", ".join(selected), parent=self):
            return
        removed = [name for name in selected
                   if remove_skill(name, base=self.skills_base, home=self.home)]
        self._report("СКИЛЛЫ\nудалено: %s\nосталось: %d" % (
            ", ".join(removed) or "—", len(list_installed_skills(self.skills_base))))
        self._render_skills()

    def _report(self, text):
        try:
            self.txt_report.configure(state="normal")
            self.txt_report.delete("1.0", "end")
            self.txt_report.insert("1.0", text)
            self.txt_report.configure(state="disabled")
            self.txt_report.see("1.0")
        except Exception:
            pass


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
        # запуск с ключом --tray (автозагрузка): окно сразу свёрнуто в трей
        if started_minimized():
            try:
                self.root.withdraw()
            except Exception:
                pass

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
        ttk.Button(row2, text="ИМПОРТ В АГЕНТОВ…",
                   style="Accent.TButton",
                   command=self.open_agents_dialog).pack(side="left", padx=(12, 3))
        ttk.Button(row2, text="MCP И СКИЛЛЫ…",
                   command=self.open_tools_dialog).pack(side="left", padx=3)
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
        """Отпечаток сохраняемых данных.

        В подпись НЕ входят служебные поля (_balance, _balance_at, _raw и прочие
        с префиксом «_»): они заполняются в процессе работы, из-за них индикатор
        «есть несохранённые изменения» горел постоянно.
        """
        try:
            clean = [{"id": p.get("id"),
                      "display_name": p.get("display_name"),
                      "base_url": p.get("base_url"),
                      "api_key": p.get("api_key"),
                      "package": p.get("package"),
                      "models": list(p.get("models") or []),
                      "known_models": list(p.get("known_models") or []),
                      "model_capabilities": p.get("model_capabilities") or {},
                      "extra_settings": p.get("extra_settings") or {},
                      "coefficient": p.get("coefficient")}
                     for p in self.profiles]
            return json.dumps([self.config, clean], sort_keys=True,
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
            dirty = self._is_dirty()
            lbl.configure(text="● ЕСТЬ НЕСОХРАНЁННЫЕ ИЗМЕНЕНИЯ" if dirty else "")
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
            "model_capabilities": copy.deepcopy(res.get("model_capabilities") or {}),
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
    def _balance_targets(self):
        """Какие профили обновлять: выбранные в AOS или текущий."""
        aos = getattr(self, "aos", None)
        if aos is not None:
            try:
                chosen = aos._visible_profiles()
                if chosen:
                    return chosen
            except Exception:
                pass
        cur = self._find(self.selected) if self.selected else None
        return [cur] if cur else []

    def request_balance(self, silent=False, force=False):
        """Запрашивает баланс для всех выбранных профилей (последовательно, с паузами)."""
        if not hasattr(self, "_balance_results"):
            self._balance_results = queue.Queue()
        if getattr(self, "_balance_busy", False) and not force:
            return
        targets = self._balance_targets()
        if not targets:
            if not silent:
                messagebox.showinfo("Баланс", "Выберите профиль в списке", parent=self.root)
            return
        if not silent:
            try:
                self.lbl_balance_main.configure(text="ЗАГРУЗКА…", fg=T.ink_dim)
                self.lbl_balance_when.configure(text="запрос…")
                self.btn_balance_main.configure(state="disabled")
            except Exception:
                pass

        jobs = [(p["id"], p["base_url"], p["api_key"]) for p in targets]
        self._balance_busy = True
        self._balance_pending = len(jobs)

        def work():
            # последовательно с паузой между запросами: шлюз лимитирует частоту
            for idx, (pid, url, key) in enumerate(jobs):
                if idx:
                    time.sleep(1.2)
                try:
                    self._balance_results.put((pid, fetch_balance(url, key), None))
                except Exception as exc:
                    self._balance_results.put((pid, None, exc))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(120, self._poll_balance)

    def _poll_balance(self):
        """Разбирает очередь результатов; опрос идёт, пока не обработаны все."""
        try:
            pid, data, err = self._balance_results.get_nowait()
        except queue.Empty:
            if getattr(self, "_balance_pending", 0) <= 0:
                self._balance_busy = False
                try:
                    self.btn_balance_main.configure(state="normal")
                except Exception:
                    pass
            else:
                self.root.after(120, self._poll_balance)
            return

        self._balance_pending = max(0, getattr(self, "_balance_pending", 1) - 1)

        try:
            self._apply_balance_result(pid, data, err)
        except Exception:
            pass
        # продолжаем опрос, пока есть необработанные результаты
        if getattr(self, "_balance_pending", 0) > 0:
            self.root.after(80, self._poll_balance)
        else:
            self._balance_busy = False
            try:
                self.btn_balance_main.configure(state="normal")
            except Exception:
                pass

    def _apply_balance_result(self, pid, data, err):
        profile = self._find(pid)
        if profile is not None:
            if err is not None:
                profile["_balance"] = None
                profile["_balance_error"] = str(err)
                self._log_balance_error("%s: %s" % (pid, err))
            else:
                profile["_balance"] = data
                profile["_balance_error"] = None
                profile["_balance_at"] = datetime.now()

            # главное: обновляем AOS для КАЖДОГО профиля, а не только выбранного
            try:
                aos = getattr(self, "aos", None)
                if aos is not None and aos.win is not None and aos.win.winfo_exists():
                    aos.refresh()
            except Exception:
                pass

            try:
                self._refresh_dirty_marker()
            except Exception:
                pass

            if pid == self.selected:
                try:
                    if err is not None:
                        self.lbl_balance_main.configure(text="нет данных", fg=T.red)
                        self.lbl_balance_when.configure(text=str(err)[:70])
                    else:
                        self._show_balance(profile)
                except Exception:
                    pass

    def _log_balance_error(self, text):
        """Пишет ошибку баланса в файл рядом с aos.json — для диагностики."""
        try:
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
            d = base / "OpenCodeProviderManager"
            d.mkdir(parents=True, exist_ok=True)
            with open(d / "balance_error.log", "a", encoding="utf-8") as fh:
                fh.write("[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text))
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

    def toggle_aos_click_through(self):
        aos = self._aos()
        if aos is None:
            return
        on = aos.toggle_click_through()
        self._set_status("AOS: клики сквозь оверлей ВКЛ" if on
                         else "AOS: клики перехватываются оверлеем")

    def open_aos_settings(self):
        aos = self._aos()
        if aos is None:
            messagebox.showerror("AOS", "Не удалось создать оверлей", parent=self.root)
            return
        # если главное окно свёрнуто в трей — сначала показываем его,
        # иначе transient-диалог тоже остаётся невидимым
        try:
            if self.root.state() != "normal":
                self.root.deiconify()
            self.root.lift()
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass
        try:
            dlg = AOSSettingsDialog(self, aos)
            try:
                dlg.deiconify()
                dlg.lift()
                dlg.attributes("-topmost", True)
                dlg.after(300, lambda: dlg.attributes("-topmost", False))
                dlg.focus_force()
                dlg.update()
            except Exception:
                pass
        except Exception as exc:
            messagebox.showerror("AOS", "Не удалось открыть настройки:\n%s" % exc,
                                 parent=self.root)

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
            fixed = migrate_provider_keys(new_config)
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
        extra = ""
        if fixed:
            extra = ("\n\nИсправлен package у провайдеров с ключом sk-cvc-*: %s\n"
                     "(@ai-sdk/openai не передаёт ключ — OpenCode отвечал "
                     "«API key is required»)" % ", ".join(fixed))
        messagebox.showinfo(
            "Готово",
            "%s\n\nФайл: %s\n\nОткат: кнопка «ИСТОРИЯ И ОТКАТ…» или Ctrl+Z%s" % (
                msg, self.config_path, extra), parent=self.root)
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

    def open_agents_dialog(self):
        """Окно переноса профилей в ИИ-агентов."""
        if not self.profiles:
            messagebox.showinfo("Перенос в агентов",
                                "Список профилей пуст — сначала добавьте профиль",
                                parent=self.root)
            return
        dlg = AgentsDialog(self)
        self.root.wait_window(dlg)

    def open_tools_dialog(self):
        """Окно MCP-серверов и скиллов."""
        dlg = ToolsDialog(self)
        self.root.wait_window(dlg)

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


# ==========================================================================
# Автозагрузка в трее (реестр Windows Run)
# ==========================================================================

_AUTOSTART_KEY = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
_AUTOSTART_NAME = "OpenCodeProviderManager"


def _app_command_line():
    """Команда запуска приложения для автозагрузки (с ключом --tray)."""
    if getattr(sys, "frozen", False):
        return '"%s" --tray' % sys.executable
    script = Path(__file__).resolve()
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = pyw if pyw.exists() else Path(sys.executable)
    return '"%s" "%s" --tray' % (exe, script)


def autostart_enabled() -> bool:
    """Включена ли автозагрузка (запись в реестре существует)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _AUTOSTART_NAME)
            return bool(value)
    except Exception:
        return False


def set_autostart(enabled: bool) -> bool:
    """Включает/выключает автозагрузку приложения в трее."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _AUTOSTART_NAME, 0, winreg.REG_SZ,
                                  _app_command_line())
            else:
                try:
                    winreg.DeleteValue(key, _AUTOSTART_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def started_minimized() -> bool:
    """Запущено ли приложение с ключом --tray (сразу свёрнутым в трей)."""
    try:
        return "--tray" in sys.argv
    except Exception:
        return False

# ==========================================================================
# Защита от двойного запуска (именованный mutex Windows)
# ==========================================================================

_SINGLE_INSTANCE_HANDLE = None
_MUTEX_NAME = "Global\\OpenCodeProviderManager.SingleInstance"
_FIND_WINDOW_TITLE = "OpenCode — менеджер провайдеров"


def acquire_single_instance():
    """Пытается стать единственным экземпляром.

    Возвращает True, если это первый запуск; False — если приложение уже работает
    (тогда активируем существующее окно и выходим).
    """
    global _SINGLE_INSTANCE_HANDLE
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                          wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
        kernel32.GetLastError.restype = wintypes.DWORD
        last_error = int(kernel32.GetLastError())
        ERROR_ALREADY_EXISTS = 183
        if last_error == ERROR_ALREADY_EXISTS:
            if handle:
                kernel32.CloseHandle(handle)
            return False
        _SINGLE_INSTANCE_HANDLE = handle
        return True
    except Exception:
        # без WinAPI просто разрешаем запуск
        return True


def activate_existing_window():
    """Разворачивает окно уже запущенного экземпляра."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        hwnd = user32.FindWindowW(None, _FIND_WINDOW_TITLE)
        if not hwnd:
            return False
        SW_RESTORE = 9
        user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
        return True
    except Exception:
        return False


def notify_already_running():
    """Сообщает, что приложение уже запущено (без Tk — окна может не быть)."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, "Менеджер OpenCode уже запущен.\n\n"
                  "Окно приложения восстановлено.",
            "OpenCode — менеджер провайдеров", 0x40)  # MB_ICONINFORMATION
    except Exception:
        pass


def main():
    hide_console()
    # единственный экземпляр: второй запуск просто развернёт уже открытое окно
    if not acquire_single_instance():
        if not activate_existing_window():
            notify_already_running()
        return 0
    notes = ensure_dependencies()
    app = App()
    if notes:
        app._set_status("  •  ".join(notes))
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
